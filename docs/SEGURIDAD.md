# Seguridad

Resumen del modelo de seguridad. Detalle operativo en `../SECURITY.md` y la matriz de
permisos en `RBAC_MATRIX.md`.

## Autenticación (JWT)

- **OAuth2 password flow.** `POST /login/access-token` (form-urlencoded) devuelve el
  access token (JWT, HS256, ~30 min) con claims `sub`, `role`, `type`, `jti`, `iat`, `exp`.
- **Refresh token** en **cookie HttpOnly + Secure + SameSite=Strict** (`Path=/api/v1/login`),
  inaccesible desde JS. Rotación con detección de reuso: cada refresh revoca el `jti`
  anterior; reusar uno viejo → 401 `TOKEN_REVOKED`.
- **Revocación**: lista de `jti` revocados en BD + caché Redis (TTL corto). El logout y el
  cambio de contraseña revocan tokens; la revocación global se valida en cada request.
- **Anti-enumeración**: hash dummy de tiempo constante + respuesta uniforme en login.

## Autorización (RBAC)

4 roles con inclusión jerárquica:

| Rol | Alcance |
|---|---|
| `SUPER_ADMIN` | Total. Único con auditoría, configuración global y reset de MFA ajeno |
| `ADMIN_TI` | Gestión completa de inventario, catálogos, personas, usuarios, compras |
| `TECNICO` | Operación de campo: activos, especificaciones, movimientos, mantenimientos |
| `CONSULTA` | Solo lectura |

Implementación: `RoleChecker` en `app/api/deps.py` (`require_super_admin`, `require_admin`,
`require_operativo`) aplicado por `dependencies=[...]`. **Invariante verificado**: 0
endpoints mutadores sin guard de rol (`scripts/check_rbac.py`, apto para CI).

## 2FA / MFA

- **TOTP** (RFC 6238, pyotp): secreto cifrado (Fernet) en BD; QR de enrolamiento.
- **Email-OTP**: código de 6 dígitos, un solo uso, expira.
- **Recovery codes**: 8 códigos de un solo uso (hash en BD).
- **Obligatorio** para `SUPER_ADMIN` y `ADMIN_TI` (`TWO_FACTOR_REQUIRED_ROLES`).
- **Login 2FA**: password → `challenge_token` → `POST /login/2fa/verify`.
- **Reset administrativo**: `POST /org/usuarios/{id}/2fa/reset` (solo SUPER_ADMIN) limpia
  2FA + recovery + OTPs cuando un empleado pierde su segundo factor.

## Endurecimiento

- **Account lockout**: tras N intentos fallidos, bloqueo temporal.
- **Política de contraseña**: longitud mínima, mayús/minús/dígito, rechazo de comunes y de
  contraseñas que contengan el usuario. `USU_Password` acotado (anti-DoS de bcrypt).
- **Rate-limiting**: login 5/min, default configurable; clave de IP a prueba de spoofing
  (X-Real-IP › último hop de XFF). PII y endpoints sensibles con límites propios.
- **Auditoría append-only**: `INV_AUDITORIA_SISTEMA` con trigger que rechaza UPDATE/DELETE
  a nivel BD; registra acción, entidad, snapshot JSON, IP real y user-agent. Incluye
  `LOGIN_SUCCESS/FAILED`, `ACCOUNT_LOCKED`, `LOGOUT`, `2FA_RESET_BY_ADMIN`, etc.
- **Cifrado de campos**: claves de activación de licencia con Fernet/MultiFernet (rotación
  sin downtime); falla cerrado en producción ante token inválido.
- **Integridad transaccional**: `IntegrityError → 409` uniforme; flujos críticos
  (asignación, devolución, recepción de orden, offboarding) atómicos y *fail-closed* ante
  estado canónico faltante.
- **Validación de entrada**: schemas Pydantic con longitudes/rangos alineados a la BD
  (entrada inválida → 422 limpio, no 500).

## Cabeceras y transporte

- Caddy: TLS automático; `/metrics` y `/health/full` bloqueados en el edge.
- Nginx (frontend): CSP restrictiva, `X-Content-Type-Options`, `X-Frame-Options: DENY`,
  `Referrer-Policy`, `Permissions-Policy`, COOP/CORP.
- Backend: HSTS en producción; CORS con `allow_credentials=False` (Bearer, no cookies de
  sesión vulnerables a CSRF).

## Infraestructura

- Contenedor backend no-root (uid 1001), `cap_drop: ALL`, `no-new-privileges`, límites de
  recursos.
- Secretos en `.env` (gitignored); en producción mover a Vault/SOPS/docker secrets y rotar
  `SECRET_KEY`, `FIELD_ENCRYPTION_KEY` y contraseñas demo.
