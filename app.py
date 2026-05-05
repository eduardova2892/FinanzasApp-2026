import streamlit as st
from supabase import create_client
import pandas as pd
import matplotlib.pyplot as plt
from datetime import date, timedelta
import uuid
# ==================================================
# CONFIGURACIÓN GENERAL
# ==================================================
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
        "Alimentación", "Alimentación Inncesario","Tecnología","Alcohol y Salids","Ropa","Regalos","Mascotas",
        "Vuelos", "Salud", "Entretenimiento","Combustible","Supermercado","Otros"],
"cuentas_ahorro": [],
"transferencias": [],
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
]
for clave in claves:
    cargar(clave)
# ==================================================
# CONFIGURACIÓN DE SIMULACIÓN
# ==================================================
st.header("⚙️ Configuración de la simulación")

conf = st.session_state["configuracion"]

fecha_inicio_sim = st.date_input(
    "Fecha inicio simulación",
    date.fromisoformat(conf["fecha_inicio_sim"])
    if conf["fecha_inicio_sim"] else date(2026, 4, 1)
)

fecha_fin_sim = st.date_input(
    "Fecha fin simulación",
    date.fromisoformat(conf["fecha_fin_sim"])
    if conf["fecha_fin_sim"] else date(2026, 12, 31)
)

ahorro_inicial = st.number_input(
    "Ahorro inicial",
    min_value=0.0,
    step=100.0,
    value=float(conf.get("ahorro_inicial", 0.0))
)

st.session_state["configuracion"] = {
    "fecha_inicio_sim": fecha_inicio_sim.isoformat(),
    "fecha_fin_sim": fecha_fin_sim.isoformat(),
    "ahorro_inicial": ahorro_inicial
}
guardar("configuracion")

st.divider()
#cuentas de ahorro secundarias
st.header("🏦 Cuentas de ahorro secundarias")

with st.form("form_cuenta_ahorro"):
    nombre = st.text_input("Nombre de la cuenta", "Ahorro Viajes")
    saldo_ini = st.number_input("Saldo inicial", min_value=0.0)

    if st.form_submit_button("Agregar cuenta"):
        st.session_state.cuentas_ahorro.append({
            "id": str(uuid.uuid4()),
            "nombre": nombre,
            "saldo_inicial": saldo_ini
        })
        guardar("cuentas_ahorro")
        st.rerun()

df_cuentas = pd.DataFrame(st.session_state.cuentas_ahorro)
if not df_cuentas.empty:
    df_cuentas["Eliminar"] = False
    ed = st.data_editor(df_cuentas, use_container_width=True)
    if st.button("Guardar cambios cuentas"):
        st.session_state.cuentas_ahorro = (
            ed[ed["Eliminar"] == False]
            .drop(columns=["Eliminar"])
            .to_dict("records")
        )
        guardar("cuentas_ahorro")
        st.rerun()
#TRANSFERNCIAS ENTRE CUENTAS DE AHORROS
st.header("🔁 Transferencias entre cuentas")

cuentas_map = {"Cuenta principal": "principal"}
for c in st.session_state.cuentas_ahorro:
    cuentas_map[c["nombre"]] = c["id"]

with st.form("form_transferencia"):
    fecha = st.date_input("Fecha", fecha_inicio_sim)
    origen = st.selectbox("Cuenta origen", list(cuentas_map.keys()))
    destino = st.selectbox("Cuenta destino", list(cuentas_map.keys()))
    monto = st.number_input("Monto", min_value=0.0)

    if st.form_submit_button("Registrar transferencia") and origen != destino:
        st.session_state.transferencias.append({
            "fecha": fecha.isoformat(),
            "origen": cuentas_map[origen],
            "destino": cuentas_map[destino],
            "monto": monto
        })
        guardar("transferencias")
        st.rerun()

# ==================================================
# RESUMEN Y EDICIÓN DE TRANSFERENCIAS
# ==================================================
df_transf = pd.DataFrame(st.session_state.transferencias)

