import streamlit as st
from zoneinfo import ZoneInfo
from supabase import create_client
import pandas as pd
import matplotlib.pyplot as plt
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
from datetime import date, timedelta
import uuid

# ==================================================
# CONFIGURACIÓN GENERAL
# ==================================================
hoy_peru = pd.Timestamp.now(
    tz=ZoneInfo("America/Lima")
).date()
st.set_page_config(page_title="Finanzas Personales", layout="wide")

# ==================================================
# CONEXIÓN SUPABASE
# ==================================================
supabase = create_client(
    st.secrets["SUPABASE_URL"],
    st.secrets["SUPABASE_ANON_KEY"]
)

# ==================================================
# LOGIN SUPABASE
# ==================================================
st.sidebar.title("🔐 Acceso")

modo = st.sidebar.radio("Selecciona", ["Iniciar sesión", "Crear cuenta"])
email = st.sidebar.text_input("Email")
password = st.sidebar.text_input("Contraseña", type="password")

if modo == "Crear cuenta":
    if st.sidebar.button("Crear cuenta"):
        try:
            supabase.auth.sign_up({
                "email": email,
                "password": password
            })
            st.sidebar.success("Cuenta creada. Ahora inicia sesión.")
        except Exception as e:
            st.sidebar.error(f"Error: {e}")

if modo == "Iniciar sesión":
    if st.sidebar.button("Ingresar"):
        try:
            res = supabase.auth.sign_in_with_password({
                "email": email,
                "password": password
            })

            st.session_state["user"] = res.user
            st.session_state["access_token"] = res.session.access_token
            st.session_state["refresh_token"] = res.session.refresh_token

            st.sidebar.success("Login exitoso")
            st.rerun()

        except Exception as e:
            st.sidebar.error("Usuario o contraseña incorrectos")

if "user" not in st.session_state:
    st.warning("Debes iniciar sesión para usar la app")
    st.stop()

supabase.auth.set_session(
    st.session_state["access_token"],
    st.session_state["refresh_token"]
)

user_id = st.session_state["user"].id

st.title("📊 Dashboard de Finanzas Personales")
st.caption("Control de ingresos, gastos, tarjetas, cuentas de ahorro y proyección mensual.")


# ==================================================
# PERSISTENCIA JSON A SUPABASE
# ==================================================
def guardar(clave):
    data = st.session_state[clave]

    res = (
        supabase.table("financial_records")
        .select("id")
        .eq("user_id", user_id)
        .eq("tipo", clave)
        .execute()
    )

    if res.data:
        record_id = res.data[0]["id"]
        supabase.table("financial_records").update({
            "data": data
        }).eq("id", record_id).execute()
    else:
        supabase.table("financial_records").insert({
            "user_id": user_id,
            "tipo": clave,
            "data": data
        }).execute()


def cargar(clave):
    res = (
        supabase.table("financial_records")
        .select("data")
        .eq("user_id", user_id)
        .eq("tipo", clave)
        .execute()
    )

    if res.data:
        st.session_state[clave] = res.data[0]["data"]

# ==================================================
# ESTADO GLOBAL
# ==================================================
defaults = {
    "configuracion": {
        "fecha_inicio_sim": None,
        "fecha_fin_sim": None,
        "ahorro_inicial": 0.0
    },
    "ingresos_recurrentes": [],
    "ingresos_puntuales": [],
    "gastos_diarios": [],
    "gastos_fijos": [],
    "tarjetas": [],
    "gastos_tarjeta": [],
    "gastos_recurrentes_tarjeta": [],
    "categorias": [
        "Alimentación","Familia","Supermercado","Tecnología","Salidas y entretenimiento","Movilidad","Ropa","Regalos","Mascotas",
        "Vuelos", "Salud","Entretenimiento","Combustible","Otros"],
"cuentas_ahorro": [],
"transferencias": [],
"pagos_tarjeta": [],
"tipos_cambio": [],
}

for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

claves = [
    "configuracion",
    "ingresos_recurrentes",
    "ingresos_puntuales",
    "gastos_diarios",
    "gastos_fijos",
    "tarjetas",
    "gastos_tarjeta",
    "gastos_recurrentes_tarjeta",
    "cuentas_ahorro",
    "transferencias",
    "categorias",
    "pagos_tarjeta",
    "tipos_cambio",
]
for clave in claves:
    cargar(clave)
# ==================================================
# MIGRACIÓN DE DATOS ANTIGUOS
# ==================================================
def migrar_datos_antiguos():
    cambios = False

    nombre_cuenta_principal = st.session_state["configuracion"].get(
        "nombre_cuenta_principal",
        "Cuenta principal"
    )

    cuentas_debito_map = {nombre_cuenta_principal: "principal"}

    for c in st.session_state["cuentas_ahorro"]:
        cuentas_debito_map[c["nombre"]] = c["id"]

    tarjetas_map = {
        t["nombre"]: t["id"]
        for t in st.session_state["tarjetas"]
    }

    # Migrar gastos diarios débito
    for g in st.session_state["gastos_diarios"]:
        if "cuenta_origen" not in g:
            cuenta_nombre = g.get("cuenta_origen_nombre", nombre_cuenta_principal)
            g["cuenta_origen"] = cuentas_debito_map.get(cuenta_nombre, "principal")
            g["cuenta_origen_nombre"] = cuenta_nombre
            cambios = True

    # Migrar gastos diarios con tarjeta
    for g in st.session_state["gastos_tarjeta"]:
        if "tarjeta_id" not in g:
            tarjeta_nombre = g.get("tarjeta_nombre")

            if tarjeta_nombre in tarjetas_map:
                g["tarjeta_id"] = tarjetas_map[tarjeta_nombre]
                cambios = True

    if cambios:
        guardar("gastos_diarios")
        guardar("gastos_tarjeta")


migrar_datos_antiguos()


# ==================================================
# LIMPIEZA DE GASTOS INVÁLIDOS
# ==================================================
def limpiar_gastos_invalidos():

    original = len(st.session_state["gastos_tarjeta"])

    st.session_state["gastos_tarjeta"] = [
        g for g in st.session_state["gastos_tarjeta"]
        if float(g.get("monto", 0)) > 0
    ]

    nuevos = len(st.session_state["gastos_tarjeta"])

    if nuevos != original:
        guardar("gastos_tarjeta")


limpiar_gastos_invalidos()


# ==================================================
# LIMPIEZA DE GASTOS INVÁLIDOS
# ==================================================
def limpiar_gastos_invalidos():

    original = len(st.session_state["gastos_tarjeta"])

    st.session_state["gastos_tarjeta"] = [
        g for g in st.session_state["gastos_tarjeta"]
        if float(g.get("monto", 0)) > 0
    ]

    nuevos = len(st.session_state["gastos_tarjeta"])

    if nuevos != original:
        guardar("gastos_tarjeta")


limpiar_gastos_invalidos()

# ==================================================
# CONFIGURACIÓN DE SIMULACIÓN Y CUENTAS DE AHORRO
# ==================================================

