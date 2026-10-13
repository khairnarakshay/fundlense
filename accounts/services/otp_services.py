# services.py
import hmac
import secrets
from datetime import timedelta

from django.conf import settings
from accounts.models import OTP
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response

from core.mail_otp_templates import send_email_otp
import  logging

from core.otp_hash import hash_otp, verify_otp_hash

logger = logging.getLogger(__name__)

OTP_EXPIRY_MINUTES = 10
OTP_DEFAULT_LIMIT = 10
OTP_RESEND_LIMIT = 5
OTP_RESEND_WINDOW_HOURS = 5
OTP_MAX_ATTEMPTS = 5


import time

def issue_email_otp(user, otp_type, is_resend=False):
    """Create or replace an OTP with resend limits based on its update time."""

    now = timezone.now()
    expiry_minutes = getattr(settings, "OTP_EXPIRY_MINUTES", 10)
    plain_otp = f"{secrets.randbelow(1_000_000):06d}"

    with transaction.atomic():
        challenge = OTP.objects.select_for_update().filter(
            user=user,
            otp_type=otp_type,
        ).first()

        if challenge:
            if now >= challenge.updated + timedelta(hours=OTP_RESEND_WINDOW_HOURS):
                challenge.resend_count = 0

            if is_resend and challenge.resend_count >= OTP_RESEND_LIMIT:
                return False, "OTP resend limit reached. Please try again later."

            if is_resend:
                challenge.resend_count += 1

            challenge.otp = hash_otp(plain_otp)
            challenge.otp_limit = OTP_DEFAULT_LIMIT
            challenge.failed_count = 0
            challenge.expires_at = now + timedelta(minutes=expiry_minutes)
            challenge.is_verified = False
            challenge.save(update_fields=[
                "otp",
                "otp_limit",
                "failed_count",
                "resend_count",
                "expires_at",
                "is_verified",
                "updated",
            ])
        else:
            OTP.objects.create(
                user=user,
                otp=hash_otp(plain_otp),
                otp_type=otp_type,
                otp_limit=OTP_DEFAULT_LIMIT,
                failed_count=0,
                resend_count=0,
                expires_at=now + timedelta(minutes=expiry_minutes),
                is_verified=False,
            )

    try:
        if not send_email_otp(user.email, plain_otp, otp_type):
            return False, "Unable to send OTP. Please try again."
    except Exception as e:
        return False, f"Unable to send OTP. Please try again.({e})"

    return True, "OTP sent successfully."

def get_valid_otp(user, otp, otp_type, require_verified=False):
    print("Hit")
    """Validate an OTP and log timings for database and hash operations."""
    total_started = time.perf_counter()
    timings = {}

    try:
        with transaction.atomic():
            started = time.perf_counter()
            challenge = OTP.objects.select_for_update().filter(
                user=user,
                otp_type=otp_type,
            ).first()
            timings["db_lookup_and_lock"] = time.perf_counter() - started

            if not challenge:
                logger.warning("OTP timing: record not found, type=%s", otp_type)
                return None

            if challenge.expires_at <= timezone.now() or challenge.otp_limit <= 0:
                logger.warning("OTP timing: expired or attempts exhausted, type=%s", otp_type)
                return None

            if require_verified and not challenge.is_verified:
                logger.warning("OTP timing: challenge not verified, type=%s", otp_type)
                return None

            started = time.perf_counter()
            is_valid = verify_otp_hash(otp, challenge.otp)
            timings["password_hash_check"] = time.perf_counter() - started

            if not is_valid:
                challenge.otp_limit -= 1
                challenge.failed_count += 1

                started = time.perf_counter()
                challenge.save(update_fields=["otp_limit", "failed_count", "updated"])
                timings["db_save"] = time.perf_counter() - started

                logger.warning("OTP timing: hash mismatch, type=%s", otp_type)
                return None

            logger.info("OTP timing: validation successful, type=%s", otp_type)
            return challenge

    except Exception:
        logger.exception("OTP validation error, type=%s", otp_type)
        raise

    finally:
        timings["total"] = time.perf_counter() - total_started
        logger.warning(
            "OTP performance | type=%s | timings=%s",
            otp_type,
            {key: round(value, 4) for key, value in timings.items()},
        )