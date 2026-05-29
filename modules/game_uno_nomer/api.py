import random
import string
from datetime import datetime
from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from . import rooms

api_bp = Blueprint('game_uno_nomer_api', __name__, url_prefix='/api/uno-nomer')

def _generate_room_id():
    while True:
        room_id = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        if room_id not in rooms:
            return room_id

def _get_room_summary(room):
    return {
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
                'ready': p['ready'],
                'is_online': p['is_online'],
                'eliminated': p.get('eliminated', False)
            } if p else None
            for p in room['players']
        ]
    }

def _get_room_detail(room):
    detail = _get_room_summary(room)
    detail['messages'] = room.get('messages', [])
    game_state = room.get('game_state', {})
    if room['status'] == 'playing' and game_state:
        detail['game_state'] = {
            'current_turn': game_state.get('current_turn'),
            'direction': game_state.get('direction', 1),
            'top_card': game_state.get('top_card'),
            'top_color': game_state.get('top_color'),
            'deck_count': len(game_state.get('deck', [])),
            'phase': game_state.get('phase'),
            'hands_count': {str(seat): len(hand) for seat, hand in game_state.get('hands', {}).items()},
            'rankings': game_state.get('rankings', [])
        }
    else:
        detail['game_state'] = game_state
    return detail

@api_bp.route('/rooms', methods=['GET'])
@login_required
def list_rooms():
    room_list = [_get_room_summary(room) for room in rooms.values() if room['status'] != 'ended']
    return jsonify(room_list)

@api_bp.route('/rooms', methods=['POST'])
@login_required
def create_room():
    data = request.json or {}
    name = data.get('name', 'UNO No Mercy房间')
    password = data.get('password')
    max_players = data.get('max_players', 8)
    if not isinstance(max_players, int) or max_players < 2 or max_players > 10:
        max_players = 8

    if not name or not isinstance(name, str) or len(name.strip()) == 0:
        return jsonify({'error': '房间名称不能为空'}), 400

    room_id = _generate_room_id()
    now = datetime.utcnow()

    room = {
        'room_id': room_id,
        'name': name.strip(),
        'password': generate_password_hash(password) if password else None,
        'game_type': 'uno_nomer',
        'status': 'waiting',
        'creator_id': current_user.id,
        'creator_name': current_user.username,
        'created_at': now,
        'max_players': max_players,
        'players': [None] * max_players,
        'messages': [],
        'game_state': {}
    }

    room['players'][0] = {
        'user_id': current_user.id,
        'username': current_user.username,
        'nickname': getattr(current_user, 'nickname', current_user.username),
        'seat': 0,
        'ready': False,
        'is_online': False,
        'eliminated': False
    }

    rooms[room_id] = room
    return jsonify(_get_room_summary(room)), 201

@api_bp.route('/rooms/<room_id>/join', methods=['POST'])
@login_required
def join_room(room_id):
    room = rooms.get(room_id)
    if not room:
        return jsonify({'error': '房间不存在'}), 404
    if room['status'] == 'ended':
        return jsonify({'error': '房间已结束'}), 400
    if room['status'] == 'playing':
        return jsonify({'error': '游戏已开始'}), 400

    if room.get('password'):
        data = request.json or {}
        password = data.get('password', '')
        if not check_password_hash(room['password'], password):
            return jsonify({'error': '房间密码错误'}), 401

    for player in room['players']:
        if player and player['user_id'] == current_user.id:
            return jsonify(_get_room_summary(room))

    assigned_seat = None
    for i, player in enumerate(room['players']):
        if player is None:
            assigned_seat = i
            break

    if assigned_seat is None:
        return jsonify({'error': '房间已满'}), 400

    room['players'][assigned_seat] = {
        'user_id': current_user.id,
        'username': current_user.username,
        'nickname': getattr(current_user, 'nickname', current_user.username),
        'seat': assigned_seat,
        'ready': False,
        'is_online': False,
        'eliminated': False
    }

    return jsonify(_get_room_summary(room))

@api_bp.route('/rooms/<room_id>', methods=['GET'])
@login_required
def get_room(room_id):
    room = rooms.get(room_id)
    if not room:
        return jsonify({'error': '房间不存在'}), 404

    is_in_room = any(p and p['user_id'] == current_user.id for p in room['players'])
    if not is_in_room:
        return jsonify({'error': '您不在该房间中'}), 403

    return jsonify(_get_room_detail(room))
