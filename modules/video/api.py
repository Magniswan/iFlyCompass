import os
import mimetypes
from flask import jsonify, request, Response
from flask_login import login_required, current_user
from config import Config
from extensions import db
from models.video import VideoAccessControl, VideoAccessUser
from models.user import User
from . import video_bp

VIDEOS_DIR = os.path.join(Config.INSTANCE_DIR, 'videos') if not Config.VIDEOS_DIR else os.path.normpath(Config.VIDEOS_DIR)

VIDEO_EXTENSIONS = {'.mp4', '.webm', '.ogg', '.ogv', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.m4v', '.mpg', '.mpeg', '.ts'}

UNCATEGORIZED = '未分类'

def _ensure_videos_dir():
    if not os.path.exists(VIDEOS_DIR):
        os.makedirs(VIDEOS_DIR)

def _check_video_access(video_path, user):
    if user.is_admin or user.is_super_admin:
        return True

    acl = VideoAccessControl.query.filter_by(video_path=video_path).first()
    if not acl:
        return True

    if acl.mode == 'public':
        return True
    elif acl.mode == 'admin_only':
        return False
    elif acl.mode == 'whitelist':
        return VideoAccessUser.query.filter_by(video_path=video_path, user_id=user.id).first() is not None
    elif acl.mode == 'blacklist':
        return VideoAccessUser.query.filter_by(video_path=video_path, user_id=user.id).first() is None

    return True

def _get_video_access_info(video_path):
    acl = VideoAccessControl.query.filter_by(video_path=video_path).first()
    if not acl:
        return {'mode': 'public', 'users': []}

    users = VideoAccessUser.query.filter_by(video_path=video_path).all()
    user_list = []
    for u in users:
        user_obj = User.query.get(u.user_id)
        if user_obj:
            user_list.append({
                'id': user_obj.id,
                'username': user_obj.username,
                'nickname': user_obj.nickname or '',
                'display_name': user_obj.display_name
            })

    return {'mode': acl.mode, 'users': user_list}

def _get_video_files_categorized():
    _ensure_videos_dir()
    categories = {}
    try:
        for dirpath, dirnames, filenames in os.walk(VIDEOS_DIR):
            rel_dir = os.path.relpath(dirpath, VIDEOS_DIR)
            if rel_dir == '.':
                category_name = UNCATEGORIZED
            else:
                category_name = rel_dir.split(os.sep)[0]
                category_name = category_name.replace('\\', '/')

            for filename in filenames:
                ext = os.path.splitext(filename)[1].lower()
                if ext in VIDEO_EXTENSIONS:
                    filepath = os.path.join(dirpath, filename)
                    rel_path = os.path.relpath(filepath, VIDEOS_DIR).replace('\\', '/')
                    size = os.path.getsize(filepath)
                    if category_name not in categories:
                        categories[category_name] = []
                    categories[category_name].append({
                        'name': filename,
                        'path': rel_path,
                        'category': '' if category_name == UNCATEGORIZED else category_name,
                        'size': size,
                        'size_display': _format_size(size)
                    })
    except Exception as e:
        print(f"[Video] 扫描视频目录失败: {e}")

    is_admin = current_user.is_admin or current_user.is_super_admin

    result = []
    sorted_names = sorted(categories.keys(), key=lambda x: (x == UNCATEGORIZED, x.lower()))
    for name in sorted_names:
        videos = categories[name]
        videos.sort(key=lambda x: x['name'].lower())

        filtered = []
        for v in videos:
            if _check_video_access(v['path'], current_user):
                if is_admin:
                    v['access'] = _get_video_access_info(v['path'])
                filtered.append(v)

        if filtered:
            result.append({
                'name': name,
                'videos': filtered
            })
    return result

def _format_size(size):
    if size < 1024:
        return f"{size} B"
    elif size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    elif size < 1024 * 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    else:
        return f"{size / (1024 * 1024 * 1024):.2f} GB"

@video_bp.route('/api/videos')
@login_required
def list_videos():
    categories = _get_video_files_categorized()
    return jsonify(categories)

@video_bp.route('/api/video/<path:filepath>')
@login_required
def stream_video(filepath):
    safe_path = os.path.normpath(filepath).lstrip('/\\')
    full_path = os.path.join(VIDEOS_DIR, safe_path)
    real_full = os.path.realpath(full_path)
    real_videos = os.path.realpath(VIDEOS_DIR)

    if not real_full.startswith(real_videos + os.sep) and real_full != real_videos:
        return jsonify({'error': '非法路径'}), 403

    if not os.path.isfile(real_full):
        return jsonify({'error': '视频文件不存在'}), 404

    if not _check_video_access(safe_path, current_user):
        return jsonify({'error': '无权访问此视频'}), 403

    filename = os.path.basename(safe_path)

    file_size = os.path.getsize(real_full)
    mime_type, _ = mimetypes.guess_type(real_full)
    if not mime_type:
        ext = os.path.splitext(filename)[1].lower()
        mime_map = {
            '.mp4': 'video/mp4',
            '.webm': 'video/webm',
            '.ogg': 'video/ogg',
            '.ogv': 'video/ogg',
            '.mkv': 'video/x-matroska',
            '.avi': 'video/x-msvideo',
            '.mov': 'video/quicktime',
            '.wmv': 'video/x-ms-wmv',
            '.flv': 'video/x-flv',
            '.m4v': 'video/mp4',
            '.mpg': 'video/mpeg',
            '.mpeg': 'video/mpeg',
            '.ts': 'video/mp2t',
        }
        mime_type = mime_map.get(ext, 'application/octet-stream')

    range_header = request.headers.get('Range', None)

    if range_header:
        byte_range = range_header.replace('bytes=', '').split('-')
        start = int(byte_range[0]) if byte_range[0] else 0
        end = int(byte_range[1]) if len(byte_range) > 1 and byte_range[1] else file_size - 1

        if start >= file_size:
            return Response(status=416)

        end = min(end, file_size - 1)
        length = end - start + 1

        def generate():
            with open(real_full, 'rb') as f:
                f.seek(start)
                remaining = length
                chunk_size = 8192
                while remaining > 0:
                    chunk = f.read(min(chunk_size, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    yield chunk

        response = Response(generate(), 206, mimetype=mime_type,
                          direct_passthrough=True)
        response.headers.add('Content-Range', f'bytes {start}-{end}/{file_size}')
        response.headers.add('Accept-Ranges', 'bytes')
        response.headers.add('Content-Length', str(length))
        return response

    def generate():
        with open(real_full, 'rb') as f:
            while True:
                chunk = f.read(8192)
                if not chunk:
                    break
                yield chunk

    response = Response(generate(), 200, mimetype=mime_type,
                      direct_passthrough=True)
    response.headers.add('Accept-Ranges', 'bytes')
    response.headers.add('Content-Length', str(file_size))
    return response

@video_bp.route('/api/video/access/<path:video_path>', methods=['GET'])
@login_required
def get_video_access(video_path):
    if not (current_user.is_admin or current_user.is_super_admin):
        return jsonify({'error': '权限不足'}), 403

    info = _get_video_access_info(video_path)
    return jsonify(info)

@video_bp.route('/api/video/access/<path:video_path>', methods=['PUT'])
@login_required
def update_video_access(video_path):
    if not (current_user.is_admin or current_user.is_super_admin):
        return jsonify({'error': '权限不足'}), 403

    data = request.get_json()
    if not data:
        return jsonify({'error': '无效请求数据'}), 400

    mode = data.get('mode')
    if mode not in ('public', 'admin_only', 'whitelist', 'blacklist'):
        return jsonify({'error': '无效的访问模式'}), 400

    user_ids = data.get('users', [])

    acl = VideoAccessControl.query.filter_by(video_path=video_path).first()
    if acl:
        acl.mode = mode
        acl.updated_at = db.func.now()
    else:
        acl = VideoAccessControl(
            video_path=video_path,
            mode=mode,
            created_by=current_user.id
        )
        db.session.add(acl)
    db.session.commit()

    VideoAccessUser.query.filter_by(video_path=video_path).delete()
    db.session.commit()

    for uid in user_ids:
        existing = VideoAccessUser.query.filter_by(video_path=video_path, user_id=uid).first()
        if not existing:
            db.session.add(VideoAccessUser(video_path=video_path, user_id=uid))
    db.session.commit()

    return jsonify({'message': '访问控制更新成功', 'mode': mode})

@video_bp.route('/api/video/access/users/search')
@login_required
def search_users_for_access():
    if not (current_user.is_admin or current_user.is_super_admin):
        return jsonify({'error': '权限不足'}), 403

    keyword = request.args.get('keyword', '')
    query = User.query
    if keyword:
        query = query.filter(
            db.or_(
                User.username.contains(keyword),
                User.nickname.contains(keyword)
            )
        )
    users = query.limit(20).all()
    return jsonify([{
        'id': u.id,
        'username': u.username,
        'nickname': u.nickname or '',
        'display_name': u.display_name
    } for u in users])