# ==================================================
# 1. CONFIGURACIÓN INICIAL
# ==================================================
# ══════════════════════════════════════════════════════
# 1. CONFIGURACIÓN INICIAL
# ══════════════════════════════════════════════════════
with st.expander("⚙️ 1. Configuración", expanded=False):

    # ── Simulación ──────────────────────────────────────
    st.markdown("#### 📅 Período de simulación")
    conf = st.session_state["configuracion"]
    col_f1, col_f2 = st.columns(2)
    with col_f1:
        fecha_inicio_sim = st.date_input(
            "Fecha inicio",
            date.fromisoformat(conf["fecha_inicio_sim"]) if conf["fecha_inicio_sim"] else date(2026, 4, 1)
        )
    with col_f2:
        fecha_fin_sim = st.date_input(
            "Fecha fin",
            date.fromisoformat(conf["fecha_fin_sim"]) if conf["fecha_fin_sim"] else date(2026, 12, 31)
        )

    st.divider()

    # ── Cuenta principal ────────────────────────────────
    st.markdown("#### 🏦 Cuenta principal (débito / sueldo)")
    col_cp1, col_cp2, col_cp3 = st.columns(3)
    with col_cp1:
        nombre_cuenta_principal = st.text_input(
            "Nombre de la cuenta",
            conf.get("nombre_cuenta_principal", "Cuenta principal")
        )
    with col_cp2:
        ahorro_inicial = st.number_input(
            "Saldo inicial (S/)",
            min_value=0.0, step=100.0,
            value=float(conf.get("ahorro_inicial", 0.0))
        )
    with col_cp3:
        tipo_cambio_default = st.number_input(
            "TC USD → PEN (defecto)",
            min_value=1.0, step=0.01,
            value=float(conf.get("tipo_cambio_default", 3.85)),
            help="Tipo de cambio que se usa si no se registra uno específico para el mes"
        )

    st.session_state["configuracion"] = {
        "fecha_inicio_sim": fecha_inicio_sim.isoformat(),
        "fecha_fin_sim": fecha_fin_sim.isoformat(),
        "ahorro_inicial": ahorro_inicial,
        "nombre_cuenta_principal": nombre_cuenta_principal,
        "tipo_cambio_default": tipo_cambio_default
    }
    guardar("configuracion")

    st.divider()

    # ── Cuentas de ahorro secundarias ───────────────────
    st.markdown("#### 💰 Cuentas de ahorro secundarias")

    with st.form("form_cuenta_ahorro"):
        col_ca1, col_ca2, col_ca3, col_ca4 = st.columns(4)
        with col_ca1:
            nombre = st.text_input("Nombre de la cuenta", "Ahorro Viajes")
        with col_ca2:
            saldo_ini = st.number_input("Saldo inicial (S/)", min_value=0.0)
        with col_ca3:
            tea = st.number_input("TEA anual (%)", min_value=0.0, max_value=100.0, value=0.0, step=0.1)
        with col_ca4:
            aplica_interes_diario = st.checkbox("Interés diario", value=False)
        if st.form_submit_button("➕ Agregar cuenta"):
            st.session_state["cuentas_ahorro"].append({
                "id": str(uuid.uuid4()),
                "nombre": nombre,
                "saldo_inicial": float(saldo_ini),
                "tea": float(tea),
                "aplica_interes_diario": bool(aplica_interes_diario)
            })
            guardar("cuentas_ahorro")
            st.rerun()

    saldo_principal = st.session_state["configuracion"].get("ahorro_inicial", 0)
    cuentas_resumen = [{"id": "principal", "Cuenta": nombre_cuenta_principal,
                        "Saldo inicial": saldo_principal, "TEA (%)": 0.0,
                        "Interés diario": False, "Tipo": "Principal", "Eliminar": False}]
    for c in st.session_state["cuentas_ahorro"]:
        cuentas_resumen.append({"id": c["id"], "Cuenta": c["nombre"],
                                 "Saldo inicial": c.get("saldo_inicial", 0.0),
                                 "TEA (%)": c.get("tea", 0.0),
                                 "Interés diario": c.get("aplica_interes_diario", False),
                                 "Tipo": "Secundaria", "Eliminar": False})
    df_cuentas_resumen = pd.DataFrame(cuentas_resumen)

    ed_cuentas = st.data_editor(
        df_cuentas_resumen.drop(columns=["id"]),
        use_container_width=True, hide_index=True,
        disabled=["Cuenta", "Saldo inicial", "Tipo"],
        column_config={
            "TEA (%)":        st.column_config.NumberColumn("TEA (%)", min_value=0.0, max_value=100.0, step=0.1),
            "Interés diario": st.column_config.CheckboxColumn("Interés diario"),
            "Eliminar":       st.column_config.CheckboxColumn("🗑")
        },
        key="editor_cuentas_ahorro_resumen"
    )
    if st.button("💾 Guardar cuentas de ahorro"):
        df_original = df_cuentas_resumen.copy()
        df_original["TEA (%)"]        = ed_cuentas["TEA (%)"].values
        df_original["Interés diario"] = ed_cuentas["Interés diario"].values
        df_original["Eliminar"]       = ed_cuentas["Eliminar"].values
        cuentas_actualizadas = []
        for _, row in df_original.iterrows():
            if row["Tipo"] == "Secundaria" and not row["Eliminar"]:
                cuentas_actualizadas.append({
                    "id": row["id"], "nombre": row["Cuenta"],
                    "saldo_inicial": float(row["Saldo inicial"]),
                    "tea": float(row["TEA (%)"]),
                    "aplica_interes_diario": bool(row["Interés diario"])
                })
        st.session_state["cuentas_ahorro"] = cuentas_actualizadas
        guardar("cuentas_ahorro")
        st.rerun()

    st.divider()

    # ── Tarjetas de crédito ──────────────────────────────
    st.markdown("#### 💳 Tarjetas de crédito")

    # Mapa cuentas débito disponibles para pagar tarjeta
    _cuentas_pago_map = {nombre_cuenta_principal: "principal"}
    for _c in st.session_state["cuentas_ahorro"]:
        _cuentas_pago_map[_c["nombre"]] = _c["id"]

    with st.form("form_tarjeta"):
        col_t1, col_t2, col_t3, col_t4 = st.columns(4)
        with col_t1:
            tar_nombre = st.text_input("Nombre tarjeta", "Visa")
        with col_t2:
            tar_dia_cierre = st.number_input("Día de cierre", 1, 31, 20)
        with col_t3:
            tar_dia_pago = st.number_input(
                "Día de pago",
                1, 31, 10,
                help="Día en que se debita de tu cuenta para pagar la tarjeta"
            )
        with col_t4:
            tar_cuenta_pago_nombre = st.selectbox(
                "Cuenta que paga",
                list(_cuentas_pago_map.keys()),
                help="Cuenta débito desde la que se realiza el pago mensual"
            )
        if st.form_submit_button("➕ Agregar tarjeta"):
            st.session_state["tarjetas"].append({
                "id": str(uuid.uuid4()),
                "nombre": tar_nombre,
                "dia_cierre": int(tar_dia_cierre),
                "dia_pago": int(tar_dia_pago),
                "cuenta_pago_id": _cuentas_pago_map[tar_cuenta_pago_nombre],
                "cuenta_pago_nombre": tar_cuenta_pago_nombre
            })
            guardar("tarjetas")
            st.rerun()

    df_tar = pd.DataFrame(st.session_state["tarjetas"])
    if not df_tar.empty:
        # Asegurar que tarjetas viejas tengan cuenta_pago_id
        if "cuenta_pago_id" not in df_tar.columns:
            df_tar["cuenta_pago_id"] = "principal"
            df_tar["cuenta_pago_nombre"] = nombre_cuenta_principal
        df_tar["cuenta_pago_id"]     = df_tar["cuenta_pago_id"].fillna("principal")
        df_tar["cuenta_pago_nombre"] = df_tar["cuenta_pago_nombre"].fillna(nombre_cuenta_principal)
        df_tar["Eliminar"] = False

        ed_tar = st.data_editor(
            df_tar.drop(columns=[c for c in ["id", "cuenta_pago_id"] if c in df_tar.columns]),
            use_container_width=True, hide_index=True,
            column_config={
                "nombre":             st.column_config.TextColumn("Tarjeta"),
                "dia_cierre":         st.column_config.NumberColumn("Día cierre", min_value=1, max_value=31),
                "dia_pago":           st.column_config.NumberColumn("Día de pago (débito)", min_value=1, max_value=31),
                "cuenta_pago_nombre": st.column_config.SelectboxColumn(
                    "Cuenta que paga", options=list(_cuentas_pago_map.keys())
                ),
                "Eliminar": st.column_config.CheckboxColumn("🗑")
            },
            key="editor_tarjetas_credito"
        )
        if st.button("💾 Guardar tarjetas"):
            _df_ed = ed_tar.copy()
            _df_ed["id"] = df_tar["id"].values
            # Reconstruir cuenta_pago_id desde nombre seleccionado
            _df_ed["cuenta_pago_id"] = _df_ed["cuenta_pago_nombre"].apply(
                lambda n: _cuentas_pago_map.get(str(n), "principal")
            )
            _df_ed = _df_ed[_df_ed["Eliminar"] == False].copy()
            _df_ed["dia_cierre"] = pd.to_numeric(_df_ed["dia_cierre"], errors="coerce").fillna(20).astype(int)
            _df_ed["dia_pago"]   = pd.to_numeric(_df_ed["dia_pago"],   errors="coerce").fillna(10).astype(int)
            st.session_state["tarjetas"] = _df_ed.drop(columns=["Eliminar"]).to_dict("records")
            guardar("tarjetas")
            st.rerun()
    else:
        st.info("No hay tarjetas registradas.")

    st.divider()

    # ── Tipo de cambio mensual por tarjeta ───────────────
    st.markdown("#### 💱 Tipo de cambio USD → PEN por mes y tarjeta")
    st.caption("Registra el tipo de cambio del mes en que se realiza el pago de cada tarjeta. "
               "Si no registras un mes, se usa el valor por defecto de arriba.")

    if st.session_state["tarjetas"]:
        _mapa_tar_tc = {t["nombre"]: t["id"] for t in st.session_state["tarjetas"]}

        # Meses dentro del rango de simulación
        _meses_sim = pd.period_range(fecha_inicio_sim, fecha_fin_sim, freq="M")
        _meses_opts = {str(m): str(m) for m in _meses_sim}  # "2026-05" -> "2026-05"

        with st.form("form_tipo_cambio"):
            col_tc1, col_tc2, col_tc3 = st.columns(3)
            with col_tc1:
                tc_tarjeta = st.selectbox("Tarjeta", list(_mapa_tar_tc.keys()), key="sel_tc_tarjeta")
            with col_tc2:
                tc_mes = st.selectbox("Mes de pago", list(_meses_opts.keys()), key="sel_tc_mes")
            with col_tc3:
                tc_valor = st.number_input(
                    "TC USD/PEN", min_value=1.0, step=0.01,
                    value=float(st.session_state["configuracion"].get("tipo_cambio_default", 3.85)),
                    key="inp_tc_valor"
                )
            if st.form_submit_button("➕ Registrar tipo de cambio"):
                # Upsert: si ya existe para esa tarjeta+mes, actualizar
                _tarjeta_id_tc = _mapa_tar_tc[tc_tarjeta]
                _existing = [r for r in st.session_state["tipos_cambio"]
                             if r["tarjeta_id"] == _tarjeta_id_tc and r["anio_mes"] == tc_mes]
                if _existing:
                    for r in st.session_state["tipos_cambio"]:
                        if r["tarjeta_id"] == _tarjeta_id_tc and r["anio_mes"] == tc_mes:
                            r["tipo_de_cambio"] = float(tc_valor)
                else:
                    st.session_state["tipos_cambio"].append({
                        "id": str(uuid.uuid4()),
                        "tarjeta_id": _tarjeta_id_tc,
                        "tarjeta_nombre": tc_tarjeta,
                        "anio_mes": tc_mes,
                        "tipo_de_cambio": float(tc_valor)
                    })
                guardar("tipos_cambio")
                st.rerun()

        _df_tc = pd.DataFrame(st.session_state["tipos_cambio"])
        if not _df_tc.empty:
            _df_tc_show = _df_tc.drop(columns=[c for c in ["id", "tarjeta_id"] if c in _df_tc.columns])
            _df_tc_show["Eliminar"] = False
            _ed_tc = st.data_editor(
                _df_tc_show,
                use_container_width=True, hide_index=True,
                column_config={
                    "tarjeta_nombre": st.column_config.TextColumn("Tarjeta"),
                    "anio_mes":       st.column_config.TextColumn("Mes (YYYY-MM)"),
                    "tipo_de_cambio": st.column_config.NumberColumn("TC USD/PEN", step=0.01),
                    "Eliminar":       st.column_config.CheckboxColumn("🗑")
                },
                key="editor_tipos_cambio"
            )
            if st.button("💾 Guardar tipos de cambio"):
                _df_tc_orig = _df_tc.copy()
                _ed_tc2 = _ed_tc.copy()
                for _col in ["id", "tarjeta_id"]:
                    if _col in _df_tc_orig.columns:
                        _ed_tc2[_col] = _df_tc_orig[_col].values
                _df_tc_save = _ed_tc2[_ed_tc2["Eliminar"] == False].drop(columns=["Eliminar"]).copy()
                _df_tc_save["tipo_de_cambio"] = pd.to_numeric(
                    _df_tc_save["tipo_de_cambio"], errors="coerce"
                ).fillna(tipo_cambio_default)
                st.session_state["tipos_cambio"] = _df_tc_save.to_dict("records")
                guardar("tipos_cambio")
                st.rerun()
        else:
            st.info("Sin tipos de cambio registrados. Se usará el valor por defecto.")
    else:
        st.info("Primero agrega una tarjeta de crédito.")

