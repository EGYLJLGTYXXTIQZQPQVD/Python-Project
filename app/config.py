# --- START OF FILE app/config.py ---

import os
from datetime import timedelta

# Base directory of the application
basedir = os.path.abspath(os.path.dirname(__file__))
# Instance folder path (usually one level up from 'app' directory)
instance_path = os.path.join(basedir, '..', 'instance')

class Config:
    """Base configuration class."""
    # Secret key for session management, CSRF, etc.
    # IMPORTANT: Load from environment variable in production!
    SECRET_KEY = os.environ.get('SECRET_KEY', 'a-very-insecure-default-secret-key-CHANGE-ME')

    # Database configuration
    # Default to SQLite in the instance folder for easy setup
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        f'sqlite:///{os.path.join(instance_path, "bank.db")}'
    SQLALCHEMY_TRACK_MODIFICATIONS = False # Disable modification tracking to save resources

    # JWT Configuration
    # IMPORTANT: Load from environment variable in production!
    JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY', 'a-very-insecure-jwt-secret-key-CHANGE-ME')
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=1) # Default access token lifetime
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=30) # Default refresh token lifetime
    # Include 'jti' (JWT ID) in tokens, required for blocklisting/revocation
    JWT_ACCESS_JTI = True
    JWT_REFRESH_JTI = True
    # Where to look for the JWT (standard 'Authorization: Bearer <token>' header)
    JWT_TOKEN_LOCATION = ["headers"]

    # Application specific configs
    DEBUG = False
    TESTING = False
    ENABLE_RATE_LIMIT = True # Enable rate limiting by default

    # Ensure instance folder exists for SQLite database if used
    if SQLALCHEMY_DATABASE_URI.startswith('sqlite:///'):
        db_path = SQLALCHEMY_DATABASE_URI.split('sqlite:///')[-1]
        if not os.path.isabs(db_path): # If it's relative, assume it's in instance path
             db_dir = os.path.dirname(os.path.join(instance_path, db_path))
             os.makedirs(db_dir, exist_ok=True)
        else: # If absolute path, ensure directory exists
             db_dir = os.path.dirname(db_path)
             os.makedirs(db_dir, exist_ok=True)


class DevelopmentConfig(Config):
    """Development specific configuration."""
    DEBUG = True
    # Use a separate database file for development
    SQLALCHEMY_DATABASE_URI = os.environ.get('DEV_DATABASE_URL') or \
        f'sqlite:///{os.path.join(instance_path, "bank_dev.db")}'
    # Use simpler keys for development, but still recommend setting via .env
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key')
    JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY', 'dev-jwt-secret-key')
    # Optionally disable rate limiting for easier development
    # ENABLE_RATE_LIMIT = False


class TestingConfig(Config):
    """Testing specific configuration."""
    TESTING = True
    DEBUG = True # Often helpful during tests
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:' # Use in-memory SQLite database for tests
    SECRET_KEY = 'test-secret-key'
    JWT_SECRET_KEY = 'test-jwt-secret-key'
    # Use very short token expiry times for testing expiration scenarios
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(seconds=5)
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(seconds=10)
    # Disable CSRF protection if Flask-WTF is used (not used here, but common practice)
    WTF_CSRF_ENABLED = False
    # Disable rate limiting during tests
    ENABLE_RATE_LIMIT = False


class ProductionConfig(Config):
    """Production specific configuration."""
    # DEBUG and TESTING must be False in production
    DEBUG = False
    TESTING = False

    # Enforce loading sensitive keys from environment variables
    SECRET_KEY = os.environ.get('SECRET_KEY')
    JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY')
    # Use DATABASE_URL convention for production database (e.g., PostgreSQL, MySQL)
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL')
    ENABLE_RATE_LIMIT = True # Ensure rate limiting is enabled

    # --- Input Validation for Production ---
    if not SECRET_KEY:
        raise ValueError("No SECRET_KEY set. Set the SECRET_KEY environment variable for production.")
    if not JWT_SECRET_KEY:
        raise ValueError("No JWT_SECRET_KEY set. Set the JWT_SECRET_KEY environment variable for production.")
    if not SQLALCHEMY_DATABASE_URI:
        raise ValueError("No DATABASE_URL set. Set the DATABASE_URL environment variable for production.")
    if SQLALCHEMY_DATABASE_URI.startswith('sqlite'):
         print("WARNING: Using SQLite database in production is generally not recommended.")


# Dictionary to easily select the configuration
config = {
    'development': DevelopmentConfig,
    'testing': TestingConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig # Default to development if FLASK_CONFIG is not set
}
# --- END OF FILE app/config.py ---