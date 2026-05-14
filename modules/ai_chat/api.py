import json
import requests
import threading
import re
from datetime import datetime, timezone
from flask import jsonify, request, Response, stream_with_context
from flask_login import login_required, current_user
from config import get_config, save_config, encrypt_value, decrypt_value
from extensions import db
from models.ai_chat import AiConversation, AiMessage
from . import ai_chat_bp

# Cache for auto-fetched models: {base_url: (models_list, timestamp)}
_models_cache = {}
_models_cache_lock = threading.Lock()
MODELS_CACHE_TTL = 3600

# In-memory current conversation tracking
_current_conv = {}

DEFAULT_MODELS = [
    {"id": "deepseek-chat", "name": "DeepSeek-V3", "description": "通用对话模型"},
    {"id": "deepseek-reasoner", "name": "DeepSeek-R1", "description": "深度推理模型，支持思考"},
]


def _get_base_url(api_url):
    """Extract base URL from full API endpoint URL."""
    url = api_url.rstrip('/')
    for suffix in ['/v1/chat/completions', '/chat/completions']:
        if url.endswith(suffix):
            return url[:-len(suffix)]
    return url


def _normalize_api_url(url):
    url = url.strip().rstrip('/')
    if not url:
        return 'https://api.deepseek.com/v1/chat/completions'
    if '/chat/completions' in url:
        return url
    return url + '/v1/chat/completions'


def _get_api_config():
    config = get_config()
    ai_config = config.get('ai', {})
    raw_url = ai_config.get('api_url', 'https://api.deepseek.com/v1/chat/completions')
    raw_key = ai_config.get('api_key', '')
    if raw_key and not raw_key.startswith('enc:'):
        encrypted = encrypt_value(raw_key)
        if 'ai' not in config:
            config['ai'] = {}
        config['ai']['api_key'] = encrypted
        save_config(config)
    return {
        'api_url': _normalize_api_url(raw_url),
        'api_key': decrypt_value(raw_key) if raw_key else '',
        'model': ai_config.get('model', 'deepseek-chat'),
        'max_tokens': ai_config.get('max_tokens', 2048),
        'temperature': ai_config.get('temperature', 0.7),
        'system_prompt': ai_config.get('system_prompt', '你是一个有用的AI助手，请用中文回答用户的问题。'),
        'reasoning_effort': ai_config.get('reasoning_effort', None),
        'thinking_enabled': ai_config.get('thinking_enabled', False),
    }


def _save_api_config(key, value):
    config = get_config()
    if 'ai' not in config:
        config['ai'] = {}
    config['ai'][key] = value
    save_config(config)


