from flask import Blueprint

md_bp = Blueprint('md', __name__)

from . import routes, api
