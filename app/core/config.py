from typing import List, Literal
from pydantic import AnyHttpUrl, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from urllib.parse import quote_plus


class Settings(BaseSettings):
    # =========================================================================
    # APP
    # =========================================================================
    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "Sistema Inventario TI"
    ENVIRONMENT: Literal["development", "staging", "production"] = "development"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"

    # =========================================================================
    # DATABASE
    # =========================================================================
    POSTGRES_SERVER: str
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_DB: str
    POSTGRES_PORT: int = 5432
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_RECYCLE: int = 1800
    DB_ECHO: bool = False

    # =========================================================================
    # AUTH
    # =========================================================================
    SECRET_KEY: str = Field(..., min_length=32)
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Account lockout
    ACCOUNT_LOCKOUT_THRESHOLD: int = 5
    ACCOUNT_LOCKOUT_MINUTES: int = 15

    # Password policy
    PASSWORD_MIN_LENGTH: int = 10
    PASSWORD_REQUIRE_UPPER: bool = True
    PASSWORD_REQUIRE_LOWER: bool = True
    PASSWORD_REQUIRE_DIGIT: bool = True
    PASSWORD_REQUIRE_SYMBOL: bool = False

    # =========================================================================
    # SECURITY
    # =========================================================================
    BACKEND_CORS_ORIGINS: List[AnyHttpUrl] = []
    RATE_LIMIT_LOGIN: str = "5/minute"
    RATE_LIMIT_DEFAULT: str = "100/minute"
    PAGINATION_MAX_LIMIT: int = 200

    # Redis (compartido entre workers/réplicas) — None = backend en memoria (no recomendado en prod)
    REDIS_URL: str | None = None
    AUTH_CACHE_TTL_SECONDS: int = 30

    # Clave Fernet para cifrar campos sensibles (LIC_Clave_Activacion).
    # Generar con: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    FIELD_ENCRYPTION_KEY: str | None = None

    # =========================================================================
    # VALIDATORS
    # =========================================================================
    @field_validator("SECRET_KEY")
    @classmethod
    def _no_default_secret(cls, v: str) -> str:
        weak_values = {"super_secret_key_change_me_in_prod", "change_me", "secret"}
        if v.lower() in weak_values:
            raise ValueError(
                "SECRET_KEY is set to a known weak default. "
                "Generate one with: openssl rand -hex 32"
            )
        return v

    # =========================================================================
    # DATABASE URI
    # =========================================================================
    @property
    def SQLALCHEMY_DATABASE_URI(self) -> str:
        if self.POSTGRES_SERVER == "sqlite":
            return "sqlite+aiosqlite:///./inventario.db"

        encoded_password = quote_plus(self.POSTGRES_PASSWORD)
        return (
            f"postgresql+psycopg://{self.POSTGRES_USER}:{encoded_password}"
            f"@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def IS_PRODUCTION(self) -> bool:
        return self.ENVIRONMENT == "production"

    @property
    def IS_SQLITE(self) -> bool:
        return self.POSTGRES_SERVER == "sqlite"

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="ignore",
    )


settings = Settings()
