"""
auth.py  —  Authentication for the SaaS platform.

Provides:
  - POST /api/auth/signup
  - POST /api/auth/login
  - get_current_user(token) dependency for protected endpoints

Passwords are bcrypt-hashed. Tokens are JWT (HS256, 7-day expiry).
The secret key comes from JWT_SECRET in your .env file.
"""

import os
import bcrypt
import jwt
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel, EmailStr
from database import get_db, init_db, log_activity

router = APIRouter(prefix="/api/auth", tags=["auth"])

JWT_SECRET  = os.getenv("JWT_SECRET", "change-this-to-a-long-random-string-in-prod")
JWT_ALGO    = "HS256"
TOKEN_DAYS  = 7


# ── Pydantic models ──────────────────────────────────────────────

class SignupRequest(BaseModel):
    email: str
    password: str
    full_name: str

class LoginRequest(BaseModel):
    email: str
    password: str

class AuthResponse(BaseModel):
    token: str
    user_id: int
    email: str
    full_name: str


# ── Helpers ──────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


def create_token(user_id: int, email: str) -> str:
    payload = {
        "user_id": user_id,
        "email":   email,
        "exp":     datetime.now(timezone.utc) + timedelta(days=TOKEN_DAYS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired. Please log in again.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token.")


# ── Dependency: get logged-in user from Authorization header ─────

def get_current_user(authorization: str = Header(...)) -> dict:
    """
    Use as a FastAPI dependency on any protected endpoint:
        @app.get("/api/something")
        def my_endpoint(user = Depends(get_current_user)):
            user_id = user["user_id"]
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token.")
    token = authorization.split(" ", 1)[1]
    payload = decode_token(token)

    with get_db() as conn:
        row = conn.execute(
            "SELECT id, email, full_name, is_active FROM users WHERE id=?",
            (payload["user_id"],)
        ).fetchone()

    if not row:
        raise HTTPException(status_code=401, detail="User not found.")
    if not row["is_active"]:
        raise HTTPException(status_code=403, detail="Account is disabled.")

    return {"user_id": row["id"], "email": row["email"], "full_name": row["full_name"]}


# ── Routes ────────────────────────────────────────────────────────

@router.post("/signup", response_model=AuthResponse)
def signup(req: SignupRequest):
    """Register a new candidate account."""
    with get_db() as conn:
        existing = conn.execute(
            "SELECT id FROM users WHERE email=?", (req.email.lower().strip(),)
        ).fetchone()
        if existing:
            raise HTTPException(status_code=400, detail="Email already registered.")

        password_hash = hash_password(req.password)
        cursor = conn.execute(
            "INSERT INTO users (email, password_hash, full_name) VALUES (?,?,?)",
            (req.email.lower().strip(), password_hash, req.full_name.strip())
        )
        user_id = cursor.fetchone()[0] # 🌟 THE NEW POSTGRES WAY!

        # Create an empty candidate profile row for this user
        conn.execute(
            "INSERT INTO candidate_profiles (user_id) VALUES (?)", (user_id,)
        )

    log_activity(user_id, "signup", f"Account created for {req.email}")
    token = create_token(user_id, req.email)
    return AuthResponse(token=token, user_id=user_id,
                        email=req.email, full_name=req.full_name)


@router.post("/login", response_model=AuthResponse)
def login(req: LoginRequest):
    """Log in and receive a JWT token."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT id, email, full_name, password_hash, is_active FROM users WHERE email=?",
            (req.email.lower().strip(),)
        ).fetchone()

    if not row or not verify_password(req.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    if not row["is_active"]:
        raise HTTPException(status_code=403, detail="Account is disabled.")

    token = create_token(row["id"], row["email"])
    return AuthResponse(token=token, user_id=row["id"],
                        email=row["email"], full_name=row["full_name"])