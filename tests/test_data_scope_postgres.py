"""
RLS de PostgreSQL (segunda capa del alcance por sede).

Estos tests APAGAN a propósito el filtro de la aplicación (`skip_data_scope`)
para demostrar que la base, por sí sola, limita lo que ve y escribe un usuario
aunque la conexión sea de un superusuario.
"""
from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError

from app.core.data_scope import scope_for_user, user_scope
from app.core.security import get_password_hash
from app.models.core import Activo
from app.models.governance import AuditoriaSistema
from app.models.organization import Persona, Usuario, UsuarioSede
from tests.conftest import crear_sede

RAW = {"skip_data_scope": True}


@pytest.fixture
async def escenario(session, domain_seed):
    sede_a = domain_seed["sede"]
    b = await crear_sede(session, "Sede B")
    await session.execute(update(Activo).values(SED_Sede=sede_a))
    await session.execute(update(Persona).values(SED_Sede=sede_a))
    act_b = Activo(ACT_Codigo_Interno="LAP-B01", ACT_Serie_Fabricante="SER-B01", ACT_Fecha_Compra=date(2024, 3, 1),
                   MOD_Modelo=domain_seed["mod"], TAC_Tipo_Activo=domain_seed["tac_lap"],
                   EOP_Estado_Operativo=domain_seed["eop_disp"], SED_Sede=b["sede"])
    session.add(act_b)
    ref = (await session.execute(select(Persona))).scalars().first()
    per = Persona(PER_Primer_Nombre="Tec", PER_Primer_Apellido="RLS", PER_Email_Corporativo="tec.rls@empresa.local",
                  DEP_Departamento=ref.DEP_Departamento, CAR_Cargo=ref.CAR_Cargo, SED_Sede=sede_a)
    session.add(per)
    await session.flush()
    tec = Usuario(USU_Username="tec_rls", USU_Password_Hash=get_password_hash("Kx7!Rls#Q"), USU_Rol="TECNICO",
                  PER_Persona=per.PER_Persona)
    session.add(tec)
    await session.flush()
    session.add(UsuarioSede(USU_Usuario=tec.USU_Usuario, SED_Sede=sede_a))
    await session.commit()
    tec = (await session.execute(select(Usuario).where(Usuario.USU_Usuario == tec.USU_Usuario))).scalar_one()
    return {**domain_seed, "sede_a": sede_a, "sede_b": b["sede"], "area_b": b["area"],
            "tec": tec, "act_b": act_b.ACT_Activo}


@pytest.mark.asyncio
async def test_la_base_filtra_sin_la_capa_de_aplicacion(engine, escenario):
    from sqlalchemy.ext.asyncio import AsyncSession
    scope = scope_for_user(escenario["tec"])
    async with AsyncSession(engine) as s:
        with user_scope(scope):
            rol = (await s.execute(text("SELECT current_user"))).scalar_one()
            assert rol == "inventario_rls"
            codigos = set((await s.execute(
                select(Activo.ACT_Codigo_Interno).execution_options(**RAW))).scalars())
            assert codigos == {"LAP-001", "LAP-002"}
            total_raw = (await s.execute(text('SELECT count(*) FROM "INV_ACTIVO"'))).scalar_one()
            assert total_raw == 2  # ni siquiera SQL crudo ve la sede B
            await s.rollback()


@pytest.mark.asyncio
async def test_la_base_rechaza_escrituras_fuera_del_alcance(engine, escenario):
    from sqlalchemy.ext.asyncio import AsyncSession
    scope = scope_for_user(escenario["tec"])
    async with AsyncSession(engine) as s:
        with user_scope(scope):
            s.add(Activo(ACT_Codigo_Interno="LAP-X", ACT_Serie_Fabricante="SER-X", ACT_Fecha_Compra=date(2025, 1, 1),
                         MOD_Modelo=escenario["mod"], TAC_Tipo_Activo=escenario["tac_lap"],
                         EOP_Estado_Operativo=escenario["eop_disp"], SED_Sede=escenario["sede_b"]))
            with pytest.raises(DBAPIError) as exc:
                await s.flush()
            assert "row-level security" in str(exc.value)
            await s.rollback()
        with user_scope(scope):
            # Mover un activo propio a la sede B tampoco pasa el WITH CHECK.
            with pytest.raises(DBAPIError):
                await s.execute(
                    update(Activo).where(Activo.ACT_Codigo_Interno == "LAP-001")
                    .values(SED_Sede=escenario["sede_b"]).execution_options(**RAW)
                )
            await s.rollback()
        with user_scope(scope):
            # Un UPDATE sobre filas de B no las encuentra (0 filas afectadas).
            r = await s.execute(
                update(Activo).where(Activo.ACT_Activo == escenario["act_b"])
                .values(ACT_Hostname="hackeado").execution_options(**RAW, synchronize_session=False)
            )
            assert r.rowcount == 0
            await s.rollback()


@pytest.mark.asyncio
async def test_bitacora_inmutable_para_peticiones(engine, escenario):
    from sqlalchemy.ext.asyncio import AsyncSession
    scope = scope_for_user(escenario["tec"])
    async with AsyncSession(engine) as s:
        with user_scope(scope):
            s.add(AuditoriaSistema(AUD_Accion="LOGIN_SUCCESS", AUD_Entidad_Afectada="INV_USUARIO",
                                   USU_Usuario=escenario["tec"].USU_Usuario))
            await s.flush()  # insertar siempre se permite
            with pytest.raises(DBAPIError):
                await s.execute(text('DELETE FROM "INV_AUDITORIA_SISTEMA"'))
            await s.rollback()


@pytest.mark.asyncio
async def test_sin_usuario_en_la_transaccion_no_ve_nada(engine, escenario):
    from sqlalchemy.ext.asyncio import AsyncSession
    async with AsyncSession(engine) as s:
        await s.execute(text('SET LOCAL ROLE "inventario_rls"'))
        assert (await s.execute(text('SELECT count(*) FROM "INV_ACTIVO"'))).scalar_one() == 0
        await s.rollback()


@pytest.mark.asyncio
async def test_modo_sistema_ve_todo(engine, escenario):
    from sqlalchemy.ext.asyncio import AsyncSession
    async with AsyncSession(engine) as s:
        total = (await s.execute(select(func.count()).select_from(Activo))).scalar_one()
        assert total == 3
