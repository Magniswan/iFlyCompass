import re
import asyncio
from datetime import datetime, timezone
import requests
from flask import jsonify, request, send_file
from flask_login import login_required, current_user
from . import bili_bp
from .download_service import (
    start_download, get_download_progress, get_all_downloads,
    is_video_cached, get_video_cache_path, get_cached_videos,
    delete_cached_video, get_video_info, QUALITY_MAP, DEFAULT_QUALITY,
    cleanup_cache, start_cache_cleanup_scheduler
)
from models.bili_video import BiliVideoUser
from extensions import db

try:
    from bilibili_api import select_client
    select_client("curl_cffi")
except Exception as e:
    print(f'[Bili] 无法选择 curl_cffi: {e}')

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Referer': 'https://www.bilibili.com/',
}


def run_async(coro):
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


@bili_bp.route('/api/bili/recommend')
@login_required
def get_recommend():
    try:
        page = request.args.get('page', 1, type=int)
        ps = request.args.get('ps', 10, type=int)
        
        from bilibili_api import rank
        from bilibili_api.rank import RankType
        
        async def _get_rank():
            data = await rank.get_rank(type_=RankType.All)
            return data
        
        data = run_async(_get_rank())
        
        all_videos = []
        for item in data.get('list', []):
            all_videos.append({
                'bvid': item.get('bvid', ''),
                'title': item.get('title', ''),
                'cover': item.get('pic', ''),
                'author': item.get('owner', {}).get('name', '') if item.get('owner') else '',
                'mid': item.get('owner', {}).get('mid', 0) if item.get('owner') else 0,
                'play': item.get('stat', {}).get('view', 0) if item.get('stat') else 0,
                'danmaku': item.get('stat', {}).get('danmaku', 0) if item.get('stat') else 0,
                'duration': item.get('duration', 0),
                'duration_display': format_duration(item.get('duration', 0)),
                'cached': is_video_cached(item.get('bvid', ''))
            })
        
        start = (page - 1) * ps
        end = start + ps
        videos = all_videos[start:end]
        
        return jsonify(videos)
    except Exception as e:
        print(f'[Bili] 获取推荐异常: {e}')
        return jsonify({'error': str(e)}), 500


@bili_bp.route('/api/bili/search')
@login_required
def search_video():
    try:
        keyword = request.args.get('keyword', '')
        page = request.args.get('page', 1, type=int)
        ps = request.args.get('ps', 10, type=int)
        
        if not keyword:
            return jsonify([])
        
        from bilibili_api import search
        
        async def _search():
            result = await search.search_by_type(keyword, search_type=search.SearchObjectType.VIDEO, page=page)
            return result
        
        data = run_async(_search())
        
        videos = []
        for item in data.get('result', [])[:ps]:
            cover = item.get('pic', '')
            if cover.startswith('//'):
                cover = 'https:' + cover
            
            videos.append({
                'bvid': item.get('bvid', ''),
                'title': clean_html(item.get('title', '')),
                'cover': cover,
                'author': item.get('author', ''),
                'mid': item.get('mid', 0),
                'play': item.get('play', 0),
                'danmaku': item.get('video_review', 0),
                'duration': parse_duration(item.get('duration', '')),
                'duration_display': item.get('duration', '0:00'),
                'cached': is_video_cached(item.get('bvid', ''))
            })
        
        return jsonify(videos)
    except Exception as e:
        print(f'[Bili] 搜索异常: {e}')
        import traceback
        traceback.print_exc()
        return jsonify([])


@bili_bp.route('/api/bili/search_user')
@login_required
def search_user():
    try:
        keyword = request.args.get('keyword', '')
        page = request.args.get('page', 1, type=int)
        ps = request.args.get('ps', 10, type=int)
        
        if not keyword:
            return jsonify([])
        
        from bilibili_api import search
        
        async def _search():
            result = await search.search_by_type(keyword, search_type=search.SearchObjectType.USER, page=page)
            return result
        
        data = run_async(_search())
        
        users = []
        for item in data.get('result', [])[:ps]:
            avatar = item.get('upic', '')
            if avatar.startswith('//'):
                avatar = 'https:' + avatar
            
            users.append({
                'mid': item.get('mid', 0),
                'uname': item.get('uname', ''),
                'avatar': avatar,
                'fans': item.get('fans', 0),
                'videos': item.get('videos', 0),
                'sign': item.get('usign', ''),
                'level': item.get('level', 0),
                'is_up': item.get('is_up', 0) == 1
            })
        
        return jsonify(users)
    except Exception as e:
        print(f'[Bili] 搜索用户异常: {e}')
        import traceback
        traceback.print_exc()
        return jsonify([])


