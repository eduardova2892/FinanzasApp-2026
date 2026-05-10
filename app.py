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

st.title("📊 Mis Finanzas Personales")


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
# CONFIGURACIÓN DE SIMULACIÓN Y CUENTAS DE AHORRO
# ==================================================
with st.expander("⚙️ Configuración y cuentas de ahorro", expanded=True):

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

    st.subheader("🏦 Cuenta de ahorro principal")

    nombre_cuenta_principal = st.text_input(
        "Nombre de la cuenta principal",
        conf.get("nombre_cuenta_principal", "Cuenta principal")
    )

    ahorro_inicial = st.number_input(
        f"Saldo inicial - {nombre_cuenta_principal}",
        min_value=0.0,
        step=100.0,
        value=float(conf.get("ahorro_inicial", 0.0))
    )

    st.session_state["configuracion"] = {
        "fecha_inicio_sim": fecha_inicio_sim.isoformat(),
        "fecha_fin_sim": fecha_fin_sim.isoformat(),
        "ahorro_inicial": ahorro_inicial,
        "nombre_cuenta_principal": nombre_cuenta_principal
    }

    guardar("configuracion")

    st.divider()

    st.subheader("🏦 Cuentas de ahorro secundarias")

    with st.form("form_cuenta_ahorro"):
        nombre = st.text_input("Nombre de la cuenta", "Ahorro Viajes")
        saldo_ini = st.number_input("Saldo inicial", min_value=0.0)

        if st.form_submit_button("Agregar cuenta"):
            st.session_state["cuentas_ahorro"].append({
                "id": str(uuid.uuid4()),
                "nombre": nombre,
                "saldo_inicial": saldo_ini
            })
            guardar("cuentas_ahorro")
            st.rerun()

    # ==================================================
    # RESUMEN EDITABLE DE CUENTAS DE AHORRO / DÉBITO
    # ==================================================
    st.subheader("🏦 Cuentas de ahorro (débito)")

    saldo_principal = st.session_state["configuracion"].get(
        "ahorro_inicial",
        0
    )

    cuentas_resumen = [{
        "id": "principal",
        "Cuenta": nombre_cuenta_principal,
        "Saldo inicial": saldo_principal,
        "Tipo": "Principal",
        "Eliminar": False
    }]

    for c in st.session_state["cuentas_ahorro"]:
        cuentas_resumen.append({
            "id": c["id"],
            "Cuenta": c["nombre"],
            "Saldo inicial": c["saldo_inicial"],
            "Tipo": "Secundaria",
            "Eliminar": False
        })

    df_cuentas_resumen = pd.DataFrame(cuentas_resumen)

    ed_cuentas = st.data_editor(
        df_cuentas_resumen.drop(columns=["id"]),
        use_container_width=True,
        hide_index=True,
        disabled=["Cuenta", "Saldo inicial", "Tipo"],
        column_config={
            "Eliminar": st.column_config.CheckboxColumn()
        },
        key="editor_cuentas_ahorro_resumen"
    )

    if st.button("Guardar cambios cuentas de ahorro"):
        df_original = df_cuentas_resumen.copy()
        df_original["Eliminar"] = ed_cuentas["Eliminar"].values

        cuentas_a_eliminar = df_original[
            (df_original["Eliminar"] == True) &
            (df_original["Tipo"] == "Secundaria")
        ]["id"].tolist()

        st.session_state["cuentas_ahorro"] = [
            c for c in st.session_state["cuentas_ahorro"]
            if c["id"] not in cuentas_a_eliminar
        ]

        guardar("cuentas_ahorro")
        st.rerun()

    st.divider()

    # ==================================================
    # TRANSFERENCIAS ENTRE CUENTAS DE AHORRO
    # ==================================================
    st.header("🔁 Transferencias entre cuentas")

    cuentas_map = {nombre_cuenta_principal: "principal"}

    for c in st.session_state["cuentas_ahorro"]:
        cuentas_map[c["nombre"]] = c["id"]

    with st.form("form_transferencia"):
        fecha = st.date_input("Fecha", fecha_inicio_sim)
        origen = st.selectbox("Cuenta origen", list(cuentas_map.keys()))
        destino = st.selectbox("Cuenta destino", list(cuentas_map.keys()))
        monto = st.number_input("Monto", min_value=0.0)

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
    # RESUMEN Y EDICIÓN DE TRANSFERENCIAS
    # ==================================================
    df_transf = pd.DataFrame(st.session_state["transferencias"])

    if not df_transf.empty:
        df_transf["fecha"] = pd.to_datetime(df_transf["fecha"], errors="coerce").dt.date
        df_transf["Eliminar"] = False

        st.subheader("📄 Historial de transferencias")

        ed = st.data_editor(
            df_transf,
            use_container_width=True,
            column_config={
                "Eliminar": st.column_config.CheckboxColumn()
            },
            key="editor_transferencias"
        )

        if st.button("Guardar cambios transferencias"):
            df_editado = ed[ed["Eliminar"] == False].drop(columns=["Eliminar"]).copy()

            if "fecha" in df_editado.columns:
                df_editado["fecha"] = pd.to_datetime(
                    df_editado["fecha"],
                    errors="coerce"
                ).dt.strftime("%Y-%m-%d")

            st.session_state["transferencias"] = df_editado.to_dict("records")

            guardar("transferencias")
            st.rerun()

    else:
        st.info("No hay transferencias registradas.")
