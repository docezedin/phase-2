from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from config import config
import logging
from logging.handlers import RotatingFileHandler
import os

db = SQLAlchemy()
migrate = Migrate()
limiter = Limiter(key_func=get_remote_address)

def create_app(config_name=None):
    """Application factory."""
    if config_name is None:
        config_name = os.environ.get("FLASK_ENV", "development")
    
    app = Flask(__name__)
    app.config.from_object(config[config_name])
    
    # Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db)
    limiter.init_app(app)
    
    # Setup logging
    setup_logging(app)
    
    # Register blueprints
    from app.routes import auth_bp, patients_bp, followup_bp, admin_bp, dashboard_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(patients_bp)
    app.register_blueprint(followup_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(dashboard_bp)
    
    # Context processors
    from app.utils import inject_template_globals
    app.context_processor(inject_template_globals)
    
    # Error handlers
    from app.errors import register_error_handlers
    register_error_handlers(app)
    
    with app.app_context():
        db.create_all()
    
    return app

def setup_logging(app):
    """Configure logging."""
    if not app.debug and not app.testing:
        if not os.path.exists("logs"):
            os.mkdir("logs")
        
        file_handler = RotatingFileHandler(
            "logs/yanet.log",
            maxBytes=10240000,
            backupCount=10
        )
        file_handler.setFormatter(logging.Formatter(
            '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
        ))
        file_handler.setLevel(logging.INFO)
        app.logger.addHandler(file_handler)
        app.logger.setLevel(logging.INFO)
        app.logger.info('Yanet Portal startup')
