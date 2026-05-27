import random
from datetime import datetime
from collections import Counter
from flask_socketio import join_room, leave_room, emit
from flask import current_app
from flask_login import current_user
from . import rooms
from models import GameRecord, UserGameStats
from extensions import db

def get_card_rank(card):
    """从牌面字符串解析rank值"""
    if card.startswith('joker'):
        return int(card[5:])
    return int(card[1:])

def _get_card_type(cards):
    """识别牌型，返回可用于比较的字典"""
    if not cards or not isinstance(cards, list):
        return {'type': 'invalid', 'valid': False}
    
    ranks = sorted([get_card_rank(c) for c in cards])
    n = len(ranks)
    
    # 火箭（大小王）
    if n == 2 and ranks == [16, 17]:
        return {'type': 'rocket', 'main_rank': 17, 'length': 2, 'valid': True}
    
    # 炸弹（4张相同rank）
    if n == 4 and len(set(ranks)) == 1:
        return {'type': 'bomb', 'main_rank': ranks[0], 'length': 4, 'valid': True}
    
    # 单张
    if n == 1:
        return {'type': 'single', 'main_rank': ranks[0], 'length': 1, 'valid': True}
    
    # 对子
    if n == 2 and len(set(ranks)) == 1:
        return {'type': 'pair', 'main_rank': ranks[0], 'length': 2, 'valid': True}
    
    # 三张
    if n == 3 and len(set(ranks)) == 1:
        return {'type': 'triple', 'main_rank': ranks[0], 'length': 3, 'valid': True}
    
    # 三带一
    if n == 4:
        cnt = Counter(ranks)
        if sorted(cnt.values()) == [1, 3]:
            main_rank = [r for r, c in cnt.items() if c == 3][0]
            return {'type': 'triple_with_single', 'main_rank': main_rank, 'length': 4, 'valid': True}
    
    # 三带二
    if n == 5:
        cnt = Counter(ranks)
        if sorted(cnt.values()) == [2, 3]:
            main_rank = [r for r, c in cnt.items() if c == 3][0]
            return {'type': 'triple_with_pair', 'main_rank': main_rank, 'length': 5, 'valid': True}
    
    # 顺子（至少5张连续单牌，不含2、大小王）
    if n >= 5:
        unique_ranks = sorted(set(ranks))
        if len(unique_ranks) == n and unique_ranks[-1] <= 14 and unique_ranks[0] >= 3:
            is_sequence = True
            for i in range(len(unique_ranks) - 1):
                if unique_ranks[i+1] - unique_ranks[i] != 1:
                    is_sequence = False
                    break
            if is_sequence:
                return {'type': 'sequence', 'main_rank': unique_ranks[-1], 'length': n, 'valid': True}
    
    # 连对（至少3对连续对子，不含2、大小王）
    if n >= 6 and n % 2 == 0:
        cnt = Counter(ranks)
        pair_ranks = sorted([r for r, c in cnt.items() if c == 2])
        if len(pair_ranks) * 2 == n and pair_ranks[-1] <= 14 and pair_ranks[0] >= 3:
            is_pair_seq = True
            for i in range(len(pair_ranks) - 1):
                if pair_ranks[i+1] - pair_ranks[i] != 1:
                    is_pair_seq = False
                    break
            if is_pair_seq:
                return {'type': 'pair_sequence', 'main_rank': pair_ranks[-1], 'length': n, 'valid': True}
    
    return {'type': 'invalid', 'valid': False}

def _compare_cards(last_cards, new_cards):
    """比较新出牌是否能压过上家出牌"""
    new_type = _get_card_type(new_cards)
    if not new_type['valid']:
        return False
    
    # 无上家出牌时，任何有效牌型均可出
    if not last_cards:
        return True
    
    last_type = _get_card_type(last_cards)
    
    # 火箭最大
    if new_type['type'] == 'rocket':
        return True
    
    # 炸弹可以压普通牌型和其他炸弹（除了火箭）
    if new_type['type'] == 'bomb':
        if last_type['type'] == 'rocket':
            return False
        if last_type['type'] == 'bomb':
            return new_type['main_rank'] > last_type['main_rank']
        return True
    
    # 相同牌型且长度相同，比较主rank
    if new_type['type'] == last_type['type'] and new_type['length'] == last_type['length']:
        return new_type['main_rank'] > last_type['main_rank']
    
    return False