# ==================================================
# INGRESOS
# ==================================================
with st.expander("💰 Ingresos", expanded=False):

    # ==================================================
    # INGRESOS RECURRENTES
    # ==================================================
    st.header("💰 Ingresos recurrentes")

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

        st.subheader("📄 Ingresos recurrentes registrados")

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

    # ==================================================
    # INGRESOS PUNTUALES
    # ==================================================
    st.header("💵 Ingresos puntuales")

    with st.form("form_ingreso_puntual"):

        concepto = st.text_input("Concepto")

        fecha = st.date_input(
            "Fecha",
            fecha_inicio_sim
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

            st.session_state["ingresos_puntuales"] = (
                df_editado.to_dict("records")
            )

            guardar("ingresos_puntuales")
            st.rerun()

    else:
        st.info("No hay ingresos puntuales registrados.")
# ==================================================
# GASTOS DÉBITO / CUENTAS DE AHORRO
# ==================================================
with st.expander("🧾 Gastos débito / cuentas de ahorro", expanded=False):

    nombre_cuenta_principal = st.session_state["configuracion"].get(
        "nombre_cuenta_principal",
        "Cuenta principal"
    )

    cuentas_debito_map = {nombre_cuenta_principal: "principal"}

    for c in st.session_state["cuentas_ahorro"]:
        cuentas_debito_map[c["nombre"]] = c["id"]

    # ==================================================
    # GASTOS FIJOS
    # ==================================================
    st.header("📆 Gastos fijos")

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

        st.subheader("📄 Gastos fijos registrados")

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
            df_fijos,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Eliminar": st.column_config.CheckboxColumn(),
                "monto": st.column_config.NumberColumn("Monto mensual"),
                "dia_cobro": st.column_config.NumberColumn("Día de cobro")
            },
            key="editor_gastos_fijos"
        )

        if st.button("Guardar cambios gastos fijos"):

            df_editado = (
                ed_fijos[
                    ed_fijos["Eliminar"] == False
                ]
                .drop(columns=["Eliminar"])
                .copy()
            )

            if "fecha_inicio" in df_editado.columns:
                df_editado["fecha_inicio"] = pd.to_datetime(
                    df_editado["fecha_inicio"],
                    errors="coerce"
                ).dt.strftime("%Y-%m-%d")

            st.session_state["gastos_fijos"] = (
                df_editado.to_dict("records")
            )

            guardar("gastos_fijos")
            st.rerun()

    else:
        st.info("No hay gastos fijos registrados.")

    st.divider()

    # ==================================================
    # GASTOS DIARIOS DÉBITO / AHORROS
    # ==================================================
    st.header("🧾 Gastos diarios débito")

    with st.form("form_gasto_diario", clear_on_submit=True):

        fecha = st.date_input(
            "Fecha",
            fecha_inicio_sim
        )

        cuenta_origen_nombre = st.selectbox(
            "Cuenta de origen",
            list(cuentas_debito_map.keys()),
            key="cuenta_origen_gasto_diario"
        )

        categoria = st.selectbox(
            "Categoría",
            st.session_state["categorias"] + ["➕ Nueva"],
            key="categoria_gasto_diario_debito"
        )

        if categoria == "➕ Nueva":
            categoria = st.text_input(
                "Nueva categoría",
                key="nueva_categoria_gasto_diario_debito"
            )

        descripcion = st.text_input("Descripción")

        monto = st.number_input(
            "Monto",
            min_value=0.0,
            step=1.0,
            key="monto_gasto_diario_debito"
        )

        submitted = st.form_submit_button("Agregar gasto")

        if submitted:

            if categoria not in st.session_state["categorias"]:
                st.session_state["categorias"].append(categoria)
                guardar("categorias")

            nuevo_gasto = {
                "id": str(uuid.uuid4()),
                "fecha": fecha.isoformat(),
                "cuenta_origen": cuentas_debito_map[cuenta_origen_nombre],
                "cuenta_origen_nombre": cuenta_origen_nombre,
                "categoria": categoria,
                "descripcion": descripcion,
                "monto": float(monto)
            }

            st.session_state["gastos_diarios"].append(nuevo_gasto)
            guardar("gastos_diarios")
            st.success("Gasto débito agregado correctamente")

    # ==================================================
    # RESUMEN Y EDICIÓN DE GASTOS DIARIOS DÉBITO / AHORROS
    # ==================================================
    df_g = pd.DataFrame(st.session_state["gastos_diarios"])

    if not df_g.empty:

        st.subheader("📄 Gastos diarios débito ")

        df_g["fecha"] = pd.to_datetime(
            df_g["fecha"],
            errors="coerce"
        ).dt.date

        df_g["monto"] = pd.to_numeric(
            df_g["monto"],
            errors="coerce"
        ).fillna(0)

        df_g["Eliminar"] = False

        ed_g = st.data_editor(
            df_g,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Eliminar": st.column_config.CheckboxColumn(),
                "monto": st.column_config.NumberColumn("Monto")
            },
            key="editor_gastos_debito"
        )

        if st.button("Guardar cambios gastos débito / ahorros"):

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

            st.session_state["gastos_diarios"] = (
                df_editado.to_dict("records")
            )

            guardar("gastos_diarios")
            st.rerun()

    else:
        st.info("No hay gastos débito registrados.")
