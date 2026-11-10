from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    tickets_api_base_url: str = ""
    tickets_api_token: str = ""
    tickets_api_login: str = ""
    tickets_api_app: str = ""
    tickets_api_timeout_ms: float = 10000
    tickets_api_metadata_cache_ttl_ms: float = 300000
    tickets_api_fan_out_concurrency: int = 5

    anthropic_api_key: str = ""
    anthropic_model: str = "claude-haiku-5-5"
    anthropic_timeout_ms: float = 60000
    anthropic_effort: str | None = None  # low|medium|high|xhigh|max; vazio = padrão do modelo

    agent_host: str = "127.0.0.1"
    agent_port: int = 3100
    agent_request_timeout_ms: float = 300000
    agent_max_concurrent_requests: int = 1
    agent_rate_limit_window_ms: float = 60000
    agent_rate_limit_max_requests: int = 30


@lru_cache
def get_settings() -> Settings:
    return Settings()
