import smtplib
from email.message import EmailMessage

from app.config import settings


def send_mail(to: str, subject: str, body: str, *, attachment: tuple[str, bytes] | None = None) -> bool:
    if not settings.smtp_host:
        if settings.development:
            return False  # 개발 인증번호는 HTTP 응답으로만 전달하고 로그에는 남기지 않는다.
        raise RuntimeError("SMTP 설정이 필요합니다.")
    message = EmailMessage()
    message["From"] = settings.smtp_from or settings.smtp_user
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    if attachment:
        filename, content = attachment
        message.add_attachment(content, maintype="text", subtype="csv", filename=filename)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
        smtp.starttls()
        if settings.smtp_user:
            smtp.login(settings.smtp_user, settings.smtp_password or "")
        smtp.send_message(message)
    return True
