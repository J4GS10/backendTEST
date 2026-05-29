from typing import List, Literal
from pydantic import AnyHttpUrl, Field, field_validator, model_validator
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
    # SMTP — notificaciones por email
    # Compatible con Brevo (300/día gratis), SendGrid (100/día), Gmail, Resend,
    # MailerSend, MailHog (dev). Si SMTP_HOST está vacío, los emails se loguean
    # pero no se envían (modo silencioso, útil para tests).
    # =========================================================================
    SMTP_HOST: str | None = None
    SMTP_PORT: int = 587
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None
    SMTP_TLS: bool = True
    SMTP_STARTTLS: bool = True
    SMTP_FROM_EMAIL: str = "noreply@lombardi.local"
    SMTP_FROM_NAME: str = "Sistema Inventario Lombardi"
    # Destinatario(s) admin que recibe copia de TODOS los eventos. Lista CSV.
    NOTIFY_ADMIN_EMAILS: str = ""  # "ops@empresa.com,it-lead@empresa.com"
    # Habilita / deshabilita envío sin cambiar SMTP_HOST (kill switch operacional).
    EMAIL_ENABLED: bool = True

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

    @model_validator(mode="after")
    def _production_hardening(self) -> "Settings":
        """
        Validaciones que sólo se aplican cuando ENVIRONMENT=production.
        El arranque falla si:
          - SEED_DEMO=true (cargaría usuarios demo con passwords conocidas).
          - FIELD_ENCRYPTION_KEY está vacío (cifrado de licencias sería no-op silencioso).
          - REDIS_URL no usa AUTH (redis:// sin :password@ en hostname).
        """
        if self.ENVIRONMENT != "production":
            return self
        # Las validaciones de SEED_DEMO se hacen en seed_demo.py al chequear el env var
        # directamente, ya que ese flag NO es parte del modelo Settings.
        if not self.FIELD_ENCRYPTION_KEY:
            raise ValueError(
                "FIELD_ENCRYPTION_KEY es OBLIGATORIO en producción. "
                "Genera una con: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
            )
        if self.REDIS_URL and "://" in self.REDIS_URL:
            # redis://[:password@]host:port/db — falla si no hay user/password antes de @
            after_scheme = self.REDIS_URL.split("://", 1)[1]
            if "@" not in after_scheme:
                raise ValueError(
                    "REDIS_URL sin AUTH en producción. Usa redis://:<password>@host:port/db"
                )
        return self

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
