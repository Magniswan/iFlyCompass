import random
from datetime import datetime
from flask_socketio import join_room, leave_room, emit
from flask import current_app
from flask_login import current_user
from . import rooms
from models import GameRecord, UserGameStats
from extensions import db

# ===== UNO No Mercy Card System =====

def _create_deck():
    """创建UNO No Mercy牌组（160张）"""
    colors = ['R', 'Y', 'G', 'B']
    deck = []
    
    # 数字牌 0-9
    for color in colors:
        deck.append(f"{color}0")
        for num in range(1, 10):
            deck.extend([f"{color}{num}", f"{color}{num}"])

    # 经典功能牌（每色1张）
    for color in colors:
        deck.append(f"{color}+2")
        deck.append(f"{color}rev")
        deck.append(f"{color}skip")

    # 经典万能牌
    for _ in range(4):
        deck.append("W")       # 变色
        deck.append("W+4")     # +4

    # 同色全弃牌（每色3张）
    for color in colors:
        for _ in range(3):
            deck.append(f"{color}ac")

    # 新增行动牌
    for _ in range(8):
        deck.append("SE")      # 全场跳过
    for _ in range(8):
        deck.append("N+4")     # +4 (新增万能)
    for _ in range(8):
        deck.append("NR+4")    # 反转+4
    for _ in range(8):
        deck.append("CR")      # 罚抽颜色
    for _ in range(4):
        deck.append("N+6")     # +6
    for _ in range(4):
        deck.append("N+10")    # +10

    random.shuffle(deck)
    return deck

def _card_color(card):
    if card in ('W', 'W+4', 'SE', 'N+4', 'NR+4', 'CR', 'N+6', 'N+10'):
        return 'wild'
    return card[0]

def _card_value(card):
    """获取牌的值部分(用于比较匹配)"""
    if card in ('W', 'SE', 'CR'):
        return card  # 万能牌值就是自身标识
    if card == 'W+4': return '+4'
    if card.startswith('N+4'): return '+4'
    if card.startswith('N+6'): return '+6'
    if card.startswith('N+10'): return '+10'
    if card.startswith('NR'): return '+4'  # NR+4 算 +4
    return card[1:] if len(card) > 1 else ''

def _get_draw_value(card):
    """获取牌的抽牌点数（用于叠加判断）"""
    val = _card_value(card)
    if val == '+2': return 2
    if val == '+4': return 4
    if val == '+6': return 6
    if val == '+10': return 10
    # N+4, NR+4 也算+4
    if card == 'N+4': return 4
    if card == 'NR+4': return 4
    if card == 'N+6': return 6
    if card == 'N+10': return 10
    return 0

def _is_playable(top_card, top_color, hand_card, draw_stack=0):
    """判断手牌是否可以打出"""
    card_val = _card_value(hand_card)
    top_val = _card_value(top_card)
    
    # 有累积惩罚时，只能出抽牌卡且点数>=累积值
    if draw_stack > 0:
        dv = _get_draw_value(hand_card)
        return dv >= draw_stack

    # 万能牌永远可以出
    if _card_color(hand_card) == 'wild':
        return True
    
    # 颜色匹配
    if _card_color(hand_card) == top_color:
        return True
    
    # 数字/符号匹配（顶牌不是万能牌时）
    if _card_color(top_card) != 'wild' and card_val == top_val:
        return True
    
    return False

def _get_next_turn(current_turn, direction, players):
    n = len(players)
    if n == 0:
        return None
    next_turn = current_turn
    for _ in range(n):
        next_turn = (next_turn + direction) % n
        if players[next_turn] is not None and not players[next_turn].get('eliminated', False):
            return next_turn
    return current_turn

def _get_active_seats(room):
    return [i for i, p in enumerate(room['players']) if p is not None and not p.get('eliminated', False)]

