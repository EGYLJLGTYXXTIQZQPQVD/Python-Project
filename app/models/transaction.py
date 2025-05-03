from app import db
from datetime import datetime, timezone
from decimal import Decimal # Use Decimal for precise currency amounts
from sqlalchemy import event, CheckConstraint

class Transaction(db.Model):
    __tablename__ = 'transaction'

    id = db.Column(db.Integer, primary_key=True)
    # Index transaction type for faster filtering
    transaction_type = db.Column(db.String(20), nullable=False, index=True)  # e.g., deposit, withdrawal, transfer
    # Use Numeric for currency amounts
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    # Foreign Keys referencing account.id.
    # Made nullable=True because a deposit only has to_account, withdrawal only has from_account.
    # ondelete='SET NULL': If an account is deleted, set the corresponding FK here to NULL.
    # Requires the column to be nullable. Keeps transaction history even if account is gone.
    # Alternative: If Account uses cascade delete, transactions will be deleted. Choose based on requirements.
    from_account_id = db.Column(db.Integer, db.ForeignKey('account.id', ondelete='SET NULL'), nullable=True, index=True)
    to_account_id = db.Column(db.Integer, db.ForeignKey('account.id', ondelete='SET NULL'), nullable=True, index=True)
    # Use timezone-aware UTC time, index for sorting/filtering by date
    timestamp = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
    description = db.Column(db.String(255), nullable=True) # Optional description provided by user or system

    # Relationships back to Account model for easier access (optional, but can be convenient)
    # Ensure foreign_keys is specified when there are multiple FKs to the same table.
    from_account = db.relationship('Account', foreign_keys=[from_account_id], back_populates='transactions_from')
    to_account = db.relationship('Account', foreign_keys=[to_account_id], back_populates='transactions_to')

    # Add constraints at the database level if possible/desired
    __table_args__ = (
        # Ensure amount is always positive
        CheckConstraint('amount > 0', name='ck_transaction_amount_positive'),
        # Ensure at least one account ID is set
        CheckConstraint('from_account_id IS NOT NULL OR to_account_id IS NOT NULL', name='ck_transaction_has_account'),
        # Ensure transfer has both accounts, deposit only 'to', withdrawal only 'from' (more complex logic, maybe better in app)
        # CheckConstraint(
        #     "(transaction_type = 'transfer' AND from_account_id IS NOT NULL AND to_account_id IS NOT NULL) OR "
        #     "(transaction_type = 'deposit' AND from_account_id IS NULL AND to_account_id IS NOT NULL) OR "
        #     "(transaction_type = 'withdrawal' AND from_account_id IS NOT NULL AND to_account_id IS NULL)",
        #     name='ck_transaction_accounts_match_type'
        # ),
    )


    def to_dict(self):
        """Returns transaction data as a dictionary suitable for JSON serialization."""
        return {
            'id': self.id,
            'transaction_type': self.transaction_type,
            # Convert Numeric amount to float for JSON (or string)
            'amount': float(self.amount) if self.amount is not None else 0.0,
            'from_account_id': self.from_account_id,
            # Optionally include account numbers if accounts exist
            'from_account_number': self.from_account.account_number if self.from_account else None,
            'to_account_id': self.to_account_id,
            'to_account_number': self.to_account.account_number if self.to_account else None,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'description': self.description
        }

    def __repr__(self):
        return f'<Transaction id={self.id} type={self.transaction_type} amount={self.amount} from={self.from_account_id} to={self.to_account_id}>'

# Optional: Event listener to validate amount before insertion/update at the ORM level.
# However, route-level validation provides better user feedback earlier.
# Database constraints (CheckConstraint) are generally more reliable.
# @event.listens_for(Transaction, 'before_insert')
# @event.listens_for(Transaction, 'before_update')
# def validate_transaction_data(mapper, connection, target):
#     if target.amount is not None and target.amount <= Decimal('0.00'):
#         raise ValueError("Transaction amount must be positive.")
#     # Add more complex validation if needed (e.g., account matching type)
#     if target.transaction_type == 'deposit' and target.from_account_id is not None:
#          raise ValueError("Deposit transaction cannot have a 'from_account_id'.")
#     # ... etc.
# --- END OF FILE app/models/transaction.py ---