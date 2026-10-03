import hashlib
import secrets
import os
from datetime import datetime, timedelta
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from app.database import get_db, User, AuditLog
import json
import base64

# Tokens expire on restart because they are stored in memory.
active_tokens = {}  # token -> {"username": ..., "role": ..., "expires": ...}
TOKEN_EXPIRY_HOURS = 24
SECRET_KEY = os.getenv("SECRET_KEY", "ai-assistant-secret-key-2024")

security = HTTPBearer(auto_error=False)

def hash_password(password: str) -> str:
    """Hash a password with SHA-256 using SECRET_KEY as the salt."""
    salt = SECRET_KEY
    return hashlib.sha256(f"{salt}{password}".encode()).hexdigest()

def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against its hash."""
    return hash_password(password) == password_hash

def create_token(username: str, role: str) -> str:
    """Create an authentication token and store its expiry in memory."""
    token = secrets.token_urlsafe(32)
    active_tokens[token] = {
        "username": username,
        "role": role,
        "expires": datetime.utcnow() + timedelta(hours=TOKEN_EXPIRY_HOURS)
    }
    return token

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Get the current authenticated user from the token."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated. Please login first."
        )
    
    token = credentials.credentials
    token_data = active_tokens.get(token)
    
    if not token_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token. Please login again."
        )
    
    if datetime.utcnow() > token_data["expires"]:
        del active_tokens[token]
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired. Please login again."
        )
    
    return token_data

def require_admin(user: dict = Depends(get_current_user)):
    """Require admin role for the endpoint."""
    if user["role"] != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required. You don't have permission."
        )
    return user

def log_action(db: Session, username: str, action: str, details: str, ip_address: str = "local"):
    """Record an action in the audit log."""
    log_entry = AuditLog(
        username=username,
        action=action,
        details=details,
        ip_address=ip_address
    )
    db.add(log_entry)
    db.commit()
