from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from app import db
from app.models.account import Account
from app.models.user import User
from app.models.transaction import Transaction
from app.utils.validators import error_response
# from app.utils.account_utils import generate_account_number # Not used currently
from datetime import datetime
from sqlalchemy import or_, and_
import uuid # Used by inline account number generation
import time # Used by inline account number generation
from decimal import Decimal, InvalidOperation # Use Decimal for money

bp = Blueprint('accounts', __name__, url_prefix='/api/accounts')

MAX_ACCOUNTS_PER_USER = 5 # Increased limit slightly

@bp.route('', methods=['GET'])
@jwt_required()
def get_accounts():
    """List all active accounts for the authenticated user."""
    try:
        user_id = int(get_jwt_identity()) # Ensure user_id is int
    except (ValueError, TypeError):
         return error_response("Invalid user identity in token", 400)

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)
    # Validate pagination params
    if page < 1 or per_page < 1 or per_page > 100:
         return error_response("Invalid pagination parameters. Page must be >= 1, 1 <= per_page <= 100", 400)

    account_type = request.args.get('type') # Filter by account type

    query = Account.query.filter(
        Account.user_id == user_id,
        Account.is_active == True # Only list active accounts
    )

    if account_type:
        query = query.filter(Account.account_type.ilike(f"%{account_type}%")) # Case-insensitive filter

    try:
        paginated_accounts = query.order_by(Account.created_at.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
    except Exception as e:
        print(f"Error during account pagination: {e}")
        return error_response("Error retrieving accounts", 500)

    accounts_data = []
    for account in paginated_accounts.items:
        account_dict = account.to_dict()
        # Standardize response format as per original attempt
        accounts_data.append({
            'id': account_dict['id'],
            'category': account_dict['account_type'], # Rename 'account_type'
            'label': account_dict['account_name'],    # Rename 'account_name'
            'balance': round(account_dict['balance'], 2), # Ensure balance is rounded correctly
            'account_number': account_dict['account_number'], # Include account number
            'created_at': account_dict['created_at']
        })

    return jsonify({
        'account_listing': accounts_data,
        'page': page,
        'per_page': per_page,
        'total': paginated_accounts.total,
        'total_pages': paginated_accounts.pages
    })

@bp.route('/<int:account_id>', methods=['GET'])
@jwt_required()
def get_account(account_id):
    """Get details of a specific account owned by the user."""
    try:
        user_id = int(get_jwt_identity())
    except (ValueError, TypeError):
         return error_response("Invalid user identity in token", 400)

    # CORRECTED: Filter by account_id AND user_id AND is_active
    account = Account.query.filter(
        Account.id == account_id,
        Account.user_id == user_id,
        Account.is_active == True
    ).first()

    if not account:
        # CORRECTED: Return 404 if not found or not owned by user
        return error_response('Account not found or access denied', 404)

    account_data = account.to_dict()
    # Return data in the structure shown in the original code's example
    return jsonify({
        'status': 'success', # Keep original status for compatibility?
        'message': 'Account retrieved',
        'account_detail': account_data,
        'balance': round(account_data['balance'], 2), # Use rounded balance from dict
    })

@bp.route('', methods=['POST'])
@jwt_required() # Fresh token not strictly needed for creation, but okay
def create_account():
    """Create a new account for the authenticated user."""
    try:
        user_id = int(get_jwt_identity())
    except (ValueError, TypeError):
         return error_response("Invalid user identity in token", 400)

    data = request.get_json()
    if not data:
        return error_response("Request body must be JSON", 400)

    user = User.query.get(user_id)
    if not user or not user.is_active:
        return error_response('User not found or inactive', 404)

    # Check account limit
    account_count = Account.query.filter_by(user_id=user_id, is_active=True).count()
    if account_count >= MAX_ACCOUNTS_PER_USER:
        return error_response(f'Maximum of {MAX_ACCOUNTS_PER_USER} active accounts allowed per user', 400)

    # Get and validate account details from payload
    account_type = data.get('account_type') or data.get('type', 'checking') # Default type
    account_name = data.get('account_name') or data.get('name') or data.get('label') # Allow different keys
    description = data.get('description')
    initial_balance_str = str(data.get('initial_balance', '0.0')) # Default balance is 0

    # Validate account name (optional, but if provided, check length)
    if account_name and (len(account_name) < 3 or len(account_name) > 100):
        return error_response('Account name must be between 3 and 100 characters', 400)

    # Validate initial balance
    try:
        initial_balance = Decimal(initial_balance_str)
        # Allow zero or positive balance, maybe small negative for overdraft setup?
        if initial_balance < Decimal('-50.00'): # Check against allowed minimum
             return error_response('Initial balance cannot be less than -50.00', 400)
    except InvalidOperation:
        return error_response('Initial balance must be a valid number', 400)

    # Generate a unique account number (using the inline method from original code)
    timestamp = int(time.time() * 1000)
    unique_suffix = str(uuid.uuid4().int)[-8:]
    account_prefix = "ACC" + str(user_id)[-3:].zfill(3)
    account_number = f"{account_prefix}{(timestamp % 10000):04d}{unique_suffix[:4]}" # Padded timestamp part

    # Ensure uniqueness just in case (rare collision)
    while Account.query.filter_by(account_number=account_number).first():
         unique_suffix = str(uuid.uuid4().int)[-8:]
         account_number = f"{account_prefix}{(timestamp % 10000):04d}{unique_suffix[:4]}"


    try:
        new_account = Account(
            account_number=account_number,
            account_type=account_type,
            account_name=account_name,
            description=description,
            balance=initial_balance, # Use Decimal
            user_id=user_id
        )
        db.session.add(new_account)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"Error creating account: {e}")
        return error_response('Could not create account', 500)

    # CORRECTED: Return consistent balance, use standard keys
    account_data = new_account.to_dict()
    return jsonify({
        'message': 'Account created successfully',
        'id': new_account.id,
        'category': new_account.account_type, # Use consistent key 'category'
        'label': new_account.account_name,    # Use consistent key 'label'
        'balance': round(float(new_account.balance), 2), # Return actual balance, rounded float
        'account': account_data # Include full details if needed
    }), 201

