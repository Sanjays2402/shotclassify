"""Code suspected-secret literal sniffing tests.

A new CodeFields.suspected_secrets slot captures string literals
that LOOK like API keys / credentials / OAuth secrets / private
keys / connection strings even when not caught by the typed
redact modes.

Each entry: {"kind": str, "hint": str} dict where hint is a
REDACTED preview (first 4 + ... + last 4 chars). The full secret
is NEVER stored.
"""
from __future__ import annotations

from shotclassify_common import CodeFields, OCRResult
from shotclassify_extract import enrich_code, extract_suspected_secrets

# ---- Private-key blocks ------------------------------------------


def test_rsa_private_key_block():
    code = "-----BEGIN RSA PRIVATE KEY-----\nMIIEpQIBAAKCAQEA...\n-----END RSA PRIVATE KEY-----"
    out = extract_suspected_secrets(code)
    kinds = [e["kind"] for e in out]
    assert "private_key" in kinds


def test_openssh_private_key():
    code = "-----BEGIN OPENSSH PRIVATE KEY-----"
    out = extract_suspected_secrets(code)
    assert any(e["kind"] == "private_key" for e in out)


def test_pgp_private_key():
    code = "-----BEGIN PGP PRIVATE KEY-----"
    out = extract_suspected_secrets(code)
    assert any(e["kind"] == "private_key" for e in out)


def test_bare_private_key():
    code = "-----BEGIN PRIVATE KEY-----"
    out = extract_suspected_secrets(code)
    assert any(e["kind"] == "private_key" for e in out)


def test_ec_private_key():
    code = "-----BEGIN EC PRIVATE KEY-----"
    out = extract_suspected_secrets(code)
    assert any(e["kind"] == "private_key" for e in out)


# ---- Authorization Bearer tokens ---------------------------------


def test_bearer_token_in_header():
    code = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.foo.bar"
    out = extract_suspected_secrets(code)
    assert any(e["kind"] == "bearer_token" for e in out)


def test_bearer_token_with_hex():
    code = "Authorization: Bearer abc123def456abc123def456"
    out = extract_suspected_secrets(code)
    assert any(e["kind"] == "bearer_token" for e in out)


def test_bearer_token_too_short_rejected():
    code = "Authorization: Bearer short"
    out = extract_suspected_secrets(code)
    # Too short to qualify as a real token.
    assert not any(e["kind"] == "bearer_token" for e in out)


# ---- Basic auth --------------------------------------------------


def test_basic_auth_header():
    code = "Authorization: Basic dXNlcjpwYXNzd29yZA=="
    out = extract_suspected_secrets(code)
    assert any(e["kind"] == "basic_auth" for e in out)


# ---- Connection strings ------------------------------------------


def test_postgres_connection_string():
    code = "DATABASE_URL=postgres://admin:secret123@localhost:5432/mydb"
    out = extract_suspected_secrets(code)
    assert any(e["kind"] == "connection_string" for e in out)


def test_mysql_connection_string():
    code = "DB=mysql://root:password123@127.0.0.1:3306/test"
    out = extract_suspected_secrets(code)
    assert any(e["kind"] == "connection_string" for e in out)


def test_mongodb_connection_string():
    code = "MONGO=mongodb://user:longpassword@cluster.example.com/db"
    out = extract_suspected_secrets(code)
    assert any(e["kind"] == "connection_string" for e in out)


def test_mongodb_srv_connection_string():
    code = "uri = mongodb+srv://admin:s3cretP4ss@cluster0.mongodb.net/db"
    out = extract_suspected_secrets(code)
    assert any(e["kind"] == "connection_string" for e in out)


def test_redis_connection_string():
    code = "REDIS=redis://default:supersecret@localhost:6379"
    out = extract_suspected_secrets(code)
    assert any(e["kind"] == "connection_string" for e in out)


def test_connection_string_hint_redacts_password():
    code = "DATABASE_URL=postgres://admin:secret123longer@host/db"
    out = extract_suspected_secrets(code)
    cs_entries = [e for e in out if e["kind"] == "connection_string"]
    assert len(cs_entries) >= 1
    hint = cs_entries[0]["hint"]
    # The full password "secret123longer" should NOT appear verbatim.
    assert "secret123longer" not in hint
    # But the user name should be visible.
    assert "admin" in hint


# ---- API keys ----------------------------------------------------


