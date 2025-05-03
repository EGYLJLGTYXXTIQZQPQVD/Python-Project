# --- START OF FILE app/__init__.py ---

import os
import time
from functools import wraps
from flask import Flask, jsonify, request
from flask_sqlalchemy import SQLAlchemy
from flask_jwt_extended import JWTManager, get_jwt, verify_jwt_in_request
from flask_bcrypt import Bcrypt
from dotenv import load_dotenv
from flasgger import Swagger
from flask_cors import CORS

# Load environment variables from .env file
load_dotenv()

# Initialize extensions
db = SQLAlchemy()
jwt = JWTManager()
bcrypt = Bcrypt()

# --- Rate Limiting Setup ---
# Simple in-memory rate limiting store
request_counts = {}
# Allow configuration via environment variables or defaults
RATE_LIMIT = int(os.environ.get('RATE_LIMIT', 15)) # Requests per window
RATE_LIMIT_WINDOW = int(os.environ.get('RATE_LIMIT_WINDOW', 60)) # Window in seconds

# --- Token Blocklist Setup ---
# Simple in-memory blocklist. For production, use Redis or a database table.
token_blocklist = set()

@jwt.token_in_blocklist_loader
def check_if_token_revoked(jwt_header, jwt_payload):
    """Callback for checking if a token's JTI is in the blocklist."""
    jti = jwt_payload.get("jti")
    return jti in token_blocklist

# --- Admin Role Check Decorator ---
def admin_required():
    """Decorator to ensure the user has the 'admin' role."""
    def wrapper(fn):
        @wraps(fn)
        def decorator(*args, **kwargs):
            try:
                verify_jwt_in_request()
                claims = get_jwt()
                if claims.get("role") != "admin":
                    return jsonify(error="Administration privileges required"), 403
                else:
                    return fn(*args, **kwargs)
            except Exception as e:
                # Catch potential JWT errors during verification
                print(f"Error during admin check: {e}")
                return jsonify(error="Unauthorized: Invalid or missing token for admin access"), 401
        return decorator
    return wrapper
# --- End Admin Role Check Decorator ---