# ==================================================
# 2. INGRESOS Y GASTOS RECURRENTES / FIJOS
# ==================================================
with st.expander("📌 2. Gastos e ingresos recurrentes / fijos", expanded=False):

    st.markdown("### 💰 Ingresos recurrentes")
    with st.form("form_ingreso_rec"):
        nombre = st.text_input("Nombre", "Sueldo")
        monto = st.number_input(
            "Monto mensual",
            min_value=0.0,
            step=100.0
        )

        fecha_ini = st.date_input(
            "Fecha inicio",
            fecha_inicio_sim
        )

        dia = st.number_input(
            "Día de cobro",
            1,
            31,
            25
        )

        if st.form_submit_button("Agregar ingreso recurrente"):

            st.session_state["ingresos_recurrentes"].append({
                "nombre": nombre,
                "monto": monto,
                "fecha_inicio": fecha_ini.isoformat(),
                "dia_cobro": dia
            })

            guardar("ingresos_recurrentes")
            st.rerun()

    # ==================================================
    # RESUMEN INGRESOS RECURRENTES
    # ==================================================
    df_ing_rec = pd.DataFrame(
        st.session_state["ingresos_recurrentes"]
    )

    if not df_ing_rec.empty:

        df_ing_rec["fecha_inicio"] = pd.to_datetime(
            df_ing_rec["fecha_inicio"],
            errors="coerce"
        ).dt.date

        df_ing_rec["Eliminar"] = False

        st.subheader("📄 Resumen de Ingresos recurrentes registrados")

        ed_ing_rec = st.data_editor(
            df_ing_rec,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Eliminar": st.column_config.CheckboxColumn()
            },
            key="editor_ingresos_recurrentes"
        )

        if st.button("Guardar cambios ingresos recurrentes"):

            df_editado = (
                ed_ing_rec[
                    ed_ing_rec["Eliminar"] == False
                ]
                .drop(columns=["Eliminar"])
                .copy()
            )

            if "fecha_inicio" in df_editado.columns:
                df_editado["fecha_inicio"] = pd.to_datetime(
                    df_editado["fecha_inicio"],
                    errors="coerce"
                ).dt.strftime("%Y-%m-%d")

            st.session_state["ingresos_recurrentes"] = (
                df_editado.to_dict("records")
            )

            guardar("ingresos_recurrentes")
            st.rerun()

    else:
        st.info("No hay ingresos recurrentes registrados.")

    st.divider()
    st.markdown("### 💰 Gastos recurrentes con tarjeta de débito")

    nombre_cuenta_principal = st.session_state["configuracion"].get(
        "nombre_cuenta_principal",
        "Cuenta principal"
    )

    cuentas_debito_map = {nombre_cuenta_principal: "principal"}

    for c in st.session_state["cuentas_ahorro"]:
        cuentas_debito_map[c["nombre"]] = c["id"]
    with st.form("form_gasto_fijo"):

        nombre = st.text_input("Nombre")
        monto = st.number_input(
            "Monto mensual",
            min_value=0.0,
            step=10.0
        )

        fecha_ini = st.date_input(
            "Fecha inicio",
            fecha_inicio_sim
        )

        cuenta_origen_nombre = st.selectbox(
            "Cuenta de origen",
            list(cuentas_debito_map.keys()),
            key="cuenta_origen_gasto_fijo"
        )

        dia = st.number_input(
            "Día de cobro",
            1,
            31,
            5
        )

        if st.form_submit_button("Agregar gasto fijo"):

            st.session_state["gastos_fijos"].append({
                "id": str(uuid.uuid4()),
                "nombre": nombre,
                "monto": float(monto),
                "fecha_inicio": fecha_ini.isoformat(),
                "dia_cobro": int(dia),
                "cuenta_origen": cuentas_debito_map[cuenta_origen_nombre],
                "cuenta_origen_nombre": cuenta_origen_nombre
            })

            guardar("gastos_fijos")
            st.rerun()

    # ==================================================
    # RESUMEN Y EDICIÓN DE GASTOS FIJOS
    # ==================================================
    df_fijos = pd.DataFrame(st.session_state["gastos_fijos"])

    if not df_fijos.empty:

        st.subheader("📄 Resumen de gastos recurrentes de tarjeta de débito registrados")

        df_fijos["fecha_inicio"] = pd.to_datetime(
            df_fijos["fecha_inicio"],
            errors="coerce"
        ).dt.date

        df_fijos["monto"] = pd.to_numeric(
            df_fijos["monto"],
            errors="coerce"
        ).fillna(0)

        df_fijos["Eliminar"] = False

        ed_fijos = st.data_editor(
            df_fijos.drop(columns=[c for c in ["id", "cuenta_origen"] if c in df_fijos.columns]),
            use_container_width=True,
            hide_index=True,
            column_config={
                "nombre": st.column_config.TextColumn("Nombre"),
                "monto": st.column_config.NumberColumn("Monto mensual (S/)", min_value=0.0, step=10.0),
                "dia_cobro": st.column_config.NumberColumn("Día cobro", min_value=1, max_value=31),
                "fecha_inicio": st.column_config.DateColumn("Desde"),
                "cuenta_origen_nombre": st.column_config.TextColumn("Cuenta débito"),
                "Eliminar": st.column_config.CheckboxColumn("🗑")
            },
            key="editor_gastos_fijos"
        )

        if st.button("Guardar cambios gastos fijos"):

            # Restaurar columnas ocultas desde df original
            _df_fijos_orig = df_fijos.copy()
            ed_fijos_full = ed_fijos.copy()
            for _col in ["id", "cuenta_origen"]:
                if _col in _df_fijos_orig.columns and _col not in ed_fijos_full.columns:
                    ed_fijos_full[_col] = _df_fijos_orig[_col].values

            df_editado = (
                ed_fijos_full[
                    ed_fijos_full["Eliminar"] == False
                ]
                .drop(columns=["Eliminar"])
                .copy()
            )

            if "fecha_inicio" in df_editado.columns:
                df_editado["fecha_inicio"] = pd.to_datetime(
                    df_editado["fecha_inicio"],
                    errors="coerce"
                ).dt.strftime("%Y-%m-%d")

            # Sanear campos que en registros viejos pueden ser NaN/None
            # (causan ValueError al serializar a JSON con allow_nan=False)
            if "id" not in df_editado.columns:
                df_editado["id"] = [str(uuid.uuid4()) for _ in range(len(df_editado))]
            else:
                df_editado["id"] = df_editado["id"].apply(
                    lambda x: str(uuid.uuid4())
                    if (x is None or (isinstance(x, float) and pd.isna(x)) or str(x) in ["", "None", "nan"])
                    else str(x)
                )

            if "cuenta_origen" not in df_editado.columns:
                df_editado["cuenta_origen"] = "principal"
            else:
                df_editado["cuenta_origen"] = df_editado["cuenta_origen"].apply(
                    lambda x: "principal"
                    if (x is None or (isinstance(x, float) and pd.isna(x)) or str(x) in ["", "None", "nan"])
                    else str(x)
                )

            if "cuenta_origen_nombre" not in df_editado.columns:
                df_editado["cuenta_origen_nombre"] = nombre_cuenta_principal
            else:
                df_editado["cuenta_origen_nombre"] = df_editado["cuenta_origen_nombre"].apply(
                    lambda x: nombre_cuenta_principal
                    if (x is None or (isinstance(x, float) and pd.isna(x)) or str(x) in ["", "None", "nan"])
                    else str(x)
                )

            if "dia_cobro" in df_editado.columns:
                df_editado["dia_cobro"] = (
                    pd.to_numeric(df_editado["dia_cobro"], errors="coerce")
                    .fillna(1).astype(int)
                )

            if "monto" in df_editado.columns:
                df_editado["monto"] = (
                    pd.to_numeric(df_editado["monto"], errors="coerce").fillna(0.0)
                )

            st.session_state["gastos_fijos"] = (
                df_editado.to_dict("records")
            )

            guardar("gastos_fijos")
            st.rerun()

    else:
        st.info("No hay gastos fijos registrados.")

    st.divider()
    st.markdown("### 💳 Gastos recurrentes con tarjeta de crédito")

    if st.session_state["tarjetas"]:

        mapa_tarjetas = {
            t["nombre"]: t["id"]
            for t in st.session_state["tarjetas"]
        }

        # ==================================================
        # GASTOS RECURRENTES CON TARJETA
        # ==================================================
        
        with st.form("form_gasto_recurrente_tarjeta"):

            nombre = st.text_input(
                "Nombre del gasto recurrente",
                "Gimnasio"
            )

            tarjeta_nombre = st.selectbox(
                "Tarjeta asociada",
                list(mapa_tarjetas.keys()),
                key="tarjeta_gasto_recurrente"
            )

            categoria = st.selectbox(
                "Categoría",
                st.session_state["categorias"] + ["➕ Nueva"],
                key="categoria_gasto_rec_tarjeta"
            )

            if categoria == "➕ Nueva":
                categoria = st.text_input(
                    "Nueva categoría",
                    key="nueva_categoria_gasto_rec_tarjeta"
                )

            moneda_rec = st.selectbox(
                "Moneda",
                ["PEN", "USD"],
                key="moneda_gasto_recurrente_tarjeta",
                help="USD: el monto se convierte a soles usando el tipo de cambio del día de pago"
            )

            monto = st.number_input(
                "Monto mensual",
                min_value=0.0,
                step=10.0,
                key="monto_gasto_recurrente_tarjeta"
            )

            dia_cargo = st.number_input(
                "Día de cargo mensual",
                1,
                31,
                15,
                key="dia_cargo_gasto_recurrente_tarjeta"
            )

            fecha_inicio = st.date_input(
                "Fecha inicio",
                fecha_inicio_sim,
                key="fecha_inicio_gasto_recurrente_tarjeta"
            )

            fecha_fin = st.date_input(
                "Fecha fin opcional",
                fecha_fin_sim,
                key="fecha_fin_gasto_recurrente_tarjeta"
            )

            if st.form_submit_button("Agregar gasto recurrente"):

                if categoria not in st.session_state["categorias"]:
                    st.session_state["categorias"].append(categoria)
                    guardar("categorias")

                st.session_state["gastos_recurrentes_tarjeta"].append({
                    "id": str(uuid.uuid4()),
                    "nombre": nombre,
                    "tarjeta_id": mapa_tarjetas[tarjeta_nombre],
                    "tarjeta_nombre": tarjeta_nombre,
                    "categoria": categoria,
                    "moneda": moneda_rec,
                    "monto": float(monto),
                    "dia_cargo": int(dia_cargo),
                    "fecha_inicio": fecha_inicio.isoformat(),
                    "fecha_fin": fecha_fin.isoformat()
                })

                guardar("gastos_recurrentes_tarjeta")
                st.rerun()

        # ==================================================
        # RESUMEN GASTOS RECURRENTES CON TARJETA
        # ==================================================
        df_grt = pd.DataFrame(
            st.session_state["gastos_recurrentes_tarjeta"]
        )

        if not df_grt.empty:

            st.subheader("📄 Resumen de gastos recurrentes con tarjeta de crédito registrados")

            df_grt["fecha_inicio"] = pd.to_datetime(
                df_grt["fecha_inicio"],
                errors="coerce"
            ).dt.date

            df_grt["fecha_fin"] = pd.to_datetime(
                df_grt["fecha_fin"],
                errors="coerce"
            ).dt.date

            df_grt["monto"] = pd.to_numeric(
                df_grt["monto"],
                errors="coerce"
            ).fillna(0)

            df_grt["Eliminar"] = False

            columnas_ocultas = [
                "id",
                "tarjeta_id"
]

            df_grt_show = df_grt.drop(
                columns=[c for c in columnas_ocultas if c in df_grt.columns]
)

            ed_grt = st.data_editor(
                df_grt_show,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "nombre": st.column_config.TextColumn("Nombre"),
                    "tarjeta_nombre": st.column_config.TextColumn("Tarjeta"),
                    "categoria": st.column_config.TextColumn("Categoría"),
                    "moneda": st.column_config.SelectboxColumn("Moneda", options=["PEN", "USD"]),
                    "monto": st.column_config.NumberColumn("Monto mensual", min_value=0.0, step=10.0),
                    "dia_cargo": st.column_config.NumberColumn("Día cargo", min_value=1, max_value=31),
                    "fecha_inicio": st.column_config.DateColumn("Desde"),
                    "fecha_fin": st.column_config.DateColumn("Hasta"),
                    "Eliminar": st.column_config.CheckboxColumn("🗑")
                },
                key="editor_gastos_recurrentes_tarjeta"
            )

            if st.button("Guardar cambios gastos recurrentes"):

                # Recuperar IDs originales
                df_temp = df_grt.copy()

                # Reinsertar columnas ocultas
                for col in ["id", "tarjeta_id"]:
                    if col in df_temp.columns:
                        ed_grt[col] = df_temp[col].values

                df_editado = (
                    ed_grt[
                        ed_grt["Eliminar"] == False
    ]
                    .drop(columns=["Eliminar"])
                    .copy()
)

                if "fecha_inicio" in df_editado.columns:
                    df_editado["fecha_inicio"] = pd.to_datetime(
                        df_editado["fecha_inicio"],
                        errors="coerce"
                    ).dt.strftime("%Y-%m-%d")

                if "fecha_fin" in df_editado.columns:
                    df_editado["fecha_fin"] = pd.to_datetime(
                        df_editado["fecha_fin"],
                        errors="coerce"
                    ).dt.strftime("%Y-%m-%d")

                st.session_state["gastos_recurrentes_tarjeta"] = (
                    df_editado.to_dict("records")
                )

                guardar("gastos_recurrentes_tarjeta")
                st.rerun()

        else:
            st.info("No hay gastos recurrentes con tarjeta registrados.")

# ==================================================
# 3. MOVIMIENTOS Y GASTOS VARIABLES / PUNTUALES
# ==================================================


