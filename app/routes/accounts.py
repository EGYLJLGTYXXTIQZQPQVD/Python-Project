# --- START OF FILE app/routes/accounts.py ---

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, current_user
from app import db
from app.models.account import Account
from app.models.user import User
from app.models.transaction import Transaction
from app.utils.validators import error_response
from datetime import datetime
from sqlalchemy import or_
import uuid # For generating account numbers
import time # For generating account numbers
from decimal import Decimal, InvalidOperation # Use Decimal for money

# Blueprint configuration (prefix '/api/accounts' is applied during registration)
bp = Blueprint('accounts', __name__)

MAX_ACCOUNTS_PER_USER = 10 # Define limit for number of accounts per user

# --- Helper: Generate Unique Account Number ---
# Simple example, consider more robust generation for production
def generate_unique_account_number(user_id):
    """Generates a unique account number."""
    while True:
        # Example format: ACC<last 3 digits of user_id>_<timestamp_part>_<random>
        timestamp_part = str(int(time.time() * 1000))[-6:] # Use last 6 digits of ms timestamp
        random_part = str(uuid.uuid4().int)[-6:] # Use last 6 digits of UUID int
        user_id_part = str(user_id)[-3:].zfill(3) # Pad user ID part
        account_number = f"ACC{user_id_part}-{timestamp_part}-{random_part}"

        # Check uniqueness in the database
        if not Account.query.filter_by(account_number=account_number).first():
            return account_number
        # print(f"Account number collision, generating new one...") # Debugging


# --- GET /api/accounts ---
@bp.route('', methods=['GET'])
@jwt_required()
def get_accounts():
    """List all active accounts for the authenticated user with pagination."""
    # current_user is loaded by JWT
    if not current_user:
        return error_response("User not found", 404)

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)
    account_type_filter = request.args.get('type') # Filter by account type

    # Validate pagination params
    if page < 1 or per_page < 1 or per_page > 100:
         return error_response("Invalid pagination parameters. Page must be >= 1, 1 <= per_page <= 100", 400)

    # Base query for active accounts owned by the current user
    query = Account.query.filter(
        Account.user_id == current_user.id,
        Account.is_active == True
    )

    # Apply optional filter
    if account_type_filter:
        query = query.filter(Account.account_type.ilike(f"%{account_type_filter}%")) # Case-insensitive filter

    try:
        paginated_accounts = query.order_by(Account.created_at.desc()).paginate(
            page=page, per_page=per_page, error_out=False # error_out=False prevents 404 on empty page
        )
    except Exception as e:
        print(f"Error during account pagination for user {current_user.id}: {e}")
        return error_response("Error retrieving accounts", 500)

    # Prepare response data using the model's to_dict method
    accounts_data = [account.to_dict() for account in paginated_accounts.items]

    # Standardize response format based on Swagger/tests
    response_data = []
    for acc_dict in accounts_data:
        response_data.append({
            'id': acc_dict['id'],
            'category': acc_dict['account_type'], # Rename key
            'label': acc_dict['account_name'],    # Rename key
            # Ensure balance is float and rounded for display if needed
            'balance': round(acc_dict['balance'], 2),
            'account_number': acc_dict['account_number'],
            'created_at': acc_dict['created_at'],
            'is_active': acc_dict['is_active']
        })

    return jsonify({
        'account_listing': response_data, # Use the key from Swagger
        'page': paginated_accounts.page,
        'per_page': paginated_accounts.per_page,
        'total': paginated_accounts.total,
        'total_pages': paginated_accounts.pages
    })

# --- GET /api/accounts/{account_id} ---
@bp.route('/<int:account_id>', methods=['GET'])
@jwt_required()
def get_account(account_id):
    """Get details of a specific active account owned by the user."""
    if not current_user:
        return error_response("User not found", 404)

    # Query for the specific account, ensuring it belongs to the user and is active
    account = Account.query.filter(
        Account.id == account_id,
        Account.user_id == current_user.id,
        Account.is_active == True # Usually only show active accounts directly
    ).first()

    if not account:
        # Return 404 if account doesn't exist, doesn't belong to user, or is inactive
        return error_response('Account not found or access denied', 404)

    account_data = account.to_dict()
    # Return data matching Swagger structure
    return jsonify({
        'message': 'Account retrieved successfully',
        'account_detail': account_data,
        'balance': round(account_data['balance'], 2), # Include balance separately if needed by tests
    })

