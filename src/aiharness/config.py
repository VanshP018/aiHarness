"""Runtime configuration sourced from the environment."""

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    api_key: str
    model: str
    base_url: str

    @classmethod
    def from_environment(cls) -> "Settings":
        return cls(
            api_key=os.getenv("AI_API_KEY", ""),
            model=os.getenv("AI_MODEL", ""),
            base_url=os.getenv("AI_BASE_URL", ""),
        )
