from __future__ import annotations

"""
Password hashing helpers.

We use Argon2id with the following minimum configuration:

- memory_cost: 19 MiB  (19 * 1024 KiB)
- time_cost:   2       (iterations)
- parallelism: 1       (degree of parallelism)

Make sure `argon2-cffi` is installed, e.g.:
    pip install argon2-cffi
"""

from argon2 import PasswordHasher
from argon2 import exceptions as argon2_exc

# Argon2id hasher instance.
# The returned hash string embeds all parameters, salt, and hash.
argon2_hasher = PasswordHasher(
    time_cost=2,  # iterations
    memory_cost=19 * 1024,  # KiB → ≈ 19 MiB
    parallelism=1,
)


def hash_password(plain: str) -> str:
    """
    Hash a plain-text password using Argon2id.

    The returned string is safe to store directly in the database.
    """
    return argon2_hasher.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """
    Verify a plain-text password against an Argon2id hash.

    Returns True if the password is valid, False otherwise.
    """
    try:
        return argon2_hasher.verify(hashed, plain)
    except (argon2_exc.VerifyMismatchError, argon2_exc.VerificationError):
        # Wrong password, corrupted hash, or unsupported format
        return False
