# --- START OF FILE app/routes/transactions.py ---

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, current_user
from app import db
from app.models.account import Account
from app.models.transaction import Transaction
from app.utils.validators import error_response
from decimal import Decimal, InvalidOperation
from sqlalchemy import or_, and_ # Import and_ if needed for complex queries
from sqlalchemy.exc import SQLAlchemyError # For catching DB errors

# Blueprint configuration (prefix '/api/transactions' is applied during registration)
bp = Blueprint('transactions', __name__)

# --- Helper Function for Amount Validation ---
def validate_transaction_amount(amount_str):
    """Validates if the amount is a positive Decimal and within reasonable limits."""
    try:
        # Ensure input is treated as string before converting to Decimal
        amount = Decimal(str(amount_str))
        if amount <= Decimal('0.00'):
            return None, "Amount must be positive"
        # Optional: Add maximum amount check (e.g., prevent huge values)
        if amount > Decimal('1000000.00'): # Example max limit
            return None, "Amount exceeds maximum transaction limit ($1,000,000.00)"
        # Ensure only two decimal places (or handle rounding/truncation)
        if amount.as_tuple().exponent < -2:
             # return None, "Amount cannot have more than two decimal places"
             # Or round it:
             amount = amount.quantize(Decimal("0.01")) # Rounds to nearest cent

        return amount, None # Return valid Decimal amount and no error
    except (InvalidOperation, ValueError, TypeError):
        return None, "Amount must be a valid number"
    except Exception as e: # Catch unexpected errors during conversion
         print(f"Unexpected error validating amount '{amount_str}': {e}")
         return None, "Invalid amount format"


