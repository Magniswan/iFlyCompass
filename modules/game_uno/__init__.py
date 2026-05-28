from flask import Blueprint

# 共享房间状态字典，供 api.py 和 websocket.py 共用
rooms = {}

game_uno_bp = Blueprint('game_uno', __name__, url_prefix='/games/uno')

from . import routes