with st.expander("🧾 3. Movimientos y gastos variables", expanded=False):

    # ==================================================
    # 3.1 GASTOS DIARIOS DÉBITO Y CRÉDITO
    # ==================================================
    with st.expander("🧾 3.1 Gastos diarios débito y crédito", expanded=True):

        # ==================================================
        # GASTOS DIARIOS DÉBITO
        # ==================================================
        st.markdown("### 🧾 Gastos diarios débito")

        nombre_cuenta_principal = st.session_state["configuracion"].get(
            "nombre_cuenta_principal",
            "Cuenta principal"
        )

        cuentas_debito_map = {nombre_cuenta_principal: "principal"}

        for c in st.session_state["cuentas_ahorro"]:
            cuentas_debito_map[c["nombre"]] = c["id"]

        with st.form("form_gasto_diario", clear_on_submit=True):

            fecha = st.date_input(
                "Fecha",
                value=hoy_peru,
                key="fecha_gasto_diario_debito"
            )

            cuenta_origen_nombre = st.selectbox(
                "Cuenta de origen",
                list(cuentas_debito_map.keys()),
                key="cuenta_origen_gasto_diario"
            )

            categoria_sel = st.selectbox(
                "Categoría",
                sorted(st.session_state["categorias"]) + ["➕ Nueva categoría"],
                key="categoria_gasto_diario_debito"
            )

            if categoria_sel == "➕ Nueva categoría":
                nueva_categoria = st.text_input(
                    "Nueva categoría",
                    key="nueva_categoria_gasto_diario_debito"
                )
                categoria = nueva_categoria.strip()
            else:
                categoria = categoria_sel

            descripcion = st.text_input("Descripción")

            monto = st.number_input(
                "Monto",
                min_value=0.0,
                step=1.0,
                key="monto_gasto_diario_debito"
            )

            submitted = st.form_submit_button("Agregar gasto")

            if submitted:

                if not categoria:
                    st.error("Debes ingresar una categoría válida.")
                    st.stop()

                if categoria not in st.session_state["categorias"]:
                    st.session_state["categorias"].append(categoria)
                    st.session_state["categorias"] = sorted(
                        list(set(st.session_state["categorias"]))
                    )
                    guardar("categorias")

                nuevo_gasto = {
                    "id": str(uuid.uuid4()),
                    "fecha": fecha.isoformat(),
                    "cuenta_origen": cuentas_debito_map.get(cuenta_origen_nombre, "principal"),
                    "cuenta_origen_nombre": cuenta_origen_nombre,
                    "categoria": categoria,
                    "descripcion": descripcion,
                    "monto": float(monto)
                }

                st.session_state["gastos_diarios"].append(nuevo_gasto)
                guardar("gastos_diarios")
                st.success("Gasto débito agregado correctamente")
                st.rerun()

        # ==================================================
        # RESUMEN GASTOS DIARIOS DÉBITO
        # ==================================================
        df_g = pd.DataFrame(st.session_state["gastos_diarios"])

        if not df_g.empty:

            st.subheader("📄 Resumen gastos diarios débito")

            if "id" not in df_g.columns:
                df_g["id"] = None

            df_g["id"] = df_g["id"].apply(
                lambda x: str(uuid.uuid4()) if pd.isna(x) or x in ["", "None", None] else x
            )

            if "cuenta_origen" not in df_g.columns:
                df_g["cuenta_origen"] = "principal"

            if "cuenta_origen_nombre" not in df_g.columns:
                df_g["cuenta_origen_nombre"] = nombre_cuenta_principal

            df_g["cuenta_origen"] = df_g["cuenta_origen"].fillna("principal")
            df_g["cuenta_origen_nombre"] = df_g["cuenta_origen_nombre"].fillna(
                nombre_cuenta_principal
            )

            df_g["fecha"] = pd.to_datetime(
                df_g["fecha"],
                errors="coerce"
            )

            df_g["monto"] = pd.to_numeric(
                df_g["monto"],
                errors="coerce"
            ).fillna(0)

            df_g = df_g.sort_values(
                by="fecha",
                ascending=False
            ).reset_index(drop=True)

            df_g["fecha"] = df_g["fecha"].dt.date
            df_g["Eliminar"] = False

            columnas_ocultas = ["id", "cuenta_origen"]

            df_g_show = df_g.drop(
                columns=[c for c in columnas_ocultas if c in df_g.columns]
            )

            ed_g = st.data_editor(
                df_g_show,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "fecha": st.column_config.DateColumn("Fecha"),
                    "cuenta_origen_nombre": st.column_config.TextColumn("Cuenta"),
                    "categoria": st.column_config.TextColumn("Categoría"),
                    "descripcion": st.column_config.TextColumn("Descripción"),
                    "monto": st.column_config.NumberColumn("Monto (S/)", min_value=0.0, step=1.0),
                    "Eliminar": st.column_config.CheckboxColumn("🗑")
                },
                key="editor_gastos_debito"
            )

            if st.button("Guardar cambios gastos débito / ahorros"):

                df_temp = df_g.copy()

                for col in ["id", "cuenta_origen"]:
                    if col in df_temp.columns:
                        ed_g[col] = df_temp[col].values

                df_editado = (
                    ed_g[
                        ed_g["Eliminar"] == False
                    ]
                    .drop(columns=["Eliminar"])
                    .copy()
                )

                if "fecha" in df_editado.columns:
                    df_editado["fecha"] = pd.to_datetime(
                        df_editado["fecha"],
                        errors="coerce"
                    ).dt.strftime("%Y-%m-%d")

                df_editado = df_editado.sort_values(
                    "fecha",
                    ascending=False
                )

                st.session_state["gastos_diarios"] = (
                    df_editado.to_dict("records")
                )

                guardar("gastos_diarios")
                st.rerun()

        else:
            st.info("No hay gastos débito registrados.")

        st.divider()

        # ==================================================
        # GASTOS DIARIOS CON TARJETA DE CRÉDITO
        # ==================================================
        st.markdown("### 💳 Gastos diarios con tarjeta de crédito")

        if st.session_state["tarjetas"]:

            mapa_tarjetas = {
                t["nombre"]: t["id"]
                for t in st.session_state["tarjetas"]
            }

            with st.form("form_gasto_tarjeta", clear_on_submit=True):

                fecha = st.date_input(
                    "Fecha gasto",
                    value=hoy_peru,
                    key="fecha_gasto_tarjeta"
                )

                tarjeta_nombre = st.selectbox(
                    "Tarjeta",
                    list(mapa_tarjetas.keys()),
                    key="tarjeta_gasto_diario"
                )

                categoria_sel = st.selectbox(
                    "Categoría",
                    sorted(st.session_state["categorias"]) + ["➕ Nueva categoría"],
                    key="categoria_gasto_tarjeta"
                )

                if categoria_sel == "➕ Nueva categoría":
                    nueva_categoria = st.text_input(
                        "Nueva categoría",
                        key="nueva_categoria_gasto_tarjeta"
                    )
                    categoria = nueva_categoria.strip()
                else:
                    categoria = categoria_sel

                descripcion = st.text_input(
                    "Descripción",
                    key="descripcion_gasto_tarjeta"
                )

                moneda_gt = st.selectbox(
                    "Moneda",
                    ["PEN", "USD"],
                    key="moneda_gasto_tarjeta",
                    help="USD: el monto se convierte a soles usando el tipo de cambio del día de pago"
                )

                monto = st.number_input(
                    "Monto",
                    min_value=0.0,
                    step=1.0,
                    key="monto_gasto_tarjeta"
                )

                if st.form_submit_button("Agregar gasto tarjeta"):

                    if not categoria:
                        st.error("Debes ingresar una categoría válida.")
                        st.stop()

                    if categoria not in st.session_state["categorias"]:
                        st.session_state["categorias"].append(categoria)
                        st.session_state["categorias"] = sorted(
                            list(set(st.session_state["categorias"]))
                        )
                        guardar("categorias")

                    nuevo_gasto_tarjeta = {
                        "id": str(uuid.uuid4()),
                        "fecha": fecha.isoformat(),
                        "tarjeta_id": mapa_tarjetas[tarjeta_nombre],
                        "tarjeta_nombre": tarjeta_nombre,
                        "categoria": categoria,
                        "descripcion": descripcion,
                        "moneda": moneda_gt,
                        "monto": float(monto)
                    }

                    st.session_state["gastos_tarjeta"].append(nuevo_gasto_tarjeta)
                    guardar("gastos_tarjeta")

                    st.success("Gasto con tarjeta agregado correctamente")
                    st.rerun()

            # ==================================================
            # RESUMEN GASTOS DIARIOS CON TARJETA DE CRÉDITO
            # ==================================================
            df_gt = pd.DataFrame(st.session_state["gastos_tarjeta"])

            if not df_gt.empty:

                st.subheader("📄 Resumen gastos diarios tarjeta crédito")

                if "id" not in df_gt.columns:
                    df_gt["id"] = None

                df_gt["id"] = df_gt["id"].apply(
                    lambda x: str(uuid.uuid4()) if pd.isna(x) or x in ["", "None", None] else x
                )

                df_gt = df_gt.drop_duplicates(
                    subset=[
                        "fecha",
                        "tarjeta_id",
                        "tarjeta_nombre",
                        "categoria",
                        "descripcion",
                        "monto"
                    ],
                    keep="first"
                )

                df_gt["fecha"] = pd.to_datetime(
                    df_gt["fecha"],
                    errors="coerce"
                )

                df_gt["monto"] = pd.to_numeric(
                    df_gt["monto"],
                    errors="coerce"
                ).fillna(0)

                df_gt = df_gt.sort_values(
                    "fecha",
                    ascending=False
                ).reset_index(drop=True)

                df_gt["fecha"] = df_gt["fecha"].dt.date
                df_gt["Eliminar"] = False

                _df_gt_save = (
                    df_gt.drop(columns=["Eliminar"])
                    .assign(fecha=lambda d: pd.to_datetime(d["fecha"]).dt.strftime("%Y-%m-%d"))
                    .copy()
                )
                # Sanear campos que pueden tener NaN (allow_nan=False en httpx)
                _nan_defaults = {
                    "moneda": "PEN", "descripcion": "", "categoria": "",
                    "tarjeta_nombre": "", "tarjeta_id": ""
                }
                for _col, _default in _nan_defaults.items():
                    if _col in _df_gt_save.columns:
                        _df_gt_save[_col] = _df_gt_save[_col].apply(
                            lambda x: _default if (x is None or (isinstance(x, float) and pd.isna(x))
                                                   or str(x) in ["", "None", "nan"]) else str(x)
                        )
                if "monto" in _df_gt_save.columns:
                    _df_gt_save["monto"] = pd.to_numeric(_df_gt_save["monto"], errors="coerce").fillna(0.0)
                if "id" in _df_gt_save.columns:
                    _df_gt_save["id"] = _df_gt_save["id"].apply(
                        lambda x: str(uuid.uuid4()) if (x is None or (isinstance(x, float) and pd.isna(x))
                                                        or str(x) in ["", "None", "nan"]) else str(x)
                    )
                st.session_state["gastos_tarjeta"] = _df_gt_save.to_dict("records")
                guardar("gastos_tarjeta")

                ed_gt = st.data_editor(
                    df_gt,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "id": None,
                        "tarjeta_id": None,
                        "fecha": st.column_config.DateColumn("Fecha"),
                        "tarjeta_nombre": st.column_config.TextColumn("Tarjeta"),
                        "categoria": st.column_config.TextColumn("Categoría"),
                        "descripcion": st.column_config.TextColumn("Descripción"),
                        "moneda": st.column_config.SelectboxColumn("Moneda", options=["PEN", "USD"]),
                        "monto": st.column_config.NumberColumn("Monto", min_value=0.0, step=1.0),
                        "Eliminar": st.column_config.CheckboxColumn("🗑")
                    },
                    key="editor_gastos_tarjeta"
                )

                if st.button("Guardar cambios gastos tarjeta"):

                    df_editado = ed_gt[ed_gt["Eliminar"] == False].copy()
                    df_editado = df_editado.drop(columns=["Eliminar"])

                    df_editado["fecha"] = pd.to_datetime(
                        df_editado["fecha"], errors="coerce"
                    ).dt.strftime("%Y-%m-%d")

                    df_editado = df_editado.sort_values("fecha", ascending=False)

                    # Sanear NaN antes de guardar
                    _nan_defs2 = {"moneda": "PEN", "descripcion": "", "categoria": "",
                                  "tarjeta_nombre": "", "tarjeta_id": ""}
                    for _c, _d in _nan_defs2.items():
                        if _c in df_editado.columns:
                            df_editado[_c] = df_editado[_c].apply(
                                lambda x: _d if (x is None or (isinstance(x, float) and pd.isna(x))
                                                 or str(x) in ["", "None", "nan"]) else str(x)
                            )
                    if "monto" in df_editado.columns:
                        df_editado["monto"] = pd.to_numeric(df_editado["monto"], errors="coerce").fillna(0.0)

                    st.session_state["gastos_tarjeta"] = df_editado.to_dict("records")
                    guardar("gastos_tarjeta")
                    st.rerun()

            else:
                st.info("No hay gastos diarios con tarjeta registrados.")

        else:
            st.warning("Primero debes registrar una tarjeta de crédito.")

    # ==================================================
    # 3.2 INGRESOS PUNTUALES Y TRANSFERENCIAS
    # ==================================================
    with st.expander("💵 3.2 Ingresos puntuales y transferencias", expanded=False):

        # ==================================================
        # INGRESOS PUNTUALES
        # ==================================================
        st.markdown("### 💵 Ingresos puntuales")

        with st.form("form_ingreso_puntual"):

            concepto = st.text_input("Concepto")

            fecha = st.date_input(
                "Fecha",
                value=hoy_peru,
                key="fecha_ingreso_puntual"
            )

            monto = st.number_input(
                "Monto",
                min_value=0.0
            )

            if st.form_submit_button("Agregar ingreso puntual"):

                st.session_state["ingresos_puntuales"].append({
                    "concepto": concepto,
                    "fecha": fecha.isoformat(),
                    "monto": monto
                })

                guardar("ingresos_puntuales")
                st.rerun()

        # ==================================================
        # RESUMEN INGRESOS PUNTUALES
        # ==================================================
        df_ing_punt = pd.DataFrame(
            st.session_state["ingresos_puntuales"]
        )

        if not df_ing_punt.empty:

            df_ing_punt["fecha"] = pd.to_datetime(
                df_ing_punt["fecha"],
                errors="coerce"
            ).dt.date

            df_ing_punt = df_ing_punt.sort_values(
                by="fecha",
                ascending=False
            )

            df_ing_punt["Eliminar"] = False

            st.subheader("📄 Ingresos puntuales registrados")

            ed_ing_punt = st.data_editor(
                df_ing_punt,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Eliminar": st.column_config.CheckboxColumn()
                },
                key="editor_ingresos_puntuales"
            )

            if st.button("Guardar cambios ingresos puntuales"):

                df_editado = (
                    ed_ing_punt[
                        ed_ing_punt["Eliminar"] == False
                    ]
                    .drop(columns=["Eliminar"])
                    .copy()
                )

                if "fecha" in df_editado.columns:
                    df_editado["fecha"] = pd.to_datetime(
                        df_editado["fecha"],
                        errors="coerce"
                    ).dt.strftime("%Y-%m-%d")

                df_editado = df_editado.sort_values(
                    "fecha",
                    ascending=False
                )

                st.session_state["ingresos_puntuales"] = (
                    df_editado.to_dict("records")
                )

                guardar("ingresos_puntuales")
                st.rerun()

        else:
            st.info("No hay ingresos puntuales registrados.")

        st.divider()

        # ==================================================
        # TRANSFERENCIAS ENTRE CUENTAS
        # ==================================================
        st.markdown("### 🔁 Transferencias entre cuentas")

        nombre_cuenta_principal = st.session_state["configuracion"].get(
            "nombre_cuenta_principal",
            "Cuenta principal"
        )

        cuentas_map = {nombre_cuenta_principal: "principal"}

        for c in st.session_state["cuentas_ahorro"]:
            cuentas_map[c["nombre"]] = c["id"]

        with st.form("form_transferencia"):

            fecha = st.date_input(
                "Fecha",
                value=hoy_peru,
                key="fecha_transferencia"
            )

            origen = st.selectbox(
                "Cuenta origen",
                list(cuentas_map.keys()),
                key="transferencia_origen"
            )

            destino = st.selectbox(
                "Cuenta destino",
                list(cuentas_map.keys()),
                key="transferencia_destino"
            )

            monto = st.number_input(
                "Monto",
                min_value=0.0,
                key="monto_transferencia"
            )

            if st.form_submit_button("Registrar transferencia") and origen != destino:
                st.session_state["transferencias"].append({
                    "fecha": fecha.isoformat(),
                    "origen": cuentas_map[origen],
                    "destino": cuentas_map[destino],
                    "monto": monto
                })
                guardar("transferencias")
                st.rerun()

        # ==================================================
        # RESUMEN TRANSFERENCIAS
        # ==================================================
        df_transf = pd.DataFrame(st.session_state["transferencias"])

        if not df_transf.empty:

            df_transf["fecha"] = pd.to_datetime(
                df_transf["fecha"],
                errors="coerce"
            ).dt.date

            df_transf = df_transf.sort_values(
                by="fecha",
                ascending=False
            )

            df_transf["Eliminar"] = False

            st.subheader("📄 Historial de transferencias")

            ed = st.data_editor(
                df_transf,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Eliminar": st.column_config.CheckboxColumn()
                },
                key="editor_transferencias"
            )

            if st.button("Guardar cambios transferencias"):

                df_editado = (
                    ed[ed["Eliminar"] == False]
                    .drop(columns=["Eliminar"])
                    .copy()
                )

                if "fecha" in df_editado.columns:
                    df_editado["fecha"] = pd.to_datetime(
                        df_editado["fecha"],
                        errors="coerce"
                    ).dt.strftime("%Y-%m-%d")

                df_editado = df_editado.sort_values(
                    "fecha",
                    ascending=False
                )

                st.session_state["transferencias"] = df_editado.to_dict("records")

                guardar("transferencias")
                st.rerun()

        else:
            st.info("No hay transferencias registradas.")