def _fetch_models_from_api(config):
    """Auto-fetch models from the API provider's /v1/models endpoint."""
    base_url = _get_base_url(config['api_url'])
    models_url = base_url + '/v1/models'
    with _models_cache_lock:
        cached = _models_cache.get(base_url)
        if cached and (datetime.now().timestamp() - cached[1]) < MODELS_CACHE_TTL:
            return cached[0]
    try:
        headers = {'Authorization': f'Bearer {config["api_key"]}'}
        resp = requests.get(models_url, headers=headers, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            models = []
            skip_kw = ['embedding', 'moderation', 'whisper', 'tts', 'dall-e', 'dalle']
            for m in data.get('data', []):
                mid = m.get('id', '')
                if any(x in mid for x in skip_kw):
                    continue
                models.append({'id': mid, 'name': mid, 'description': m.get('owned_by', 'API 模型')})
            if models:
                with _models_cache_lock:
                    _models_cache[base_url] = (models, datetime.now().timestamp())
                return models
    except Exception:
        pass
    ai_config = get_config().get('ai', {})
    return ai_config.get('models', DEFAULT_MODELS)


def _get_models():
    config = _get_api_config()
    if not config['api_key']:
        ai_config = get_config().get('ai', {})
        return ai_config.get('models', DEFAULT_MODELS)
    return _fetch_models_from_api(config)


def _build_payload(config, messages, stream=False, model_override=None,
                   enable_thinking=False):
    model = model_override or config['model']
    payload = {
        'model': model, 'messages': messages,
        'max_tokens': config['max_tokens'], 'temperature': config['temperature']
    }
    if stream:
        payload['stream'] = True
    # Per-request toggle takes priority; only enable thinking when user explicitly toggles it on
    if enable_thinking:
        payload['thinking'] = {'type': 'enabled'}
        payload['reasoning_effort'] = config.get('reasoning_effort') or 'high'
    return payload


def _web_search(query, max_results=5):
    """Perform web search using Bing search engine."""
    try:
        resp = requests.get('https://www.bing.com/search',
                            params={'q': query, 'setlang': 'zh-Hans'},
                            timeout=15,
                            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'})
        if resp.status_code != 200:
            print(f"[AI Search] Bing 返回 {resp.status_code}")
            return None

        html = resp.text
        results = []

        # Bing search result blocks are in <li class="b_algo">
        # Title: <h2><a href="...">title</a></h2>
        # Snippet: <p> or <div class="b_caption">...<p>snippet</p>
        algo_pattern = re.compile(r'<li[^>]*class="b_algo"[^>]*>(.*?)</li>', re.DOTALL | re.IGNORECASE)
        title_pattern = re.compile(r'<h2[^>]*><a[^>]*href="([^"]*)"[^>]*>(.*?)</a></h2>', re.DOTALL | re.IGNORECASE)
        snippet_pattern = re.compile(r'<p[^>]*>(.*?)</p>', re.DOTALL | re.IGNORECASE)

        blocks = algo_pattern.findall(html)
        for block in blocks[:max_results]:
            title_match = title_pattern.search(block)
            if not title_match:
                continue
            url = title_match.group(1)
            title = re.sub(r'<[^>]+>', '', title_match.group(2)).strip()
            if not title:
                continue
            snippet = ''
            snippet_match = snippet_pattern.search(block)
            if snippet_match:
                snippet = re.sub(r'<[^>]+>', '', snippet_match.group(1)).strip()
            entry = f"- {title}"
            if snippet:
                entry += f": {snippet}"
            if url:
                entry += f" (来源: {url})"
            results.append(entry)

        if results:
            return '\n'.join(results)

        print("[AI Search] Bing 未解析到结果")
        return None
    except requests.exceptions.Timeout:
        print("[AI Search] Bing 搜索超时")
        return None
    except Exception as e:
        print(f"[AI Search] Bing 搜索失败: {e}")
        return None


def _auto_title(content):
    title = content[:30].replace('\n', ' ').strip()
    return title if title else '新对话'


def _save_msg(conv_id, role, content):
    if not conv_id:
        return
    msg = AiMessage(conversation_id=conv_id, role=role, content=content)
    db.session.add(msg)
    db.session.commit()


def _get_or_create_conv(user_id, model=None):
    conv_id = _current_conv.get(user_id)
    if conv_id:
        conv = AiConversation.query.filter_by(id=conv_id, user_id=user_id).first()
        if conv:
            return conv
    conv = AiConversation(user_id=user_id, title='新对话',
                          model=model or _get_api_config()['model'])
    db.session.add(conv)
    db.session.commit()
    _current_conv[user_id] = conv.id
    return conv


# ─── Models ───

@ai_chat_bp.route('/api/ai-chat/models', methods=['GET'])
@login_required
def get_models():
    models = _get_models()
    config = _get_api_config()
    return jsonify({'models': models, 'current_model': config['model']})


@ai_chat_bp.route('/api/ai-chat/models/refresh', methods=['POST'])
@login_required
def refresh_models():
    with _models_cache_lock:
        _models_cache.clear()
    models = _get_models()
    return jsonify({'models': models})


# ─── Conversations ───

@ai_chat_bp.route('/api/ai-chat/conversations', methods=['GET'])
@login_required
def list_conversations():
    convs = (AiConversation.query
             .filter_by(user_id=current_user.id)
             .order_by(AiConversation.updated_at.desc()).all())
    return jsonify({'conversations': [c.to_dict() for c in convs]})


@ai_chat_bp.route('/api/ai-chat/conversations', methods=['POST'])
@login_required
def create_conversation():
    data = request.json or {}
    conv = AiConversation(
        user_id=current_user.id,
        title=data.get('title', '新对话'),
        model=data.get('model', _get_api_config()['model']))
    db.session.add(conv)
    db.session.commit()
    _current_conv[current_user.id] = conv.id
    return jsonify({'success': True, 'conversation': conv.to_dict()})


@ai_chat_bp.route('/api/ai-chat/conversations/<int:conv_id>', methods=['GET'])
@login_required
def get_conversation(conv_id):
    conv = AiConversation.query.filter_by(id=conv_id, user_id=current_user.id).first()
    if not conv:
        return jsonify({'error': '对话不存在'}), 404
    _current_conv[current_user.id] = conv.id
    messages = [m.to_dict() for m in conv.messages.all()]
    return jsonify({'conversation': conv.to_dict(), 'messages': messages})


@ai_chat_bp.route('/api/ai-chat/conversations/<int:conv_id>', methods=['PUT'])
@login_required
def update_conversation(conv_id):
    conv = AiConversation.query.filter_by(id=conv_id, user_id=current_user.id).first()
    if not conv:
        return jsonify({'error': '对话不存在'}), 404
    data = request.json or {}
    if 'title' in data:
        conv.title = data['title']
    if 'model' in data:
        conv.model = data['model']
    conv.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    return jsonify({'success': True, 'conversation': conv.to_dict()})


@ai_chat_bp.route('/api/ai-chat/conversations/<int:conv_id>', methods=['DELETE'])
@login_required
def delete_conversation(conv_id):
    conv = AiConversation.query.filter_by(id=conv_id, user_id=current_user.id).first()
    if not conv:
        return jsonify({'error': '对话不存在'}), 404
    db.session.delete(conv)
    db.session.commit()
    if _current_conv.get(current_user.id) == conv_id:
        _current_conv.pop(current_user.id, None)
    return jsonify({'success': True})


@ai_chat_bp.route('/api/ai-chat/history', methods=['GET'])
@login_required
def load_history():
    conv_id = _current_conv.get(current_user.id)
    if conv_id:
        conv = AiConversation.query.filter_by(id=conv_id, user_id=current_user.id).first()
        if conv:
            messages = [m.to_dict() for m in conv.messages.all()]
            return jsonify({'success': True, 'history': messages})
    return jsonify({'success': True, 'history': []})


@ai_chat_bp.route('/api/ai-chat/history', methods=['DELETE'])
@login_required
def clear_history():
    conv_id = _current_conv.get(current_user.id)
    if conv_id:
        conv = AiConversation.query.filter_by(id=conv_id, user_id=current_user.id).first()
        if conv:
            db.session.delete(conv)
            db.session.commit()
    _current_conv.pop(current_user.id, None)
    return jsonify({'success': True})


# ─── Config ───

@ai_chat_bp.route('/api/ai-chat/config', methods=['GET'])
@login_required
def get_ai_config():
    if not (current_user.is_admin or current_user.is_super_admin):
        return jsonify({'error': '权限不足'}), 403
    config = _get_api_config()
    api_key = config['api_key']
    if api_key and len(api_key) > 8:
        masked_key = api_key[:4] + '*' * (len(api_key) - 8) + api_key[-4:]
    elif api_key:
        masked_key = api_key[:2] + '****'
    else:
        masked_key = ''
    return jsonify({
        'api_url': config['api_url'], 'api_key_masked': masked_key,
        'has_api_key': bool(api_key), 'model': config['model'],
        'max_tokens': config['max_tokens'], 'temperature': config['temperature'],
        'system_prompt': config['system_prompt'],
        'reasoning_effort': config['reasoning_effort'],
        'thinking_enabled': config['thinking_enabled'],
    })


@ai_chat_bp.route('/api/ai-chat/config', methods=['PUT'])
@login_required
def update_ai_config():
    if not (current_user.is_admin or current_user.is_super_admin):
        return jsonify({'error': '权限不足'}), 403
    data = request.json
    if 'api_key' in data and data['api_key']:
        key = data['api_key'].strip()
        if key and not key.startswith('****') and '*' not in key:
            _save_api_config('api_key', encrypt_value(key))
    for field in ['api_url', 'model', 'system_prompt']:
        if field in data and data[field]:
            _save_api_config(field, data[field].strip())
    if 'max_tokens' in data:
        try:
            mt = int(data['max_tokens'])
            if 100 <= mt <= 16384:
                _save_api_config('max_tokens', mt)
        except (ValueError, TypeError):
            pass
    if 'temperature' in data:
        try:
            temp = float(data['temperature'])
            if 0.0 <= temp <= 2.0:
                _save_api_config('temperature', temp)
        except (ValueError, TypeError):
            pass
    if 'reasoning_effort' in data:
        re_val = data['reasoning_effort']
        if re_val is None or re_val in ('low', 'medium', 'high'):
            _save_api_config('reasoning_effort', re_val)
    if 'thinking_enabled' in data:
        _save_api_config('thinking_enabled', bool(data['thinking_enabled']))
    with _models_cache_lock:
        _models_cache.clear()
    return jsonify({'success': True, 'message': 'AI配置已保存'})


# ─── Send ───

@ai_chat_bp.route('/api/ai-chat/send', methods=['POST'])
@login_required
def send_message():
    data = request.json
    message = data.get('message', '').strip()
    model_override = data.get('model')
    enable_search = data.get('enable_search', False)
    enable_thinking = data.get('enable_thinking', False)
    conv_id_param = data.get('conversation_id')

    if not message:
        return jsonify({'error': '消息不能为空'}), 400
    if len(message) > 4000:
        return jsonify({'error': '消息过长，请限制在4000字以内'}), 400

    config = _get_api_config()
    if not config['api_key']:
        return jsonify({'error': 'AI API Key 未配置'}), 400

    if conv_id_param:
        conv = AiConversation.query.filter_by(id=conv_id_param, user_id=current_user.id).first()
        if not conv:
            return jsonify({'error': '对话不存在'}), 404
        _current_conv[current_user.id] = conv.id
    else:
        conv = _get_or_create_conv(current_user.id, model_override)

    if conv.title == '新对话':
        conv.title = _auto_title(message)
    if model_override:
        conv.model = model_override
    conv.updated_at = datetime.now(timezone.utc)
    db.session.commit()

    _save_msg(conv.id, 'user', message)

    db_messages = conv.messages.order_by(AiMessage.created_at.asc()).all()
    system_content = config['system_prompt']
    if enable_search:
        sr = _web_search(message)
        if sr:
            system_content += f'\n\n[联网搜索结果]\n{sr}\n\n请基于以上搜索结果回答用户问题，并在回答中引用相关来源。'

    messages = [{"role": "system", "content": system_content}]
    max_pairs = 20
    recent = db_messages[-(max_pairs * 2):]
    messages.extend([{"role": m.role, "content": m.content} for m in recent])

    try:
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {config["api_key"]}'
        }
        payload = _build_payload(config, messages,
                                 model_override=model_override,
                                 enable_thinking=enable_thinking)
        resp = requests.post(config['api_url'], headers=headers, json=payload, timeout=120)

        if resp.status_code != 200:
            error_detail = resp.text
            try:
                ej = resp.json()
                if 'error' in ej:
                    error_detail = ej['error'].get('message', resp.text)
            except Exception:
                pass
            if resp.status_code == 404:
                error_detail = f'{error_detail}。请检查 API URL 配置是否正确（通常应包含 /v1/chat/completions 路径）'
            return jsonify({'error': f'AI API 错误 ({resp.status_code}): {error_detail}'}), 502

        result = resp.json()
        assistant_message = result['choices'][0]['message']['content']
        _save_msg(conv.id, 'assistant', assistant_message)

        usage = result.get('usage', {})
        return jsonify({
            'success': True, 'conversation_id': conv.id,
            'message': assistant_message,
            'usage': {
                'prompt_tokens': usage.get('prompt_tokens', 0),
                'completion_tokens': usage.get('completion_tokens', 0),
                'total_tokens': usage.get('total_tokens', 0)
            }
        })
    except requests.exceptions.Timeout:
        return jsonify({'error': 'AI API 请求超时'}), 504
    except requests.exceptions.ConnectionError:
        return jsonify({'error': '无法连接到 AI API 服务器'}), 502
    except Exception as e:
        return jsonify({'error': f'请求失败: {str(e)}'}), 500


@ai_chat_bp.route('/api/ai-chat/stream', methods=['POST'])
@login_required
def send_message_stream():
    data = request.json
    message = data.get('message', '').strip()
    model_override = data.get('model')
    enable_search = data.get('enable_search', False)
    enable_thinking = data.get('enable_thinking', False)
    conv_id_param = data.get('conversation_id')

    if not message:
        return jsonify({'error': '消息不能为空'}), 400
    if len(message) > 4000:
        return jsonify({'error': '消息过长'}), 400

    config = _get_api_config()
    if not config['api_key']:
        return jsonify({'error': 'AI API Key 未配置'}), 400

    if conv_id_param:
        conv = AiConversation.query.filter_by(id=conv_id_param, user_id=current_user.id).first()
        if not conv:
            return jsonify({'error': '对话不存在'}), 404
        _current_conv[current_user.id] = conv.id
    else:
        conv = _get_or_create_conv(current_user.id, model_override)

    if conv.title == '新对话':
        conv.title = _auto_title(message)
    if model_override:
        conv.model = model_override
    conv.updated_at = datetime.now(timezone.utc)
    db.session.commit()

    _save_msg(conv.id, 'user', message)

    db_messages = conv.messages.order_by(AiMessage.created_at.asc()).all()
    system_content = config['system_prompt']
    if enable_search:
        sr = _web_search(message)
        if sr:
            system_content += f'\n\n[联网搜索结果]\n{sr}\n\n请基于以上搜索结果回答用户问题，并在回答中引用相关来源。'

    messages = [{"role": "system", "content": system_content}]
    max_pairs = 20
    recent = db_messages[-(max_pairs * 2):]
    messages.extend([{"role": m.role, "content": m.content} for m in recent])

    def generate():
        full_response = ""
        try:
            headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {config["api_key"]}'
            }
            payload = _build_payload(config, messages, stream=True,
                                     model_override=model_override,
                                     enable_thinking=enable_thinking)
            resp = requests.post(config['api_url'], headers=headers, json=payload,
                                 timeout=120, stream=True)

            if resp.status_code != 200:
                error_detail = resp.text
                try:
                    ej = resp.json()
                    if 'error' in ej:
                        error_detail = ej['error'].get('message', resp.text)
                except Exception:
                    pass
                if resp.status_code == 404:
                    error_detail = f'{error_detail}。请检查 API URL 配置是否正确'
                yield f"data: {json.dumps({'error': f'AI API 错误 ({resp.status_code}): {error_detail}'})}\n\n"
                return

            for line in resp.iter_lines():
                if line:
                    line = line.decode('utf-8')
                    if line.startswith('data: '):
                        ds = line[6:]
                        if ds == '[DONE]':
                            break
                        try:
                            chunk = json.loads(ds)
                            if 'choices' in chunk and chunk['choices']:
                                delta = chunk['choices'][0].get('delta', {})
                                content = delta.get('content', '')
                                reasoning = delta.get('reasoning_content', '')
                                if reasoning:
                                    full_response += reasoning
                                    yield f"data: {json.dumps({'reasoning_content': reasoning})}\n\n"
                                if content:
                                    full_response += content
                                    yield f"data: {json.dumps({'content': content})}\n\n"
                            if 'usage' in chunk:
                                yield f"data: {json.dumps({'usage': chunk['usage']})}\n\n"
                        except json.JSONDecodeError:
                            continue
            yield f"data: {json.dumps({'done': True, 'conversation_id': conv.id})}\n\n"
        except requests.exceptions.Timeout:
            yield f"data: {json.dumps({'error': 'AI API 请求超时'})}\n\n"
        except requests.exceptions.ConnectionError:
            yield f"data: {json.dumps({'error': '无法连接到 AI API 服务器'})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': f'请求失败: {str(e)}'})}\n\n"
        if full_response:
            _save_msg(conv.id, 'assistant', full_response)

    return Response(stream_with_context(generate()), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})
