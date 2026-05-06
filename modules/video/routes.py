from flask import render_template
from flask_login import login_required
from utils import get_settings
from . import video_bp

@video_bp.route('/tools/videoplayer')
@login_required
def video_player():
    settings = get_settings()
    return render_template('video_player.html',
                         sidebar_expanded=settings.get('sidebar_default_expanded', False))
