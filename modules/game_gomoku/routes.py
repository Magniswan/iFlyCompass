from flask import render_template
from flask_login import login_required, current_user
from . import game_gomoku_bp

@game_gomoku_bp.route('/')
@login_required
def index():
    return render_template('gomoku.html',
                         current_user=current_user,
                         display_name=current_user.display_name,
                         username=current_user.username)