def _init_game_state(room):
    """初始化游戏状态：洗牌、发牌、设置初始状态"""
    suits = ['s', 'h', 'd', 'c']
    ranks = list(range(3, 16))  # 3-15 (3~10, J=11, Q=12, K=13, A=14, 2=15)
    deck = [f"{s}{r}" for s in suits for r in ranks]
    deck.extend(['joker16', 'joker17'])  # 小王、大王
    
    random.shuffle(deck)
    
    hands = {
        0: sorted(deck[0:17], key=get_card_rank),
        1: sorted(deck[17:34], key=get_card_rank),
        2: sorted(deck[34:51], key=get_card_rank)
    }
    bottom_cards = deck[51:54]
    
    game_state = {
        'hands': hands,
        'bottom_cards': bottom_cards,
        'landlord': None,
        'current_turn': 0,
        'phase': 'bidding',  # bidding, playing, ended
        'bids': {},
        'current_bid': 0,
        'bidder': None,
        'bid_count': 0,
        'last_play': None,  # {'seat': int, 'cards': [], 'card_type': dict}
        'consecutive_passes': 0,
        'winner': None,
        'played_cards': {0: [], 1: [], 2: []}
    }
    
    room['game_state'] = game_state
    room['status'] = 'playing'
    room['game_start_time'] = datetime.utcnow()
    
    # 重置玩家准备状态和角色
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
                game_type='doudizhu',
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
            
            # 更新用户统计
            for p in room['players']:
                if not p:
                    continue
                user_id = p['user_id']
                stats = UserGameStats.query.filter_by(user_id=user_id, game_type='doudizhu').first()
                if not stats:
                    stats = UserGameStats(user_id=user_id, game_type='doudizhu')
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

def _get_next_turn(seat):
    """获取下一个轮到的座位"""
    return (seat + 1) % 3

def _find_player_by_sid(room, sid):
    """通过Socket.IO sid查找玩家（由于无法直接映射，此函数为占位，实际使用user_id查找）"""
    # Socket.IO事件处理中current_user通常可用
    return None

def _get_player_seat(room, user_id):
    """获取玩家在房间中的座位号"""
    for i, p in enumerate(room['players']):
        if p and p['user_id'] == user_id:
            return i
    return None

def _can_start_bidding(room):
    """检查叫分是否完成，决定地主"""
    gs = room['game_state']
    bids = gs['bids']
    
    # 如果所有人都pass了（都叫了0分）
    if gs['bid_count'] >= 3:
        if gs['current_bid'] == 0:
            # 所有人都pass，seat 0 当地主，1分
            gs['landlord'] = 0
            gs['current_bid'] = 1
        else:
            # 有最高叫分者
            gs['landlord'] = gs['bidder']
        
        # 给地主发底牌
        landlord = gs['landlord']
        gs['hands'][landlord].extend(gs['bottom_cards'])
        gs['hands'][landlord] = sorted(gs['hands'][landlord], key=get_card_rank)
        
        # 设置角色
        for i, p in enumerate(room['players']):
            if p:
                p['role'] = 'landlord' if i == landlord else 'peasant'
        
        gs['phase'] = 'playing'
        gs['current_turn'] = landlord
        gs['last_play'] = None
        gs['consecutive_passes'] = 0
        return True
    
    # 如果有人直接叫了3分，立即结束叫分
    if gs['current_bid'] == 3 and gs['bidder'] is not None:
        gs['landlord'] = gs['bidder']
        landlord = gs['landlord']
        gs['hands'][landlord].extend(gs['bottom_cards'])
        gs['hands'][landlord] = sorted(gs['hands'][landlord], key=get_card_rank)
        
        for i, p in enumerate(room['players']):
            if p:
                p['role'] = 'landlord' if i == landlord else 'peasant'
        
        gs['phase'] = 'playing'
        gs['current_turn'] = landlord
        gs['last_play'] = None
        gs['consecutive_passes'] = 0
        return True
    
    return False

