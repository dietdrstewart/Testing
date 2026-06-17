from __future__ import annotations

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from .config import Config
from .models.flight import FlightData
from .models.hotel import HotelStay

logger = logging.getLogger(__name__)


def _html_wrap(title: str, rows: list[tuple[str, str]], footer: str = "") -> str:
    row_html = "".join(
        f"<tr><td style='padding:6px 12px;color:#666;font-size:14px'>{k}</td>"
        f"<td style='padding:6px 12px;font-size:14px;font-weight:bold'>{v}</td></tr>"
        for k, v in rows
    )
    return f"""
<div style="font-family:Arial,sans-serif;max-width:480px;margin:0 auto;border:1px solid #ddd;border-radius:8px;overflow:hidden">
  <div style="background:#003366;padding:20px">
    <h2 style="color:#fff;margin:0;font-size:20px">{title}</h2>
  </div>
  <table style="width:100%;border-collapse:collapse;background:#fafafa">
    {row_html}
  </table>
  {f'<div style="padding:12px;font-size:13px;color:#555;background:#f0f0f0">{footer}</div>' if footer else ''}
</div>
"""


class EmailNotifier:
    def __init__(self, config: Config):
        self._config = config

    def send(self, subject: str, body_text: str, body_html: str) -> bool:
        cfg = self._config
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = cfg.gmail_sender
        msg["To"] = cfg.notify_email
        msg.attach(MIMEText(body_text, "plain"))
        msg.attach(MIMEText(body_html, "html"))

        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
                smtp.login(cfg.gmail_sender, cfg.gmail_app_password)
                smtp.sendmail(cfg.gmail_sender, cfg.notify_email, msg.as_string())
            logger.info(f"Email sent: {subject}")
            return True
        except Exception as e:
            logger.error(f"Email failed ({subject}): {e}")
            return False

    def send_self(self, subject: str, body_text: str) -> None:
        """Send an alert to the sender's own address (health alerts, CAPTCHA notices)."""
        cfg = self._config
        msg = MIMEMultipart()
        msg["Subject"] = f"[Travel Notifier] {subject}"
        msg["From"] = cfg.gmail_sender
        msg["To"] = cfg.gmail_sender
        msg.attach(MIMEText(body_text, "plain"))
        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
                smtp.login(cfg.gmail_sender, cfg.gmail_app_password)
                smtp.sendmail(cfg.gmail_sender, cfg.gmail_sender, msg.as_string())
        except Exception as e:
            logger.error(f"Self-alert email failed: {e}")

    # ── Flight notifications ──────────────────────────────────────────────────

    def flight_delayed(self, flight: FlightData, location: str) -> None:
        subject = f"✈ AA {flight.flight_number} to {flight.destination} is DELAYED"
        rows = [
            ("Flight", flight.flight_number),
            ("Route", f"{flight.origin} → {flight.destination}"),
            ("New departure", flight.display_departure()),
            ("Scheduled arrival", flight.display_arrival()),
            ("Status", "⚠️ Delayed"),
            ("Gate", flight.gate or "TBD"),
            ("Current location", location),
        ]
        text = (
            f"Flight {flight.flight_number} ({flight.origin}→{flight.destination}) is DELAYED.\n"
            f"New departure: {flight.display_departure()}\n"
            f"Currently in: {location}"
        )
        self.send(subject, text, _html_wrap(subject, rows))

    def flight_boarding(self, flight: FlightData, location: str) -> None:
        subject = f"✈ AA {flight.flight_number} — NOW BOARDING at Gate {flight.gate or 'TBD'}"
        rows = [
            ("Flight", flight.flight_number),
            ("Route", f"{flight.origin} → {flight.destination}"),
            ("Departure", flight.display_departure()),
            ("Gate", flight.gate or "TBD"),
            ("Status", "🛫 Boarding"),
            ("Current location", location),
        ]
        text = (
            f"Flight {flight.flight_number} is NOW BOARDING at Gate {flight.gate or 'TBD'}.\n"
            f"Departure: {flight.display_departure()}\n"
            f"Currently in: {location}"
        )
        self.send(subject, text, _html_wrap(subject, rows))

    def flight_departed(self, flight: FlightData, location: str) -> None:
        subject = f"✈ AA {flight.flight_number} has DEPARTED {flight.origin}"
        rows = [
            ("Flight", flight.flight_number),
            ("Departed from", flight.origin),
            ("Destination", flight.destination),
            ("Departed at", flight.display_departure()),
            ("Expected arrival", flight.display_arrival()),
            ("Status", "🛫 En route"),
            ("Last known location", location),
        ]
        text = (
            f"Flight {flight.flight_number} has DEPARTED {flight.origin}.\n"
            f"Departed at: {flight.display_departure()}\n"
            f"Expected in {flight.destination} at: {flight.display_arrival()}\n"
            f"Last location: {location}"
        )
        self.send(subject, text, _html_wrap(subject, rows))

    def flight_landed(self, flight: FlightData, location: str) -> None:
        subject = f"✈ AA {flight.flight_number} has LANDED in {flight.destination}"
        rows = [
            ("Flight", flight.flight_number),
            ("Arrived in", flight.destination),
            ("Arrival time", flight.display_arrival()),
            ("Status", "🛬 Landed"),
            ("Current location", location),
        ]
        text = (
            f"Flight {flight.flight_number} has LANDED in {flight.destination}.\n"
            f"Arrival time: {flight.display_arrival()}\n"
            f"Current location: {location}"
        )
        self.send(subject, text, _html_wrap(subject, rows))

    def flight_cancelled(self, flight: FlightData, location: str) -> None:
        subject = f"❌ AA {flight.flight_number} has been CANCELLED"
        rows = [
            ("Flight", flight.flight_number),
            ("Route", f"{flight.origin} → {flight.destination}"),
            ("Status", "❌ Cancelled"),
            ("Current location", location),
        ]
        text = (
            f"Flight {flight.flight_number} ({flight.origin}→{flight.destination}) has been CANCELLED.\n"
            f"Currently in: {location}"
        )
        self.send(subject, text, _html_wrap(subject, rows))

    def gate_changed(self, flight: FlightData, old_gate: str, location: str) -> None:
        subject = f"✈ AA {flight.flight_number} — Gate changed to {flight.gate}"
        rows = [
            ("Flight", flight.flight_number),
            ("Route", f"{flight.origin} → {flight.destination}"),
            ("Old gate", old_gate or "Unknown"),
            ("New gate", flight.gate or "TBD"),
            ("Departure", flight.display_departure()),
            ("Current location", location),
        ]
        text = (
            f"Gate change: Flight {flight.flight_number} is now at Gate {flight.gate}.\n"
            f"Previous gate: {old_gate or 'Unknown'}\n"
            f"Currently in: {location}"
        )
        self.send(subject, text, _html_wrap(subject, rows))

    # ── Hotel notifications ───────────────────────────────────────────────────

    def hotel_checkin_today(self, stay: HotelStay, location: str) -> None:
        subject = f"🏨 Check-in day: {stay.hotel_name}"
        rows = [
            ("Hotel", stay.hotel_name),
            ("Check-in", stay.check_in_date.strftime("%A, %B %-d, %Y")),
            ("Check-out", stay.check_out_date.strftime("%A, %B %-d, %Y")),
            ("Confirmation", stay.confirmation_number),
            ("Current location", location),
        ]
        text = (
            f"Today is check-in day at {stay.hotel_name}.\n"
            f"Check-in: {stay.check_in_date}\n"
            f"Check-out: {stay.check_out_date}\n"
            f"Confirmation: {stay.confirmation_number}\n"
            f"Current location: {location}"
        )
        self.send(subject, text, _html_wrap(subject, rows))
