from app import db
from datetime import datetime
from sqlalchemy import event
from decimal import Decimal # Use Decimal for amounts

class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    transaction_type = db.Column(db.String(20), nullable=False, index=True)  # deposit, withdrawal, transfer
    amount = db.Column(db.Numeric(10, 2), nullable=False) # Use Numeric for currency amounts
    # Define Foreign Keys referencing account.id. Handle deletion appropriately.
    # If an account is deleted, maybe nullify the FK here instead of deleting the transaction?
    # `ondelete='SET NULL'` would require the columns to be nullable.
    # Current setup (Account using cascade delete) will delete transactions if account is deleted.
    from_account_id = db.Column(db.Integer, db.ForeignKey('account.id'), nullable=True, index=True)
    to_account_id = db.Column(db.Integer, db.ForeignKey('account.id'), nullable=True, index=True)
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True) # Index timestamp
    description = db.Column(db.String(200), nullable=True)

    # Add relationships back to Account model for easier access if needed (optional, already defined in Account)
    # from_account = db.relationship('Account', foreign_keys=[from_account_id], backref='sent_transactions')
    # to_account = db.relationship('Account', foreign_keys=[to_account_id], backref='received_transactions')


    def to_dict(self):
        """Returns transaction data as a dictionary."""
        return {
            'id': self.id,
            'transaction_type': self.transaction_type,
            # Convert Numeric amount to float for JSON serialization
            'amount': float(self.amount) if self.amount is not None else 0.0,
            'from_account_id': self.from_account_id,
            'to_account_id': self.to_account_id,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'description': self.description
        }

    def __repr__(self):
        return f'<Transaction {self.id} ({self.transaction_type} {self.amount})>'

# Ensure amount is positive using SQLAlchemy events or validation logic in routes
@event.listens_for(Transaction.amount, 'set', retval=True)
def validate_amount(target, value, oldvalue, initiator):
    if value is not None and value <= Decimal('0.00'):
        # This validation might be better placed in the route logic before creating the object
        # raise ValueError("Transaction amount must be positive.")
        pass # Allow zero/negative internally if needed, but enforce in routes
    return value