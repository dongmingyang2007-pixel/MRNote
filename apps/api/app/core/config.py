from functools import lru_cache
from pathlib import Path
from typing import Annotated
from urllib.parse import urlparse

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

LOOPBACK_ORIGIN_REGEX = r"^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$"

# Resolve project root .env regardless of CWD
_PROJECT_ROOT = Path(__file__).resolve().parents[4]  # config.py → core → app → api → apps → project root
_ENV_FILE = _PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(_ENV_FILE), env_file_encoding="utf-8", extra="ignore")

    env: str = "local"
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/qihang"

    jwt_secret: str = "CHANGE_ME"
    jwt_expire_minutes: int = 60
    jwt_refresh_expire_days: int = 14
    cookie_domain: str = "localhost"
    cookie_secure: bool = False
    cookie_samesite: str = "lax"
    access_cookie_name: str = "access_token"
    csrf_cookie_name: str = "csrf_token"
    csrf_ttl_seconds: int = 3600

    redis_url: str = "redis://localhost:6379/0"
    redis_namespace: str = "qihang"
    redis_connect_timeout_seconds: float = 1.0
    trust_forwarded_for: bool = False

    s3_endpoint: str = "http://localhost:9000"
    s3_presign_endpoint: str = ""
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_private_bucket: str = "qihang-private"
    s3_ai_action_payloads_bucket: str = "ai-action-payloads"
    s3_notebook_attachments_bucket: str = "notebook-attachments"
    notebook_attachment_max_bytes: int = 50 * 1024 * 1024
    s3_region: str = "us-east-1"
    s3_presign_expire_seconds: int = 900

    upload_max_mb: int = 50
    upload_put_proxy: bool = False
    upload_session_ttl_seconds: int = 900

    # ── AI / Model API ──
    dashscope_api_key: str = ""
    dashscope_model: str = "qwen3.5-plus"
    dashscope_embedding_model: str = "text-embedding-v3"
    dashscope_rerank_model: str = "gte-rerank-v2"
    thinking_classifier_model: str = "qwen3.5-flash"
    thinking_classifier_min_confidence: float = 0.65
    ai_gateway_tool_selection_enabled: bool = True
    ai_gateway_tool_selection_trigger_tool_count: int = 4
    ai_gateway_tool_selection_top_n: int = 6
    ai_gateway_tool_selection_top_k_percent: int = 60
    ai_gateway_tool_selection_score_threshold: float = 0.0
    ai_gateway_tool_selection_failure_mode: str = "bypass"
    ai_gateway_tool_selection_query_rewrite_enabled: bool = True
    ai_gateway_tool_selection_query_rewrite_turn_threshold: int = 2
    ai_gateway_tool_selection_query_rewrite_model: str = "qwen3.5-flash"

    # ── Memory Triage ──
    memory_triage_model: str = "qwen-turbo"
    memory_triage_similarity_low: float = 0.70
    memory_triage_similarity_high: float = 0.90

    # ── Realtime Voice ──
    realtime_interrupt_threshold_ms: int = 500
    realtime_idle_timeout_seconds: int = 60
    realtime_close_timeout_seconds: int = 120
    realtime_max_session_seconds: int = 1800
    realtime_max_concurrent_sessions: int = 50
    realtime_context_history_turns: int = 10
    realtime_rag_refresh_turns: int = 5
    realtime_reconnect_max_attempts: int = 3
    realtime_media_max_mb: int = 12
    voice_reply_max_sentences: int = 2
    voice_reply_soft_char_limit: int = 60
    voice_reply_hard_char_limit: int = 90

    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from_address: str = ""
    smtp_from_name: str = "铭润科技"
    verification_code_ttl_seconds: int = 600
    verification_code_length: int = 6
    verification_rate_limit_window_seconds: int = 60
    verification_rate_limit_max: int = 3
    image_allowed_media_types: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["image/jpeg", "image/png", "image/webp"]
    )

    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["http://localhost:3000", "http://127.0.0.1:3000"])
    allowed_hosts: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["localhost", "127.0.0.1", "testserver"]
    )

    auth_rate_limit_window_seconds: int = 300
    auth_rate_limit_ip_max: int = 10
    auth_rate_limit_email_ip_max: int = 5
    upload_presign_rate_limit_window_seconds: int = 300
    upload_presign_rate_limit_max: int = 20
    model_artifact_presign_rate_limit_window_seconds: int = 300
    model_artifact_presign_rate_limit_max: int = 20
    sse_rate_limit_window_seconds: int = 60
    sse_rate_limit_max: int = 10
    memory_read_rate_limit_window_seconds: int = 60
    memory_read_rate_limit_max: int = 120
    memory_write_rate_limit_window_seconds: int = 60
    memory_write_rate_limit_max: int = 40

    # ---------------------------------------------------------------
    # S6 Billing — Stripe (livemode IDs are defaults; env can override)
    # NOTE: production deployments MUST set
    # stripe_billing_portal_return_url to the public domain.
    # ---------------------------------------------------------------
    stripe_api_key: str = Field(default="", env="STRIPE_API_KEY")
    stripe_webhook_secret: str = Field(default="", env="STRIPE_WEBHOOK_SECRET")
    stripe_publishable_key: str = Field(default="", env="STRIPE_PUBLISHABLE_KEY")
    stripe_billing_portal_return_url: str = Field(
        default="http://localhost:3000/workspace/settings/billing",
        env="STRIPE_BILLING_PORTAL_RETURN_URL",
    )
    stripe_checkout_success_url: str = Field(
        default="http://localhost:3000/workspace/settings/billing?status=success",
        env="STRIPE_CHECKOUT_SUCCESS_URL",
    )
    stripe_checkout_cancel_url: str = Field(
        default="http://localhost:3000/workspace/settings/billing?status=cancel",
        env="STRIPE_CHECKOUT_CANCEL_URL",
    )
    stripe_price_pro_monthly: str = Field(
        default="price_1TNFnSRzO5cz1hgYP5J3Ez3h", env="STRIPE_PRICE_PRO_MONTHLY",
    )
    stripe_price_pro_yearly: str = Field(
        default="price_1TNFnWRzO5cz1hgYqPbchdne", env="STRIPE_PRICE_PRO_YEARLY",
    )
    stripe_price_power_monthly: str = Field(
        default="price_1TNFncRzO5cz1hgYvZ4UkVlP", env="STRIPE_PRICE_POWER_MONTHLY",
    )
    stripe_price_power_yearly: str = Field(
        default="price_1TNFnhRzO5cz1hgYxQUJh6aL", env="STRIPE_PRICE_POWER_YEARLY",
    )
    stripe_price_team_monthly: str = Field(
        default="price_1TNFnmRzO5cz1hgYpqQBCs8s", env="STRIPE_PRICE_TEAM_MONTHLY",
    )
    stripe_price_team_yearly: str = Field(
        default="price_1TNFnrRzO5cz1hgYPFabWMpM", env="STRIPE_PRICE_TEAM_YEARLY",
    )

    # ---------------------------------------------------------------
    # Google OAuth (see docs/superpowers/specs/2026-04-19-google-oauth-design.md)
    # ---------------------------------------------------------------
    google_client_id: str = Field(default="", env="GOOGLE_CLIENT_ID")
    google_client_secret: str = Field(default="", env="GOOGLE_CLIENT_SECRET")
    google_oauth_redirect_base: str = Field(
        default="http://localhost:3000", env="GOOGLE_OAUTH_REDIRECT_BASE",
    )
    oauth_session_secret: str = Field(
        default="change-me-in-prod-use-openssl-rand-hex-32",
        env="OAUTH_SESSION_SECRET",
    )
    google_oauth_enabled: bool = Field(default=False, env="GOOGLE_OAUTH_ENABLED")

    @property
    def google_oauth_redirect_uri(self) -> str:
        return f"{self.google_oauth_redirect_base.rstrip('/')}/api/v1/auth/google/callback"

    @field_validator("cors_origins", "allowed_hosts", "image_allowed_media_types", mode="before")
    @classmethod
    def _parse_list_settings(cls, value):
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @property
    def is_production(self) -> bool:
        return self.env.lower() == "production"

    @property
    def normalized_cors_origins(self) -> set[str]:
        return {self.normalize_origin(origin) for origin in self.cors_origins}

    @property
    def cors_origin_regex(self) -> str | None:
        if self.is_production:
            return None
        return LOOPBACK_ORIGIN_REGEX

    def should_use_proxy_uploads(self) -> bool:
        return self.env in {"local", "test"} or self.upload_put_proxy

    @staticmethod
    def normalize_origin(value: str) -> str:
        parsed = urlparse(value)
        if not parsed.scheme or not parsed.netloc:
            return value.rstrip("/")
        return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")

    def is_origin_allowed(self, origin: str) -> bool:
        normalized_origin = self.normalize_origin(origin)
        if normalized_origin in self.normalized_cors_origins:
            return True

        if self.is_production:
            return False

        parsed = urlparse(normalized_origin)
        return parsed.scheme in {"http", "https"} and parsed.hostname in {"localhost", "127.0.0.1", "::1"}

    def validate_runtime_configuration(self) -> None:
        if not self.is_production:
            return

        problems: list[str] = []
        if self.jwt_secret == "CHANGE_ME" or len(self.jwt_secret) < 32:
            problems.append("JWT_SECRET must be a strong non-default secret in production")
        if not self.cookie_secure:
            problems.append("COOKIE_SECURE must be true in production")
        if not self.allowed_hosts or "*" in self.allowed_hosts:
            problems.append("ALLOWED_HOSTS must be explicitly configured in production")
        if not self.cors_origins or "*" in self.cors_origins:
            problems.append("CORS origins must be explicitly configured in production")
        if self.s3_access_key == "minioadmin" or self.s3_secret_key == "minioadmin":
            problems.append("Default object storage credentials must not be used in production")
        if problems:
            raise RuntimeError("Invalid production configuration: " + "; ".join(problems))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
