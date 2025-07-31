import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)

class EmailService:
    def __init__(self):
        self.smtp_host = settings.SMTP_HOST
        self.smtp_port = settings.SMTP_PORT
        self.smtp_secure = settings.SMTP_SECURE
        self.smtp_user = settings.SMTP_USER
        self.smtp_pass = settings.SMTP_PASS
        self.from_email = settings.FROM_EMAIL

    def is_configured(self) -> bool:
        """Check if SMTP is properly configured"""
        return all([
            self.smtp_host,
            self.smtp_port,
            self.smtp_user,
            self.smtp_pass,
            self.from_email
        ])

    def send_password_reset_email(self, to_email: str, reset_token: str, reset_url: str) -> bool:
        """Send password reset email with reset link"""
        if not self.is_configured():
            logger.warning("SMTP not configured, cannot send password reset email")
            return False

        try:
            # Create message
            msg = MIMEMultipart()
            msg['From'] = self.from_email
            msg['To'] = to_email
            msg['Subject'] = "DirectDrive Password Reset"

            # Email body
            body = f"""
            Hello,

            You have requested a password reset for your DirectDrive account.

            Click the following link to reset your password:
            {reset_url}?token={reset_token}

            This link will expire in 1 hour.

            If you did not request this password reset, please ignore this email.

            Best regards,
            DirectDrive Team
            """

            msg.attach(MIMEText(body, 'plain'))

            # Send email
            if self.smtp_secure:
                server = smtplib.SMTP_SSL(self.smtp_host, self.smtp_port)
            else:
                server = smtplib.SMTP(self.smtp_host, self.smtp_port)
                server.starttls()

            server.login(self.smtp_user, self.smtp_pass)
            server.send_message(msg)
            server.quit()

            logger.info(f"Password reset email sent to {to_email}")
            return True

        except Exception as e:
            logger.error(f"Failed to send password reset email to {to_email}: {str(e)}")
            return False

    def send_test_email(self, to_email: str) -> bool:
        """Send a test email to verify SMTP configuration"""
        if not self.is_configured():
            logger.warning("SMTP not configured, cannot send test email")
            return False

        try:
            msg = MIMEMultipart()
            msg['From'] = self.from_email
            msg['To'] = to_email
            msg['Subject'] = "DirectDrive SMTP Test"

            body = "This is a test email to verify SMTP configuration is working correctly."
            msg.attach(MIMEText(body, 'plain'))

            if self.smtp_secure:
                server = smtplib.SMTP_SSL(self.smtp_host, self.smtp_port)
            else:
                server = smtplib.SMTP(self.smtp_host, self.smtp_port)
                server.starttls()

            server.login(self.smtp_user, self.smtp_pass)
            server.send_message(msg)
            server.quit()

            logger.info(f"Test email sent successfully to {to_email}")
            return True

        except Exception as e:
            logger.error(f"Failed to send test email to {to_email}: {str(e)}")
            return False

# Global email service instance
email_service = EmailService() 