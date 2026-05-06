from flask import Blueprint

novel_bp = Blueprint('novel', __name__)

from . import routes, api
