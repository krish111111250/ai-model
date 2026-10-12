"""
Cloud dashboard API: accounts.

The engine's /v1/ask-stateless is authenticated by API key and knows nothing
about people. These routes are the other half: who owns those keys, and who
may manage them.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .accounts import (
    authenticate,
    create_access_token,
    create_user,
    get_current_user,
    public_user,
)
from .rate_limit import limiter

router = APIRouter(prefix="/v1/auth", tags=["accounts"])


class SignupRequest(BaseModel):
    email: str = Field(..., description="Work email")
    password: str = Field(..., min_length=8, description="At least 8 characters")


class LoginRequest(BaseModel):
    email: str
    password: str


@router.post("/signup", status_code=201)
@limiter.limit("10/hour")
async def signup(request: Request, body: SignupRequest):
    """Create an account and sign straight in."""
    user = create_user(body.email, body.password)

    return {**create_access_token(user), "user": public_user(user)}


@router.post("/login")
@limiter.limit("20/minute")
async def login(request: Request, body: LoginRequest):
    """
    Exchange a password for a session token.

    The failure message never distinguishes a wrong password from an unknown
    address - that difference is a list of who has an account here.
    """
    user = authenticate(body.email, body.password)

    if not user:
        raise HTTPException(status_code=401, detail="Incorrect email or password.")

    return {**create_access_token(user), "user": public_user(user)}


@router.get("/me")
@limiter.limit("120/minute")
async def me(request: Request, user: dict = Depends(get_current_user)):
    return public_user(user)