if not df_transf.empty:
    df_transf["fecha"] = pd.to_datetime(df_transf["fecha"])
    df_transf["Eliminar"] = False

    st.subheader("📄 Historial de transferencias")

    ed = st.data_editor(
        df_transf,
        use_container_width=True,
        column_config={
            "Eliminar": st.column_config.CheckboxColumn()
        }
    )

    if st.button("Guardar cambios transferencias"):
        st.session_state.transferencias = (
            ed[ed["Eliminar"] == False]
            .drop(columns=["Eliminar"])
            .to_dict("records")
        )
        guardar("transferencias")
        st.rerun()
else:
    st.info("No hay transferencias registradas.")
# ==================================================
# INGRESOS
# ==================================================
st.header("💰 Ingresos recurrentes")

with st.form("form_ingreso_rec"):
    nombre = st.text_input("Nombre", "Sueldo")
    monto = st.number_input("Monto mensual", min_value=0.0, step=100.0)
    fecha_ini = st.date_input("Fecha inicio", fecha_inicio_sim)
    dia = st.number_input("Día de cobro", 1, 31, 25)

    if st.form_submit_button("Agregar ingreso recurrente"):
        st.session_state.ingresos_recurrentes.append({
            "nombre": nombre,
            "monto": monto,
            "fecha_inicio": fecha_ini.isoformat(),
            "dia_cobro": dia
        })
        guardar("ingresos_recurrentes")
        st.rerun()

df_ing_rec = pd.DataFrame(st.session_state.ingresos_recurrentes)
if not df_ing_rec.empty:
    df_ing_rec["Eliminar"] = False
    ed = st.data_editor(df_ing_rec, use_container_width=True)
    if st.button("Guardar cambios ingresos recurrentes"):
        st.session_state.ingresos_recurrentes = (
            ed[ed["Eliminar"] == False]
            .drop(columns=["Eliminar"])
            .to_dict("records")
        )
        guardar("ingresos_recurrentes")
        st.rerun()

st.header("💵 Ingresos puntuales")

with st.form("form_ingreso_puntual"):
    concepto = st.text_input("Concepto")
    fecha = st.date_input("Fecha", fecha_inicio_sim)
    monto = st.number_input("Monto", min_value=0.0)

    if st.form_submit_button("Agregar ingreso puntual"):
        st.session_state.ingresos_puntuales.append({
            "concepto": concepto,
            "fecha": fecha.isoformat(),
            "monto": monto
        })
        guardar("ingresos_puntuales")
        st.rerun()

df_ing_punt = pd.DataFrame(st.session_state.ingresos_puntuales)
if not df_ing_punt.empty:
    df_ing_punt["Eliminar"] = False
    ed = st.data_editor(df_ing_punt, use_container_width=True)
    if st.button("Guardar cambios ingresos puntuales"):
        st.session_state.ingresos_puntuales = (
            ed[ed["Eliminar"] == False]
            .drop(columns=["Eliminar"])
            .to_dict("records")
        )
        guardar("ingresos_puntuales")
        st.rerun()

# ==================================================
# GASTOS FIJOS Y DIARIOS
# ==================================================
st.header("📆 Gastos fijos")

with st.form("form_gasto_fijo"):
    nombre = st.text_input("Nombre")
    monto = st.number_input("Monto mensual", min_value=0.0)
    fecha_ini = st.date_input("Fecha inicio", fecha_inicio_sim)
    dia = st.number_input("Día cobro", 1, 31, 5)

    if st.form_submit_button("Agregar gasto fijo"):
        st.session_state.gastos_fijos.append({
            "nombre": nombre,
            "monto": monto,
            "fecha_inicio": fecha_ini.isoformat(),
            "dia_cobro": dia
        })
        guardar("gastos_fijos")
        st.rerun()

df_fijos = pd.DataFrame(st.session_state.gastos_fijos)
if not df_fijos.empty:
    df_fijos["Eliminar"] = False
    ed = st.data_editor(df_fijos, use_container_width=True)
    if st.button("Guardar cambios gastos fijos"):
        st.session_state.gastos_fijos = (
            ed[ed["Eliminar"] == False]
            .drop(columns=["Eliminar"])
            .to_dict("records")
        )
        guardar("gastos_fijos")
        st.rerun()

