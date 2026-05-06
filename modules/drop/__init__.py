from flask import Blueprint

drop_bp = Blueprint('drop', __name__, url_prefix='')

from . import routes, api