def create_app(test_config=None):
    """Application Factory Function"""
    # Create and configure the app
    app = Flask(__name__, instance_relative_config=True)

    # Enable CORS for all routes and origins (adjust in production if needed)
    CORS(app, resources={r"/api/*": {"origins": "*"}}) # Allow all origins for API routes

    # --- Load Configuration ---
    config_name = os.environ.get('FLASK_CONFIG', 'development')
    try:
        from app.config import config as app_configs
        app.config.from_object(app_configs[config_name])
        print(f" * Loaded config: {config_name}")
    except ImportError:
         print("Warning: config.py not found or invalid. Using default Flask settings.")
    except KeyError:
         print(f"Warning: Config '{config_name}' not found. Falling back to 'default'.")
         app.config.from_object(app_configs['default'])


    # Override with test_config if provided (primarily for testing)
    if test_config:
        app.config.from_mapping(test_config)
        print(" * Loaded test configuration.")

    # Ensure JWT keys are set
    if not app.config.get('JWT_SECRET_KEY'):
        raise ValueError("JWT_SECRET_KEY is not set in the configuration!")
    if not app.config.get('SECRET_KEY'):
         raise ValueError("SECRET_KEY is not set in the configuration!")


    # --- Configure Database URI ---
    # Default to instance folder if URI is relative, unless it's in-memory
    db_uri = app.config.get('SQLALCHEMY_DATABASE_URI', 'sqlite:///bank.db')
    if db_uri.startswith('sqlite:///') and not db_uri == 'sqlite:///:memory:':
         # Ensure the path is relative to the instance folder
         db_name = db_uri.split('sqlite:///')[-1]
         instance_path = app.instance_path
         app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{os.path.join(instance_path, db_name)}"
         # Ensure the instance folder exists
         try:
             os.makedirs(instance_path, exist_ok=True)
         except OSError as e:
             print(f"Error creating instance folder at {instance_path}: {e}")


    print(f" * Database URI: {app.config['SQLALCHEMY_DATABASE_URI']}")

    # --- Initialize Extensions with App ---
    db.init_app(app)
    jwt.init_app(app)
    bcrypt.init_app(app)

    # --- Configure Swagger ---
    # Swagger UI configuration to use CDN for assets
    swagger_config = Swagger.DEFAULT_CONFIG
    swagger_config['swagger_ui_bundle_js'] = '//unpkg.com/swagger-ui-dist@3/swagger-ui-bundle.js'
    swagger_config['swagger_ui_standalone_preset_js'] = '//unpkg.com/swagger-ui-dist@3/swagger-ui-standalone-preset.js'
    swagger_config['jquery_js'] = '//unpkg.com/jquery@2.2.4/dist/jquery.min.js'
    swagger_config['swagger_ui_css'] = '//unpkg.com/swagger-ui-dist@3/swagger-ui.css'
    # Specify the path to your swagger.yaml file
    swagger_template_path = os.path.join(os.path.dirname(__file__), 'swagger.yaml')
    if os.path.exists(swagger_template_path):
        swagger = Swagger(app, template_file=swagger_template_path, config=swagger_config)
    else:
        print(f"Warning: swagger.yaml not found at {swagger_template_path}. Initializing Swagger without template.")
        swagger = Swagger(app, config=swagger_config) # Initialize without template if not found

    # --- Configure JWT Handling ---
    @jwt.user_identity_loader
    def user_identity_lookup(user):
        """Specifies that the user's ID should be used as the identity in JWT."""
        return user.id # Assuming 'user' object passed during token creation has 'id'

    @jwt.user_lookup_loader
    def user_lookup_callback(_jwt_header, jwt_data):
        """Loads user object from identity (user ID) stored in JWT."""
        identity = jwt_data.get("sub")
        if identity is None:
            return None
        from app.models.user import User
        return User.query.filter_by(id=identity, is_active=True).one_or_none()

    # --- JWT Error Handlers ---
    @jwt.expired_token_loader
    def expired_token_callback(jwt_header, jwt_payload):
        return jsonify({"error": "Token has expired"}), 401

    @jwt.invalid_token_loader
    def invalid_token_callback(error):
        # Provides more context about why the token is invalid
        return jsonify({"error": f"Invalid token: {error}"}), 422 # 422 Unprocessable Entity is sometimes used

    @jwt.unauthorized_loader
    def missing_token_callback(error):
        return jsonify({"error": "Authorization token is missing"}), 401

    @jwt.needs_fresh_token_loader
    def token_not_fresh_callback(jwt_header, jwt_payload):
        return jsonify({"error": "Fresh token required for this operation"}), 401

    @jwt.revoked_token_loader
    def revoked_token_callback(jwt_header, jwt_payload):
        return jsonify({"error": "Token has been revoked (logged out)"}), 401

    # --- Request Hooks ---

    @app.before_request
    def before_request_func():
        """Actions to perform before each request."""
        # Rate Limiting (apply before processing the request)
        if app.config.get('ENABLE_RATE_LIMIT', True) and not app.config.get('TESTING'):
            # Apply rate limiting logic only to specific paths if needed, e.g., auth
            # Here, applying broadly to /api/ paths, excluding Swagger
            if request.path.startswith('/api/') and not request.path.startswith('/apidocs'):
                # Use X-Forwarded-For if behind a proxy, fallback to remote_addr
                client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
                current_time = time.time()

                # Clean up old entries from request_counts (simple approach)
                cutoff = current_time - RATE_LIMIT_WINDOW
                # Use list() to avoid RuntimeError: dictionary changed size during iteration
                for ip in list(request_counts.keys()):
                    timestamps = [t for t in request_counts.get(ip, []) if t > cutoff]
                    if timestamps:
                        request_counts[ip] = timestamps
                    else:
                        # Remove IP if no recent requests within the window
                        if ip in request_counts: # Check existence before deleting
                             del request_counts[ip]

                # Check current request count for the client IP
                client_requests = request_counts.get(client_ip, [])
                if len(client_requests) >= RATE_LIMIT:
                    # Return 429 Too Many Requests
                    return jsonify({"error": f"Rate limit exceeded. Please try again in {RATE_LIMIT_WINDOW} seconds."}), 429

                # Record the current request timestamp
                client_requests.append(current_time)
                request_counts[client_ip] = client_requests
                # print(f"Rate limit check: IP {client_ip}, Count: {len(client_requests)}") # Debugging


    @app.after_request
    def add_security_headers(response):
        """Add security headers to responses."""
        # Skip adding headers to Swagger UI routes to avoid potential conflicts
        if request.path.startswith('/apidocs') or request.path.startswith('/flasgger_static'):
            return response

        # Prevent MIME type sniffing
        response.headers['X-Content-Type-Options'] = 'nosniff'
        # Prevent framing of the site
        response.headers['X-Frame-Options'] = 'DENY'
        # Enable XSS filter in browsers
        response.headers['X-XSS-Protection'] = '1; mode=block'
        # Content Security Policy (adjust as needed for your frontend/static files)
        # 'self' allows resources from the same origin. Add other sources if necessary.
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'" # Allow inline for Swagger potentially
        # Enforce HTTPS
        if not app.config.get('DEBUG'): # Only enforce in non-debug environments
             response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        # Control referrer information
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        # Remove server identification header
        response.headers['Server'] = 'BankAPI' # Obscure default server name

        return response

    # --- Register Blueprints ---
    # Import blueprints here to avoid circular imports
    from app.routes import auth, accounts, transactions
    app.register_blueprint(auth.bp, url_prefix='/api') # Keep /api prefix here
    app.register_blueprint(accounts.bp, url_prefix='/api/accounts')
    app.register_blueprint(transactions.bp, url_prefix='/api/transactions')

    # --- Import Models ---
    # Ensure models are imported so SQLAlchemy knows about them
    from app.models import user, account, transaction

    # --- Root Endpoint ---
    @app.route('/')
    def home():
        # Redirect to Swagger UI or provide a simple welcome message
        # from flask import redirect, url_for
        # return redirect(url_for('flasgger.apidocs'))
        return jsonify({"message": "Welcome to the Banking API. Visit /apidocs for documentation."})

    # --- CLI Commands ---
    @app.cli.command('init-db')
    def init_db_command():
        """Drop existing tables and create new tables based on models."""
        # Safety check to prevent accidental execution in production
        allow_init = os.environ.get("FLASK_ALLOW_INIT_DB", "false").lower() == "true"
        if not app.config['DEBUG'] and not app.config['TESTING'] and not allow_init:
            print('Error: Database initialization is disabled in this environment.')
            print('Set FLASK_CONFIG to development/testing or set FLASK_ALLOW_INIT_DB=true to override.')
            return

        print('Dropping existing database tables...')
        db.drop_all()
        print('Creating new database tables...')
        db.create_all()

        # Optional: Seed database with initial data (e.g., admin user)
        from app.models.user import User
        admin_username = os.environ.get('ADMIN_USERNAME', 'admin')
        admin_email = os.environ.get('ADMIN_EMAIL', 'admin@example.com')
        admin_password = os.environ.get('ADMIN_PASSWORD', 'DefaultAdminPassword1!') # Use env var!

        if not User.query.filter_by(username=admin_username).first():
            print(f"Creating default admin user: {admin_username} / {admin_email}")
            try:
                admin_user = User(
                    username=admin_username,
                    email=admin_email,
                    password=admin_password, # Password will be hashed by User model
                    first_name='Admin',
                    last_name='User'
                )
                admin_user.role = 'admin' # Explicitly set role
                admin_user.is_active = True
                db.session.add(admin_user)
                db.session.commit()
                print(f"Default admin user created. Username: {admin_username}, Password: [set from env or default]")
                if admin_password == 'DefaultAdminPassword1!':
                     print("WARNING: Using default admin password. Change it or set ADMIN_PASSWORD env var.")
            except Exception as e:
                db.session.rollback()
                print(f"Error creating default admin user: {e}")

        print('Database initialized successfully.')

    return app
# --- END OF FILE app/__init__.py ---