import random
from datetime import datetime, timezone
from flask_socketio import join_room, leave_room, emit
from flask import current_app
from flask_login import current_user
from . import rooms
from .effects import (
    _card_color, _card_value, _get_draw_value, is_playable,
    apply_card_effect, _get_next_turn, _active_seats,
    recycle_discard, draw_from_deck
)
from .game import (
    check_elimination, check_empty_hand, check_game_over,
    end_game, advance_turn_after_play, init_game_state
)


def _player_seat(room, user_id):
    for i, p in enumerate(room['players']):
        if p and p['user_id'] == user_id:
            return i
    return None


def _system_msg(room, message):
    msg = {'username': 'system', 'message': message, 'timestamp': datetime.now(timezone.utc).isoformat(), 'type': 'system'}
    room['messages'].append(msg)
    if len(room['messages']) > 200:
        room['messages'] = room['messages'][-200:]
    return msg


def _room_summary(room):
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


def _broadcast_card_played(room, seat, card, effects):
    gs = room['game_state']
    emit('card_played', {
        'room_id': room['room_id'], 'seat': seat, 'card': card,
        'chosen_color': gs['top_color'] if _card_color(card) == 'wild' else None,
        'top_color': gs['top_color'], 'top_card': gs['top_card'],
        'remaining': len(gs['hands'].get(seat, [])),
        'draw_stack': gs.get('draw_stack', 0),
        'effects': effects,
        'hand_counts': {str(s): len(h) for s, h in gs['hands'].items()}
    }, room=room['room_id'])


def _broadcast_turn_change(room, next_turn):
    gs = room['game_state']
    emit('turn_changed', {
        'room_id': room['room_id'], 'seat': next_turn,
        'must_play': True, 'draw_stack': gs.get('draw_stack', 0)
    }, room=room['room_id'])


