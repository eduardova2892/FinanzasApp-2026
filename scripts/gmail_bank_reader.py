"""
Módulo Streamlit para revisar e importar gastos bancarios detectados desde Gmail.

Objetivo:
- Mantener la lógica de la bandeja fuera de app.py.
- Leer data/bank_gmail_expenses_pending.csv generado por Airflow/Gmail.
- Permitir revisar, corregir categoría, importar o descartar gastos.
- Soportar varios bancos a futuro usando una bandeja común.

Uso en app.py:
    from scripts.streamlit_bank_inbox import render_bank_gmail_inbox
    render_bank_gmail_inbox(guardar)
"""

from __future__ import annotations

import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st


BANK_GMAIL_PENDING_PATH = Path("data/bank_gmail_expenses_pending.csv")

BANK_GMAIL_PENDING_COLUMNS = [
    "gmail_id",
    "gmail_thread_id",
    "gmail_date",
    "subject",
    "banco",
    "medio_pago",
    "monto",
    "moneda",
    "empresa",
    "fecha",
    "hora",
    "fecha_hora_texto",
    "tarjeta_ultimos4",
    "numero_operacion",
    "categoria_sugerida",
    "descripcion_sugerida",
    "hash_importacion",
    "estado",
    "fecha_detectado_lima",
    "fecha_importado_lima",
    "resultado_importacion",
    "fuente",
]


def filtrar_por_fecha_desde_hasta(df: pd.DataFrame, fecha_desde, fecha_hasta) -> pd.DataFrame:
    if df.empty or "fecha" not in df.columns:
        return df.copy()

    tmp = df.copy()
    tmp["_fecha_dt"] = pd.to_datetime(tmp["fecha"], errors="coerce").dt.date

    tmp = tmp[
        (tmp["_fecha_dt"] >= fecha_desde) &
        (tmp["_fecha_dt"] <= fecha_hasta)
    ].copy()

    tmp = tmp.drop(columns=["_fecha_dt"], errors="ignore")
    return tmp


def _texto_seguro(value) -> str:
    if value is None:
        return ""
    try:
        if isinstance(value, float) and pd.isna(value):
            return ""
    except Exception:
        pass
    return str(value).strip()


def _normalizar_estado(value) -> str:
    s = _texto_seguro(value).lower().strip()
    return s or "pendiente"


def _fecha_desde_texto(value):
    """Convierte una fecha de CSV a date. Si no puede, usa la fecha actual Lima."""
    s = _texto_seguro(value)
    hoy_lima = datetime.now(ZoneInfo("America/Lima")).date()
    if not s:
        return hoy_lima

    for fmt in ["%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%d-%m-%Y"]:
        try:
            return datetime.strptime(s, fmt).date()
        except Exception:
            pass

    try:
        dt = pd.to_datetime(s, errors="coerce")
        if pd.isna(dt):
            return hoy_lima
        return dt.date()
    except Exception:
        return hoy_lima


def cargar_pendientes_bancos(path: Path | str = BANK_GMAIL_PENDING_PATH) -> pd.DataFrame:
    """Carga la bandeja común de gastos detectados por Gmail/Airflow."""
    p = Path(path)
    if not p.exists():
        return pd.DataFrame(columns=BANK_GMAIL_PENDING_COLUMNS)

    try:
        df = pd.read_csv(p, dtype=str)
    except Exception:
        return pd.DataFrame(columns=BANK_GMAIL_PENDING_COLUMNS)

    for col in BANK_GMAIL_PENDING_COLUMNS:
        if col not in df.columns:
            df[col] = ""

    df = df[BANK_GMAIL_PENDING_COLUMNS].copy().fillna("")
    df["monto"] = pd.to_numeric(df["monto"], errors="coerce").fillna(0.0)
    df["estado"] = df["estado"].map(_normalizar_estado)
    return df


