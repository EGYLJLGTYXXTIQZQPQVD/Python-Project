# --- START OF FILE app/routes/auth.py ---

from flask import Blueprint, request, jsonify
from flask_jwt_extended import (
    create_access_token,
    create_refresh_token,
    jwt_required,
    get_jwt_identity,
    get_jwt,
    current_user # Proxy object for the loaded user
)
from app import db, jwt, token_blocklist, bcrypt # Import blocklist and bcrypt
from app.models.user import User
from app.utils.validators import validate_email, error_response
from app.utils.password_utils import validate_password_complexity
from app import admin_required # Import the admin decorator
import uuid # For potentially generating unique usernames if needed

# Blueprint configuration
# Note: url_prefix='/api' is applied when registering the blueprint in app/__init__.py
bp = Blueprint("auth", __name__, url_prefix="/auth") # Define prefix here for clarity within the module

# --- Registration ---
# Accepts POST requests on /api/auth/register (due to blueprint registration prefix)
# Also added an alias route for /api/register if needed for compatibility
@bp.route("/register", methods=["POST"])
@bp.route("/register_alias", methods=["POST"]) # Alias route if /api/register is needed
def register():
    """Registers a new user."""
    data = request.get_json()

    if not data:
        return error_response("Request body must be JSON", 400)

    required_fields = ["email", "password"]
    if not all(field in data for field in required_fields):
        missing = [field for field in required_fields if field not in data]
        return error_response(f"Missing required fields: {', '.join(missing)}", 400)

    email = data["email"].strip().lower()
    password = data["password"] # Don't strip password, complexity check handles spaces if needed

    # --- Username Handling ---
    username_provided = data.get("username", "").strip().lower()
    first_name = data.get("first_name", "").strip()
    last_name = data.get("last_name", "").strip()
    username = ""

    if username_provided:
        username = username_provided
    elif first_name and last_name:
        # Generate username from first/last name (simple example)
        base_username = f"{first_name.lower()}_{last_name.lower()}"
        username = base_username
        # Check for collisions and append number if needed (basic handling)
        count = 1
        while User.query.filter_by(username=username).first():
            username = f"{base_username}{count}"
            count += 1
            if count > 10: # Limit attempts to avoid infinite loop
                 return error_response("Could not generate a unique username from name.", 400)
    else:
        # Default username from email prefix
        username_prefix = email.split("@")[0]
        username = username_prefix
        count = 1
        while User.query.filter_by(username=username).first():
             username = f"{username_prefix}{count}"
             count += 1
             if count > 10:
                 return error_response("Could not generate a unique username from email.", 400)

    if not username:
         return error_response("Could not determine username.", 400)


    # --- Validation ---
    if not validate_email(email):
        return error_response("Invalid email format", 400)

    is_complex, message = validate_password_complexity(password)
    if not is_complex:
        return error_response(f"Password validation failed: {message}", 400)

    # Check uniqueness constraints
    if User.query.filter_by(username=username).first():
        return error_response("Username already exists", 409) # 409 Conflict
    if User.query.filter_by(email=email).first():
        return error_response("Email already exists", 409) # 409 Conflict

    # --- User Creation ---
    try:
        new_user = User(
            username=username,
            email=email,
            password=password, # Hashing happens in User.__init__
            first_name=first_name or None,
            last_name=last_name or None
            # role and is_active default in User model
        )
        db.session.add(new_user)
        db.session.commit()

        # Return user info (excluding password hash)
        return jsonify({
            "message": "User registered successfully",
            "user": new_user.to_dict()
        }), 201 # 201 Created
    except Exception as e:
        db.session.rollback()
        print(f"Error during registration: {e}") # Log the error server-side
        return error_response("Could not register user due to an internal error", 500)


