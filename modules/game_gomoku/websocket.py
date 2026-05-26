from datetime import datetime
from flask_socketio import join_room, leave_room, emit
from flask import current_app
from flask_login import current_user
from . import rooms
from models import GameRecord, UserGameStats
from extensions import db

BOARD_SIZE = 15

# ===== Game Logic =====

def _check_five_in_row(board, x, y, player):
    """检查在 (x, y) 落子后，player 是否形成五连珠。返回获胜坐标列表或 None。"""
    directions = [
        (0, 1),   # 水平
        (1, 0),   # 垂直
        (1, 1),   # 主对角线
        (1, -1),  # 副对角线
    ]
    for dx, dy in directions:
        line = [(x, y)]
        # 正向
        i, j = x + dx, y + dy
        while 0 <= i < BOARD_SIZE and 0 <= j < BOARD_SIZE and board[i][j] == player:
            line.append((i, j))
            i += dx
            j += dy
        # 反向
        i, j = x - dx, y - dy
        while 0 <= i < BOARD_SIZE and 0 <= j < BOARD_SIZE and board[i][j] == player:
            line.append((i, j))
            i -= dx
            j -= dy
        if len(line) >= 5:
            return line
    return None


# ===== Game State Helpers =====

def _init_game_state(room):
    """初始化五子棋游戏状态"""
    game_state = {
        'board': [[0]*BOARD_SIZE for _ in range(BOARD_SIZE)],
        'current_turn': 1,  # 1=黑方, 2=白方
        'black_player': 0,
        'white_player': 1,
        'move_history': [],
        'winner': None,
        'winning_line': [],
        'draw_offered_by': None
    }
    room['game_state'] = game_state
    room['status'] = 'playing'
    room['game_start_time'] = datetime.utcnow()
    for p in room['players']:
        if p:
            p['ready'] = False
            p['role'] = 'unknown'
    return game_state


def _save_game_record(room, winner_ids, reason=''):
    """保存游戏记录到数据库并更新用户统计"""
    try:
        with current_app.app_context():
            winner_names = []
            loser_ids = []
            loser_names = []
            player_ids = []

            for p in room['players']:
                if p:
                    player_ids.append(p['user_id'])
                    if p['user_id'] in winner_ids:
                        winner_names.append(p['username'])
                    else:
                        loser_ids.append(p['user_id'])
                        loser_names.append(p['username'])

            record = GameRecord(
                game_type='gomoku',
                room_id=room['room_id'],
                started_at=room.get('game_start_time', datetime.utcnow()),
                ended_at=datetime.utcnow(),
                winner_ids=winner_ids,
                winner_names=winner_names,
                loser_ids=loser_ids,
                loser_names=loser_names,
                player_ids=player_ids,
                game_data={
                    'reason': reason,
                    'final_state': {
                        'board': room.get('game_state', {}).get('board', []),
                        'current_turn': room.get('game_state', {}).get('current_turn'),
                        'move_history': room.get('game_state', {}).get('move_history', [])
                    }
                }
            )
            db.session.add(record)

            for p in room['players']:
                if not p:
                    continue
                user_id = p['user_id']
                stats = UserGameStats.query.filter_by(user_id=user_id, game_type='gomoku').first()
                if not stats:
                    stats = UserGameStats(user_id=user_id, game_type='gomoku')
                    db.session.add(stats)

                stats.total_games += 1
                if user_id in winner_ids:
                    stats.wins += 1
                elif winner_ids:
                    stats.losses += 1
                else:
                    stats.draws += 1

                total = stats.wins + stats.losses + stats.draws
                stats.win_rate = stats.wins / total if total > 0 else 0.0
                stats.last_played = datetime.utcnow()

            db.session.commit()
    except Exception as e:
        print(f"保存游戏记录失败: {e}")


def _add_system_message(room, message):
    """添加系统消息到房间"""
    msg = {
        'username': 'system',
        'message': message,
        'timestamp': datetime.utcnow().isoformat(),
        'type': 'system'
    }
    room['messages'].append(msg)
    if len(room['messages']) > 200:
        room['messages'] = room['messages'][-200:]
    return msg


