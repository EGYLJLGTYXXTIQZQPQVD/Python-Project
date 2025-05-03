# --- START OF FILE app/models/user.py ---

from app import db, bcrypt
from datetime import datetime, timezone # Use timezone-aware datetime

class User(db.Model):
    __tablename__ = 'user' # Optional but good practice

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(128), nullable=False) # Increased length for future hash algorithms
    first_name = db.Column(db.String(50), nullable=True)
    last_name = db.Column(db.String(50), nullable=True)
    # Use timezone-aware UTC time
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    role = db.Column(db.String(50), nullable=False, default='user', index=True) # Roles: 'user', 'admin'
    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True) # For soft delete/activation

    # Relationship to Accounts
    # cascade="all, delete-orphan": If user is deleted, their accounts are also deleted.
    # Alternatively, use passive_deletes=True and handle deletion constraints at the DB level,
    # or prevent user deletion if accounts exist.
    accounts = db.relationship('Account', back_populates='owner', lazy='dynamic', cascade="all, delete-orphan")

    def __init__(self, username, email, password, first_name=None, last_name=None, role='user', is_active=True):
        self.username = username.strip().lower() # Store username consistently lowercase
        self.email = email.strip().lower() # Store email consistently lowercase
        self.set_password(password) # Hash password on creation
        self.first_name = first_name.strip() if first_name else None
        self.last_name = last_name.strip() if last_name else None
        self.role = role
        self.is_active = is_active

    def set_password(self, password):
        """Hashes and sets the user's password."""
        if not password:
             raise ValueError("Password cannot be empty")
        self.password_hash = bcrypt.generate_password_hash(password).decode('utf-8')

    def check_password(self, password):
        """Checks if the provided plaintext password matches the stored hash."""
        if not self.password_hash or not password:
             return False
        return bcrypt.check_password_hash(self.password_hash, password)

    @staticmethod
    def hash_password(password):
        """Static method to hash a password (useful for seeding/testing)."""
        if not password:
            raise ValueError("Password cannot be empty")
        return bcrypt.generate_password_hash(password).decode('utf-8')

    def to_dict(self):
        """Returns user data as a dictionary, excluding sensitive information."""
        return {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'first_name': self.first_name,
            'last_name': self.last_name,
            # Format datetime with timezone info (ISO 8601)
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'role': self.role,
            'is_active': self.is_active
        }

    def __repr__(self):
        return f'<User id={self.id} username={self.username} role={self.role} active={self.is_active}>'
# --- END OF FILE app/models/user.py ---