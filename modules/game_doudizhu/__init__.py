from flask import Blueprint

# 共享房间状态字典，供 api.py 和 websocket.py 共用
rooms = {}

game_doudizhu_bp = Blueprint('game_doudizhu', __name__, url_prefix='/games/doudizhu')

from . import routes
