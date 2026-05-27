import os
from datetime import datetime
from flask import jsonify, request
from flask_login import login_required
from config import Config
from . import md_bp

MD_DIR = os.path.join(Config.INSTANCE_DIR, 'md')
MAX_FILE_SIZE = 1024 * 1024  # 1MB
INVALID_CHARS = set('/\\:*?"<>|')


def _validate_path(rel_path):
    """验证路径安全，确保在 instance/md/ 范围内"""
    if not rel_path:
        return MD_DIR, None
    
    # 检查路径穿越
    parts = rel_path.replace('\\', '/').split('/')
    if '..' in parts:
        return None, '非法路径'
    
    # 检查非法字符
    for char in rel_path:
        if char in INVALID_CHARS:
            return None, f'路径包含非法字符: {char}'
    
    full_path = os.path.abspath(os.path.join(MD_DIR, rel_path))
    if not full_path.startswith(os.path.abspath(MD_DIR)):
        return None, '路径超出允许范围'
    
    return full_path, None


def _get_file_preview(file_path):
    """获取文件内容预览（前80字符）"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read(200)
        preview = content.replace('\n', ' ')[:80]
        return preview + ('...' if len(content) > 80 else '')
    except Exception:
        return ''


def _get_items(rel_path=''):
    """获取指定目录下的文件和文件夹列表"""
    full_path, error = _validate_path(rel_path)
    if error:
        return None, error
    
    if not os.path.exists(full_path):
        return None, '目录不存在'
    
    items = []
    try:
        for name in sorted(os.listdir(full_path)):
            item_path = os.path.join(full_path, name)
            rel_item_path = os.path.join(rel_path, name).replace('\\', '/')
            
            if os.path.isdir(item_path):
                items.append({
                    'name': name,
                    'type': 'folder',
                    'item_count': len(os.listdir(item_path)),
                    'path': rel_item_path
                })
            elif name.endswith('.md'):
                stat = os.stat(item_path)
                items.append({
                    'name': name,
                    'type': 'file',
                    'size': stat.st_size,
                    'modified': datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    'preview': _get_file_preview(item_path),
                    'path': rel_item_path
                })
    except Exception as e:
        return None, str(e)
    
    return items, None


@md_bp.route('/api/md/files', methods=['GET'])
@login_required
def get_files():
    path = request.args.get('path', '').replace('/', os.sep)
    items, error = _get_items(path)
    if error:
        return jsonify({'error': error}), 400
    return jsonify({'path': path.replace(os.sep, '/'), 'items': items})


@md_bp.route('/api/md/file', methods=['GET'])
@login_required
def get_file():
    rel_path = request.args.get('path', '').replace('/', os.sep)
    if not rel_path:
        return jsonify({'error': '未指定文件路径'}), 400
    
    full_path, error = _validate_path(rel_path)
    if error:
        return jsonify({'error': error}), 400
    
    if not os.path.exists(full_path):
        return jsonify({'error': '文件不存在'}), 404
    
    if os.path.getsize(full_path) > MAX_FILE_SIZE:
        return jsonify({'error': '文件过大，最大支持 1MB'}), 400
    
    try:
        with open(full_path, 'r', encoding='utf-8') as f:
            content = f.read()
        stat = os.stat(full_path)
        return jsonify({
            'name': os.path.basename(full_path),
            'path': rel_path.replace(os.sep, '/'),
            'content': content,
            'size': stat.st_size,
            'modified': datetime.fromtimestamp(stat.st_mtime).isoformat()
        })
    except Exception as e:
        return jsonify({'error': f'读取失败: {str(e)}'}), 500


@md_bp.route('/api/md/file', methods=['POST'])
@login_required
def save_file():
    data = request.get_json()
    if not data or 'path' not in data:
        return jsonify({'error': '缺少路径参数'}), 400
    
    rel_path = data['path'].replace('/', os.sep)
    action = data.get('action', 'save')
    content = data.get('content', '')
    
    full_path, error = _validate_path(rel_path)
    if error:
        return jsonify({'error': error}), 400
    
    # 确保父目录存在
    parent_dir = os.path.dirname(full_path)
    if parent_dir and not os.path.exists(parent_dir):
        os.makedirs(parent_dir, exist_ok=True)
    
    if action == 'create':
        if os.path.exists(full_path):
            return jsonify({'error': '文件已存在'}), 409
    
    if len(content.encode('utf-8')) > MAX_FILE_SIZE:
        return jsonify({'error': '文件内容过大，最大支持 1MB'}), 400
    
    try:
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(content)
        stat = os.stat(full_path)
        return jsonify({
            'success': True,
            'message': '保存成功',
            'modified': datetime.fromtimestamp(stat.st_mtime).isoformat()
        })
    except Exception as e:
        return jsonify({'error': f'保存失败: {str(e)}'}), 500


@md_bp.route('/api/md/folder', methods=['POST'])
@login_required
def create_folder():
    data = request.get_json()
    if not data or 'path' not in data:
        return jsonify({'error': '缺少路径参数'}), 400
    
    rel_path = data['path'].replace('/', os.sep)
    full_path, error = _validate_path(rel_path)
    if error:
        return jsonify({'error': error}), 400
    
    if os.path.exists(full_path):
        return jsonify({'error': '文件夹已存在'}), 409
    
    try:
        os.makedirs(full_path, exist_ok=True)
        return jsonify({'success': True, 'message': '创建成功'})
    except Exception as e:
        return jsonify({'error': f'创建失败: {str(e)}'}), 500


@md_bp.route('/api/md/file', methods=['DELETE'])
@login_required
def delete_file():
    rel_path = request.args.get('path', '').replace('/', os.sep)
    if not rel_path:
        return jsonify({'error': '未指定路径'}), 400
    
    full_path, error = _validate_path(rel_path)
    if error:
        return jsonify({'error': error}), 400
    
    if not os.path.exists(full_path):
        return jsonify({'error': '文件或文件夹不存在'}), 404
    
    try:
        if os.path.isdir(full_path):
            # 检查是否为空文件夹
            if os.listdir(full_path):
                return jsonify({'error': '文件夹非空，请先删除内部文件'}), 400
            os.rmdir(full_path)
        else:
            os.remove(full_path)
        return jsonify({'success': True, 'message': '删除成功'})
    except Exception as e:
        return jsonify({'error': f'删除失败: {str(e)}'}), 500


@md_bp.route('/api/md/file', methods=['PUT'])
@login_required
def rename_file():
    data = request.get_json()
    if not data or 'old_path' not in data or 'new_path' not in data:
        return jsonify({'error': '缺少路径参数'}), 400
    
    old_rel = data['old_path'].replace('/', os.sep)
    new_rel = data['new_path'].replace('/', os.sep)
    
    old_full, error = _validate_path(old_rel)
    if error:
        return jsonify({'error': error}), 400
    
    new_full, error = _validate_path(new_rel)
    if error:
        return jsonify({'error': error}), 400
    
    if not os.path.exists(old_full):
        return jsonify({'error': '原文件不存在'}), 404
    
    if os.path.exists(new_full):
        return jsonify({'error': '目标名称已存在'}), 409
    
    # 确保新路径的父目录存在
    new_parent = os.path.dirname(new_full)
    if new_parent and not os.path.exists(new_parent):
        os.makedirs(new_parent, exist_ok=True)
    
    try:
        os.rename(old_full, new_full)
        return jsonify({'success': True, 'message': '重命名成功'})
    except Exception as e:
        return jsonify({'error': f'重命名失败: {str(e)}'}), 500
