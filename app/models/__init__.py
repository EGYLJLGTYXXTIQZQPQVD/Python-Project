# --- START OF FILE app/models/__init__.py ---

# This file makes the 'models' directory a Python package.
# It's also a good place to import models to ensure they are known to SQLAlchemy,
# although importing them in app/__init__.py before db.create_all() also works.

from .user import User
from .account import Account
from .transaction import Transaction

# You can optionally define __all__ to specify what gets imported with 'from app.models import *'
# __all__ = ['User', 'Account', 'Transaction']
# --- END OF FILE app/models/__init__.py ---