from app import db
from datetime import datetime
from sqlalchemy import event

class Account(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    # Added index for faster lookups by account_number
    account_number = db.Column(db.String(20), unique=True, nullable=False, index=True)
    account_type = db.Column(db.String(20), nullable=False)  # e.g., savings, checking
    account_name = db.Column(db.String(100), nullable=True)  # Optional user-defined name
    description = db.Column(db.String(200), nullable=True)  # Optional description
    balance = db.Column(db.Numeric(10, 2), nullable=False, default=0.00) # Use Numeric for currency
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True) # Added index, ondelete
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, nullable=False, default=True)  # For soft delete

    # Relationships for transactions involving this account
    # Use primaryjoin for clarity when multiple FKs exist to the same table
    transactions_from = db.relationship('Transaction',
                                      primaryjoin='Account.id==Transaction.from_account_id',
                                      backref='from_account_ref', # Changed backref name slightly to avoid potential clash
                                      lazy='dynamic', # Use dynamic loading if expecting many transactions
                                      cascade="all, delete-orphan") # If account deleted, delete its outgoing transactions

    transactions_to = db.relationship('Transaction',
                                    primaryjoin='Account.id==Transaction.to_account_id',
                                    backref='to_account_ref', # Changed backref name slightly
                                    lazy='dynamic',
                                    cascade="all, delete-orphan") # If account deleted, delete its incoming transactions


    def to_dict(self):
        """Returns account data as a dictionary."""
        return {
            'id': self.id,
            'account_number': self.account_number,
            'account_type': self.account_type,
            'account_name': self.account_name,
            'description': self.description,
            # Convert Numeric balance to float for JSON serialization
            'balance': float(self.balance) if self.balance is not None else 0.0,
            'user_id': self.user_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'is_active': self.is_active
        }

    def __repr__(self):
        return f'<Account {self.account_number} ({self.account_type})>'

# Optional: Use SQLAlchemy events to enforce balance constraints if needed
# Example: Prevent balance from going below a certain threshold
# @event.listens_for(Account.balance, 'set', retval=True)
# def validate_balance(target, value, oldvalue, initiator):
#     if value is not None and value < -1000.00: # Example minimum balance
#         raise ValueError("Account balance cannot go below -1000.00")
#     return values