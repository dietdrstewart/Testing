import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


class ConfigError(Exception):
    pass


@dataclass
class Config:
    aa_username: str
    aa_password: str
    marriott_username: str
    marriott_password: str
    gmail_sender: str
    gmail_app_password: str
    notify_email: str
    poll_interval_minutes: int
    state_file_path: Path
    cookie_dir: Path
    headed_browser: bool
    checkin_notify_hour: int
    log_level: str


def load_config() -> Config:
    load_dotenv()

    def require(key: str) -> str:
        val = os.getenv(key, "").strip()
        if not val:
            raise ConfigError(f"Missing required .env variable: {key}")
        return val

    def optional(key: str, default: str) -> str:
        return os.getenv(key, default).strip()

    return Config(
        aa_username=require("AA_USERNAME"),
        aa_password=require("AA_PASSWORD"),
        marriott_username=require("MARRIOTT_USERNAME"),
        marriott_password=require("MARRIOTT_PASSWORD"),
        gmail_sender=require("GMAIL_SENDER"),
        gmail_app_password=require("GMAIL_APP_PASSWORD"),
        notify_email=require("NOTIFY_EMAIL"),
        poll_interval_minutes=int(optional("POLL_INTERVAL_MINUTES", "5")),
        state_file_path=Path(optional("STATE_FILE_PATH", "~/.travel_notifier_state.json")).expanduser(),
        cookie_dir=Path(optional("COOKIE_DIR", "~/.travel_notifier_cookies")).expanduser(),
        headed_browser=optional("HEADED_BROWSER", "True").lower() in ("true", "1", "yes"),
        checkin_notify_hour=int(optional("CHECKIN_NOTIFY_HOUR", "8")),
        log_level=optional("LOG_LEVEL", "INFO").upper(),
    )