@bp.route('/<int:account_id>', methods=['PUT'])
@jwt_required(fresh=True) # Require fresh token for updates
def update_account(account_id):
    """Update details of a specific account."""
    try:
        user_id = int(get_jwt_identity())
    except (ValueError, TypeError):
         return error_response("Invalid user identity in token", 400)

    data = request.get_json()
    if not data:
        return error_response("Request body must be JSON", 400)

    # CORRECTED: Filter by account_id AND user_id AND is_active
    account = Account.query.filter(
        Account.id == account_id,
        Account.user_id == user_id,
        Account.is_active == True
    ).first()

    if not account:
        return error_response('Account not found or access denied', 404)

    updated = False
    # Update account name (accept 'account_name' or 'account_label')
    new_name = data.get('account_name') or data.get('account_label')
    if new_name is not None:
        if not isinstance(new_name, str) or len(new_name) < 3 or len(new_name) > 100:
            return error_response('Account name must be a string between 3 and 100 characters', 400)
        account.account_name = new_name
        updated = True

    # Update description
    if 'description' in data:
        # REMOVED: Obscure logic based on ';' in description
        # if data.get('description') and ';' in data.get('description'):
        #     account.is_active = False # This logic was removed

        account.description = data['description']
        updated = True

    # Potentially update other fields like 'account_type' if allowed
    if 'account_type' in data or 'type' in data:
        new_type = data.get('account_type') or data.get('type')
        # Add validation for allowed account types if necessary
        account.account_type = new_type
        updated = True

    if updated:
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"Error updating account {account_id}: {e}")
            return error_response('Could not update account', 500)
    else:
        return jsonify({'message': 'No changes provided for update'}), 200 # Or 304 Not Modified?

    return jsonify({
        'message': 'Account updated successfully',
        'account_detail': account.to_dict()
    })

