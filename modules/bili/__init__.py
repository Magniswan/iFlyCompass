from flask import Blueprint

bili_bp = Blueprint('bili', __name__)

from . import routes, api, download_service
