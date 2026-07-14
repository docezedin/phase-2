from functools import wraps
from flask import g, session, redirect, url_for, flash, abort, request, current_app
import hmac

def login_required(f):
    """Require user to be logged in."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not g.get('current_user'):
            flash("Please sign in to continue.", "warning")
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    """Require user to be admin."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not g.get('current_user'):
            flash("Please sign in to continue.", "warning")
            return redirect(url_for('auth.login'))
        if g.current_user['role'] != 'admin':
            current_app.logger.warning(f"Unauthorized admin access attempt by {g.current_user['username']}")
            abort(403)
        return f(*args, **kwargs)
    return decorated_function

def csrf_protect(f):
    """CSRF token validation."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if request.method == 'POST':
            submitted_token = request.form.get('csrf_token', '')
            session_token = session.get('csrf_token', '')
            if not hmac.compare_digest(submitted_token, session_token):
                current_app.logger.warning("CSRF token validation failed")
                abort(400, "Invalid or missing CSRF token.")
        return f(*args, **kwargs)
    return decorated_function
