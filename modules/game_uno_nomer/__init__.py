from flask import Blueprint

# 共享房间状态字典，供 api.py 和 websocket.py 共用
rooms = {}

game_uno_nomer_bp = Blueprint('game_uno_nomer', __name__, url_prefix='/games/uno-nomer')

from . import routes
from .effects import CARD_EFFECTS, apply_card_effect, is_playable
from .game import init_game_state, check_elimination, check_game_over, end_game
