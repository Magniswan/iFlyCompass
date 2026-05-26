from flask import render_template
from flask_login import login_required, current_user
from . import game_doudizhu_bp

@game_doudizhu_bp.route('/')
@login_required
def index():
    return render_template('doudizhu.html',
                         current_user=current_user,
                         display_name=current_user.display_name,
                         username=current_user.username)
