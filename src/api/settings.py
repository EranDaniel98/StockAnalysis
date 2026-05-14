"""API settings — read once at process start, overridable via env."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ApiSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="STOCKNEW_API_",
        env_file=".env",
        extra="ignore",
    )

    # 0.0.0.0 by default so the dashboard is reachable from a phone /
    # tablet on the same LAN. Personal dev box; this is gated by the
    # local network. Override via STOCKNEW_API_HOST=127.0.0.1 to lock
    # it back to loopback.
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8000)
    reload: bool = Field(default=False)

    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:3001",
            "http://127.0.0.1:3001",
            "http://localhost:3002",
            "http://127.0.0.1:3002",
            "http://localhost:3003",
            "http://127.0.0.1:3003",
            "http://localhost:3004",
            "http://127.0.0.1:3004",
        ]
    )
    """Exact-match origins. Add LAN IPs via cors_origin_regex instead so
    a DHCP-shifted phone doesn't need a settings change."""

    cors_origin_regex: str = Field(
        default=r"^http://(localhost|127\.0\.0\.1|10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|172\.(1[6-9]|2[0-9]|3[01])\.\d+\.\d+):(300\d|808\d)$"
    )
    """Regex covering the three RFC1918 LAN ranges on the Next.js (300x) /
    optional reverse-proxy (808x) ports. Stops `192.168.68.51:3000` from
    triggering the same `CORS Missing Allow Origin` browser error when
    the dashboard is opened from a phone."""

    log_level: str = Field(default="info")