# ==================================================
# TARJETAS DE CRÉDITO
# ==================================================
with st.expander("💳 Tarjetas de crédito", expanded=False):

    # ==================================================
    # REGISTRO DE TARJETAS
    # ==================================================
    st.header("💳 Tarjetas registradas")

    with st.form("form_tarjeta"):

        nombre = st.text_input("Nombre tarjeta", "Visa")
        dia_cierre = st.number_input(
            "Día de cierre",
            1,
            31,
            20
        )
        dia_pago = st.number_input(
            "Día de pago",
            1,
            31,
            10
        )

        if st.form_submit_button("Agregar tarjeta"):

            st.session_state["tarjetas"].append({
                "id": str(uuid.uuid4()),
                "nombre": nombre,
                "dia_cierre": int(dia_cierre),
                "dia_pago": int(dia_pago)
            })

            guardar("tarjetas")
            st.rerun()

    # ==================================================
    # RESUMEN Y EDICIÓN DE TARJETAS
    # ==================================================
    df_tar = pd.DataFrame(st.session_state["tarjetas"])

    if not df_tar.empty:

        st.subheader("📄 Tarjetas de crédito registradas")

        df_tar["Eliminar"] = False

        ed_tar = st.data_editor(
            df_tar.drop(columns=["id"]),
            use_container_width=True,
            hide_index=True,
            column_config={
                "Eliminar": st.column_config.CheckboxColumn(),
                "dia_cierre": st.column_config.NumberColumn("Día de cierre"),
                "dia_pago": st.column_config.NumberColumn("Día de pago")
            },
            key="editor_tarjetas_credito"
        )

        if st.button("Guardar cambios tarjetas"):

            df_original = df_tar.copy()
            df_original["Eliminar"] = ed_tar["Eliminar"].values

            tarjetas_a_eliminar = df_original[
                df_original["Eliminar"] == True
            ]["id"].tolist()

            st.session_state["tarjetas"] = [
                t for t in st.session_state["tarjetas"]
                if t["id"] not in tarjetas_a_eliminar
            ]

            guardar("tarjetas")
            st.rerun()

    else:
        st.info("No hay tarjetas registradas.")

    st.divider()

    if st.session_state["tarjetas"]:

        mapa_tarjetas = {
            t["nombre"]: t["id"]
            for t in st.session_state["tarjetas"]
        }

        # ==================================================
        # GASTOS RECURRENTES CON TARJETA
        # ==================================================
        st.header("🔁 Gastos recurrentes con tarjeta")

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

            st.subheader("📄 Gastos recurrentes registrados")

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

            ed_grt = st.data_editor(
                df_grt,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Eliminar": st.column_config.CheckboxColumn(),
                    "monto": st.column_config.NumberColumn("Monto mensual"),
                    "dia_cargo": st.column_config.NumberColumn("Día de cargo")
                },
                key="editor_gastos_recurrentes_tarjeta"
            )

            if st.button("Guardar cambios gastos recurrentes"):

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

        st.divider()

        # ==================================================
        # GASTOS DIARIOS CON TARJETA
        # ==================================================
        st.header("🧾 Gastos diarios con tarjeta")

        with st.form("form_gasto_tarjeta", clear_on_submit=True):

            fecha = st.date_input(
                "Fecha gasto",
                fecha_inicio_sim,
                key="fecha_gasto_tarjeta"
            )

            tarjeta_nombre = st.selectbox(
                "Tarjeta",
                list(mapa_tarjetas.keys()),
                key="tarjeta_gasto_diario"
            )

            categoria = st.selectbox(
                "Categoría",
                st.session_state["categorias"] + ["➕ Nueva"],
                key="categoria_gasto_tarjeta"
            )

            if categoria == "➕ Nueva":
                categoria = st.text_input(
                    "Nueva categoría",
                    key="nueva_categoria_gasto_tarjeta"
                )

            descripcion = st.text_input(
                "Descripción",
                key="descripcion_gasto_tarjeta"
            )

            monto = st.number_input(
                "Monto",
                min_value=0.0,
                step=1.0,
                key="monto_gasto_tarjeta"
            )

            if st.form_submit_button("Agregar gasto tarjeta"):

                if categoria not in st.session_state["categorias"]:
                    st.session_state["categorias"].append(categoria)
                    guardar("categorias")

                st.session_state["gastos_tarjeta"].append({
                    "id": str(uuid.uuid4()),
                    "fecha": fecha.isoformat(),
                    "tarjeta_id": mapa_tarjetas[tarjeta_nombre],
                    "tarjeta_nombre": tarjeta_nombre,
                    "categoria": categoria,
                    "descripcion": descripcion,
                    "monto": float(monto)
                })

                guardar("gastos_tarjeta")
                st.success("Gasto con tarjeta agregado correctamente")

        # ==================================================
        # RESUMEN GASTOS DIARIOS CON TARJETA
        # ==================================================
        # ==================================================
        # RESUMEN GASTOS DIARIOS CON TARJETA
        # ==================================================
        df_gt = pd.DataFrame(st.session_state["gastos_tarjeta"])

        if not df_gt.empty:

            st.subheader("📄 Gastos diarios con tarjeta registrados")

            df_gt["fecha"] = pd.to_datetime(
                df_gt["fecha"],
                errors="coerce"
            ).dt.date

            df_gt["monto"] = pd.to_numeric(
                df_gt["monto"],
                errors="coerce"
            ).fillna(0)

            df_gt["Eliminar"] = False

            ed_gt = st.data_editor(
                df_gt,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Eliminar": st.column_config.CheckboxColumn(),
                    "monto": st.column_config.NumberColumn("Monto")
                },
                key="editor_gastos_tarjeta"
            )

            if st.button("Guardar cambios gastos tarjeta"):

                df_editado = (
                    ed_gt[ed_gt["Eliminar"] == False]
                    .drop(columns=["Eliminar"])
                    .copy()
                )

                if "fecha" in df_editado.columns:
                    df_editado["fecha"] = pd.to_datetime(
                        df_editado["fecha"],
                        errors="coerce"
                    ).dt.strftime("%Y-%m-%d")

                st.session_state["gastos_tarjeta"] = (
                    df_editado.to_dict("records")
                )

                guardar("gastos_tarjeta")
                st.rerun()

        else:
            st.info("No hay gastos diarios con tarjeta registrados.")

    else:
        st.warning("Primero debes registrar una tarjeta de crédito.")

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