def _check_win(room, seat):
    """检查指定玩家是否出完手牌，返回获胜方列表"""
    gs = room['game_state']
    if not gs['hands'][seat]:
        # 该玩家出完了
        landlord = gs['landlord']
        if seat == landlord:
            # 地主获胜，只有地主赢
            return [landlord]
        else:
            # 农民获胜，两个农民赢
            winners = []
            for i in range(3):
                if i != landlord:
                    winners.append(i)
            return winners
    return None

def _end_game(room, winner_seats, reason=''):
    """结束游戏并保存记录"""
    gs = room['game_state']
    gs['phase'] = 'ended'
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
            'landlord': gs['landlord'],
            'hands': {str(k): v for k, v in gs['hands'].items()}
        }
    }, room=room['room_id'])

def register_socketio_events(socketio):
    
    @socketio.on('create_room', namespace='/game-doudizhu')
    def on_create_room(data):
        """创建Socket.IO房间（在REST API创建后调用）"""
        try:
            room_id = data.get('room_id')
            if not room_id:
                emit('error', {'message': '缺少房间ID'})
                return
            
            join_room(room_id)
            room = rooms.get(room_id)
            if room:
                # 更新创建者在线状态
                if room['players'][0]:
                    room['players'][0]['is_online'] = True
                
                emit('room_created', {'room_id': room_id, 'seat': 0})
                emit('new_message', _add_system_message(room, f"{current_user.username} 创建了房间"), room=room_id)
        except Exception as e:
            emit('error', {'message': f'创建房间事件失败: {str(e)}'})
    
    @socketio.on('join_room', namespace='/game-doudizhu')
    def on_join_room(data):
        """加入Socket.IO房间"""
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
            
            # 广播玩家加入
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
    
    @socketio.on('leave_room', namespace='/game-doudizhu')
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
            
            # 如果是创建者，解散房间
            if is_creator:
                if room['status'] == 'playing':
                    # 游戏进行中，保存记录（无胜负）
                    _end_game(room, [], 'creator_left')
                
                room['status'] = 'ended'
                emit('room_disbanded', {
                    'room_id': room_id,
                    'reason': 'creator_left'
                }, room=room_id)
                
                # 清理房间
                if room_id in rooms:
                    del rooms[room_id]
                return
            
            # 普通玩家离开
            room['players'][seat] = None
            
            if room['status'] == 'playing':
                # 游戏进行中有人离开，结束游戏
                # 剩下的玩家获胜
                remaining = [i for i, p in enumerate(room['players']) if p is not None]
                if remaining:
                    _end_game(room, remaining, 'player_left')
                room['status'] = 'ended'
                emit('room_disbanded', {
                    'room_id': room_id,
                    'reason': 'player_left'
                }, room=room_id)
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
    
    @socketio.on('ready', namespace='/game-doudizhu')
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
    
    @socketio.on('start_game', namespace='/game-doudizhu')
    def on_start_game(data):
        """开始游戏"""
        try:
            room_id = data.get('room_id')
            room = rooms.get(room_id)
            if not room:
                emit('error', {'message': '房间不存在'})
                return
            
            # 只有创建者可以开始游戏
            if room['creator_id'] != current_user.id:
                emit('error', {'message': '只有房主可以开始游戏'})
                return
            
            if room['status'] != 'waiting':
                emit('error', {'message': '游戏不在等待状态'})
                return
            
            # 检查是否3个玩家都在
            active_players = [p for p in room['players'] if p is not None]
            if len(active_players) < 3:
                emit('error', {'message': '需要3名玩家才能开始游戏'})
                return
            
            # 检查是否所有玩家都准备好了
            if not all(p['ready'] for p in active_players):
                emit('error', {'message': '有玩家尚未准备'})
                return
            
            # 初始化游戏状态
            gs = _init_game_state(room)
            
            emit('game_started', {
                'room_id': room_id,
                'hands': {str(k): v for k, v in gs['hands'].items()},
                'bottom_cards': gs['bottom_cards'],
                'current_turn': gs['current_turn'],
                'phase': gs['phase']
            }, room=room_id)
            
            # 开始叫分阶段
            emit('bidding_turn', {
                'room_id': room_id,
                'seat': gs['current_turn'],
                'current_bid': gs['current_bid']
            }, room=room_id)
            
            emit('new_message', _add_system_message(room, "游戏开始！请叫分"), room=room_id)
        except Exception as e:
            emit('error', {'message': f'开始游戏事件失败: {str(e)}'})
    
    @socketio.on('bid', namespace='/game-doudizhu')
    def on_bid(data):
        """叫分"""
        try:
            room_id = data.get('room_id')
            seat = data.get('seat')
            score = data.get('score', 0)
            
            room = rooms.get(room_id)
            if not room:
                emit('error', {'message': '房间不存在'})
                return
            
            gs = room['game_state']
            if gs['phase'] != 'bidding':
                emit('error', {'message': '不在叫分阶段'})
                return
            
            # 验证是否是当前叫分者
            if gs['current_turn'] != seat:
                emit('error', {'message': '不是您的叫分回合'})
                return
            
            # 验证座位合法性
            player_seat = _get_player_seat(room, current_user.id)
            if player_seat != seat:
                emit('error', {'message': '座位号不匹配'})
                return
            
            # 验证分数
            if not isinstance(score, int) or score < 0 or score > 3:
                emit('error', {'message': '叫分必须是0-3的整数'})
                return
            
            # 如果叫分，必须比当前最高分高
            if score > 0 and score <= gs['current_bid']:
                emit('error', {'message': f'叫分必须高于当前最高分 {gs["current_bid"]}'})
                return
            
            # 记录叫分
            gs['bids'][seat] = score
            gs['bid_count'] += 1
            
            if score > gs['current_bid']:
                gs['current_bid'] = score
                gs['bidder'] = seat
            
            emit('bid_result', {
                'room_id': room_id,
                'seat': seat,
                'score': score,
                'current_bid': gs['current_bid']
            }, room=room_id)
            
            # 检查叫分是否结束
            if _can_start_bidding(room):
                # 叫分结束，公布地主
                landlord = gs['landlord']
                emit('landlord_decided', {
                    'room_id': room_id,
                    'landlord': landlord,
                    'bottom_cards': gs['bottom_cards'],
                    'hands': {str(k): v for k, v in gs['hands'].items()},
                    'bid_score': gs['current_bid']
                }, room=room_id)
                
                emit('play_turn', {
                    'room_id': room_id,
                    'seat': gs['current_turn'],
                    'must_play': True
                }, room=room_id)
                
                emit('new_message', _add_system_message(room, f"地主是 {room['players'][landlord]['username']}，叫分 {gs['current_bid']} 分"), room=room_id)
            else:
                # 下一位叫分
                gs['current_turn'] = _get_next_turn(seat)
                emit('bidding_turn', {
                    'room_id': room_id,
                    'seat': gs['current_turn'],
                    'current_bid': gs['current_bid']
                }, room=room_id)
        except Exception as e:
            emit('error', {'message': f'叫分事件失败: {str(e)}'})
    
    @socketio.on('play_cards', namespace='/game-doudizhu')
    def on_play_cards(data):
        """出牌"""
        try:
            room_id = data.get('room_id')
            cards = data.get('cards', [])
            
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
            
            # 验证牌型
            card_type = _get_card_type(cards)
            if not card_type['valid']:
                emit('error', {'message': '无效的牌型'})
                return
            
            # 验证牌是否在手牌中
            hand = gs['hands'][seat]
            hand_ranks = Counter([get_card_rank(c) for c in hand])
            play_ranks = Counter([get_card_rank(c) for c in cards])
            
            for rank, count in play_ranks.items():
                if hand_ranks[rank] < count:
                    emit('error', {'message': '您没有这些牌'})
                    return
            
            # 验证是否能压过上家
            last_play = gs['last_play']
            if last_play and last_play['seat'] != seat:
                last_cards = last_play['cards']
                if not _compare_cards(last_cards, cards):
                    emit('error', {'message': '您的牌无法压过上家'})
                    return
            elif not last_play:
                # 新一轮开始，必须出牌（不能过）
                pass
            
            # 出牌成功，从手牌移除
            new_hand = hand[:]
            for card in cards:
                for i, h_card in enumerate(new_hand):
                    if h_card == card:
                        new_hand.pop(i)
                        break
            gs['hands'][seat] = sorted(new_hand, key=get_card_rank)
            gs['played_cards'][seat].extend(cards)
            
            gs['last_play'] = {
                'seat': seat,
                'cards': cards,
                'card_type': card_type
            }
            gs['consecutive_passes'] = 0
            
            emit('cards_played', {
                'room_id': room_id,
                'seat': seat,
                'cards': cards,
                'card_type': card_type,
                'remaining': len(gs['hands'][seat])
            }, room=room_id)
            
            # 检查是否获胜
            winners = _check_win(room, seat)
            if winners is not None:
                _end_game(room, winners, 'cards_finished')
                winner_names = [room['players'][w]['username'] for w in winners if room['players'][w]]
                emit('new_message', _add_system_message(room, f"游戏结束！获胜者: {', '.join(winner_names)}"), room=room_id)
                return
            
            # 下一位出牌
            gs['current_turn'] = _get_next_turn(seat)
            emit('play_turn', {
                'room_id': room_id,
                'seat': gs['current_turn'],
                'must_play': False  # 可以选择过
            }, room=room_id)
        except Exception as e:
            emit('error', {'message': f'出牌事件失败: {str(e)}'})
    
    @socketio.on('pass', namespace='/game-doudizhu')
    def on_pass(data):
        """过牌"""
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
            
            # 检查是否必须出牌（新一轮开始，无上家出牌 或 上家就是自己）
            last_play = gs['last_play']
            if not last_play or last_play['seat'] == seat:
                emit('error', {'message': '新一轮开始，您必须出牌'})
                return
            
            gs['consecutive_passes'] += 1
            
            emit('pass_turn', {
                'room_id': room_id,
                'seat': seat
            }, room=room_id)
            
            # 检查是否连续两个pass（加上上家的出牌，新一轮开始）
            if gs['consecutive_passes'] >= 2:
                # 新一轮，最后出牌的人继续出牌
                gs['last_play'] = None
                gs['consecutive_passes'] = 0
                # current_turn 已经是下一位，但需要回到最后出牌者
                # 实际上，last_play['seat'] 是最后出牌的人
                last_seat = last_play['seat']
                gs['current_turn'] = _get_next_turn(last_seat)  # 按顺序应该是下一位？不，应该是最后出牌者的下一家
                # 等等，如果 A 出牌，B pass，C pass，那么 A 继续出牌
                # 此时 current_turn 应该是 A 的下一家？不，应该是 A 继续？
                # 不，应该是 A 继续出牌（新一轮由 A 开始）
                gs['current_turn'] = last_seat
                emit('play_turn', {
                    'room_id': room_id,
                    'seat': gs['current_turn'],
                    'must_play': True
                }, room=room_id)
            else:
                # 下一位出牌
                gs['current_turn'] = _get_next_turn(seat)
                emit('play_turn', {
                    'room_id': room_id,
                    'seat': gs['current_turn'],
                    'must_play': False
                }, room=room_id)
        except Exception as e:
            emit('error', {'message': f'过牌事件失败: {str(e)}'})
    
    @socketio.on('send_message', namespace='/game-doudizhu')
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
    """生成房间摘要（用于websocket广播）"""
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