@bp.route('/<int:account_id>', methods=['DELETE'])
@jwt_required(fresh=True) # Require fresh token for deletion
def delete_account(account_id):
    """Delete (soft delete) a specific account."""
    try:
        user_id = int(get_jwt_identity())
    except (ValueError, TypeError):
         return error_response("Invalid user identity in token", 400)

    # CORRECTED: Filter by account_id AND user_id AND is_active
    account = Account.query.filter(
        Account.id == account_id,
        Account.user_id == user_id,
        Account.is_active == True # Only allow deleting active accounts
    ).first()

    if not account:
        return error_response('Account not found or access denied', 404)

    # Check if account balance is zero before allowing deletion (optional business rule)
    # if account.balance != Decimal('0.00'):
    #     return error_response('Account cannot be deleted with a non-zero balance', 400)

    # Perform soft delete
    account.is_active = False
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"Error deleting account {account_id}: {e}")
        return error_response('Could not delete account', 500)

    # Return 200 OK or 204 No Content
    return jsonify({
        'message': 'Account marked as inactive successfully'
    }), 200


@bp.route('/<int:account_id>/transactions', methods=['GET'])
@jwt_required()
def get_account_transactions(account_id):
    """Get transaction history for a specific account."""
    try:
        user_id = int(get_jwt_identity())
    except (ValueError, TypeError):
         return error_response("Invalid user identity in token", 400)

    # CORRECTED: Verify account ownership and activity status
    account = Account.query.filter(
        Account.id == account_id,
        Account.user_id == user_id,
        # Allow viewing transactions for inactive accounts? Or only active?
        # Account.is_active == True # Let's allow viewing history even if inactive
    ).first()

    if not account:
        return error_response('Account not found or access denied', 404)

    # Base query for transactions related to this account
    query = Transaction.query.filter(
        or_(
            Transaction.from_account_id == account_id,
            Transaction.to_account_id == account_id
        )
    )

    # Filtering logic (dates, type, search)
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')
    tx_type = request.args.get('type')
    search = request.args.get('search')

    try:
        if start_date_str:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
            query = query.filter(Transaction.timestamp >= start_date)
        if end_date_str:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
            # Include the entire end day
            end_date = end_date.replace(hour=23, minute=59, second=59, microsecond=999999)
            query = query.filter(Transaction.timestamp <= end_date)
    except ValueError:
        return error_response('Invalid date format. Use YYYY-MM-DD', 400)

    if tx_type:
        tx_type = tx_type.lower()
        if tx_type in ['deposit', 'withdrawal', 'transfer']:
             # Refined filtering based on direction relative to the account_id
             if tx_type == 'deposit':
                 query = query.filter(Transaction.to_account_id == account_id, Transaction.transaction_type == 'deposit')
             elif tx_type == 'withdrawal':
                 query = query.filter(Transaction.from_account_id == account_id, Transaction.transaction_type == 'withdrawal')
             elif tx_type == 'transfer':
                  # Show both incoming and outgoing transfers for this account
                  query = query.filter(Transaction.transaction_type == 'transfer',
                                       or_(Transaction.from_account_id == account_id, Transaction.to_account_id == account_id) )
        else:
             return error_response('Invalid transaction type filter. Use deposit, withdrawal, or transfer.', 400)

    if search:
        search_term = f'%{search}%'
        # Search in description, maybe transaction type?
        query = query.filter(Transaction.description.ilike(search_term))

    # Pagination logic
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
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

    # Return consistent response format
    response = {
        'transactions': transactions_list,
        'page': page,                     # Renamed from 'pg'
        'per_page': per_page,             # Renamed from 'per_pg'
        'total_items': paginated_transactions.total,
        'total_pages': paginated_transactions.pages # Add total pages
    }

    # Keep 'tx_list' for compatibility if needed by tests
    # response['tx_list'] = transactions_list

    return jsonify(response)