# --- Login ---
# Accepts POST requests on /api/auth/login
@bp.route("/login", methods=["POST"])
def login():
    """Authenticates a user and returns JWT tokens."""
    data = request.get_json()
    if not data:
        return error_response("Request body must be JSON", 400)

    # Allow login with either email or username
    identifier = data.get("email") or data.get("username")
    password = data.get("password")

    if not identifier or not password:
        return error_response("Email/username and password are required", 400)

    identifier = identifier.strip().lower()

    # Find user by email or username
    user = User.query.filter(
        (User.email == identifier) | (User.username == identifier)
    ).first()

    # Verify user exists, password is correct, and user is active
    if not user or not user.check_password(password):
        return error_response("Invalid credentials", 401) # Keep error generic for security

    if not user.is_active:
        return error_response("User account is inactive", 403) # Forbidden

    # --- Token Creation ---
    # Identity for the token is the user's ID
    identity = user.id
    # Add custom claims (e.g., role) to the access token
    # **NEVER ADD SENSITIVE INFO LIKE PASSWORDS TO CLAIMS**
    additional_claims = {"role": user.role}

    # Create a fresh access token upon login
    access_token = create_access_token(identity=identity, additional_claims=additional_claims, fresh=True)
    # Create a refresh token (typically longer-lived)
    refresh_token = create_refresh_token(identity=identity, additional_claims=additional_claims) # Include role here too if needed

    return jsonify({
        "message": "Login successful",
        "access_token": access_token,
        "refresh_token": refresh_token,
        "user": user.to_dict() # Include user info in response
    })


# --- Refresh Access Token ---
# Accepts POST requests on /api/auth/refresh
@bp.route("/refresh", methods=["POST"])
@jwt_required(refresh=True) # Decorator requires a valid refresh token
def refresh():
    """Generates a new non-fresh access token using a refresh token."""
    # current_user is automatically loaded based on identity in refresh token
    if not current_user or not current_user.is_active:
         # Should ideally not happen if token verified, but good practice
         return error_response("User not found or inactive", 401)

    # Get existing claims from the refresh token to preserve them (like role)
    claims = get_jwt()
    additional_claims = {"role": claims.get('role', 'user')} # Default if somehow missing

    # Create a new access token (non-fresh)
    new_access_token = create_access_token(identity=current_user.id, additional_claims=additional_claims, fresh=False)

    return jsonify(access_token=new_access_token)


# --- Logout ---
# Accepts POST requests on /api/auth/logout
@bp.route("/logout", methods=["POST"])
@jwt_required() # Requires a valid token (access or refresh) to logout
def logout():
    """Revokes the current token by adding its JTI to the blocklist."""
    jti = get_jwt().get("jti")
    token_type = get_jwt().get("type") # 'access' or 'refresh'

    if not jti:
         return error_response("Missing JTI in token, cannot revoke", 400)

    token_blocklist.add(jti)
    # print(f"Token JTI added to blocklist: {jti}") # Debugging

    # For more robust logout, you might want to revoke associated refresh/access tokens
    # This requires more complex state management (e.g., storing token pairs).

    return jsonify({"message": f"Successfully logged out. {token_type.capitalize()} token revoked."})


# --- Verify Token ---
# Accepts POST requests on /api/auth/verify
@bp.route("/verify", methods=["POST"])
@jwt_required() # This decorator handles validation (signature, expiry, blocklist)
def verify_token():
    """Verifies the validity of the provided token."""
    # If the decorator passes, the token is valid, not expired, and not revoked.
    # current_user is loaded by the user_lookup_loader.
    if not current_user: # Check if user lookup failed (e.g., user deleted after token issued)
         return error_response("Token valid, but user not found", 404)
    if not current_user.is_active:
        return error_response("Token valid, but user account is inactive", 403)

    # Return confirmation and potentially user info/role from token
    claims = get_jwt()
    return jsonify({
        "message": "Token is valid and active",
        "verified": True,
        "user_id": current_user.id,
        "role": claims.get('role', 'user') # Get role from claims
    })


# --- Get User Profile ---
# Accepts GET requests on /api/auth/profile
@bp.route("/profile", methods=["GET"])
@jwt_required() # Requires a valid access token
def get_profile():
    """Returns the profile information of the currently authenticated user."""
    # current_user is loaded via the user_lookup_loader associated with the JWT
    if not current_user:
        return error_response("User not found", 404) # Should not happen if token is valid
    if not current_user.is_active:
         return error_response("User account is inactive", 403)

    return jsonify(current_user.to_dict())


