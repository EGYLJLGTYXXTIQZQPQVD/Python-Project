import os
from flask import Flask, jsonify, request, Response
from flask_sqlalchemy import SQLAlchemy
from flask_jwt_extended import JWTManager, get_jwt
from flask_bcrypt import Bcrypt
from dotenv import load_dotenv
from flasgger import Swagger
from flask_cors import CORS
import time
from functools import wraps

# Load environment variables
load_dotenv()

# Initialize extensions
db = SQLAlchemy()
jwt = JWTManager()
bcrypt = Bcrypt()

# Dictionary to track request counts for rate limiting
request_counts = {}
# How many requests allowed within the time window
RATE_LIMIT = 15
# Time window in seconds
RATE_LIMIT_WINDOW = 60

# Blocklist for revoked tokens (simple in-memory implementation)
token_blocklist = set()

@jwt.token_in_blocklist_loader
def check_if_token_revoked(jwt_header, jwt_payload):
    jti = jwt_payload["jti"]
    return jti in token_blocklist

# --- Admin Role Check Decorator ---
def admin_required():
    def wrapper(fn):
        @wraps(fn)
        def decorator(*args, **kwargs):
            # Ensure the user is authenticated first
            from flask_jwt_extended import verify_jwt_in_request, get_jwt
            verify_jwt_in_request()
            claims = get_jwt()
            # Check if the user has the 'admin' role
            if claims.get("role") != "admin":
                return jsonify(error="Administration privileges required"), 403
            else:
                return fn(*args, **kwargs)
        return decorator
    return wrapper
# --- End Admin Role Check Decorator ---

