import copy
from datetime import datetime, timezone
from flask_socketio import join_room, leave_room, emit
from flask import current_app
from flask_login import current_user
from . import rooms
from models import GameRecord, UserGameStats
from extensions import db

# 初始棋盘状态 (10 行 × 9 列)
# 黑方在上方 (x=0..4)，红方在下方 (x=5..9)
INITIAL_BOARD = [
    ['b_rook', 'b_knight', 'b_elephant', 'b_guard', 'b_king', 'b_guard', 'b_elephant', 'b_knight', 'b_rook'],
    [None]*9,
    [None, 'b_cannon', None, None, None, None, None, 'b_cannon', None],
    ['b_pawn', None, 'b_pawn', None, 'b_pawn', None, 'b_pawn', None, 'b_pawn'],
    [None]*9,
    [None]*9,
    ['r_pawn', None, 'r_pawn', None, 'r_pawn', None, 'r_pawn', None, 'r_pawn'],
    [None, 'r_cannon', None, None, None, None, None, 'r_cannon', None],
    [None]*9,
    ['r_rook', 'r_knight', 'r_elephant', 'r_guard', 'r_king', 'r_guard', 'r_elephant', 'r_knight', 'r_rook']
]


# ===== Move Validation Helpers =====

def _get_king_pos(board, color):
    """找到指定颜色的帅/将位置"""
    king_name = 'r_king' if color == 'red' else 'b_king'
    for x in range(10):
        for y in range(9):
            if board[x][y] == king_name:
                return (x, y)
    return None


def _is_clear_path(board, x1, y1, x2, y2):
    """检查两点之间直线路径是否有棋子（不包括端点）"""
    if x1 == x2:
        step = 1 if y2 > y1 else -1
        for y in range(y1 + step, y2, step):
            if board[x1][y] is not None:
                return False
        return True
    elif y1 == y2:
        step = 1 if x2 > x1 else -1
        for x in range(x1 + step, x2, step):
            if board[x][y1] is not None:
                return False
        return True
    return False


def _count_pieces_between(board, x1, y1, x2, y2):
    """统计两点之间直线上的棋子数量"""
    count = 0
    if x1 == x2:
        step = 1 if y2 > y1 else -1
        for y in range(y1 + step, y2, step):
            if board[x1][y] is not None:
                count += 1
    elif y1 == y2:
        step = 1 if x2 > x1 else -1
        for x in range(x1 + step, x2, step):
            if board[x][y1] is not None:
                count += 1
    return count


def _can_piece_reach(board, from_x, from_y, to_x, to_y):
    """检查棋子是否能从 (from_x, from_y) 走到 (to_x, to_y)，只检查几何和阻挡规则，不检查将军"""
    piece = board[from_x][from_y]
    if piece is None:
        return False, '起始位置无棋子'

    color = 'red' if piece.startswith('r_') else 'black'
    target = board[to_x][to_y]
    if target and ((color == 'red' and target.startswith('r_')) or (color == 'black' and target.startswith('b_'))):
        return False, '不能吃掉自己的棋子'

    piece_type = piece[2:]
    dx = abs(to_x - from_x)
    dy = abs(to_y - from_y)

    # 帅/将
    if piece_type == 'king':
        if color == 'red' and not (7 <= to_x <= 9 and 3 <= to_y <= 5):
            return False, '帅只能在九宫内移动'
        if color == 'black' and not (0 <= to_x <= 2 and 3 <= to_y <= 5):
            return False, '将只能在九宫内移动'
        if dx + dy != 1:
            return False, '帅/将只能走一步'
        return True, ''

    # 仕/士
    if piece_type == 'guard':
        if color == 'red' and not (7 <= to_x <= 9 and 3 <= to_y <= 5):
            return False, '仕只能在九宫内移动'
        if color == 'black' and not (0 <= to_x <= 2 and 3 <= to_y <= 5):
            return False, '士只能在九宫内移动'
        if dx != 1 or dy != 1:
            return False, '士/仕只能斜走一步'
        return True, ''

    # 相/象
    if piece_type == 'elephant':
        if color == 'red' and to_x < 5:
            return False, '相不能过河'
        if color == 'black' and to_x > 4:
            return False, '象不能过河'
        if dx != 2 or dy != 2:
            return False, '象只能走田字'
        eye_x = (from_x + to_x) // 2
        eye_y = (from_y + to_y) // 2
        if board[eye_x][eye_y] is not None:
            return False, '象眼被塞'
        return True, ''

    # 马
    if piece_type == 'knight':
        if not ((dx == 2 and dy == 1) or (dx == 1 and dy == 2)):
            return False, '马只能走日字'
        if dx == 2:
            leg_x = from_x + (1 if to_x > from_x else -1)
            leg_y = from_y
        else:
            leg_x = from_x
            leg_y = from_y + (1 if to_y > from_y else -1)
        if board[leg_x][leg_y] is not None:
            return False, '马腿被蹩'
        return True, ''

    # 车
    if piece_type == 'rook':
        if from_x != to_x and from_y != to_y:
            return False, '车只能直线走'
        if not _is_clear_path(board, from_x, from_y, to_x, to_y):
            return False, '车不能越子'
        return True, ''

    # 炮
    if piece_type == 'cannon':
        if from_x != to_x and from_y != to_y:
            return False, '炮只能直线走'
        count = _count_pieces_between(board, from_x, from_y, to_x, to_y)
        if target is None:
            if count != 0:
                return False, '炮移动时不能越子'
        else:
            if count != 1:
                return False, '炮吃子必须隔一个子'
        return True, ''

    # 兵/卒
    if piece_type == 'pawn':
        mx = to_x - from_x
        my = to_y - from_y
        if color == 'red':
            # 红兵向上走 (x 减小)
            if from_x >= 5:  # 未过河
                if not (mx == -1 and my == 0):
                    return False, '兵未过河只能前进'
            else:  # 已过河
                if not ((mx == -1 and my == 0) or (mx == 0 and abs(my) == 1)):
                    return False, '兵过河后才能左右移动'
        else:
            # 黑卒向下走 (x 增大)
            if from_x <= 4:  # 未过河
                if not (mx == 1 and my == 0):
                    return False, '卒未过河只能前进'
            else:  # 已过河
                if not ((mx == 1 and my == 0) or (mx == 0 and abs(my) == 1)):
                    return False, '卒过河后才能左右移动'
        return True, ''

    return False, '未知棋子'


