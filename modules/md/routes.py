from flask import render_template
from flask_login import login_required, current_user
from . import md_bp

@md_bp.route('/tools/md-editor')
@login_required
def md_editor():
    return render_template('md_editor.html', current_user=current_user)
