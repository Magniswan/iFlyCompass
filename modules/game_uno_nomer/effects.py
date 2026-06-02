"""
UNO No Mercy 卡牌效果处理注册表

每种卡牌的效果注册为独立 handler，接受 (gs, seat, room, **kwargs) 并返回效果名称列表。
"""
import random


def skip_handler(gs, seat, room, **kw):
    """跳过下家"""
    gs['_skip_next'] = True
    return ['skip']


def reverse_handler(gs, seat, room, **kw):
    """反转方向；2人时=跳过"""
    gs['direction'] *= -1
    if len(_active_seats(room)) == 2:
        gs['_skip_next'] = True
    return ['reverse']


def draw_handler(count):
    def handler(gs, seat, room, **kw):
        gs['draw_stack'] = gs.get('draw_stack', 0) + count
        return ['draw', str(count)]
    return handler


def reverse_draw_handler(count):
    def handler(gs, seat, room, **kw):
        gs['direction'] *= -1
        gs['draw_stack'] = gs.get('draw_stack', 0) + count
        return ['reverse_draw', str(count)]
    return handler


def all_discard_handler(gs, seat, room, **kw):
    """同色全弃：所有玩家弃掉当前颜色牌"""
    color = gs['top_color']
    for s, hand in list(gs['hands'].items()):
        discarded = [c for c in hand if _card_color(c) == color]
        for c in discarded:
            hand.remove(c)
            gs['discard_pile'].append(c)
        gs['hands'][s] = hand
    return [f'all_discard_{color}']


def hand_swap_handler(gs, seat, room, **kw):
    """数字7：与目标交换手牌"""
    target = kw.get('target_seat')
    if target is not None and target != seat and target in gs['hands']:
        gs['hands'][seat], gs['hands'][target] = gs['hands'][target], gs['hands'][seat]
        return ['hand_swap', str(target)]
    return []


def hand_pass_handler(gs, seat, room, **kw):
    """数字0：全体传递手牌"""
    active = [s for s in _active_seats(room) if s != seat]
    if not active:
        return []
    direction = gs['direction']
    ordered = []
    cur = seat
    for _ in range(len(active) + 1):
        nxt = _get_next_turn(cur, direction, room['players'])
        if nxt == seat or nxt in ordered:
            break
        ordered.append(nxt)
        cur = nxt
    if not ordered:
        return []
    involved = [seat] + ordered
    hands_snapshot = {s: gs['hands'].get(s, [])[:] for s in involved}
    for i, s in enumerate(involved):
        prev_s = ordered[-1] if i == 0 else involved[i - 1]
        gs['hands'][s] = hands_snapshot[prev_s]
    return ['hands_pass']


def skip_all_handler(gs, seat, room, **kw):
    """SE 全场跳过：当前玩家再获得一个回合"""
    gs['_repeat_turn'] = True
    return ['skip_all']


def color_roulette_handler(gs, seat, room, **kw):
    """CR 罚抽颜色：标记需要交互"""
    gs['_needs_roulette'] = seat
    return ['color_roulette']


def wild_handler(gs, seat, room, **kw):
    """W 变色（无额外效果）"""
    return ['wild']


# ---- 注册表 ----

CARD_EFFECTS = {
    'skip':  skip_handler,
    'rev':   reverse_handler,
    '+2':    draw_handler(2),
    'ac':    all_discard_handler,
    '7':     hand_swap_handler,
    '0':     hand_pass_handler,
    'SE':    skip_all_handler,
    'NR+4':  reverse_draw_handler(4),
    'W+4':   draw_handler(4),
    'N+4':   draw_handler(4),
    'N+6':   draw_handler(6),
    'N+10':  draw_handler(10),
    'CR':    color_roulette_handler,
    'W':     wild_handler,
}


def apply_card_effect(gs, card, seat, room, **kwargs):
    """
    根据卡牌查找效果 handler 并执行。
    返回效果名称列表用于广播。
    """
    val = _card_value(card)

    if card in CARD_EFFECTS:
        handler = CARD_EFFECTS[card]
    elif val in CARD_EFFECTS:
        handler = CARD_EFFECTS[val]
    else:
        return []

    return handler(gs, seat, room, **kwargs)


# ---- 辅助函数 ----

def _active_seats(room):
    return [i for i, p in enumerate(room['players']) if p is not None and not p.get('eliminated', False)]


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


def _card_color(card):
    if card in ('W', 'W+4', 'SE', 'N+4', 'NR+4', 'CR', 'N+6', 'N+10'):
        return 'wild'
    return card[0]


def _card_value(card):
    if card in ('W', 'SE', 'CR'):
        return card
    if card == 'W+4':
        return '+4'
    if card.startswith('N+4'):
        return '+4'
    if card.startswith('N+6'):
        return '+6'
    if card.startswith('N+10'):
        return '+10'
    if card.startswith('NR'):
        return '+4'
    return card[1:] if len(card) > 1 else ''


def _get_draw_value(card):
    val = _card_value(card)
    if val == '+2':
        return 2
    if val == '+4':
        return 4
    if val == '+6':
        return 6
    if val == '+10':
        return 10
    if card == 'N+4':
        return 4
    if card == 'NR+4':
        return 4
    if card == 'N+6':
        return 6
    if card == 'N+10':
        return 10
    return 0


def is_playable(top_card, top_color, hand_card, draw_stack=0):
    card_val = _card_value(hand_card)
    top_val = _card_value(top_card)
    if draw_stack > 0:
        dv = _get_draw_value(hand_card)
        return dv >= draw_stack
    if _card_color(hand_card) == 'wild':
        return True
    if _card_color(hand_card) == top_color:
        return True
    if _card_color(top_card) != 'wild' and card_val == top_val:
        return True
    return False


def recycle_discard(gs):
    """弃牌堆回收到牌堆"""
    if len(gs['discard_pile']) > 1:
        top = gs['discard_pile'].pop()
        gs['deck'] = gs['discard_pile'][:]
        gs['discard_pile'] = [top]
        random.shuffle(gs['deck'])


def draw_from_deck(gs, count):
    """从牌堆抽 count 张牌"""
    cards = []
    for _ in range(count):
        if not gs['deck']:
            recycle_discard(gs)
        if gs['deck']:
            cards.append(gs['deck'].pop())
    return cards