def _is_in_check(board, color):
    """检查指定颜色的帅/将是否被将军"""
    king_pos = _get_king_pos(board, color)
    if not king_pos:
        return False
    king_x, king_y = king_pos
    opp_color = 'black' if color == 'red' else 'red'
    opp_prefix = 'b_' if color == 'red' else 'r_'

    # 检查帅/将是否面对面
    opp_king = _get_king_pos(board, opp_color)
    if opp_king:
        okx, oky = opp_king
        if king_y == oky:
            x1, x2 = sorted([king_x, okx])
            clear = True
            for x in range(x1 + 1, x2):
                if board[x][king_y] is not None:
                    clear = False
                    break
            if clear:
                return True

    # 检查是否有对方棋子可以攻击到帅/将
    for x in range(10):
        for y in range(9):
            piece = board[x][y]
            if piece and piece.startswith(opp_prefix):
                if _can_attack(board, x, y, king_x, king_y):
                    return True
    return False


def _can_attack(board, from_x, from_y, to_x, to_y):
    """检查 (from_x, from_y) 处的棋子能否攻击到 (to_x, to_y)（纯几何+阻挡，不检查将军）"""
    piece = board[from_x][from_y]
    if piece is None:
        return False
    piece_type = piece[2:]
    dx = abs(to_x - from_x)
    dy = abs(to_y - from_y)

    if piece_type == 'king':
        if dx + dy != 1:
            return False
        color = 'red' if piece.startswith('r_') else 'black'
        if color == 'red' and not (7 <= to_x <= 9 and 3 <= to_y <= 5):
            return False
        if color == 'black' and not (0 <= to_x <= 2 and 3 <= to_y <= 5):
            return False
        return True

    if piece_type == 'guard':
        if dx != 1 or dy != 1:
            return False
        color = 'red' if piece.startswith('r_') else 'black'
        if color == 'red' and not (7 <= to_x <= 9 and 3 <= to_y <= 5):
            return False
        if color == 'black' and not (0 <= to_x <= 2 and 3 <= to_y <= 5):
            return False
        return True

    if piece_type == 'elephant':
        color = 'red' if piece.startswith('r_') else 'black'
        if color == 'red' and to_x < 5:
            return False
        if color == 'black' and to_x > 4:
            return False
        if dx != 2 or dy != 2:
            return False
        eye_x = (from_x + to_x) // 2
        eye_y = (from_y + to_y) // 2
        if board[eye_x][eye_y] is not None:
            return False
        return True

    if piece_type == 'knight':
        if not ((dx == 2 and dy == 1) or (dx == 1 and dy == 2)):
            return False
        if dx == 2:
            leg_x = from_x + (1 if to_x > from_x else -1)
            leg_y = from_y
        else:
            leg_x = from_x
            leg_y = from_y + (1 if to_y > from_y else -1)
        if board[leg_x][leg_y] is not None:
            return False
        return True

    if piece_type == 'rook':
        if from_x != to_x and from_y != to_y:
            return False
        return _is_clear_path(board, from_x, from_y, to_x, to_y)

    if piece_type == 'cannon':
        if from_x != to_x and from_y != to_y:
            return False
        count = _count_pieces_between(board, from_x, from_y, to_x, to_y)
        return count == 1

    if piece_type == 'pawn':
        mx = to_x - from_x
        my = to_y - from_y
        color = 'red' if piece.startswith('r_') else 'black'
        if color == 'red':
            if from_x >= 5:
                return mx == -1 and my == 0
            else:
                return (mx == -1 and my == 0) or (mx == 0 and abs(my) == 1)
        else:
            if from_x <= 4:
                return mx == 1 and my == 0
            else:
                return (mx == 1 and my == 0) or (mx == 0 and abs(my) == 1)

    return False