st.header("🧾 Gastos diarios")

with st.form("form_gasto_diario"):
    fecha = st.date_input("Fecha", fecha_inicio_sim)
    categoria = st.selectbox("Categoría", st.session_state.categorias + ["➕ Nueva"])
    if categoria == "➕ Nueva":
        categoria = st.text_input("Nueva categoría")
    descripcion = st.text_input("Descripción")
    monto = st.number_input("Monto", min_value=0.0)

    if st.form_submit_button("Agregar gasto"):
        if categoria not in st.session_state.categorias:
            st.session_state.categorias.append(categoria)
        st.session_state.gastos_diarios.append({
            "fecha": fecha.isoformat(),
            "categoria": categoria,
            "descripcion": descripcion,
            "monto": monto
        })
        guardar("gastos_diarios")
        st.rerun()

df_g = pd.DataFrame(st.session_state.gastos_diarios)
if not df_g.empty:
    df_g["fecha"] = pd.to_datetime(df_g["fecha"], errors="coerce")
    # ✅ Normalizar para visualización
    df_g["fecha"] = df_g["fecha"].apply(
    lambda x: x.date() if pd.notnull(x) and hasattr(x, "date") else x
)
    df_g["Eliminar"] = False
    ed = st.data_editor(
        df_g,
        use_container_width=True,
        column_config={
            "categoria": st.column_config.SelectboxColumn(options=st.session_state.categorias),
            "Eliminar": st.column_config.CheckboxColumn()
        }
    )

    if st.button("Guardar cambios gastos diarios"):
        st.session_state.gastos_diarios = (
            ed[ed["Eliminar"] == False]
            .drop(columns=["Eliminar"])
            .to_dict("records")
        )
        guardar("gastos_diarios")
        st.rerun()

# ==================================================
# TARJETAS DE CRÉDITO (PASOS 3 y 4)
# ==================================================
st.header("💳 Tarjetas de crédito")

with st.form("form_tarjeta"):
    nombre = st.text_input("Nombre tarjeta", "Visa")
    dia_cierre = st.number_input("Día de cierre", 1, 31, 20)
    dia_pago = st.number_input("Día de pago", 1, 31, 10)

    if st.form_submit_button("Agregar tarjeta"):
        st.session_state.tarjetas.append({
            "id": str(uuid.uuid4()),
            "nombre": nombre,
            "dia_cierre": dia_cierre,
            "dia_pago": dia_pago
        })
        guardar("tarjetas")
        st.rerun()

df_tar = pd.DataFrame(st.session_state.tarjetas)
if not df_tar.empty:
    df_tar["Eliminar"] = False
    ed = st.data_editor(df_tar, use_container_width=True)
    if st.button("Guardar cambios tarjetas"):
        st.session_state.tarjetas = (
            ed[ed["Eliminar"] == False]
            .drop(columns=["Eliminar"])
            .to_dict("records")
        )
        guardar("tarjetas")
        st.rerun()

st.header("💳 Gastos con tarjeta Crédito")


st.header("🔁 Gastos recurrentes con tarjeta de crédito")

