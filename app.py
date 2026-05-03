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
    "categorias": [
        "Alimentación", "Transporte", "Alcohol",
        "Vuelos", "Salud", "Entretenimiento", "Otros"],
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

st.header("💳 Gastos con tarjeta")

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

st.header("📈 Evolución de ahorros")



# Selector de fecha para mostrar saldo
hoy = pd.Timestamp.today().normalize()
if hoy < fechas.min() or hoy > fechas.max():
    fecha_saldo_sel = st.date_input("📅 Fecha para mostrar saldo", fechas.max().date())
else:
    fecha_saldo_sel = st.date_input("📅 Fecha para mostrar saldo", hoy.date())

fecha_saldo_sel = pd.to_datetime(fecha_saldo_sel)

col1, col2 = st.columns(2)
with col1:
    rango_y1 = st.slider("Saldo (S/)", 0, 300000, (0, 150000), step=10000)
with col2:
    rango_y2 = st.slider("Ingresos / Egresos mensuales (S/)", 0, 300000, (0, 80000), step=10000)

fig, ax1 = plt.subplots(figsize=(12, 5))
ax1.plot(df_plot["fecha"], saldo, color="#2E7D32", linewidth=2.5, label="Saldo")

# ==================================================
# EXTENSIÓN MULTICUENTA DEL GRÁFICO
# ==================================================
cuenta_sel = st.selectbox(
    "Cuenta secundaria a visualizar",
    ["Ninguna"] + list(saldos_sec.keys())
)

# Cuenta principal
ax1.plot(
    fechas,
    serie_cuenta_principal,
    color="#2E7D32",
    linewidth=2.5,
    label="Cuenta principal"
)

# Cuenta secundaria seleccionada
if cuenta_sel != "Ninguna":
    ax1.plot(
        fechas,
        saldos_sec[cuenta_sel],
        color="#1976D2",
        linestyle="--",
        linewidth=2.0,
        label=f"Ahorro {cuenta_sel}"
    )

# Ahorro total
ax1.plot(
    fechas,
    serie_ahorro_total,
    color="black",
    linestyle=":",
    linewidth=2.0,
    label="Ahorro total"
)


ax1.set_ylim(rango_y1)
ax1.axhline(0, color="#BDBDBD", linestyle="--")

# Punto y etiqueta del saldo
if fecha_saldo_sel in saldo.index:
    saldo_val = saldo.loc[fecha_saldo_sel]
    ax1.scatter(fecha_saldo_sel, saldo_val, color="#2E7D32", s=70, zorder=5)
    ax1.annotate(
        f"Saldo al {fecha_saldo_sel.strftime('%d-%m-%Y')}\nS/ {saldo_val:,.0f}",
        xy=(fecha_saldo_sel, saldo_val),
        xytext=(10, 15),
        textcoords="offset points",
        fontsize=10,
        bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="#2E7D32"),
        arrowprops=dict(arrowstyle="->", color="#2E7D32")
    )

ax2 = ax1.twinx()
offset = pd.Timedelta(days=7)

ax2.bar(mensual["fecha_mes"] - offset, mensual["ingresos"], width=10, color="#81C784", alpha=0.85, label="Ingresos")
ax2.bar(mensual["fecha_mes"] + offset, mensual["egresos"], width=10, color="#EF9A9A", alpha=0.85, label="Egresos")
ax2.set_ylim(rango_y2)
ax2.invert_yaxis()

handles, labels = [], []
for a in (ax1, ax2):
    h, l = a.get_legend_handles_labels()
    handles += h
    labels += l

ax1.legend(handles, labels, loc="upper center",
           bbox_to_anchor=(0.5, -0.15), ncol=3, frameon=False)

plt.tight_layout()
st.pyplot(fig)

# ==================================================
# PASO 5A — RESUMEN MENSUAL POR TARJETA
# ==================================================
st.header("💳 Resumen mensual por tarjeta")

if not df_gt.empty:
    resumen = []
    for t in st.session_state.tarjetas:
        df_t = df_gt[df_gt["tarjeta_id"] == t["id"]]
        for _, g in df_t.iterrows():
            inicio, cierre = obtener_ciclo_tarjeta(g["fecha"], t["dia_cierre"])
            fecha_pago = (pd.Timestamp(cierre) + pd.DateOffset(months=1)).replace(day=t["dia_pago"])
            resumen.append({
                "Tarjeta": t["nombre"],
                "Inicio ciclo": inicio,
                "Fin ciclo": cierre, 
                "Fecha pago": fecha_pago.date() if pd.notnull(fecha_pago) else None,
                "Mes pago": fecha_pago.strftime("%Y-%m") if pd.notnull(fecha_pago) else None,
                "Monto": g["monto"]
            })

    df_res = pd.DataFrame(resumen)
    resumen_mensual = (
        df_res.groupby(["Tarjeta", "Mes pago", "Fecha pago"])["Monto"]
        .sum()
        .reset_index()
        .sort_values("Fecha pago")
    )

    st.dataframe(resumen_mensual, use_container_width=True)
else:
    st.info("No hay gastos con tarjeta registrados.")