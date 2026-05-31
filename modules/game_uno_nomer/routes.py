from flask import render_template
from flask_login import login_required
from . import game_uno_nomer_bp

@game_uno_nomer_bp.route('/')
@login_required
def index():
    return render_template('uno_nomer.html',
                           current_user=__import__('flask_login', fromlist=['current_user']).current_user)