if st.session_state.tarjetas:
    mapa_tarjetas = {t["nombre"]: t["id"] for t in st.session_state.tarjetas}

    with st.form("form_gasto_recurrente_tarjeta"):
        nombre = st.text_input("Nombre del gasto recurrente", "Gimnasio")
        tarjeta_nombre = st.selectbox("Tarjeta asociada", list(mapa_tarjetas.keys()))
        categoria = st.selectbox(
            "Categoría",
            st.session_state.categorias + ["➕ Nueva"],
            key="categoria_gasto_rec_tarjeta"
        )

        if categoria == "➕ Nueva":
            categoria = st.text_input("Nueva categoría", key="nueva_categoria_gasto_rec_tarjeta")

        monto = st.number_input("Monto mensual", min_value=0.0, step=10.0)
        dia_cargo = st.number_input("Día de cargo mensual", 1, 31, 15)
        fecha_inicio = st.date_input("Fecha inicio", fecha_inicio_sim)
        fecha_fin = st.date_input("Fecha fin opcional", fecha_fin_sim)

        if st.form_submit_button("Agregar gasto recurrente con tarjeta"):
            if categoria not in st.session_state.categorias:
                st.session_state.categorias.append(categoria)
                guardar("categorias")

            st.session_state.gastos_recurrentes_tarjeta.append({
                "id": str(uuid.uuid4()),
                "nombre": nombre,
                "tarjeta_id": mapa_tarjetas[tarjeta_nombre],
                "tarjeta_nombre": tarjeta_nombre,
                "categoria": categoria,
                "monto": monto,
                "dia_cargo": int(dia_cargo),
                "fecha_inicio": fecha_inicio.isoformat(),
                "fecha_fin": fecha_fin.isoformat()
            })

            guardar("gastos_recurrentes_tarjeta")
            st.rerun()

    # ==================================================
# RESUMEN Y EDICIÓN DE GASTOS RECURRENTES CON TARJETA
# ==================================================
df_grt = pd.DataFrame(st.session_state.gastos_recurrentes_tarjeta)

if not df_grt.empty:
    st.subheader("📄 Gastos recurrentes con tarjeta registrados")

    df_grt["Eliminar"] = False

    ed_grt = st.data_editor(
        df_grt,
        use_container_width=True,
        column_config={
            "Eliminar": st.column_config.CheckboxColumn(),
            "monto": st.column_config.NumberColumn("Monto mensual"),
            "dia_cargo": st.column_config.NumberColumn("Día de cargo"),
        },
        key="editor_gastos_recurrentes_tarjeta"
    )

    if st.button("Guardar cambios gastos recurrentes con tarjeta"):
        st.session_state.gastos_recurrentes_tarjeta = (
            ed_grt[ed_grt["Eliminar"] == False]
            .drop(columns=["Eliminar"])
            .to_dict("records")
        )

        guardar("gastos_recurrentes_tarjeta")
        st.rerun()
    else:
     st.info("No hay gastos recurrentes con tarjeta registrados.")

else:
    st.info("Primero debes registrar una tarjeta de crédito.")



st.header("🔁 Gastos diarios con tarjeta de crédito")
if st.session_state.tarjetas:
    mapa = {t["nombre"]: t["id"] for t in st.session_state.tarjetas}

    with st.form("form_gasto_tarjeta"):
        fecha = st.date_input("Fecha gasto", fecha_inicio_sim)
        tarjeta = st.selectbox("Tarjeta", list(mapa.keys()))
        categoria = st.selectbox("Categoría", st.session_state.categorias + ["➕ Nueva"])
        if categoria == "➕ Nueva":
            categoria = st.text_input("Nueva categoría")
        descripcion = st.text_input("Descripción")
        monto = st.number_input("Monto", min_value=0.0)

        if st.form_submit_button("Agregar gasto tarjeta"):
            st.session_state.gastos_tarjeta.append({
                "fecha": fecha.isoformat(),
                "tarjeta_id": mapa[tarjeta],
                "tarjeta_nombre": tarjeta,
                "categoria": categoria,
                "descripcion": descripcion,
                "monto": monto
            })
            guardar("gastos_tarjeta")
            st.rerun()

df_gt = pd.DataFrame(st.session_state.gastos_tarjeta)
if not df_gt.empty:
    df_gt["fecha"] = pd.to_datetime(df_gt["fecha"], errors="coerce")
    df_gt["fecha"] = df_gt["fecha"].apply(
        lambda x: x.date() if pd.notnull(x) and hasattr(x, "date") else x
    )

    df_gt["Eliminar"] = False
    ed = st.data_editor(df_gt, use_container_width=True)
    if st.button("Guardar cambios gastos tarjeta"):
        st.session_state.gastos_tarjeta = (
            ed[ed["Eliminar"] == False]
            .drop(columns=["Eliminar"])
            .to_dict("records")
        )
        guardar("gastos_tarjeta")
        st.rerun()