# ==================================================
# 4. CÁLCULOS BASE
# ==================================================
def obtener_ciclo_tarjeta(fecha, dia_cierre):
    fecha = pd.to_datetime(fecha)

    if fecha.day <= dia_cierre:
        cierre = fecha.replace(day=dia_cierre)
    else:
        cierre = (fecha + pd.DateOffset(months=1)).replace(day=dia_cierre)

    inicio = cierre - pd.DateOffset(months=1) + timedelta(days=1)

    return inicio.date(), cierre.date()


# ==================================================
# PREPARAR GASTOS DE TARJETA PARA CÁLCULOS Y GRÁFICOS
# ==================================================
df_gt = pd.DataFrame(st.session_state["gastos_tarjeta"])

if not df_gt.empty:
    df_gt["fecha"] = pd.to_datetime(df_gt["fecha"], errors="coerce")
    df_gt["monto"] = pd.to_numeric(df_gt["monto"], errors="coerce").fillna(0)
    df_gt["tipo_gasto"] = "Crédito diario"
    if "moneda" not in df_gt.columns:
        df_gt["moneda"] = "PEN"
    else:
        df_gt["moneda"] = df_gt["moneda"].fillna("PEN")

gastos_tarjeta_recurrentes_expandido = []

for g in st.session_state["gastos_recurrentes_tarjeta"]:
    fecha_ini = pd.to_datetime(g["fecha_inicio"])
    fecha_fin_g = pd.to_datetime(g["fecha_fin"])

    for mes in pd.date_range(fecha_inicio_sim, fecha_fin_sim, freq="MS"):
        try:
            fecha_cargo = mes.replace(day=int(g["dia_cargo"]))

            if fecha_cargo >= fecha_ini and fecha_cargo <= fecha_fin_g:
                gastos_tarjeta_recurrentes_expandido.append({
                    "fecha": fecha_cargo,
                    "tarjeta_id": g["tarjeta_id"],
                    "tarjeta_nombre": g["tarjeta_nombre"],
                    "categoria": g["categoria"],
                    "descripcion": g["nombre"],
                    "moneda": g.get("moneda", "PEN"),
                    "monto": float(g["monto"]),
                    "tipo_gasto": "Crédito recurrente"
                })
        except:
            pass

df_grt_expandido = pd.DataFrame(gastos_tarjeta_recurrentes_expandido)

if not df_grt_expandido.empty:
    df_grt_expandido["fecha"] = pd.to_datetime(
        df_grt_expandido["fecha"],
        errors="coerce"
    )
    df_grt_expandido["monto"] = pd.to_numeric(
        df_grt_expandido["monto"],
        errors="coerce"
    ).fillna(0)

if not df_gt.empty and not df_grt_expandido.empty:
    df_gt_calc = pd.concat([df_gt, df_grt_expandido], ignore_index=True)
elif not df_gt.empty:
    df_gt_calc = df_gt.copy()
elif not df_grt_expandido.empty:
    df_gt_calc = df_grt_expandido.copy()
else:
    df_gt_calc = pd.DataFrame(
        columns=[
            "fecha",
            "tarjeta_id",
            "tarjeta_nombre",
            "categoria",
            "descripcion",
            "monto",
            "tipo_gasto"
        ]
    )
# ==================================================
# CÁLCULOS FINALES Y GRÁFICO (CON SALDO RESALTADO ✅)
# ==================================================
fechas = pd.date_range(fecha_inicio_sim, fecha_fin_sim, freq="D")

# Ingresos y gastos diarios
if not df_g.empty:
    df_g["fecha"] = pd.to_datetime(df_g["fecha"], errors="coerce")
    df_gt = df_gt.sort_values(
    by="fecha",
    ascending=False
)
    g_diarios_principal = (
        df_g[df_g.get("cuenta_origen", "principal") == "principal"]
        .groupby("fecha")["monto"]
        .sum()
        .reindex(fechas, fill_value=0)
    )
else:
    g_diarios_principal = pd.Series(0.0, index=fechas)

g_fijos = pd.Series(0.0, index=fechas)

for _, r in df_fijos.iterrows():
    cuenta_origen = r.get("cuenta_origen", "principal")

    if cuenta_origen != "principal":
        continue

    for mes in pd.date_range(fecha_inicio_sim, fecha_fin_sim, freq="MS"):
        try:
            f = mes.replace(day=int(r["dia_cobro"]))

            if f >= pd.to_datetime(r["fecha_inicio"]) and f in g_fijos.index:
                g_fijos.loc[f] += float(r["monto"])
        except:
            pass
    for mes in pd.date_range(fecha_inicio_sim, fecha_fin_sim, freq="MS"):
        try:
            f = mes.replace(day=int(r["dia_cobro"]))
            if f >= pd.to_datetime(r["fecha_inicio"]) and f in g_fijos.index:
                g_fijos.loc[f] += r["monto"]
        except:
            pass

ing_rec = pd.Series(0.0, index=fechas)
for _, r in df_ing_rec.iterrows():
    for mes in pd.date_range(fecha_inicio_sim, fecha_fin_sim, freq="MS"):
        try:
            f = mes.replace(day=int(r["dia_cobro"]))
            if f >= pd.to_datetime(r["fecha_inicio"]) and f in ing_rec.index:
                ing_rec.loc[f] += r["monto"]
        except:
            pass

ing_punt = pd.Series(0.0, index=fechas)
for _, r in df_ing_punt.iterrows():
    f = pd.to_datetime(r["fecha"])
    if f in ing_punt.index:
        ing_punt.loc[f] += r["monto"]

# Lookup tipo_de_cambio: (tarjeta_id, "YYYY-MM") -> float
_tc_lookup = {}
for _tc in st.session_state.get("tipos_cambio", []):
    _tc_lookup[(_tc["tarjeta_id"], _tc["anio_mes"])] = float(_tc["tipo_de_cambio"])
# Compatibilidad con pagos_tarjeta antiguo (por ciclo_cierre)
for _p in st.session_state.get("pagos_tarjeta", []):
    _ym = str(_p.get("ciclo_cierre", ""))[:7]  # "2026-05"
    _key_old = (_p["tarjeta_id"], _ym)
    if _key_old not in _tc_lookup:
        _tc_lookup[_key_old] = float(_p.get("tipo_de_cambio", 3.85))

_tc_default = float(st.session_state["configuracion"].get("tipo_cambio_default", 3.85))

# egresos por cuenta: dict cuenta_id -> Series
egresos_tarjeta_por_cuenta = {}

if not df_gt_calc.empty:
    for t in st.session_state.tarjetas:
        # Cuenta que paga esta tarjeta (nuevo campo, fallback a "principal")
        _cuenta_pago_t = t.get("cuenta_pago_id", "principal") or "principal"
        df_t = df_gt_calc[df_gt_calc["tarjeta_id"] == t["id"]]
        for _, g in df_t.iterrows():
            _, cierre = obtener_ciclo_tarjeta(g["fecha"], t["dia_cierre"])
            fecha_pago = (pd.Timestamp(cierre) + pd.DateOffset(months=1)).replace(day=t["dia_pago"])
            # Mes del pago para buscar tipo de cambio
            _anio_mes_pago = fecha_pago.strftime("%Y-%m")
            tc = _tc_lookup.get((t["id"], _anio_mes_pago), _tc_default)
            moneda_g = g.get("moneda", "PEN")
            monto_pen = float(g["monto"]) * tc if moneda_g == "USD" else float(g["monto"])
            if _cuenta_pago_t not in egresos_tarjeta_por_cuenta:
                egresos_tarjeta_por_cuenta[_cuenta_pago_t] = pd.Series(0.0, index=fechas)
            if fecha_pago in egresos_tarjeta_por_cuenta[_cuenta_pago_t].index:
                egresos_tarjeta_por_cuenta[_cuenta_pago_t].loc[fecha_pago] += monto_pen

# egresos de cuenta principal (para saldo principal y gráfico)
egresos_tarjeta = egresos_tarjeta_por_cuenta.get("principal", pd.Series(0.0, index=fechas))

saldo = (
    ahorro_inicial
    + ing_rec.cumsum()
    + ing_punt.cumsum()
    - g_diarios_principal.cumsum()
    - g_fijos.cumsum()
    - egresos_tarjeta.cumsum()
)


# ✅ Serie base de la cuenta principal (nombre nuevo, sin colisiones)
serie_cuenta_principal = saldo
# ==================================================
# AJUSTES POR TRANSFERENCIAS EN CUENTA PRINCIPAL
# ==================================================
for t in st.session_state.transferencias:
    f = pd.to_datetime(t["fecha"])

    if f in serie_cuenta_principal.index:
        # Sale dinero de la cuenta principal
        if t["origen"] == "principal":
            serie_cuenta_principal.loc[f:] -= t["monto"]

        # Entra dinero a la cuenta principal
        if t["destino"] == "principal":
            serie_cuenta_principal.loc[f:] += t["monto"]

# ==================================================
# SALDOS DE CUENTAS DE AHORRO SECUNDARIAS
# ==================================================

saldos_sec = {}

