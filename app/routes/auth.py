from flask import Blueprint, request, jsonify
from flask_jwt_extended import (
    create_access_token,
    create_refresh_token,
    jwt_required,
    get_jwt_identity,
    get_jwt,
    verify_jwt_in_request # Import for manual verification if needed
)
from app import db, jwt, token_blocklist # Import blocklist
from app.models.user import User
from app.utils.validators import validate_email, error_response
from app.utils.password_utils import validate_password_complexity # Assume complexity check is moved here
from app import admin_required # Import the admin decorator


bp = Blueprint("auth", __name__, url_prefix="/api")

# Register endpoint (accepts both paths)
@bp.route("/register", methods=["POST"])
@bp.route("/auth/register", methods=["POST"])
def register():
    data = request.get_json()

    if not data:
        return error_response("Request body must be JSON", 400)

    required_fields = ["email", "password"]
    if not all(k in data for k in required_fields):
        return error_response("Missing required fields: email, password", 400)

    email = data["email"].strip().lower()
    password = data["password"] # Don't strip password

    # Parse username or generate one
    username = data.get("username")
    first_name = data.get("first_name")
    last_name = data.get("last_name")

    if username:
        username = username.strip().lower()
    elif first_name and last_name:
        username = f"{first_name.strip().lower()}_{last_name.strip().lower()}"
        # Check if generated username is valid/unique, handle potential collisions
        if User.query.filter_by(username=username).first():
             # Simple collision handling: append number or prompt user
             return error_response(f"Generated username '{username}' already exists. Please provide a unique username.", 400)
    else:
        # Default username from email prefix if no other info provided
        username = email.split("@")[0]
        if User.query.filter_by(username=username).first():
             return error_response(f"Default username '{username}' already exists. Please provide a unique username.", 400)


    if not validate_email(email):
        return error_response("Invalid email format", 400)

    # Use password complexity validator
    is_complex, message = validate_password_complexity(password)
    if not is_complex:
        return error_response(message, 400)

    # Check uniqueness
    if User.query.filter_by(username=username).first():
        return error_response("Username already exists", 409) # 409 Conflict
    if User.query.filter_by(email=email).first():
        return error_response("Email already exists", 409) # 409 Conflict

    try:
        new_user = User(
            username=username,
            email=email,
            password=password,
            first_name=first_name.strip() if first_name else None,
            last_name=last_name.strip() if last_name else None
        )
        db.session.add(new_user)
        db.session.commit()

        return jsonify(
            {"message": "User registered successfully", "user": new_user.to_dict()}
        ), 201
    except Exception as e:
        db.session.rollback()
        # Log the exception e
        print(f"Error during registration: {e}")
        return error_response("Could not register user", 500)


# Login endpoint (accepts both paths)
@bp.route("/login", methods=["POST"])
@bp.route("/auth/login", methods=["POST"])
def login():
    data = request.get_json()
    if not data:
        return error_response("Request body must be JSON", 400)

    identifier = data.get("email") or data.get("username")
    password = data.get("password")

    if not identifier or not password:
        return error_response("Email/username and password are required", 400)

    identifier = identifier.strip().lower()

    # Find user by email or username
    user = User.query.filter(
        (User.email == identifier) | (User.username == identifier)
    ).first()

    # Verify user and password
    if not user or not user.check_password(password) or not user.is_active:
        return error_response("Invalid credentials or inactive user", 401)

    # Add role to JWT claims for authorization checks
    # **SECURITY FIX: DO NOT ADD PLAINTEXT PASSWORD TO CLAIMS**
    additional_claims = {'role': user.role}

    # Create access and refresh tokens
    access_token = create_access_token(identity=user.id, additional_claims=additional_claims, fresh=True) # Make login token fresh
    refresh_token = create_refresh_token(identity=user.id, additional_claims=additional_claims)

    response_data = {
        "message": "Login successful",
        "user": user.to_dict(),
        # Return tokens using consistent keys expected by tests/frontend
        "token": access_token,         # Common legacy key
        "access_token": access_token,  # Standard key
        "refresh_token": refresh_token
    }

    return jsonify(response_data)


# Refresh access token
@bp.route("/auth/refresh", methods=["POST"])
@jwt_required(refresh=True) # CORRECT: Use refresh=True decorator
def refresh():
    current_user_id = get_jwt_identity() # This is the user ID (int)
    user = User.query.get(current_user_id)

    if not user or not user.is_active:
         return error_response("User not found or inactive", 401) # Should not happen if token is valid, but check

    # Get existing claims to persist role
    claims = get_jwt()
    additional_claims = {'role': claims.get('role', 'user')} # Default to 'user' if missing

    # Create a new non-fresh access token
    new_access_token = create_access_token(identity=current_user_id, additional_claims=additional_claims, fresh=False)

    return jsonify(
        {
            "message": "Access token refreshed",
            "token": new_access_token,        # Legacy key compatibility
            "access_token": new_access_token # Standard key
        }
    )