def obtener_ciclo_tarjeta(fecha, dia_cierre):
    fecha = pd.to_datetime(fecha)
    if fecha.day <= dia_cierre:
        cierre = fecha.replace(day=dia_cierre)
    else:
        cierre = (fecha + pd.DateOffset(months=1)).replace(day=dia_cierre)
    inicio = cierre - pd.DateOffset(months=1) + timedelta(days=1)
    return inicio.date(), cierre.date()

# =============================
# EXPANDIR GASTOS RECURRENTES DE TARJETA
# =============================

gastos_tarjeta_recurrentes_expandido = []

for g in st.session_state.gastos_recurrentes_tarjeta:
    fecha_ini = pd.to_datetime(g["fecha_inicio"])
    fecha_fin_g = pd.to_datetime(g["fecha_fin"])

    for mes in pd.date_range(fecha_inicio_sim, fecha_fin_sim, freq="MS"):
        try:
            fecha_cargo = mes.replace(day=int(g["dia_cargo"]))

            if fecha_cargo >= fecha_ini and fecha_cargo <= fecha_fin_g:
                gastos_tarjeta_recurrentes_expandido.append({
                    "fecha": fecha_cargo.date(),
                    "tarjeta_id": g["tarjeta_id"],
                    "tarjeta_nombre": g["tarjeta_nombre"],
                    "categoria": g["categoria"],
                    "descripcion": g["nombre"],
                    "monto": g["monto"]
                })
        except:
            pass

df_grt_expandido = pd.DataFrame(gastos_tarjeta_recurrentes_expandido)

# 👉 ESTE ES EL DATAFRAME CLAVE
if not df_grt_expandido.empty:
    df_gt_calc = pd.concat([df_gt, df_grt_expandido], ignore_index=True)
else:
    df_gt_calc = df_gt.copy()

# ==================================================
# CÁLCULOS FINALES Y GRÁFICO (CON SALDO RESALTADO ✅)
# ==================================================
fechas = pd.date_range(fecha_inicio_sim, fecha_fin_sim, freq="D")

# Ingresos y gastos diarios
g_diarios = df_g.groupby("fecha")["monto"].sum().reindex(fechas, fill_value=0) if not df_g.empty else pd.Series(0.0, index=fechas)

g_fijos = pd.Series(0.0, index=fechas)
for _, r in df_fijos.iterrows():
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

egresos_tarjeta = pd.Series(0.0, index=fechas)

if not df_gt.empty:
    for t in st.session_state.tarjetas:
        df_t = df_gt[df_gt["tarjeta_id"] == t["id"]]
        for _, g in df_t.iterrows():
            _, cierre = obtener_ciclo_tarjeta(g["fecha"], t["dia_cierre"])
            fecha_pago = (pd.Timestamp(cierre) + pd.DateOffset(months=1)).replace(day=t["dia_pago"])
            if fecha_pago in egresos_tarjeta.index:
                egresos_tarjeta.loc[fecha_pago] += g["monto"]

saldo = (
    ahorro_inicial
    + ing_rec.cumsum()
    + ing_punt.cumsum()
    - g_diarios.cumsum()
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

for cuenta in st.session_state.cuentas_ahorro:
    nombre_cuenta = cuenta["nombre"]
    saldo_ini = cuenta["saldo_inicial"]

    # Serie base de la cuenta secundaria
    serie_sec = pd.Series(saldo_ini, index=fechas)

    # Aplicar transferencias
    for t in st.session_state.transferencias:
        f = pd.to_datetime(t["fecha"])

        if f in serie_sec.index:
            # Sale dinero de esta cuenta
            if t["origen"] == cuenta["id"]:
                serie_sec.loc[f:] -= t["monto"]

            # Entra dinero a esta cuenta
            if t["destino"] == cuenta["id"]:
                serie_sec.loc[f:] += t["monto"]

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
    "egresos": g_diarios + g_fijos + egresos_tarjeta
})

df_plot["mes"] = df_plot["fecha"].dt.to_period("M")
mensual = df_plot.groupby("mes")[["ingresos", "egresos"]].sum().reset_index()
mensual["fecha_mes"] = mensual["mes"].dt.to_timestamp()