# --- GET /api/transactions (All User Transactions) ---
@bp.route('', methods=['GET'])
@jwt_required()
def get_all_user_transactions():
    """Get transaction history across all active accounts for the authenticated user."""
    if not current_user:
        return error_response("User not found", 404)

    # Get IDs of all *active* accounts belonging to the user
    user_account_ids = db.session.query(Account.id).filter(
        Account.user_id == current_user.id,
        Account.is_active == True
    ).all()

    # Extract IDs from the result tuples
    account_ids = [acc_id[0] for acc_id in user_account_ids]

    if not account_ids:
        # No active accounts, return empty list
        return jsonify({
            'transactions': [],
            'page': 1,
            'per_page': 20, # Match default per_page
            'total_items': 0,
            'total_pages': 0
        })

    # --- Pagination and Filtering ---
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    if page < 1 or per_page < 1 or per_page > 100:
        return error_response('Invalid pagination parameters.', 400)

    # Base query: transactions where from_account_id OR to_account_id is in user's active account list
    query = Transaction.query.filter(
        or_(
            Transaction.from_account_id.in_(account_ids),
            Transaction.to_account_id.in_(account_ids)
        )
    )

    # --- Optional Filters (can add date, type, search similar to account specific endpoint) ---
    # Example: Type filter
    tx_type = request.args.get('type', '').lower()
    if tx_type:
        allowed_types = ['deposit', 'withdrawal', 'transfer']
        if tx_type not in allowed_types:
             return error_response(f'Invalid transaction type filter. Use one of: {", ".join(allowed_types)}.', 400)
        query = query.filter(Transaction.transaction_type == tx_type)
        # Note: This simple type filter shows all transfers, not just those involving the user
        # if you need more specific filtering (e.g., only *outgoing* transfers), adjust the base query.

    # --- Execute Query ---
    try:
        paginated_transactions = query.order_by(Transaction.timestamp.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
    except Exception as e:
        print(f"Error retrieving all transactions for user {current_user.id}: {e}")
        return error_response("Error retrieving transactions", 500)

    transactions_list = [transaction.to_dict() for transaction in paginated_transactions.items]

    return jsonify({
        'transactions': transactions_list,
        'page': paginated_transactions.page,
        'per_page': paginated_transactions.per_page,
        'total_items': paginated_transactions.total,
        'total_pages': paginated_transactions.pages
    })

# --- POST /api/transactions/deposit ---
@bp.route('/deposit', methods=['POST'])
@jwt_required(fresh=True) # Require fresh token for monetary operations
def deposit():
    """Deposit funds into a user's own active account."""
    if not current_user:
        return error_response("User not found", 404)

    data = request.get_json()
    if not data:
        return error_response("Request body must be JSON", 400)
    if not all(k in data for k in ('account_id', 'amount')):
        return error_response('Account ID and amount are required', 400)

    account_id = data.get('account_id')
    amount_str = data.get('amount')
    description = data.get('description', 'Deposit').strip() # Default description

    # Validate amount
    amount, error_msg = validate_transaction_amount(amount_str)
    if error_msg:
        return error_response(error_msg, 400)

    # --- Database Operation ---
    try:
        # Get the account, ensuring it belongs to the user and is active
        # Use with_for_update() if using database-level locking for high concurrency
        account = db.session.query(Account).filter(
             Account.id == account_id,
             Account.user_id == current_user.id,
             Account.is_active == True
        ).with_for_update().first() # Lock the row during transaction

        if not account:
            # Rollback not needed here as no changes made yet
            return error_response('Active account not found or does not belong to you', 404)

        # Update balance
        account.balance += amount

        # Create transaction record
        transaction = Transaction(
            transaction_type='deposit',
            amount=amount,
            to_account_id=account.id, # Deposit goes TO this account
            from_account_id=None,     # No source account for deposit
            description=description
        )
        db.session.add(transaction)

        # Commit changes (updates balance and adds transaction)
        db.session.commit()

        return jsonify({
            'message': 'Deposit successful',
            'transaction': transaction.to_dict(),
            'new_balance': float(account.balance) # Return updated balance as float
        }), 201 # 201 Created for the transaction resource

    except SQLAlchemyError as e: # Catch specific DB errors
        db.session.rollback()
        print(f"Database error during deposit to account {account_id}: {e}")
        return error_response('Deposit failed due to a database error', 500)
    except Exception as e: # Catch other unexpected errors
        db.session.rollback()
        print(f"Unexpected error during deposit to account {account_id}: {e}")
        return error_response('Deposit failed due to an internal error', 500)


# --- POST /api/transactions/withdraw ---
@bp.route('/withdraw', methods=['POST'])
@jwt_required(fresh=True) # Require fresh token
def withdraw():
    """Withdraw funds from a user's own active account."""
    if not current_user:
        return error_response("User not found", 404)

    data = request.get_json()
    if not data:
        return error_response("Request body must be JSON", 400)
    if not all(k in data for k in ('account_id', 'amount')):
        return error_response('Account ID and amount are required', 400)

    account_id = data.get('account_id')
    amount_str = data.get('amount')
    description = data.get('description', 'Withdrawal').strip() # Default description

    amount, error_msg = validate_transaction_amount(amount_str)
    if error_msg:
        return error_response(error_msg, 400)

    # --- Database Operation ---
    try:
        # Get account, check ownership, activity, and lock for update
        account = db.session.query(Account).filter(
             Account.id == account_id,
             Account.user_id == current_user.id,
             Account.is_active == True
        ).with_for_update().first() # Lock the row

        if not account:
            return error_response('Active account not found or does not belong to you', 404)

        # Check sufficient balance (using Decimal comparison)
        if account.balance < amount:
            # Rollback not strictly needed, but good practice before returning error
            db.session.rollback()
            return error_response('Insufficient funds', 400) # 400 Bad Request is appropriate

        # Update balance
        account.balance -= amount

        # Create transaction record
        transaction = Transaction(
            transaction_type='withdrawal',
            amount=amount,
            from_account_id=account.id, # Withdrawal comes FROM this account
            to_account_id=None,         # No destination account for withdrawal
            description=description
        )
        db.session.add(transaction)

        # Commit changes
        db.session.commit()

        return jsonify({
            'message': 'Withdrawal successful',
            'transaction': transaction.to_dict(),
            'new_balance': float(account.balance) # Return updated balance
        }), 201 # 201 as a transaction was created

    except SQLAlchemyError as e:
        db.session.rollback()
        print(f"Database error during withdrawal from account {account_id}: {e}")
        return error_response('Withdrawal failed due to a database error', 500)
    except Exception as e:
        db.session.rollback()
        print(f"Unexpected error during withdrawal from account {account_id}: {e}")
        return error_response('Withdrawal failed due to an internal error', 500)


# --- POST /api/transactions/transfer ---
@bp.route('/transfer', methods=['POST'])
@jwt_required(fresh=True) # Require fresh token for transfers
def transfer():
    """Transfer funds from user's active account to another active account."""
    if not current_user:
        return error_response("User not found", 404)

    data = request.get_json()
    if not data:
        return error_response("Request body must be JSON", 400)
    required_fields = ['from_account_id', 'to_account_id', 'amount']
    if not all(k in data for k in required_fields):
        missing = [f for f in required_fields if f not in data]
        return error_response(f'Missing required fields: {", ".join(missing)}', 400)

    try:
        from_account_id = int(data.get('from_account_id'))
        to_account_id = int(data.get('to_account_id'))
    except (ValueError, TypeError):
         return error_response('Account IDs must be valid integers', 400)

    amount_str = data.get('amount')
    description = data.get('description', '').strip() # Optional description

    # Basic validation
    if from_account_id == to_account_id:
        return error_response('Cannot transfer funds to the same account', 400)

    amount, error_msg = validate_transaction_amount(amount_str)
    if error_msg:
        return error_response(error_msg, 400)

    # --- Database Operations within a Transaction ---
    try:
        # Lock both accounts involved to prevent race conditions
        # Order locking (e.g., by ID) to prevent deadlocks if possible
        id1, id2 = sorted((from_account_id, to_account_id))
        locked_accounts = db.session.query(Account).filter(Account.id.in_([id1, id2])).with_for_update().all()

        # Find the specific accounts from the locked results
        from_account = next((acc for acc in locked_accounts if acc.id == from_account_id), None)
        to_account = next((acc for acc in locked_accounts if acc.id == to_account_id), None)


        # --- Validate Accounts ---
        if not from_account:
             return error_response(f'Source account ({from_account_id}) not found', 404)
        if from_account.user_id != current_user.id:
             return error_response('Source account does not belong to you', 403) # Forbidden
        if not from_account.is_active:
             return error_response('Source account is inactive', 400)

        if not to_account:
            return error_response(f'Destination account ({to_account_id}) not found', 404)
        if not to_account.is_active:
            return error_response('Destination account is inactive', 400)

        # Check sufficient funds in source account
        if from_account.balance < amount:
            return error_response('Insufficient funds in source account', 400)

        # --- Perform Balance Updates ---
        from_account.balance -= amount
        to_account.balance += amount

        # Generate description if not provided
        if not description:
            description = f'Transfer from {from_account.account_number} to {to_account.account_number}'

        # --- Create Transaction Record ---
        transaction = Transaction(
            transaction_type='transfer',
            amount=amount,
            from_account_id=from_account.id,
            to_account_id=to_account.id,
            description=description
        )
        db.session.add(transaction)

        # Commit all changes together (updates and insert)
        db.session.commit()

        # --- Success Response ---
        return jsonify({
            'message': 'Transfer successful',
            'transaction': transaction.to_dict(),
            'from_account_balance': float(from_account.balance), # New balance of source
            'to_account_balance': float(to_account.balance)     # New balance of destination
        }), 201 # 201 for created transaction

    except SQLAlchemyError as e:
        db.session.rollback()
        print(f"Database error during transfer from {from_account_id} to {to_account_id}: {e}")
        return error_response('Transfer failed due to a database error', 500)
    except Exception as e:
        db.session.rollback()
        print(f"Unexpected error during transfer from {from_account_id} to {to_account_id}: {e}")
        return error_response('Transfer failed due to an internal error', 500)


# --- POST /api/transactions/transfer-advanced ---
# This endpoint seems redundant given the corrected '/transfer' implementation.
# Kept for compatibility if tests specifically target it.
# Note: Original Swagger didn't require fresh=True here, but it's recommended.
@bp.route('/transfer-advanced', methods=['POST'])
@jwt_required() # Consider changing to fresh=True
def transfer_advanced():
    """(Potentially Redundant) Transfer funds between accounts."""
    # This implementation mirrors the corrected '/transfer' route exactly.
    # If different logic is intended, it needs to be specified here.
    if not current_user:
        return error_response("User not found", 404)

    data = request.get_json()
    if not data: return error_response("Request body must be JSON", 400)
    required = ['from_account_id', 'to_account_id', 'amount']
    if not all(k in data for k in required): return error_response(f'Missing: {", ".join(f for f in required if f not in data)}', 400)

    try:
        from_id, to_id = int(data['from_account_id']), int(data['to_account_id'])
    except (ValueError, TypeError): return error_response('Account IDs must be integers', 400)

    amount_str = data['amount']
    desc = data.get('description', '').strip()

    if from_id == to_id: return error_response('Cannot transfer to the same account', 400)
    amount, err = validate_transaction_amount(amount_str)
    if err: return error_response(err, 400)

    try:
        id1, id2 = sorted((from_id, to_id))
        accounts = db.session.query(Account).filter(Account.id.in_([id1, id2])).with_for_update().all()
        from_acc = next((a for a in accounts if a.id == from_id), None)
        to_acc = next((a for a in accounts if a.id == to_id), None)

        if not from_acc: return error_response(f'Source account ({from_id}) not found', 404)
        if from_acc.user_id != current_user.id: return error_response('Source account does not belong to you', 403)
        if not from_acc.is_active: return error_response('Source account is inactive', 400)
        if not to_acc: return error_response(f'Destination account ({to_id}) not found', 404)
        if not to_acc.is_active: return error_response('Destination account is inactive', 400)
        if from_acc.balance < amount: return error_response('Insufficient funds', 400)

        from_acc.balance -= amount
        to_acc.balance += amount
        if not desc: desc = f'Transfer from {from_acc.account_number} to {to_acc.account_number}'

        tx = Transaction(transaction_type='transfer', amount=amount, from_account_id=from_id, to_account_id=to_id, description=desc)
        db.session.add(tx)
        db.session.commit()

        return jsonify({
            'message': 'Transfer successful', 'transaction': tx.to_dict(),
            'from_account_balance': float(from_acc.balance), 'to_account_balance': float(to_acc.balance)
        }), 201
    except SQLAlchemyError as e:
        db.session.rollback(); print(f"DB Error (Adv Transfer): {e}"); return error_response('DB error', 500)
    except Exception as e:
        db.session.rollback(); print(f"Error (Adv Transfer): {e}"); return error_response('Internal error', 500)


# --- Combined endpoint: GET/POST /api/transactions/accounts/{account_id}/transactions ---
# Note: This endpoint duplicates functionality from other routes.
# GET is same as GET /api/accounts/{account_id}/transactions
# POST combines deposit, withdrawal, transfer logic based on 'type' field.
# Keep it if required by tests, otherwise consider consolidating/removing.
@bp.route('/accounts/<int:account_id>/transactions', methods=['POST', 'GET'])
@jwt_required() # Consider fresh=True for POST
def account_transactions_alt(account_id):
    """Handle GET (list) or POST (create) transactions for a specific account."""
    if not current_user: return error_response("User not found", 404)

    # Verify account ownership and activity status (for POST, must be active)
    account = db.session.query(Account).filter(
        Account.id == account_id,
        Account.user_id == current_user.id
    ).first() # Get account regardless of active status for GET

    if not account:
        return error_response('Account not found or does not belong to you', 404)

    # --- Handle GET Request (List Transactions) ---
    if request.method == 'GET':
        # This logic duplicates GET /api/accounts/{account_id}/transactions
        # Consider calling that function or redirecting if possible.
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        if page < 1 or per_page < 1 or per_page > 100:
             return error_response('Invalid pagination parameters.', 400)

        query = Transaction.query.filter(
            or_(Transaction.from_account_id == account_id, Transaction.to_account_id == account_id)
        )
        # Add filtering/sorting as needed here... (e.g., date, type from request.args)
        try:
            paginated_transactions = query.order_by(Transaction.timestamp.desc()).paginate(
                page=page, per_page=per_page, error_out=False
            )
            transactions_list = [tx.to_dict() for tx in paginated_transactions.items]
            return jsonify({
                'transactions': transactions_list,
                'page': paginated_transactions.page,
                'per_page': paginated_transactions.per_page,
                'total_items': paginated_transactions.total,
                'total_pages': paginated_transactions.pages
            })
        except Exception as e:
             print(f"Error listing alt transactions for account {account_id}: {e}")
             return error_response("Error retrieving transactions", 500)


    # --- Handle POST Request (Create Transaction) ---
    if request.method == 'POST':
        # Ensure account is active for creating transactions
        if not account.is_active:
             return error_response('Account is inactive, cannot create transactions', 400)

        data = request.get_json()
        if not data: return error_response("Request body must be JSON", 400)
        if not all(k in data for k in ('type', 'amount')):
            return error_response('Transaction type and amount are required', 400)

        transaction_type = data.get('type', '').lower()
        amount_str = data.get('amount')
        description = data.get('description', '').strip()

        amount, error_msg = validate_transaction_amount(amount_str)
        if error_msg: return error_response(error_msg, 400)

        transaction = None
        to_account = None # Keep track of destination account for transfer response

        try:
            # Lock the primary account for update
            db.session.refresh(account) # Refresh state before locking
            db.session.query(Account).filter_by(id=account.id).with_for_update().one()

            if transaction_type == 'deposit':
                account.balance += amount
                transaction = Transaction(
                    transaction_type='deposit', amount=amount,
                    to_account_id=account_id, description=description or 'Deposit'
                )

            elif transaction_type == 'withdrawal':
                if account.balance < amount:
                    return error_response('Insufficient funds', 400)
                account.balance -= amount
                transaction = Transaction(
                    transaction_type='withdrawal', amount=amount,
                    from_account_id=account_id, description=description or 'Withdrawal'
                )

            elif transaction_type == 'transfer':
                to_account_id_str = data.get('to_account_id')
                if not to_account_id_str:
                    return error_response('Destination account ID (to_account_id) is required for transfers', 400)
                try:
                     to_account_id = int(to_account_id_str)
                except (ValueError, TypeError):
                     return error_response('Destination account ID must be an integer', 400)

                if to_account_id == account_id:
                     return error_response('Cannot transfer to the same account', 400)
                if account.balance < amount:
                    return error_response('Insufficient funds', 400)

                # Lock destination account as well
                to_account = db.session.query(Account).filter(
                    Account.id == to_account_id, Account.is_active == True
                ).with_for_update().first()

                if not to_account:
                    return error_response('Destination account not found or is inactive', 404)

                # Perform updates
                account.balance -= amount
                to_account.balance += amount

                transaction = Transaction(
                    transaction_type='transfer', amount=amount,
                    from_account_id=account_id, to_account_id=to_account_id,
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
                # Include id as per original Swagger example for this endpoint
                'id': transaction.id
            }
            if transaction_type == 'transfer' and to_account:
                 response_data['to_account_balance'] = float(to_account.balance)

            return jsonify(response_data), 201

        except SQLAlchemyError as e:
            db.session.rollback()
            print(f"DB Error processing POST alt transaction for account {account_id}: {e}")
            return error_response(f'{transaction_type.capitalize()} failed due to DB error', 500)
        except Exception as e:
            db.session.rollback()
            print(f"Error processing POST alt transaction for account {account_id}: {e}")
            return error_response(f'{transaction_type.capitalize()} failed due to internal error', 500)

    # Should not reach here if method is GET or POST handled above
    return error_response("Method not allowed for this resource", 405)
# --- END OF FILE app/routes/transactions.py ---