# --- Change Password ---
# Accepts POST requests on /api/auth/change-password
@bp.route("/change-password", methods=["POST"])
@jwt_required(fresh=True) # Require a fresh token (obtained recently from login)
def change_password():
    """Allows the authenticated user to change their password."""
    # current_user is loaded
    if not current_user or not current_user.is_active:
        return error_response("User not found or inactive", 404)

    data = request.get_json()
    if not data or not all(k in data for k in ("current_password", "new_password")):
        return error_response("Current password and new password are required", 400)

    current_password = data["current_password"]
    new_password = data["new_password"]

    # Verify the current password
    if not current_user.check_password(current_password):
        return error_response("Current password is incorrect", 401)

    # Validate the new password complexity
    is_complex, message = validate_password_complexity(new_password)
    if not is_complex:
        return error_response(f"New password validation failed: {message}", 400)

    # Prevent setting the same password
    if current_user.check_password(new_password):
        return error_response("New password cannot be the same as the current password", 400)

    # --- Update Password ---
    try:
        current_user.set_password(new_password) # Use the model method to hash and set
        db.session.commit()

        # SECURITY NOTE: Consider revoking all other existing tokens for this user
        # upon password change. This requires more advanced token management.
        # For now, just add the *current* token used for this request to the blocklist
        # as a minimal measure, although the user might have other valid tokens.
        jti = get_jwt().get("jti")
        if jti:
             token_blocklist.add(jti)

        return jsonify({"message": "Password changed successfully"})
    except Exception as e:
        db.session.rollback()
        print(f"Error changing password for user {current_user.id}: {e}")
        return error_response("Could not change password due to an internal error", 500)


# --- Admin Endpoints ---

# Accepts GET requests on /api/auth/users
@bp.route("/users", methods=["GET"])
@jwt_required()
@admin_required() # Apply the custom admin decorator
def get_all_users():
    """(Admin Only) Retrieve a paginated list of all users."""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)
    # Validate pagination params
    if page < 1 or per_page < 1 or per_page > 100:
         return error_response("Invalid pagination parameters. Page must be >= 1, 1 <= per_page <= 100", 400)

    try:
        users_pagination = User.query.order_by(User.id.asc()).paginate(
            page=page, per_page=per_page, error_out=False # error_out=False prevents 404 on empty page
        )
    except Exception as e:
        print(f"Error during user pagination: {e}")
        return error_response("Error retrieving users", 500)

    users_list = [user.to_dict() for user in users_pagination.items]

    return jsonify({
        "users": users_list,
        "page": users_pagination.page,
        "per_page": users_pagination.per_page,
        "total_users": users_pagination.total,
        "total_pages": users_pagination.pages
    })

# Accepts DELETE requests on /api/auth/user/<user_id>
@bp.route("/user/<int:user_id>", methods=["DELETE"])
@jwt_required()
@admin_required() # Apply the custom admin decorator
def delete_user(user_id):
    """(Admin Only) Delete a user by ID (Hard Delete)."""
    # Prevent admin from deleting themselves via this endpoint
    if user_id == get_jwt_identity():
        return error_response("Admin cannot delete their own account using this endpoint", 403)

    user_to_delete = User.query.get(user_id)
    if not user_to_delete:
        return error_response("User not found", 404)

    # Check if deleting an admin (optional: prevent deleting other admins?)
    # if user_to_delete.role == 'admin':
    #     return error_response("Cannot delete another admin account", 403)

    try:
        # Hard delete: Deletes the user record and cascades based on model relationships (e.g., deletes accounts)
        # Soft delete alternative: user_to_delete.is_active = False
        db.session.delete(user_to_delete)
        db.session.commit()

        # SECURITY NOTE: Ideally, revoke any remaining tokens for the deleted user.
        # This is complex with a simple blocklist.

        return jsonify({"message": f"User ID {user_id} ({user_to_delete.username}) deleted successfully"})
    except Exception as e:
        db.session.rollback()
        print(f"Error deleting user {user_id}: {e}")
        # Check for specific errors like constraint violations if cascade isn't working as expected
        return error_response(f"Could not delete user {user_id} due to an internal error", 500)
# --- END OF FILE app/routes/auth.py ---