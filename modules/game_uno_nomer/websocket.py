import random
from datetime import datetime
from flask_socketio import join_room, leave_room, emit
from flask import current_app
from flask_login import current_user
from . import rooms
from models import GameRecord, UserGameStats
from extensions import db

# ===== UNO No Mercy Card Helpers =====

def _create_deck():
    """创建UNO No Mercy牌组（包含+6, +10）"""
    colors = ['R', 'Y', 'G', 'B']
    deck = []
    for color in colors:
        deck.append(f"{color}0")
        for num in range(1, 10):
            deck.extend([f"{color}{num}", f"{color}{num}"])
        deck.extend([f"{color}+2", f"{color}+2"])
        deck.extend([f"{color}+6", f"{color}+6"])
        deck.extend([f"{color}+10", f"{color}+10"])
        deck.extend([f"{color}skip", f"{color}skip"])
        deck.extend([f"{color}reverse", f"{color}reverse"])
    for _ in range(4):
        deck.append("W")
        deck.append("W+4")
        deck.append("W+6")
        deck.append("W+10")
    random.shuffle(deck)
    return deck

def _card_color(card):
    if card.startswith('W'):
        return 'wild'
    return card[0]

def _card_value(card):
    return card[1:]

def _is_playable(top_card, top_color, hand_card, chosen_color=None):
    if hand_card.startswith('W'):
        return True
    hand_color = _card_color(hand_card)
    hand_value = _card_value(hand_card)
    top_value = _card_value(top_card)
    if hand_color == top_color:
        return True
    if hand_value == top_value and not top_card.startswith('W'):
        return True
    return False

def _get_draw_value(card):
    """获取牌的抽牌惩罚值"""
    val = _card_value(card)
    if val == '+2':
        return 2
    if val == '+4':
        return 4
    if val == '+6':
        return 6
    if val == '+10':
        return 10
    return 0

def _can_stack(stack_card, played_card):
    """判断是否可以叠加惩罚牌"""
    sv = _get_draw_value(stack_card)
    pv = _get_draw_value(played_card)
    if sv == 0 or pv == 0:
        return False
    # No Mercy规则：任何惩罚牌都可以叠在任何惩罚牌上
    return True

def _get_next_turn(current_turn, direction, players, game_state=None):
    n = len(players)
    if n == 0:
        return None
    next_turn = (current_turn + direction) % n
    attempts = 0
    while (players[next_turn] is None or players[next_turn].get('eliminated', False)) and attempts < n:
        next_turn = (next_turn + direction) % n
        attempts += 1
    return next_turn

def _get_active_seats(room):
    return [i for i, p in enumerate(room['players']) if p is not None and not p.get('eliminated', False)]

def _init_game_state(room):
    deck = _create_deck()
    active_seats = _get_active_seats(room)
    num_players = len(active_seats)

    hands = {}
    for seat in active_seats:
        hands[seat] = [deck.pop() for _ in range(7)]

    top_card = deck.pop()
    top_color = _card_color(top_card)
    while top_color == 'wild':
        deck.insert(0, top_card)
        random.shuffle(deck)
        top_card = deck.pop()
        top_color = _card_color(top_card)

    current_turn = active_seats[0]

    game_state = {
        'hands': hands,
        'deck': deck,
        'discard_pile': [top_card],
        'top_card': top_card,
        'top_color': top_color,
        'current_turn': current_turn,
        'direction': 1,
        'phase': 'playing',
        'last_action': None,
        'winner': None,
        'draw_stack': 0,
        'rankings': [],
        'stacking': False,
    }

    room['game_state'] = game_state
    room['status'] = 'playing'
    room['game_start_time'] = datetime.utcnow()

    for p in room['players']:
        if p:
            p['ready'] = False
            p['eliminated'] = False

    return game_state

def _save_game_record(room, winner_seats, reason=''):
    try:
        with current_app.app_context():
            winner_ids = []
            loser_ids = []
            player_ids = []
            winner_names = []
            loser_names = []

            for p in room['players']:
                if p:
                    player_ids.append(p['user_id'])
                    if p['seat'] in winner_seats:
                        winner_ids.append(p['user_id'])
                        winner_names.append(p['username'])
                    else:
                        loser_ids.append(p['user_id'])
                        loser_names.append(p['username'])

            record = GameRecord(
                game_type='uno_nomer',
                room_id=room['room_id'],
                started_at=room.get('game_start_time', datetime.utcnow()),
                ended_at=datetime.utcnow(),
                winner_ids=winner_ids,
                winner_names=winner_names,
                loser_ids=loser_ids,
                loser_names=loser_names,
                player_ids=player_ids,
                game_data={'reason': reason, 'final_state': {k: v for k, v in room.get('game_state', {}).items() if k != 'hands'}}
            )
            db.session.add(record)

            for p in room['players']:
                if not p:
                    continue
                user_id = p['user_id']
                stats = UserGameStats.query.filter_by(user_id=user_id, game_type='uno_nomer').first()
                if not stats:
                    stats = UserGameStats(user_id=user_id, game_type='uno_nomer')
                    db.session.add(stats)

                stats.total_games += 1
                if user_id in winner_ids:
                    stats.wins += 1
                else:
                    stats.losses += 1

                total = stats.wins + stats.losses + stats.draws
                stats.win_rate = stats.wins / total if total > 0 else 0.0
                stats.last_played = datetime.utcnow()

            db.session.commit()
    except Exception as e:
        print(f"保存游戏记录失败: {e}")

