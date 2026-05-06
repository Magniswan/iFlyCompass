from flask import render_template
from utils import get_settings
from . import ncm_bp

@ncm_bp.route('/ncmplayer')
def ncm_player():
    settings = get_settings()
    return render_template('ncm_player.html',
                         sidebar_expanded=settings.get('sidebar_default_expanded', False))
