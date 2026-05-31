from flask import render_template, send_from_directory, jsonify, request
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from utils import get_bing_wallpaper, get_poetry, get_settings, get_nav_items
from config import Config
from . import main_bp
from models import GameRecord, UserGameStats
from modules.game_chess import rooms as chess_rooms
from modules.game_gomoku import rooms as gomoku_rooms
from modules.game_doudizhu import rooms as doudizhu_rooms
from modules.game_uno import rooms as uno_rooms
from modules.game_uno_nomer import rooms as uno_nomer_rooms
import random
import string
from datetime import datetime, timezone


# 游戏配置
GAME_CONFIG = {
    'doudizhu': {
        'name': '斗地主',
        'rooms': doudizhu_rooms,
        'max_players': 3,
        'default_name': '斗地主房间',
        'api_prefix': '/api/doudizhu'
    },
    'chess': {
        'name': '象棋',
        'rooms': chess_rooms,
        'max_players': 2,
        'default_name': '象棋房间',
        'api_prefix': '/api/chess'
    },
    'gomoku': {
        'name': '五子棋',
        'rooms': gomoku_rooms,
        'max_players': 2,
        'default_name': '五子棋房间',
        'api_prefix': '/api/gomoku'
    },
    'uno': {
        'name': 'UNO',
        'rooms': uno_rooms,
        'max_players': 8,
        'min_players': 3,
        'default_name': 'UNO房间',
        'api_prefix': '/api/uno'
    },
    'uno-nomer': {
        'name': 'UNO No Mercy',
        'rooms': uno_nomer_rooms,
        'max_players': 10,
        'min_players': 2,
        'default_name': 'UNO No Mercy房间',
        'api_prefix': '/api/uno-nomer',
        'game_type': 'uno_nomer'
    }
}


def _generate_room_id():
    """生成8位房间ID"""
    all_rooms = {}
    for config in GAME_CONFIG.values():
        all_rooms.update(config['rooms'])
    while True:
        room_id = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        if room_id not in all_rooms:
            return room_id


def _get_room_summary(room, game_type):
    """返回房间摘要（过滤敏感数据）"""
    summary = {
        'room_id': room['room_id'],
        'name': room['name'],
        'has_password': bool(room.get('password')),
        'status': room['status'],
        'creator_id': room['creator_id'],
        'creator_name': room['creator_name'],
        'created_at': room['created_at'].isoformat() if isinstance(room['created_at'], datetime) else room['created_at'],
        'max_players': room['max_players'],
        'player_count': len([p for p in room['players'] if p is not None]),
        'players': [
            {
                'user_id': p['user_id'],
                'username': p['username'],
                'nickname': p['nickname'],
                'seat': p['seat'],
                'ready': p.get('ready', False),
                'role': p.get('role', 'unknown'),
                'is_online': p.get('is_online', False)
            } if p else None
            for p in room['players']
        ],
        'game_type': game_type,
        'game_type_name': GAME_CONFIG[game_type]['name']
    }
    return summary

@main_bp.route('/')
def index():
    wallpaper_url = get_bing_wallpaper()
    poetry = get_poetry()
    return render_template('index.html', wallpaper_url=wallpaper_url, poetry=poetry)

@main_bp.route('/board')
@login_required
def board():
    settings = get_settings()
    return render_template('board.html', 
                         current_user=current_user,
                         home_display=settings.get('home_display', 'nickname'),
                         sidebar_expanded=settings.get('sidebar_default_expanded', False))

@main_bp.route('/board/tools')
@login_required
def tools():
    settings = get_settings()
    return render_template('tools.html',
                         current_user=current_user,
                         sidebar_expanded=settings.get('sidebar_default_expanded', False),
                         card_layout=settings.get('card_layout', '1x4'),
                         category='tools')

@main_bp.route('/board/games')
@login_required
def games():
    settings = get_settings()
    return render_template('games.html',
                         current_user=current_user,
                         sidebar_expanded=settings.get('sidebar_default_expanded', False))

@main_bp.route('/board/swipe-test')
@login_required
def swipe_test():
    if not (current_user.is_admin or current_user.is_super_admin):
        return render_template('error.html', 
                             error_title='权限不足',
                             error_message='您没有权限访问此页面',
                             current_user=current_user), 403
    settings = get_settings()
    return render_template('swipe_test.html', 
                         current_user=current_user,
                         sidebar_expanded=settings.get('sidebar_default_expanded', False))

@main_bp.route('/board/announcements')
@login_required
def announcement_manage():
    if not (current_user.is_admin or current_user.is_super_admin):
        return render_template('error.html', 
                             error_title='权限不足',
                             error_message='您没有权限访问此页面',
                             current_user=current_user), 403
    settings = get_settings()
    return render_template('announcement_manage.html', 
                         current_user=current_user,
                         sidebar_expanded=settings.get('sidebar_default_expanded', False))

@main_bp.route('/temp/<path:filename>')
def serve_temp(filename):
    return send_from_directory(Config.TEMP_DIR, filename)

@main_bp.route('/assets/<path:filename>')
def serve_assets(filename):
    return send_from_directory(Config.ASSETS_DIR, filename)

@main_bp.route('/api/nav/items')
@login_required
def get_nav_items_api():
    category = request.args.get('category', 'tools')
    items = get_nav_items()
    filtered_items = [item for item in items if item.get('category') == category]
    return jsonify(filtered_items)