@bili_bp.route('/api/bili/user_videos/<int:mid>')
@login_required
def get_user_videos(mid):
    try:
        page = request.args.get('page', 1, type=int)
        ps = request.args.get('ps', 10, type=int)
        
        from bilibili_api import user
        
        async def _get_videos():
            u = user.User(mid)
            result = await u.get_videos()
            return result
        
        data = run_async(_get_videos())
        
        videos = []
        vlist = data.get('list', {}).get('vlist', [])
        
        start = (page - 1) * ps
        end = start + ps
        paginated_list = vlist[start:end]
        
        for item in paginated_list:
            videos.append({
                'bvid': item.get('bvid', ''),
                'title': item.get('title', ''),
                'cover': item.get('pic', ''),
                'author': item.get('author', ''),
                'play': item.get('play', 0),
                'duration': item.get('length', 0),
                'duration_display': item.get('length', '0:00'),
                'created': item.get('created', 0),
                'cached': is_video_cached(item.get('bvid', ''))
            })
        
        return jsonify(videos)
    except Exception as e:
        print(f'[Bili] 获取用户视频异常: {e}')
        import traceback
        traceback.print_exc()
        return jsonify([])


@bili_bp.route('/api/bili/video/<bvid>')
@login_required
def get_video_detail(bvid):
    try:
        info = get_video_info(bvid)
        
        pages = []
        for p in info.get('pages', []):
            pages.append({
                'cid': p.get('cid'),
                'page': p.get('page', 1),
                'part': p.get('part', ''),
                'duration': p.get('duration', 0),
                'duration_display': format_duration(p.get('duration', 0))
            })
        
        return jsonify({
            'bvid': info.get('bvid'),
            'aid': info.get('aid'),
            'title': info.get('title'),
            'cover': info.get('pic'),
            'desc': info.get('desc'),
            'author': info.get('owner', {}).get('name'),
            'mid': info.get('owner', {}).get('mid'),
            'duration': info.get('duration'),
            'duration_display': format_duration(info.get('duration', 0)),
            'view': info.get('stat', {}).get('view', 0),
            'danmaku': info.get('stat', {}).get('danmaku', 0),
            'like': info.get('stat', {}).get('like', 0),
            'coin': info.get('stat', {}).get('coin', 0),
            'pages': pages,
            'cached': is_video_cached(bvid),
            'quality': QUALITY_MAP.get(DEFAULT_QUALITY, '480P')
        })
    except Exception as e:
        print(f'[Bili] 获取视频详情异常: {e}')
        return jsonify({'error': str(e)}), 500


@bili_bp.route('/api/bili/download/<bvid>', methods=['POST'])
@login_required
def download_video(bvid):
    try:
        # 检查视频文件是否已缓存
        file_cached = is_video_cached(bvid)

        # 检查用户是否已添加该视频到列表
        existing_record = BiliVideoUser.query.filter_by(
            bvid=bvid,
            user_id=current_user.id
        ).first()

        if existing_record:
            # 用户已有该视频，直接返回成功
            return jsonify({
                'status': 'exists_in_list',
                'message': '视频已在您的缓存列表中',
                'file_cached': file_cached
            })

        if file_cached:
            # 文件已缓存但用户没有记录，添加用户记录
            new_record = BiliVideoUser(
                bvid=bvid,
                user_id=current_user.id,
                added_at=datetime.now(timezone.utc)
            )
            db.session.add(new_record)
            db.session.commit()

            return jsonify({
                'status': 'added_to_list',
                'message': '视频已添加到您的缓存列表'
            })

        # 文件未缓存，需要下载
        data = request.get_json(silent=True) or {}
        reencode = data.get('reencode', current_user.bili_reencode)
        task = start_download(bvid, reencode=reencode)
        if task:
            # 创建用户记录（标记为下载中）
            new_record = BiliVideoUser(
                bvid=bvid,
                user_id=current_user.id,
                added_at=datetime.now(timezone.utc)
            )
            db.session.add(new_record)
            db.session.commit()

            return jsonify({'status': 'started', 'task': task.to_dict()})
        else:
            return jsonify({'status': 'cached', 'message': '视频已缓存'})
    except Exception as e:
        print(f'[Bili] 启动下载异常: {e}')
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@bili_bp.route('/api/bili/settings', methods=['GET', 'PUT'])
@login_required
def bili_settings():
    if request.method == 'GET':
        return jsonify({
            'reencode': current_user.bili_reencode
        })
    try:
        data = request.get_json(silent=True) or {}
        reencode = data.get('reencode')
        if reencode is not None:
            current_user.bili_reencode = bool(reencode)
            db.session.commit()
        return jsonify({'success': True, 'reencode': current_user.bili_reencode})
    except Exception as e:
        print(f'[Bili] 保存设置异常: {e}')
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@bili_bp.route('/api/bili/progress/<bvid>')
@login_required
def get_progress(bvid):
    progress = get_download_progress(bvid)
    if progress:
        return jsonify(progress)
    elif is_video_cached(bvid):
        return jsonify({'status': 'completed', 'progress': 100})
    else:
        return jsonify({'status': 'not_found'})


@bili_bp.route('/api/bili/downloads')
@login_required
def list_downloads():
    return jsonify(get_all_downloads())


