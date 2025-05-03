import re
from flask import jsonify

EMAIL_REGEX = r'^[\w\.-]+@[\w\.-]+\.\w+$'
# A more comprehensive regex (RFC 5322 general conformance) - might be overkill
# EMAIL_REGEX = r"(^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$)"

def validate_email(email):
    """Validate email format using a regular expression."""
    if not email or not isinstance(email, str):
        return False
    # Use re.fullmatch for stricter matching of the entire string
    if re.fullmatch(EMAIL_REGEX, email) is None:
        return False
    return True

# Removed validate_password - use validate_password_complexity instead
# Removed validate_amount - use Decimal-based validation in transaction routes

def error_response(message, status_code=400):
    """Return a standardized JSON error response."""
    # Ensure message is serializable
    if not isinstance(message, (str, dict, list)):
        message = str(message)

    response = jsonify({'error': message})
    response.status_code = status_code
    return response
# --- END OF FILE app/utils/validators.py ---