from flask import Blueprint

sticker_bp = Blueprint('sticker', __name__)

from . import routes, api
