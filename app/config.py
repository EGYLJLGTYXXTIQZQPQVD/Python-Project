import os
from datetime import timedelta

class Config:
    """Base configuration class for the application."""
    SECRET_KEY = os.environ.get('SECRET_KEY', 'a-very-secure-default-secret-key') # Use a better default
    SQLALCHEMY_DATABASE_URI = os.environ.get('SQLALCHEMY_DATABASE_URI', 'sqlite:///bank.db') # Default to file in instance folder
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY', 'a-secure-jwt-secret-key') # Use a better default
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=1)
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=30)
    # Configure JWT to include 'jti' needed for blocklisting
    JWT_DECODE_ISSUER = False # Adjust if you use issuer validation
    JWT_ENCODE_ISSUER = None
    JWT_ALGORITHM = "HS256"
    # Application specific configs
    DEBUG = False
    TESTING = False
    ENABLE_RATE_LIMIT = True # Flag to easily disable rate limiting if needed

class DevelopmentConfig(Config):
    """Development configuration."""
    DEBUG = True
    # Use a file-based db for easier inspection in dev
    SQLALCHEMY_DATABASE_URI = os.environ.get('DEV_DATABASE_URI', 'sqlite:///../instance/bank_dev.db') # Path relative to app folder
    SECRET_KEY = 'dev-secret-key' # Keep simple key for dev
    JWT_SECRET_KEY = 'dev-jwt-secret-key' # Keep simple key for dev


class TestingConfig(Config):
    """Testing configuration."""
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:' # Use in-memory DB for tests
    SECRET_KEY = 'test-secret-key'
    JWT_SECRET_KEY = 'test-jwt-secret-key'
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(seconds=5) # Short expiry for testing token expiration
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(seconds=10)
    # Disable CSRF protection if using Flask-WTF (not used here)
    WTF_CSRF_ENABLED = False
    DEBUG = True # Often helpful to have debug on during tests
    ENABLE_RATE_LIMIT = False # Disable rate limiting for tests


class ProductionConfig(Config):
    """Production configuration."""
    # Ensure these are set via environment variables in production
    SECRET_KEY = os.environ.get('SECRET_KEY')
    JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY')
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') # Use DATABASE_URL convention
    ENABLE_RATE_LIMIT = True # Ensure rate limiting is on

    # Basic input validation for production config
    if not SECRET_KEY:
        raise ValueError("No SECRET_KEY set for Flask application in production")
    if not JWT_SECRET_KEY:
        raise ValueError("No JWT_SECRET_KEY set for Flask application in production")
    if not SQLALCHEMY_DATABASE_URI:
        raise ValueError("No DATABASE_URL set for Flask application in production")


# Configuration dictionary to select the appropriate configuration
config = {
    'development': DevelopmentConfig,
    'testing': TestingConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}