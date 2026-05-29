from extensions import db
from datetime import datetime, timezone

class GameRecord(db.Model):
    __tablename__ = 'game_record'
    id = db.Column(db.Integer, primary_key=True)
    game_type = db.Column(db.String(20), nullable=False)
    room_id = db.Column(db.String(36), nullable=False)
    started_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    ended_at = db.Column(db.DateTime)
    winner_ids = db.Column(db.JSON, default=list)
    winner_names = db.Column(db.JSON, default=list)
    loser_ids = db.Column(db.JSON, default=list)
    loser_names = db.Column(db.JSON, default=list)
    player_ids = db.Column(db.JSON, default=list)
    game_data = db.Column(db.JSON, default=dict)

class UserGameStats(db.Model):
    __tablename__ = 'user_game_stats'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    game_type = db.Column(db.String(20), nullable=False)
    total_games = db.Column(db.Integer, default=0)
    wins = db.Column(db.Integer, default=0)
    losses = db.Column(db.Integer, default=0)
    draws = db.Column(db.Integer, default=0)
    win_rate = db.Column(db.Float, default=0.0)
    last_played = db.Column(db.DateTime)
    __table_args__ = (db.UniqueConstraint('user_id', 'game_type', name='uq_user_game'),)