def test_api_key_uppercase_env():
    code = 'API_KEY="sk-1234567890abcdefghij"'
    out = extract_suspected_secrets(code)
    assert any(e["kind"] == "api_key" for e in out)


def test_api_secret_uppercase_env():
    code = 'API_SECRET=AbCdEfGhIjKlMnOpQr1234'
    out = extract_suspected_secrets(code)
    assert any(e["kind"] == "api_key" for e in out)


def test_lowercase_api_key_json():
    code = '"api_key": "sk-proj-abcdefghijklmnopqrstuvwxyz1234"'
    out = extract_suspected_secrets(code)
    assert any(e["kind"] == "api_key" for e in out)


def test_apikey_yaml_key():
    code = 'apikey: very-long-secret-value-abc-123\n'
    out = extract_suspected_secrets(code)
    assert any(e["kind"] == "api_key" for e in out)


# ---- Passwords ---------------------------------------------------


def test_db_password_uppercase():
    code = 'DB_PASSWORD="MySecretP@ssw0rd2024!"'
    out = extract_suspected_secrets(code)
    assert any(e["kind"] == "db_password" for e in out)


def test_password_uppercase_short_rejected():
    code = 'PASSWORD="hi"'
    out = extract_suspected_secrets(code)
    # Too short and low-entropy to qualify.
    assert not any(e["kind"] == "db_password" for e in out)


def test_database_password_env():
    code = 'DATABASE_PASSWORD=Sup3rS3cr3tDB!@#'
    out = extract_suspected_secrets(code)
    assert any(e["kind"] == "db_password" for e in out)


def test_lowercase_password_yaml():
    code = 'password: MyVerySecretPassword123!'
    out = extract_suspected_secrets(code)
    assert any(e["kind"] == "db_password" for e in out)


# ---- Secret keys -------------------------------------------------


def test_secret_key_uppercase():
    code = 'SECRET_KEY="r4nd0mEntr0pyV4lu3WithSymbols!"'
    out = extract_suspected_secrets(code)
    assert any(e["kind"] == "secret_key" for e in out)


def test_signing_key_uppercase():
    code = 'SIGNING_KEY="AbCdEfGhIj1234567890XyZ!"'
    out = extract_suspected_secrets(code)
    assert any(e["kind"] == "secret_key" for e in out)


def test_encryption_key_uppercase():
    code = 'ENCRYPTION_KEY="HiGhEnTrOpYv4lu3w1thSymbols!"'
    out = extract_suspected_secrets(code)
    assert any(e["kind"] == "secret_key" for e in out)


def test_client_secret_lowercase():
    code = 'client_secret: "sk-proj-abcdefghi1234567890"'
    out = extract_suspected_secrets(code)
    assert any(e["kind"] == "secret_key" for e in out)


def test_app_secret_uppercase():
    code = 'APP_SECRET=HiGhEnTrOpYv4lu3w1thSymbols!'
    out = extract_suspected_secrets(code)
    assert any(e["kind"] == "secret_key" for e in out)


# ---- OAuth tokens ------------------------------------------------


def test_access_token_uppercase():
    code = 'ACCESS_TOKEN="ya29.AbCdEfGhIjKlMnOpQrStUvWxYz1234"'
    out = extract_suspected_secrets(code)
    assert any(e["kind"] == "oauth_token" for e in out)


def test_refresh_token_uppercase():
    code = 'REFRESH_TOKEN="1//04AbCdEfGhIjKlMnOpQrStUvWxYz"'
    out = extract_suspected_secrets(code)
    assert any(e["kind"] == "oauth_token" for e in out)


def test_auth_token_uppercase():
    code = 'AUTH_TOKEN="abc123def456ghi789jkl0mno1pqr2"'
    out = extract_suspected_secrets(code)
    assert any(e["kind"] == "oauth_token" for e in out)


def test_session_token_uppercase():
    code = 'SESSION_TOKEN="sessHiGhEnTrOpY1234567890!"'
    out = extract_suspected_secrets(code)
    assert any(e["kind"] == "oauth_token" for e in out)


def test_lowercase_access_token_json():
    code = '"access_token": "ya29.AbCdEfGh-IjKlMnOp_QrStUvWxYz1234"'
    out = extract_suspected_secrets(code)
    assert any(e["kind"] == "oauth_token" for e in out)


# ---- Hex secrets -------------------------------------------------


