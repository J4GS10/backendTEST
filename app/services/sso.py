"""Autenticacion SSO OIDC para Microsoft Entra ID y Google Workspace."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, urlparse
import secrets

import httpx
from fastapi import HTTPException
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.transactional import transactional
from app.models.organization import Usuario
from app.repositories.governance import GovernanceRepository
from app.repositories.organization import UsuarioRepository


@dataclass(frozen=True)
class OIDCProvider:
    name: str
    label: str
    client_id: str
    client_secret: str
    redirect_uri: str
    discovery_url: str


class SSOService:
    STATE_TTL_MINUTES = 10

    def __init__(self, db: AsyncSession):
        self.db = db
        self.user_repo = UsuarioRepository(db)
        self.gov_repo = GovernanceRepository(db)

    def configured_providers(self) -> list[dict[str, str]]:
        providers: list[dict[str, str]] = []
        for provider in ("microsoft", "google"):
            try:
                cfg = self._provider(provider)
            except HTTPException:
                continue
            providers.append({"provider": cfg.name, "label": cfg.label})
        return providers if settings.SSO_ENABLED else []

    def build_authorization_url(self, provider: str, return_to: str | None = None) -> str:
        cfg = self._provider(provider)
        nonce = secrets.token_urlsafe(24)
        state = self._encode_state(cfg.name, nonce, self._safe_return_to(return_to))
        discovery = self._static_discovery(cfg)
        params = {
            "client_id": cfg.client_id,
            "response_type": "code",
            "redirect_uri": cfg.redirect_uri,
            "scope": "openid email profile",
            "state": state,
            "nonce": nonce,
            "prompt": "select_account",
        }
        return f"{discovery['authorization_endpoint']}?{urlencode(params)}"

    async def authenticate_callback(
        self,
        provider: str,
        *,
        code: str,
        state: str,
        ip: str | None,
        user_agent: str | None,
    ) -> tuple[Usuario, str]:
        cfg = self._provider(provider)
        state_payload = self._decode_state(state, cfg.name)
        discovery = await self._fetch_discovery(cfg)
        token_payload = await self._exchange_code(cfg, discovery, code)
        claims = await self._verify_id_token(
            cfg,
            discovery,
            token_payload.get("id_token"),
            expected_nonce=state_payload["nonce"],
        )
        email = self._extract_email(cfg.name, claims)
        self._validate_domain(email)

        user = await self.user_repo.get_by_persona_email(email)
        if not user:
            await self._audit_failed(cfg.name, email, "user_not_found", ip, user_agent)
            raise HTTPException(403, detail="SSO_USER_NOT_AUTHORIZED")
        if not user.USU_Estado or not user.persona or not user.persona.PER_Estado:
            await self._audit_failed(cfg.name, email, "inactive_user", ip, user_agent, user)
            raise HTTPException(403, detail="SSO_USER_NOT_AUTHORIZED")
        if not user.USU_SSO_Habilitado:
            await self._audit_failed(cfg.name, email, "sso_disabled_for_user", ip, user_agent, user)
            raise HTTPException(403, detail="SSO_NOT_ENABLED_FOR_USER")
        if user.USU_SSO_Provider and user.USU_SSO_Provider != cfg.name:
            await self._audit_failed(cfg.name, email, "provider_mismatch", ip, user_agent, user)
            raise HTTPException(403, detail="SSO_PROVIDER_NOT_ALLOWED_FOR_USER")

        await self._record_successful_login(user, cfg.name, ip, user_agent)
        return user, state_payload["return_to"]

    @transactional
    async def _record_successful_login(
        self, user: Usuario, provider: str, ip: str | None, user_agent: str | None
    ) -> None:
        """Persist the successful SSO login as one service-owned transaction."""
        user.USU_Ultimo_Login = datetime.now(timezone.utc).replace(tzinfo=None)
        await self.gov_repo.create_audit_log(
            accion="LOGIN_SUCCESS",
            entidad="INV_USUARIO",
            snapshot={"username": user.USU_Username, "rol": user.USU_Rol, "sso": provider},
            usuario_id=user.USU_Usuario,
            ip_origen=ip,
            user_agent=user_agent,
        )

    def _provider(self, provider: str) -> OIDCProvider:
        if not settings.SSO_ENABLED:
            raise HTTPException(400, detail="SSO_DISABLED")
        if provider == "microsoft":
            tenant = settings.SSO_MICROSOFT_TENANT.strip() or "organizations"
            return self._require_provider(
                OIDCProvider(
                    name="microsoft",
                    label="Microsoft 365",
                    client_id=settings.SSO_MICROSOFT_CLIENT_ID or "",
                    client_secret=settings.SSO_MICROSOFT_CLIENT_SECRET or "",
                    redirect_uri=settings.SSO_MICROSOFT_REDIRECT_URI or "",
                    discovery_url=(
                        f"https://login.microsoftonline.com/{tenant}"
                        "/v2.0/.well-known/openid-configuration"
                    ),
                )
            )
        if provider == "google":
            return self._require_provider(
                OIDCProvider(
                    name="google",
                    label="Google Workspace",
                    client_id=settings.SSO_GOOGLE_CLIENT_ID or "",
                    client_secret=settings.SSO_GOOGLE_CLIENT_SECRET or "",
                    redirect_uri=settings.SSO_GOOGLE_REDIRECT_URI or "",
                    discovery_url="https://accounts.google.com/.well-known/openid-configuration",
                )
            )
        raise HTTPException(404, detail="SSO_PROVIDER_NOT_SUPPORTED")

    @staticmethod
    def _require_provider(cfg: OIDCProvider) -> OIDCProvider:
        if not cfg.client_id or not cfg.client_secret or not cfg.redirect_uri:
            raise HTTPException(400, detail="SSO_PROVIDER_NOT_CONFIGURED")
        return cfg

    @staticmethod
    def _static_discovery(cfg: OIDCProvider) -> dict[str, str]:
        if cfg.name == "microsoft":
            base = cfg.discovery_url.split("/v2.0/.well-known", 1)[0]
            return {"authorization_endpoint": f"{base}/oauth2/v2.0/authorize"}
        return {"authorization_endpoint": "https://accounts.google.com/o/oauth2/v2/auth"}

    async def _fetch_discovery(self, cfg: OIDCProvider) -> dict:
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                response = await client.get(cfg.discovery_url)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPError as exc:
            raise HTTPException(502, detail="SSO_DISCOVERY_UNAVAILABLE") from exc

    async def _exchange_code(self, cfg: OIDCProvider, discovery: dict, code: str) -> dict:
        token_endpoint = discovery.get("token_endpoint")
        if not token_endpoint:
            raise HTTPException(502, detail="SSO_DISCOVERY_INVALID")
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": cfg.redirect_uri,
            "client_id": cfg.client_id,
            "client_secret": cfg.client_secret,
        }
        async with httpx.AsyncClient(timeout=12.0) as client:
            response = await client.post(token_endpoint, data=data)
            if response.status_code >= 400:
                raise HTTPException(401, detail="SSO_CODE_EXCHANGE_FAILED")
            return response.json()

    async def _verify_id_token(
        self,
        cfg: OIDCProvider,
        discovery: dict,
        id_token: str | None,
        *,
        expected_nonce: str,
    ) -> dict:
        if not id_token:
            raise HTTPException(401, detail="SSO_ID_TOKEN_MISSING")
        jwks_uri = discovery.get("jwks_uri")
        if not jwks_uri:
            raise HTTPException(502, detail="SSO_DISCOVERY_INVALID")
        header = jwt.get_unverified_header(id_token)
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                jwks_response = await client.get(jwks_uri)
                jwks_response.raise_for_status()
                jwks = jwks_response.json()
        except httpx.HTTPError as exc:
            raise HTTPException(502, detail="SSO_JWKS_UNAVAILABLE") from exc
        key = next((item for item in jwks.get("keys", []) if item.get("kid") == header.get("kid")), None)
        if not key:
            raise HTTPException(401, detail="SSO_SIGNING_KEY_NOT_FOUND")

        options = {"verify_at_hash": False}
        issuer = discovery.get("issuer")
        decode_kwargs = {
            "key": key,
            "algorithms": [header.get("alg", "RS256")],
            "audience": cfg.client_id,
            "options": options,
        }
        if cfg.name == "microsoft" and settings.SSO_MICROSOFT_TENANT in {"common", "organizations", "consumers"}:
            options["verify_iss"] = False
        elif issuer:
            decode_kwargs["issuer"] = issuer

        try:
            claims = jwt.decode(id_token, **decode_kwargs)
        except JWTError as exc:
            raise HTTPException(401, detail="SSO_ID_TOKEN_INVALID") from exc

        if claims.get("nonce") != expected_nonce:
            raise HTTPException(401, detail="SSO_NONCE_INVALID")
        if cfg.name == "google" and claims.get("iss") not in {
            "https://accounts.google.com",
            "accounts.google.com",
        }:
            raise HTTPException(401, detail="SSO_ID_TOKEN_INVALID")
        if claims.get("email_verified") is False:
            raise HTTPException(403, detail="SSO_EMAIL_NOT_VERIFIED")
        return claims

    def _encode_state(self, provider: str, nonce: str, return_to: str) -> str:
        now = datetime.now(timezone.utc)
        payload = {
            "type": "sso_state",
            "provider": provider,
            "nonce": nonce,
            "return_to": return_to,
            "iat": now,
            "exp": now + timedelta(minutes=self.STATE_TTL_MINUTES),
        }
        return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

    @staticmethod
    def _decode_state(state: str, provider: str) -> dict:
        try:
            payload = jwt.decode(state, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        except JWTError as exc:
            raise HTTPException(401, detail="SSO_STATE_INVALID") from exc
        if payload.get("type") != "sso_state" or payload.get("provider") != provider:
            raise HTTPException(401, detail="SSO_STATE_INVALID")
        return payload

    @staticmethod
    def _safe_return_to(return_to: str | None) -> str:
        default = f"{settings.FRONTEND_BASE_URL.rstrip('/')}/sso/callback"
        if not return_to:
            return default
        try:
            allowed = urlparse(settings.FRONTEND_BASE_URL.rstrip("/"))
            candidate = urlparse(return_to)
        except ValueError:
            return default

        allowed_origin = (allowed.scheme, allowed.netloc)
        candidate_origin = (candidate.scheme, candidate.netloc)
        if candidate_origin != allowed_origin:
            return default
        if candidate.scheme not in {"http", "https"}:
            return default
        return return_to

    @staticmethod
    def _extract_email(provider: str, claims: dict) -> str:
        email = claims.get("email")
        if provider == "microsoft":
            email = email or claims.get("preferred_username") or claims.get("upn")
        if not isinstance(email, str) or "@" not in email:
            raise HTTPException(403, detail="SSO_EMAIL_MISSING")
        return email.strip().lower()

    @staticmethod
    def _validate_domain(email: str) -> None:
        allowed = {
            domain.strip().lower()
            for domain in settings.SSO_ALLOWED_EMAIL_DOMAINS.split(",")
            if domain.strip()
        }
        if not allowed:
            return
        domain = email.rsplit("@", 1)[-1].lower()
        if domain not in allowed:
            raise HTTPException(403, detail="SSO_EMAIL_DOMAIN_NOT_ALLOWED")

    @transactional
    async def _audit_failed(
        self,
        provider: str,
        email: str,
        reason: str,
        ip: str | None,
        user_agent: str | None,
        user: Usuario | None = None,
    ) -> None:
        await self.gov_repo.create_audit_log(
            accion="LOGIN_FAILED",
            entidad="INV_USUARIO",
            snapshot={"provider": provider, "email": email, "reason": reason},
            usuario_id=user.USU_Usuario if user else None,
            ip_origen=ip,
            user_agent=user_agent,
        )
