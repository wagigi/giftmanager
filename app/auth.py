"""Password hashing and the access-control decorators."""
from functools import wraps
from flask import session, flash, redirect, url_for, g
from flask_babel import _
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from storage import load_users


ph = PasswordHasher()


# Define a decorator for requiring authentication
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            flash(_('Please log in first.'), 'warning')
            return redirect(url_for('login'))

        # A session can outlive its account (user deleted by an admin): log it out
        user = next((u for u in load_users() if u['username'] == session['username']), None)
        if not user:
            session.clear()
            flash(_('Please log in first.'), 'login_warning')  # shown on the login page
            return redirect(url_for('login'))

        # Check if user is a guest and route doesn't allow guests
        if user.get('guest', False):
            # Check if the route has @guest_allowed decorator
            if not getattr(f, '_guest_allowed', False):
                flash(_('This feature is not available for guest users.'), 'danger')
                return redirect(url_for('dashboard'))

        # Templates use it (as is_guest) to hide links to pages refused to guests
        g.is_guest = user.get('guest', False)
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Check if the user is logged in
        if 'username' not in session:
            flash(_('Please log in first.'), 'warning')
            return redirect(url_for('login'))

        # Load users from the JSON file
        users = load_users()

        # Find the user based on the username stored in the session
        user = next((u for u in users if u['username'] == session['username']), None)

        # A session can outlive its account (user deleted by an admin): log it out
        if not user:
            session.clear()
            flash(_('Please log in first.'), 'login_warning')  # shown on the login page
            return redirect(url_for('login'))

        # Check if the user is an admin
        if not user.get('admin'):
            flash(_('Admin access required.'), 'danger')
            return redirect(url_for('dashboard'))

        # Continue to the original function if the user is an admin
        return f(*args, **kwargs)
    
    return decorated_function

def is_guest_user(username):
    """Check if a user is a guest"""
    users = load_users()
    user = next((u for u in users if u['username'] == username), None)
    return user and user.get('guest', False)

def guest_allowed(f):
    """Decorator to allow guest users access to specific routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            flash(_('Please log in first.'), 'warning')
            return redirect(url_for('login'))
        
        # Check if user is a guest
        if is_guest_user(session['username']):
            return f(*args, **kwargs)
        else:
            # Regular users can always access guest-allowed routes
            return f(*args, **kwargs)
    
    # Mark this function as guest allowed
    decorated_function._guest_allowed = True
    return decorated_function


# Hash the password using Argon2
def password_hash(password):
    return ph.hash(password)

# Verify the hashed password
def verify_password(hash, password):
    try:
        return ph.verify(hash, password)
    except VerifyMismatchError:
        return False
