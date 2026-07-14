from flask import Blueprint, render_template, request, redirect, url_for, flash, g, session, current_app
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from app import db, limiter
from app.models import User
from app.decorators import csrf_protect, login_required, admin_required
from app.schemas import UserSchema
from app.utils import log_audit, get_csrf_token
from marshmallow import ValidationError
import re

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')
schema = UserSchema()

USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,50}$")
PASSWORD_HASH_METHOD = "pbkdf2:sha256"

@auth_bp.before_request
def load_user():
    """Load user from session before each request."""
    g.current_user = None
    user_id = session.get('user_id')
    if user_id:
        user = User.query.filter_by(id=user_id, is_active=True).first()
        if user:
            g.current_user = {'id': user.id, 'username': user.username, 'role': user.role}
        else:
            session.clear()

@auth_bp.after_request
def apply_security_headers(response):
    """Apply security headers."""
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'same-origin'
    if g.get('current_user'):
        response.headers['Cache-Control'] = 'no-store'
    return response

@auth_bp.route('/setup', methods=['GET', 'POST'])
@limiter.limit("5 per hour")
def setup():
    """Setup initial admin account."""
    has_users = User.query.first() is not None
    if has_users:
        return redirect(url_for('auth.login'))
    
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        password_confirmation = request.form.get('password_confirmation', '')
        
        # Validation
        if not USERNAME_RE.fullmatch(username):
            flash("Username must be 3–50 characters and use alphanumeric characters, dot, dash, or underscore.", "danger")
            return redirect(url_for('auth.setup'))
        
        if len(password) < 12:
            flash("Admin password must be at least 12 characters.", "danger")
            return redirect(url_for('auth.setup'))
        
        if password != password_confirmation:
            flash("Password confirmation does not match.", "danger")
            return redirect(url_for('auth.setup'))
        
        try:
            new_admin = User(
                username=username,
                password_hash=generate_password_hash(password, method=PASSWORD_HASH_METHOD),
                role='admin',
                created_at=datetime.utcnow()
            )
            db.session.add(new_admin)
            db.session.commit()
            
            log_audit('administrator_account_created', details=f'username={username}')
            flash("Administrator account created. Please sign in.", "success")
            return redirect(url_for('auth.login'))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Setup failed: {str(e)}")
            flash("An error occurred during setup. Please try again.", "danger")
    
    return render_template('auth/setup.html')

@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("10 per minute")
@csrf_protect
def login():
    """User login."""
    has_users = User.query.first() is not None
    if not has_users:
        return redirect(url_for('auth.setup'))
    
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        
        user = User.query.filter_by(username=username).first()
        if user and user.is_active and check_password_hash(user.password_hash, password):
            user.last_login_at = datetime.utcnow()
            db.session.commit()
            
            session.clear()
            session['user_id'] = user.id
            session['username'] = user.username
            
            log_audit('user_login', details=f'role={user.role}')
            flash(f"Welcome back, {user.username}!", "success")
            return redirect(url_for('dashboard.index'))
        else:
            log_audit('failed_login_attempt', details=f'username={username}')
            flash("Invalid username or password.", "danger")
    
    return render_template('auth/login.html')

@auth_bp.route('/logout', methods=['POST'])
@login_required
@csrf_protect
def logout():
    """User logout."""
    log_audit('user_logout')
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for('auth.login'))

@auth_bp.route('/password', methods=['GET', 'POST'])
@login_required
@csrf_protect
def change_password():
    """Change user password."""
    if request.method == 'POST':
        current_password = request.form.get('current_password', '')
        new_password = request.form.get('new_password', '')
        confirmation = request.form.get('password_confirmation', '')
        
        user = User.query.get(g.current_user['id'])
        if not user or not check_password_hash(user.password_hash, current_password):
            flash('Your current password is incorrect.', 'danger')
        elif len(new_password) < 12:
            flash('New password must be at least 12 characters.', 'danger')
        elif new_password != confirmation:
            flash('Password confirmation does not match.', 'danger')
        else:
            user.password_hash = generate_password_hash(new_password, method=PASSWORD_HASH_METHOD)
            db.session.commit()
            log_audit('own_password_changed')
            flash('Password changed successfully.', 'success')
            return redirect(url_for('dashboard.index'))
    
    return render_template('auth/change_password.html')
