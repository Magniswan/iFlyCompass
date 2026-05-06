import re
import asyncio
import requests
from flask import jsonify, request, send_file
from flask_login import login_required
from . import bili_bp
from .download_service import (
    start_download, get_download_progress, get_all_downloads,
    is_video_cached, get_video_cache_path, get_cached_videos,
    delete_cached_video, get_video_info, QUALITY_MAP, DEFAULT_QUALITY
)

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
        if is_video_cached(bvid):
            return jsonify({'status': 'cached', 'message': '视频已缓存'})
        
        task = start_download(bvid)
        if task:
            return jsonify({'status': 'started', 'task': task.to_dict()})
        else:
            return jsonify({'status': 'cached', 'message': '视频已缓存'})
    except Exception as e:
        print(f'[Bili] 启动下载异常: {e}')
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
    return jsonify(get_cached_videos())


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
    if delete_cached_video(bvid):
        return jsonify({'success': True})
    return jsonify({'error': '视频不存在'}), 404


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