def _add_system_message(room, message):
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
    for i, p in enumerate(room['players']):
        if p and p['user_id'] == user_id:
            return i
    return None

def _eliminate_player(room, seat):
    """淘汰玩家"""
    gs = room['game_state']
    p = room['players'][seat]
    if p:
        p['eliminated'] = True
    if seat not in gs['rankings']:
        gs['rankings'].append(seat)
    emit('player_eliminated', {
        'room_id': room['room_id'],
        'seat': seat,
        'rank': len(gs['rankings'])
    }, room=room['room_id'])

def _check_game_over(room):
    """检查游戏是否结束（只剩一人未淘汰）"""
    active = _get_active_seats(room)
    if len(active) <= 1:
        # 把最后一人加入排名（最后一名）
        gs = room['game_state']
        if active and active[0] not in gs['rankings']:
            gs['rankings'].append(active[0])
        return True
    return False

def _end_game(room, reason=''):
    gs = room['game_state']
    gs['phase'] = 'ended'
    room['status'] = 'ended'
    rankings = gs.get('rankings', [])
    winner_seats = rankings[:1] if rankings else []
    winner_ids = []
    for seat in winner_seats:
        p = room['players'][seat]
        if p:
            winner_ids.append(p['user_id'])

    _save_game_record(room, winner_ids, reason)

    emit('game_ended', {
        'room_id': room['room_id'],
        'rankings': rankings,
        'reason': reason,
        'game_state': {
            'hands': {str(k): v for k, v in gs['hands'].items()}
        }
    }, room=room['room_id'])

def _get_room_summary(room):
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
                'is_online': p['is_online'],
                'eliminated': p.get('eliminated', False)
            } if p else None
            for p in room['players']
        ]
    }