# --- POST /api/accounts ---
@bp.route('', methods=['POST'])
@jwt_required() # Fresh token not strictly required for creation, but okay
def create_account():
    """Create a new account for the authenticated user."""
    if not current_user or not current_user.is_active:
        return error_response('User not found or inactive', 404)

    data = request.get_json()
    if not data:
        return error_response("Request body must be JSON", 400)

    # Check account limit
    # Use lazy='dynamic' on User.accounts relationship if performance is concern for many accounts
    # account_count = current_user.accounts.filter_by(is_active=True).count() # If using dynamic
    account_count = Account.query.filter_by(user_id=current_user.id, is_active=True).count()
    if account_count >= MAX_ACCOUNTS_PER_USER:
        return error_response(f'Maximum of {MAX_ACCOUNTS_PER_USER} active accounts allowed per user', 400)

    # --- Get and Validate Account Details ---
    # Allow different keys for compatibility ('account_type' or 'type', 'account_name' or 'name'/'label')
    account_type = data.get('account_type', data.get('type', 'checking')).strip() # Default type
    account_name = data.get('account_name', data.get('name', data.get('label')))
    description = data.get('description', '').strip()
    initial_balance_str = str(data.get('initial_balance', '0.00')) # Default balance is 0

    # Validate account name (optional, but good practice)
    if account_name:
        account_name = account_name.strip()
        if not (3 <= len(account_name) <= 100):
            return error_response('Account name must be between 3 and 100 characters', 400)
    else:
        # Default account name if not provided
        account_name = f"{account_type.capitalize()} Account {account_count + 1}"


    # Validate initial balance
    try:
        initial_balance = Decimal(initial_balance_str)
        # Define allowed range for initial balance (e.g., cannot start deeply negative)
        if initial_balance < Decimal('-100.00') or initial_balance > Decimal('1000000.00'): # Example limits
             return error_response('Initial balance is outside the allowed range (-100 to 1,000,000)', 400)
    except InvalidOperation:
        return error_response('Initial balance must be a valid number', 400)

    # --- Create Account ---
    account_number = generate_unique_account_number(current_user.id)

    try:
        new_account = Account(
            account_number=account_number,
            account_type=account_type,
            account_name=account_name,
            description=description,
            balance=initial_balance, # Use Decimal
            user_id=current_user.id, # Set owner
            is_active=True # New accounts start active
        )
        db.session.add(new_account)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"Error creating account for user {current_user.id}: {e}")
        return error_response('Could not create account due to an internal error', 500)

    # Return created account details, matching Swagger/test structure
    created_account_data = new_account.to_dict()
    return jsonify({
        'message': 'Account created successfully',
        'id': new_account.id,
        'category': new_account.account_type, # Consistent key 'category'
        'label': new_account.account_name,    # Consistent key 'label'
        'balance': round(float(new_account.balance), 2), # Return rounded float
        'account_number': new_account.account_number,
        'account_detail': created_account_data # Include full details if needed
    }), 201 # 201 Created

# --- PUT /api/accounts/{account_id} ---
@bp.route('/<int:account_id>', methods=['PUT'])
@jwt_required(fresh=True) # Require fresh token for updates
def update_account(account_id):
    """Update details (name, description, type) of a specific active account."""
    if not current_user:
        return error_response("User not found", 404)

    data = request.get_json()
    if not data:
        return error_response("Request body must be JSON", 400)

    # Find the account, ensuring it belongs to the user and is active
    account = Account.query.filter(
        Account.id == account_id,
        Account.user_id == current_user.id,
        Account.is_active == True # Can only update active accounts
    ).first()

    if not account:
        return error_response('Active account not found or access denied', 404)

    updated = False
    # Update account name (accept 'account_name' or 'account_label')
    new_name = data.get('account_name', data.get('account_label'))
    if new_name is not None:
        new_name = new_name.strip()
        if not (3 <= len(new_name) <= 100):
            return error_response('Account name must be a string between 3 and 100 characters', 400)
        if account.account_name != new_name:
            account.account_name = new_name
            updated = True

    # Update description
    if 'description' in data:
        new_description = data['description'].strip()
        if account.description != new_description:
            account.description = new_description
            updated = True

    # Update account type (accept 'account_type' or 'type')
    new_type = data.get('account_type', data.get('type'))
    if new_type is not None:
        new_type = new_type.strip()
        # Add validation for allowed account types if necessary
        # allowed_types = ['checking', 'savings', 'loan']
        # if new_type.lower() not in allowed_types:
        #     return error_response(f'Invalid account type. Allowed types: {", ".join(allowed_types)}', 400)
        if account.account_type != new_type:
            account.account_type = new_type
            updated = True

    # --- Commit Changes ---
    if updated:
        try:
            db.session.commit()
            return jsonify({
                'message': 'Account updated successfully',
                'account_detail': account.to_dict() # Return updated details
            })
        except Exception as e:
            db.session.rollback()
            print(f"Error updating account {account_id}: {e}")
            return error_response('Could not update account due to an internal error', 500)
    else:
        # No changes were made or provided
        return jsonify({
            'message': 'No changes provided or necessary for update',
            'account_detail': account.to_dict() # Return current details
        }), 200 # OK, but no changes applied