# Logout endpoint
@bp.route("/auth/logout", methods=["POST"])
@jwt_required() # Requires a valid access or refresh token to logout
def logout():
    jti = get_jwt()["jti"]
    token_type = get_jwt()["type"] # Check if it's access or refresh

    # Add the token's JTI to the blocklist
    token_blocklist.add(jti)

    # Optionally, block the refresh token if an access token is used for logout
    # This requires storing refresh token JTIs or linking them, complex for simple blocklist

    return jsonify({"message": f"Successfully logged out ({token_type} token revoked)"})

# Verify token endpoint
@bp.route("/auth/verify", methods=["POST"])
@jwt_required() # CORRECT: Add decorator to enforce verification
def verify_token():
    # If @jwt_required passes, the token is valid and not expired/revoked
    user_id = get_jwt_identity()
    user = User.query.get(user_id)

    if not user or not user.is_active:
        # This case might indicate the user was deactivated after token issuance
        return error_response("Token valid but user is inactive", 403)

    return jsonify({"message": "Token is valid", "verified": True, "user_id": user_id, "role": get_jwt().get('role')})


# Get user profile
@bp.route("/auth/profile", methods=["GET"])
@jwt_required() # Requires valid access token
def get_profile():
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)

    if not user:
        # Should ideally not happen if token is valid, maybe user deleted?
        return error_response("User not found", 404)
    if not user.is_active:
        return error_response("User is inactive", 403)


    return jsonify(user.to_dict())


# Change password endpoint
@bp.route("/auth/change-password", methods=["POST"])
@jwt_required(fresh=True) # Require a fresh token (from login)
def change_password():
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)

    if not user or not user.is_active:
        return error_response("User not found or inactive", 404)

    data = request.get_json()
    if not data or not all(k in data for k in ("current_password", "new_password")):
        return error_response("Current password and new password are required", 400)

    current_password = data["current_password"]
    new_password = data["new_password"]

    # Verify current password
    if not user.check_password(current_password):
        return error_response("Current password is incorrect", 401)

    # Validate new password complexity
    is_complex, message = validate_password_complexity(new_password)
    if not is_complex:
        return error_response(f"New password validation failed: {message}", 400)

    # Prevent setting the same password
    if user.check_password(new_password):
        return error_response("New password cannot be the same as the current password", 400)

    try:
        # Update password hash
        user.set_password(new_password) # Use the model method
        db.session.commit()
        # Optionally: Revoke all existing tokens for the user upon password change
        # (Requires more complex token management than simple blocklist)
        return jsonify({"message": "Password changed successfully"})
    except Exception as e:
        db.session.rollback()
        # Log exception e
        print(f"Error changing password: {e}")
        return error_response("Could not change password", 500)


# --- Admin Endpoints ---

@bp.route("/auth/users", methods=["GET"])
@jwt_required()
@admin_required() # Use the admin decorator
def get_all_users():
    """Retrieve a list of all users (Admin-only)"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)

    users_pagination = User.query.paginate(page=page, per_page=per_page, error_out=False)
    users_list = [user.to_dict() for user in users_pagination.items]

    return jsonify({
        "users": users_list,
        "page": users_pagination.page,
        "per_page": users_pagination.per_page,
        "total_users": users_pagination.total,
        "total_pages": users_pagination.pages
    })

@bp.route("/auth/user/<int:user_id>", methods=["DELETE"])
@jwt_required()
@admin_required() # Use the admin decorator
def delete_user(user_id):
    """Delete a user by ID (Admin-only)"""
    current_user_id = get_jwt_identity()
    if user_id == current_user_id:
        return error_response("Admin cannot delete their own account via this endpoint", 403)

    user = User.query.get(user_id)
    if not user:
        return error_response("User not found", 404)

    try:
        # Hard delete: Deletes the user and potentially associated data via cascades (check model definitions)
        # Soft delete alternative: user.is_active = False
        db.session.delete(user)
        db.session.commit()
        # Optionally: Revoke any remaining tokens for the deleted user (complex with simple blocklist)
        return jsonify({"message": f"User ID {user_id} deleted successfully"})
    except Exception as e:
        db.session.rollback()
        # Log exception e
        print(f"Error deleting user {user_id}: {e}")
        # Check for constraints violation (e.g., if cascade isn't set up correctly)
        return error_response(f"Could not delete user {user_id}", 500)