# ==================================================
# GRÁFICO PROFESIONAL DE EVOLUCIÓN DE AHORROS
# ==================================================
st.header("📈 Evolución de ahorros")

MESES_ES = {
    1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril",
    5: "Mayo", 6: "Junio", 7: "Julio", 8: "Agosto",
    9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre"
}

# Selector de fecha para mostrar saldo
hoy = pd.Timestamp.today().normalize()

if hoy < fechas.min() or hoy > fechas.max():
    fecha_saldo_sel = st.date_input("📅 Fecha para mostrar saldo", fechas.max().date())
else:
    fecha_saldo_sel = st.date_input("📅 Fecha para mostrar saldo", hoy.date())

fecha_saldo_sel = pd.to_datetime(fecha_saldo_sel)

col1, col2 = st.columns(2)

with col1:
    rango_y1 = st.slider(
        "Saldo / Ahorro total (S/)",
        0, 300000, (0, 150000),
        step=10000
    )

with col2:
    rango_y2 = st.slider(
        "Ingresos / Egresos mensuales (S/)",
        0, 300000, (0, 80000),
        step=10000
    )

# Opciones de visualización
mostrar_ahorro_total = st.checkbox("Mostrar ahorro total", value=True)
mostrar_secundarias = st.checkbox("Mostrar cuentas secundarias", value=False)

fig, ax1 = plt.subplots(figsize=(14, 7))

# Cuenta principal
ax1.plot(
    fechas,
    serie_cuenta_principal,
    color="#2E7D32",
    linewidth=3.0,
    label="Cuenta de ahorros principal"
)

# Cuentas secundarias opcionales
if mostrar_secundarias:
    for nombre_cuenta, serie_sec in saldos_sec.items():
        ax1.plot(
            fechas,
            serie_sec,
            linestyle="--",
            linewidth=2.2,
            label=f"Cuenta secundaria: {nombre_cuenta}"
        )

        if fecha_saldo_sel in serie_sec.index:
            saldo_sec_val = serie_sec.loc[fecha_saldo_sel]

            ax1.scatter(
                fecha_saldo_sel,
                saldo_sec_val,
                s=80,
                zorder=5
            )

            ax1.annotate(
                f"{nombre_cuenta}\nS/ {saldo_sec_val:,.0f}",
                xy=(fecha_saldo_sel, saldo_sec_val),
                xytext=(15, 35),
                textcoords="offset points",
                fontsize=12,
                bbox=dict(boxstyle="round,pad=0.35", fc="white"),
                arrowprops=dict(arrowstyle="->")
            )
# Ahorro total
if mostrar_ahorro_total:
    ax1.plot(
        fechas,
        serie_ahorro_total,
        color="black",
        linestyle=":",
        linewidth=3.0,
        label="Ahorro total"
    )

ax1.set_ylim(rango_y1)
ax1.axhline(0, color="#BDBDBD", linestyle="--", linewidth=1)

# Etiqueta de cuenta principal
if fecha_saldo_sel in serie_cuenta_principal.index:
    saldo_principal_val = serie_cuenta_principal.loc[fecha_saldo_sel]

    ax1.scatter(
        fecha_saldo_sel,
        saldo_principal_val,
        color="#2E7D32",
        s=90,
        zorder=5
    )

    ax1.annotate(
        f"Cuenta principal\nS/ {saldo_principal_val:,.0f}",
        xy=(fecha_saldo_sel, saldo_principal_val),
        xytext=(15, 20),
        textcoords="offset points",
        fontsize=12,
        bbox=dict(boxstyle="round,pad=0.35", fc="white", ec="#2E7D32"),
        arrowprops=dict(arrowstyle="->", color="#2E7D32")
    )

