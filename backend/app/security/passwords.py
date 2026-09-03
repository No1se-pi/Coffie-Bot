"""Password hashing for the optional browser admin login."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import sys

ALGORITHM = "pbkdf2_sha256"
ITERATIONS = 600_000


def hash_password(password: str) -> str:
    """Return a self-contained PBKDF2 hash suitable for an environment secret."""

    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), ITERATIONS)
    # Colons survive Docker Compose .env interpolation unchanged; dollar signs
    # would require error-prone escaping during production deployment.
    return f"{ALGORITHM}:{ITERATIONS}:{salt}:{digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    """Verify a password without leaking comparison timing."""

    try:
        algorithm, raw_iterations, salt, expected = encoded.split(":", 3)
        if algorithm != ALGORITHM:
            return False
        iterations = int(raw_iterations)
        if iterations < 100_000 or iterations > 2_000_000:
            return False
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt), iterations
        ).hex()
    except (TypeError, ValueError):
        return False
    return hmac.compare_digest(actual, expected)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python -m app.security.passwords '<password>'")
    print(hash_password(sys.argv[1]))
