from flask import Blueprint

video_bp = Blueprint('video', __name__)

from . import routes, api