def guardar_pendientes_bancos(df: pd.DataFrame, path: Path | str = BANK_GMAIL_PENDING_PATH) -> None:
    """Guarda la bandeja común de gastos detectados."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    out = df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame(columns=BANK_GMAIL_PENDING_COLUMNS)
    for col in BANK_GMAIL_PENDING_COLUMNS:
        if col not in out.columns:
            out[col] = ""

    out = out[BANK_GMAIL_PENDING_COLUMNS].copy()
    out.to_csv(p, index=False, encoding="utf-8-sig")


def existe_importacion_bancaria(hash_importacion: str, numero_operacion: str = "", banco: str = "") -> bool:
    """Evita duplicados entre gastos débito y crédito ya importados."""
    h = _texto_seguro(hash_importacion)
    op = _texto_seguro(numero_operacion)
    banco_norm = _texto_seguro(banco).upper()

    listas = [
        st.session_state.get("gastos_diarios", []),
        st.session_state.get("gastos_tarjeta", []),
    ]

    for lista in listas:
        for gasto in lista:
            if h and _texto_seguro(gasto.get("hash_importacion")) == h:
                return True

            gasto_op = _texto_seguro(gasto.get("numero_operacion"))
            gasto_banco = _texto_seguro(gasto.get("banco")).upper()
            if op and gasto_op == op and (not banco_norm or gasto_banco == banco_norm):
                return True

    return False


def _llamar_guardar(guardar_func: Optional[Callable[[str], None]], clave: str) -> None:
    if guardar_func is None:
        return
    try:
        guardar_func(clave)
    except Exception as exc:
        st.warning(f"No se pudo guardar la clave `{clave}` automáticamente: {exc}")


def _mapear_cuentas_debito():
    """Devuelve nombres e IDs de cuentas disponibles para consumos débito."""
    config = st.session_state.get("configuracion", {}) or {}
    nombre_principal = config.get("nombre_cuenta_principal", "Cuenta principal")

    cuentas = {nombre_principal: "principal"}
    for cuenta in st.session_state.get("cuentas_ahorro", []):
        nombre = _texto_seguro(cuenta.get("nombre"))
        cuenta_id = _texto_seguro(cuenta.get("id"))
        if nombre:
            cuentas[nombre] = cuenta_id or nombre

    return cuentas


def _indice_default_por_banco(nombres: list[str], banco: str) -> int:
    banco_norm = _texto_seguro(banco).upper()
    if not nombres:
        return 0
    for idx, nombre in enumerate(nombres):
        if banco_norm and banco_norm in _texto_seguro(nombre).upper():
            return idx
    return 0



def generar_pendientes_desde_gmail_bcp(
    days: int = 10,
    max_results: int = 200,
    pending_path: Path | str = BANK_GMAIL_PENDING_PATH,
) -> dict:
    """
    Lee Gmail y REEMPLAZA la bandeja CSV seg?n los d?as seleccionados.

    Antes el proceso agregaba nuevos registros al CSV existente. Eso hac?a que,
    al cambiar de 30 a 10 d?as, se siguiera viendo el resumen anterior.
    Ahora la bandeja queda sincronizada con el rango actual elegido por el usuario.
    """
    project = Path.cwd()
    scripts_dir = project / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))

    from gmail_bank_reader import fetch_bcp_consumption_emails
    from bank_email_parsers import parse_bank_email

    pending_path = Path(pending_path)

    # Leemos lo anterior solo para conservar estado de importado/descartado si el hash coincide.
    df_existing = cargar_pendientes_bancos(pending_path)
    estados_previos = {}
    if not df_existing.empty and "hash_importacion" in df_existing.columns:
        for _, old in df_existing.iterrows():
            h = _texto_seguro(old.get("hash_importacion"))
            if h:
                estados_previos[h] = old.to_dict()

    emails = fetch_bcp_consumption_emails(
        project,
        days=int(days),
        max_results=int(max_results),
    )
    from datetime import timedelta

    hoy_lima = datetime.now(ZoneInfo("America/Lima")).date()
    fecha_corte = hoy_lima - timedelta(days=int(days))

    rows = []
    leidos = len(emails)
    interpretados = 0
    errores = 0
    ahora_lima = datetime.now(ZoneInfo("America/Lima")).strftime("%Y-%m-%d %H:%M:%S")

    for email in emails:
        try:
            d = email.to_dict() if hasattr(email, "to_dict") else dict(email)

            gmail_id = _texto_seguro(d.get("gmail_id"))

            texto_parse = " ".join([
                _texto_seguro(d.get("subject")),
                _texto_seguro(d.get("snippet")),
                _texto_seguro(d.get("text")),
                _texto_seguro(d.get("body")),
            ])

            parsed = parse_bank_email(
                texto_parse,
                banco="BCP",
                gmail_id=gmail_id,
                gmail_thread_id=d.get("thread_id", ""),
                gmail_date=d.get("date", ""),
                subject=d.get("subject", ""),
            )

            if not parsed:
                continue

            # Filtro real por fecha del correo (no por fecha de recepción)
            fecha_txt = _texto_seguro(parsed.get("fecha"))
            fecha_dt = pd.to_datetime(fecha_txt, errors="coerce")
            if pd.isna(fecha_dt) or fecha_dt.date() < fecha_corte:
                continue

            interpretados += 1

            hash_imp = _texto_seguro(parsed.get("hash_importacion"))
            old = estados_previos.get(hash_imp, {})

            # Conserva importado/descartado si ya existía; si no, pendiente.
            parsed["estado"] = _texto_seguro(old.get("estado")) or "pendiente"
            parsed["fecha_importado_lima"] = _texto_seguro(old.get("fecha_importado_lima"))
            parsed["resultado_importacion"] = _texto_seguro(old.get("resultado_importacion"))

            if not _texto_seguro(parsed.get("fecha_detectado_lima")):
                parsed["fecha_detectado_lima"] = _texto_seguro(old.get("fecha_detectado_lima")) or ahora_lima

            if not _texto_seguro(parsed.get("fuente")):
                parsed["fuente"] = "Gmail BCP"

            rows.append(parsed)

        except Exception:
            errores += 1

    if rows:
        df_new = pd.DataFrame(rows)
        for col in BANK_GMAIL_PENDING_COLUMNS:
            if col not in df_new.columns:
                df_new[col] = ""
        df_new = df_new[BANK_GMAIL_PENDING_COLUMNS].copy()
        df_new["monto"] = pd.to_numeric(df_new["monto"], errors="coerce").fillna(0.0)
        df_new["estado"] = df_new["estado"].map(_normalizar_estado)
        df_new = df_new.sort_values(["fecha", "hora"], ascending=[False, False])
    else:
        df_new = pd.DataFrame(columns=BANK_GMAIL_PENDING_COLUMNS)

    # Punto clave: reemplaza el CSV completo.
    guardar_pendientes_bancos(df_new, pending_path)

    if not df_new.empty and "medio_pago" in df_new.columns:
        conteo_medio = df_new["medio_pago"].value_counts(dropna=False).to_dict()
    else:
        conteo_medio = {}

    pendientes = 0
    if not df_new.empty and "estado" in df_new.columns:
        pendientes = int(df_new["estado"].eq("pendiente").sum())

    return {
        "correos_leidos": leidos,
        "gastos_interpretados": interpretados,
        "nuevos_pendientes": pendientes,
        "duplicados_omitidos": 0,
        "errores": errores,
        "conteo_medio": conteo_medio,
        "archivo": str(pending_path),
        "dias": int(days),
    }

def render_bank_gmail_inbox(
    guardar_func: Optional[Callable[[str], None]] = None,
    pending_path: Path | str = BANK_GMAIL_PENDING_PATH,
    expanded_history: bool = False,
) -> None:
    """
    Renderiza la bandeja de gastos bancarios detectados desde Gmail.

    Parámetros:
    - guardar_func: función de app.py para persistir st.session_state por clave. Usualmente `guardar`.
    - pending_path: CSV generado por Airflow/Gmail.
    - expanded_history: si True, muestra el histórico expandido.
    """
    st.markdown("#### 📥 Bandeja Gmail — gastos bancarios detectados")
    st.caption(
        "Lee automáticamente tus últimos correos bancarios de Gmail, genera una bandeja pendiente "
        "y luego te permite importar cada consumo como gasto de débito o crédito."
    )

    with st.container(border=True):
        st.markdown("##### 🔄 Lectura automática desde Gmail")
        c1, c2, c3 = st.columns([1, 1, 2])
        with c1:
            dias_gmail = st.number_input(
                "Días a revisar",
                min_value=1,
                max_value=90,
                value=10,
                step=1,
                key="bank_gmail_read_days",
            )
        with c2:
            max_correos = st.number_input(
                "Máx. correos",
                min_value=5,
                max_value=200,
                value=200,
                step=5,
                key="bank_gmail_read_max_results",
            )
        with c3:
            st.write("")
            leer_ahora = st.button(
                "🔄 Leer últimos correos Gmail ahora",
                type="primary",
                use_container_width=True,
                key="btn_leer_gmail_bancos_ahora",
            )

        if leer_ahora:
            try:
                with st.spinner("Leyendo Gmail y generando bandeja pendiente..."):
                    resumen = generar_pendientes_desde_gmail_bcp(
                        days=int(dias_gmail),
                        max_results=int(max_correos),
                        pending_path=pending_path,
                    )
                st.success(
                    "Lectura completada: "
                    f"{resumen['correos_leidos']} correos leídos, "
                    f"{resumen['gastos_interpretados']} gastos interpretados, "
                    f"{resumen['nuevos_pendientes']} nuevos pendientes, "
                    f"{resumen['duplicados_omitidos']} duplicados omitidos."
                )
            except Exception as exc:
                st.error(
                    "No pude leer Gmail desde este entorno. "
                    "Verifica que existan `secrets/credentials_gmail.json` y `secrets/token_gmail.json` "
                    "o genera el CSV con Airflow/localmente."
                )
                st.caption(f"Detalle técnico: {exc}")

    df_all = cargar_pendientes_bancos(pending_path)

    if df_all.empty:
        st.info(
            "Todavía no hay gastos detectados desde Gmail. Presiona "
            "**Leer últimos correos Gmail ahora** o ejecuta el DAG `bank_gmail_expenses_pending`."
        )
        return

    df_all["estado"] = df_all["estado"].map(_normalizar_estado)
    df_pending = df_all[df_all["estado"].eq("pendiente")].copy()

    col1, col2, col3 = st.columns(3)
    col1.metric("Pendientes", len(df_pending))
    col2.metric("Detectados totales", len(df_all))
    col3.metric("Monto pendiente", f"S/ {df_pending['monto'].sum():,.2f}" if not df_pending.empty else "S/ 0.00")

    if df_pending.empty:
        st.success("No tienes gastos bancarios pendientes por revisar.")
        with st.expander("🗃️ Ver histórico de bandeja Gmail", expanded=expanded_history):
            st.dataframe(df_all.tail(300), use_container_width=True, hide_index=True)
        return

    bancos_pendientes = sorted([b for b in df_pending["banco"].astype(str).str.upper().unique() if b])
    banco_default = bancos_pendientes[0] if bancos_pendientes else ""

    cuentas_map = _mapear_cuentas_debito()
    cuentas_nombres = list(cuentas_map.keys())
    idx_cuenta = _indice_default_por_banco(cuentas_nombres, banco_default)

    tarjetas_map = {
        _texto_seguro(t.get("nombre")): _texto_seguro(t.get("id"))
        for t in st.session_state.get("tarjetas", [])
        if _texto_seguro(t.get("nombre"))
    }
    tarjetas_nombres = list(tarjetas_map.keys())
    idx_tarjeta = _indice_default_por_banco(tarjetas_nombres, banco_default)

    sel1, sel2 = st.columns(2)
    with sel1:
        cuenta_debito = st.selectbox(
            "Cuenta para consumos de débito",
            cuentas_nombres,
            index=idx_cuenta if cuentas_nombres else 0,
            key="bank_gmail_inbox_cuenta_debito",
        )
    with sel2:
        if tarjetas_nombres:
            tarjeta_credito = st.selectbox(
                "Tarjeta para consumos de crédito",
                tarjetas_nombres,
                index=idx_tarjeta,
                key="bank_gmail_inbox_tarjeta_credito",
            )
        else:
            tarjeta_credito = None
            st.warning("No tienes tarjetas registradas. Crea una tarjeta para importar consumos de crédito.")

    editor_df = df_pending.copy()
    editor_df.insert(0, "importar", False)
    editor_df["categoria_final"] = editor_df["categoria_sugerida"].replace("", "Otros")

    cols_review = [
        "importar",
        "fecha",
        "hora",
        "banco",
        "medio_pago",
        "empresa",
        "monto",
        "moneda",
        "categoria_final",
        "tarjeta_ultimos4",
        "numero_operacion",
        "hash_importacion",
    ]
    editor_df = editor_df[cols_review].copy()

    categorias = sorted(st.session_state.get("categorias", [])) or ["Otros"]

    edited_df = st.data_editor(
        editor_df,
        key=f"bank_gmail_pending_editor_{st.session_state.get('bank_gmail_refresh_token', 0)}",
        hide_index=True,
        use_container_width=True,
        num_rows="fixed",
        column_config={
            "importar": st.column_config.CheckboxColumn("Importar"),
            "fecha": st.column_config.TextColumn("Fecha", disabled=True),
            "hora": st.column_config.TextColumn("Hora", disabled=True),
            "banco": st.column_config.TextColumn("Banco", disabled=True),
            "medio_pago": st.column_config.TextColumn("Medio", disabled=True),
            "empresa": st.column_config.TextColumn("Empresa / comercio", disabled=True),
            "monto": st.column_config.NumberColumn("Monto", format="S/ %.2f", disabled=True),
            "moneda": st.column_config.TextColumn("Moneda", disabled=True),
            "categoria_final": st.column_config.SelectboxColumn("Categoría", options=categorias),
            "tarjeta_ultimos4": st.column_config.TextColumn("Tarjeta", disabled=True),
            "numero_operacion": st.column_config.TextColumn("Operación", disabled=True),
            "hash_importacion": None,
        },
    )

    btn_importar, btn_descartar = st.columns(2)
    with btn_importar:
        importar_sel = st.button(
            "📥 Importar gastos seleccionados",
            type="primary",
            use_container_width=True,
            key="btn_importar_gmail_bancos_pendientes",
        )
    with btn_descartar:
        descartar_sel = st.button(
            "🚫 Descartar seleccionados",
            use_container_width=True,
            key="btn_descartar_gmail_bancos_pendientes",
        )

    if importar_sel:
        seleccionados = edited_df[edited_df["importar"].astype(bool)].copy()
        if seleccionados.empty:
            st.warning("Selecciona al menos un gasto pendiente.")
            st.stop()

        importados = 0
        duplicados = 0
        errores = 0
        ahora_lima = datetime.now(ZoneInfo("America/Lima")).strftime("%Y-%m-%d %H:%M:%S")

        for _, row in seleccionados.iterrows():
            hash_imp = _texto_seguro(row.get("hash_importacion"))
            op = _texto_seguro(row.get("numero_operacion"))
            banco = _texto_seguro(row.get("banco"))
            medio = _texto_seguro(row.get("medio_pago")).capitalize()
            monto = float(row.get("monto", 0) or 0)
            moneda = _texto_seguro(row.get("moneda")) or "PEN"
            empresa = _texto_seguro(row.get("empresa"))
            categoria = _texto_seguro(row.get("categoria_final")) or "Otros"
            fecha = _fecha_desde_texto(row.get("fecha"))
            hora = _texto_seguro(row.get("hora"))
            ult4 = _texto_seguro(row.get("tarjeta_ultimos4"))

            mask = df_all["hash_importacion"].astype(str).eq(hash_imp)

            if monto <= 0 or not empresa:
                errores += 1
                df_all.loc[mask, "resultado_importacion"] = "Error: monto o empresa inválidos"
                continue

            if existe_importacion_bancaria(hash_imp, op, banco):
                duplicados += 1
                df_all.loc[mask, "estado"] = "duplicado"
                df_all.loc[mask, "resultado_importacion"] = "Detectado como duplicado al importar"
                df_all.loc[mask, "fecha_importado_lima"] = ahora_lima
                continue

            if categoria not in st.session_state.get("categorias", []):
                st.session_state.setdefault("categorias", []).append(categoria)
                st.session_state["categorias"] = sorted(list(set(st.session_state["categorias"])))
                _llamar_guardar(guardar_func, "categorias")

            if medio == "Debito":
                nuevo_gasto = {
                    "id": str(uuid.uuid4()),
                    "fecha": fecha.isoformat(),
                    "cuenta_origen": cuentas_map.get(cuenta_debito, "principal"),
                    "cuenta_origen_nombre": cuenta_debito,
                    "categoria": categoria,
                    "descripcion": empresa,
                    "monto": monto,
                    "fuente": "Gmail bancos",
                    "banco": banco,
                    "medio_pago": "Debito",
                    "moneda": moneda,
                    "empresa": empresa,
                    "hora": hora,
                    "tarjeta_ultimos4": ult4,
                    "numero_operacion": op,
                    "hash_importacion": hash_imp,
                }
                st.session_state.setdefault("gastos_diarios", []).append(nuevo_gasto)
                importados += 1

            elif medio == "Credito":
                if not tarjeta_credito:
                    errores += 1
                    df_all.loc[mask, "resultado_importacion"] = "Error: no hay tarjeta de crédito seleccionada"
                    continue

                nuevo_gasto = {
                    "id": str(uuid.uuid4()),
                    "fecha": fecha.isoformat(),
                    "tarjeta_id": tarjetas_map[tarjeta_credito],
                    "tarjeta_nombre": tarjeta_credito,
                    "categoria": categoria,
                    "descripcion": empresa,
                    "moneda": moneda,
                    "monto": monto,
                    "fuente": "Gmail bancos",
                    "banco": banco,
                    "medio_pago": "Credito",
                    "empresa": empresa,
                    "hora": hora,
                    "tarjeta_ultimos4": ult4,
                    "numero_operacion": op,
                    "hash_importacion": hash_imp,
                }
                st.session_state.setdefault("gastos_tarjeta", []).append(nuevo_gasto)
                importados += 1

            else:
                errores += 1
                df_all.loc[mask, "resultado_importacion"] = f"Error: medio no soportado: {medio}"
                continue

            df_all.loc[mask, "estado"] = "importado"
            df_all.loc[mask, "fecha_importado_lima"] = ahora_lima
            df_all.loc[mask, "resultado_importacion"] = "Importado a gastos"

        if importados > 0:
            _llamar_guardar(guardar_func, "gastos_diarios")
            _llamar_guardar(guardar_func, "gastos_tarjeta")

        guardar_pendientes_bancos(df_all, pending_path)
        st.success(f"Importados: {importados} | Duplicados: {duplicados} | Errores: {errores}")
        st.rerun()

    if descartar_sel:
        seleccionados = edited_df[edited_df["importar"].astype(bool)].copy()
        if seleccionados.empty:
            st.warning("Selecciona al menos un gasto pendiente para descartar.")
            st.stop()

        ahora_lima = datetime.now(ZoneInfo("America/Lima")).strftime("%Y-%m-%d %H:%M:%S")
        for _, row in seleccionados.iterrows():
            hash_imp = _texto_seguro(row.get("hash_importacion"))
            mask = df_all["hash_importacion"].astype(str).eq(hash_imp)
            df_all.loc[mask, "estado"] = "descartado"
            df_all.loc[mask, "fecha_importado_lima"] = ahora_lima
            df_all.loc[mask, "resultado_importacion"] = "Descartado manualmente"

        guardar_pendientes_bancos(df_all, pending_path)
        st.success("Gastos seleccionados descartados.")
        st.rerun()

    with st.expander("🗃️ Ver histórico de bandeja Gmail", expanded=expanded_history):
        st.dataframe(df_all.tail(300), use_container_width=True, hide_index=True)