"""DTOs de Active Directory y reglas de notificación."""
from __future__ import annotations

from typing import Optional

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.common import CorporateEmail


class SyncPendiente(BaseModel):
    persona_id: str
    nombre: str
    email: str
    activos: int


class SyncError(BaseModel):
    email: Optional[str] = None
    detalle: str


class SyncResult(BaseModel):
    fecha: str
    dry_run: bool
    total_ad: int
    creados: int
    actualizados: int
    vinculados: int
    desactivados: int
    reactivados: int
    jefes_asignados: int
    pendientes_con_activos: list[SyncPendiente]
    errores: list[SyncError]


class DirectoryStatus(BaseModel):
    enabled: bool
    configured: bool
    server: Optional[str] = None
    base_dn: Optional[str] = None
    admin_group: Optional[str] = None
    sync_interval_minutes: int
    last_sync: Optional[SyncResult] = None


class ConnectionTest(BaseModel):
    ok: bool
    message: str
    usuarios_encontrados: int = 0


class GroupOut(BaseModel):
    nombre: str
    dn: str


class ReglaBase(BaseModel):
    activa: bool = True
    notificar_afectado: bool = True
    notificar_jefe: bool = False
    copiar_admins: bool = True
    grupos_ad: list[str] = Field(default_factory=list, max_length=20)
    correos_extra: list[CorporateEmail] = Field(default_factory=list, max_length=30)


class ReglaUpdate(ReglaBase):
    pass


class ReglaOut(ReglaBase):
    evento: str
    correos_extra: list[str] = Field(default_factory=list)
    personalizada: bool = False


class DestinatarioOut(BaseModel):
    email: str
    origen: str


class VistaPrevia(BaseModel):
    destinatarios: list[str]
    detalle: list[DestinatarioOut]


# ================= Cuenta de servicio (correo + AD) =================
class IntegracionBase(BaseModel):
    modo: Literal["DESACTIVADO", "CORREO", "CORREO_AD"] = "DESACTIVADO"
    proveedor: Literal["SMTP", "GRAPH"] = "SMTP"
    cuenta_email: Optional[CorporateEmail] = None
    cuenta_usuario: Optional[str] = Field(None, max_length=150)
    nombre_remitente: Optional[str] = Field(None, max_length=100)
    smtp_host: Optional[str] = Field(None, max_length=150)
    smtp_puerto: int = Field(587, ge=1, le=65535)
    smtp_seguridad: Literal["STARTTLS", "SSL", "NINGUNA"] = "STARTTLS"
    graph_tenant_id: Optional[str] = Field(None, max_length=100)
    graph_client_id: Optional[str] = Field(None, max_length=100)
    ad_servidor: Optional[str] = Field(None, max_length=300)
    ad_base_dn: Optional[str] = Field(None, max_length=300)
    ad_grupo_base_dn: Optional[str] = Field(None, max_length=300)
    ad_grupo_admin: Optional[str] = Field(None, max_length=150)
    ad_start_tls: bool = False
    ad_verificar_cert: bool = True
    ad_intervalo_min: int = Field(0, ge=0, le=10080)
    ad_desactivar: bool = True
    ad_usar_cuenta_servicio: bool = True
    ad_bind_usuario: Optional[str] = Field(None, max_length=150)


class IntegracionUpdate(IntegracionBase):
    """Secretos: omitido/None = conservar el guardado; "" = borrarlo."""
    cuenta_password: Optional[str] = Field(None, max_length=500)
    graph_client_secret: Optional[str] = Field(None, max_length=500)
    ad_bind_password: Optional[str] = Field(None, max_length=500)

    @model_validator(mode="after")
    def _requeridos(self):
        if self.modo == "DESACTIVADO":
            return self
        if not self.cuenta_email:
            raise ValueError("CUENTA_EMAIL_REQUERIDA")
        if self.proveedor == "SMTP" and not self.smtp_host:
            raise ValueError("SMTP_HOST_REQUERIDO")
        if self.proveedor == "GRAPH" and not (self.graph_tenant_id and self.graph_client_id):
            raise ValueError("GRAPH_TENANT_Y_CLIENT_REQUERIDOS")
        if self.modo == "CORREO_AD":
            if not (self.ad_servidor and self.ad_base_dn):
                raise ValueError("AD_SERVIDOR_Y_BASE_DN_REQUERIDOS")
            if not all(u.strip().lower().startswith(("ldap://", "ldaps://")) for u in self.ad_servidor.split(",") if u.strip()):
                raise ValueError("AD_SERVIDOR_DEBE_SER_LDAP_O_LDAPS")
            if not self.ad_usar_cuenta_servicio and not self.ad_bind_usuario:
                raise ValueError("AD_BIND_USUARIO_REQUERIDO")
        return self


class Bloqueo(BaseModel):
    smtp_hasta: Optional[str] = None
    ad_hasta: Optional[str] = None


class IntegracionOut(IntegracionBase):
    cuenta_email: Optional[str] = None
    origen: Literal["interfaz", "entorno"]
    password_configurada: bool
    graph_secret_configurado: bool
    ad_bind_password_configurada: bool
    bloqueo: Bloqueo
    cifrado_ok: bool


class ProbarCorreoIn(BaseModel):
    config: IntegracionUpdate
    destinatario: CorporateEmail


class ProbarAdIn(BaseModel):
    config: IntegracionUpdate


class ResultadoPrueba(BaseModel):
    ok: bool
    codigo: str
    mensaje: str = ""
    usuarios_encontrados: int = 0

