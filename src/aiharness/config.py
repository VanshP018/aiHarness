"""Runtime configuration sourced from the environment."""

from dataclasses import dataclass
import os
from pathlib import Path


def _load_local_env() -> None:
    """Load simple KEY=VALUE entries from .env without overriding the shell."""
    env_file = Path.cwd() / ".env"
    if not env_file.is_file():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name, value = name.strip(), value.strip()
        if name not in {"AI_API_KEY", "AI_MODEL", "AI_BASE_URL"}:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(name, value)


@dataclass(frozen=True)
class Settings:
    api_key: str
    model: str
    base_url: str

    @classmethod
    def from_environment(cls) -> "Settings":
        _load_local_env()
        return cls(
            api_key=os.getenv("AI_API_KEY", ""),
            model=os.getenv("AI_MODEL", "deepseek/deepseek-v3.2"),
            base_url=os.getenv("AI_BASE_URL", "https://openrouter.ai/api/v1"),
        )