def _init_game_state(room):
    deck = _create_deck()
    active_seats = _get_active_seats(room)

    hands = {}
    for seat in active_seats:
        hands[seat] = [deck.pop() for _ in range(7)]

    # 翻底牌，跳过行动牌直到数字牌
    top_card = deck.pop()
    while _card_color(top_card) == 'wild' or _card_value(top_card) in ('+2', 'rev', 'skip', 'ac'):
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
        'draw_stack': 0,
        'rankings': [],
        'uno_called': {},
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
            player_ids = []
            for p in room['players']:
                if p:
                    player_ids.append(p['user_id'])
            winner_ids = [room['players'][s]['user_id'] for s in winner_seats if room['players'][s]]
            loser_ids = [uid for uid in player_ids if uid not in winner_ids]

            record = GameRecord(
                game_type='uno_nomer',
                room_id=room['room_id'],
                started_at=room.get('game_start_time', datetime.utcnow()),
                ended_at=datetime.utcnow(),
                winner_ids=winner_ids,
                winner_names=[room['players'][s]['username'] for s in winner_seats if room['players'][s]],
                loser_ids=loser_ids,
                loser_names=[room['players'][s]['username'] for s in winner_seats if room['players'][s]],
                player_ids=player_ids,
                game_data={'reason': reason}
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
                stats.win_rate = stats.wins / (stats.wins + stats.losses + stats.draws) if (stats.wins + stats.losses + stats.draws) > 0 else 0.0
                stats.last_played = datetime.utcnow()
            db.session.commit()
    except Exception as e:
        print(f"保存游戏记录失败: {e}")

def _add_system_message(room, message):
    msg = {'username': 'system', 'message': message, 'timestamp': datetime.utcnow().isoformat(), 'type': 'system'}
    room['messages'].append(msg)
    if len(room['messages']) > 200:
        room['messages'] = room['messages'][-200:]
    return msg

def _get_player_seat(room, user_id):
    for i, p in enumerate(room['players']):
        if p and p['user_id'] == user_id:
            return i
    return None

def _recycle_discard(gs):
    if len(gs['discard_pile']) > 1:
        top = gs['discard_pile'].pop()
        gs['deck'] = gs['discard_pile'][:]
        gs['discard_pile'] = [top]
        random.shuffle(gs['deck'])

def _draw_cards(gs, count):
    cards = []
    for _ in range(count):
        if not gs['deck']:
            _recycle_discard(gs)
        if gs['deck']:
            cards.append(gs['deck'].pop())
    return cards

def _eliminate_player(room, seat, reason='hand_limit'):
    gs = room['game_state']
    p = room['players'][seat]
    if p and not p.get('eliminated', False):
        p['eliminated'] = True
        # 手牌放入弃牌堆
        if seat in gs['hands']:
            gs['discard_pile'].extend(gs['hands'][seat])
            del gs['hands'][seat]
        if seat not in gs['rankings']:
            gs['rankings'].append(seat)
        emit('player_eliminated', {
            'room_id': room['room_id'],
            'seat': seat,
            'rank': len(gs['rankings']),
            'reason': reason
        }, room=room['room_id'])

def _check_elimination(room, seat):
    """检查是否因手牌>=25而被淘汰，返回True表示被淘汰"""
    gs = room['game_state']
    if seat in gs['hands'] and len(gs['hands'][seat]) >= 25:
        _eliminate_player(room, seat, 'hand_limit')
        return True
    return False

def _check_win(room, seat):
    """检查玩家是否出完手牌"""
    gs = room['game_state']
    if seat in gs['hands'] and not gs['hands'][seat]:
        return True
    return False

def _check_game_over(room):
    """检查游戏是否结束"""
    gs = room['game_state']
    active = _get_active_seats(room)
    
    # 只剩一个活跃玩家 -> 淘汰胜利
    if len(active) <= 1:
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
    _save_game_record(room, winner_seats, reason)
    emit('game_ended', {
        'room_id': room['room_id'],
        'rankings': rankings,
        'reason': reason,
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
                'user_id': p['user_id'], 'username': p['username'],
                'nickname': p['nickname'], 'seat': p['seat'],
                'ready': p['ready'], 'is_online': p['is_online'],
                'eliminated': p.get('eliminated', False)
            } if p else None
            for p in room['players']
        ]
    }

