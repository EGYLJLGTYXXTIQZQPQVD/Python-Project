# --- START OF FILE app/utils/password_utils.py ---

import re
from flask import current_app # Import current_app to check config

# Define password complexity rules
MIN_LENGTH = 8
REQUIRE_UPPER = True
REQUIRE_LOWER = True
REQUIRE_DIGIT = True
REQUIRE_SPECIAL = True
# Define allowed special characters (adjust as needed)
SPECIAL_CHARS_REGEX = r"[!@#$%^&*(),.?\":{}|<>]"
# SPECIAL_CHARS_DISPLAY = "!@#$%^&*(),.?\":{}|<>" # For error messages

def validate_password_complexity(password):
    """
    Validate that a password meets complexity requirements defined above.
    Returns tuple: (is_valid: bool, message: str)
    """
    # Allow bypassing complexity checks in testing environment for convenience
    # Check if current_app context exists and TESTING is True
    try:
        if current_app and current_app.config.get("TESTING"):
             # Simple length check for tests
             if password and isinstance(password, str) and len(password) >= 5:
                 return True, "Password meets minimum test requirements."
             else:
                 return False, "Password must be at least 5 characters in testing mode."
    except RuntimeError:
         # Handle cases where function might be called outside app context (e.g., CLI script)
         # In such cases, enforce full complexity or decide on default behavior.
         # For now, let's enforce full complexity if not in app context.
         pass


    # --- Standard Complexity Checks ---
    if not password or not isinstance(password, str):
        return False, "Password must be provided as a string."

    if len(password) < MIN_LENGTH:
        return False, f"Password must be at least {MIN_LENGTH} characters long."

    errors = []
    if REQUIRE_UPPER and not re.search(r"[A-Z]", password):
        errors.append("contain at least one uppercase letter")
    if REQUIRE_LOWER and not re.search(r"[a-z]", password):
        errors.append("contain at least one lowercase letter")
    if REQUIRE_DIGIT and not re.search(r"\d", password):
        errors.append("contain at least one number")
    if REQUIRE_SPECIAL and not re.search(SPECIAL_CHARS_REGEX, password):
        errors.append(f"contain at least one special character ({SPECIAL_CHARS_REGEX})") # Show regex pattern

    if not errors:
        return True, "Password meets complexity requirements."
    else:
        # Construct readable error message
        message = "Password must " + ", ".join(errors) + "."
        return False, message
# --- END OF FILE app/utils/password_utils.py ---