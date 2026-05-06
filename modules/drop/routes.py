from flask import render_template, redirect, url_for
from flask_login import login_required, current_user
from . import drop_bp

@drop_bp.route('/drop/settings')
@login_required
def drop_settings():
    return render_template('drop_settings.html')
