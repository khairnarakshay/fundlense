import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags

logger = logging.getLogger(__name__)


# Human-friendly subject + copy per OTP purpose
OTP_TEMPLATES = {
    "SIGNUP": {
        "subject": "Verify your email address",
        "heading": "Confirm your email",
        "intro": "Use the code below to verify your email and activate your account.",
    },
    "LOGIN": {
        "subject": "Your login verification code",
        "heading": "Login verification",
        "intro": "Use the code below to complete your login.",
    },
    "RESET_PASSWORD": {
        "subject": "Reset your password",
        "heading": "Password reset",
        "intro": "Use the code below to reset your password.",
    },
}
import time

def send_email_otp(email: str, otp: str, purpose: str) -> bool:
    """
    Send an OTP code to the given email address.

    Args:
        email: Recipient email address.
        otp: The OTP code (string).
        purpose: One of OTPType values, e.g. "SIGNUP", "LOGIN", "RESET_PASSWORD".

    Returns:
        True if the email was sent, False otherwise.

    Raises:
        Exception: re-raises SMTP errors so the caller's transaction can roll back.
    """
    started_at = time.perf_counter()
    purpose_key = str(purpose).upper()
    meta = OTP_TEMPLATES.get(purpose_key, OTP_TEMPLATES["SIGNUP"])

    subject = meta["subject"]
    from_email = getattr(settings, "SENT_FROM_EMAIL", settings.EMAIL_HOST_USER)

    context = {
        "otp": otp,
        "email": email,
        "purpose": purpose_key,
        "heading": meta["heading"],
        "intro": meta["intro"],
        "expiry_minutes": getattr(settings, "OTP_EXPIRY_MINUTES", 10),
        "brand_name": getattr(settings, "BRAND_NAME", "Fundlense-AI"),
    }

    # Plain-text fallback (always send this)
    text_body = (
        f"{meta['heading']}\n\n"
        f"{meta['intro']}\n\n"
        f"Your OTP code: {otp}\n\n"
        f"This code expires in {context['expiry_minutes']} minutes.\n"
        f"If you did not request this, please ignore this email.\n"
    )

    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=from_email,
        to=[email],
    )

    # Optional HTML version — only if the template exists
    try:
        html_body = render_to_string(
            "emails/otp_email.html",
            context,
        )
        msg.attach_alternative(html_body, "text/html")
    except Exception:
        # No template? That's fine — plain text will be sent.
        pass

    try:
        sent = msg.send(fail_silently=False)
        logger.info("OTP email sent to %s (purpose=%s)", email, purpose_key)
        return sent == 1
    except Exception as exc:
        logger.exception("Failed to send OTP email to %s: %s", email, exc)
        # Re-raise so the SignupAPIView transaction rolls back and returns 104.
        raise
    finally:
        logger.info(
            "OTP email delivery duration: %.3fs, purpose=%s",
            time.perf_counter() - started_at,
            purpose,
        )