# ===== Socket.IO Events =====

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
            if room and room['players'][0]:
                room['players'][0]['is_online'] = True
                emit('room_created', {'room_id': room_id, 'seat': 0})
                emit('new_message', _add_system_message(room, f"{current_user.username} 创建了房间"), room=room_id)
        except Exception as e:
            emit('error', {'message': f'创建房间失败: {str(e)}'})

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
            emit('room_joined', {'room_id': room_id, 'seat': seat, 'room': _get_room_summary(room)})
            if seat is not None:
                emit('player_joined', {
                    'room_id': room_id, 'seat': seat,
                    'username': current_user.username,
                    'nickname': getattr(current_user, 'nickname', current_user.username),
                    'players': [
                        {
                            'user_id': p['user_id'], 'username': p['username'],
                            'nickname': p['nickname'], 'seat': p['seat'],
                            'ready': p['ready'], 'is_online': p['is_online'],
                            'eliminated': p.get('eliminated', False)
                        } if p else None
                        for p in room['players']
                    ]
                }, room=room_id)
                emit('new_message', _add_system_message(room, f"{current_user.username} 加入了房间"), room=room_id)
        except Exception as e:
            emit('error', {'message': f'加入房间失败: {str(e)}'})

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
                    gs = room['game_state']
                    for s in [s for s in active if s != seat]:
                        if s not in gs['rankings']:
                            gs['rankings'].append(s)
                    _end_game(room, 'creator_left')
                room['status'] = 'ended'
                emit('room_disbanded', {'room_id': room_id, 'reason': 'creator_left'}, room=room_id)
                if room_id in rooms:
                    del rooms[room_id]
                return
            if room['status'] == 'playing':
                p = room['players'][seat]
                if not p.get('eliminated', False):
                    _eliminate_player(room, seat, 'player_left')
                    if _check_game_over(room):
                        _end_game(room, 'player_left')
                        room['status'] = 'ended'
                        emit('room_disbanded', {'room_id': room_id, 'reason': 'player_left'}, room=room_id)
                        if room_id in rooms:
                            del rooms[room_id]
                        return
                else:
                    room['players'][seat] = None
                # 如果是当前回合玩家，切换回合
                gs = room['game_state']
                if gs.get('current_turn') == seat:
                    nxt = _get_next_turn(seat, gs.get('direction', 1), room['players'])
                    gs['current_turn'] = nxt
                    emit('turn_changed', {
                        'room_id': room_id, 'seat': nxt, 'must_play': True,
                        'draw_stack': gs.get('draw_stack', 0)
                    }, room=room_id)
            else:
                room['players'][seat] = None
            emit('player_left', {'room_id': room_id, 'seat': seat, 'username': current_user.username}, room=room_id)
            emit('new_message', _add_system_message(room, f"{current_user.username} 离开了房间"), room=room_id)
        except Exception as e:
            emit('error', {'message': f'离开房间失败: {str(e)}'})

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
            emit('player_ready', {'room_id': room_id, 'seat': seat, 'ready': bool(ready), 'username': current_user.username}, room=room_id)
        except Exception as e:
            emit('error', {'message': f'准备失败: {str(e)}'})

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
            active = [p for p in room['players'] if p is not None]
            if len(active) < 2:
                emit('error', {'message': '需要至少2名玩家'})
                return
            if not all(p['ready'] for p in active):
                emit('error', {'message': '有玩家尚未准备'})
                return
            gs = _init_game_state(room)
            emit('game_started', {
                'room_id': room_id,
                'hands': {str(k): v for k, v in gs['hands'].items()},
                'top_card': gs['top_card'],
                'top_color': gs['top_color'],
                'current_turn': gs['current_turn'],
                'direction': gs['direction'],
                'phase': gs['phase'],
                'draw_stack': 0
            }, room=room_id)
            emit('turn_changed', {
                'room_id': room_id, 'seat': gs['current_turn'],
                'must_play': True, 'draw_stack': 0
            }, room=room_id)
            emit('new_message', _add_system_message(room, "UNO No Mercy 开始！准备好迎接残酷惩罚！"), room=room_id)
        except Exception as e:
            emit('error', {'message': f'开始游戏失败: {str(e)}'})

    @socketio.on('play_card', namespace='/game-uno-nomer')
    def on_play_card(data):
        try:
            room_id = data.get('room_id')
            card = data.get('card')
            chosen_color = data.get('chosen_color')
            target_seat = data.get('target_seat')  # 数字7的目标
            room = rooms.get(room_id)
            if not room:
                emit('error', {'message': '房间不存在'})
                return
            gs = room['game_state']
            if gs['phase'] != 'playing':
                emit('error', {'message': '不在出牌阶段'})
                return
            seat = _get_player_seat(room, current_user.id)
            if seat is None:
                emit('error', {'message': '您不在该房间中'})
                return
            if gs['current_turn'] != seat:
                emit('error', {'message': '不是您的回合'})
                return
            p = room['players'][seat]
            if p.get('eliminated', False):
                emit('error', {'message': '您已被淘汰'})
                return
            hand = gs['hands'].get(seat, [])
            if card not in hand:
                emit('error', {'message': '您没有这张牌'})
                return

            draw_stack = gs.get('draw_stack', 0)
            if not _is_playable(gs['top_card'], gs['top_color'], card, draw_stack):
                emit('error', {'message': '这张牌无法打出'})
                return

            # 重置UNO状态
            gs['uno_called'].pop(str(seat), None)

            # 打出牌
            hand.remove(card)
            gs['discard_pile'].append(card)
            gs['top_card'] = card

            # 处理万能牌选色
            if _card_color(card) == 'wild':
                if not chosen_color or chosen_color not in ('R', 'Y', 'G', 'B'):
                    emit('error', {'message': '请选择颜色'})
                    return
                gs['top_color'] = chosen_color
            else:
                gs['top_color'] = _card_color(card)

            card_val = _card_value(card)
            card_draw = _get_draw_value(card)
            direction = gs['direction']
            skip_next = False
            effects = []

            # ---- 处理各种牌的特殊效果 ----

            # 数字7：与目标交换手牌
            if card_val == '7':
                if target_seat is not None and target_seat != seat:
                    target_hand = gs['hands'].get(target_seat)
                    if target_hand is not None:
                        gs['hands'][seat], gs['hands'][target_seat] = target_hand, hand
                        effects.append('hand_swap')
                        emit('hands_swapped', {
                            'room_id': room_id, 'seat1': seat, 'seat2': target_seat
                        }, room=room_id)

            # 数字0：全体传递手牌
            elif card_val == '0':
                active = [s for s in _get_active_seats(room) if s != seat]
                if active:
                    ordered = []
                    cur = seat
                    for _ in range(len(active) + 1):
                        nxt = _get_next_turn(cur, direction, room['players'])
                        if nxt == seat or nxt in ordered:
                            break
                        ordered.append(nxt)
                        cur = nxt
                    if ordered:
                        hands_snapshot = {s: gs['hands'].get(s, [])[:] for s in [seat] + ordered}
                        for i, s in enumerate([seat] + ordered):
                            prev_s = ordered[-1] if i == 0 else ([seat] + ordered)[i - 1]
                            gs['hands'][s] = hands_snapshot[prev_s]
                        effects.append('hands_pass')

            # 反转
            elif card_val == 'rev':
                gs['direction'] *= -1
                # 2人时反转=跳过
                if len(_get_active_seats(room)) == 2:
                    skip_next = True

            # 跳过
            elif card_val == 'skip':
                skip_next = True

            # 全场跳过
            elif card == 'SE':
                # 当前玩家再获得一个回合
                pass  # 不改变turn

            # 反转+4
            elif card == 'NR+4':
                gs['direction'] *= -1
                gs['draw_stack'] = draw_stack + 4

            # 抽牌卡（+2, +4, +6, +10, N+4, N+6, N+10）
            elif card_draw > 0:
                gs['draw_stack'] = draw_stack + card_draw

            # 罚抽颜色
            elif card == 'CR':
                # 下家选颜色，抽到为止
                _emit_color_roulette(room, seat)
                # 效果在CR处理中
                pass

            # 同色全弃
            elif card_val == 'ac':
                color = _card_color(card)
                for s, h in list(gs['hands'].items()):
                    if s == seat:
                        continue
                    discarded = [c for c in h if _card_color(c) == color]
                    for c in discarded:
                        h.remove(c)
                        gs['discard_pile'].append(c)
                    gs['hands'][s] = h
                if seat in gs['hands']:
                    self_discard = [c for c in gs['hands'][seat] if _card_color(c) == color]
                    for c in self_discard:
                        gs['hands'][seat].remove(c)
                        gs['discard_pile'].append(c)
                effects.append(f'all_discard_{color}')
                # 广播所有玩家更新后的手牌数
                hands_count = {str(s): len(h) for s, h in gs['hands'].items()}
                emit('hands_updated', {
                    'room_id': room_id, 'hands_count': hands_count
                }, room=room_id)

            # W（经典变色）
            elif card == 'W':
                pass

            # 检查出完手牌 -> 排名
            if seat in gs['hands'] and not gs['hands'][seat]:
                if seat not in gs['rankings']:
                    gs['rankings'].append(seat)
                emit('player_eliminated', {
                    'room_id': room_id, 'seat': seat,
                    'rank': len(gs['rankings']), 'reason': 'empty_hand'
                }, room=room_id)
                player_name = room['players'][seat]['username'] if room['players'][seat] else '玩家'
                emit('new_message', _add_system_message(room, f"{player_name} 出完了手牌，获得第{len(gs['rankings'])}名！"), room=room_id)
                if _check_game_over(room):
                    _end_game(room, 'cards_finished')
                    return
                next_turn = _get_next_turn(seat, gs['direction'], room['players'])
                gs['current_turn'] = next_turn
                emit('card_played', {
                    'room_id': room_id, 'seat': seat, 'card': card,
                    'top_color': gs['top_color'], 'top_card': gs['top_card'],
                    'remaining': 0, 'draw_stack': gs['draw_stack'],
                    'effects': effects
                }, room=room_id)
                emit('turn_changed', {
                    'room_id': room_id, 'seat': next_turn,
                    'must_play': True, 'draw_stack': gs['draw_stack']
                }, room=room_id)
                return

            # 检查25张淘汰
            if _check_elimination(room, seat):
                emit('card_played', {
                    'room_id': room_id, 'seat': seat, 'card': card,
                    'top_color': gs['top_color'], 'top_card': gs['top_card'],
                    'remaining': len(gs['hands'].get(seat, [])),
                    'draw_stack': gs.get('draw_stack', 0), 'effects': effects
                }, room=room_id)
                if _check_game_over(room):
                    _end_game(room, 'elimination')
                    return
                next_turn = _get_next_turn(seat, gs['direction'], room['players'])
                gs['current_turn'] = next_turn
                emit('turn_changed', {
                    'room_id': room_id, 'seat': next_turn,
                    'must_play': True, 'draw_stack': gs.get('draw_stack', 0)
                }, room=room_id)
                return

            # 计算下一个玩家
            next_turn = _get_next_turn(seat, direction, room['players'])

            # 全场跳过
            if card == 'SE':
                gs['current_turn'] = seat  # 自己再出
            elif skip_next:
                gs['current_turn'] = _get_next_turn(next_turn, direction, room['players'])
            else:
                gs['current_turn'] = next_turn

            emit('card_played', {
                'room_id': room_id, 'seat': seat, 'card': card,
                'chosen_color': gs['top_color'] if _card_color(card) == 'wild' else None,
                'top_color': gs['top_color'], 'top_card': gs['top_card'],
                'remaining': len(gs['hands'].get(seat, [])),
                'draw_stack': gs.get('draw_stack', 0),
                'effects': effects
            }, room=room_id)

            emit('turn_changed', {
                'room_id': room_id, 'seat': gs['current_turn'],
                'must_play': True, 'draw_stack': gs.get('draw_stack', 0)
            }, room=room_id)
        except Exception as e:
            emit('error', {'message': f'出牌失败: {str(e)}'})

    def _emit_color_roulette(room, from_seat):
        """告知下家需要接受罚抽颜色惩罚：选色->抽到该色为止"""
        gs = room['game_state']
        next_seat = _get_next_turn(from_seat, gs['direction'], room['players'])
        emit('color_roulette', {
            'room_id': room['room_id'],
            'seat': next_seat,
            'from_seat': from_seat
        }, room=room['room_id'])

    @socketio.on('color_roulette_pick', namespace='/game-uno-nomer')
    def on_color_roulette_pick(data):
        """罚抽颜色：玩家选色后，抽牌直到抽到该色"""
        try:
            room_id = data.get('room_id')
            color = data.get('color')
            room = rooms.get(room_id)
            if not room or color not in ('R', 'Y', 'G', 'B'):
                return
            gs = room['game_state']
            seat = _get_player_seat(room, current_user.id)
            if seat is None or seat not in gs['hands']:
                return
            hand = gs['hands'][seat]
            drawn = []
            while True:
                if not gs['deck']:
                    _recycle_discard(gs)
                if not gs['deck']:
                    break
                c = gs['deck'].pop()
                drawn.append(c)
                hand.append(c)
                if _card_color(c) == color:
                    break
            gs['hands'][seat] = hand
            emit('player_drew', {
                'room_id': room_id, 'seat': seat,
                'cards': drawn, 'count': len(drawn),
                'reason': 'color_roulette'
            }, room=room_id)
            _check_elimination(room, seat)
            if _check_game_over(room):
                _end_game(room, 'elimination')
                return
            next_turn = _get_next_turn(seat, gs['direction'], room['players'])
            gs['current_turn'] = next_turn
            emit('turn_changed', {
                'room_id': room_id, 'seat': next_turn,
                'must_play': True, 'draw_stack': gs.get('draw_stack', 0)
            }, room=room_id)
        except Exception as e:
            emit('error', {'message': f'罚抽颜色失败: {str(e)}'})

    @socketio.on('draw_card', namespace='/game-uno-nomer')
    def on_draw_card(data):
        """抽牌：有draw_stack时接受惩罚，无draw_stack时抽到能出为止"""
        try:
            room_id = data.get('room_id')
            room = rooms.get(room_id)
            if not room:
                emit('error', {'message': '房间不存在'})
                return
            gs = room['game_state']
            if gs['phase'] != 'playing':
                return
            seat = _get_player_seat(room, current_user.id)
            if seat is None or gs['current_turn'] != seat:
                emit('error', {'message': '不是您的回合'})
                return
            p = room['players'][seat]
            if p.get('eliminated', False):
                return
            hand = gs['hands'].get(seat, [])
            draw_stack = gs.get('draw_stack', 0)
            drawn = []

            if draw_stack > 0:
                # 接受累积惩罚
                gs['draw_stack'] = 0
                drawn = _draw_cards(gs, draw_stack)
                hand.extend(drawn)
                gs['hands'][seat] = hand
                emit('player_drew', {
                    'room_id': room_id, 'seat': seat,
                    'cards': drawn, 'count': len(drawn),
                    'reason': 'stack_penalty'
                }, room=room_id)
                _check_elimination(room, seat)
                if _check_game_over(room):
                    _end_game(room, 'elimination')
                    return
                next_turn = _get_next_turn(seat, gs['direction'], room['players'])
                gs['current_turn'] = next_turn
                emit('turn_changed', {
                    'room_id': room_id, 'seat': next_turn,
                    'must_play': True, 'draw_stack': 0
                }, room=room_id)
                return

            # 普通抽牌：抽到能出为止
            while True:
                if not gs['deck']:
                    _recycle_discard(gs)
                if not gs['deck']:
                    break
                c = gs['deck'].pop()
                drawn.append(c)
                hand.append(c)
                if _is_playable(gs['top_card'], gs['top_color'], c):
                    # 抽到可出的牌后，自动打出
                    hand.remove(c)
                    gs['discard_pile'].append(c)
                    gs['top_card'] = c
                    if _card_color(c) != 'wild':
                        gs['top_color'] = _card_color(c)
                    # 处理特殊效果（简化版）
                    card_draw = _get_draw_value(c)
                    if card_draw > 0:
                        gs['draw_stack'] = card_draw
                    if _card_value(c) == 'skip' or (_card_value(c) == 'rev' and len(_get_active_seats(room)) == 2):
                        emit('card_played', {
                            'room_id': room_id, 'seat': seat, 'card': c,
                            'top_color': gs['top_color'], 'top_card': gs['top_card'],
                            'remaining': len(hand), 'draw_stack': gs.get('draw_stack', 0), 'auto_play': True
                        }, room=room_id)
                        emit('player_drew', {
                            'room_id': room_id, 'seat': seat,
                            'cards': drawn, 'count': len(drawn),
                            'reason': 'draw_to_play', 'auto_played': c
                        }, room=room_id)
                        _check_elimination(room, seat)
                        if _check_game_over(room):
                            _end_game(room, 'elimination')
                            return
                        next_turn = _get_next_turn(_get_next_turn(seat, gs['direction'], room['players']), gs['direction'], room['players'])
                        gs['current_turn'] = next_turn
                        emit('turn_changed', {
                            'room_id': room_id, 'seat': next_turn,
                            'must_play': True, 'draw_stack': gs.get('draw_stack', 0)
                        }, room=room_id)
                        return
                    # 检查出完
                    if not hand:
                        if seat not in gs['rankings']:
                            gs['rankings'].append(seat)
                        emit('player_eliminated', {
                            'room_id': room_id, 'seat': seat,
                            'rank': len(gs['rankings']), 'reason': 'empty_hand'
                        }, room=room_id)
                        if _check_game_over(room):
                            _end_game(room, 'cards_finished')
                            return
                    emit('card_played', {
                        'room_id': room_id, 'seat': seat, 'card': c,
                        'top_color': gs['top_color'], 'top_card': gs['top_card'],
                        'remaining': len(hand), 'draw_stack': gs.get('draw_stack', 0), 'auto_play': True
                    }, room=room_id)
                    emit('player_drew', {
                        'room_id': room_id, 'seat': seat,
                        'cards': drawn, 'count': len(drawn),
                        'reason': 'draw_to_play', 'auto_played': c
                    }, room=room_id)
                    _check_elimination(room, seat)
                    if _check_game_over(room):
                        _end_game(room, 'elimination')
                        return
                    next_turn = _get_next_turn(seat, gs['direction'], room['players'])
                    gs['current_turn'] = next_turn
                    emit('turn_changed', {
                        'room_id': room_id, 'seat': next_turn,
                        'must_play': True, 'draw_stack': gs.get('draw_stack', 0)
                    }, room=room_id)
                    return
                # 检查25张淘汰
                gs['hands'][seat] = hand
                if _check_elimination(room, seat):
                    emit('player_drew', {
                        'room_id': room_id, 'seat': seat,
                        'cards': drawn, 'count': len(drawn),
                        'reason': 'draw_to_play'
                    }, room=room_id)
                    if _check_game_over(room):
                        _end_game(room, 'elimination')
                        return
                    next_turn = _get_next_turn(seat, gs['direction'], room['players'])
                    gs['current_turn'] = next_turn
                    emit('turn_changed', {
                        'room_id': room_id, 'seat': next_turn,
                        'must_play': True, 'draw_stack': 0
                    }, room=room_id)
                    return

            # 牌堆耗尽且没有抽到可出的牌
            gs['hands'][seat] = hand
            emit('player_drew', {
                'room_id': room_id, 'seat': seat,
                'cards': drawn, 'count': len(drawn),
                'reason': 'draw_to_play'
            }, room=room_id)
            next_turn = _get_next_turn(seat, gs['direction'], room['players'])
            gs['current_turn'] = next_turn
            emit('turn_changed', {
                'room_id': room_id, 'seat': next_turn,
                'must_play': True, 'draw_stack': 0
            }, room=room_id)
        except Exception as e:
            emit('error', {'message': f'抽牌失败: {str(e)}'})

    @socketio.on('call_uno', namespace='/game-uno-nomer')
    def on_call_uno(data):
        """喊UNO"""
        try:
            room_id = data.get('room_id')
            room = rooms.get(room_id)
            if not room:
                return
            seat = _get_player_seat(room, current_user.id)
            if seat is None:
                return
            gs = room['game_state']
            gs['uno_called'][str(seat)] = True
            emit('uno_called', {
                'room_id': room_id, 'seat': seat,
                'username': current_user.username,
                'nickname': getattr(current_user, 'nickname', current_user.username)
            }, room=room_id)
        except Exception as e:
            emit('error', {'message': f'喊UNO失败: {str(e)}'})

    @socketio.on('catch_uno', namespace='/game-uno-nomer')
    def on_catch_uno(data):
        """抓住未喊UNO的玩家"""
        try:
            room_id = data.get('room_id')
            target_seat = data.get('target_seat')
            room = rooms.get(room_id)
            if not room or target_seat is None:
                return
            gs = room['game_state']
            if target_seat not in gs['hands']:
                return
            target_hand = gs['hands'][target_seat]
            if len(target_hand) == 1 and not gs['uno_called'].get(str(target_seat)):
                drawn = _draw_cards(gs, 2)
                target_hand.extend(drawn)
                gs['hands'][target_seat] = target_hand
                gs['uno_called'][str(target_seat)] = False
                emit('uno_penalty', {
                    'room_id': room_id, 'seat': target_seat, 'count': 2
                }, room=room_id)
                emit('new_message', _add_system_message(room, f"{room['players'][target_seat]['username']} 忘记喊UNO，被罚抽2张牌！"), room=room_id)
                _check_elimination(room, target_seat)
                if _check_game_over(room):
                    _end_game(room, 'elimination')
        except Exception as e:
            emit('error', {'message': f'抓UNO失败: {str(e)}'})

    @socketio.on('send_message', namespace='/game-uno-nomer')
    def on_send_message(data):
        try:
            room_id = data.get('room_id')
            message = data.get('message', '').strip()
            if not room_id or not message:
                return
            room = rooms.get(room_id)
            if not room:
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