def register_socketio_events(socketio):

    @socketio.on('create_room', namespace='/game-uno-nomer')
    def on_create_room(data):
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

    @socketio.on('join_room', namespace='/game-uno-nomer')
    def on_join_room(data):
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
                            'is_online': p['is_online'],
                            'eliminated': p.get('eliminated', False)
                        } if p else None
                        for p in room['players']
                    ]
                }, room=room_id)
                emit('new_message', _add_system_message(room, f"{current_user.username} 加入了房间"), room=room_id)
        except Exception as e:
            emit('error', {'message': f'加入房间事件失败: {str(e)}'})

    @socketio.on('leave_room', namespace='/game-uno-nomer')
    def on_leave_room(data):
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
                    active = _get_active_seats(room)
                    remaining = [s for s in active if s != seat]
                    if remaining:
                        # 把剩余未淘汰的人都算入排名
                        gs = room['game_state']
                        for s in remaining:
                            if s not in gs['rankings']:
                                gs['rankings'].append(s)
                        _end_game(room, 'creator_left')
                room['status'] = 'ended'
                emit('room_disbanded', {'room_id': room_id, 'reason': 'creator_left'}, room=room_id)
                if room_id in rooms:
                    del rooms[room_id]
                return
            # 普通玩家离开
            # 如果游戏中且未淘汰，则算淘汰
            if room['status'] == 'playing' and not room['players'][seat].get('eliminated', False):
                _eliminate_player(room, seat)
                if _check_game_over(room):
                    _end_game(room, 'player_left')
                    room['status'] = 'ended'
                    emit('room_disbanded', {'room_id': room_id, 'reason': 'player_left'}, room=room_id)
                    if room_id in rooms:
                        del rooms[room_id]
                    return
                # 如果是当前回合玩家离开，切换回合
                gs = room['game_state']
                if gs['current_turn'] == seat:
                    next_turn = _get_next_turn(seat, gs['direction'], room['players'], gs)
                    gs['current_turn'] = next_turn
                    emit('turn_changed', {
                        'room_id': room_id,
                        'seat': next_turn,
                        'must_play': True
                    }, room=room_id)
            else:
                room['players'][seat] = None
                if room['status'] == 'playing':
                    # 检查是否所有人都离开了或结束了
                    active = _get_active_seats(room)
                    if len(active) <= 1:
                        _end_game(room, 'player_left')
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

    @socketio.on('ready', namespace='/game-uno-nomer')
    def on_ready(data):
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

    @socketio.on('start_game', namespace='/game-uno-nomer')
    def on_start_game(data):
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
            if len(active_players) < 3:
                emit('error', {'message': '需要至少3名玩家才能开始游戏'})
                return
            if not all(p['ready'] for p in active_players):
                emit('error', {'message': '有玩家尚未准备'})
                return
            gs = _init_game_state(room)
            active_seats = _get_active_seats(room)
            emit('game_started', {
                'room_id': room_id,
                'hands': {str(k): v for k, v in gs['hands'].items()},
                'top_card': gs['top_card'],
                'top_color': gs['top_color'],
                'current_turn': gs['current_turn'],
                'direction': gs['direction'],
                'phase': gs['phase']
            }, room=room_id)
            emit('turn_changed', {
                'room_id': room_id,
                'seat': gs['current_turn'],
                'must_play': True,
                'draw_stack': 0
            }, room=room_id)
            emit('new_message', _add_system_message(room, "UNO No Mercy 开始！准备好接受残酷惩罚了吗？"), room=room_id)
        except Exception as e:
            emit('error', {'message': f'开始游戏事件失败: {str(e)}'})

    @socketio.on('play_card', namespace='/game-uno-nomer')
    def on_play_card(data):
        try:
            room_id = data.get('room_id')
            card = data.get('card')
            chosen_color = data.get('chosen_color')
            room = rooms.get(room_id)
            if not room:
                emit('error', {'message': '房间不存在'})
                return
            gs = room['game_state']
            if gs['phase'] != 'playing':
                emit('error', {'message': '游戏不在出牌阶段'})
                return
            seat = _get_player_seat(room, current_user.id)
            if seat is None:
                emit('error', {'message': '您不在该房间中'})
                return
            if gs['current_turn'] != seat:
                emit('error', {'message': '不是您的回合'})
                return
            if room['players'][seat].get('eliminated', False):
                emit('error', {'message': '您已被淘汰'})
                return

            hand = gs['hands'][seat]
            if card not in hand:
                emit('error', {'message': '您没有这张牌'})
                return

            top_card = gs['top_card']
            top_color = gs['top_color']
            draw_stack = gs.get('draw_stack', 0)
            card_draw_val = _get_draw_value(card)

            # 如果有累积惩罚，必须出惩罚牌（可叠加）或接受惩罚
            if draw_stack > 0:
                if card_draw_val > 0 and _can_stack(top_card, card):
                    pass  # 允许叠加
                else:
                    emit('error', {'message': f'当前有累积惩罚 {draw_stack} 张，您必须出惩罚牌叠加或抽牌接受惩罚'})
                    return
            else:
                if not _is_playable(top_card, top_color, card, chosen_color):
                    emit('error', {'message': '这张牌不能打出'})
                    return

            # 打出牌
            hand.remove(card)
            gs['discard_pile'].append(card)
            gs['top_card'] = card
            if card.startswith('W'):
                if not chosen_color or chosen_color not in ['R', 'Y', 'G', 'B']:
                    emit('error', {'message': '请选择颜色'})
                    return
                gs['top_color'] = chosen_color
            else:
                gs['top_color'] = _card_color(card)

            # 处理惩罚累积
            if card_draw_val > 0:
                gs['draw_stack'] = draw_stack + card_draw_val
            else:
                gs['draw_stack'] = 0

            active_seats = _get_active_seats(room)
            n = len(active_seats)
            next_turn = _get_next_turn(seat, gs['direction'], room['players'], gs)
            skip_next = False

            card_value = _card_value(card)
            if card_value == 'skip':
                skip_next = True
            elif card_value == 'reverse':
                gs['direction'] *= -1
                if n == 2:
                    skip_next = True

            # 检查是否出完手牌 -> 淘汰/排名
            if not hand:
                _eliminate_player(room, seat)
                if _check_game_over(room):
                    _end_game(room, 'cards_finished')
                    return
                # 如果当前玩家被淘汰且是他回合，需要传回合
                next_turn = _get_next_turn(seat, gs['direction'], room['players'], gs)
                gs['current_turn'] = next_turn
                emit('card_played', {
                    'room_id': room_id,
                    'seat': seat,
                    'card': card,
                    'chosen_color': gs['top_color'] if card.startswith('W') else None,
                    'top_color': gs['top_color'],
                    'top_card': gs['top_card'],
                    'remaining': 0,
                    'draw_stack': gs['draw_stack']
                }, room=room_id)
                emit('turn_changed', {
                    'room_id': room_id,
                    'seat': gs['current_turn'],
                    'must_play': True,
                    'draw_stack': gs['draw_stack']
                }, room=room_id)
                return

            # 计算下一个玩家
            if skip_next:
                next_turn = _get_next_turn(next_turn, gs['direction'], room['players'], gs)

            gs['current_turn'] = next_turn
            emit('card_played', {
                'room_id': room_id,
                'seat': seat,
                'card': card,
                'chosen_color': gs['top_color'] if card.startswith('W') else None,
                'top_color': gs['top_color'],
                'top_card': gs['top_card'],
                'remaining': len(hand),
                'draw_stack': gs['draw_stack']
            }, room=room_id)
            emit('turn_changed', {
                'room_id': room_id,
                'seat': gs['current_turn'],
                'must_play': True,
                'draw_stack': gs['draw_stack']
            }, room=room_id)
        except Exception as e:
            emit('error', {'message': f'出牌事件失败: {str(e)}'})

    @socketio.on('draw_card', namespace='/game-uno-nomer')
    def on_draw_card(data):
        try:
            room_id = data.get('room_id')
            room = rooms.get(room_id)
            if not room:
                emit('error', {'message': '房间不存在'})
                return
            gs = room['game_state']
            if gs['phase'] != 'playing':
                emit('error', {'message': '游戏不在出牌阶段'})
                return
            seat = _get_player_seat(room, current_user.id)
            if seat is None:
                emit('error', {'message': '您不在该房间中'})
                return
            if gs['current_turn'] != seat:
                emit('error', {'message': '不是您的回合'})
                return
            if room['players'][seat].get('eliminated', False):
                emit('error', {'message': '您已被淘汰'})
                return

            hand = gs['hands'][seat]
            draw_stack = gs.get('draw_stack', 0)
            drawn = []

            # 如果有累积惩罚，接受惩罚
            if draw_stack > 0:
                count = draw_stack
                gs['draw_stack'] = 0
                for _ in range(count):
                    if not gs['deck']:
                        if len(gs['discard_pile']) > 1:
                            top = gs['discard_pile'].pop()
                            gs['deck'] = gs['discard_pile'][:]
                            gs['discard_pile'] = [top]
                            random.shuffle(gs['deck'])
                    if gs['deck']:
                        c = gs['deck'].pop()
                        drawn.append(c)
                        hand.append(c)
                gs['hands'][seat] = hand
                emit('player_drew', {
                    'room_id': room_id,
                    'seat': seat,
                    'cards': drawn,
                    'count': len(drawn),
                    'reason': 'stack_penalty'
                }, room=room_id)
                next_turn = _get_next_turn(seat, gs['direction'], room['players'], gs)
                gs['current_turn'] = next_turn
                emit('turn_changed', {
                    'room_id': room_id,
                    'seat': gs['current_turn'],
                    'must_play': True,
                    'draw_stack': 0
                }, room=room_id)
                return

            # 普通抽牌
            if gs['deck']:
                drawn_card = gs['deck'].pop()
                drawn.append(drawn_card)
                hand.append(drawn_card)
            else:
                if len(gs['discard_pile']) > 1:
                    top = gs['discard_pile'].pop()
                    gs['deck'] = gs['discard_pile'][:]
                    gs['discard_pile'] = [top]
                    random.shuffle(gs['deck'])
                    if gs['deck']:
                        drawn_card = gs['deck'].pop()
                        drawn.append(drawn_card)
                        hand.append(drawn_card)

            can_play = False
            if drawn:
                can_play = _is_playable(gs['top_card'], gs['top_color'], drawn[0])
            gs['hands'][seat] = hand
            emit('player_drew', {
                'room_id': room_id,
                'seat': seat,
                'cards': drawn,
                'count': len(drawn),
                'can_play': can_play,
                'reason': 'draw'
            }, room=room_id)
            if not can_play or not drawn:
                next_turn = _get_next_turn(seat, gs['direction'], room['players'], gs)
                gs['current_turn'] = next_turn
                emit('turn_changed', {
                    'room_id': room_id,
                    'seat': gs['current_turn'],
                    'must_play': True,
                    'draw_stack': 0
                }, room=room_id)
        except Exception as e:
            emit('error', {'message': f'抽牌事件失败: {str(e)}'})

    @socketio.on('send_message', namespace='/game-uno-nomer')
    def on_send_message(data):
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