def _get_player_seat(room, user_id):
    """获取玩家在房间中的座位号"""
    for i, p in enumerate(room['players']):
        if p and p['user_id'] == user_id:
            return i
    return None


def _get_player_color(room, seat):
    """根据座位号获取玩家颜色（1=黑, 2=白）"""
    gs = room['game_state']
    if gs.get('black_player') == seat:
        return 1
    if gs.get('white_player') == seat:
        return 2
    return None


def _end_game(room, winner_seats, reason=''):
    """结束游戏并保存记录"""
    gs = room['game_state']
    gs['winner'] = winner_seats
    room['status'] = 'ended'

    winner_ids = []
    for seat in winner_seats:
        p = room['players'][seat]
        if p:
            winner_ids.append(p['user_id'])

    _save_game_record(room, winner_ids, reason)

    emit('game_ended', {
        'room_id': room['room_id'],
        'winners': winner_seats,
        'reason': reason,
        'game_state': {
            'board': gs['board'],
            'current_turn': gs['current_turn'],
            'winning_line': gs.get('winning_line', []),
            'move_history': gs.get('move_history', [])
        }
    }, room=room['room_id'])


# ===== Socket.IO Events =====

def register_socketio_events(socketio):

    @socketio.on('create_room', namespace='/game-gomoku')
    def on_create_room(data):
        """创建 Socket.IO 房间"""
        try:
            room_id = data.get('room_id')
            if not room_id:
                emit('error', {'message': '缺少房间ID'})
                return
            join_room(room_id)
            room = rooms.get(room_id)
            if room:
                if room['players'][0]:
                    room['players'][0]['is_online'] = True
                emit('room_created', {'room_id': room_id, 'seat': 0})
                emit('new_message', _add_system_message(room, f"{current_user.username} 创建了房间"), room=room_id)
        except Exception as e:
            emit('error', {'message': f'创建房间事件失败: {str(e)}'})

    @socketio.on('join_room', namespace='/game-gomoku')
    def on_join_room(data):
        """加入 Socket.IO 房间"""
        try:
            room_id = data.get('room_id')
            if not room_id:
                emit('error', {'message': '缺少房间ID'})
                return
            room = rooms.get(room_id)
            if not room:
                emit('error', {'message': '房间不存在'})
                return
            join_room(room_id)
            seat = _get_player_seat(room, current_user.id)
            if seat is not None and room['players'][seat]:
                room['players'][seat]['is_online'] = True
            emit('room_joined', {
                'room_id': room_id,
                'seat': seat,
                'room': _get_room_summary(room)
            })
            if seat is not None:
                emit('player_joined', {
                    'room_id': room_id,
                    'seat': seat,
                    'username': current_user.username,
                    'nickname': getattr(current_user, 'nickname', current_user.username),
                    'players': [
                        {
                            'user_id': p['user_id'],
                            'username': p['username'],
                            'nickname': p['nickname'],
                            'seat': p['seat'],
                            'ready': p['ready'],
                            'role': p['role'],
                            'is_online': p['is_online']
                        } if p else None
                        for p in room['players']
                    ]
                }, room=room_id)
                emit('new_message', _add_system_message(room, f"{current_user.username} 加入了房间"), room=room_id)
        except Exception as e:
            emit('error', {'message': f'加入房间事件失败: {str(e)}'})

    @socketio.on('leave_room', namespace='/game-gomoku')
    def on_leave_room(data):
        """离开房间"""
        try:
            room_id = data.get('room_id')
            if not room_id:
                return
            room = rooms.get(room_id)
            if not room:
                leave_room(room_id)
                return
            seat = _get_player_seat(room, current_user.id)
            if seat is None:
                leave_room(room_id)
                return
            leave_room(room_id)
            is_creator = (room['creator_id'] == current_user.id)

            if is_creator:
                if room['status'] == 'playing':
                    # 游戏进行中，其他玩家获胜
                    remaining = [i for i, p in enumerate(room['players']) if p is not None and i != seat]
                    if remaining:
                        _end_game(room, remaining, 'creator_left')
                    else:
                        _end_game(room, [], 'creator_left')
                room['status'] = 'ended'
                emit('room_disbanded', {'room_id': room_id, 'reason': 'creator_left'}, room=room_id)
                if room_id in rooms:
                    del rooms[room_id]
                return

            # 普通玩家离开
            room['players'][seat] = None
            if room['status'] == 'playing':
                remaining = [i for i, p in enumerate(room['players']) if p is not None]
                if remaining:
                    _end_game(room, remaining, 'player_left')
                room['status'] = 'ended'
                emit('room_disbanded', {'room_id': room_id, 'reason': 'player_left'}, room=room_id)
                if room_id in rooms:
                    del rooms[room_id]
                return

            emit('player_left', {
                'room_id': room_id,
                'seat': seat,
                'username': current_user.username
            }, room=room_id)
            emit('new_message', _add_system_message(room, f"{current_user.username} 离开了房间"), room=room_id)
        except Exception as e:
            emit('error', {'message': f'离开房间事件失败: {str(e)}'})

    @socketio.on('ready', namespace='/game-gomoku')
    def on_ready(data):
        """切换准备状态"""
        try:
            room_id = data.get('room_id')
            ready = data.get('ready', False)
            room = rooms.get(room_id)
            if not room:
                emit('error', {'message': '房间不存在'})
                return
            seat = _get_player_seat(room, current_user.id)
            if seat is None:
                emit('error', {'message': '您不在该房间中'})
                return
            if room['status'] != 'waiting':
                emit('error', {'message': '游戏不在等待状态'})
                return
            room['players'][seat]['ready'] = bool(ready)
            emit('player_ready', {
                'room_id': room_id,
                'seat': seat,
                'ready': bool(ready),
                'username': current_user.username
            }, room=room_id)
        except Exception as e:
            emit('error', {'message': f'准备事件失败: {str(e)}'})

    @socketio.on('start_game', namespace='/game-gomoku')
    def on_start_game(data):
        """开始游戏"""
        try:
            room_id = data.get('room_id')
            room = rooms.get(room_id)
            if not room:
                emit('error', {'message': '房间不存在'})
                return
            if room['creator_id'] != current_user.id:
                emit('error', {'message': '只有房主可以开始游戏'})
                return
            if room['status'] != 'waiting':
                emit('error', {'message': '游戏不在等待状态'})
                return
            active_players = [p for p in room['players'] if p is not None]
            if len(active_players) < 2:
                emit('error', {'message': '需要2名玩家才能开始游戏'})
                return
            if not all(p['ready'] for p in active_players):
                emit('error', {'message': '有玩家尚未准备'})
                return

            gs = _init_game_state(room)
            # 设置角色
            if room['players'][0]:
                room['players'][0]['role'] = 'black'
            if room['players'][1]:
                room['players'][1]['role'] = 'white'

            emit('game_started', {
                'room_id': room_id,
                'board': gs['board'],
                'current_turn': gs['current_turn'],
                'black_player': gs['black_player'],
                'white_player': gs['white_player'],
                'players': [
                    {
                        'user_id': p['user_id'],
                        'username': p['username'],
                        'nickname': p['nickname'],
                        'seat': p['seat'],
                        'role': p['role'],
                        'is_online': p['is_online']
                    } if p else None
                    for p in room['players']
                ]
            }, room=room_id)
            emit('new_message', _add_system_message(room, "游戏开始！黑方先行"), room=room_id)
        except Exception as e:
            emit('error', {'message': f'开始游戏事件失败: {str(e)}'})

    @socketio.on('move', namespace='/game-gomoku')
    def on_move(data):
        """落子"""
        try:
            room_id = data.get('room_id')
            x = data.get('x')
            y = data.get('y')

            if x is None or y is None:
                emit('error', {'message': '缺少落子坐标'})
                return

            room = rooms.get(room_id)
            if not room:
                emit('error', {'message': '房间不存在'})
                return
            gs = room['game_state']
            if room['status'] != 'playing':
                emit('error', {'message': '游戏不在进行中'})
                return

            seat = _get_player_seat(room, current_user.id)
            if seat is None:
                emit('error', {'message': '您不在该房间中'})
                return

            player_color = _get_player_color(room, seat)
            if player_color is None:
                emit('error', {'message': '您不是游戏参与者'})
                return
            if gs['current_turn'] != player_color:
                emit('error', {'message': '不是您的回合'})
                return

            # 验证坐标
            if not (0 <= x < BOARD_SIZE and 0 <= y < BOARD_SIZE):
                emit('error', {'message': '坐标超出范围'})
                return

            board = gs['board']
            if board[x][y] != 0:
                emit('error', {'message': '该位置已有棋子'})
                return

            # 执行落子
            board[x][y] = player_color
            gs['move_history'].append({
                'x': x,
                'y': y,
                'player': player_color
            })

            # 广播落子结果
            next_turn = 2 if player_color == 1 else 1
            emit('move_result', {
                'room_id': room_id,
                'x': x,
                'y': y,
                'player': player_color,
                'current_turn': gs['current_turn'],
                'next_turn': next_turn
            }, room=room_id)

            # 检查五连珠
            winning_line = _check_five_in_row(board, x, y, player_color)
            if winning_line:
                gs['winning_line'] = winning_line
                winner_seat = gs['black_player'] if player_color == 1 else gs['white_player']
                emit('five_in_row', {
                    'room_id': room_id,
                    'player': player_color,
                    'winning_line': winning_line,
                    'winner': winner_seat
                }, room=room_id)
                _end_game(room, [winner_seat], 'five_in_row')
                color_name = '黑方' if player_color == 1 else '白方'
                emit('new_message', _add_system_message(room, f"{color_name} 五子连珠，获胜！"), room=room_id)
                return

            # 检查棋盘是否已满
            if len(gs['move_history']) >= BOARD_SIZE * BOARD_SIZE:
                emit('board_full', {'room_id': room_id}, room=room_id)
                _end_game(room, [], 'board_full')
                emit('new_message', _add_system_message(room, "棋盘已满，平局！"), room=room_id)
                return

            # 切换回合
            gs['current_turn'] = next_turn

        except Exception as e:
            emit('error', {'message': f'落子事件失败: {str(e)}'})

    @socketio.on('offer_draw', namespace='/game-gomoku')
    def on_offer_draw(data):
        """请求和棋"""
        try:
            room_id = data.get('room_id')
            room = rooms.get(room_id)
            if not room:
                emit('error', {'message': '房间不存在'})
                return
            if room['status'] != 'playing':
                emit('error', {'message': '游戏不在进行中'})
                return
            seat = _get_player_seat(room, current_user.id)
            if seat is None:
                emit('error', {'message': '您不在该房间中'})
                return
            gs = room['game_state']
            if gs.get('draw_offered_by') is not None:
                emit('error', {'message': '已有待处理的和棋请求'})
                return
            gs['draw_offered_by'] = seat
            emit('draw_offered', {
                'room_id': room_id,
                'seat': seat,
                'username': current_user.username
            }, room=room_id)
            emit('new_message', _add_system_message(room, f"{current_user.username} 请求和棋"), room=room_id)
        except Exception as e:
            emit('error', {'message': f'请求和棋失败: {str(e)}'})

    @socketio.on('accept_draw', namespace='/game-gomoku')
    def on_accept_draw(data):
        """同意和棋"""
        try:
            room_id = data.get('room_id')
            room = rooms.get(room_id)
            if not room:
                emit('error', {'message': '房间不存在'})
                return
            if room['status'] != 'playing':
                emit('error', {'message': '游戏不在进行中'})
                return
            seat = _get_player_seat(room, current_user.id)
            if seat is None:
                emit('error', {'message': '您不在该房间中'})
                return
            gs = room['game_state']
            if gs.get('draw_offered_by') is None:
                emit('error', {'message': '没有待处理的和棋请求'})
                return
            if gs['draw_offered_by'] == seat:
                emit('error', {'message': '不能同意自己的和棋请求'})
                return
            emit('draw_accepted', {'room_id': room_id}, room=room_id)
            _end_game(room, [], 'draw')
            emit('new_message', _add_system_message(room, "双方同意和棋，平局"), room=room_id)
        except Exception as e:
            emit('error', {'message': f'同意和棋失败: {str(e)}'})

    @socketio.on('decline_draw', namespace='/game-gomoku')
    def on_decline_draw(data):
        """拒绝和棋"""
        try:
            room_id = data.get('room_id')
            room = rooms.get(room_id)
            if not room:
                emit('error', {'message': '房间不存在'})
                return
            seat = _get_player_seat(room, current_user.id)
            if seat is None:
                emit('error', {'message': '您不在该房间中'})
                return
            gs = room['game_state']
            gs['draw_offered_by'] = None
            emit('draw_declined', {
                'room_id': room_id,
                'seat': seat,
                'username': current_user.username
            }, room=room_id)
            emit('new_message', _add_system_message(room, f"{current_user.username} 拒绝了和棋请求"), room=room_id)
        except Exception as e:
            emit('error', {'message': f'拒绝和棋失败: {str(e)}'})

    @socketio.on('resign', namespace='/game-gomoku')
    def on_resign(data):
        """认输"""
        try:
            room_id = data.get('room_id')
            room = rooms.get(room_id)
            if not room:
                emit('error', {'message': '房间不存在'})
                return
            if room['status'] != 'playing':
                emit('error', {'message': '游戏不在进行中'})
                return
            seat = _get_player_seat(room, current_user.id)
            if seat is None:
                emit('error', {'message': '您不在该房间中'})
                return
            gs = room['game_state']
            player_color = _get_player_color(room, seat)
            winner_seat = gs['white_player'] if player_color == 1 else gs['black_player']
            emit('game_ended', {
                'room_id': room_id,
                'winners': [winner_seat],
                'reason': 'resign'
            }, room=room_id)
            _end_game(room, [winner_seat], 'resign')
            color_name = '黑方' if player_color == 1 else '白方'
            winner_name = '白方' if player_color == 1 else '黑方'
            emit('new_message', _add_system_message(room, f"{color_name} 认输，{winner_name} 获胜"), room=room_id)
        except Exception as e:
            emit('error', {'message': f'认输失败: {str(e)}'})

    @socketio.on('send_message', namespace='/game-gomoku')
    def on_send_message(data):
        """发送聊天消息"""
        try:
            room_id = data.get('room_id')
            message = data.get('message', '').strip()
            if not room_id or not message:
                return
            room = rooms.get(room_id)
            if not room:
                emit('error', {'message': '房间不存在'})
                return
            seat = _get_player_seat(room, current_user.id)
            if seat is None:
                emit('error', {'message': '您不在该房间中'})
                return
            msg = {
                'username': current_user.username,
                'nickname': getattr(current_user, 'nickname', current_user.username),
                'message': message,
                'timestamp': datetime.utcnow().isoformat(),
                'type': 'chat'
            }
            room['messages'].append(msg)
            if len(room['messages']) > 200:
                room['messages'] = room['messages'][-200:]
            emit('new_message', msg, room=room_id)
        except Exception as e:
            emit('error', {'message': f'发送消息失败: {str(e)}'})


def _get_room_summary(room):
    """生成房间摘要（用于 websocket 广播）"""
    return {
        'room_id': room['room_id'],
        'name': room['name'],
        'status': room['status'],
        'creator_id': room['creator_id'],
        'creator_name': room['creator_name'],
        'max_players': room['max_players'],
        'players': [
            {
                'user_id': p['user_id'],
                'username': p['username'],
                'nickname': p['nickname'],
                'seat': p['seat'],
                'ready': p['ready'],
                'role': p['role'],
                'is_online': p['is_online']
            } if p else None
            for p in room['players']
        ]
    }
