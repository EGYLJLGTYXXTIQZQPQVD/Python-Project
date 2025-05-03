from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from app import db
from app.models.account import Account
from app.models.transaction import Transaction
from app.utils.validators import error_response # Removed unused validate_amount
from decimal import Decimal, InvalidOperation

bp = Blueprint('transactions', __name__, url_prefix='/api/transactions')

# --- Helper Function for Amount Validation ---
def validate_transaction_amount(amount_str):
    """Validates if the amount is a positive Decimal."""
    try:
        amount = Decimal(str(amount_str)) # Ensure it's treated as string first
        if amount <= Decimal('0.00'):
            return None, "Amount must be positive"
        # Optional: Add maximum amount check
        # if amount > Decimal('10000.00'):
        #     return None, "Amount exceeds maximum limit"
        return amount, None # Return Decimal amount and no error
    except (InvalidOperation, ValueError, TypeError):
        return None, "Amount must be a valid number"

# --- Route Implementations ---

@bp.route('', methods=['GET'])
@jwt_required()
def get_all_user_transactions():
    """Get transaction history across all accounts for the authenticated user."""
    try:
        user_id = int(get_jwt_identity())
    except (ValueError, TypeError):
         return error_response("Invalid user identity in token", 400)

    # Get all active account IDs for the user
    user_accounts = Account.query.filter_by(user_id=user_id, is_active=True).with_entities(Account.id).all()
    if not user_accounts:
        return jsonify({'transactions': [], 'total_items': 0}) # No accounts, no transactions

    account_ids = [acc.id for acc in user_accounts]

    # Pagination and filtering (similar to account specific endpoint)
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    if page < 1 or per_page < 1 or per_page > 100:
        return error_response('Invalid pagination parameters.', 400)

    # Base query: transactions involving any of the user's accounts
    query = Transaction.query.filter(
        (Transaction.from_account_id.in_(account_ids)) |
        (Transaction.to_account_id.in_(account_ids))
    )

    # Apply optional filters (e.g., date range, type, search - similar to accounts route)
    # ... (Add filtering logic here if needed, mirroring GET /accounts/{id}/transactions) ...

    try:
        paginated_transactions = query.order_by(Transaction.timestamp.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
    except Exception as e:
        print(f"Error retrieving all transactions for user {user_id}: {e}")
        return error_response("Error retrieving transactions", 500)


    transactions_list = [transaction.to_dict() for transaction in paginated_transactions.items]

    return jsonify({
        'transactions': transactions_list,
        'page': page,
        'per_page': per_page,
        'total_items': paginated_transactions.total,
        'total_pages': paginated_transactions.pages
    })

@bp.route('/deposit', methods=['POST'])
@jwt_required(fresh=True) # Require fresh token for monetary operations
def deposit():
    """Deposit funds into a user's own account."""
    try:
        user_id = int(get_jwt_identity())
    except (ValueError, TypeError):
         return error_response("Invalid user identity in token", 400)

    data = request.get_json()
    if not data or not all(k in data for k in ('account_id', 'amount')):
        return error_response('Account ID and amount are required', 400)

    account_id = data.get('account_id')
    amount_str = data.get('amount')
    description = data.get('description', 'Deposit')

    # Validate amount
    amount, error_msg = validate_transaction_amount(amount_str)
    if error_msg:
        return error_response(error_msg, 400)

    # Get the account, ensuring it belongs to the user and is active
    account = Account.query.filter_by(id=account_id, user_id=user_id, is_active=True).first()
    if not account:
        return error_response('Active account not found or does not belong to you', 404)

    try:
        # Update balance
        account.balance += amount

        # Create transaction record
        transaction = Transaction(
            transaction_type='deposit',
            amount=amount,
            to_account_id=account.id,
            description=description
        )
        db.session.add(transaction)
        db.session.commit()

        return jsonify({
            'message': 'Deposit successful',
            'transaction': transaction.to_dict(),
            'new_balance': float(account.balance) # Return as float
        }), 201 # Use 201 Created for successful resource creation (transaction)

    except Exception as e:
        db.session.rollback()
        print(f"Error during deposit to account {account_id}: {e}")
        return error_response('Deposit failed', 500)


@bp.route('/withdraw', methods=['POST'])
@jwt_required(fresh=True) # Require fresh token
def withdraw():
    """Withdraw funds from a user's own account."""
    try:
        user_id = int(get_jwt_identity())
    except (ValueError, TypeError):
         return error_response("Invalid user identity in token", 400)

    data = request.get_json()
    if not data or not all(k in data for k in ('account_id', 'amount')):
        return error_response('Account ID and amount are required', 400)

    account_id = data.get('account_id')
    amount_str = data.get('amount')
    description = data.get('description', 'Withdrawal')

    amount, error_msg = validate_transaction_amount(amount_str)
    if error_msg:
        return error_response(error_msg, 400)

    # Get account, check ownership and activity
    account = Account.query.filter_by(id=account_id, user_id=user_id, is_active=True).first()
    if not account:
        return error_response('Active account not found or does not belong to you', 404)

    # Check sufficient balance
    if account.balance < amount:
        return error_response('Insufficient funds', 400) # 400 Bad Request is common here

    try:
        # Update balance
        account.balance -= amount

        # Create transaction record
        transaction = Transaction(
            transaction_type='withdrawal',
            amount=amount,
            from_account_id=account.id,
            description=description
        )
        db.session.add(transaction)
        db.session.commit()

        return jsonify({
            'message': 'Withdrawal successful',
            'transaction': transaction.to_dict(),
            'new_balance': float(account.balance)
        }), 201 # 201 as a transaction was created

    except Exception as e:
        db.session.rollback()
        print(f"Error during withdrawal from account {account_id}: {e}")
        return error_response('Withdrawal failed', 500)

# --- Transfer Endpoint (Handles internal & potentially external transfers) ---
# Use a lock or transaction isolation for transfers if high concurrency is expected
@bp.route('/transfer', methods=['POST'])
@jwt_required(fresh=True) # Require fresh token
def transfer():
    """Transfer funds from user's account to another account (user's or other)."""
    try:
        user_id = int(get_jwt_identity())
    except (ValueError, TypeError):
         return error_response("Invalid user identity in token", 400)

    data = request.get_json()
    if not data or not all(k in data for k in ('from_account_id', 'to_account_id', 'amount')):
        return error_response('From account ID, to account ID, and amount are required', 400)

    from_account_id = data.get('from_account_id')
    to_account_id = data.get('to_account_id')
    amount_str = data.get('amount')
    description = data.get('description') # Optional description

    # Basic validation
    if from_account_id == to_account_id:
        return error_response('Cannot transfer to the same account', 400)

    amount, error_msg = validate_transaction_amount(amount_str)
    if error_msg:
        return error_response(error_msg, 400)

    # --- Database Operations within a Transaction ---
    try:
        # Lock the accounts involved if using pessimistic locking, or rely on transaction isolation
        # Get 'from' account, ensuring ownership and activity
        from_account = Account.query.filter_by(id=from_account_id, user_id=user_id, is_active=True).first()
        if not from_account:
            return error_response('Source account not found, inactive, or does not belong to you', 404)

        # Get 'to' account (can belong to anyone, must be active)
        to_account = Account.query.filter_by(id=to_account_id, is_active=True).first()
        if not to_account:
            return error_response('Destination account not found or is inactive', 404)

        # Check sufficient funds in 'from' account
        if from_account.balance < amount:
            return error_response('Insufficient funds in source account', 400)

        # Perform balance updates
        from_account.balance -= amount
        to_account.balance += amount

        # Generate description if not provided
        if not description:
            description = f'Transfer from {from_account.account_number} to {to_account.account_number}'

        # Create transaction record
        transaction = Transaction(
            transaction_type='transfer',
            amount=amount,
            from_account_id=from_account.id,
            to_account_id=to_account.id,
            description=description
        )
        db.session.add(transaction)

        # Commit all changes together
        db.session.commit()

        # Success response
        return jsonify({
            'message': 'Transfer successful',
            'transaction': transaction.to_dict(),
            'from_account_balance': float(from_account.balance),
            'to_account_balance': float(to_account.balance)
        }), 201 # 201 for created transaction

    except Exception as e:
        db.session.rollback() # Rollback on any error
        print(f"Error during transfer from {from_account_id} to {to_account_id}: {e}")
        # More specific error checking (e.g., constraint violations) could be added
        return error_response('Transfer failed due to an internal error', 500)


# --- /transfer-advanced Endpoint ---
# This seems redundant given the try/except block added to /transfer.
# If it serves a specific purpose (e.g., different validation rules, different auth requirements),
# keep it, otherwise, it could be removed. Assuming it might be needed for tests.
@bp.route('/transfer-advanced', methods=['POST'])
@jwt_required() # Note: Not requiring fresh=True as per original code
def transfer_advanced():
    # This implementation mirrors the corrected '/transfer' route exactly.
    # If different logic is intended, it needs to be specified.
    try:
        user_id = int(get_jwt_identity())
    except (ValueError, TypeError):
         return error_response("Invalid user identity in token", 400)

    data = request.get_json()
    if not data or not all(k in data for k in ('from_account_id', 'to_account_id', 'amount')):
        return error_response('From account ID, to account ID, and amount are required', 400)

    from_account_id = data.get('from_account_id')
    to_account_id = data.get('to_account_id')
    amount_str = data.get('amount')
    description = data.get('description')

    if from_account_id == to_account_id:
        return error_response('Cannot transfer to the same account', 400)

    amount, error_msg = validate_transaction_amount(amount_str)
    if error_msg:
        return error_response(error_msg, 400)

    try:
        from_account = Account.query.filter_by(id=from_account_id, user_id=user_id, is_active=True).first()
        if not from_account:
            return error_response('Source account not found, inactive, or does not belong to you', 404)

        to_account = Account.query.filter_by(id=to_account_id, is_active=True).first()
        if not to_account:
            return error_response('Destination account not found or is inactive', 404)

        if from_account.balance < amount:
            return error_response('Insufficient funds in source account', 400)

        from_account.balance -= amount
        to_account.balance += amount

        if not description:
            description = f'Transfer from {from_account.account_number} to {to_account.account_number}'

        transaction = Transaction(
            transaction_type='transfer',
            amount=amount,
            from_account_id=from_account.id,
            to_account_id=to_account.id,
            description=description
        )
        db.session.add(transaction)
        db.session.commit()

        return jsonify({
            'message': 'Transfer successful',
            'transaction': transaction.to_dict(),
            'from_account_balance': float(from_account.balance),
            'to_account_balance': float(to_account.balance)
        }), 201

    except Exception as e:
        db.session.rollback()
        print(f"Error during advanced transfer from {from_account_id} to {to_account_id}: {e}")
        return error_response('Transfer failed due to an internal error', 500)

# --- Endpoint for Account-Specific Transactions (POST/GET) ---
# Note: This endpoint duplicates functionality from other routes.
# GET is same as GET /api/accounts/{account_id}/transactions
# POST combines deposit, withdrawal, transfer logic based on 'type' field.
# Keep it if required by tests, otherwise consider consolidating.
@bp.route('/accounts/<int:account_id>/transactions', methods=['POST', 'GET'])
@jwt_required() # Changed from fresh=True in original, adjust if freshness needed
def account_transactions_alt(account_id):
    """Handle GET (list) or POST (create) transactions for a specific account."""
    try:
        user_id = int(get_jwt_identity())
    except (ValueError, TypeError):
         return error_response("Invalid user identity in token", 400)

    # Verify account ownership and activity status
    account = Account.query.filter_by(id=account_id, user_id=user_id, is_active=True).first()
    if not account:
        return error_response('Active account not found or does not belong to you', 404)

    # --- Handle GET Request (List Transactions) ---
    if request.method == 'GET':
        # This logic is identical to GET /api/accounts/{account_id}/transactions
        # Consider redirecting or calling the other function? For now, duplicate.
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        if page < 1 or per_page < 1 or per_page > 100:
             return error_response('Invalid pagination parameters.', 400)

        query = Transaction.query.filter(
            or_(Transaction.from_account_id == account_id, Transaction.to_account_id == account_id)
        )
        # Add filtering/sorting as needed here...
        paginated_transactions = query.order_by(Transaction.timestamp.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
        transactions_list = [tx.to_dict() for tx in paginated_transactions.items]

        return jsonify({
            'transactions': transactions_list,
            'page': page,
            'per_page': per_page,
            'total_items': paginated_transactions.total,
            'total_pages': paginated_transactions.pages
        })

    # --- Handle POST Request (Create Transaction) ---
    if request.method == 'POST':
        data = request.get_json()
        if not data or not all(k in data for k in ('type', 'amount')):
            return error_response('Transaction type and amount are required', 400)

        transaction_type = data.get('type', '').lower()
        amount_str = data.get('amount')
        description = data.get('description')

        amount, error_msg = validate_transaction_amount(amount_str)
        if error_msg:
            return error_response(error_msg, 400)

        transaction = None # Initialize transaction object

        try:
            if transaction_type == 'deposit':
                account.balance += amount
                transaction = Transaction(
                    transaction_type='deposit',
                    amount=amount,
                    to_account_id=account_id,
                    description=description or 'Deposit'
                )

            elif transaction_type == 'withdrawal':
                if account.balance < amount:
                    return error_response('Insufficient funds', 400)
                account.balance -= amount
                transaction = Transaction(
                    transaction_type='withdrawal',
                    amount=amount,
                    from_account_id=account_id,
                    description=description or 'Withdrawal'
                )

            elif transaction_type == 'transfer':
                to_account_id = data.get('to_account_id')
                if not to_account_id:
                    return error_response('Destination account ID (to_account_id) is required for transfers', 400)
                if int(to_account_id) == account_id:
                     return error_response('Cannot transfer to the same account', 400)

                if account.balance < amount:
                    return error_response('Insufficient funds', 400)

                to_account = Account.query.filter_by(id=to_account_id, is_active=True).first()
                if not to_account:
                    return error_response('Destination account not found or is inactive', 404)

                # Perform updates
                account.balance -= amount
                to_account.balance += amount

                transaction = Transaction(
                    transaction_type='transfer',
                    amount=amount,
                    from_account_id=account_id,
                    to_account_id=to_account_id,
                    description=description or f'Transfer to {to_account.account_number}'
                )
            else:
                return error_response('Invalid transaction type. Must be deposit, withdrawal, or transfer', 400)

            # Add transaction to session and commit
            db.session.add(transaction)
            db.session.commit()

            # Success response
            response_data = {
                'message': f'{transaction_type.capitalize()} successful',
                'transaction': transaction.to_dict(),
                'new_balance': float(account.balance),
                'id': transaction.id # Include id as per original code
            }
            # If transfer, optionally include destination balance
            if transaction_type == 'transfer':
                 response_data['to_account_balance'] = float(to_account.balance)


            return jsonify(response_data), 201

        except Exception as e:
            db.session.rollback()
            print(f"Error processing POST to /accounts/{account_id}/transactions: {e}")
            return error_response(f'{transaction_type.capitalize()} failed', 500)

    # Should not reach here if method is GET or POST
    return error_response("Method not allowed", 405)