for cuenta in st.session_state.cuentas_ahorro:
    nombre_cuenta = cuenta["nombre"]
    saldo_ini = float(cuenta["saldo_inicial"])

    serie_sec = pd.Series(saldo_ini, index=fechas)

    # Gastos débito asociados a esta cuenta secundaria
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
    for t in st.session_state.transferencias:
        f = pd.to_datetime(t["fecha"])

        if f in serie_sec.index:
            if t["origen"] == cuenta["id"]:
                serie_sec.loc[f:] -= float(t["monto"])

            if t["destino"] == cuenta["id"]:
                serie_sec.loc[f:] += float(t["monto"])

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

horizonte_meses = st.selectbox(
    "Horizonte del gráfico",
    [3, 6, 9, 12],
    index=0,
    format_func=lambda x: f"{x} meses"
)

fecha_x_inicio = fechas.min()
fecha_x_fin = min(
    fecha_x_inicio + pd.DateOffset(months=horizonte_meses),
    fechas.max()
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
    label=nombre_cuenta_principal
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
        f"{nombre_cuenta_principal}\nS/ {saldo_principal_val:,.0f}",
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


ax1.set_xlim(fecha_x_inicio, fecha_x_fin)
ax2.set_xlim(fecha_x_inicio, fecha_x_fin)



# Formato eje X: Mayo 2026, Junio 2026...
ticks_mensuales = pd.date_range(fecha_x_inicio, fecha_x_fin, freq="MS")

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
# META MENSUAL DE AHORRO
# ==================================================
st.subheader("🎯 Meta mensual de ahorro")

mes_actual = pd.Timestamp.today().to_period("M")

meta_ahorro = st.number_input(
    "¿Cuánto quieres ahorrar este mes?",
    min_value=0.0,
    step=100.0,
    value=2000.0
)

# Ingresos del mes actual
ingresos_mes_actual = (
    (ing_rec + ing_punt)
    .loc[(ing_rec + ing_punt).index.to_period("M") == mes_actual]
    .sum()
)

# Gastos fijos / comprometidos del mes actual
gastos_fijos_mes_actual = (
    g_fijos
    .loc[g_fijos.index.to_period("M") == mes_actual]
    .sum()
)

# Pagos tarjeta del mes actual
tarjeta_mes_actual = (
    egresos_tarjeta
    .loc[egresos_tarjeta.index.to_period("M") == mes_actual]
    .sum()
)

# Gastos débito diarios ya registrados este mes
gastos_debito_mes_actual = (
    g_diarios_principal
    .loc[g_diarios_principal.index.to_period("M") == mes_actual]
    .sum()
)

gastos_comprometidos = (
    gastos_fijos_mes_actual +
    tarjeta_mes_actual +
    gastos_debito_mes_actual
)

monto_disponible_para_gastar = (
    ingresos_mes_actual -
    gastos_comprometidos -
    meta_ahorro
)

col1, col2, col3 = st.columns(3)

with col1:
    st.metric(
        "Ingresos del mes",
        f"S/ {ingresos_mes_actual:,.0f}"
    )

with col2:
    st.metric(
        "Gastos ya comprometidos",
        f"S/ {gastos_comprometidos:,.0f}"
    )

with col3:
    st.metric(
    "Puedes gastar todavía",
    f"S/ {max(0, monto_disponible_para_gastar):,.0f}"
)

if monto_disponible_para_gastar >= 0:
    st.success(
        f"Vas bien. Puedes gastar hasta S/ {monto_disponible_para_gastar:,.0f} más este mes y aún cumplir tu meta de ahorro."
    )
else:
    st.error(
        f"Ya superaste tu meta de ahorro mensual por S/ {abs(monto_disponible_para_gastar):,.0f}."
    )

# ==================================================
# GRÁFICO DE GASTOS POR CATEGORÍA
# ==================================================
st.header("🥧 Gastos por categoría")

# Selector de mes
meses_disponibles = pd.period_range(
    start=fecha_inicio_sim,
    end=fecha_fin_sim,
    freq="M"
)

opciones_meses = {
    f"{MESES_ES[m.month]} {m.year}": m
    for m in meses_disponibles
}

mes_categoria_txt = st.selectbox(
    "Selecciona el mes para analizar gastos",
    list(opciones_meses.keys()),
    key="mes_gastos_categoria"
)

mes_categoria = opciones_meses[mes_categoria_txt]

# =============================
# Gastos débito / diarios
# =============================
df_debito_cat = pd.DataFrame(st.session_state.gastos_diarios)

if not df_debito_cat.empty:
    df_debito_cat["fecha"] = pd.to_datetime(df_debito_cat["fecha"], errors="coerce")
    df_debito_cat["monto"] = pd.to_numeric(df_debito_cat["monto"], errors="coerce").fillna(0)
    df_debito_cat["tipo"] = "Débito"

# =============================
# Gastos crédito
# usa df_gt_calc para incluir gastos manuales + recurrentes
# =============================
df_credito_cat = df_gt_calc.copy()

if not df_credito_cat.empty:
    df_credito_cat["fecha"] = pd.to_datetime(df_credito_cat["fecha"], errors="coerce")
    df_credito_cat["tipo"] = "Crédito"

# =============================
# Unir ambos tipos de gasto
# =============================
# ==================================================
# GASTOS VARIABLES / PUNTUALES POR CATEGORÍA
# SOLO DÉBITO DIARIO + CRÉDITO DIARIO
# ==================================================

# Débito diario
df_debito_cat = pd.DataFrame(st.session_state["gastos_diarios"])

if not df_debito_cat.empty:
    df_debito_cat["fecha"] = pd.to_datetime(
        df_debito_cat["fecha"],
        errors="coerce"
    )

# Crédito diario
df_credito_cat = pd.DataFrame(st.session_state["gastos_tarjeta"])

if not df_credito_cat.empty:
    df_credito_cat["fecha"] = pd.to_datetime(
        df_credito_cat["fecha"],
        errors="coerce"
    )

# Unir SOLO gastos variables
frames_cat = []

if not df_debito_cat.empty:
    frames_cat.append(
        df_debito_cat[["fecha", "categoria", "monto"]]
    )

if not df_credito_cat.empty:
    frames_cat.append(
        df_credito_cat[["fecha", "categoria", "monto"]]
    )

if len(frames_cat) > 0:
    df_gastos_cat = pd.concat(frames_cat, ignore_index=True)
else:
    df_gastos_cat = pd.DataFrame(
        columns=["fecha", "categoria", "monto"]
    )

if not df_gastos_cat.empty:
    df_gastos_cat["mes"] = df_gastos_cat["fecha"].dt.to_period("M")

    df_mes = df_gastos_cat[df_gastos_cat["mes"] == mes_categoria]

    if not df_mes.empty:
        resumen_cat = (
            df_mes.groupby("categoria")["monto"]
            .sum()
            .reset_index()
            .sort_values("monto", ascending=False)
        )

        total_mes = resumen_cat["monto"].sum()

        col1, col2 = st.columns([1.3, 1])

        with col1:
            fig_cat, ax_cat = plt.subplots(figsize=(8, 8))

            ax_cat.pie(
                resumen_cat["monto"],
                labels=resumen_cat["categoria"],
                autopct=lambda p: f"{p:.1f}%\nS/ {p * total_mes / 100:,.0f}",
                startangle=90,
                textprops={"fontsize": 12}
            )

            ax_cat.set_title(
                f"Distribución de gastos - {mes_categoria_txt}",
                fontsize=16,
                pad=20
            )

            ax_cat.axis("equal")

            st.pyplot(fig_cat, use_container_width=True)

        with col2:
            st.subheader(f"Resumen {mes_categoria_txt}")
            st.metric("Gasto total", f"S/ {total_mes:,.0f}")

            st.dataframe(
                resumen_cat.rename(columns={
                    "categoria": "Categoría",
                    "monto": "Monto"
                }),
                use_container_width=True
            )

    else:
        st.info(f"No hay gastos registrados en {mes_categoria_txt}.")
else:
    st.info("No hay gastos registrados para mostrar.")

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


# ==================================================
# GRÁFICO MENSUAL DE GASTOS: DÉBITO, CRÉDITO, FIJOS Y NO FIJOS
# ==================================================
st.header("💳🧾 Gastos mensuales por tipo")

# 1. Débito diario
df_debito_diario_mes = pd.DataFrame(st.session_state["gastos_diarios"])

if not df_debito_diario_mes.empty:
    df_debito_diario_mes["fecha"] = pd.to_datetime(df_debito_diario_mes["fecha"], errors="coerce")
    df_debito_diario_mes["monto"] = pd.to_numeric(df_debito_diario_mes["monto"], errors="coerce").fillna(0)
    df_debito_diario_mes["mes"] = df_debito_diario_mes["fecha"].dt.to_period("M")

    df_debito_diario_mes = (
        df_debito_diario_mes.groupby("mes")["monto"]
        .sum()
        .reset_index()
        .rename(columns={"monto": "Débito diario"})
    )
else:
    df_debito_diario_mes = pd.DataFrame(columns=["mes", "Débito diario"])


# 2. Gastos fijos
gastos_fijos_expandido = []

for _, r in df_fijos.iterrows():
    for mes in pd.date_range(fecha_inicio_sim, fecha_fin_sim, freq="MS"):
        try:
            fecha_gasto_fijo = mes.replace(day=int(r["dia_cobro"]))

            if fecha_gasto_fijo >= pd.to_datetime(r["fecha_inicio"]):
                gastos_fijos_expandido.append({
                    "fecha": fecha_gasto_fijo,
                    "monto": float(r["monto"])
                })
        except:
            pass

df_fijos_mes = pd.DataFrame(gastos_fijos_expandido)

if not df_fijos_mes.empty:
    df_fijos_mes["fecha"] = pd.to_datetime(df_fijos_mes["fecha"], errors="coerce")
    df_fijos_mes["mes"] = df_fijos_mes["fecha"].dt.to_period("M")

    df_fijos_mes = (
        df_fijos_mes.groupby("mes")["monto"]
        .sum()
        .reset_index()
        .rename(columns={"monto": "Gastos fijos mensuales"})
    )
else:
    df_fijos_mes = pd.DataFrame(columns=["mes", "Gastos fijos mensuales"])


# 3. Crédito
df_credito_mes = df_gt_calc.copy()

if not df_credito_mes.empty:
    df_credito_mes["fecha"] = pd.to_datetime(df_credito_mes["fecha"], errors="coerce")
    df_credito_mes["monto"] = pd.to_numeric(df_credito_mes["monto"], errors="coerce").fillna(0)
    df_credito_mes["mes"] = df_credito_mes["fecha"].dt.to_period("M")

    df_credito_mes = (
        df_credito_mes.groupby("mes")["monto"]
        .sum()
        .reset_index()
        .rename(columns={"monto": "Gastos crédito total mensual"})
    )
else:
    df_credito_mes = pd.DataFrame(columns=["mes", "Gastos crédito total mensual"])


# 4. Base mensual
meses_base = pd.DataFrame({
    "mes": pd.period_range(fecha_inicio_sim, fecha_fin_sim, freq="M")
})
# ==================================================
# DATAFRAMES BASE
# ==================================================

df_gd = pd.DataFrame(st.session_state["gastos_diarios"])
df_gf = pd.DataFrame(st.session_state["gastos_fijos"])
df_gt = pd.DataFrame(st.session_state["gastos_tarjeta"])

# Recurrentes crédito ya expandidos
df_grt_expandido = pd.DataFrame(gastos_tarjeta_recurrentes_expandido)

# ==================================================
# DÉBITO DIARIO
# ==================================================

if not df_gd.empty:

    df_gd["fecha"] = pd.to_datetime(df_gd["fecha"], errors="coerce")
    df_gd["monto"] = pd.to_numeric(df_gd["monto"], errors="coerce").fillna(0)

    df_gd["mes"] = df_gd["fecha"].dt.to_period("M")

    df_debito_diario_mes = (
        df_gd.groupby("mes")["monto"]
        .sum()
        .reset_index()
        .rename(columns={"monto": "Débito diario"})
    )

else:
    df_debito_diario_mes = pd.DataFrame(columns=["mes", "Débito diario"])


# ==================================================
# GASTOS FIJOS DÉBITO
# ==================================================

gastos_fijos_expandido = []

for g in st.session_state["gastos_fijos"]:

    fecha_ini = pd.to_datetime(g["fecha_inicio"])

    fechas = pd.date_range(
        start=fecha_ini,
        end=fecha_fin_sim,
        freq="MS"
    )

    for f in fechas:

        fecha_cobro = f.replace(day=min(g["dia_cobro"], 28))

        gastos_fijos_expandido.append({
            "fecha": fecha_cobro,
            "monto": g["monto"]
        })

df_fijos_expandido = pd.DataFrame(gastos_fijos_expandido)

if not df_fijos_expandido.empty:

    df_fijos_expandido["fecha"] = pd.to_datetime(
        df_fijos_expandido["fecha"],
        errors="coerce"
    )

    df_fijos_expandido["mes"] = (
        df_fijos_expandido["fecha"].dt.to_period("M")
    )

    df_fijos_mes = (
        df_fijos_expandido.groupby("mes")["monto"]
        .sum()
        .reset_index()
        .rename(columns={"monto": "Gastos fijos débito"})
    )

else:
    df_fijos_mes = pd.DataFrame(
        columns=["mes", "Gastos fijos débito"]
    )


# ==================================================
# CRÉDITO DIARIO
# ==================================================

if not df_gt.empty:

    df_gt["fecha"] = pd.to_datetime(df_gt["fecha"], errors="coerce")
    df_gt["monto"] = pd.to_numeric(df_gt["monto"], errors="coerce").fillna(0)

    df_gt["mes"] = df_gt["fecha"].dt.to_period("M")

    df_credito_diario_mes = (
        df_gt.groupby("mes")["monto"]
        .sum()
        .reset_index()
        .rename(columns={"monto": "Crédito diario"})
    )

else:
    df_credito_diario_mes = pd.DataFrame(
        columns=["mes", "Crédito diario"]
    )


# ==================================================
# CRÉDITO RECURRENTE
# ==================================================

if not df_grt_expandido.empty:

    df_grt_expandido["fecha"] = pd.to_datetime(
        df_grt_expandido["fecha"],
        errors="coerce"
    )

    df_grt_expandido["monto"] = pd.to_numeric(
        df_grt_expandido["monto"],
        errors="coerce"
    ).fillna(0)

    df_grt_expandido["mes"] = (
        df_grt_expandido["fecha"].dt.to_period("M")
    )

    df_credito_recurrente_mes = (
        df_grt_expandido.groupby("mes")["monto"]
        .sum()
        .reset_index()
        .rename(columns={"monto": "Crédito recurrente"})
    )

else:
    df_credito_recurrente_mes = pd.DataFrame(
        columns=["mes", "Crédito recurrente"]
    )


# ==================================================
# BASE DE MESES
# ==================================================

meses_base = pd.DataFrame({
    "mes": pd.period_range(
        start=fecha_inicio_sim,
        end=fecha_fin_sim,
        freq="M"
    )
})


# ==================================================
# MERGE FINAL
# ==================================================

df_mes_tipo = (
    meses_base
    .merge(df_debito_diario_mes, on="mes", how="left")
    .merge(df_fijos_mes, on="mes", how="left")
    .merge(df_credito_diario_mes, on="mes", how="left")
    .merge(df_credito_recurrente_mes, on="mes", how="left")
    .fillna(0)
)

for col in [
    "Débito diario",
    "Gastos fijos débito",
    "Crédito diario",
    "Crédito recurrente"
]:
    if col not in df_mes_tipo.columns:
        df_mes_tipo[col] = 0

df_mes_tipo["Mes"] = df_mes_tipo["mes"].apply(
    lambda m: f"{MESES_ES[m.month]} {m.year}"
)

# Débito total mensual
df_mes_tipo["Gastos débito total mensual"] = (
    df_mes_tipo["Débito diario"] +
    df_mes_tipo["Gastos fijos débito"]
)

# Crédito total mensual
df_mes_tipo["Gastos crédito total mensual"] = (
    df_mes_tipo["Crédito diario"] +
    df_mes_tipo["Crédito recurrente"]
)

# Fijos mensuales: todo lo recurrente/fijo, sea débito o crédito
df_mes_tipo["Gastos fijos mensuales"] = (
    df_mes_tipo["Gastos fijos débito"] +
    df_mes_tipo["Crédito recurrente"]
)

# No fijos mensuales: solo gastos puntuales/diarios
df_mes_tipo["Gastos no fijos mensuales"] = (
    df_mes_tipo["Débito diario"] +
    df_mes_tipo["Crédito diario"]
)

df_mes_tipo["Total general"] = (
    df_mes_tipo["Gastos fijos mensuales"] +
    df_mes_tipo["Gastos no fijos mensuales"]
)


# 5. Gráficos separados
if df_mes_tipo["Total general"].sum() > 0:

    x = range(len(df_mes_tipo))
    ancho = 0.35

    # ==================================================
    # GRÁFICO 1: DÉBITO VS CRÉDITO
    # ==================================================
    st.subheader("💳 Gastos débito vs crédito")

    fig_dc, ax_dc = plt.subplots(figsize=(16, 6))

    ax_dc.bar(
        [i - ancho / 2 for i in x],
        df_mes_tipo["Gastos débito total mensual"],
        width=ancho,
        label="Gastos débito total mensual"
    )

    ax_dc.bar(
        [i + ancho / 2 for i in x],
        df_mes_tipo["Gastos crédito total mensual"],
        width=ancho,
        label="Gastos crédito total mensual"
    )

    ax_dc.set_xticks(list(x))
    ax_dc.set_xticklabels(
        df_mes_tipo["Mes"],
        rotation=35,
        ha="right",
        fontsize=12
    )

    ax_dc.set_ylabel("Monto mensual (S/)", fontsize=13)
    ax_dc.set_title("Gastos mensuales: débito vs crédito", fontsize=16, pad=18)
    ax_dc.tick_params(axis="y", labelsize=12)
    ax_dc.grid(axis="y", linestyle="--", alpha=0.25)
    ax_dc.legend(fontsize=11)

    max_val_dc = max(
        df_mes_tipo["Gastos débito total mensual"].max(),
        df_mes_tipo["Gastos crédito total mensual"].max()
    )

    for i, row in df_mes_tipo.iterrows():
        valores = [
            (i - ancho / 2, row["Gastos débito total mensual"]),
            (i + ancho / 2, row["Gastos crédito total mensual"]),
        ]

        for xpos, valor in valores:
            if valor > 0:
                ax_dc.text(
                    xpos,
                    valor + max_val_dc * 0.02,
                    f"S/ {valor:,.0f}",
                    ha="center",
                    va="bottom",
                    fontsize=9,
                    rotation=90
                )

    plt.tight_layout()
    st.pyplot(fig_dc, use_container_width=True)

    # ==================================================
    # GRÁFICO 2: FIJOS VS NO FIJOS
    # ==================================================
    st.subheader("📌 Gastos fijos vs no fijos")

    fig_fnf, ax_fnf = plt.subplots(figsize=(16, 6))

    ax_fnf.bar(
        [i - ancho / 2 for i in x],
        df_mes_tipo["Gastos fijos mensuales"],
        width=ancho,
        label="Gastos fijos mensuales"
    )

    ax_fnf.bar(
        [i + ancho / 2 for i in x],
        df_mes_tipo["Gastos no fijos mensuales"],
        width=ancho,
        label="Gastos no fijos mensuales"
    )

    ax_fnf.set_xticks(list(x))
    ax_fnf.set_xticklabels(
        df_mes_tipo["Mes"],
        rotation=35,
        ha="right",
        fontsize=12
    )

    ax_fnf.set_ylabel("Monto mensual (S/)", fontsize=13)
    ax_fnf.set_title("Gastos mensuales: fijos vs no fijos", fontsize=16, pad=18)
    ax_fnf.tick_params(axis="y", labelsize=12)
    ax_fnf.grid(axis="y", linestyle="--", alpha=0.25)
    ax_fnf.legend(fontsize=11)

    max_val_fnf = max(
        df_mes_tipo["Gastos fijos mensuales"].max(),
        df_mes_tipo["Gastos no fijos mensuales"].max()
    )

    for i, row in df_mes_tipo.iterrows():
        valores = [
            (i - ancho / 2, row["Gastos fijos mensuales"]),
            (i + ancho / 2, row["Gastos no fijos mensuales"]),
        ]

        for xpos, valor in valores:
            if valor > 0:
                ax_fnf.text(
                    xpos,
                    valor + max_val_fnf * 0.02,
                    f"S/ {valor:,.0f}",
                    ha="center",
                    va="bottom",
                    fontsize=9,
                    rotation=90
                )

    plt.tight_layout()
    st.pyplot(fig_fnf, use_container_width=True)

    st.dataframe(
        df_mes_tipo[
            [
                "Mes",
                "Gastos débito total mensual",
                "Gastos crédito total mensual",
                "Gastos fijos mensuales",
                "Gastos no fijos mensuales",
                "Total general"
            ]
        ],
        use_container_width=True,
        hide_index=True
    )

else:
    st.info("No hay gastos registrados para mostrar.")