@main_bp.route('/api/game/stats/<game_type>')
@login_required
def get_game_stats(game_type):
    """获取某游戏战绩"""
    user_id = request.args.get('user_id', current_user.id, type=int)
    stats = UserGameStats.query.filter_by(user_id=user_id, game_type=game_type).first()
    if not stats:
        return jsonify({
            'game_type': game_type,
            'total_games': 0,
            'wins': 0,
            'losses': 0,
            'draws': 0,
            'win_rate': 0.0
        })
    return jsonify({
        'game_type': stats.game_type,
        'total_games': stats.total_games,
        'wins': stats.wins,
        'losses': stats.losses,
        'draws': stats.draws,
        'win_rate': stats.win_rate
    })


@main_bp.route('/api/game/records')
@login_required
def get_game_records():
    """获取最近对局记录"""
    game_type = request.args.get('game_type')
    limit = request.args.get('limit', 20, type=int)
    q = GameRecord.query
    if game_type:
        q = q.filter_by(game_type=game_type)
    records = q.order_by(GameRecord.ended_at.desc()).limit(limit).all()
    return jsonify({'records': [{
        'id': r.id,
        'game_type': r.game_type,
        'winner_names': r.winner_names or [],
        'loser_names': r.loser_names or [],
        'ended_at': r.ended_at.isoformat() if r.ended_at else None,
        'game_data': r.game_data or {}
    } for r in records]})


@main_bp.route('/api/game/leaderboard/<game_type>')
@login_required
def get_leaderboard(game_type):
    """获取游戏排行榜"""
    stats = UserGameStats.query.filter_by(game_type=game_type).order_by(
        UserGameStats.win_rate.desc()
    ).limit(20).all()
    return jsonify({'leaderboard': [{
        'user_id': s.user_id,
        'total_games': s.total_games,
        'wins': s.wins,
        'win_rate': s.win_rate,
        'last_played': s.last_played.isoformat() if s.last_played else None
    } for s in stats]})


@main_bp.route('/api/games/rooms')
@login_required
def list_all_rooms():
    """获取所有游戏的活跃房间列表"""
    all_rooms = []
    for game_type, config in GAME_CONFIG.items():
        rooms = config['rooms']
        for room in rooms.values():
            if room['status'] != 'ended':
                all_rooms.append(_get_room_summary(room, game_type))
    # 按创建时间排序，最新的在前
    all_rooms.sort(key=lambda x: x['created_at'], reverse=True)
    return jsonify(all_rooms)


@main_bp.route('/api/games/rooms', methods=['POST'])
@login_required
def create_room_unified():
    """创建房间（统一入口）"""
    data = request.json or {}
    game_type = data.get('game_type')
    name = data.get('name')
    password = data.get('password')
    max_players = data.get('max_players')

    if game_type not in GAME_CONFIG:
        return jsonify({'error': '无效的游戏类型'}), 400

    config = GAME_CONFIG[game_type]
    rooms = config['rooms']

    if not name or not isinstance(name, str) or len(name.strip()) == 0:
        name = config['default_name']

    room_id = _generate_room_id()
    now = datetime.now(timezone.utc)

    # 确定最大玩家数
    if max_players:
        if not isinstance(max_players, int):
            max_players = config['max_players']
        if max_players > config['max_players']:
            max_players = config['max_players']
        if 'min_players' in config and max_players < config['min_players']:
            max_players = config['min_players']
    else:
        max_players = config['max_players']

    # 确定房间游戏类型（有些游戏的内部类型与 URL 前缀不同）
    internal_game_type = config.get('game_type', game_type)

    room = {
        'room_id': room_id,
        'name': name.strip(),
        'password': generate_password_hash(password) if password else None,
        'game_type': internal_game_type,
        'status': 'waiting',
        'creator_id': current_user.id,
        'creator_name': current_user.username,
        'created_at': now,
        'max_players': max_players,
        'players': [None] * max_players,
        'messages': [],
        'game_state': {}
    }

    # 创建者加入座位 0
    room['players'][0] = {
        'user_id': current_user.id,
        'username': current_user.username,
        'nickname': getattr(current_user, 'nickname', current_user.username),
        'seat': 0,
        'ready': False,
        'role': 'unknown',
        'is_online': False
    }

    rooms[room_id] = room

    return jsonify(_get_room_summary(room, game_type)), 201


@main_bp.route('/api/games/rooms/<room_id>/join', methods=['POST'])
@login_required
def join_room_unified(room_id):
    """加入房间（统一入口）"""
    data = request.json or {}
    password = data.get('password', '')

    # 在所有游戏房间中查找
    found_room = None
    found_game_type = None
    for game_type, config in GAME_CONFIG.items():
        rooms = config['rooms']
        if room_id in rooms:
            found_room = rooms[room_id]
            found_game_type = game_type
            break

    if not found_room:
        return jsonify({'error': '房间不存在'}), 404

    if found_room['status'] == 'ended':
        return jsonify({'error': '房间已结束'}), 400

    if found_room['status'] == 'playing':
        return jsonify({'error': '游戏已开始'}), 400

    # 验证密码
    if found_room.get('password'):
        if not check_password_hash(found_room['password'], password):
            return jsonify({'error': '房间密码错误'}), 401

    # 检查是否已经在房间中
    for player in found_room['players']:
        if player and player['user_id'] == current_user.id:
            return jsonify(_get_room_summary(found_room, found_game_type))

    # 寻找空座位
    assigned_seat = None
    for i, player in enumerate(found_room['players']):
        if player is None:
            assigned_seat = i
            break

    if assigned_seat is None:
        return jsonify({'error': '房间已满'}), 400

    found_room['players'][assigned_seat] = {
        'user_id': current_user.id,
        'username': current_user.username,
        'nickname': getattr(current_user, 'nickname', current_user.username),
        'seat': assigned_seat,
        'ready': False,
        'role': 'unknown',
        'is_online': False
    }

    return jsonify(_get_room_summary(found_room, found_game_type))
