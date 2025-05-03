# --- START OF FILE app/utils/__init__.py ---

# This file makes the 'utils' directory a Python package.

# You can import utility functions here if desired, or import them directly where needed.
# from .validators import validate_email, error_response
# from .password_utils import validate_password_complexity
# from .account_utils import generate_account_number

# __all__ = ['validate_email', 'error_response', 'validate_password_complexity', 'generate_account_number']
# --- END OF FILE app/utils/__init__.py ---

# --- START OF FILE app/utils/account_utils.py ---

import random
import string
# Note: This function is currently NOT used by the corrected routes/accounts.py,
# which uses an inline generation method. Kept here for reference or potential future use.

def generate_random_account_number():
    """Generate a simple random account number (example format)."""
    # Example: ACCT- followed by 10 random digits
    digits = ''.join(random.choices(string.digits, k=10))
    return f"ACCT-{digits}"

# Consider adding a function here that takes db session and user_id
# to generate and *ensure* uniqueness if the inline method is removed.
# from app.models.account import Account
# def ensure_unique_account_number(db_session, user_id):
#     while True:
#         # Combine user info, timestamp, randomness for better uniqueness
#         # ... generation logic ...
#         account_number = generate_random_account_number() # Replace with better logic
#         if not db_session.query(Account.id).filter_by(account_number=account_number).first():
#             return account_number
# --- END OF FILE app/utils/account_utils.py ---