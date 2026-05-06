from flask import render_template
from flask_login import login_required, current_user
from . import novel_bp

@novel_bp.route('/tools/novelreader')
@login_required
def novel_reader():
    return render_template('novel_reader.html', 
                         username=current_user.username)

@novel_bp.route('/tools/immersive-reader')
@login_required
def immersive_reader():
    return render_template('immersive_reader.html',
                         username=current_user.username)
