from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import date, timedelta

import httpx
from sqlalchemy import select, text

from app.core import security
from app.db.session import SessionLocal, engine, read_engine
from app.models.catalogs import EstadoOperativo, Modelo, TipoActivo, TipoEspecificacion
from app.models.location import Area
from app.models.organization import Cargo, Departamento, Persona, Usuario
from app.models.traceability import TipoMantenimiento, TipoMovimiento


BASE = "http://127.0.0.1:8000"
API = f"{BASE}/api/v1"
SUFFIX = str(int(time.time()))[-8:]

results: list[dict] = []
ids: dict[str, str] = {}


def add(label: str, method: str, path: str, status, ok: bool, expected, note: str = "") -> None:
    if isinstance(expected, (tuple, list, set)):
        exp = list(expected)
    else:
        exp = [expected]
    results.append(
        {
            "label": label,
            "method": method,
            "path": path,
            "status": status,
            "ok": bool(ok),
            "expected": exp,
            "note": note,
        }
    )


async def get_context() -> dict:
    async with SessionLocal() as db:
        user = (
            await db.execute(
                select(Usuario)
                .where(Usuario.USU_Estado.is_(True), Usuario.USU_Rol == "SUPER_ADMIN")
                .limit(1)
            )
        ).scalar_one_or_none()
        if not user:
            user = (
                await db.execute(
                    select(Usuario)
                    .where(Usuario.USU_Estado.is_(True), Usuario.USU_Rol == "ADMIN_TI")
                    .limit(1)
                )
            ).scalar_one_or_none()
        if not user:
            user = (
                await db.execute(select(Usuario).where(Usuario.USU_Estado.is_(True)).limit(1))
            ).scalar_one_or_none()
        if not user:
            raise RuntimeError("NO_ACTIVE_USER_FOR_AUDIT")

        modelo = (await db.execute(select(Modelo).limit(1))).scalar_one_or_none()
        tipo = (await db.execute(select(TipoActivo).limit(1))).scalar_one_or_none()
        estado = (
            await db.execute(
                select(EstadoOperativo)
                .where(EstadoOperativo.EOP_Nombre.ilike("%Bodega%"))
                .limit(1)
            )
        ).scalar_one_or_none()
        if not estado:
            estado = (
                await db.execute(
                    select(EstadoOperativo)
                    .where(EstadoOperativo.EOP_Nombre.ilike("%Disponible%"))
                    .limit(1)
                )
            ).scalar_one_or_none()
        specs = (await db.execute(select(TipoEspecificacion).limit(3))).scalars().all()
        area = (await db.execute(select(Area).limit(1))).scalar_one_or_none()
        personas = (
            await db.execute(select(Persona).where(Persona.PER_Estado.is_(True)).limit(3))
        ).scalars().all()
        dep = (
            await db.execute(
                select(Departamento).where(Departamento.DEP_Activo.is_(True)).limit(1)
            )
        ).scalar_one_or_none()
        cargo = (await db.execute(select(Cargo).limit(1))).scalar_one_or_none()
        mov_tipo = (
            await db.execute(
                select(TipoMovimiento).where(TipoMovimiento.TMO_Nombre.ilike("%asign%")).limit(1)
            )
        ).scalar_one_or_none()
        mant_tipo = (await db.execute(select(TipoMantenimiento).limit(1))).scalar_one_or_none()

        required = {
            "modelo": modelo,
            "tipo_activo": tipo,
            "estado_disponible_bodega": estado,
            "tipo_especificacion": specs[0] if specs else None,
            "area": area,
            "persona": personas[0] if personas else None,
            "departamento": dep,
            "cargo": cargo,
            "tipo_movimiento_asignacion": mov_tipo,
            "tipo_mantenimiento": mant_tipo,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise RuntimeError("MISSING_BASE_DATA:" + ",".join(missing))

        return {
            "user": {
                "id": str(user.USU_Usuario),
                "username": user.USU_Username,
                "role": user.USU_Rol,
            },
            "token": security.create_access_token(user.USU_Username, user.USU_Rol),
            "modelo": modelo.MOD_Modelo,
            "tipo_activo": modelo.TAC_Tipo_Activo or tipo.TAC_Tipo_Activo,
            "estado": estado.EOP_Estado_Operativo,
            "specs": [s.TES_Tipo_Especificacion for s in specs],
            "area": area.ARE_Area,
            "persona": str(personas[0].PER_Persona),
            "persona2": str(personas[1].PER_Persona) if len(personas) > 1 else None,
            "dep": dep.DEP_Departamento,
            "cargo": cargo.CAR_Cargo,
            "mov_tipo": mov_tipo.TMO_Tipo_Movimiento,
            "mant_tipo": mant_tipo.TMA_Tipo_Mantenimiento,
        }


async def req(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    *,
    label: str | None = None,
    expected=(200,),
    headers: dict | None = None,
    **kwargs,
):
    url = path if path.startswith("http") else API + path
    req_headers = dict(headers or {})
    req_headers.setdefault("X-Request-ID", "qa-" + uuid.uuid4().hex[:12])
    try:
        response = await client.request(method, url, headers=req_headers, **kwargs)
        ok = response.status_code in expected
        note = ""
        if not ok:
            try:
                payload = response.json()
                if isinstance(payload, dict) and payload.get("detail"):
                    note = str(payload["detail"])[:160]
            except Exception:
                note = response.text[:160]
        add(label or path, method, path, response.status_code, ok, expected, note)
        try:
            return response, response.json()
        except Exception:
            return response, None
    except Exception as exc:  # noqa: BLE001
        add(label or path, method, path, "EXC", False, expected, f"{type(exc).__name__}:{exc}"[:180])
        return None, None


async def check_public_and_catalogs(client: httpx.AsyncClient, auth: dict) -> None:
    await req(client, "GET", f"{BASE}/health", label="health", expected=(200,))
    await req(client, "GET", f"{BASE}/health/full", label="health/full", expected=(200,))
    await req(client, "GET", f"{BASE}/metrics", label="metrics", expected=(200,))
    await req(client, "GET", "/login/sso/providers", label="sso providers", expected=(200,))
    await req(client, "GET", "/core/activos", label="protected without token", expected=(401,))
    await req(client, "GET", "/me", label="me", headers=auth)
    await req(client, "GET", "/me/2fa", label="me 2fa status", headers=auth)

    for path in (
        "/cat/tipos-activo",
        "/cat/marcas",
        "/cat/tipos-conexion",
        "/cat/modelos-flat",
        "/cat/estados-operativos",
        "/cat/tipos-especificacion",
    ):
        await req(client, "GET", path, label=f"read {path}", headers=auth)

    catalog_tests = [
        (
            "/cat/marcas",
            "MAR_Marca",
            {"MAR_Nombre": f"QA Marca {SUFFIX}"},
            {"MAR_Nombre": f"QA Marca {SUFFIX} v2"},
            "cat marca",
        ),
        (
            "/cat/tipos-activo",
            "TAC_Tipo_Activo",
            {"TAC_Nombre": f"QA Tipo {SUFFIX}", "TAC_Prefijo": "QAT", "TAC_Aplica_Depreciacion": False},
            {"TAC_Nombre": f"QA Tipo {SUFFIX} v2"},
            "cat tipo activo",
        ),
        (
            "/cat/tipos-conexion",
            "TCN_Tipo_Conexion",
            {"TCN_Nombre": f"QA Conexion {SUFFIX}", "TCN_Descripcion": "QA"},
            {"TCN_Descripcion": "QA actualizado"},
            "cat conexion",
        ),
        (
            "/cat/estados-operativos",
            "EOP_Estado_Operativo",
            {"EOP_Nombre": f"QA Estado {SUFFIX}", "EOP_Descripcion": "QA"},
            {"EOP_Descripcion": "QA actualizado"},
            "cat estado operativo",
        ),
        (
            "/cat/tipos-especificacion",
            "TES_Tipo_Especificacion",
            {"TES_Nombre": f"QA Spec {SUFFIX}", "TES_Unidad_Medida": "u"},
            {"TES_Unidad_Medida": "und"},
            "cat tipo spec",
        ),
    ]
    for path, id_key, create_body, patch_body, name in catalog_tests:
        _, data = await req(client, "POST", path, label=f"CRUD {name} create", headers=auth, expected=(201,), json=create_body)
        item_id = data.get(id_key) if data else None
        if item_id:
            await req(client, "GET", f"{path}/{item_id}", label=f"CRUD {name} read", headers=auth)
            await req(client, "PATCH", f"{path}/{item_id}", label=f"CRUD {name} update", headers=auth, json=patch_body)
            await req(client, "DELETE", f"{path}/{item_id}", label=f"CRUD {name} delete", headers=auth, expected=(204,))


async def check_geo(client: httpx.AsyncClient, auth: dict) -> None:
    _, pais = await req(
        client,
        "POST",
        "/geo/paises",
        label="CRUD geo pais create",
        headers=auth,
        expected=(201,),
        json={"PAI_Nombre": f"QA Pais {SUFFIX}", "PAI_Codigo_ISO": "Q" + SUFFIX[-2:]},
    )
    pais_id = pais.get("PAI_Pais") if pais else None
    if not pais_id:
        return
    await req(client, "PATCH", f"/geo/paises/{pais_id}", label="CRUD geo pais update", headers=auth, json={"PAI_Nombre": f"QA Pais {SUFFIX} v2"})
    _, est = await req(client, "POST", "/geo/estados", label="CRUD geo estado create", headers=auth, expected=(201,), json={"EST_Nombre": f"QA Estado Geo {SUFFIX}", "PAI_Pais": pais_id})
    est_id = est.get("EST_Estado") if est else None
    if est_id:
        await req(client, "GET", f"/geo/estados?pais_id={pais_id}", label="CRUD geo estado list", headers=auth)
        await req(client, "PATCH", f"/geo/estados/{est_id}", label="CRUD geo estado update", headers=auth, json={"EST_Nombre": f"QA Estado Geo {SUFFIX} v2"})
        _, mun = await req(client, "POST", "/geo/municipios", label="CRUD geo municipio create", headers=auth, expected=(201,), json={"MUN_Nombre": f"QA Municipio {SUFFIX}", "EST_Estado": est_id})
        mun_id = mun.get("MUN_Municipio") if mun else None
        if mun_id:
            _, sede = await req(client, "POST", "/geo/sedes", label="CRUD geo sede create", headers=auth, expected=(201,), json={"SED_Nombre": f"QA Sede {SUFFIX}", "SED_Direccion_Calle": "QA", "SED_Direccion_Numero": "1", "MUN_Municipio": mun_id})
            sede_id = sede.get("SED_Sede") if sede else None
            if sede_id:
                _, edi = await req(client, "POST", "/geo/edificios", label="CRUD geo edificio create", headers=auth, expected=(201,), json={"EDI_Nombre": f"QA Edificio {SUFFIX}", "SED_Sede": sede_id})
                edi_id = edi.get("EDI_Edificio") if edi else None
                if edi_id:
                    _, niv = await req(client, "POST", "/geo/niveles", label="CRUD geo nivel create", headers=auth, expected=(201,), json={"NIV_Numero_Piso": "QA", "NIV_Alias": f"QA Nivel {SUFFIX}", "EDI_Edificio": edi_id})
                    niv_id = niv.get("NIV_Nivel") if niv else None
                    if niv_id:
                        _, area = await req(client, "POST", "/geo/areas", label="CRUD geo area create", headers=auth, expected=(201,), json={"ARE_Nombre": f"QA Area {SUFFIX}", "ARE_Tipo_Acceso": "General", "ARE_Descripcion": "QA", "NIV_Nivel": niv_id})
                        area_id = area.get("ARE_Area") if area else None
                        if area_id:
                            await req(client, "PATCH", f"/geo/areas/{area_id}", label="CRUD geo area update", headers=auth, json={"ARE_Descripcion": "QA actualizado"})
                            await req(client, "DELETE", f"/geo/areas/{area_id}", label="CRUD geo area delete", headers=auth, expected=(204,))
                        await req(client, "DELETE", f"/geo/niveles/{niv_id}", label="CRUD geo nivel delete", headers=auth, expected=(204,))
                    await req(client, "DELETE", f"/geo/edificios/{edi_id}", label="CRUD geo edificio delete", headers=auth, expected=(204,))
                await req(client, "DELETE", f"/geo/sedes/{sede_id}", label="CRUD geo sede delete", headers=auth, expected=(204,))
            await req(client, "DELETE", f"/geo/municipios/{mun_id}", label="CRUD geo municipio delete", headers=auth, expected=(204,))
        await req(client, "DELETE", f"/geo/estados/{est_id}", label="CRUD geo estado delete", headers=auth, expected=(204,))
    await req(client, "DELETE", f"/geo/paises/{pais_id}", label="CRUD geo pais delete", headers=auth, expected=(204,))
    await req(client, "GET", "/geo/areas/all", label="geo hierarchy", headers=auth)


async def check_org(client: httpx.AsyncClient, auth: dict, ctx: dict) -> None:
    for path in ("/org/departamentos", "/org/departamentos/resumen", "/org/cargos", "/org/personas", "/org/personas/disponibles", "/org/usuarios"):
        await req(client, "GET", path, label=f"read {path}", headers=auth, expected=(200, 403))

    _, dep = await req(client, "POST", "/org/departamentos", label="CRUD org dept create", headers=auth, expected=(201,), json={"DEP_Nombre": f"QA Dept {SUFFIX}", "DEP_Codigo_Costos": "QA", "DEP_Descripcion": "QA"})
    dep_id = dep.get("DEP_Departamento") if dep else None
    if dep_id:
        await req(client, "PATCH", f"/org/departamentos/{dep_id}", label="CRUD org dept update", headers=auth, json={"DEP_Descripcion": "QA actualizado"})
        await req(client, "DELETE", f"/org/departamentos/{dep_id}", label="CRUD org dept delete", headers=auth, expected=(204,))

    _, cargo = await req(client, "POST", "/org/cargos", label="CRUD org cargo create", headers=auth, expected=(201,), json={"CAR_Nombre": f"QA Cargo {SUFFIX}", "CAR_Es_Jefatura": False, "CAR_Descripcion": "QA"})
    cargo_id = cargo.get("CAR_Cargo") if cargo else None
    if cargo_id:
        await req(client, "PATCH", f"/org/cargos/{cargo_id}", label="CRUD org cargo update", headers=auth, json={"CAR_Descripcion": "QA actualizado"})
        await req(client, "DELETE", f"/org/cargos/{cargo_id}", label="CRUD org cargo delete", headers=auth, expected=(204,))

    _, person = await req(client, "POST", "/org/personas", label="CRUD org persona create", headers=auth, expected=(201,), json={"PER_Primer_Nombre": "QA", "PER_Primer_Apellido": f"Persona{SUFFIX}", "PER_Email_Corporativo": f"qa.persona.{SUFFIX}@example.com", "PER_Telefono": "5555-0000", "DEP_Departamento": ctx["dep"], "CAR_Cargo": ctx["cargo"]})
    person_id = person.get("PER_Persona") if person else None
    if person_id:
        await req(client, "PATCH", f"/org/personas/{person_id}", label="CRUD org persona update", headers=auth, json={"PER_Telefono": "5555-1111"})
        await req(client, "DELETE", f"/org/personas/{person_id}", label="CRUD org persona delete logical", headers=auth, expected=(204,))

    _, user_person = await req(client, "POST", "/org/personas", label="CRUD org user person create", headers=auth, expected=(201,), json={"PER_Primer_Nombre": "QA", "PER_Primer_Apellido": f"Usuario{SUFFIX}", "PER_Email_Corporativo": f"qa.user.{SUFFIX}@example.com", "DEP_Departamento": ctx["dep"], "CAR_Cargo": ctx["cargo"]})
    user_person_id = user_person.get("PER_Persona") if user_person else None
    if user_person_id:
        _, user = await req(client, "POST", "/org/usuarios", label="CRUD org usuario create", headers=auth, expected=(201, 403), json={"USU_Username": f"qauser{SUFFIX}", "USU_Password": f"QApass{SUFFIX}!A1", "USU_Rol": "CONSULTA", "PER_Persona": user_person_id})
        user_id = user.get("USU_Usuario") if user else None
        if user_id:
            await req(client, "GET", f"/org/usuarios/{user_id}", label="CRUD org usuario read", headers=auth, expected=(200, 403))
            await req(client, "PATCH", f"/org/usuarios/{user_id}", label="CRUD org usuario update", headers=auth, expected=(200, 403), json={"USU_Rol": "TECNICO"})
            await req(client, "POST", f"/org/usuarios/{user_id}/2fa/reset", label="org usuario 2fa reset", headers=auth, expected=(200, 403))
            await req(client, "DELETE", f"/org/usuarios/{user_id}", label="CRUD org usuario deactivate", headers=auth, expected=(204, 403))


async def check_asset_trace_maintenance_attachment(client: httpx.AsyncClient, auth: dict, ctx: dict) -> None:
    asset_payload = {
        "ACT_Codigo_Interno": f"QA-AUD-{SUFFIX}",
        "ACT_Serie_Fabricante": f"QA-SER-{SUFFIX}",
        "ACT_Hostname": f"qa-host-{SUFFIX}",
        "ACT_Fecha_Compra": str(date.today()),
        "ACT_Fin_Garantia": str(date.today() + timedelta(days=365)),
        "ACT_Costo": "125.50",
        "MOD_Modelo": ctx["modelo"],
        "TAC_Tipo_Activo": ctx["tipo_activo"],
        "EOP_Estado_Operativo": ctx["estado"],
        "especificaciones": [
            {"TES_Tipo_Especificacion": ctx["specs"][0], "ESP_Valor": f"QA valor {SUFFIX}"}
        ],
    }
    _, asset = await req(client, "POST", "/core/activos", label="CRUD core activo create", headers=auth, expected=(201,), json=asset_payload)
    asset_id = asset.get("ACT_Activo") if asset else None
    ids["asset"] = asset_id
    if not asset_id:
        return

    await req(client, "GET", f"/core/activos/{asset_id}", label="CRUD core activo read", headers=auth)
    await req(client, "GET", f"/core/activos/by-code/QA-AUD-{SUFFIX}", label="core activo by code", headers=auth)
    await req(client, "PATCH", f"/core/activos/{asset_id}", label="CRUD core activo update", headers=auth, json={"ACT_Hostname": f"qa-host-{SUFFIX}-upd", "ACT_Costo": "130.75"})
    await req(client, "GET", "/core/activos?skip=0&limit=5", label="core activo list", headers=auth)
    await req(client, "POST", "/core/activos/search", label="core activo search", headers=auth, json={"q": f"QA-AUD-{SUFFIX}", "page": 1, "per_page": 10})
    await req(client, "POST", "/core/activos/etiquetas.pdf", label="core etiquetas selected", headers=auth, expected=(200,), json={"activos_ids": [asset_id]})

    _, specs = await req(client, "GET", f"/core/activos/{asset_id}/especificaciones", label="core specs list", headers=auth)
    if specs:
        esp_id = specs[0].get("ESP_Especificacion")
        if esp_id:
            await req(client, "PATCH", f"/core/especificaciones/{esp_id}", label="CRUD core spec update", headers=auth, expected=(204,), json={"ESP_Valor": f"QA valor actualizado {SUFFIX}"})
    if len(ctx["specs"]) > 1:
        _, new_spec = await req(client, "POST", f"/core/activos/{asset_id}/especificaciones", label="CRUD core spec create", headers=auth, expected=(201,), json={"TES_Tipo_Especificacion": ctx["specs"][1], "ESP_Valor": f"QA extra {SUFFIX}"})
        esp2 = new_spec.get("ESP_Especificacion") if new_spec else None
        if esp2:
            await req(client, "DELETE", f"/core/especificaciones/{esp2}", label="CRUD core spec delete", headers=auth, expected=(204,))

    files = {"file": (f"qa-{SUFFIX}.txt", b"QA attachment content", "text/plain")}
    form = {"categoria": "otro", "descripcion": "QA adjunto"}
    _, adj = await req(client, "POST", f"/adjuntos/activos/{asset_id}", label="CRUD adjunto activo upload", headers=auth, expected=(201,), files=files, data=form)
    adj_id = adj.get("ADJ_Adjunto") if adj else None
    await req(client, "GET", f"/adjuntos/activos/{asset_id}", label="adjunto activo list", headers=auth)
    if adj_id:
        await req(client, "GET", f"/adjuntos/{adj_id}/download", label="adjunto activo download", headers=auth, expected=(200,))
        await req(client, "DELETE", f"/adjuntos/{adj_id}", label="CRUD adjunto activo delete", headers=auth, expected=(204,))

    trace_headers = {**auth, "Idempotency-Key": "qa-trace-" + uuid.uuid4().hex}
    mov_payload = {
        "ACT_Activo": asset_id,
        "PER_Persona": ctx["persona"],
        "ARE_Area": ctx["area"],
        "TMO_Tipo_Movimiento": ctx["mov_tipo"],
        "MOV_Observacion": "QA asignacion",
    }
    _, mov = await req(client, "POST", "/trazabilidad/movimientos", label="CRUD trazabilidad movimiento create", headers=trace_headers, expected=(201,), json=mov_payload)
    mov_id = mov.get("MOV_Movimiento") if mov else None
    if mov_id:
        await req(client, "POST", "/trazabilidad/movimientos", label="trazabilidad duplicate open guard", headers={**auth, "Idempotency-Key": "qa-trace-dup-" + uuid.uuid4().hex}, expected=(409,), json=mov_payload)
        await req(client, "GET", f"/trazabilidad/activo/{asset_id}/historial", label="trazabilidad historial activo", headers=auth)
        await req(client, "GET", f"/trazabilidad/persona/{ctx['persona']}/asignaciones", label="trazabilidad asignaciones persona", headers=auth)
        await req(client, "GET", f"/trazabilidad/acta/{mov_id}", label="trazabilidad acta", headers=auth, expected=(200,))
        await req(client, "POST", "/trazabilidad/acta/lote", label="trazabilidad acta lote", headers=auth, expected=(200,), json={"movimientos_ids": [mov_id]})
        if ctx.get("persona2"):
            await req(client, "POST", "/trazabilidad/transferencia", label="trazabilidad transferencia", headers=auth, expected=(201,), json={"ACT_Activo": asset_id, "PER_Persona_Destino": ctx["persona2"], "ARE_Area_Destino": ctx["area"], "MOV_Observacion": "QA transferencia"})
        await req(client, "POST", "/trazabilidad/devolucion", label="trazabilidad devolucion", headers=auth, expected=(200,), json={"ACT_Activo": asset_id})

    await req(client, "GET", "/trazabilidad/movimientos?skip=0&limit=10", label="trazabilidad list", headers=auth)
    await req(client, "GET", "/trazabilidad/tipos", label="trazabilidad tipos list", headers=auth)

    _, mant = await req(client, "POST", "/mantenimiento/", label="CRUD mantenimiento create", headers=auth, expected=(201,), json={"ACT_Activo": asset_id, "PER_Persona_Solicita": ctx["persona"], "TMA_Tipo_Mantenimiento": ctx["mant_tipo"], "MAN_Descripcion_Falla": "QA mantenimiento controlado", "MAN_Costo_Total": "0", "detalles": []})
    mant_id = mant.get("MAN_Mantenimiento") if mant else None
    if mant_id:
        await req(client, "GET", f"/mantenimiento/{mant_id}", label="CRUD mantenimiento read", headers=auth)
        _, det = await req(client, "POST", f"/mantenimiento/{mant_id}/detalles", label="CRUD mantenimiento detalle create", headers=auth, expected=(201,), json={"DMA_Accion_Realizada": "QA revision inicial", "DMA_Costo_Item": "5.00"})
        det_id = det.get("DMA_Detalle_Mant") if det else None
        await req(client, "GET", f"/mantenimiento/{mant_id}/detalles", label="mantenimiento detalles list", headers=auth)
        if det_id:
            await req(client, "PATCH", f"/mantenimiento/detalles/{det_id}", label="CRUD mantenimiento detalle update", headers=auth, json={"DMA_Accion_Realizada": "QA revision actualizada", "DMA_Costo_Item": "7.00"})
            await req(client, "DELETE", f"/mantenimiento/detalles/{det_id}", label="CRUD mantenimiento detalle delete", headers=auth, expected=(204,))
        await req(client, "PATCH", f"/mantenimiento/{mant_id}/cerrar", label="mantenimiento cerrar", headers=auth, json={"MAN_Costo_Total": "7.00"})
        await req(client, "DELETE", f"/mantenimiento/{mant_id}", label="CRUD mantenimiento delete closed", headers=auth, expected=(204,))
    await req(client, "GET", "/mantenimiento/", label="mantenimiento list", headers=auth)
    await req(client, "GET", "/mantenimiento/tipos", label="mantenimiento tipos list", headers=auth)


async def check_consumables_procurement(client: httpx.AsyncClient, auth: dict) -> None:
    _, con_del = await req(client, "POST", "/consumibles", label="CRUD consumible create deletable", headers=auth, expected=(201,), json={"CON_Nombre": f"QA Consumible DEL {SUFFIX}", "CON_Descripcion": "QA", "CON_Categoria": "QA", "CON_Unidad": "unidad", "CON_Stock_Minimo": 1, "CON_Stock_Actual": 0})
    con_del_id = con_del.get("CON_Consumible") if con_del else None
    if con_del_id:
        await req(client, "PATCH", f"/consumibles/{con_del_id}", label="CRUD consumible update deletable", headers=auth, json={"CON_Descripcion": "QA actualizado"})
        await req(client, "DELETE", f"/consumibles/{con_del_id}", label="CRUD consumible delete no history", headers=auth, expected=(204,))

    _, con = await req(client, "POST", "/consumibles", label="CRUD consumible create stock", headers=auth, expected=(201,), json={"CON_Nombre": f"QA Consumible STOCK {SUFFIX}", "CON_Descripcion": "QA stock", "CON_Categoria": "QA", "CON_Unidad": "unidad", "CON_Stock_Minimo": 2, "CON_Stock_Actual": 1})
    con_id = con.get("CON_Consumible") if con else None
    if con_id:
        await req(client, "POST", f"/consumibles/{con_id}/entrada", label="consumible entrada", headers=auth, expected=(201,), json={"MOC_Cantidad": 5, "MOC_Motivo": "QA entrada"})
        await req(client, "POST", f"/consumibles/{con_id}/salida", label="consumible salida", headers=auth, expected=(201,), json={"MOC_Cantidad": 2, "MOC_Motivo": "QA salida"})
        await req(client, "POST", f"/consumibles/{con_id}/salida", label="consumible insufficient stock guard", headers=auth, expected=(409,), json={"MOC_Cantidad": 9999, "MOC_Motivo": "QA overdraw"})
        await req(client, "GET", f"/consumibles/{con_id}/movimientos", label="consumible movimientos list", headers=auth)
        await req(client, "DELETE", f"/consumibles/{con_id}", label="consumible delete blocked by history", headers=auth, expected=(409,))
    await req(client, "GET", "/consumibles", label="consumible list", headers=auth)
    await req(client, "GET", "/consumibles?solo_bajo_stock=true", label="consumible bajo stock filter", headers=auth)

    _, prv = await req(client, "POST", "/compras/proveedores", label="CRUD proveedor create", headers=auth, expected=(201,), json={"PRV_Nombre": f"QA Proveedor {SUFFIX}", "PRV_Identificacion_Fiscal": f"NIT-{SUFFIX}", "PRV_Contacto": "QA", "PRV_Email": f"proveedor.{SUFFIX}@example.com", "PRV_Telefono": "5555-2222", "PRV_Direccion": "QA"})
    prv_id = prv.get("PRV_Proveedor") if prv else None
    if prv_id:
        await req(client, "PATCH", f"/compras/proveedores/{prv_id}", label="CRUD proveedor update", headers=auth, json={"PRV_Contacto": "QA actualizado"})
        line = {"OCL_Descripcion": "QA item", "OCL_Cantidad": 1, "OCL_Precio_Unitario": "10.00"}
        if con_id:
            line["CON_Consumible"] = con_id
        _, order = await req(client, "POST", "/compras/ordenes", label="CRUD orden create", headers=auth, expected=(201,), json={"OCO_Numero": f"QA-OC-{SUFFIX}", "OCO_Fecha": str(date.today()), "OCO_Moneda": "GTQ", "OCO_Notas": "QA orden", "PRV_Proveedor": prv_id, "lineas": [line]})
        order_id = order.get("OCO_Orden") if order else None
        if order_id:
            lineas = order.get("lineas") or []
            line_id = lineas[0].get("OCL_Linea") if lineas else None
            await req(client, "GET", f"/compras/ordenes/{order_id}", label="CRUD orden read", headers=auth)
            if con_id and line_id:
                await req(client, "POST", f"/compras/ordenes/{order_id}/recibir", label="orden recibir consumible", headers=auth, expected=(200,), json={"consumibles": [{"OCL_Linea": line_id, "CON_Consumible": con_id, "cantidad": 1}], "activos": [], "licencias": []})
            else:
                await req(client, "PATCH", f"/compras/ordenes/{order_id}/estado", label="CRUD orden update estado", headers=auth, json={"OCO_Estado": "CANCELADA"})
            files = {"file": (f"qa-oc-{SUFFIX}.txt", b"QA orden attachment", "text/plain")}
            form = {"categoria": "factura", "descripcion": "QA factura"}
            _, adj_ord = await req(client, "POST", f"/adjuntos/ordenes/{order_id}", label="CRUD adjunto orden upload", headers=auth, expected=(201,), files=files, data=form)
            adj_id = adj_ord.get("ADJ_Adjunto") if adj_ord else None
            await req(client, "GET", f"/adjuntos/ordenes/{order_id}", label="adjunto orden list", headers=auth)
            if adj_id:
                await req(client, "GET", f"/adjuntos/{adj_id}/download", label="adjunto orden download", headers=auth, expected=(200,))
                await req(client, "DELETE", f"/adjuntos/{adj_id}", label="CRUD adjunto orden delete", headers=auth, expected=(204,))
        await req(client, "DELETE", f"/compras/proveedores/{prv_id}", label="proveedor delete blocked by order", headers=auth, expected=(409,))
    await req(client, "GET", "/compras/proveedores", label="proveedor list", headers=auth)
    await req(client, "GET", "/compras/ordenes", label="orden list", headers=auth)
    await req(client, "GET", "/compras/garantias?dias=90&solo_alertas=false", label="garantias read replica", headers=auth)
    await req(client, "POST", "/compras/garantias/notificar?dias=90", label="garantias notificar", headers=auth, expected=(200, 403))


async def check_software(client: httpx.AsyncClient, auth: dict) -> None:
    _, tl = await req(client, "POST", "/soft/tipos-licencia", label="CRUD soft tipo licencia create", headers=auth, expected=(201,), json={"TLI_Nombre": f"QA LicType {SUFFIX}", "TLI_Descripcion": "QA"})
    tl_id = tl.get("TLI_Tipo_Licencia") if tl else None
    _, sw = await req(client, "POST", "/soft/software", label="CRUD soft software create", headers=auth, expected=(201,), json={"SOF_Nombre": f"QA Software {SUFFIX}", "SOF_Version": "1.0", "SOF_Fabricante": "QA"})
    sw_id = sw.get("SOF_Software") if sw else None
    if tl_id:
        await req(client, "PATCH", f"/soft/tipos-licencia/{tl_id}", label="CRUD soft tipo licencia update", headers=auth, json={"TLI_Descripcion": "QA actualizado"})
    if sw_id:
        await req(client, "PATCH", f"/soft/software/{sw_id}", label="CRUD soft software update", headers=auth, json={"SOF_Version": "1.1"})
    if tl_id and sw_id:
        _, lic = await req(client, "POST", "/soft/licencias", label="CRUD soft licencia create with keys", headers=auth, expected=(201,), json={"SOF_Software": sw_id, "TLI_Tipo_Licencia": tl_id, "LIC_Cantidad_Total": 2, "LIC_Fecha_Vencimiento": str(date.today() + timedelta(days=180)), "LIC_Claves": [{"LCL_Clave_Activacion": f"QA-KEY-{SUFFIX}-A", "LCL_Referencia": "QA-A"}, {"LCL_Clave_Activacion": f"QA-KEY-{SUFFIX}-B", "LCL_Referencia": "QA-B"}]})
        lic_id = lic.get("LIC_Licencia") if lic else None
        if lic_id:
            await req(client, "GET", f"/soft/licencias?software_id={sw_id}", label="soft licencia list by software", headers=auth)
            await req(client, "GET", f"/soft/licencias/{lic_id}", label="CRUD soft licencia read", headers=auth)
            _, keys = await req(client, "GET", f"/soft/licencias/{lic_id}/claves", label="soft licencia keys admin audited", headers=auth)
            if keys is not None:
                ok = isinstance(keys, list) and len(keys) == 2 and all(k.get("LCL_Clave_Activacion") for k in keys)
                add("soft license key payload visible to admin", "CHECK", "/soft/licencias/{id}/claves", "OK" if ok else "BAD", ok, ["OK"], "values redacted")
            await req(client, "PATCH", f"/soft/licencias/{lic_id}", label="CRUD soft licencia update", headers=auth, json={"LIC_Fecha_Vencimiento": str(date.today() + timedelta(days=210))})
            if ids.get("asset"):
                install_body = {"ACT_Activo": ids["asset"], "LIC_Licencia": lic_id, "INS_Fecha_Instalacion": str(date.today())}
                await req(client, "POST", "/soft/instalaciones", label="soft instalacion create", headers={**auth, "Idempotency-Key": "qa-install-" + uuid.uuid4().hex}, expected=(201,), json=install_body)
                await req(client, "GET", f"/soft/activos/{ids['asset']}/instalaciones?solo_activas=true", label="soft instalaciones activo", headers=auth)
                await req(client, "POST", "/soft/instalaciones/desinstalar", label="soft instalacion uninstall", headers=auth, expected=(200,), json=install_body)
            await req(client, "DELETE", f"/soft/licencias/{lic_id}", label="soft licencia delete blocked by history", headers=auth, expected=(409, 204))
        _, lic2 = await req(client, "POST", "/soft/licencias", label="CRUD soft licencia create deletable", headers=auth, expected=(201,), json={"SOF_Software": sw_id, "TLI_Tipo_Licencia": tl_id, "LIC_Cantidad_Total": 1, "LIC_Fecha_Vencimiento": str(date.today() + timedelta(days=90)), "LIC_Claves": [{"LCL_Clave_Activacion": f"QA-KEY-{SUFFIX}-DEL", "LCL_Referencia": "QA-DEL"}]})
        lic2_id = lic2.get("LIC_Licencia") if lic2 else None
        if lic2_id:
            await req(client, "DELETE", f"/soft/licencias/{lic2_id}", label="CRUD soft licencia delete no history", headers=auth, expected=(204,))
        await req(client, "DELETE", f"/soft/software/{sw_id}", label="soft software delete blocked by license history", headers=auth, expected=(409, 204))
        await req(client, "DELETE", f"/soft/tipos-licencia/{tl_id}", label="soft tipo licencia delete blocked by license history", headers=auth, expected=(409, 204))
    await req(client, "GET", "/soft/tipos-licencia", label="soft tipos list", headers=auth)
    await req(client, "GET", "/soft/software", label="soft software list", headers=auth)


async def check_governance_exports(client: httpx.AsyncClient, auth: dict, role: str) -> None:
    _, cfg = await req(client, "GET", "/gov/config", label="gov config public", headers=auth)
    if cfg and role == "SUPER_ADMIN":
        payload = {
            key: cfg.get(key)
            for key in (
                "SYS_Nombre_Empresa",
                "SYS_Logo_URL",
                "SYS_Color_Primario",
                "SYS_Color_Secundario",
                "SYS_Color_Fondo",
                "SYS_Idioma_Defecto",
                "SYS_Codigo_Formulario",
                "SYS_Ciudad",
            )
        }
        await req(client, "PUT", "/gov/config", label="gov config update same payload", headers=auth, json=payload)
    await req(client, "GET", "/gov/auditoria?skip=0&limit=5", label="gov auditoria list", headers=auth, expected=(200, 403))
    await req(client, "GET", "/gov/auditoria/resumen", label="gov auditoria resumen", headers=auth, expected=(200, 403))
    await req(client, "GET", "/stats/dashboard", label="stats dashboard", headers=auth)
    for path in ("/export/activos.csv", "/export/movimientos.csv", "/export/consumibles.csv", "/export/proveedores.csv", "/export/ordenes.csv", "/export/auditoria.csv"):
        await req(client, "GET", path, label=f"export {path}", headers=auth, expected=(200, 403))


async def main() -> None:
    ctx = await get_context()
    auth = {"Authorization": "Bearer " + ctx["token"]}
    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0), follow_redirects=False) as client:
        await check_public_and_catalogs(client, auth)
        await check_geo(client, auth)
        await check_org(client, auth, ctx)
        await check_asset_trace_maintenance_attachment(client, auth, ctx)
        await check_consumables_procurement(client, auth)
        await check_software(client, auth)
        await check_governance_exports(client, auth, ctx["user"]["role"])
        if ids.get("asset"):
            await req(client, "DELETE", f"/core/activos/{ids['asset']}", label="CRUD core activo delete logical/baja", headers=auth, expected=(204, 409))
        await req(client, "POST", "/login/password-reset/request", label="password reset request nonexistent", expected=(202,), json={"identifier": f"noexiste.{SUFFIX}@example.com"})
        logout_token = security.create_access_token(ctx["user"]["username"], ctx["user"]["role"])
        await req(client, "POST", "/login/logout", label="login logout", headers={"Authorization": "Bearer " + logout_token}, expected=(204,))

    async with engine.connect() as conn:
        primary_assets = (await conn.execute(text('select count(*) from "INV_ACTIVO"'))).scalar()
        primary_recovery = (await conn.execute(text("select pg_is_in_recovery()"))).scalar()
    async with read_engine.connect() as conn:
        replica_assets = (await conn.execute(text('select count(*) from "INV_ACTIVO"'))).scalar()
        replica_recovery = (await conn.execute(text("select pg_is_in_recovery()"))).scalar()

    failures = [item for item in results if not item["ok"]]
    by_status: dict[str, int] = {}
    for item in results:
        by_status[str(item["status"])] = by_status.get(str(item["status"]), 0) + 1

    print(
        json.dumps(
            {
                "suffix": SUFFIX,
                "user_role_used": ctx["user"]["role"],
                "total_checks": len(results),
                "passed": len(results) - len(failures),
                "failed": len(failures),
                "by_status": by_status,
                "replication": {
                    "primary_assets": primary_assets,
                    "replica_assets": replica_assets,
                    "primary_in_recovery": primary_recovery,
                    "replica_in_recovery": replica_recovery,
                    "counts_match": primary_assets == replica_assets,
                },
                "created_asset_code": f"QA-AUD-{SUFFIX}" if ids.get("asset") else None,
                "failures": failures[:80],
            },
            ensure_ascii=True,
            indent=2,
            default=str,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