def _validate_move(board, from_x, from_y, to_x, to_y, color):
    """完整的走法验证，包括不能送将/不能动将被将/不能帅见面等"""
    piece = board[from_x][from_y]
    if piece is None:
        return False, '起始位置无棋子'

    piece_color = 'red' if piece.startswith('r_') else 'black'
    if piece_color != color:
        return False, '只能移动自己的棋子'

    valid, msg = _can_piece_reach(board, from_x, from_y, to_x, to_y)
    if not valid:
        return False, msg

    # 模拟走棋，检查是否违反规则
    new_board = [row[:] for row in board]
    new_board[to_x][to_y] = new_board[from_x][from_y]
    new_board[from_x][from_y] = None

    # 检查帅/将是否见面
    red_king = _get_king_pos(new_board, 'red')
    black_king = _get_king_pos(new_board, 'black')
    if red_king and black_king and red_king[1] == black_king[1]:
        rx, _ = red_king
        bx, _ = black_king
        x1, x2 = sorted([rx, bx])
        clear = True
        for x in range(x1 + 1, x2):
            if new_board[x][red_king[1]] is not None:
                clear = False
                break
        if clear:
            return False, '帅不能见面'

    # 检查走完后己方是否被将军
    if _is_in_check(new_board, color):
        return False, '移动后己方被将军'

    return True, ''


def _is_checkmate(board, color):
    """检查指定颜色是否被将死"""
    if not _is_in_check(board, color):
        return False
    return _has_no_valid_moves(board, color)


def _is_stalemate(board, color):
    """检查指定颜色是否被逼和（无子可动且未被将军）"""
    if _is_in_check(board, color):
        return False
    return _has_no_valid_moves(board, color)


def _has_no_valid_moves(board, color):
    """检查指定颜色是否有任何合法走法"""
    for x in range(10):
        for y in range(9):
            piece = board[x][y]
            if piece and ((color == 'red' and piece.startswith('r_')) or (color == 'black' and piece.startswith('b_'))):
                for tx in range(10):
                    for ty in range(9):
                        valid, _ = _validate_move(board, x, y, tx, ty, color)
                        if valid:
                            return False
    return True


# ===== Game State Helpers =====

def _init_game_state(room):
    """初始化象棋游戏状态"""
    game_state = {
        'board': copy.deepcopy(INITIAL_BOARD),
        'current_turn': 'red',
        'red_player': 0,
        'black_player': 1,
        'move_history': [],
        'winner': None,
        'check_status': False,
        'draw_offered_by': None
    }
    room['game_state'] = game_state
    room['status'] = 'playing'
    room['game_start_time'] = datetime.now(timezone.utc)
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
                game_type='chess',
                room_id=room['room_id'],
                started_at=room.get('game_start_time', datetime.now(timezone.utc)),
                ended_at=datetime.now(timezone.utc),
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
                stats = UserGameStats.query.filter_by(user_id=user_id, game_type='chess').first()
                if not stats:
                    stats = UserGameStats(user_id=user_id, game_type='chess')
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
                stats.last_played = datetime.now(timezone.utc)

            db.session.commit()
    except Exception as e:
        print(f"保存游戏记录失败: {e}")


def _add_system_message(room, message):
    """添加系统消息到房间"""
    msg = {
        'username': 'system',
        'message': message,
        'timestamp': datetime.now(timezone.utc).isoformat(),
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
    """根据座位号获取玩家颜色"""
    gs = room['game_state']
    if gs.get('red_player') == seat:
        return 'red'
    if gs.get('black_player') == seat:
        return 'black'
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
            'check_status': gs.get('check_status', False),
            'move_history': gs.get('move_history', [])
        }
    }, room=room['room_id'])


# ===== Socket.IO Events =====

