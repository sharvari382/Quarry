import time

import jwt
import pytest

from app.config import get_settings
from app.security import crypto
from app.security.passwords import hash_password, password_problems, verify_password
from app.security.tokens import TokenError, create_access_token, decode_access_token, hash_token
from app.services.export import rows_to_csv, safe_cell
from app.services.kv import MemoryKV


def test_argon2_hash_and_verify():
    h = hash_password("Correct-horse-42")
    assert h.startswith("$argon2id$")
    assert verify_password(h, "Correct-horse-42")
    assert not verify_password(h, "wrong")
    assert not verify_password("not-a-hash", "x")


@pytest.mark.parametrize("pw,problem", [
    ("short1", "at least 10"),
    ("onlyletterslong", "letter and one number"),
    ("password1", "too common"),
    ("alicesmith123", "email name"),
])
def test_password_policy(pw, problem):
    assert any(problem in p for p in password_problems(pw, "alicesmith@example.com"))


def test_password_policy_accepts_good_password():
    assert password_problems("Tangerine-river-88", "bob@example.com") == []


def test_access_token_roundtrip_and_tamper():
    tok = create_access_token("user-1")
    assert decode_access_token(tok) == "user-1"
    with pytest.raises(TokenError):
        decode_access_token(tok[:-2] + ("A" if tok[-2] != "A" else "B") + tok[-1])


def test_alg_none_and_wrong_type_rejected():
    forged = jwt.encode({"sub": "admin", "exp": time.time() + 60, "type": "access"}, key="", algorithm="none")
    with pytest.raises(TokenError):
        decode_access_token(forged)
    refresh_like = jwt.encode({"sub": "u", "exp": time.time() + 60, "type": "refresh"},
                              get_settings().jwt_secret, algorithm="HS256")
    with pytest.raises(TokenError):
        decode_access_token(refresh_like)


def test_expired_token_rejected():
    expired = jwt.encode({"sub": "u", "exp": time.time() - 1, "type": "access"},
                         get_settings().jwt_secret, algorithm="HS256")
    with pytest.raises(TokenError):
        decode_access_token(expired)


def test_refresh_token_only_hash_stored():
    assert len(hash_token("abc")) == 64 and hash_token("abc") != "abc"


def test_encryption_roundtrip_and_integrity():
    blob = crypto.encrypt(b"secret,data\n1,2\n")
    assert b"secret" not in blob
    assert crypto.decrypt(blob) == b"secret,data\n1,2\n"
    tampered = blob[:-5] + b"AAAAA"
    with pytest.raises(crypto.DecryptionError):
        crypto.decrypt(tampered)


def test_key_rotation(monkeypatch):
    old = crypto.encrypt(b"payload")
    new_key = crypto.generate_key()
    s = get_settings()
    monkeypatch.setattr(s, "data_encryption_keys", f"{new_key},{s.data_encryption_keys}")
    crypto._cipher.cache_clear()
    try:
        assert crypto.decrypt(old) == b"payload"  # old data still readable
        rotated = crypto.rotate(old)
        monkeypatch.setattr(s, "data_encryption_keys", new_key)
        crypto._cipher.cache_clear()
        assert crypto.decrypt(rotated) == b"payload"  # readable with only the new key
    finally:
        crypto._cipher.cache_clear()


def test_csv_formula_injection_escaped():
    assert safe_cell("=HYPERLINK(\"http://evil\")").startswith("'=")
    assert safe_cell("-42") == "-42"  # real numbers untouched
    assert "'@SUM" in rows_to_csv(["a"], [["@SUM(A1)"]])


def test_memory_kv_window():
    kv = MemoryKV()
    assert [kv.incr("k", 60) for _ in range(3)] == [1, 2, 3]
    kv.set("x", b"1", 60)
    assert kv.get("x") == b"1"


def test_production_config_refuses_dev_secrets(monkeypatch):
    s = get_settings().model_copy(update={"app_env": "production"})
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        s.validate_for_production()