for cuenta in st.session_state["cuentas_ahorro"]:
    nombre_cuenta = cuenta["nombre"]
    saldo_ini = float(cuenta.get("saldo_inicial", 0.0))

    serie_sec = pd.Series(saldo_ini, index=fechas)

    # Gastos diarios débito asociados a esta cuenta secundaria
    if not df_g.empty and "cuenta_origen" in df_g.columns:
        gastos_sec = (
            df_g[df_g["cuenta_origen"] == cuenta["id"]]
            .groupby("fecha")["monto"]
            .sum()
            .reindex(fechas, fill_value=0)
        )

        serie_sec = serie_sec - gastos_sec.cumsum()

    # Gastos fijos asociados a esta cuenta secundaria
    if not df_fijos.empty and "cuenta_origen" in df_fijos.columns:
        gastos_fijos_sec = pd.Series(0.0, index=fechas)

        for _, r in df_fijos[df_fijos["cuenta_origen"] == cuenta["id"]].iterrows():
            for mes in pd.date_range(fecha_inicio_sim, fecha_fin_sim, freq="MS"):
                try:
                    f = mes.replace(day=int(r["dia_cobro"]))

                    if f >= pd.to_datetime(r["fecha_inicio"]) and f in gastos_fijos_sec.index:
                        gastos_fijos_sec.loc[f] += float(r["monto"])
                except:
                    pass

        serie_sec = serie_sec - gastos_fijos_sec.cumsum()

    # Transferencias
    for t in st.session_state["transferencias"]:
        f = pd.to_datetime(t["fecha"])

        if f in serie_sec.index:
            if t["origen"] == cuenta["id"]:
                serie_sec.loc[f:] -= float(t["monto"])

            if t["destino"] == cuenta["id"]:
                serie_sec.loc[f:] += float(t["monto"])

    # Pagos de tarjeta de crédito desde esta cuenta secundaria
    egr_tc_sec = egresos_tarjeta_por_cuenta.get(cuenta["id"], pd.Series(0.0, index=fechas))
    serie_sec = serie_sec - egr_tc_sec.cumsum()

    # Interés diario por TEA
    tea = float(cuenta.get("tea", 0.0))
    aplica_interes_diario = bool(cuenta.get("aplica_interes_diario", False))

    if aplica_interes_diario and tea > 0:
        tasa_diaria = (1 + tea / 100) ** (1 / 365) - 1

        serie_con_interes = pd.Series(index=fechas, dtype=float)
        saldo_actual = float(serie_sec.iloc[0])
        serie_movimientos = serie_sec.diff().fillna(0)

        for i, f in enumerate(fechas):
            if i == 0:
                serie_con_interes.loc[f] = saldo_actual
            else:
                saldo_actual = saldo_actual + serie_movimientos.loc[f]
                saldo_actual = saldo_actual * (1 + tasa_diaria)
                serie_con_interes.loc[f] = saldo_actual

        serie_sec = serie_con_interes

    # IMPORTANTE: esto debe ir fuera del if de interés
    saldos_sec[nombre_cuenta] = serie_sec

# ==================================================
# AHORRO TOTAL (SUMA DE TODAS LAS CUENTAS)
# ==================================================
serie_ahorro_total = serie_cuenta_principal

for s in saldos_sec.values():
    serie_ahorro_total = serie_ahorro_total + s

df_plot = pd.DataFrame({
    "fecha": fechas,
    "saldo": saldo,
    "ingresos": ing_rec + ing_punt,
    "egresos": g_diarios_principal + g_fijos + egresos_tarjeta
})

df_plot["mes"] = df_plot["fecha"].dt.to_period("M")
mensual = df_plot.groupby("mes")[["ingresos", "egresos"]].sum().reset_index()
mensual["fecha_mes"] = mensual["mes"].dt.to_timestamp()

# ==================================================

