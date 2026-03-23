from datetime import timedelta

import pytest

from app.core.config import settings
from app.core.security import (
    create_access_token,
    decode_access_token,
    get_password_hash,
    verify_password,
)
from app.models.user import User, UserCreate, UserOut


def test_password_hash_round_trip():
    password = "super-secret-password"

    hashed_password = get_password_hash(password)

    assert hashed_password != password
    assert verify_password(password, hashed_password) is True
    assert verify_password("wrong-password", hashed_password) is False


def test_create_and_decode_access_token():
    token = create_access_token({"sub": "user-123", "user_id": "user-123"})

    payload = decode_access_token(token)

    assert payload["sub"] == "user-123"
    assert payload["user_id"] == "user-123"
    assert "exp" in payload


def test_decode_access_token_rejects_missing_subject():
    token = create_access_token({"scope": "read"})

    with pytest.raises(ValueError, match="missing sub or user_id"):
        decode_access_token(token)


def test_decode_access_token_rejects_expired_token():
    token = create_access_token({"sub": "user-123"}, expires_delta=timedelta(minutes=-1))

    with pytest.raises(ValueError, match="Invalid or expired"):
        decode_access_token(token)


def test_user_schemas_hide_hashed_password():
    user_in = UserCreate(email="user@example.com", password="plain-text", role="admin")
    db_user = User(
        email=user_in.email,
        hashed_password=get_password_hash(user_in.password),
        role=user_in.role,
    )

    response_model = UserOut.model_validate(db_user)

    assert response_model.email == "user@example.com"
    assert response_model.role == "admin"
    assert "hashed_password" not in response_model.model_dump()
