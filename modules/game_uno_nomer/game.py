"""
UNO No Mercy 游戏通用操作

抽取 websocket.py 中重复的淘汰检查、回合推进、游戏结束逻辑。
"""
import random
from datetime import datetime, timezone
from flask import current_app
from flask_socketio import emit
from extensions import db
from models import GameRecord, UserGameStats
from .effects import _get_next_turn, _active_seats, _card_color, _card_value, draw_from_deck


def check_elimination(room, seat):
    """检查手牌 >= 25 淘汰，返回 True 表示被淘汰"""
    gs = room['game_state']
    if seat in gs['hands'] and len(gs['hands'][seat]) >= 25:
        _eliminate_player(room, seat, 'hand_limit')
        return True
    return False


def check_empty_hand(room, seat):
    """检查手牌为空，排名并广播，返回 True 表示出完"""
    gs = room['game_state']
    if seat in gs['hands'] and not gs['hands'][seat]:
        if seat not in gs['rankings']:
            gs['rankings'].append(seat)
        emit('player_eliminated', {
            'room_id': room['room_id'], 'seat': seat,
            'rank': len(gs['rankings']), 'reason': 'empty_hand'
        }, room=room['room_id'])
        player_name = room['players'][seat]['username'] if room['players'][seat] else '玩家'
        _system_msg(room, f"{player_name} 出完了手牌，获得第{len(gs['rankings'])}名！")
        return True
    return False


def check_game_over(room):
    """检查游戏是否结束，返回 True 表示结束"""
    gs = room['game_state']
    active = _active_seats(room)
    if len(active) <= 1:
        if active and active[0] not in gs['rankings']:
            gs['rankings'].append(active[0])
        return True
    return False


def end_game(room, reason=''):
    """结束游戏"""
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


def advance_turn_after_play(room, seat, effects):
    """
    处理出牌后的回合推进。
    返回：下一个回合的座位号，None 表示游戏已结束。
    """
    gs = room['game_state']
    direction = gs['direction']

    if seat in gs['hands'] and not gs['hands'][seat]:
        return _get_next_turn(seat, direction, room['players'])

    if check_elimination(room, seat):
        if check_game_over(room):
            end_game(room, 'elimination')
            return None
        return _get_next_turn(seat, direction, room['players'])

    if gs.pop('_repeat_turn', False):
        return seat

    next_seat = _get_next_turn(seat, direction, room['players'])
    if gs.pop('_skip_next', False):
        next_seat = _get_next_turn(next_seat, direction, room['players'])

    return next_seat


# ---- 内部辅助 ----

def _eliminate_player(room, seat, reason='hand_limit'):
    gs = room['game_state']
    p = room['players'][seat]
    if p and not p.get('eliminated', False):
        p['eliminated'] = True
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


def _system_msg(room, message):
    msg = {'username': 'system', 'message': message, 'timestamp': datetime.now(timezone.utc).isoformat(), 'type': 'system'}
    room['messages'].append(msg)
    if len(room['messages']) > 200:
        room['messages'] = room['messages'][-200:]
    emit('new_message', msg, room=room['room_id'])


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
                started_at=room.get('game_start_time', datetime.now(timezone.utc)),
                ended_at=datetime.now(timezone.utc),
                winner_ids=winner_ids,
                winner_names=[room['players'][s]['username'] for s in winner_seats if room['players'][s]],
                loser_ids=loser_ids,
                loser_names=[
                    room['players'][s]['username'] for s, p in enumerate(room['players'])
                    if p and p['user_id'] in loser_ids
                ],
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
                stats.last_played = datetime.now(timezone.utc)
            db.session.commit()
    except Exception as e:
        print(f"保存游戏记录失败: {e}")


def init_game_state(room):
    """初始化游戏状态"""
    deck = _create_deck()
    active_seats = _active_seats(room)

    hands = {}
    for seat in active_seats:
        hands[seat] = [deck.pop() for _ in range(7)]

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
    room['game_start_time'] = datetime.now(timezone.utc)

    for p in room['players']:
        if p:
            p['ready'] = False
            p['eliminated'] = False

    return game_state


def _create_deck():
    """创建UNO No Mercy牌组（160张）"""
    colors = ['R', 'Y', 'G', 'B']
    deck = []

    for color in colors:
        deck.append(f"{color}0")
        for num in range(1, 10):
            deck.extend([f"{color}{num}", f"{color}{num}"])

    for color in colors:
        deck.append(f"{color}+2")
        deck.append(f"{color}rev")
        deck.append(f"{color}skip")

    for _ in range(4):
        deck.append("W")
        deck.append("W+4")

    for color in colors:
        for _ in range(3):
            deck.append(f"{color}ac")

    for _ in range(8):
        deck.append("SE")
    for _ in range(8):
        deck.append("N+4")
    for _ in range(8):
        deck.append("NR+4")
    for _ in range(8):
        deck.append("CR")
    for _ in range(4):
        deck.append("N+6")
    for _ in range(4):
        deck.append("N+10")

    random.shuffle(deck)
    return deck
