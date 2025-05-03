# --- START OF FILE app/routes/__init__.py ---

# This file makes the 'routes' directory a Python package.
# Blueprints are typically registered in the application factory (app/__init__.py)
# after being imported there.

# You could potentially import the blueprints here, but it often leads to circular
# import issues if blueprints need access to 'app' or extensions defined in app/__init__.py.
# It's generally safer to import them within the app factory function.

# from .auth import bp as auth_bp
# from .accounts import bp as accounts_bp
# from .transactions import bp as transactions_bp

# __all__ = ['auth_bp', 'accounts_bp', 'transactions_bp']

# --- END OF FILE app/routes/__init__.py ---