# --- DELETE /api/accounts/{account_id} ---
@bp.route('/<int:account_id>', methods=['DELETE'])
@jwt_required(fresh=True) # Require fresh token for deletion
def delete_account(account_id):
    """Soft delete a specific active account (marks as inactive)."""
    if not current_user:
        return error_response("User not found", 404)

    # Find the account, ensuring it belongs to the user and is currently active
    account = Account.query.filter(
        Account.id == account_id,
        Account.user_id == current_user.id,
        Account.is_active == True # Only allow deleting currently active accounts
    ).first()

    if not account:
        return error_response('Active account not found or access denied', 404)

    # --- Business Rule: Check balance before deletion? ---
    # Decide if deletion is allowed with non-zero balance.
    # if account.balance != Decimal('0.00'):
    #     return error_response('Account cannot be deleted with a non-zero balance. Please transfer funds first.', 400)

    # --- Perform Soft Delete ---
    account.is_active = False
    try:
        db.session.commit()
        # Return 200 OK or 204 No Content
        # return '', 204
        return jsonify({'message': f'Account {account.account_number} marked as inactive successfully'}), 200
    except Exception as e:
        db.session.rollback()
        print(f"Error soft-deleting account {account_id}: {e}")
        return error_response('Could not deactivate account due to an internal error', 500)


# --- GET /api/accounts/{account_id}/transactions ---
@bp.route('/<int:account_id>/transactions', methods=['GET'])
@jwt_required()
def get_account_transactions(account_id):
    """Get transaction history for a specific account owned by the user."""
    if not current_user:
        return error_response("User not found", 404)

    # Verify the account exists and belongs to the current user.
    # Allow viewing transactions even if the account is inactive.
    account = Account.query.filter(
        Account.id == account_id,
        Account.user_id == current_user.id
    ).first()

    if not account:
        return error_response('Account not found or access denied', 404)

    # --- Filtering Logic ---
    query = Transaction.query.filter(
        or_(
            Transaction.from_account_id == account_id,
            Transaction.to_account_id == account_id
        )
    )

    # Date Filtering
    try:
        start_date_str = request.args.get('start_date')
        if start_date_str:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            # Make timezone-aware if DB stores timezone info (recommended)
            # start_date = datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc)
            query = query.filter(Transaction.timestamp >= start_date)

        end_date_str = request.args.get('end_date')
        if end_date_str:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            # Include the entire end day
            end_datetime = datetime.combine(end_date, datetime.max.time())
            # Make timezone-aware if needed
            # end_datetime = end_datetime.replace(tzinfo=timezone.utc)
            query = query.filter(Transaction.timestamp <= end_datetime)
    except ValueError:
        return error_response('Invalid date format. Use YYYY-MM-DD', 400)

    # Type Filtering
    tx_type = request.args.get('type', '').lower()
    if tx_type:
        allowed_types = ['deposit', 'withdrawal', 'transfer']
        if tx_type not in allowed_types:
             return error_response(f'Invalid transaction type filter. Use one of: {", ".join(allowed_types)}.', 400)
        # Refined filtering based on direction relative to *this* account_id
        if tx_type == 'deposit':
             query = query.filter(Transaction.to_account_id == account_id, Transaction.transaction_type == 'deposit')
        elif tx_type == 'withdrawal':
             query = query.filter(Transaction.from_account_id == account_id, Transaction.transaction_type == 'withdrawal')
        elif tx_type == 'transfer':
             # Show transfers where this account is either sender OR receiver
             query = query.filter(Transaction.transaction_type == 'transfer',
                                  or_(Transaction.from_account_id == account_id, Transaction.to_account_id == account_id))

    # Search Filtering (in description)
    search = request.args.get('search')
    if search:
        search_term = f'%{search}%'
        query = query.filter(Transaction.description.ilike(search_term))

    # --- Pagination Logic ---
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int) # Default 20 per page
    if page < 1 or per_page < 1 or per_page > 100:
        return error_response('Invalid pagination parameters. Page must be >= 1, 1 <= per_page <= 100', 400)

    try:
        paginated_transactions = query.order_by(Transaction.timestamp.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
    except Exception as e:
        print(f"Error retrieving transactions for account {account_id}: {e}")
        return error_response("Error retrieving transactions", 500)

    transactions_list = [tx.to_dict() for tx in paginated_transactions.items]

    # Return consistent response format matching Swagger/tests
    return jsonify({
        'transactions': transactions_list,
        'page': paginated_transactions.page,          # Use 'page'
        'per_page': paginated_transactions.per_page,  # Use 'per_page'
        'total_items': paginated_transactions.total,
        'total_pages': paginated_transactions.pages
        # 'tx_list': transactions_list # Keep legacy key if tests require it
    })
# --- END OF FILE app/routes/accounts.py ---