@bili_bp.route('/api/bili/cached')
@login_required
def list_cached():
    try:
        # 获取当前用户的视频列表
        user_videos = BiliVideoUser.query.filter_by(user_id=current_user.id).all()
        user_bvids = [uv.bvid for uv in user_videos]
        
        # 获取所有缓存视频的状态
        all_cached = get_cached_videos()
        
        # 过滤出用户有权限访问的视频，并添加额外信息
        result = []
        for video in all_cached:
            if video['bvid'] in user_bvids:
                # 找到对应的用户记录
                uv = next((u for u in user_videos if u.bvid == video['bvid']), None)
                if uv:
                    video['added_at'] = uv.added_at.isoformat() if uv.added_at else None
                    video['last_watched_at'] = uv.last_watched_at.isoformat() if uv.last_watched_at else None
                
                result.append(video)
        
        return jsonify(result)
    except Exception as e:
        print(f'[Bili] 获取缓存列表异常: {e}')
        import traceback
        traceback.print_exc()
        return jsonify([])


@bili_bp.route('/api/bili/cached_titles', methods=['POST'])
@login_required
def get_cached_titles():
    try:
        data = request.get_json()
        bvids = data.get('bvids', [])
        
        titles = {}
        for bvid in bvids:
            try:
                info = get_video_info(bvid)
                titles[bvid] = info.get('title', bvid)
            except Exception as e:
                print(f'[Bili] 获取视频标题失败 {bvid}: {e}')
                titles[bvid] = bvid
        
        return jsonify(titles)
    except Exception as e:
        print(f'[Bili] 获取缓存视频标题异常: {e}')
        return jsonify({'error': str(e)}), 500


@bili_bp.route('/api/bili/delete/<bvid>', methods=['DELETE'])
@login_required
def delete_video(bvid):
    try:
        # 查找用户的记录
        user_record = BiliVideoUser.query.filter_by(
            bvid=bvid,
            user_id=current_user.id
        ).first()
        
        if not user_record:
            return jsonify({'error': '视频不在您的缓存列表中'}), 404
        
        # 删除用户的记录
        db.session.delete(user_record)
        
        # 检查是否还有其他用户引用该视频
        other_users_count = BiliVideoUser.query.filter(
            BiliVideoUser.bvid == bvid,
            BiliVideoUser.user_id != current_user.id
        ).count()
        
        if other_users_count == 0:
            # 没有其他用户使用，可以删除物理文件
            file_deleted = delete_cached_video(bvid)
            if not file_deleted:
                return jsonify({'error': '视频文件删除失败'}), 500
            
            db.session.commit()
            return jsonify({
                'success': True,
                'message': '已从您的缓存列表中移除，视频文件已删除'
            })
        else:
            # 还有其他用户在使用，只删除记录，保留文件
            db.session.commit()
            return jsonify({
                'success': True,
                'message': f'已从您的缓存列表中移除（仍有 {other_users_count} 位用户使用该视频）',
                'other_users_count': other_users_count
            })
            
    except Exception as e:
        print(f'[Bili] 删除视频异常: {e}')
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@bili_bp.route('/api/bili/play/<bvid>')
@login_required
def play_video(bvid):
    if not is_video_cached(bvid):
        return jsonify({'error': '视频未缓存'}), 404
    
    path = get_video_cache_path(bvid)
    return send_file(path, mimetype='video/mp4')


@bili_bp.route('/api/bili/cover')
@login_required
def proxy_cover():
    url = request.args.get('url', '')
    if not url:
        return jsonify({'error': '缺少url参数'}), 400
    
    if not url.startswith('http'):
        url = 'https:' + url
    
    try:
        headers = HEADERS.copy()
        headers['Referer'] = 'https://www.bilibili.com/'
        
        resp = requests.get(url, headers=headers, timeout=10, stream=True)
        
        from flask import Response
        content_type = resp.headers.get('Content-Type', 'image/jpeg')
        
        def generate():
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    yield chunk
        
        return Response(generate(), mimetype=content_type, direct_passthrough=True)
    except Exception as e:
        print(f"[Bili] 封面代理失败: {e}")
        return jsonify({'error': str(e)}), 500


@bili_bp.route('/api/bili/cache/cleanup', methods=['POST'])
@login_required
def trigger_cache_cleanup():
    """Manually trigger cache cleanup."""
    result = cleanup_cache()
    return jsonify({'success': True, **result})


@bili_bp.route('/api/bili/cache/stats', methods=['GET'])
@login_required
def cache_stats():
    """Get cache statistics."""
    cached = get_cached_videos()
    total_size = sum(c.get('size', 0) for c in cached)
    return jsonify({
        'file_count': len(cached),
        'total_size': total_size,
        'total_size_display': format_size(total_size) if 'format_size' in dir() else f'{total_size / (1024*1024):.1f} MB',
        'max_size_mb': 10240,
        'max_age_days': 30
    })


def format_duration(seconds):
    if not seconds:
        return '0:00'
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f'{h}:{m:02d}:{s:02d}'
    return f'{m}:{s:02d}'


def parse_duration(duration_str):
    if not duration_str:
        return 0
    parts = duration_str.split(':')
    if len(parts) == 2:
        return int(parts[0]) * 60 + int(parts[1])
    elif len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    return 0


def clean_html(text):
    return re.sub(r'<[^>]+>', '', text).replace('<em class="keyword">', '').replace('</em>', '')
