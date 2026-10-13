
"""Provide fast, secure hashing utilities for one-time passwords."""

import hashlib
import hmac

from django.conf import settings


def hash_otp(plain_otp: str) -> str:
    """Return a keyed SHA-256 digest for an OTP."""
    secret = settings.OTP_HASH_SECRET.encode("utf-8")
    message = plain_otp.encode("utf-8")

    return hmac.new(secret, message, hashlib.sha256).hexdigest()


def verify_otp_hash(plain_otp: str, stored_hash: str) -> bool:
    """Verify an OTP against its stored digest using constant-time comparison."""
    return hmac.compare_digest(hash_otp(plain_otp), stored_hash)
