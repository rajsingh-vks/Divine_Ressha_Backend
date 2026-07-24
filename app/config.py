from functools import lru_cache
from os import environ, getenv
from pathlib import Path


def load_env_file() -> None:
    env_file = Path(__file__).resolve().parents[1] / ".env"

    if not env_file.exists():
        return

    for line in env_file.read_text().splitlines():
        stripped = line.strip()

        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue

        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")

        if key and getenv(key) is None:
            environ[key] = value


class Settings:
    def __init__(self) -> None:
        self.app_name = "Divine Reesha API"
        self.api_version = "0.1.0"
        self.mongodb_uri = getenv("MONGODB_URI", "mongodb://localhost:27017")
        self.mongodb_database = getenv("MONGODB_DATABASE", "divine_reesha")
        self.public_base_url = getenv("PUBLIC_BASE_URL", "").strip().rstrip("/") or None
        self.media_url_prefix = getenv("MEDIA_URL_PREFIX", "/api/media").strip() or "/api/media"
        if not self.media_url_prefix.startswith("/"):
            self.media_url_prefix = f"/{self.media_url_prefix}"
        self.media_url_prefix = self.media_url_prefix.rstrip("/")
        self.media_backend = getenv("MEDIA_BACKEND", "local").strip().lower() or "local"
        self.aws_region = getenv("AWS_REGION", "").strip() or None
        self.aws_s3_bucket = getenv("AWS_S3_BUCKET", "").strip() or None
        self.aws_s3_public_base_url = getenv("AWS_S3_PUBLIC_BASE_URL", "").strip().rstrip("/") or None
        self.razorpay_key_id = (
            getenv("RAZORPAY_KEY_ID", "").strip()
            or getenv("RAZORPAY_LIVE_KEY_ID", "").strip()
            or getenv("RAZORPAY_TEST_KEY_ID", "").strip()
            or None
        )
        self.razorpay_key_secret = (
            getenv("RAZORPAY_KEY_SECRET", "").strip()
            or getenv("RAZORPAY_LIVE_KEY_SECRET", "").strip()
            or getenv("RAZORPAY_TEST_KEY_SECRET", "").strip()
            or None
        )
        self.razorpay_currency = getenv("RAZORPAY_CURRENCY", "INR").strip().upper() or "INR"
        self.cors_origins = [
            origin.strip()
            for origin in getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
            if origin.strip()
        ]
        self.environment = getenv("ENVIRONMENT", "development").strip().lower() or "development"
        otp_expose_codes_raw = getenv("OTP_EXPOSE_CODES")
        if otp_expose_codes_raw is None:
            self.otp_expose_codes = self.environment != "production"
        else:
            self.otp_expose_codes = otp_expose_codes_raw.strip().lower() in {"1", "true", "yes", "on"}

        self.email_delivery_backend = getenv("EMAIL_DELIVERY_BACKEND", "console").strip().lower() or "console"
        self.ses_from_email = getenv("SES_FROM_EMAIL", "").strip() or None
        self.ses_configuration_set = getenv("SES_CONFIGURATION_SET", "").strip() or None
        self.smtp_host = getenv("SMTP_HOST", "").strip() or None
        self.smtp_port = int(getenv("SMTP_PORT", "587").strip() or "587")
        self.smtp_username = getenv("SMTP_USERNAME", "").strip() or getenv("EMAIL_USER", "").strip() or None
        self.smtp_password = getenv("SMTP_PASSWORD", "").strip() or getenv("EMAIL_PASS", "").strip() or None
        self.smtp_from_email = getenv("SMTP_FROM_EMAIL", "").strip() or None
        self.smtp_use_tls = getenv("SMTP_USE_TLS", "true").strip().lower() in {"1", "true", "yes", "on"}

        self.sms_delivery_backend = getenv("SMS_DELIVERY_BACKEND", "console").strip().lower() or "console"
        self.sms_webhook_url = getenv("SMS_WEBHOOK_URL", "").strip() or None
        self.sms_webhook_auth_token = getenv("SMS_WEBHOOK_AUTH_TOKEN", "").strip() or None


@lru_cache
def get_settings() -> Settings:
    load_env_file()
    return Settings()