def create_app(test_config=None):
    # Create and configure the app
    app = Flask(__name__, instance_relative_config=True)

    # Enable CORS for all routes
    CORS(app)

    # Initialize Swagger for API documentation
    # Ensure swagger.yaml is in the 'app' directory or adjust the path
    swagger_config = Swagger.DEFAULT_CONFIG
    swagger_config['swagger_ui_bundle_js'] = '//unpkg.com/swagger-ui-dist@3/swagger-ui-bundle.js'
    swagger_config['swagger_ui_standalone_preset_js'] = '//unpkg.com/swagger-ui-dist@3/swagger-ui-standalone-preset.js'
    swagger_config['jquery_js'] = '//unpkg.com/jquery@2.2.4/dist/jquery.min.js'
    swagger_config['swagger_ui_css'] = '//unpkg.com/swagger-ui-dist@3/swagger-ui.css'
    try:
        swagger_template_path = os.path.join(os.path.dirname(__file__), 'swagger.yaml')
        if os.path.exists(swagger_template_path):
             swagger = Swagger(app, template_file=swagger_template_path, config=swagger_config)
        else:
             print(f"Warning: swagger.yaml not found at {swagger_template_path}. Swagger UI might not work correctly.")
             swagger = Swagger(app, config=swagger_config) # Initialize without template if not found
    except Exception as e:
        print(f"Error initializing Swagger: {e}")
        # Fallback initialization if template loading fails
        swagger = Swagger(app, config=swagger_config)


    # Load configuration based on environment variable or default to development
    config_name = os.environ.get('FLASK_CONFIG', 'development')
    # Use the custom config.py structure
    from app.config import config as app_configs
    app.config.from_object(app_configs[config_name])

    # Override with test_config if provided
    if test_config:
        app.config.from_mapping(test_config)

    # Ensure database URI uses instance path if relative
    if 'sqlite:///' in app.config['SQLALCHEMY_DATABASE_URI'] and not app.config['SQLALCHEMY_DATABASE_URI'].startswith('sqlite:///:memory:'):
         app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{os.path.join(app.instance_path, 'bank.db')}"


    # Ensure the instance folder exists
    try:
        os.makedirs(app.instance_path)
    except OSError:
        pass

    # Initialize extensions with app
    db.init_app(app)
    jwt.init_app(app)
    bcrypt.init_app(app)

    # Configure JWT handling
    @jwt.user_identity_loader
    def user_identity_lookup(identity):
        # Identity is expected to be user ID (int)
        return identity # Keep it as int internally

    @jwt.user_lookup_loader
    def user_lookup_callback(_jwt_header, jwt_data):
        identity = jwt_data["sub"]
        from app.models.user import User
        # Identity should already be the user ID (int)
        return User.query.filter_by(id=identity).one_or_none()

    # Error handling
    @jwt.expired_token_loader
    def expired_token_callback(_jwt_header, jwt_payload):
        return jsonify({"error": "Token has expired"}), 401 # Use 'error' key for consistency

    @jwt.invalid_token_loader
    def invalid_token_callback(error):
        return jsonify({"error": f"Invalid token: {error}"}), 401 # Use 'error' key

    @jwt.unauthorized_loader
    def missing_token_callback(error):
        return jsonify({"error": "Authentication required"}), 401 # Use 'error' key

    # In testing mode, make token expiration predictable
    if app.config.get('TESTING'):
        # Short expiry already set in TestingConfig, no need to override here unless necessary
        pass

    # Add security headers
    @app.after_request
    def add_security_headers(response):
        # Skip Swagger UI routes
        if request.path.startswith('/apidocs') or request.path.startswith('/flasgger_static'):
            return response

        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        # Consider a stricter CSP if needed
        response.headers['Content-Security-Policy'] = "default-src 'self'"
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'

        return response

    # Implement rate limiting
    @app.before_request
    def rate_limiting():
        # Skip rate limiting in test mode or if disabled
        if app.config.get('TESTING') or not app.config.get('ENABLE_RATE_LIMIT', True): # Add config flag
            return

        # Apply only to specific sensitive endpoints if needed, e.g., login/register
        # Here applying to all /api/auth/* for simplicity as per original code
        # Note: Original code also had '/api/login' which is redundant if '/api/auth' is checked.
        if request.path.startswith('/api/auth'):
            # Use X-Forwarded-For if behind proxy, fallback to remote_addr
            client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
            current_time = time.time()

            # Clean up old requests (simple cleanup)
            cutoff = current_time - RATE_LIMIT_WINDOW
            for ip in list(request_counts.keys()):
                timestamps = [t for t in request_counts[ip] if t > cutoff]
                if timestamps:
                    request_counts[ip] = timestamps
                else:
                    del request_counts[ip] # Remove IP if no recent requests

            # Check current request count
            client_requests = request_counts.get(client_ip, [])
            if len(client_requests) >= RATE_LIMIT:
                return jsonify({"error": "Too many requests, please try again later"}), 429

            # Add current request
            client_requests.append(current_time)
            request_counts[client_ip] = client_requests


    # Register models (ensure they are defined before init-db)
    from app.models import user, account, transaction

    # Register blueprints
    from app.routes import auth, accounts, transactions
    app.register_blueprint(auth.bp)
    app.register_blueprint(accounts.bp)
    app.register_blueprint(transactions.bp)

    # Root endpoint for testing
    @app.route('/')
    def home():
        return jsonify({"message": "Welcome to the Banking API"})

    # CLI commands
    @app.cli.command('init-db')
    def init_db_command():
        """Clear the existing data and create new tables."""
        with app.app_context():
             # Added check to prevent dropping production data accidentally
             if app.config['DEBUG'] or app.config['TESTING'] or os.environ.get("FLASK_ALLOW_INIT_DB") == "true":
                 print('Dropping and recreating database tables...')
                 db.drop_all()
                 db.create_all()
                 # Optional: Add default admin user or other seed data
                 print('Initialized the database.')
                 # Example: Create a default admin user if needed
                 from app.models.user import User
                 if not User.query.filter_by(username='admin').first():
                     admin_user = User(username='admin', email='admin@example.com', password='DefaultAdminPassword1!')
                     admin_user.role = 'admin' # Set role to admin
                     db.session.add(admin_user)
                     db.session.commit()
                     print('Default admin user created (admin/DefaultAdminPassword1!). CHANGE THIS PASSWORD!')
             else:
                 print('Skipping db initialization in production environment without FLASK_ALLOW_INIT_DB=true.')


    return app