def test_hex_secret_in_assignment():
    code = "MY_SECRET=a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4"
    out = extract_suspected_secrets(code)
    assert any(e["kind"] == "hex_secret" for e in out)


def test_long_hex_token_assignment():
    code = "API_TOKEN=deadbeefcafebabe0123456789abcdef"
    out = extract_suspected_secrets(code)
    # Either api_key (matches catalogue) or hex_secret -- both are
    # acceptable; the catalogue match wins because pass 5 runs
    # before pass 7.
    kinds = [e["kind"] for e in out]
    assert "api_key" in kinds or "hex_secret" in kinds


def test_hex_in_commit_id_does_not_fire():
    """SHA / commit hashes shouldn't be flagged as secrets."""
    code = "COMMIT_ID=a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4"
    out = extract_suspected_secrets(code)
    # COMMIT_ID doesn't contain a secret-y keyword.
    assert not any(e["kind"] == "hex_secret" for e in out)


# ---- Hint redaction ----------------------------------------------


def test_hint_redacts_long_value():
    code = 'API_KEY="sk-1234567890abcdefghij"'
    out = extract_suspected_secrets(code)
    api_entries = [e for e in out if e["kind"] == "api_key"]
    assert len(api_entries) >= 1
    hint = api_entries[0]["hint"]
    # Full value should NOT appear in hint.
    assert "1234567890" not in hint
    assert "abcdefghij" not in hint
    # Should be redacted to head + ... + tail.
    assert "..." in hint


def test_hint_format_head_tail():
    code = 'API_KEY="abcdefghijklmnopqrst"'
    out = extract_suspected_secrets(code)
    api_entries = [e for e in out if e["kind"] == "api_key"]
    hint = api_entries[0]["hint"]
    # First 4 + ... + last 4.
    assert hint.startswith("abcd")
    assert hint.endswith("qrst")


def test_short_hint_uses_asterisks():
    # Values <= 8 chars use asterisks (full mask).
    code = 'password: abcdef12'  # 8 chars
    out = extract_suspected_secrets(code)
    pw_entries = [e for e in out if e["kind"] == "db_password"]
    if pw_entries:
        hint = pw_entries[0]["hint"]
        # Either asterisk mask or head/tail format both ok for 8-char.
        # The head/tail kicks in for > 8 chars.
        assert "*" in hint or "..." in hint


# ---- False-positive defences -------------------------------------


def test_log_level_does_not_fire():
    """LOG_LEVEL=INFO is not a secret."""
    code = "LOG_LEVEL=INFO"
    out = extract_suspected_secrets(code)
    assert out == []


def test_debug_flag_does_not_fire():
    code = "DEBUG=true"
    out = extract_suspected_secrets(code)
    assert out == []


def test_api_url_does_not_fire():
    """API_URL is not in the catalogue -- shouldn't fire."""
    code = "API_URL=https://api.example.com/v1"
    out = extract_suspected_secrets(code)
    # The URL itself doesn't satisfy entropy + key match.
    assert not any(e["kind"] == "api_key" for e in out)


def test_api_version_does_not_fire():
    code = "API_VERSION=2024-03-15"
    out = extract_suspected_secrets(code)
    assert out == []


def test_short_assignment_value_rejected():
    """Values < 16 chars on uppercase env vars fail entropy check."""
    code = "API_KEY=short"
    out = extract_suspected_secrets(code)
    assert out == []


def test_low_entropy_long_value_rejected():
    """All-lowercase 16+ char value still fails entropy (1 class) for the
    UPPERCASE assignment matcher. The lowercase keyed assignment matcher
    intentionally accepts named keys without entropy."""
    code = "API_VERSION=abcdefghijklmnopqr"  # all lowercase, generic key
    out = extract_suspected_secrets(code)
    # API_VERSION is not in the catalogue, so no entry.
    assert out == []


# ---- De-duplication ----------------------------------------------


def test_duplicate_secrets_collapse():
    code = """
    API_KEY="sk-1234567890abcdefghij"
    API_KEY="sk-1234567890abcdefghij"
    """
    out = extract_suspected_secrets(code)
    api_entries = [e for e in out if e["kind"] == "api_key"]
    # Same secret printed twice collapses.
    assert len(api_entries) == 1


def test_different_secrets_kept_separate():
    code = """
    API_KEY="sk-1234567890abcdefghij"
    SECRET_KEY="r4nd0mEntr0pyV4lu3WithStuff"
    """
    out = extract_suspected_secrets(code)
    kinds = [e["kind"] for e in out]
    assert "api_key" in kinds
    assert "secret_key" in kinds


