from flask import render_template, send_from_directory, jsonify, request
from flask_login import login_required, current_user
from utils import get_bing_wallpaper, get_poetry, get_settings, get_nav_items
from config import Config
from . import main_bp
from models import GameRecord, UserGameStats

@main_bp.route('/')
def index():
    wallpaper_url = get_bing_wallpaper()
    poetry = get_poetry()
    return render_template('index.html', wallpaper_url=wallpaper_url, poetry=poetry)

@main_bp.route('/board')
@login_required
def board():
    settings = get_settings()
    return render_template('board.html', 
                         current_user=current_user,
                         home_display=settings.get('home_display', 'nickname'),
                         sidebar_expanded=settings.get('sidebar_default_expanded', False))

@main_bp.route('/board/tools')
@login_required
def tools():
    settings = get_settings()
    return render_template('tools.html',
                         current_user=current_user,
                         sidebar_expanded=settings.get('sidebar_default_expanded', False),
                         card_layout=settings.get('card_layout', '1x4'),
                         category='tools')

@main_bp.route('/board/games')
@login_required
def games():
    settings = get_settings()
    return render_template('games.html',
                         current_user=current_user,
                         sidebar_expanded=settings.get('sidebar_default_expanded', False))

@main_bp.route('/board/swipe-test')
@login_required
def swipe_test():
    if not (current_user.is_admin or current_user.is_super_admin):
        return render_template('error.html', 
                             error_title='权限不足',
                             error_message='您没有权限访问此页面',
                             current_user=current_user), 403
    settings = get_settings()
    return render_template('swipe_test.html', 
                         current_user=current_user,
                         sidebar_expanded=settings.get('sidebar_default_expanded', False))

@main_bp.route('/board/announcements')
@login_required
def announcement_manage():
    if not (current_user.is_admin or current_user.is_super_admin):
        return render_template('error.html', 
                             error_title='权限不足',
                             error_message='您没有权限访问此页面',
                             current_user=current_user), 403
    settings = get_settings()
    return render_template('announcement_manage.html', 
                         current_user=current_user,
                         sidebar_expanded=settings.get('sidebar_default_expanded', False))

@main_bp.route('/temp/<path:filename>')
def serve_temp(filename):
    return send_from_directory(Config.TEMP_DIR, filename)

@main_bp.route('/assets/<path:filename>')
def serve_assets(filename):
    return send_from_directory(Config.ASSETS_DIR, filename)

@main_bp.route('/api/nav/items')
@login_required
def get_nav_items_api():
    category = request.args.get('category', 'tools')
    items = get_nav_items()
    filtered_items = [item for item in items if item.get('category') == category]
    return jsonify(filtered_items)


@main_bp.route('/api/game/stats/<game_type>')
@login_required
def get_game_stats(game_type):
    """获取某游戏战绩"""
    user_id = request.args.get('user_id', current_user.id, type=int)
    stats = UserGameStats.query.filter_by(user_id=user_id, game_type=game_type).first()
    if not stats:
        return jsonify({
            'game_type': game_type,
            'total_games': 0,
            'wins': 0,
            'losses': 0,
            'draws': 0,
            'win_rate': 0.0
        })
    return jsonify({
        'game_type': stats.game_type,
        'total_games': stats.total_games,
        'wins': stats.wins,
        'losses': stats.losses,
        'draws': stats.draws,
        'win_rate': stats.win_rate
    })


@main_bp.route('/api/game/records')
@login_required
def get_game_records():
    """获取最近对局记录"""
    game_type = request.args.get('game_type')
    limit = request.args.get('limit', 20, type=int)
    q = GameRecord.query
    if game_type:
        q = q.filter_by(game_type=game_type)
    records = q.order_by(GameRecord.ended_at.desc()).limit(limit).all()
    return jsonify({'records': [{
        'id': r.id,
        'game_type': r.game_type,
        'winner_names': r.winner_names or [],
        'loser_names': r.loser_names or [],
        'ended_at': r.ended_at.isoformat() if r.ended_at else None,
        'game_data': r.game_data or {}
    } for r in records]})


@main_bp.route('/api/game/leaderboard/<game_type>')
@login_required
def get_leaderboard(game_type):
    """获取游戏排行榜"""
    stats = UserGameStats.query.filter_by(game_type=game_type).order_by(
        UserGameStats.win_rate.desc()
    ).limit(20).all()
    return jsonify({'leaderboard': [{
        'user_id': s.user_id,
        'total_games': s.total_games,
        'wins': s.wins,
        'win_rate': s.win_rate,
        'last_played': s.last_played.isoformat() if s.last_played else None
    } for s in stats]})
