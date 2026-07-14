from flask import g, session
from datetime import datetime
from app.models import User, AuditLog
from app import db
import secrets

def get_csrf_token():
    """Get or create CSRF token for session."""
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_urlsafe(32)
    return session['csrf_token']

def inject_template_globals():
    """Inject global variables into templates."""
    return {
        'csrf_token': get_csrf_token,
        'current_user': g.get('current_user'),
        'today_str': datetime.today().strftime("%Y-%m-%d"),
    }

def log_audit(action, chart_number=None, details=None):
    """Log an action to audit trail."""
    try:
        user_id = g.current_user['id'] if g.get('current_user') else None
        username = g.current_user['username'] if g.get('current_user') else 'system'
        
        audit_entry = AuditLog(
            timestamp=datetime.utcnow(),
            user_id=user_id,
            username=username,
            action=action,
            chart_number=chart_number,
            details=details
        )
        db.session.add(audit_entry)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        from flask import current_app
        current_app.logger.error(f"Audit log failed: {str(e)}")

def parse_date(value, field_name, required=True):
    """Parse and validate date string."""
    if not value:
        if required:
            raise ValueError(f"{field_name} is required.")
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(f"{field_name} must use YYYY-MM-DD format.") from exc

def escape_excel_injection(value):
    """Escape potential Excel formula injection."""
    if isinstance(value, str) and value.startswith(('=', '+', '-', '@')):
        return f"'{value}"
    return value
