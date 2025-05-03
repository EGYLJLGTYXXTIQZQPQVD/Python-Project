# --- START OF FILE app/models/account.py ---

from app import db
from datetime import datetime, timezone
from decimal import Decimal # Use Decimal for precise currency representation

class Account(db.Model):
    __tablename__ = 'account'

    id = db.Column(db.Integer, primary_key=True)
    # Use index for faster lookups by account_number
    account_number = db.Column(db.String(30), unique=True, nullable=False, index=True) # Increased length slightly
    account_type = db.Column(db.String(50), nullable=False, default='checking')  # e.g., savings, checking
    account_name = db.Column(db.String(100), nullable=True)  # Optional user-defined name/label
    description = db.Column(db.String(255), nullable=True)  # Optional description
    # Use Numeric for currency (precision=12, scale=2 means up to 10 digits before decimal, 2 after)
    balance = db.Column(db.Numeric(12, 2), nullable=False, default=Decimal('0.00'))
    # Foreign key to User. Set ondelete='CASCADE' if accounts should be deleted when user is deleted.
    # If you want to prevent user deletion if they have accounts, remove ondelete or use 'RESTRICT'.
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    # Use timezone-aware UTC time
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)  # For soft delete/activation

    # Relationship back to the User
    owner = db.relationship('User', back_populates='accounts')

    # Relationships for transactions involving this account
    # Use primaryjoin for clarity when multiple FKs exist to the same table (Transaction)
    # cascade: If an account is deleted, delete its related transactions.
    transactions_from = db.relationship('Transaction',
                                      foreign_keys='Transaction.from_account_id',
                                      back_populates='from_account',
                                      lazy='dynamic', # Use dynamic loading if expecting many transactions
                                      cascade="all, delete-orphan")

    transactions_to = db.relationship('Transaction',
                                    foreign_keys='Transaction.to_account_id',
                                    back_populates='to_account',
                                    lazy='dynamic',
                                    cascade="all, delete-orphan")

    def to_dict(self):
        """Returns account data as a dictionary suitable for JSON serialization."""
        return {
            'id': self.id,
            'account_number': self.account_number,
            'account_type': self.account_type,
            'account_name': self.account_name,
            'description': self.description,
            # Convert Numeric balance to float for JSON (or string for absolute precision)
            'balance': float(self.balance) if self.balance is not None else 0.0,
            'user_id': self.user_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'is_active': self.is_active
            # Optionally include owner info, but avoid circular references if nesting deeply
            # 'owner_username': self.owner.username if self.owner else None
        }

    def __repr__(self):
        active_status = "active" if self.is_active else "inactive"
        return f'<Account id={self.id} number={self.account_number} type={self.account_type} balance={self.balance} status={active_status}>'

# Optional: Use SQLAlchemy events for complex validation or side effects,
# but simple checks are often better handled in routes or service layers.
# from sqlalchemy import event
# @event.listens_for(Account.balance, 'set', retval=True)
# def validate_balance_on_set(target, value, oldvalue, initiator):
#     if value is not None and value < Decimal('-1000.00'): # Example minimum balance check
#         # Raising ValueError here might be caught by SQLAlchemy and cause issues.
#         # It's often better to validate *before* setting.
#         print(f"Warning: Account {target.id} balance attempted to be set below minimum.")
#         # Or potentially clamp the value: return max(value, Decimal('-1000.00'))
#     return value # Must return the value to be set
# --- END OF FILE app/models/account.py ---