from __future__ import annotations

import logging
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from dmsai_models import SystemConfig, get_session

logger = logging.getLogger("dmsai.email")


def _get_smtp_config() -> dict:
    with get_session() as session:
        rows = session.query(SystemConfig).filter(
            SystemConfig.category == "email"
        ).all()
    return {r.key: r.value for r in rows}


def send_verification_email(to_email: str, full_name: str, token: str, base_url: str) -> bool:
    cfg = _get_smtp_config()
    host = cfg.get("smtp_host", "")
    if not host:
        logger.warning("SMTP not configured — verification email not sent to %s", to_email)
        return False

    port = int(cfg.get("smtp_port", "587"))
    user = cfg.get("smtp_user", "")
    password = cfg.get("smtp_password", "")
    use_tls = cfg.get("smtp_use_tls", "true").lower() == "true"
    from_email = cfg.get("smtp_from_email", "noreply@dmsai.local")
    from_name = cfg.get("smtp_from_name", "DMSAI")

    verify_url = f"{base_url}/api/auth/verify-email?token={token}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "DMSAI — Verify your email address"
    msg["From"] = f"{from_name} <{from_email}>"
    msg["To"] = to_email

    text_body = (
        f"Hello {full_name},\n\n"
        f"Please verify your email by visiting this link:\n{verify_url}\n\n"
        f"This link will expire in 24 hours.\n\n"
        f"If you did not create an account, you can ignore this email."
    )
    html_body = f"""\
<html><body style="font-family:sans-serif;color:#333;">
<h2>Welcome to DMSAI</h2>
<p>Hello {full_name},</p>
<p>Please click the button below to verify your email address:</p>
<p style="margin:24px 0;">
  <a href="{verify_url}"
     style="background:#2563eb;color:#fff;padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:600;">
    Verify Email
  </a>
</p>
<p style="font-size:13px;color:#888;">
  Or copy this URL into your browser:<br>{verify_url}
</p>
<p style="font-size:13px;color:#888;">This link expires in 24 hours.</p>
</body></html>"""

    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    try:
        if use_tls and port == 465:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(host, port, context=context) as server:
                if user:
                    server.login(user, password)
                server.sendmail(from_email, [to_email], msg.as_string())
        else:
            with smtplib.SMTP(host, port, timeout=15) as server:
                if use_tls:
                    server.starttls(context=ssl.create_default_context())
                if user:
                    server.login(user, password)
                server.sendmail(from_email, [to_email], msg.as_string())
        logger.info("Verification email sent to %s", to_email)
        return True
    except Exception:
        logger.exception("Failed to send verification email to %s", to_email)
        return False
