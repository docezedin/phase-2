from flask import render_template, flash, redirect, url_for, current_app
from werkzeug.exceptions import HTTPException

def register_error_handlers(app):
    """Register error handlers for the app."""
    
    @app.errorhandler(400)
    def bad_request(error):
        current_app.logger.warning(f"Bad request: {error.description}")
        flash(f"Bad request: {error.description}", "danger")
        return redirect(url_for('dashboard.index'))
    
    @app.errorhandler(403)
    def forbidden(error):
        current_app.logger.warning(f"Forbidden access attempt: {error.description}")
        flash("You do not have permission to access this resource.", "danger")
        return redirect(url_for('dashboard.index'))
    
    @app.errorhandler(404)
    def not_found(error):
        current_app.logger.warning(f"Resource not found: {error.description}")
        flash("Resource not found.", "danger")
        return redirect(url_for('dashboard.index'))
    
    @app.errorhandler(429)
    def ratelimit_handler(e):
        flash(f"Rate limit exceeded. Please try again later.", "warning")
        return redirect(url_for('auth.login'))
    
    @app.errorhandler(500)
    def internal_error(error):
        current_app.logger.error(f"Internal server error: {error}", exc_info=True)
        flash("An internal server error occurred. Please contact support.", "danger")
        return redirect(url_for('dashboard.index'))
