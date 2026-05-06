from flask import jsonify, request, send_file
from . import ncm_bp
from utils.music_cache import get_cached_music, cache_music, cache_cover
from utils.ncm_api import ncm_client

@ncm_bp.route('/api/ncm/search', methods=['GET'])
def api_search():
    keywords = request.args.get('keywords', '')
    limit = request.args.get('limit', 30, type=int)
    offset = request.args.get('offset', 0, type=int)
    search_type = request.args.get('type', 1, type=int)
    
    print(f"[NCM] 搜索请求: keywords={keywords}, limit={limit}, offset={offset}, type={search_type}")
    
    result = ncm_client.search(keywords, limit, offset, search_type)
    
    if result.get('code') == 200:
        song_count = len(result.get('result', {}).get('songs', []))
        print(f"[NCM] 搜索成功, 返回 {song_count} 首歌曲")
    else:
        print(f"[NCM] 搜索失败: {result}")
    
    return jsonify(result)

@ncm_bp.route('/api/ncm/song/url', methods=['GET'])
def api_song_url():
    song_id = request.args.get('id', '')
    print(f"[NCM] 获取歌曲URL请求: song_id={song_id}")
    
    result = ncm_client.get_song_url(song_id)
    
    if result.get('code') == 200 and result.get('data'):
        url = result['data'][0].get('url', 'N/A') if result['data'] else 'N/A'
        if url and url != 'N/A':
            print(f"[NCM] 获取歌曲URL成功: {url[:60]}...")
        else:
            print(f"[NCM] 获取歌曲URL失败: 无URL")
    else:
        print(f"[NCM] 获取歌曲URL失败: {result}")
    
    return jsonify(result)

@ncm_bp.route('/api/ncm/song/detail', methods=['GET'])
def api_song_detail():
    ids = request.args.get('ids', '')
    print(f"[NCM] 获取歌曲详情请求: ids={ids}")
    
    result = ncm_client.get_song_detail(ids)
    print(f"[NCM] 歌曲详情响应: code={result.get('code')}")
    
    return jsonify(result)

@ncm_bp.route('/api/ncm/personalized', methods=['GET'])
def api_personalized():
    limit = request.args.get('limit', 30, type=int)
    print(f"[NCM] 获取推荐歌单请求: limit={limit}")
    
    result = ncm_client.get_personalized(limit)
    
    if result.get('code') == 200:
        count = len(result.get('result', []))
        print(f"[NCM] 推荐歌单获取成功, 数量: {count}")
    else:
        print(f"[NCM] 推荐歌单获取失败: {result}")
    
    return jsonify(result)

@ncm_bp.route('/api/ncm/lyric', methods=['GET'])
def api_lyric():
    song_id = request.args.get('id', '')
    print(f"[NCM] 获取歌词请求: song_id={song_id}")
    
    result = ncm_client.get_lyric(song_id)
    print(f"[NCM] 歌词响应: code={result.get('code')}")
    
    return jsonify(result)

@ncm_bp.route('/api/ncm/playlist/detail', methods=['GET'])
def api_playlist_detail():
    playlist_id = request.args.get('id', '')
    print(f"[NCM] 获取歌单详情请求: playlist_id={playlist_id}")
    
    result = ncm_client.get_playlist_detail(playlist_id)
    
    if result.get('code') == 200 and result.get('playlist'):
        track_count = len(result['playlist'].get('tracks', []))
        print(f"[NCM] 歌单详情获取成功, 歌曲数量: {track_count}")
    else:
        print(f"[NCM] 歌单详情获取失败: {result}")
    
    return jsonify(result)

@ncm_bp.route('/api/ncm/hot-search', methods=['GET'])
def api_hot_search():
    print("[NCM] 获取热搜列表请求")
    
    result = ncm_client.get_hot_search()
    
    if result.get('code') == 200:
        count = len(result.get('data', []))
        print(f"[NCM] 热搜列表获取成功, 数量: {count}")
    else:
        print(f"[NCM] 热搜列表获取失败: {result}")
    
    return jsonify(result)

@ncm_bp.route('/api/ncm/cache-music', methods=['POST'])
def api_cache_music():
    data = request.get_json()
    song_id = data.get('id')
    song_url = data.get('url')
    song_name = data.get('name', 'unknown')
    
    print(f"[NCM] 缓存音乐请求: id={song_id}, name={song_name}")
    if song_url:
        print(f"[NCM] 音乐URL: {song_url[:80]}...")
    else:
        print("[NCM] 音乐URL: None")
    
    if not song_id or not song_url:
        print("[NCM] 缓存失败: 缺少参数")
        return jsonify({'success': False, 'error': '缺少参数'})
    
    cached_path = cache_music(song_id, song_url, song_name)
    
    if cached_path:
        print(f"[NCM] 缓存成功: {cached_path}")
        return jsonify({'success': True, 'path': cached_path})
    else:
        print("[NCM] 缓存失败: 下载或保存失败")
        return jsonify({'success': False, 'error': '缓存失败'})

@ncm_bp.route('/api/ncm/cached-music/<int:song_id>', methods=['GET'])
def api_get_cached_music(song_id):
    print(f"[NCM] 检查缓存: song_id={song_id}")
    
    cached_path = get_cached_music(song_id)
    if cached_path:
        print(f"[NCM] 缓存命中: {cached_path}")
        return jsonify({'success': True, 'path': cached_path})
    else:
        print("[NCM] 缓存未命中")
        return jsonify({'success': False, 'error': '未缓存'})

@ncm_bp.route('/music/<filename>', methods=['GET'])
def serve_music(filename):
    print(f"[NCM] 提供音乐文件: {filename}")
    music_dir = 'temp/music'
    return send_file(f'{music_dir}/{filename}')

@ncm_bp.route('/api/ncm/cache-cover', methods=['POST'])
def api_cache_cover():
    data = request.get_json()
    pic_url = data.get('url')
    
    print(f"[NCM] 缓存封面请求: {pic_url[:60] if pic_url else 'None'}...")
    
    if not pic_url:
        print("[NCM] 缓存封面失败: 缺少URL")
        return jsonify({'success': False, 'error': '缺少URL'})
    
    cached_url = cache_cover(pic_url)
    
    if cached_url:
        print(f"[NCM] 封面缓存成功: {cached_url}")
        return jsonify({'success': True, 'url': cached_url})
    else:
        print("[NCM] 封面缓存失败")
        return jsonify({'success': False, 'error': '缓存失败'})

@ncm_bp.route('/api/ncm/cache-covers', methods=['POST'])
def api_cache_covers():
    data = request.get_json()
    urls = data.get('urls', [])
    
    print(f"[NCM] 批量缓存封面请求: {len(urls)} 个URL")
    
    if not urls:
        return jsonify({'success': True, 'cached': {}})
    
    cached = {}
    for url in urls:
        if url:
            cached_url = cache_cover(url)
            if cached_url:
                cached[url] = cached_url
    
    print(f"[NCM] 批量缓存完成: {len(cached)}/{len(urls)} 成功")
    return jsonify({'success': True, 'cached': cached})

@ncm_bp.route('/music/cache/covers/<filename>', methods=['GET'])
def serve_cached_cover(filename):
    print(f"[NCM] 提供缓存封面: {filename}")
    cover_dir = 'temp/music/covers'
    return send_file(f'{cover_dir}/{filename}')