# ==================================================
# 5. GRÁFICOS Y RESULTADOS
# ==================================================
with st.expander("📊 4. Gráficos y resultados", expanded=True):

    # ─────────────────────────────────────────────────────────
    # PALETA Y CONSTANTES
    # ─────────────────────────────────────────────────────────
    MESES_ES = {
        1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril",
        5: "Mayo", 6: "Junio", 7: "Julio", 8: "Agosto",
        9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre"
    }

    # ── Detección de tema light / dark ────────────────────────
    try:
        _tema = st.get_option("theme.base") or "dark"
    except Exception:
        _tema = "dark"
    _is_dark   = (_tema != "light")
    _font_col  = "white"                  if _is_dark else "#1a1a2e"
    _grid_col  = "#1e2530"               if _is_dark else "#d0d0d0"
    _plot_bg   = "rgba(14,17,23,1)"      if _is_dark else "rgba(248,249,250,1)"

    PLOTLY_LAYOUT = dict(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor=_plot_bg,
        font=dict(color=_font_col, family="Inter, sans-serif"),
        margin=dict(l=10, r=10, t=40, b=10),
    )
    _LEGEND_BASE = dict(bgcolor="rgba(0,0,0,0)", bordercolor="rgba(0,0,0,0)", font=dict(color=_font_col))
    _XAXIS_DEF   = dict(gridcolor=_grid_col, zeroline=False, color=_font_col)
    _YAXIS_DEF   = dict(gridcolor=_grid_col, zeroline=False, color=_font_col)

    PALETTE = {
        "principal": "#26C281",
        "total":     "#7F8C8D",
        "ingresos":  "#2ECC71",
        "egresos":   "#E74C3C",
        "debito":    "#3498DB",
        "credito":   "#E74C3C",
        "fijos":     "#9B59B6",
        "variables": "#F39C12",
        "hoy":       "#F1C40F",
    }
    COLORES_SEC = ["#3498DB", "#9B59B6", "#1ABC9C", "#E67E22"]

    hoy = pd.Timestamp.now(tz=ZoneInfo("America/Lima")).tz_localize(None).normalize()

    # ─────────────────────────────────────────────────────────
    # GASTOS MENSUALES POR TIPO  (cálculo base, necesario para todo)
    # ─────────────────────────────────────────────────────────
    MESES_ES_MIN = {
        1: "enero", 2: "febrero", 3: "marzo", 4: "abril",
        5: "mayo", 6: "junio", 7: "julio", 8: "agosto",
        9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre"
    }

    meses_base = pd.DataFrame({
        "mes": pd.period_range(fecha_inicio_sim, fecha_fin_sim, freq="M")
    })

    df_debito_diario = pd.DataFrame(st.session_state["gastos_diarios"])
    if not df_debito_diario.empty:
        df_debito_diario["fecha"] = pd.to_datetime(df_debito_diario["fecha"], errors="coerce")
        df_debito_diario["monto"] = pd.to_numeric(df_debito_diario["monto"], errors="coerce").fillna(0)
        df_debito_diario["mes"] = df_debito_diario["fecha"].dt.to_period("M")
        df_debito_diario_mes = (df_debito_diario.groupby("mes")["monto"].sum()
                                .reset_index().rename(columns={"monto": "Débito diario"}))
    else:
        df_debito_diario_mes = pd.DataFrame(columns=["mes", "Débito diario"])

    gastos_fijos_expandido = []
    for g in st.session_state["gastos_fijos"]:
        fecha_ini = pd.to_datetime(g["fecha_inicio"], errors="coerce")
        for mes in pd.date_range(fecha_inicio_sim, fecha_fin_sim, freq="MS"):
            try:
                fecha_cobro = mes.replace(day=min(int(g["dia_cobro"]), 28))
                if fecha_cobro >= fecha_ini:
                    gastos_fijos_expandido.append({"fecha": fecha_cobro, "monto": float(g["monto"])})
            except:
                pass

    df_fijos_expandido = pd.DataFrame(gastos_fijos_expandido)
    if not df_fijos_expandido.empty:
        df_fijos_expandido["mes"] = pd.to_datetime(df_fijos_expandido["fecha"]).dt.to_period("M")
        df_fijos_mes = (df_fijos_expandido.groupby("mes")["monto"].sum()
                        .reset_index().rename(columns={"monto": "Gastos fijos débito"}))
    else:
        df_fijos_mes = pd.DataFrame(columns=["mes", "Gastos fijos débito"])

    df_credito_diario = pd.DataFrame(st.session_state["gastos_tarjeta"])
    if not df_credito_diario.empty:
        df_credito_diario["fecha"] = pd.to_datetime(df_credito_diario["fecha"], errors="coerce")
        df_credito_diario["monto"] = pd.to_numeric(df_credito_diario["monto"], errors="coerce").fillna(0)
        df_credito_diario["mes"] = df_credito_diario["fecha"].dt.to_period("M")
        df_credito_diario_mes = (df_credito_diario.groupby("mes")["monto"].sum()
                                 .reset_index().rename(columns={"monto": "Crédito diario"}))
    else:
        df_credito_diario_mes = pd.DataFrame(columns=["mes", "Crédito diario"])

    df_credito_recurrente = pd.DataFrame(gastos_tarjeta_recurrentes_expandido)
    if not df_credito_recurrente.empty:
        df_credito_recurrente["fecha"] = pd.to_datetime(df_credito_recurrente["fecha"], errors="coerce")
        df_credito_recurrente["monto"] = pd.to_numeric(df_credito_recurrente["monto"], errors="coerce").fillna(0)
        df_credito_recurrente["mes"] = df_credito_recurrente["fecha"].dt.to_period("M")
        df_credito_recurrente_mes = (df_credito_recurrente.groupby("mes")["monto"].sum()
                                     .reset_index().rename(columns={"monto": "Crédito recurrente"}))
    else:
        df_credito_recurrente_mes = pd.DataFrame(columns=["mes", "Crédito recurrente"])

    df_mes_tipo = (
        meses_base
        .merge(df_debito_diario_mes, on="mes", how="left")
        .merge(df_fijos_mes, on="mes", how="left")
        .merge(df_credito_diario_mes, on="mes", how="left")
        .merge(df_credito_recurrente_mes, on="mes", how="left")
        .fillna(0)
    )
    for col in ["Débito diario", "Gastos fijos débito", "Crédito diario", "Crédito recurrente"]:
        df_mes_tipo[col] = pd.to_numeric(df_mes_tipo[col], errors="coerce").fillna(0)

    df_mes_tipo["Mes"] = df_mes_tipo["mes"].apply(
        lambda m: f"{MESES_ES_MIN[m.month].capitalize()} {m.year}"
    )
    df_mes_tipo["Gastos débito total mensual"]   = df_mes_tipo["Débito diario"] + df_mes_tipo["Gastos fijos débito"]
    df_mes_tipo["Gastos crédito total mensual"]  = df_mes_tipo["Crédito diario"] + df_mes_tipo["Crédito recurrente"]
    df_mes_tipo["Gastos fijos mensuales"]        = df_mes_tipo["Gastos fijos débito"] + df_mes_tipo["Crédito recurrente"]
    df_mes_tipo["Gastos no fijos mensuales"]     = df_mes_tipo["Débito diario"] + df_mes_tipo["Crédito diario"]
    df_mes_tipo["Total general"]                 = df_mes_tipo["Gastos fijos mensuales"] + df_mes_tipo["Gastos no fijos mensuales"]

    # ─────────────────────────────────────────────────────────
    # SECCIÓN 1 — EVOLUCIÓN DE SALDOS
    # ─────────────────────────────────────────────────────────
    st.markdown("### 📈 Evolución de saldos")

    # ── Cuadro de saldos actuales ──────────────────────────────
    # Índice de la fecha más cercana a hoy (evitar conflictos de timezone)
    _hoy_naive = pd.Timestamp(hoy_peru)
    _fechas_arr = fechas.to_series().dt.normalize().reset_index(drop=True)
    _f_min, _f_max = _fechas_arr.iloc[0], _fechas_arr.iloc[-1]
    _fecha_ref = _hoy_naive if (_f_min <= _hoy_naive <= _f_max) else _f_max
    _idx_ref = int((_fechas_arr - _fecha_ref).abs().values.argmin())
    _fecha_ref_real = fechas[_idx_ref]

    _saldo_principal_hoy = float(serie_cuenta_principal.iloc[_idx_ref])
    _saldo_total_hoy     = float(serie_ahorro_total.iloc[_idx_ref])

    _lbl_fecha = _fecha_ref_real.strftime("%d/%m/%Y")
    with st.container(border=True):
        st.caption(f"💰 Saldos al {_lbl_fecha}")
        _sb_cols = st.columns(2 + len(saldos_sec))
        _sb_cols[0].metric(nombre_cuenta_principal, f"S/ {_saldo_principal_hoy:,.0f}")
        for _i, (_nc, _ss) in enumerate(saldos_sec.items()):
            _v = float(_ss.iloc[_idx_ref])
            _sb_cols[1 + _i].metric(f"↳ {_nc}", f"S/ {_v:,.0f}")
        _sb_cols[-1].metric("🏦 Total ahorros", f"S/ {_saldo_total_hoy:,.0f}")

    # ── Controles del gráfico ──────────────────────────────────
    ctrl_col1, ctrl_col2, ctrl_col3 = st.columns([1, 1, 1])
    with ctrl_col1:
        horizonte_meses = st.selectbox(
            "Horizonte",
            [3, 6, 9, 12],
            index=1,
            format_func=lambda x: f"{x} meses",
            key="horizonte_evol"
        )
    with ctrl_col2:
        mostrar_ahorro_total = st.toggle("Mostrar ahorro total", value=True, key="tog_total")
    with ctrl_col3:
        mostrar_secundarias = st.toggle("Mostrar cuentas secundarias", value=False, key="tog_sec")

    # ── Sliders de rango Y ─────────────────────────────────────
    # Y1: máximo = 5x el saldo máximo observado, mínimo 200k, redondeado a 50k
    _max_saldo_data = max(int(serie_cuenta_principal.max()), int(serie_ahorro_total.max()), 50000)
    _max_saldo = max(((_max_saldo_data * 5) // 50000 + 1) * 50000, 500000)
    # Y2: máximo = 2x el flujo máximo observado, mínimo 50k, redondeado a 10k
    _max_flujo_data = max(int(mensual["ingresos"].max()), int(mensual["egresos"].max()), 10000)
    _max_flujo = max(((_max_flujo_data * 2) // 10000 + 1) * 10000, 50000)

    _sl_col1, _sl_col2 = st.columns(2)
    with _sl_col1:
        rango_y1 = st.slider(
            "Rango eje Y — Saldo (S/)",
            min_value=0, max_value=_max_saldo,
            value=(0, min(int(_max_saldo_data * 1.4 // 10000 + 1) * 10000, _max_saldo)),
            step=10000, format="%,d",
            key="slider_y1"
        )
    with _sl_col2:
        rango_y2 = st.slider(
            "Rango eje Y2 — Flujo mensual (S/)",
            min_value=0, max_value=_max_flujo,
            value=(0, min(int(_max_flujo_data * 1.4 // 5000 + 1) * 5000, _max_flujo)),
            step=5000, format="%,d",
            key="slider_y2"
        )

    fecha_x_inicio = fechas.min()
    fecha_x_fin = min(fecha_x_inicio + pd.DateOffset(months=horizonte_meses), fechas.max())

    mask = (fechas >= fecha_x_inicio) & (fechas <= fecha_x_fin)
    fechas_vis = fechas[mask]

    fig_evol = make_subplots(specs=[[{"secondary_y": True}]])

    # Barras ingresos/egresos (eje secundario, invertido)
    mensual_vis = mensual[
        (mensual["fecha_mes"] >= fecha_x_inicio) &
        (mensual["fecha_mes"] <= fecha_x_fin)
    ]
    fig_evol.add_trace(go.Bar(
        x=mensual_vis["fecha_mes"], y=mensual_vis["ingresos"],
        name="Ingresos mes", marker_color=PALETTE["ingresos"], opacity=0.55,
        hovertemplate="<b>Ingresos</b><br>S/ %{y:,.0f}<extra></extra>"
    ), secondary_y=True)
    fig_evol.add_trace(go.Bar(
        x=mensual_vis["fecha_mes"], y=mensual_vis["egresos"],
        name="Egresos mes", marker_color=PALETTE["egresos"], opacity=0.55,
        hovertemplate="<b>Egresos</b><br>S/ %{y:,.0f}<extra></extra>"
    ), secondary_y=True)

    # Línea cuenta principal
    fig_evol.add_trace(go.Scatter(
        x=fechas_vis, y=serie_cuenta_principal[mask],
        name=nombre_cuenta_principal,
        line=dict(color=PALETTE["principal"], width=2.5),
        hovertemplate=f"<b>{nombre_cuenta_principal}</b><br>%{{x|%d %b %Y}}<br>S/ %{{y:,.0f}}<extra></extra>"
    ), secondary_y=False)

    # Cuentas secundarias
    if mostrar_secundarias:
        for i, (nc, ss) in enumerate(saldos_sec.items()):
            fig_evol.add_trace(go.Scatter(
                x=fechas_vis, y=ss[mask],
                name=f"↳ {nc}",
                line=dict(color=COLORES_SEC[i % len(COLORES_SEC)], width=1.8, dash="dash"),
                hovertemplate=f"<b>{nc}</b><br>%{{x|%d %b %Y}}<br>S/ %{{y:,.0f}}<extra></extra>"
            ), secondary_y=False)

    # Ahorro total
    if mostrar_ahorro_total:
        fig_evol.add_trace(go.Scatter(
            x=fechas_vis, y=serie_ahorro_total[mask],
            name="Ahorro total",
            line=dict(color=PALETTE["total"], width=2, dash="dot"),
            hovertemplate="<b>Ahorro total</b><br>%{x|%d %b %Y}<br>S/ %{y:,.0f}<extra></extra>"
        ), secondary_y=False)

    # Línea "hoy"
    if fecha_x_inicio <= hoy <= fecha_x_fin:
        fig_evol.add_vline(
            x=hoy.timestamp() * 1000,
            line_width=1.5, line_dash="dash",
            line_color=PALETTE["hoy"],
            annotation_text="Hoy",
            annotation_position="top right",
            annotation_font_color=PALETTE["hoy"]
        )

    fig_evol.update_layout(
        **PLOTLY_LAYOUT,
        height=420,
        barmode="group",
        hovermode="x unified",
        legend={**_LEGEND_BASE, "orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "right", "x": 1},
    )
    fig_evol.update_yaxes(
        title_text="Saldo (S/)", secondary_y=False,
        gridcolor=_grid_col, tickformat=",d", color=_font_col,
        range=[rango_y1[0], rango_y1[1]]
    )
    fig_evol.update_yaxes(
        title_text="Flujo mensual (S/)", secondary_y=True,
        gridcolor="rgba(0,0,0,0)", tickformat=",d",
        color=_font_col, range=[rango_y2[1], rango_y2[0]]
    )
    fig_evol.update_xaxes(showgrid=False, color=_font_col)

    st.plotly_chart(fig_evol, use_container_width=True)

    # ─────────────────────────────────────────────────────────
    # SECCIÓN 2 — META MENSUAL DE AHORRO
    # ─────────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### 🎯 Meta mensual de ahorro")

    mes_actual = pd.Timestamp(hoy_peru).to_period("M")

    meta_col, _ = st.columns([1, 2])
    with meta_col:
        meta_ahorro = st.number_input(
            "¿Cuánto quieres ahorrar este mes? (S/)",
            min_value=0.0, step=100.0, value=2000.0
        )

    ingresos_mes_actual = (
        (ing_rec + ing_punt)
        .loc[(ing_rec + ing_punt).index.to_period("M") == mes_actual]
        .sum()
    )

    fila_mes_actual = df_mes_tipo[df_mes_tipo["mes"] == mes_actual]
    if not fila_mes_actual.empty:
        gastos_fijos_mes_actual    = float(fila_mes_actual["Gastos fijos mensuales"].iloc[0])
        gastos_no_fijos_mes_actual = float(fila_mes_actual["Gastos no fijos mensuales"].iloc[0])
    else:
        gastos_fijos_mes_actual = gastos_no_fijos_mes_actual = 0.0

    gastos_comprometidos          = gastos_fijos_mes_actual + gastos_no_fijos_mes_actual
    monto_disponible_para_gastar  = ingresos_mes_actual - gastos_comprometidos - meta_ahorro
    pct_gastado = (gastos_comprometidos / ingresos_mes_actual * 100) if ingresos_mes_actual > 0 else 0

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Ingresos del mes",        f"S/ {ingresos_mes_actual:,.0f}")
    m2.metric("Gastos comprometidos",    f"S/ {gastos_comprometidos:,.0f}",
              delta=f"{pct_gastado:.0f}% del ingreso", delta_color="inverse")
    m3.metric("Meta de ahorro",          f"S/ {meta_ahorro:,.0f}")
    m4.metric("Disponible para gastar",  f"S/ {max(0, monto_disponible_para_gastar):,.0f}",
              delta="✅ OK" if monto_disponible_para_gastar >= 0 else "⚠️ Meta en riesgo",
              delta_color="normal" if monto_disponible_para_gastar >= 0 else "inverse")

    # Gauge de progreso
    fig_gauge = go.Figure(go.Indicator(
        mode="gauge+number+delta",
        value=gastos_comprometidos,
        delta={"reference": ingresos_mes_actual - meta_ahorro, "valueformat": ",.0f",
               "prefix": "S/ ", "increasing": {"color": "#E74C3C"}, "decreasing": {"color": "#2ECC71"}},
        title={"text": "Gastos vs presupuesto disponible", "font": {"color": "white", "size": 14}},
        number={"prefix": "S/ ", "valueformat": ",.0f", "font": {"color": "white"}},
        gauge={
            "axis": {"range": [0, max(ingresos_mes_actual, gastos_comprometidos * 1.2)],
                     "tickformat": ",.0f", "tickcolor": "white"},
            "bar": {"color": "#E74C3C" if monto_disponible_para_gastar < 0 else "#26C281"},
            "bgcolor": _plot_bg,
            "bordercolor": "#333",
            "threshold": {
                "line": {"color": PALETTE["hoy"], "width": 3},
                "thickness": 0.75,
                "value": ingresos_mes_actual - meta_ahorro
            },
            "steps": [
                {"range": [0, ingresos_mes_actual - meta_ahorro], "color": "rgba(38,194,129,0.15)"},
                {"range": [ingresos_mes_actual - meta_ahorro, max(ingresos_mes_actual, gastos_comprometidos * 1.2)],
                 "color": "rgba(231,76,60,0.15)"}
            ]
        }
    ))
    fig_gauge.update_layout(paper_bgcolor="rgba(0,0,0,0)", font_color=_font_col, height=260,
                            margin=dict(l=20, r=20, t=40, b=10))
    st.plotly_chart(fig_gauge, use_container_width=True)

    if monto_disponible_para_gastar >= 0:
        st.success(f"Vas bien. Puedes gastar hasta **S/ {monto_disponible_para_gastar:,.0f}** más este mes y cumplir tu meta.")
    else:
        st.error(f"Ya superaste el presupuesto de tu meta de ahorro por **S/ {abs(monto_disponible_para_gastar):,.0f}**.")

    # ─────────────────────────────────────────────────────────
    # SECCIÓN 3 — GASTOS NO FIJOS POR CATEGORÍA
    # ─────────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### 🗂️ Gastos no fijos por categoría")

    meses_disponibles = pd.period_range(start=fecha_inicio_sim, end=fecha_fin_sim, freq="M")
    opciones_meses = {
        f"{MESES_ES[m.month]} {m.year}": m for m in meses_disponibles
    }

    # Seleccionar mes por defecto: el mes actual si está en rango, si no el primero
    _mes_default_key = f"{MESES_ES.get(hoy_peru.month, 'Enero')} {hoy_peru.year}"
    _idx_default = list(opciones_meses.keys()).index(_mes_default_key) \
        if _mes_default_key in opciones_meses else 0

    cat_col1, cat_col2 = st.columns([1, 1])
    with cat_col1:
        mes_categoria_txt = st.selectbox(
            "Mes a analizar",
            list(opciones_meses.keys()),
            index=_idx_default,
            key="mes_gastos_categoria"
        )
    with cat_col2:
        tipo_vista_cat = st.radio(
            "Vista",
            ["Donut", "Barras horizontales"],
            horizontal=True,
            key="vista_cat"
        )

    mes_categoria = opciones_meses[mes_categoria_txt]

    frames_cat = []
    df_debito_cat = pd.DataFrame(st.session_state["gastos_diarios"])
    if not df_debito_cat.empty:
        df_debito_cat["fecha"] = pd.to_datetime(df_debito_cat["fecha"], errors="coerce")
        df_debito_cat["monto"] = pd.to_numeric(df_debito_cat["monto"], errors="coerce").fillna(0)
        df_debito_cat["mes"]   = df_debito_cat["fecha"].dt.to_period("M")
        frames_cat.append(df_debito_cat[["fecha", "mes", "categoria", "monto"]])

    df_credito_cat = pd.DataFrame(st.session_state["gastos_tarjeta"])
    if not df_credito_cat.empty:
        df_credito_cat["fecha"] = pd.to_datetime(df_credito_cat["fecha"], errors="coerce")
        df_credito_cat["monto"] = pd.to_numeric(df_credito_cat["monto"], errors="coerce").fillna(0)
        df_credito_cat["mes"]   = df_credito_cat["fecha"].dt.to_period("M")
        frames_cat.append(df_credito_cat[["fecha", "mes", "categoria", "monto"]])

    df_gastos_cat = pd.concat(frames_cat, ignore_index=True) if frames_cat \
        else pd.DataFrame(columns=["fecha", "mes", "categoria", "monto"])

    df_mes_cat = df_gastos_cat[df_gastos_cat["mes"] == mes_categoria]

    if not df_mes_cat.empty:
        resumen_cat = (
            df_mes_cat.groupby("categoria")["monto"]
            .sum().reset_index().sort_values("monto", ascending=False)
        )
        total_mes = resumen_cat["monto"].sum()

        # Definir colores por categoría
        _cat_colors = px.colors.qualitative.Set3

        if tipo_vista_cat == "Donut":
            fig_cat = go.Figure(go.Pie(
                labels=resumen_cat["categoria"],
                values=resumen_cat["monto"],
                hole=0.52,
                textinfo="label+percent",
                hovertemplate="<b>%{label}</b><br>S/ %{value:,.0f}<br>%{percent}<extra></extra>",
                marker=dict(colors=_cat_colors[:len(resumen_cat)],
                            line=dict(color="#0E1117", width=2)),
            ))
            fig_cat.add_annotation(
                text=f"S/ {total_mes:,.0f}",
                x=0.5, y=0.5, font=dict(size=16, color=_font_col), showarrow=False
            )
            fig_cat.update_layout(
                **PLOTLY_LAYOUT, height=420,
                showlegend=True,
                legend={**_LEGEND_BASE, "orientation": "v", "x": 1.01, "y": 0.5},
                title=dict(text=f"Distribución — {mes_categoria_txt}", font=dict(size=15))
            )
        else:
            resumen_cat_sorted = resumen_cat.sort_values("monto")
            fig_cat = go.Figure(go.Bar(
                x=resumen_cat_sorted["monto"],
                y=resumen_cat_sorted["categoria"],
                orientation="h",
                marker=dict(
                    color=resumen_cat_sorted["monto"],
                    colorscale="Teal",
                    showscale=False
                ),
                text=[f"S/ {v:,.0f}" for v in resumen_cat_sorted["monto"]],
                textposition="outside",
                hovertemplate="<b>%{y}</b><br>S/ %{x:,.0f}<extra></extra>"
            ))
            fig_cat.update_layout(
                **PLOTLY_LAYOUT, height=max(350, len(resumen_cat) * 38),
                title=dict(text=f"Gastos por categoría — {mes_categoria_txt}",
                           font=dict(size=15, color=_font_col))
            )
            fig_cat.update_xaxes(**_XAXIS_DEF, tickformat=",d")
            fig_cat.update_yaxes(**_YAXIS_DEF)

        chart_col, table_col = st.columns([1.6, 1])
        with chart_col:
            st.plotly_chart(fig_cat, use_container_width=True)
        with table_col:
            st.metric("Total no fijo del mes", f"S/ {total_mes:,.0f}")
            st.dataframe(
                resumen_cat.rename(columns={"categoria": "Categoría", "monto": "Monto (S/)"})
                           .assign(**{"% del total": lambda d: (d["Monto (S/)"] / total_mes * 100).round(1)}),
                use_container_width=True, hide_index=True,
                column_config={
                    "Monto (S/)": st.column_config.NumberColumn(format="S/ %,.0f"),
                    "% del total": st.column_config.ProgressColumn(format="%.1f%%", min_value=0, max_value=100)
                }
            )
    else:
        st.info(f"No hay gastos no fijos registrados en {mes_categoria_txt}.")

    # ─────────────────────────────────────────────────────────
    # SECCIÓN 4 — GRÁFICOS MENSUALES COMPARATIVOS
    # ─────────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### 📊 Comparativa mensual de gastos")

    if df_mes_tipo["Total general"].sum() > 0:

        tab_debcred, tab_fijvar, tab_tabla = st.tabs(
            ["💳 Débito vs Crédito", "📌 Fijos vs Variables", "📋 Tabla detallada"]
        )

        def _plotly_bar_grouped(col_a, col_b, lbl_a, lbl_b, col_color_a, col_color_b):
            fig_b = go.Figure()
            fig_b.add_trace(go.Bar(
                x=df_mes_tipo["Mes"], y=df_mes_tipo[col_a],
                name=lbl_a, marker_color=col_color_a,
                hovertemplate=f"<b>{lbl_a}</b><br>%{{x}}<br>S/ %{{y:,.0f}}<extra></extra>"
            ))
            fig_b.add_trace(go.Bar(
                x=df_mes_tipo["Mes"], y=df_mes_tipo[col_b],
                name=lbl_b, marker_color=col_color_b,
                hovertemplate=f"<b>{lbl_b}</b><br>%{{x}}<br>S/ %{{y:,.0f}}<extra></extra>"
            ))
            fig_b.update_layout(
                **PLOTLY_LAYOUT,
                barmode="group", height=380,
                legend={**_LEGEND_BASE, "orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "right", "x": 1},
                hovermode="x unified"
            )
            fig_b.update_xaxes(**_XAXIS_DEF, tickangle=-30, showgrid=False)
            fig_b.update_yaxes(**_YAXIS_DEF, tickformat=",d", title_text="S/")
            return fig_b

        with tab_debcred:
            st.plotly_chart(
                _plotly_bar_grouped(
                    "Gastos débito total mensual", "Gastos crédito total mensual",
                    "Débito", "Crédito",
                    PALETTE["debito"], PALETTE["credito"]
                ), use_container_width=True
            )

        with tab_fijvar:
            st.plotly_chart(
                _plotly_bar_grouped(
                    "Gastos fijos mensuales", "Gastos no fijos mensuales",
                    "Fijos", "Variables",
                    PALETTE["fijos"], PALETTE["variables"]
                ), use_container_width=True
            )

        with tab_tabla:
            st.dataframe(
                df_mes_tipo[[
                    "Mes", "Débito diario", "Gastos fijos débito",
                    "Crédito diario", "Crédito recurrente",
                    "Gastos débito total mensual", "Gastos crédito total mensual",
                    "Gastos fijos mensuales", "Gastos no fijos mensuales", "Total general"
                ]],
                use_container_width=True, hide_index=True,
                column_config={
                    col: st.column_config.NumberColumn(format="S/ %,.0f")
                    for col in [
                        "Débito diario", "Gastos fijos débito", "Crédito diario",
                        "Crédito recurrente", "Gastos débito total mensual",
                        "Gastos crédito total mensual", "Gastos fijos mensuales",
                        "Gastos no fijos mensuales", "Total general"
                    ]
                }
            )
    else:
        st.info("No hay gastos registrados para mostrar.")

    # ─────────────────────────────────────────────────────────
    # SECCIÓN 5 — RESUMEN POR CICLO DE TARJETA
    # ─────────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### 💳 Pagos de tarjeta de crédito")

    if not df_gt_calc.empty:
        resumen = []
        for t in st.session_state["tarjetas"]:
            df_t = df_gt_calc[df_gt_calc["tarjeta_id"] == t["id"]]
            for _, g in df_t.iterrows():
                fecha_gasto = pd.to_datetime(g["fecha"], errors="coerce")
                if pd.isna(fecha_gasto):
                    continue
                inicio, cierre = obtener_ciclo_tarjeta(fecha_gasto, int(t["dia_cierre"]))
                fecha_pago = (pd.Timestamp(cierre) + pd.DateOffset(months=1)).replace(day=int(t["dia_pago"]))
                resumen.append({
                    "Tarjeta": t["nombre"], "Inicio ciclo": inicio,
                    "Cierre ciclo": cierre, "Fecha pago": fecha_pago.date(),
                    "Monto": float(g["monto"])
                })

        df_res = pd.DataFrame(resumen)
        if not df_res.empty:
            resumen_ciclo = (
                df_res.groupby(["Tarjeta", "Inicio ciclo", "Cierre ciclo", "Fecha pago"], as_index=False)["Monto"]
                .sum().sort_values("Fecha pago")
            )
            resumen_ciclo["Ciclo facturación"] = resumen_ciclo.apply(
                lambda r: f"{pd.to_datetime(r['Inicio ciclo']).strftime('%d/%m/%Y')} → {pd.to_datetime(r['Cierre ciclo']).strftime('%d/%m/%Y')}",
                axis=1
            )

            hoy_date = pd.Timestamp.now(tz=ZoneInfo("America/Lima")).normalize().date()
            resumen_ciclo["_fecha_pago_dt"] = pd.to_datetime(resumen_ciclo["Fecha pago"])
            resumen_ciclo["_dias"] = (resumen_ciclo["_fecha_pago_dt"].dt.date
                                       .apply(lambda d: (d - hoy_date).days))

            pagos_futuros = resumen_ciclo[resumen_ciclo["_dias"] >= 0].copy()
            pagos_pasados  = resumen_ciclo[resumen_ciclo["_dias"] < 0].copy()

            # ── Próximos pagos como tarjetas visuales ──────────────
            if not pagos_futuros.empty:
                proximos = pagos_futuros.sort_values("_dias").head(4)
                st.markdown("#### 📅 Próximos pagos")
                _pcols = st.columns(len(proximos))
                for _ci, (_, _row) in enumerate(proximos.iterrows()):
                    _d = int(_row["_dias"])
                    if _d == 0:
                        _urgencia = "🔴 ¡HOY!"
                        _dc = "inverse"
                    elif _d <= 5:
                        _urgencia = f"🔴 {_d} días"
                        _dc = "inverse"
                    elif _d <= 15:
                        _urgencia = f"🟡 {_d} días"
                        _dc = "off"
                    else:
                        _urgencia = f"🟢 {_d} días"
                        _dc = "normal"

                    with _pcols[_ci]:
                        with st.container(border=True):
                            st.caption(f"💳 {_row['Tarjeta']}")
                            st.markdown(f"### S/ {_row['Monto']:,.0f}")
                            st.caption(f"📆 Pago: **{_row['_fecha_pago_dt'].strftime('%d/%m/%Y')}**")
                            st.caption(f"🗓 Cierre: {pd.to_datetime(_row['Cierre ciclo']).strftime('%d/%m/%Y')}")
                            st.markdown(f"**{_urgencia}**")

            # ── Timeline de pagos futuros (gráfico) ────────────────
            if not pagos_futuros.empty:
                st.markdown("#### 📊 Timeline de pagos futuros")
                _timeline = pagos_futuros.sort_values("_dias").copy()
                _timeline["label"] = _timeline.apply(
                    lambda r: f"{r['Tarjeta']}<br>S/ {r['Monto']:,.0f}", axis=1
                )
                _timeline["color"] = _timeline["_dias"].apply(
                    lambda d: "#E74C3C" if d <= 5 else ("#F39C12" if d <= 15 else "#26C281")
                )

                fig_tl = go.Figure()
                for _, _row in _timeline.iterrows():
                    fig_tl.add_trace(go.Bar(
                        x=[_row["Monto"]],
                        y=[f"{_row['Tarjeta']} — {_row['_fecha_pago_dt'].strftime('%d/%m')}"],
                        orientation="h",
                        marker_color=_row["color"],
                        text=f"S/ {_row['Monto']:,.0f}  ({int(_row['_dias'])} días)",
                        textposition="outside",
                        hovertemplate=(
                            f"<b>{_row['Tarjeta']}</b><br>"
                            f"Ciclo: {_row['Ciclo facturación']}<br>"
                            f"Pago: {_row['_fecha_pago_dt'].strftime('%d/%m/%Y')}<br>"
                            f"<b>S/ {_row['Monto']:,.0f}</b><extra></extra>"
                        ),
                        showlegend=False
                    ))

                fig_tl.update_layout(
                    **PLOTLY_LAYOUT,
                    height=max(200, len(_timeline) * 52 + 60),
                    showlegend=False,
                    barmode="overlay",
                    xaxis=dict(tickformat=",d", gridcolor=_grid_col, color=_font_col, title="Monto (S/)"),
                    yaxis=dict(gridcolor="rgba(0,0,0,0)", color=_font_col, autorange="reversed"),
                    margin=dict(l=10, r=120, t=20, b=30),
                )
                # Línea vertical en "hoy" (monto 0)
                fig_tl.add_annotation(
                    text="← Monto a pagar por ciclo",
                    xref="paper", yref="paper",
                    x=0.5, y=1.05, showarrow=False,
                    font=dict(size=11, color=_font_col)
                )
                st.plotly_chart(fig_tl, use_container_width=True)

            # ── Tabla completa ─────────────────────────────────────
            with st.expander("📋 Ver historial completo de ciclos", expanded=False):
                _tabla_show = resumen_ciclo[
                    ["Tarjeta", "Ciclo facturación", "Cierre ciclo", "Fecha pago", "Monto", "_dias"]
                ].copy()
                _tabla_show["Estado"] = _tabla_show["_dias"].apply(
                    lambda d: "✅ Pagado" if d < 0 else ("🔴 Urgente" if d <= 5 else ("🟡 Próximo" if d <= 15 else "🟢 Futuro"))
                )
                _tabla_show = _tabla_show.drop(columns=["_dias"])
                st.dataframe(
                    _tabla_show,
                    use_container_width=True, hide_index=True,
                    column_config={
                        "Monto": st.column_config.NumberColumn("Monto (S/)", format="S/ %,.0f"),
                        "Estado": st.column_config.TextColumn("Estado"),
                    }
                )
        else:
            st.info("No hay gastos válidos con tarjeta para calcular ciclos.")
    else:
        st.info("No hay gastos con tarjeta registrados.")