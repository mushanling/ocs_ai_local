from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit
import os

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    base_url: str = "https://api.deepseek.com"
    api_key: str = field(default="", repr=False)
    model: str = "deepseek-flash"
    thinking: str = "enabled"
    effort: str = "low"
    timeout: float = 110
    max_tokens: int = 16384
    vision: bool = True
    token: str = field(default="", repr=False)
    port: int = 8765
    cache: bool = True
    cache_ttl: int = 604800
    db_path: Path = ROOT / "data/quiz.sqlite3"

    def __post_init__(self):
        url = urlsplit(self.base_url)
        if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError("LLM_BASE_URL 必须是不含凭据、查询参数的 HTTP(S) base URL")
        if self.base_url.rstrip("/").endswith("/chat/completions"):
            raise ValueError("LLM_BASE_URL 不要包含 /chat/completions")
        if self.thinking not in {"enabled", "disabled", "omit"}:
            raise ValueError("LLM_THINKING_MODE 必须是 enabled / disabled / omit")
        if self.thinking == "enabled" and self.effort == "none":
            raise ValueError("启用思考时不能使用 none 强度")
        if not self.model.strip() or not self.token or self.token == "replace-with-a-random-token":
            raise ValueError("请在 .env 中设置 LLM_MODEL 和随机 LOCAL_TOKEN")
        if not 1 <= self.port <= 65535 or self.timeout <= 0 or self.max_tokens <= 0 or self.cache_ttl <= 0:
            raise ValueError("端口、超时、token 上限和缓存有效期必须为正数")

    @classmethod
    def load(cls):
        load_dotenv(ROOT / ".env", override=False)

        def boolean(name, default):
            value = os.getenv(name, default).lower().strip()
            if value not in {"true", "false"}:
                raise ValueError(f"{name} 必须是 true / false")
            return value == "true"

        return cls(
            base_url=os.getenv("LLM_BASE_URL", "https://api.deepseek.com").rstrip("/"),
            api_key=os.getenv("LLM_API_KEY", "").strip(),
            model=os.getenv("LLM_MODEL", "deepseek-flash"),
            thinking=os.getenv("LLM_THINKING_MODE", "enabled"),
            effort=os.getenv("LLM_REASONING_EFFORT", "low").strip(),
            timeout=float(os.getenv("LLM_TIMEOUT_SECONDS", "110")),
            max_tokens=int(os.getenv("LLM_MAX_TOKENS", "16384")),
            vision=boolean("VISION_ENABLED", "true"),
            token=os.getenv("LOCAL_TOKEN", "").strip(),
            port=int(os.getenv("PORT", "8765")),
            cache=boolean("CACHE_ENABLED", "true"),
            cache_ttl=int(os.getenv("CACHE_TTL_SECONDS", "604800")),
            db_path=ROOT / os.getenv("DB_PATH", "data/quiz.sqlite3"),
        )
