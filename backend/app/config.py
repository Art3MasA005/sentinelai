"""Runtime settings. Everything is local-first; override with SENTINEL_* env vars."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

APP_VERSION = "0.1.0"
API_PREFIX = "/api/v1"

_ROOT = Path(__file__).resolve().parents[2]  # .../sentinelai


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SENTINEL_", env_file=".env", extra="ignore")

    host: str = "127.0.0.1"
    port: int = 8765
    datasets_dir: Path = _ROOT / "data" / "datasets"
    results_dir: Path = _ROOT / "experiments" / "results"
    configs_dir: Path = _ROOT / "experiments" / "configs"
    db_path: Path = _ROOT / "data" / "sentinel.db"
    max_page_size: int = 500
    # Experiments running at once; extra starts wait in the queue (status "queued").
    max_workers: int = 2
    # Allowed browser origins for the Flutter app (desktop builds don't need CORS; web debug does).
    cors_origins: list[str] = ["http://localhost", "http://127.0.0.1"]
    cors_origin_regex: str = r"http://(localhost|127\.0\.0\.1)(:\d+)?"

    # ---- accounts (local only; nothing leaves this machine except the Google token check) ----
    # When true, every /api/v1 route except health and /auth/* needs a session token.
    auth_required: bool = False
    avatars_dir: Path = _ROOT / "data" / "avatars"
    session_hours: int = 12
    session_hours_remember: int = 24 * 30
    # OAuth client ID from Google Cloud Console (Web application type). Empty = Google sign-in disabled.
    google_client_id: str = ""
    # Desktop ("installed app") OAuth client for the Windows build's browser login, if used.
    google_desktop_client_id: str = ""
    google_desktop_client_secret: str = ""

    def ensure_dirs(self) -> None:
        for d in (self.datasets_dir, self.results_dir, self.configs_dir, self.db_path.parent, self.avatars_dir):
            d.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.ensure_dirs()
    return s
