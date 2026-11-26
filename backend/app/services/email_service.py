import logging
import aiosmtplib
from email.message import EmailMessage
from backend.app.core.config import settings

logger = logging.getLogger("smartpresence.email")

async def send_low_attendance_email(
    to_email: str, 
    student_name: str, 
    subject_name: str, 
    attendance_percentage: float,
    threshold: float = 75.0,
    custom_note: str = ""
) -> bool:
    """
    Asynchronously sends an official low-attendance warning email using SMTP.
    """
    if not settings.SMTP_USER or not settings.SMTP_PASSWORD:
        logger.warning(
            f"[SIMULATED SMTP] SMTP credentials not set. Email would be dispatched to {to_email} "
            f"for student {student_name}: Attendance {attendance_percentage}% (< {threshold}% threshold)."
        )
        return True

    msg = EmailMessage()
    msg["Subject"] = f"URGENT: Low Attendance Warning Notice — {subject_name} ({attendance_percentage}%)"
    msg["From"] = settings.SMTP_FROM_EMAIL
    msg["To"] = to_email

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="utf-8">
      <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: #080F1F; color: #F8FAFC; margin: 0; padding: 24px; }}
        .card {{ background: #101B30; border: 1px solid rgba(255,255,255,0.1); border-radius: 12px; padding: 24px; max-width: 600px; margin: 0 auto; }}
        .badge {{ background: #EF4444; color: #FFF; padding: 4px 8px; border-radius: 6px; font-weight: bold; font-size: 12px; }}
        .stat {{ font-size: 28px; font-weight: 800; color: #F59E0B; margin: 12px 0; }}
        .footer {{ font-size: 11px; color: #94A3B8; margin-top: 24px; border-top: 1px solid rgba(255,255,255,0.05); padding-top: 12px; }}
      </style>
    </head>
    <body>
      <div class="card">
        <div style="display:flex; justify-content:space-between; align-items:center;">
          <h2 style="color: #6366F1; margin:0;">SmartPresence Institutional Notice</h2>
          <span class="badge">ACTION REQUIRED</span>
        </div>
        <p>Dear <strong>{student_name}</strong>,</p>
        <p>This is an automated notification regarding your academic attendance in <strong>{subject_name}</strong>.</p>
        <div class="stat">Your Attendance: {attendance_percentage:.1f}%</div>
        <p style="color: #EF4444;">Your recorded attendance is below the mandatory institutional requirement of <strong>{threshold:.0f}%</strong>.</p>
        {f'<p style="background: rgba(99,102,241,0.1); padding: 10px; border-radius: 8px;"><em>Note from Faculty: {custom_note}</em></p>' if custom_note else ''}
        <p>Please meet with your course instructor and academic advisor immediately to discuss your attendance and prevent examination disqualification.</p>
        <div class="footer">
          Sent by SmartPresence AI-Powered Attendance Management System • Official Academic Record
        </div>
      </div>
    </body>
    </html>
    """
    msg.set_content(f"Dear {student_name},\n\nYour attendance in {subject_name} is {attendance_percentage:.1f}%, which is below the required {threshold}%. Please consult your instructor immediately.")
    msg.add_alternative(html_content, subtype="html")

    try:
        await aiosmtplib.send(
            msg,
            hostname=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            start_tls=settings.SMTP_TLS,
            username=settings.SMTP_USER,
            password=settings.SMTP_PASSWORD,
            timeout=10
        )
        logger.info(f"Low attendance email sent successfully to {to_email}")
        return True
    except Exception as e:
        logger.error(f"Failed to dispatch email to {to_email}: {str(e)}")
        return False
