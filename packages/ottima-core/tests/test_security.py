import time

import jwt
import pytest
from cryptography.fernet import Fernet, InvalidToken
from ottima_core.security import (
    create_access_token,
    decode_access_token,
    decrypt_secret,
    encrypt_secret,
    hash_password,
    verify_password,
)


def test_hash_argon2id_e_verificacao():
    h = hash_password("senha-forte-123")
    assert h.startswith("$argon2id$")
    assert verify_password("senha-forte-123", h) is True
    assert verify_password("senha-errada", h) is False


def test_jwt_roundtrip_claims():
    tok = create_access_token(user_id=7, username="lfr", role="admin", secret="s3", ttl_hours=1)
    payload = decode_access_token(tok, secret="s3")
    assert payload["sub"] == "7"
    assert payload["username"] == "lfr"
    assert payload["role"] == "admin"
    assert payload["exp"] > payload["iat"]


def test_jwt_segredo_errado_rejeitado():
    tok = create_access_token(user_id=1, username="a", role="operator", secret="s1", ttl_hours=1)
    with pytest.raises(jwt.PyJWTError):
        decode_access_token(tok, secret="outro")


def test_jwt_expirado_rejeitado():
    tok = create_access_token(user_id=1, username="a", role="operator", secret="s1", ttl_hours=0)
    time.sleep(1.1)
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_access_token(tok, secret="s1")


def test_fernet_roundtrip_e_chave_errada():
    k1 = Fernet.generate_key().decode()
    k2 = Fernet.generate_key().decode()
    enc = encrypt_secret("senha-opc", key=k1)
    assert enc != "senha-opc"
    assert decrypt_secret(enc, key=k1) == "senha-opc"
    with pytest.raises(InvalidToken):
        decrypt_secret(enc, key=k2)