def _broadcast_effects(room, seat, effects):
    """广播卡牌特殊效果（交换/传递/全弃）"""
    gs = room['game_state']
    room_id = room['room_id']

    # 同色全弃
    for eff in effects:
        if eff.startswith('all_discard_'):
            hands_count = {str(s): len(h) for s, h in gs['hands'].items()}
            emit('hands_updated', {
                'room_id': room_id, 'hands_count': hands_count
            }, room=room_id)
            return

    # 手牌交换
    if effects and effects[0] == 'hand_swap' and len(effects) > 1:
        target = int(effects[1])
        emit('hands_swapped', {
            'room_id': room_id, 'seat1': seat, 'seat2': target,
            'hands': {str(seat): gs['hands'][seat][:], str(target): gs['hands'][target][:]}
        }, room=room_id)

    # 手牌传递
    if 'hands_pass' in effects:
        active = [s for s in _active_seats(room) if s != seat]
        involved = [seat]
        cur = seat
        for _ in range(len(active)):
            nxt = _get_next_turn(cur, gs['direction'], room['players'])
            if nxt == seat or nxt in involved:
                break
            involved.append(nxt)
            cur = nxt
        emit('hands_passed', {
            'room_id': room_id, 'from_seat': seat,
            'hands': {str(s): gs['hands'][s][:] for s in involved}
        }, room=room_id)


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
                emit('new_message', _system_msg(room, f"{current_user.username} 创建了房间"), room=room_id)
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
            seat = _player_seat(room, current_user.id)
            if seat is not None and room['players'][seat]:
                room['players'][seat]['is_online'] = True
            emit('room_joined', {'room_id': room_id, 'seat': seat, 'room': _room_summary(room)})
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
                emit('new_message', _system_msg(room, f"{current_user.username} 加入了房间"), room=room_id)
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
            seat = _player_seat(room, current_user.id)
            if seat is None:
                leave_room(room_id)
                return
            leave_room(room_id)
            is_creator = (room['creator_id'] == current_user.id)
            if is_creator:
                if room['status'] == 'playing':
                    gs = room['game_state']
                    active = _active_seats(room)
                    for s in [s for s in active if s != seat]:
                        if s not in gs['rankings']:
                            gs['rankings'].append(s)
                    end_game(room, 'creator_left')
                room['status'] = 'ended'
                emit('room_disbanded', {'room_id': room_id, 'reason': 'creator_left'}, room=room_id)
                if room_id in rooms:
                    del rooms[room_id]
                return
            if room['status'] == 'playing':
                p = room['players'][seat]
                if not p.get('eliminated', False):
                    from .game import _eliminate_player as eliminate_p
                    eliminate_p(room, seat, 'player_left')
                    if check_game_over(room):
                        end_game(room, 'player_left')
                        room['status'] = 'ended'
                        emit('room_disbanded', {'room_id': room_id, 'reason': 'player_left'}, room=room_id)
                        if room_id in rooms:
                            del rooms[room_id]
                        return
                else:
                    room['players'][seat] = None
                gs = room['game_state']
                if gs.get('current_turn') == seat:
                    nxt = _get_next_turn(seat, gs.get('direction', 1), room['players'])
                    gs['current_turn'] = nxt
                    _broadcast_turn_change(room, nxt)
            else:
                room['players'][seat] = None
            emit('player_left', {'room_id': room_id, 'seat': seat, 'username': current_user.username}, room=room_id)
            emit('new_message', _system_msg(room, f"{current_user.username} 离开了房间"), room=room_id)
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
            seat = _player_seat(room, current_user.id)
            if seat is None:
                emit('error', {'message': '您不在该房间中'})
                return
            if room['status'] != 'waiting':
                emit('error', {'message': '游戏不在等待状态'})
                return
            room['players'][seat]['ready'] = bool(ready)
            emit('player_ready', {
                'room_id': room_id, 'seat': seat,
                'ready': bool(ready), 'username': current_user.username
            }, room=room_id)
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
            gs = init_game_state(room)
            emit('game_started', {
                'room_id': room_id,
                'hands': {str(k): v for k, v in gs['hands'].items()},
                'hand_counts': {str(k): len(v) for k, v in gs['hands'].items()},
                'top_card': gs['top_card'],
                'top_color': gs['top_color'],
                'current_turn': gs['current_turn'],
                'direction': gs['direction'],
                'phase': gs['phase'],
                'draw_stack': 0
            }, room=room_id)
            _broadcast_turn_change(room, gs['current_turn'])
            emit('new_message', _system_msg(room, "UNO No Mercy 开始！准备好迎接残酷惩罚！"), room=room_id)
        except Exception as e:
            emit('error', {'message': f'开始游戏失败: {str(e)}'})

    @socketio.on('play_card', namespace='/game-uno-nomer')
    def on_play_card(data):
        try:
            room_id = data.get('room_id')
            card = data.get('card')
            chosen_color = data.get('chosen_color')
            target_seat = data.get('target_seat')
            room = rooms.get(room_id)
            if not room:
                emit('error', {'message': '房间不存在'})
                return
            gs = room['game_state']
            if gs['phase'] != 'playing':
                emit('error', {'message': '不在出牌阶段'})
                return
            seat = _player_seat(room, current_user.id)
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
            if not is_playable(gs['top_card'], gs['top_color'], card, draw_stack):
                emit('error', {'message': '这张牌无法打出'})
                return

            # 重置 UNO，打出牌
            gs['uno_called'].pop(str(seat), None)
            hand.remove(card)
            gs['discard_pile'].append(card)
            gs['top_card'] = card

            # 处理颜色
            if _card_color(card) == 'wild':
                if not chosen_color or chosen_color not in ('R', 'Y', 'G', 'B'):
                    emit('error', {'message': '请选择颜色'})
                    return
                gs['top_color'] = chosen_color
            else:
                gs['top_color'] = _card_color(card)

            # ---- 核心：应用卡牌效果 ----
            gs['_skip_next'] = False
            gs['_repeat_turn'] = False
            gs['_needs_roulette'] = None
            effects = apply_card_effect(gs, card, seat, room, target_seat=target_seat)

            # CR 罚抽颜色交互
            roulette_seat = gs.pop('_needs_roulette', None)
            if roulette_seat is not None:
                next_seat = _get_next_turn(roulette_seat, gs['direction'], room['players'])
                emit('color_roulette', {
                    'room_id': room_id, 'seat': next_seat, 'from_seat': roulette_seat
                }, room=room_id)

            # 广播特殊效果
            _broadcast_effects(room, seat, effects)

            # 检查出完手牌
            hand_emptied = check_empty_hand(room, seat)
            if hand_emptied:
                if check_game_over(room):
                    end_game(room, 'cards_finished')
                    return

            # 推进回合
            next_turn = advance_turn_after_play(room, seat, effects)
            if next_turn is None:
                return

            _broadcast_card_played(room, seat, card, effects)
            _broadcast_turn_change(room, next_turn)

        except Exception as e:
            emit('error', {'message': f'出牌失败: {str(e)}'})

    @socketio.on('color_roulette_pick', namespace='/game-uno-nomer')
    def on_color_roulette_pick(data):
        try:
            room_id = data.get('room_id')
            color = data.get('color')
            room = rooms.get(room_id)
            if not room or color not in ('R', 'Y', 'G', 'B'):
                return
            gs = room['game_state']
            seat = _player_seat(room, current_user.id)
            if seat is None or seat not in gs['hands']:
                return
            hand = gs['hands'][seat]
            drawn = []
            while True:
                if not gs['deck']:
                    recycle_discard(gs)
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
            check_elimination(room, seat)
            if check_game_over(room):
                end_game(room, 'elimination')
                return
            next_turn = _get_next_turn(seat, gs['direction'], room['players'])
            gs['current_turn'] = next_turn
            _broadcast_turn_change(room, next_turn)
        except Exception as e:
            emit('error', {'message': f'罚抽颜色失败: {str(e)}'})

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
                return
            seat = _player_seat(room, current_user.id)
            if seat is None or gs['current_turn'] != seat:
                emit('error', {'message': '不是您的回合'})
                return
            p = room['players'][seat]
            if p.get('eliminated', False):
                return
            hand = gs['hands'].get(seat, [])
            draw_stack = gs.get('draw_stack', 0)
            drawn = []

            # 栈惩罚模式
            if draw_stack > 0:
                gs['draw_stack'] = 0
                drawn = draw_from_deck(gs, draw_stack)
                hand.extend(drawn)
                gs['hands'][seat] = hand
                emit('player_drew', {
                    'room_id': room_id, 'seat': seat,
                    'cards': drawn, 'count': len(drawn),
                    'reason': 'stack_penalty'
                }, room=room_id)
                check_elimination(room, seat)
                if check_game_over(room):
                    end_game(room, 'elimination')
                    return
                next_turn = _get_next_turn(seat, gs['direction'], room['players'])
                gs['current_turn'] = next_turn
                _broadcast_turn_change(room, next_turn)
                return

            # 抽到能出为止
            while True:
                if not gs['deck']:
                    recycle_discard(gs)
                if not gs['deck']:
                    break
                c = gs['deck'].pop()
                drawn.append(c)
                hand.append(c)
                if is_playable(gs['top_card'], gs['top_color'], c):
                    # 自动打出
                    hand.remove(c)
                    gs['discard_pile'].append(c)
                    gs['top_card'] = c
                    if _card_color(c) != 'wild':
                        gs['top_color'] = _card_color(c)
                    card_draw = _get_draw_value(c)
                    if card_draw > 0:
                        gs['draw_stack'] = card_draw

                    is_skip_play = _card_value(c) == 'skip' or (_card_value(c) == 'rev' and len(_active_seats(room)) == 2)

                    if not hand:
                        if seat not in gs['rankings']:
                            gs['rankings'].append(seat)
                        emit('player_eliminated', {
                            'room_id': room_id, 'seat': seat,
                            'rank': len(gs['rankings']), 'reason': 'empty_hand'
                        }, room=room_id)
                        if check_game_over(room):
                            end_game(room, 'cards_finished')
                            return

                    emit('card_played', {
                        'room_id': room_id, 'seat': seat, 'card': c,
                        'top_color': gs['top_color'], 'top_card': gs['top_card'],
                        'remaining': len(hand), 'draw_stack': gs.get('draw_stack', 0),
                        'auto_play': True,
                        'hand_counts': {str(s): len(h) for s, h in gs['hands'].items()}
                    }, room=room_id)
                    emit('player_drew', {
                        'room_id': room_id, 'seat': seat,
                        'cards': drawn, 'count': len(drawn),
                        'reason': 'draw_to_play', 'auto_played': c
                    }, room=room_id)
                    check_elimination(room, seat)
                    if check_game_over(room):
                        end_game(room, 'elimination')
                        return
                    if is_skip_play:
                        next_turn = _get_next_turn(
                            _get_next_turn(seat, gs['direction'], room['players']),
                            gs['direction'], room['players'])
                    else:
                        next_turn = _get_next_turn(seat, gs['direction'], room['players'])
                    gs['current_turn'] = next_turn
                    _broadcast_turn_change(room, next_turn)
                    return

                # 中途检查 25 张淘汰
                gs['hands'][seat] = hand
                if check_elimination(room, seat):
                    emit('player_drew', {
                        'room_id': room_id, 'seat': seat,
                        'cards': drawn, 'count': len(drawn),
                        'reason': 'draw_to_play'
                    }, room=room_id)
                    if check_game_over(room):
                        end_game(room, 'elimination')
                        return
                    next_turn = _get_next_turn(seat, gs['direction'], room['players'])
                    gs['current_turn'] = next_turn
                    _broadcast_turn_change(room, next_turn)
                    return

            # 牌堆耗尽
            gs['hands'][seat] = hand
            emit('player_drew', {
                'room_id': room_id, 'seat': seat,
                'cards': drawn, 'count': len(drawn),
                'reason': 'draw_to_play'
            }, room=room_id)
            next_turn = _get_next_turn(seat, gs['direction'], room['players'])
            gs['current_turn'] = next_turn
            _broadcast_turn_change(room, next_turn)

        except Exception as e:
            emit('error', {'message': f'抽牌失败: {str(e)}'})

    @socketio.on('call_uno', namespace='/game-uno-nomer')
    def on_call_uno(data):
        try:
            room_id = data.get('room_id')
            room = rooms.get(room_id)
            if not room:
                return
            seat = _player_seat(room, current_user.id)
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
                drawn = draw_from_deck(gs, 2)
                target_hand.extend(drawn)
                gs['hands'][target_seat] = target_hand
                gs['uno_called'][str(target_seat)] = False
                emit('uno_penalty', {
                    'room_id': room_id, 'seat': target_seat, 'count': 2
                }, room=room_id)
                emit('new_message', _system_msg(room, f"{room['players'][target_seat]['username']} 忘记喊UNO，被罚抽2张牌！"), room=room_id)
                check_elimination(room, target_seat)
                if check_game_over(room):
                    end_game(room, 'elimination')
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
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'type': 'chat'
            }
            room['messages'].append(msg)
            if len(room['messages']) > 200:
                room['messages'] = room['messages'][-200:]
            emit('new_message', msg, room=room_id)
        except Exception as e:
            emit('error', {'message': f'发送消息失败: {str(e)}'})
