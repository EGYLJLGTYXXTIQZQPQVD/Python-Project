from app import db, bcrypt
from datetime import datetime

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True) # Added index
    email = db.Column(db.String(120), unique=True, nullable=False, index=True) # Added index
    password_hash = db.Column(db.String(128), nullable=False)
    first_name = db.Column(db.String(50), nullable=True)
    last_name = db.Column(db.String(50), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    role = db.Column(db.String(50), nullable=False, default='user') # Roles: 'user', 'admin'
    is_active = db.Column(db.Boolean, nullable=False, default=True) # Added for soft delete capability

    # Relationship: Use cascade options carefully, especially for delete
    # 'delete-orphan' ensures accounts are deleted if the user is deleted.
    # Alternatively, prevent user deletion if they have accounts, or just nullify user_id.
    accounts = db.relationship('Account', backref='owner', lazy=True, cascade="all, delete-orphan")

    def __init__(self, username, email, password, first_name=None, last_name=None):
        self.username = username.lower() # Store username lowercase for consistency
        self.email = email.lower() # Store email lowercase
        self.password_hash = bcrypt.generate_password_hash(password).decode('utf-8')
        self.first_name = first_name
        self.last_name = last_name
        self.role = 'user' # Default role
        self.is_active = True

    def set_password(self, password):
         """Sets the password hash."""
         self.password_hash = bcrypt.generate_password_hash(password).decode('utf-8')

    def check_password(self, password):
        """Checks if the provided password matches the stored hash."""
        return bcrypt.check_password_hash(self.password_hash, password)

    @staticmethod
    def generate_password_hash(password):
        """Static method to hash password (used in change password endpoint)."""
        return bcrypt.generate_password_hash(password).decode('utf-8')

    def to_dict(self):
        """Returns user data as a dictionary, excluding sensitive info."""
        return {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'first_name': self.first_name,
            'last_name': self.last_name,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'role': self.role,
            'is_active': self.is_active # Include active status
        }

    def __repr__(self):
        return f'<User {self.username}>'