# ---- Edge cases --------------------------------------------------


def test_empty_code():
    assert extract_suspected_secrets("") == []


def test_none_input():
    assert extract_suspected_secrets(None) == []  # type: ignore[arg-type]


def test_non_string_input():
    assert extract_suspected_secrets(123) == []  # type: ignore[arg-type]


def test_no_secrets_in_pure_code():
    code = "def add(a, b): return a + b"
    assert extract_suspected_secrets(code) == []


def test_capped_at_20_entries():
    # Generate >20 distinct secrets.
    lines = []
    for i in range(30):
        lines.append(f'API_KEY="sk-unique{i:04d}AbCdEfGhIj{i}"')
    code = "\n".join(lines)
    out = extract_suspected_secrets(code)
    assert len(out) <= 20


# ---- Realistic .env file -----------------------------------------


def test_realistic_env_file():
    code = """# Production environment
DATABASE_URL=postgres://admin:SuperSecret123@db.host/myapp
REDIS_URL=redis://default:redisP@ssw0rd@cache.host:6379
API_KEY="sk-proj-abc123def456ghi789jkl012mno"
SECRET_KEY="r4nd0mSym3tr1cK3yV4lu3"
JWT_SECRET="random32charsHighEntropy12345"
LOG_LEVEL=INFO
DEBUG=false
"""
    out = extract_suspected_secrets(code)
    kinds = {e["kind"] for e in out}
    # Connection strings (postgres + redis), api_key, secret_key.
    assert "connection_string" in kinds
    assert "api_key" in kinds
    # LOG_LEVEL and DEBUG should NOT pollute.
    # JWT_SECRET contains "SECRET" -- catches via catalogue OR
    # lowercase pattern (it's all-caps so won't hit lowercase).
    # Anyway, should not include false positives.
    assert "INFO" not in str(out)
    assert "false" not in str(out)


def test_realistic_config_yaml():
    code = """
database:
  host: localhost
  port: 5432
  username: admin
  password: MyVerySecretPasswordHere2024!
api:
  api_key: sk-proj-realisticAPIkey123456
  api_secret: realisticSecret789012345
oauth:
  access_token: ya29.AccessTokenFromGoogleOAuth
  refresh_token: 1//04RefreshTokenFromGoogleOAuth
"""
    out = extract_suspected_secrets(code)
    kinds = {e["kind"] for e in out}
    assert "db_password" in kinds
    assert "api_key" in kinds
    assert "oauth_token" in kinds


# ---- enrich_code integration -------------------------------------


def test_enrich_code_populates_suspected_secrets():
    """enrich_code surfaces suspected secrets into CodeFields."""
    ocr = OCRResult(
        text='API_KEY="sk-1234567890abcdefghij"'
    )
    code = enrich_code(None, ocr)
    assert len(code.suspected_secrets) >= 1
    assert any(e["kind"] == "api_key" for e in code.suspected_secrets)


def test_enrich_code_no_secrets_empty_list():
    """Pure code with no secrets returns empty suspected_secrets."""
    ocr = OCRResult(text="def add(a, b): return a + b")
    code = enrich_code(None, ocr)
    assert code.suspected_secrets == []


def test_enrich_code_preserves_caller_secrets():
    """Caller-supplied suspected_secrets are preserved."""
    existing = CodeFields(
        suspected_secrets=[{"kind": "private_key", "hint": "manually added"}],
        code="API_KEY=very-secret-value-12345abc",
    )
    ocr = OCRResult(text="API_KEY=very-secret-value-12345abc")
    code = enrich_code(existing, ocr)
    # Caller's value is preserved verbatim.
    assert any(e["hint"] == "manually added" for e in code.suspected_secrets)


def test_full_secret_never_appears_in_output():
    """Security guarantee: full secret value never appears in the output."""
    secret = "sk-fullSecretValueThatShouldNeverLeakIntoOutput12345"
    code = f'API_KEY="{secret}"'
    out = extract_suspected_secrets(code)
    api_entries = [e for e in out if e["kind"] == "api_key"]
    for entry in api_entries:
        # Full secret must not appear in hint.
        assert secret not in entry["hint"]
        # Hint is short.
        assert len(entry["hint"]) < len(secret)
