from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.config import get_settings
from app.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    hash_refresh_token,
    new_refresh_token,
    verify_password,
)


def test_password_hash_roundtrip():
    h = hash_password("correct-horse-battery")
    assert h != "correct-horse-battery"
    assert verify_password("correct-horse-battery", h)
    assert not verify_password("wrong-password-here", h)
    assert not verify_password("anything", "not-a-valid-hash")


def test_access_token_roundtrip():
    payload = decode_access_token(create_access_token("user-1", "CUSTOMER"))
    assert payload["sub"] == "user-1"
    assert payload["role"] == "CUSTOMER"


def test_expired_and_tampered_tokens_rejected():
    secret = get_settings().jwt_secret
    past = datetime.now(UTC) - timedelta(minutes=5)
    expired = jwt.encode({"sub": "u", "type": "access", "exp": past}, secret, algorithm="HS256")
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_access_token(expired)
    forged = jwt.encode(
        {"sub": "u", "type": "access", "exp": datetime.now(UTC) + timedelta(hours=1)},
        "another-secret-another-secret-123456",
        algorithm="HS256",
    )
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(forged)


def test_refresh_token_is_random_and_hashed():
    a, b = new_refresh_token(), new_refresh_token()
    assert a != b
    assert hash_refresh_token(a) != a
    assert hash_refresh_token(a) == hash_refresh_token(a)
