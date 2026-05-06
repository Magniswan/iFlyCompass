from flask import render_template
from flask_login import login_required
from utils import get_settings
from . import bili_bp

@bili_bp.route('/tools/biliplayer')
@login_required
def bili_player():
    settings = get_settings()
    return render_template('bili_player.html',
                         sidebar_expanded=settings.get('sidebar_default_expanded', False))
