from flask import render_template, redirect, url_for, request, flash, session
from flask_login import login_user, current_user, logout_user, login_required
from extensions import db
from models.user import User, Passkey
from utils import get_settings, validate_username, validate_password_strength, is_weak_password
from . import auth_bp

user_sessions = {}

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.board'))

    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            login_user(user, remember=True)
            session.permanent = True
            session['_session_version'] = user.session_version or 0
            user_sessions[username] = request.cookies.get('session')

            if not user.is_active:
                return redirect(url_for('auth.maintenance'))

            next_page = request.form.get('next', '')
            if next_page and next_page.startswith('/') and not next_page.startswith('//'):
                return redirect(next_page)
            return redirect(url_for('main.board'))
        else:
            flash('用户名或密码错误')

    next_page = request.args.get('next', '')
    return render_template('login.html', next=next_page)

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('main.board'))
    
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        confirm_password = request.form['confirm_password']
        passkey = request.form.get('passkey', '')
        
        is_first_user = User.query.count() == 0
        
        if not is_first_user:
            passkey_obj = Passkey.query.filter_by(key=passkey).first()
            if not passkey_obj or not passkey_obj.is_valid():
                flash('无效的Passkey')
                return redirect(url_for('auth.register'))
            
            passkey_obj.current_uses += 1
            if passkey_obj.max_uses and passkey_obj.current_uses >= passkey_obj.max_uses:
                passkey_obj.is_active = False
            db.session.commit()
        
        settings = get_settings()
        username_min = settings.get('username_register_min', 3)
        username_max = settings.get('username_register_max', 50)
        
        is_valid_username, username_error = validate_username(username, username_min, username_max)
        if not is_valid_username:
            flash(username_error)
            return redirect(url_for('auth.register'))
        
        if password != confirm_password:
            flash('两次输入的密码不一致')
            return redirect(url_for('auth.register'))
        
        if User.query.filter_by(username=username).first():
            flash('用户名已存在')
            return redirect(url_for('auth.register'))
        
        password_strength = settings.get('password_strength', 1)
        allow_weak_password = settings.get('allow_weak_password', False)
        
        is_valid_password, password_error = validate_password_strength(password, password_strength)
        if not is_valid_password:
            flash(password_error)
            return redirect(url_for('auth.register'))
        
        if not allow_weak_password and is_weak_password(password):
            flash('密码过于简单，请使用更强的密码')
            return redirect(url_for('auth.register'))
        
        user = User(
            username=username,
            is_super_admin=is_first_user,
            is_admin=is_first_user,
            passkey_used=passkey if not is_first_user else None
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        
        flash('注册成功，请登录')
        return redirect(url_for('auth.login'))
    
    return render_template('register.html')

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('main.index'))

@auth_bp.route('/board/users')
@login_required
def user_management():
    if not (current_user.is_admin or current_user.is_super_admin):
        flash('权限不足')
        return redirect(url_for('main.board'))
    
    settings = get_settings()
    users = User.query.all()
    return render_template('user_management.html', 
                         users=users,
                         current_user=current_user,
                         sidebar_expanded=settings.get('sidebar_default_expanded', False))

@auth_bp.route('/board/passkeys')
@login_required
def passkey_management():
    if not current_user.is_super_admin:
        flash('权限不足')
        return redirect(url_for('main.board'))
    
    settings = get_settings()
    passkeys = Passkey.query.all()
    return render_template('passkey_management.html', 
                         passkeys=passkeys,
                         current_user=current_user,
                         sidebar_expanded=settings.get('sidebar_default_expanded', False))

@auth_bp.route('/forgot-password', methods=['GET'])
def forgot_password():
    settings = get_settings()
    if not settings.get('allow_self_password_reset', False):
        flash('自助找回密码功能未启用')
        return redirect(url_for('auth.login'))
    
    return render_template('forgot_password.html')

@auth_bp.route('/maintenance')
def maintenance():
    if current_user.is_authenticated and current_user.is_active:
        return redirect(url_for('main.board'))
    return render_template('maintenance.html')
