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
    DB_ENGINE: Literal["postgres", "oracle", "mysql", "sqlite"] = "postgres"
    DB_WRITE_DSN: str | None = None
    DB_READ_DSN: str | None = None
    DB_WRITE_HOST: str | None = None
    DB_READ_HOST: str | None = None
    POSTGRES_SERVER: str
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_DB: str
    POSTGRES_PORT: int = 5432
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_RECYCLE: int = 1800
    DB_ECHO: bool = False

    # Replica opcional para reportería/exports/consultas pesadas.
    # Si POSTGRES_REPLICA_SERVER está vacío, el backend usa el primario también
    # para lecturas, manteniendo compatibilidad con despliegues simples.
    POSTGRES_REPLICA_SERVER: str | None = None
    POSTGRES_REPLICA_USER: str | None = None
    POSTGRES_REPLICA_PASSWORD: str | None = None
    POSTGRES_REPLICA_DB: str | None = None
    POSTGRES_REPLICA_PORT: int = 5432
    DB_READ_POOL_SIZE: int = 10
    DB_READ_MAX_OVERFLOW: int = 20
    DB_CONNECT_TIMEOUT_SECONDS: int = 5
    DB_FAILOVER_PROBE_RETRIES: int = 1
    DB_FAILOVER_RETRY_DELAY_SECONDS: float = 0.25
    DB_REPLICA_CHECK_TIMEOUT_SECONDS: float = 2.0
    DB_REPLICA_LAG_WARNING_SECONDS: float = 5.0
    DB_REPLICA_LAG_CRITICAL_SECONDS: float = 30.0

    # =========================================================================
    # AUTH
    # =========================================================================
    SECRET_KEY: str = Field(..., min_length=32)
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 1
    # Duración máxima ABSOLUTA de una sesión desde el login, aunque haya
    # actividad y el refresh rote (evita sesiones eternas en equipos compartidos).
    SESSION_ABSOLUTE_MAX_HOURS: int = 12
    # Inactividad máxima aplicada por el SERVIDOR: el refresh token vive este
    # tiempo y se renueva con cada uso (actividad). Sin actividad, la sesión
    # muere aunque el navegador quede abierto. Debe ser > ACCESS_TOKEN_EXPIRE_MINUTES.
    SESSION_IDLE_TIMEOUT_MINUTES: int = 30
    # False = cookie de sesión (se borra al cerrar el navegador). True = persiste
    # hasta la expiración del refresh ("recordarme").
    REFRESH_COOKIE_PERSISTENT: bool = False
    # Ventana en la que reusar un refresh ya rotado se considera una carrera
    # legítima (respuesta perdida, dos pestañas). Fuera de ella = posible robo
    # → se revocan TODAS las sesiones del usuario.
    REFRESH_REUSE_GRACE_SECONDS: int = 30

    # Account lockout
    ACCOUNT_LOCKOUT_THRESHOLD: int = 5
    ACCOUNT_LOCKOUT_MINUTES: int = 15

    # Password reset (olvidé mi contraseña) — el token se envía SOLO al correo
    # corporativo registrado del usuario; expira y es de un solo uso.
    PASSWORD_RESET_EXPIRE_MINUTES: int = 30
    # Throttle POR CUENTA: no se emite otro correo de reset si ya se solicitó uno
    # en esta ventana (anti-bombardeo de emails a una víctima desde IPs rotativas).
    PASSWORD_RESET_REQUEST_COOLDOWN_MINUTES: int = 2

    # 2FA / MFA
    TWO_FACTOR_ISSUER: str = "Inventario Lombardi"   # nombre que muestra la app TOTP
    TWO_FACTOR_EMAIL_OTP_EXPIRE_MINUTES: int = 10    # validez del código por email
    TWO_FACTOR_CHALLENGE_EXPIRE_MINUTES: int = 5     # validez del "challenge" tras la contraseña
    TWO_FACTOR_MAX_ATTEMPTS: int = 5                 # intentos por código de email
    TWO_FACTOR_RECOVERY_CODES: int = 8               # códigos de recuperación generados
    # Roles para los que 2FA es OBLIGATORIO (deben enrolarse; CSV de roles).
    TWO_FACTOR_REQUIRED_ROLES: str = "SUPER_ADMIN,ADMIN_SEGURIDAD,ADMIN_TI"
    # Base pública del frontend para construir el enlace de restablecimiento.
    FRONTEND_BASE_URL: str = "https://localhost"

    # SSO / OIDC (Microsoft Entra ID y Google Workspace). Desactivado por
    # defecto: el login interno sigue funcionando aun si el proveedor externo cae.
    SSO_ENABLED: bool = False
    SSO_ALLOWED_EMAIL_DOMAINS: str = ""  # CSV opcional: empresa.com,subsidiaria.com
    SSO_MICROSOFT_CLIENT_ID: str | None = None
    SSO_MICROSOFT_CLIENT_SECRET: str | None = None
    SSO_MICROSOFT_TENANT: str = "organizations"
    SSO_MICROSOFT_REDIRECT_URI: str | None = None
    SSO_GOOGLE_CLIENT_ID: str | None = None
    SSO_GOOGLE_CLIENT_SECRET: str | None = None
    SSO_GOOGLE_REDIRECT_URI: str | None = None

    # Password policy
    PASSWORD_MIN_LENGTH: int = 10
    PASSWORD_REQUIRE_UPPER: bool = True
    PASSWORD_REQUIRE_LOWER: bool = True
    PASSWORD_REQUIRE_DIGIT: bool = True
    PASSWORD_REQUIRE_SYMBOL: bool = False
    # No se puede reutilizar ninguna de las últimas N contraseñas (0 = sin historial).
    PASSWORD_HISTORY_COUNT: int = 5
    # Palabras que una contraseña no puede contener (además de la lista de
    # contraseñas comunes y del nombre de usuario). CSV, sin distinguir mayúsculas.
    PASSWORD_BLOCKED_WORDS: str = "lombardi,inventario,password,contrasena,contraseña,admin,bienvenido,welcome"

    # Sesiones y cuentas
    # Aviso por correo cuando se inicia sesión desde un dispositivo no visto antes.
    NEW_DEVICE_ALERT_ENABLED: bool = True
    # Días que se conserva el historial de sesiones (base de "dispositivo conocido").
    SESSION_HISTORY_DAYS: int = 180
    # Cuentas sin iniciar sesión en N días se desactivan solas (0 = nunca).
    ACCOUNT_INACTIVITY_DISABLE_DAYS: int = 90
    # Retención de la bitácora de auditoría en días (0 = conservar siempre).
    AUDIT_RETENTION_DAYS: int = 0

    # RLS por sede en PostgreSQL: las consultas de usuarios se ejecutan con este
    # rol sin privilegios (SET LOCAL ROLE), sujeto a las políticas de app/db/rls.py.
    DB_RLS_ENABLED: bool = True
    DB_RLS_ROLE: str = Field("inventario_rls", pattern=r"^[a-z_][a-z0-9_]{2,62}$")

    # =========================================================================
    # SECURITY
    # =========================================================================
    BACKEND_CORS_ORIGINS: List[AnyHttpUrl] = []
    RATE_LIMIT_LOGIN: str = "5/minute"
    # Por IP. Si los usuarios salen por un proxy/NAT corporativo compartido, TODOS
    # comparten este cupo: súbelo (p. ej. 300/minute) junto con RATE_LIMIT_LOGIN.
    RATE_LIMIT_REFRESH: str = "10/minute"
    RATE_LIMIT_DEFAULT: str = "100/minute"
    PAGINATION_MAX_LIMIT: int = 200

    # Redis (compartido entre workers/réplicas) — None = backend en memoria (no recomendado en prod)
    REDIS_URL: str | None = None
    AUTH_CACHE_TTL_SECONDS: int = 30

    # Clave Fernet para cifrar campos sensibles (LIC_Clave_Activacion).
    # Generar con: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    FIELD_ENCRYPTION_KEY: str | None = None

    # =========================================================================
    # ADJUNTOS (archivos por activo: factura, foto, acta firmada)
    # Almacenamiento en disco local (volumen Docker). Para migrar a S3/MinIO,
    # reemplazar la capa de storage en services/attachments.py.
    # =========================================================================
    UPLOAD_DIR: str = "/app/uploads"
    MAX_UPLOAD_SIZE_MB: int = 10
    # Extensiones permitidas (defensa: evita subir ejecutables/scripts).
    ALLOWED_UPLOAD_EXTENSIONS: List[str] = [
        ".pdf", ".png", ".jpg", ".jpeg", ".webp", ".docx", ".xlsx", ".csv", ".txt",
    ]
    STORAGE_BACKEND: Literal["local", "s3"] = "local"
    S3_ENDPOINT_URL: str | None = None
    S3_ACCESS_KEY: str | None = None
    S3_SECRET_KEY: str | None = None
    S3_BUCKET: str = "lombardi-adjuntos"
    S3_REGION: str = "us-east-1"
    STORAGE_TIMEOUT_SECONDS: float = 5.0

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
    SMTP_TIMEOUT_SECONDS: float = 10.0
    SMTP_FROM_EMAIL: str = "noreply@lombardi.local"
    SMTP_FROM_NAME: str = "Sistema Inventario Lombardi"
    # Destinatario(s) admin que recibe copia de TODOS los eventos. Lista CSV.
    NOTIFY_ADMIN_EMAILS: str = ""  # "ops@empresa.com,it-lead@empresa.com"
    # Habilita / deshabilita envío sin cambiar SMTP_HOST (kill switch operacional).
    EMAIL_ENABLED: bool = True
    # Cola persistente de correos (SYS_EMAIL_OUTBOX): intentos antes de FALLIDO
    # (backoff 1m,5m,15m,1h,3h,6h ≈ 10 h cubiertas) y sondeo del worker.
    OUTBOX_MAX_ATTEMPTS: int = 7
    OUTBOX_POLL_SECONDS: int = 15
    OUTBOX_RETENTION_DAYS: int = 30

    # =========================================================================
    # ACTIVE DIRECTORY (LDAP) — directorio de personas, jefes y grupos para
    # notificaciones. Desactivado por defecto. Bind SIMPLE con UPN
    # (svc_inventario@empresa.local) sobre LDAPS (ldaps://dc01:636) o StartTLS.
    # =========================================================================
    AD_ENABLED: bool = False
    AD_SERVER: str = ""  # "ldaps://dc01.empresa.local" (CSV para varios DC)
    AD_START_TLS: bool = False
    AD_VERIFY_CERT: bool = True
    AD_CA_CERT_FILE: str | None = None
    AD_BIND_USER: str | None = None
    AD_BIND_PASSWORD: str | None = None
    AD_BASE_DN: str = ""  # "OU=Usuarios,DC=empresa,DC=local"
    AD_GROUP_BASE_DN: str = ""  # vacío → AD_BASE_DN
    AD_USER_FILTER: str = "(&(objectCategory=person)(objectClass=user)(mail=*))"
    # Grupo AD cuyos miembros reciben copia como "admins" (además de NOTIFY_ADMIN_EMAILS).
    AD_ADMIN_GROUP: str = ""
    AD_TIMEOUT_SECONDS: int = 10
    AD_GROUP_CACHE_SECONDS: int = 600
    # 0 = sin sincronización automática (solo manual desde la UI/API).
    AD_SYNC_INTERVAL_MINUTES: int = 0
    # Desactivar personas deshabilitadas/eliminadas en AD (si no tienen activos).
    AD_SYNC_DEACTIVATE: bool = True
    AD_DEFAULT_DEPARTMENT: str = "Sin departamento"
    AD_DEFAULT_CARGO: str = "Sin cargo"

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
    def _session_timeouts_coherent(self) -> "Settings":
        """
        El refresh (inactividad) debe durar más que el access; si no, expiraría
        antes de poder usarse. En producción es un error de configuración; en
        desarrollo se ajusta al doble del access para no bloquear el arranque.
        """
        if self.SESSION_IDLE_TIMEOUT_MINUTES <= self.ACCESS_TOKEN_EXPIRE_MINUTES:
            if self.ENVIRONMENT == "production":
                raise ValueError(
                    "SESSION_IDLE_TIMEOUT_MINUTES debe ser mayor que ACCESS_TOKEN_EXPIRE_MINUTES "
                    "(si no, el refresh expira antes de poder usarse)."
                )
            self.SESSION_IDLE_TIMEOUT_MINUTES = self.ACCESS_TOKEN_EXPIRE_MINUTES * 2
        return self

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
                    "REDIS_URL sin AUTH en producción. Use redis://:<password>@host:port/db"
                )
        if self.STORAGE_BACKEND == "s3" and (
            not self.S3_ACCESS_KEY or not self.S3_SECRET_KEY or not self.S3_BUCKET
        ):
            raise ValueError(
                "S3_ACCESS_KEY, S3_SECRET_KEY y S3_BUCKET son obligatorios "
                "cuando STORAGE_BACKEND=s3"
            )
        return self

    # =========================================================================
    # DATABASE URI
    # =========================================================================
    def _postgres_uri(self, user: str, password: str, server: str, port: int, db: str) -> str:
        encoded_password = quote_plus(password)
        return f"postgresql+psycopg://{user}:{encoded_password}@{server}:{port}/{db}"

    def _normalize_dsn(self, dsn: str) -> str:
        """Normaliza DSN comunes al driver async elegido por SQLAlchemy."""
        replacements = {
            "postgresql://": "postgresql+psycopg://",
            "postgres://": "postgresql+psycopg://",
            "mysql://": "mysql+asyncmy://",
            "oracle://": "oracle+oracledb_async://",
            "oracle+oracledb://": "oracle+oracledb_async://",
        }
        for prefix, async_prefix in replacements.items():
            if dsn.startswith(prefix):
                return async_prefix + dsn[len(prefix):]
        return dsn

    @property
    def SQLALCHEMY_DATABASE_URI(self) -> str:
        if self.DB_WRITE_DSN:
            return self._normalize_dsn(self.DB_WRITE_DSN)
        if self.DB_ENGINE == "sqlite" or self.POSTGRES_SERVER == "sqlite":
            return "sqlite+aiosqlite:///./inventario.db"
        if self.DB_ENGINE != "postgres":
            raise ValueError(
                f"DB_WRITE_DSN es obligatorio cuando DB_ENGINE={self.DB_ENGINE}"
            )

        return self._postgres_uri(
            self.POSTGRES_USER,
            self.POSTGRES_PASSWORD,
            self.DB_WRITE_HOST or self.POSTGRES_SERVER,
            self.POSTGRES_PORT,
            self.POSTGRES_DB,
        )

    @property
    def SQLALCHEMY_READ_DATABASE_URI(self) -> str:
        if not self.HAS_READ_REPLICA:
            return self.SQLALCHEMY_DATABASE_URI
        if self.DB_READ_DSN:
            return self._normalize_dsn(self.DB_READ_DSN)
        if self.DB_ENGINE != "postgres":
            raise ValueError(
                f"DB_READ_DSN es obligatorio para réplica cuando DB_ENGINE={self.DB_ENGINE}"
            )

        return self._postgres_uri(
            self.POSTGRES_REPLICA_USER or self.POSTGRES_USER,
            self.POSTGRES_REPLICA_PASSWORD or self.POSTGRES_PASSWORD,
            self.DB_READ_HOST or self.POSTGRES_REPLICA_SERVER or self.DB_WRITE_HOST or self.POSTGRES_SERVER,
            self.POSTGRES_REPLICA_PORT,
            self.POSTGRES_REPLICA_DB or self.POSTGRES_DB,
        )

    @property
    def HAS_READ_REPLICA(self) -> bool:
        return (
            not self.IS_SQLITE
            and bool(self.DB_READ_DSN or self.DB_READ_HOST or self.POSTGRES_REPLICA_SERVER)
        )

    @property
    def IS_PRODUCTION(self) -> bool:
        return self.ENVIRONMENT == "production"

    @property
    def IS_SQLITE(self) -> bool:
        return self.DB_ENGINE == "sqlite" or self.POSTGRES_SERVER == "sqlite"

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="ignore",
    )


settings = Settings()
