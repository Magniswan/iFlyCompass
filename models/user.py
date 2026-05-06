from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timezone
from extensions import db

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    nickname = db.Column(db.String(50), nullable=True)
    password_hash = db.Column(db.String(128), nullable=False)
    is_super_admin = db.Column(db.Boolean, default=False)
    is_admin = db.Column(db.Boolean, default=False)
    passkey_used = db.Column(db.String(6), nullable=True)
    security_question = db.Column(db.String(255), nullable=True)
    security_answer_hash = db.Column(db.String(128), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    def set_security_answer(self, answer):
        self.security_answer_hash = generate_password_hash(answer.lower().strip())
    
    def check_security_answer(self, answer):
        if not self.security_answer_hash:
            return False
        return check_password_hash(self.security_answer_hash, answer.lower().strip())
    
    @property
    def display_name(self):
        from utils.system_settings import get_settings
        settings = get_settings()
        if settings.get('allow_nickname', True) and self.nickname:
            return self.nickname
        return self.username

class Passkey(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(6), unique=True, nullable=False)
    duration_days = db.Column(db.Integer, nullable=True)
    max_uses = db.Column(db.Integer, nullable=True)
    current_uses = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)
    expires_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    
    def is_valid(self):
        if not self.is_active:
            return False
        
        if self.expires_at:
            if datetime.now(timezone.utc) > self.expires_at.astimezone(timezone.utc):
                return False
        
        if self.max_uses and self.current_uses >= self.max_uses:
            return False
        
        return True