def register_socketio_events(socketio):

    @socketio.on('create_room', namespace='/game-chess')
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

    @socketio.on('join_room', namespace='/game-chess')
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

    @socketio.on('leave_room', namespace='/game-chess')
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

    @socketio.on('ready', namespace='/game-chess')
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

    @socketio.on('start_game', namespace='/game-chess')
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
                room['players'][0]['role'] = 'red'
            if room['players'][1]:
                room['players'][1]['role'] = 'black'

            emit('game_started', {
                'room_id': room_id,
                'board': gs['board'],
                'current_turn': gs['current_turn'],
                'red_player': gs['red_player'],
                'black_player': gs['black_player'],
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
            emit('new_message', _add_system_message(room, "游戏开始！红方先行"), room=room_id)
        except Exception as e:
            emit('error', {'message': f'开始游戏事件失败: {str(e)}'})

    @socketio.on('move', namespace='/game-chess')
    def on_move(data):
        """走棋"""
        try:
            room_id = data.get('room_id')
            from_x = data.get('from_x')
            from_y = data.get('from_y')
            to_x = data.get('to_x')
            to_y = data.get('to_y')

            if from_x is None or from_y is None or to_x is None or to_y is None:
                emit('error', {'message': '缺少走棋坐标'})
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
            if not (0 <= from_x < 10 and 0 <= from_y < 9 and 0 <= to_x < 10 and 0 <= to_y < 9):
                emit('error', {'message': '坐标超出范围'})
                return

            board = gs['board']
            valid, msg = _validate_move(board, from_x, from_y, to_x, to_y, player_color)
            if not valid:
                emit('error', {'message': msg})
                return

            piece = board[from_x][from_y]
            captured = board[to_x][to_y]

            # 执行走棋
            board[to_x][to_y] = piece
            board[from_x][from_y] = None
            gs['move_history'].append({
                'from_x': from_x,
                'from_y': from_y,
                'to_x': to_x,
                'to_y': to_y,
                'piece': piece,
                'captured': captured,
                'color': player_color
            })

            # 广播走棋结果
            emit('move_result', {
                'room_id': room_id,
                'from_x': from_x,
                'from_y': from_y,
                'to_x': to_x,
                'to_y': to_y,
                'piece': piece,
                'captured': captured,
                'color': player_color,
                'current_turn': gs['current_turn'],
                'next_turn': 'black' if player_color == 'red' else 'red'
            }, room=room_id)

            # 检查是否吃掉对方帅/将（理论上不会发生，因为 _validate_move 会阻止走到被将军的位置，但以防万一）
            if captured and (captured == 'r_king' or captured == 'b_king'):
                winner_seat = gs['red_player'] if player_color == 'red' else gs['black_player']
                _end_game(room, [winner_seat], 'king_captured')
                emit('new_message', _add_system_message(room, f"游戏结束！{'红方' if player_color == 'red' else '黑方'}获胜"), room=room_id)
                return

            # 切换回合
            next_color = 'black' if player_color == 'red' else 'red'
            gs['current_turn'] = next_color

            # 检查对方状态
            if _is_checkmate(board, next_color):
                gs['check_status'] = True
                winner_seat = gs['red_player'] if next_color == 'black' else gs['black_player']
                emit('checkmate', {
                    'room_id': room_id,
                    'color': next_color,
                    'winner': winner_seat
                }, room=room_id)
                _end_game(room, [winner_seat], 'checkmate')
                emit('new_message', _add_system_message(room, f"将死！{'红方' if next_color == 'black' else '黑方'}获胜"), room=room_id)
                return
            elif _is_stalemate(board, next_color):
                emit('stalemate', {'room_id': room_id, 'color': next_color}, room=room_id)
                _end_game(room, [], 'stalemate')
                emit('new_message', _add_system_message(room, "逼和！平局"), room=room_id)
                return
            elif _is_in_check(board, next_color):
                gs['check_status'] = True
                emit('check', {'room_id': room_id, 'color': next_color}, room=room_id)
            else:
                gs['check_status'] = False

        except Exception as e:
            emit('error', {'message': f'走棋事件失败: {str(e)}'})

    @socketio.on('offer_draw', namespace='/game-chess')
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

    @socketio.on('accept_draw', namespace='/game-chess')
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

    @socketio.on('decline_draw', namespace='/game-chess')
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

    @socketio.on('resign', namespace='/game-chess')
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
            winner_seat = gs['black_player'] if player_color == 'red' else gs['red_player']
            emit('game_ended', {
                'room_id': room_id,
                'winners': [winner_seat],
                'reason': 'resign'
            }, room=room_id)
            _end_game(room, [winner_seat], 'resign')
            emit('new_message', _add_system_message(room, f"{current_user.username} 认输，{'黑方' if player_color == 'red' else '红方'}获胜"), room=room_id)
        except Exception as e:
            emit('error', {'message': f'认输失败: {str(e)}'})

    @socketio.on('send_message', namespace='/game-chess')
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
                'timestamp': datetime.now(timezone.utc).isoformat(),
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
