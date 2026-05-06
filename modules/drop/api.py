from flask import jsonify, request
from flask_login import login_required, current_user
from datetime import datetime, timezone, timedelta
from extensions import db
from models.drop import DropMessage, DropSettings, DropBlacklist
from models.user import User
from . import drop_bp

GLOBAL_COOLDOWN_SECONDS = 60
USER_COOLDOWN_SECONDS = 600

def get_user_drop_settings(user_id):
    settings = DropSettings.query.filter_by(user_id=user_id).first()
    if not settings:
        settings = DropSettings(user_id=user_id, enabled=True)
        db.session.add(settings)
        db.session.commit()
    return settings

def is_user_in_blacklist(user_id, sender_id):
    return DropBlacklist.query.filter_by(user_id=user_id, blocked_user_id=sender_id).first() is not None

def get_global_cooldown_remaining():
    last_drop = DropMessage.query.order_by(DropMessage.created_at.desc()).first()
    if not last_drop:
        return 0
    
    now = datetime.now(timezone.utc)
    if last_drop.created_at.tzinfo is None:
        last_drop.created_at = last_drop.created_at.replace(tzinfo=timezone.utc)
    
    elapsed = (now - last_drop.created_at).total_seconds()
    remaining = GLOBAL_COOLDOWN_SECONDS - elapsed
    return max(0, int(remaining))

def get_user_cooldown_remaining(user_id):
    settings = get_user_drop_settings(user_id)
    if not settings.last_drop_at:
        return 0
    
    now = datetime.now(timezone.utc)
    if settings.last_drop_at.tzinfo is None:
        settings.last_drop_at = settings.last_drop_at.replace(tzinfo=timezone.utc)
    
    elapsed = (now - settings.last_drop_at).total_seconds()
    remaining = USER_COOLDOWN_SECONDS - elapsed
    return max(0, int(remaining))

@drop_bp.route('/api/drop/send', methods=['POST'])
@login_required
def send_drop():
    global_cooldown = get_global_cooldown_remaining()
    if global_cooldown > 0:
        return jsonify({
            'error': '全服冷却中',
            'cooldown': global_cooldown
        }), 429
    
    user_cooldown = get_user_cooldown_remaining(current_user.id)
    if user_cooldown > 0:
        return jsonify({
            'error': '个人冷却中',
            'cooldown': user_cooldown
        }), 429
    
    data = request.json
    content = data.get('content', '').strip()
    
    if not content:
        return jsonify({'error': '消息内容不能为空'}), 400
    
    if len(content) > 200:
        return jsonify({'error': '消息内容不能超过200字'}), 400
    
    display_name = current_user.display_name
    
    drop = DropMessage(
        sender_id=current_user.id,
        sender_name=display_name,
        content=content
    )
    db.session.add(drop)
    
    settings = get_user_drop_settings(current_user.id)
    settings.last_drop_at = datetime.now(timezone.utc)
    
    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': 'Drop 发送成功',
        'drop': {
            'id': drop.id,
            'sender_name': drop.sender_name,
            'content': drop.content,
            'created_at': drop.created_at.strftime('%Y-%m-%d %H:%M:%S')
        }
    })

@drop_bp.route('/api/drop/poll', methods=['GET'])
@login_required
def poll_drop():
    settings = get_user_drop_settings(current_user.id)
    
    if not settings.enabled:
        return jsonify({'enabled': False, 'drops': []})
    
    last_id = request.args.get('last_id', 0, type=int)
    
    drops = DropMessage.query.filter(
        DropMessage.id > last_id,
        DropMessage.sender_id != current_user.id
    ).order_by(DropMessage.id.desc()).limit(5).all()
    
    result = []
    for drop in reversed(drops):
        if not is_user_in_blacklist(current_user.id, drop.sender_id):
            result.append({
                'id': drop.id,
                'sender_name': drop.sender_name,
                'sender_id': drop.sender_id,
                'content': drop.content,
                'created_at': drop.created_at.strftime('%Y-%m-%d %H:%M:%S')
            })
    
    return jsonify({
        'enabled': True,
        'drops': result,
        'last_id': drops[0].id if drops else last_id
    })

@drop_bp.route('/api/drop/status', methods=['GET'])
@login_required
def get_drop_status():
    global_cooldown = get_global_cooldown_remaining()
    user_cooldown = get_user_cooldown_remaining(current_user.id)
    
    return jsonify({
        'global_cooldown': global_cooldown,
        'user_cooldown': user_cooldown,
        'can_send': global_cooldown == 0 and user_cooldown == 0
    })

@drop_bp.route('/api/drop/settings', methods=['GET', 'PUT'])
@login_required
def drop_settings_api():
    settings = get_user_drop_settings(current_user.id)
    
    if request.method == 'GET':
        blacklist = DropBlacklist.query.filter_by(user_id=current_user.id).all()
        blocked_users = []
        for item in blacklist:
            user = User.query.get(item.blocked_user_id)
            if user:
                blocked_users.append({
                    'id': user.id,
                    'username': user.username,
                    'display_name': user.display_name
                })
        
        return jsonify({
            'enabled': settings.enabled,
            'blocked_users': blocked_users
        })
    
    elif request.method == 'PUT':
        data = request.json
        
        if 'enabled' in data:
            settings.enabled = bool(data['enabled'])
        
        db.session.commit()
        return jsonify({'success': True})

@drop_bp.route('/api/drop/blacklist', methods=['POST', 'DELETE'])
@login_required
def manage_blacklist():
    if request.method == 'POST':
        data = request.json
        blocked_user_id = data.get('user_id')
        
        if not blocked_user_id:
            return jsonify({'error': '缺少用户ID'}), 400
        
        if blocked_user_id == current_user.id:
            return jsonify({'error': '不能屏蔽自己'}), 400
        
        existing = DropBlacklist.query.filter_by(
            user_id=current_user.id,
            blocked_user_id=blocked_user_id
        ).first()
        
        if existing:
            return jsonify({'error': '该用户已在黑名单中'}), 400
        
        blacklist = DropBlacklist(
            user_id=current_user.id,
            blocked_user_id=blocked_user_id
        )
        db.session.add(blacklist)
        db.session.commit()
        
        user = User.query.get(blocked_user_id)
        return jsonify({
            'success': True,
            'blocked_user': {
                'id': user.id,
                'username': user.username,
                'display_name': user.display_name
            }
        })
    
    elif request.method == 'DELETE':
        data = request.json
        blocked_user_id = data.get('user_id')
        
        if not blocked_user_id:
            return jsonify({'error': '缺少用户ID'}), 400
        
        blacklist = DropBlacklist.query.filter_by(
            user_id=current_user.id,
            blocked_user_id=blocked_user_id
        ).first()
        
        if not blacklist:
            return jsonify({'error': '该用户不在黑名单中'}), 404
        
        db.session.delete(blacklist)
        db.session.commit()
        
        return jsonify({'success': True})

@drop_bp.route('/api/drop/users/search', methods=['GET'])
@login_required
def search_users():
    keyword = request.args.get('keyword', '').strip()
    
    if not keyword:
        return jsonify([])
    
    users = User.query.filter(
        User.id != current_user.id,
        db.or_(
            User.username.contains(keyword),
            User.nickname.contains(keyword)
        )
    ).limit(10).all()
    
    return jsonify([{
        'id': user.id,
        'username': user.username,
        'display_name': user.display_name
    } for user in users])
