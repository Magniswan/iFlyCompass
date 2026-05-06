from flask import Blueprint

ncm_bp = Blueprint('ncm', __name__, url_prefix='')

from . import routes, api