# Etiqueta de ahorro total
if mostrar_ahorro_total and fecha_saldo_sel in serie_ahorro_total.index:
    ahorro_total_val = serie_ahorro_total.loc[fecha_saldo_sel]

    ax1.scatter(
        fecha_saldo_sel,
        ahorro_total_val,
        color="black",
        s=90,
        zorder=5
    )

    ax1.annotate(
        f"Ahorro total\nS/ {ahorro_total_val:,.0f}",
        xy=(fecha_saldo_sel, ahorro_total_val),
        xytext=(15, -45),
        textcoords="offset points",
        fontsize=12,
        bbox=dict(boxstyle="round,pad=0.35", fc="white", ec="black"),
        arrowprops=dict(arrowstyle="->", color="black")
    )

# Barras ingresos / egresos
ax2 = ax1.twinx()
offset = pd.Timedelta(days=7)

ax2.bar(
    mensual["fecha_mes"] - offset,
    mensual["ingresos"],
    width=10,
    color="#81C784",
    alpha=0.80,
    label="Ingresos"
)

ax2.bar(
    mensual["fecha_mes"] + offset,
    mensual["egresos"],
    width=10,
    color="#EF9A9A",
    alpha=0.80,
    label="Egresos"
)

ax2.set_ylim(rango_y2)
ax2.invert_yaxis()

# Formato eje X: Mayo 2026, Junio 2026...
ticks_mensuales = pd.date_range(fechas.min(), fechas.max(), freq="MS")

labels_mensuales = [
    f"{MESES_ES[t.month]} {t.year}" for t in ticks_mensuales
]

ax1.set_xticks(ticks_mensuales)
ax1.set_xticklabels(labels_mensuales, rotation=35, ha="right", fontsize=12)

# Tamaño de letras para celular
ax1.tick_params(axis="y", labelsize=12)
ax2.tick_params(axis="y", labelsize=12)

ax1.set_ylabel("Saldo / Ahorro total (S/)", fontsize=13)
ax2.set_ylabel("Ingresos / Egresos mensuales (S/)", fontsize=13)

# Leyenda limpia
handles, labels = [], []

for a in (ax1, ax2):
    h, l = a.get_legend_handles_labels()
    handles += h
    labels += l

ax1.legend(
    handles,
    labels,
    loc="upper center",
    bbox_to_anchor=(0.5, -0.22),
    ncol=2,
    frameon=False,
    fontsize=12
)

ax1.grid(True, linestyle="--", alpha=0.25)

plt.tight_layout()
st.pyplot(fig, use_container_width=True)

# ==================================================
#  RESUMEN MENSUAL POR TARJETA DE CRÉDITO
# ==================================================
st.header("💳 Resumen mensual por tarjeta de crédito")

MESES_ES = {
    1: "enero", 2: "febrero", 3: "marzo", 4: "abril",
    5: "mayo", 6: "junio", 7: "julio", 8: "agosto",
    9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre"
}

if not df_gt_calc.empty:
    resumen = []

    for t in st.session_state.tarjetas:
        df_t = df_gt_calc[df_gt_calc["tarjeta_id"] == t["id"]]

        for _, g in df_t.iterrows():
            fecha_gasto = pd.to_datetime(g["fecha"])

            inicio, cierre = obtener_ciclo_tarjeta(fecha_gasto, t["dia_cierre"])
            fecha_pago = (pd.Timestamp(cierre) + pd.DateOffset(months=1)).replace(day=t["dia_pago"])

            mes_acumulacion = f"{MESES_ES[fecha_gasto.month]} {fecha_gasto.year}"

            resumen.append({
                "Tarjeta": t["nombre"],
                "Mes consumo": mes_acumulacion,
                "Fecha pago": fecha_pago.date() if pd.notnull(fecha_pago) else None,
                "Inicio ciclo": inicio,
                "Fin ciclo": cierre,
                "Monto": g["monto"]
            })

    df_res = pd.DataFrame(resumen)

    resumen_mensual = (
        df_res.groupby(["Tarjeta", "Mes consumo", "Fecha pago", "Inicio ciclo", "Fin ciclo"])["Monto"]
        .sum()
        .reset_index()
        .sort_values("Fecha pago")
    )

    st.dataframe(resumen_mensual, use_container_width=True)

else:
    st.info("No hay gastos con tarjeta registrados.")