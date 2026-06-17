import streamlit as st
from zoneinfo import ZoneInfo
from supabase import create_client
import pandas as pd
import matplotlib.pyplot as plt
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
from datetime import date, timedelta
from pathlib import Path
import uuid
import requests

def _parse_float_tc(value):
    """Convierte valores numéricos de tipo de cambio aunque vengan como texto con coma decimal."""
    try:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None
        return float(str(value).strip().replace(",", "."))
    except Exception:
        return None


def leer_ultimo_tipo_cambio(path, nombre_fuente):
    """
    Lee el último tipo de cambio desde un CSV generado por Airflow.

    Soporta archivos con estas estructuras:
    - usd_pen
    - tipo_cambio
    - promedio
    - compra y venta
    """
    p = Path(path)
    if not p.exists():
        return None

    try:
        df = pd.read_csv(p)

        if df.empty:
            return None

        df.columns = [str(c).strip().lower() for c in df.columns]

        if "fecha" in df.columns:
            df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce")
            df = df.dropna(subset=["fecha"]).sort_values("fecha")

        if df.empty:
            return None

        latest = df.iloc[-1]
        tc = None

        if "usd_pen" in df.columns:
            tc = _parse_float_tc(latest.get("usd_pen"))

        elif "tipo_cambio" in df.columns:
            tc = _parse_float_tc(latest.get("tipo_cambio"))

        elif "promedio" in df.columns:
            tc = _parse_float_tc(latest.get("promedio"))

        elif "compra" in df.columns and "venta" in df.columns:
            compra = _parse_float_tc(latest.get("compra"))
            venta = _parse_float_tc(latest.get("venta"))

            if compra is not None and venta is not None:
                tc = (compra + venta) / 2

        if tc is None:
            return None

        fecha_val = None
        if "fecha" in df.columns and not pd.isna(latest.get("fecha")):
            fecha_val = latest["fecha"].date()

        return {
            "fecha": fecha_val,
            "usd_pen": float(tc),
            "fuente": nombre_fuente,
            "fuente_csv": str(latest.get("fuente", nombre_fuente)),
            "fecha_fuente": str(latest.get("fecha_fuente", "")),
            "updated_at_lima": str(latest.get("updated_at_lima", "")),
            "archivo": str(p),
        }

    except Exception:
        return None


def leer_tipo_cambio_usd_pen(path="data/exchange_rate_usd_pen.csv"):
    """
    Función de compatibilidad para código antiguo.
    Lee el archivo de tipo de cambio internacional.
    """
    return leer_ultimo_tipo_cambio(path, "API internacional")


def cargar_tipos_cambio_airflow():
    """Carga todos los tipos de cambio disponibles generados por Airflow."""
    archivos_tc = {
        "BCRP": "data/exchange_rate_bcrp.csv",
        "BCP": "data/exchange_rate_bcp.csv",
        "API internacional": "data/exchange_rate_usd_pen.csv",
    }

    fuentes = {}

    for nombre, ruta in archivos_tc.items():
        info = leer_ultimo_tipo_cambio(ruta, nombre)
        if info is not None:
            fuentes[nombre] = info

    return fuentes


def seleccionar_fuente_default_tc(fuentes_tc, preferida=None):
    """
    Selecciona una fuente por defecto.
    Si existe una fuente previamente elegida y está disponible, la mantiene.
    Si no, toma la fuente más reciente; ante empate prioriza BCRP, luego BCP y luego API internacional.
    """
    if not fuentes_tc:
        return None

    if preferida in fuentes_tc:
        return preferida

    prioridad = {
        "BCRP": 1,
        "BCP": 2,
        "API internacional": 3,
    }

    fecha_min = pd.Timestamp.min.date()

    ordenadas = sorted(
        fuentes_tc.items(),
        key=lambda x: (
            x[1]["fecha"] if x[1].get("fecha") is not None else fecha_min,
            -prioridad.get(x[0], 99),
        ),
        reverse=True,
    )

    return ordenadas[0][0]


def obtener_tipo_cambio_default_airflow(fuente_preferida=None):
    """Devuelve la información de TC seleccionada por defecto desde los CSVs de Airflow."""
    fuentes_tc = cargar_tipos_cambio_airflow()
    fuente_default = seleccionar_fuente_default_tc(fuentes_tc, fuente_preferida)

    if fuente_default is None:
        return None

    return fuentes_tc[fuente_default]



# ==================================================
# HELPERS AIRFLOW / IBKR
# ==================================================
IBKR_INSTRUMENTS_PATH = Path("data/ibkr_instruments.csv")
IBKR_MARKET_PRICES_PATH = Path("data/market_prices_portfolio.csv")
IBKR_MARKET_PRICES_HISTORY_PATH = Path("data/market_prices_portfolio_history.csv")

_DEFAULT_IBKR_INSTRUMENTS = [
    {
        "ticker": "VOO",
        "nombre": "Vanguard S&P 500 ETF",
        "tipo": "ETF",
        "moneda": "USD",
        "source_symbol": "VOO",
        "fuente_precio": "Yahoo Finance",
        "activo": True,
    },
    {
        "ticker": "SCCO",
        "nombre": "Southern Copper Corporation",
        "tipo": "Accion",
        "moneda": "USD",
        "source_symbol": "SCCO",
        "fuente_precio": "Yahoo Finance",
        "activo": True,
    },
    {
        "ticker": "GLD",
        "nombre": "SPDR Gold Shares",
        "tipo": "ETF",
        "moneda": "USD",
        "source_symbol": "GLD",
        "fuente_precio": "Yahoo Finance",
        "activo": True,
    },
    {
        "ticker": "CCOEY",
        "nombre": "Capcom Co. Ltd. ADR",
        "tipo": "Accion",
        "moneda": "USD",
        "source_symbol": "CCOEY",
        "fuente_precio": "Yahoo Finance",
        "activo": True,
    },
]


def _parse_bool_ibkr(value):
    """Interpreta valores booleanos típicos guardados en CSV."""
    return str(value).strip().upper() in ["TRUE", "1", "SI", "SÍ", "YES", "Y"]


def normalizar_catalogo_ibkr(df):
    """Normaliza el catálogo de instrumentos IBKR para que Airflow y Streamlit usen la misma estructura."""
    cols = ["ticker", "nombre", "tipo", "moneda", "source_symbol", "fuente_precio", "activo"]

    if df is None or df.empty:
        df = pd.DataFrame(_DEFAULT_IBKR_INSTRUMENTS)

    for col in cols:
        if col not in df.columns:
            if col == "moneda":
                df[col] = "USD"
            elif col == "fuente_precio":
                df[col] = "Yahoo Finance"
            elif col == "activo":
                df[col] = True
            elif col == "source_symbol":
                df[col] = df["ticker"] if "ticker" in df.columns else ""
            else:
                df[col] = ""

    df = df[cols].copy()
    df["ticker"] = df["ticker"].fillna("").astype(str).str.upper().str.strip()
    df["nombre"] = df["nombre"].fillna("").astype(str).str.strip()
    df["tipo"] = df["tipo"].fillna("Accion").astype(str).str.strip()
    df["moneda"] = df["moneda"].fillna("USD").astype(str).str.upper().str.strip()
    df["source_symbol"] = df["source_symbol"].fillna("").astype(str).str.strip()
    df["fuente_precio"] = df["fuente_precio"].fillna("Yahoo Finance").astype(str).str.strip()
    df["activo"] = df["activo"].apply(_parse_bool_ibkr)

    df.loc[df["source_symbol"] == "", "source_symbol"] = df.loc[df["source_symbol"] == "", "ticker"]
    df = df[df["ticker"] != ""].copy()
    df = df.drop_duplicates(subset=["ticker"], keep="last").sort_values("ticker").reset_index(drop=True)

    return df


def cargar_catalogo_ibkr(path=IBKR_INSTRUMENTS_PATH):
    """
    Lee el catálogo dinámico de instrumentos IBKR.
    Si el CSV no existe, devuelve un catálogo base y trata de crearlo localmente.
    """
    p = Path(path)

    try:
        if p.exists():
            df = pd.read_csv(p)
        else:
            df = pd.DataFrame(_DEFAULT_IBKR_INSTRUMENTS)
            p.parent.mkdir(parents=True, exist_ok=True)
            df.to_csv(p, index=False)

        return normalizar_catalogo_ibkr(df)

    except Exception:
        return normalizar_catalogo_ibkr(pd.DataFrame(_DEFAULT_IBKR_INSTRUMENTS))


def guardar_catalogo_ibkr(df, path=IBKR_INSTRUMENTS_PATH):
    """Guarda el catálogo de instrumentos para que Airflow lo lea en la siguiente corrida."""
    p = Path(path)
    df_save = normalizar_catalogo_ibkr(df)
    p.parent.mkdir(parents=True, exist_ok=True)
    df_save.to_csv(p, index=False)
    return df_save


def upsert_instrumento_ibkr(ticker, nombre="", tipo="Accion", moneda="USD", source_symbol="", fuente_precio="Yahoo Finance", activo=True):
    """
    Agrega o actualiza un instrumento en data/ibkr_instruments.csv.
    Esto permite comprar nuevos tickers sin modificar el DAG ni app.py.
    """
    ticker = str(ticker or "").upper().strip()
    if not ticker:
        return cargar_catalogo_ibkr()

    nombre = str(nombre or ticker).strip()
    tipo = str(tipo or "Accion").strip()
    moneda = str(moneda or "USD").upper().strip()
    source_symbol = str(source_symbol or ticker).strip()
    fuente_precio = str(fuente_precio or "Yahoo Finance").strip()

    df = cargar_catalogo_ibkr()
    df = df[df["ticker"] != ticker].copy()

    nueva_fila = pd.DataFrame([{
        "ticker": ticker,
        "nombre": nombre,
        "tipo": tipo,
        "moneda": moneda,
        "source_symbol": source_symbol,
        "fuente_precio": fuente_precio,
        "activo": bool(activo),
    }])

    df = pd.concat([df, nueva_fila], ignore_index=True)
    return guardar_catalogo_ibkr(df)


def cargar_precios_ibkr_airflow(path=IBKR_MARKET_PRICES_PATH):
    """
    Lee los últimos precios generados por el DAG market_prices_ibkr_portfolio.
    Devuelve una fila por ticker.
    """
    p = Path(path)

    if not p.exists():
        return pd.DataFrame()

    try:
        df = pd.read_csv(p)
        if df.empty:
            return pd.DataFrame()

        df.columns = [str(c).strip().lower() for c in df.columns]

        if "ticker" not in df.columns:
            return pd.DataFrame()

        df["ticker"] = df["ticker"].astype(str).str.upper().str.strip()

        if "fecha" in df.columns:
            df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce")

        if "updated_at_lima" in df.columns:
            df["_updated_dt"] = pd.to_datetime(df["updated_at_lima"], errors="coerce")
        else:
            df["_updated_dt"] = pd.NaT

        if "precio_actual_usd" not in df.columns:
            for alt_col in ["close", "last", "precio_usd"]:
                if alt_col in df.columns:
                    df["precio_actual_usd"] = df[alt_col]
                    break

        if "precio_actual_usd" not in df.columns:
            return pd.DataFrame()

        df["precio_actual_usd"] = pd.to_numeric(df["precio_actual_usd"], errors="coerce")
        df = df.dropna(subset=["ticker", "precio_actual_usd"])
        df = df[df["precio_actual_usd"] > 0].copy()

        if df.empty:
            return pd.DataFrame()

        sort_cols = [c for c in ["ticker", "fecha", "_updated_dt"] if c in df.columns]
        if sort_cols:
            df = df.sort_values(sort_cols)

        df = df.drop_duplicates(subset=["ticker"], keep="last").reset_index(drop=True)

        if "_updated_dt" in df.columns:
            df = df.drop(columns=["_updated_dt"])

        df["archivo"] = str(p)
        return df

    except Exception:
        return pd.DataFrame()


def obtener_nombre_instrumento_ibkr(ticker, catalogo_df=None):
    """Devuelve el nombre de un instrumento desde el catálogo; si no existe, devuelve el ticker."""
    ticker = str(ticker or "").upper().strip()
    if catalogo_df is None:
        catalogo_df = cargar_catalogo_ibkr()

    if not catalogo_df.empty and "ticker" in catalogo_df.columns:
        row = catalogo_df[catalogo_df["ticker"].astype(str).str.upper().str.strip() == ticker]
        if not row.empty:
            nombre = str(row.iloc[0].get("nombre", "")).strip()
            return nombre if nombre else ticker

    return ticker


def obtener_source_symbol_ibkr(ticker, catalogo_df=None):
    """Devuelve el símbolo que usa Yahoo Finance para consultar el precio."""
    ticker = str(ticker or "").upper().strip()
    if catalogo_df is None:
        catalogo_df = cargar_catalogo_ibkr()

    if not catalogo_df.empty and "ticker" in catalogo_df.columns:
        row = catalogo_df[catalogo_df["ticker"].astype(str).str.upper().str.strip() == ticker]
        if not row.empty:
            symbol = str(row.iloc[0].get("source_symbol", "")).strip()
            return symbol if symbol else ticker

    return ticker


def inferir_tipo_instrumento_ibkr(ticker, nombre=""):
    """Inferencia ligera para tickers nuevos. No afecta cálculos; solo ordena el catálogo."""
    ticker = str(ticker or "").upper().strip()
    nombre_u = str(nombre or "").upper()
    etfs_comunes = {
        "VOO", "QQQ", "QQQM", "SPY", "IVV", "VTI", "SCHD", "GLD",
        "SLV", "DIA", "IWM", "COPX", "XLK", "XLF", "XLE", "XLV"
    }

    if ticker in etfs_comunes or "ETF" in nombre_u or "TRUST" in nombre_u or "FUND" in nombre_u:
        return "ETF"

    if ticker.endswith("Y") and len(ticker) >= 5:
        return "ADR"

    return "Accion"


def sincronizar_catalogo_desde_compras_ibkr(compras, catalogo_df=None):
    """
    Asegura automáticamente que todo ticker comprado exista en data/ibkr_instruments.csv.
    Así una compra nueva queda lista para que Airflow la tome en la siguiente corrida,
    sin editar manualmente el catálogo.
    """
    if compras is None:
        return cargar_catalogo_ibkr(), []

    df_compras = pd.DataFrame(compras)
    if df_compras.empty or "ticker" not in df_compras.columns:
        return cargar_catalogo_ibkr(), []

    if catalogo_df is None or catalogo_df.empty:
        catalogo_df = cargar_catalogo_ibkr()

    catalogo_df = normalizar_catalogo_ibkr(catalogo_df)
    tickers_catalogo = set(catalogo_df["ticker"].astype(str).str.upper().str.strip())
    agregados = []

    df_compras["ticker"] = df_compras["ticker"].fillna("").astype(str).str.upper().str.strip()
    df_compras = df_compras[df_compras["ticker"] != ""].copy()

    for ticker in sorted(df_compras["ticker"].unique()):
        if ticker in tickers_catalogo:
            continue

        fila = df_compras[df_compras["ticker"] == ticker].iloc[-1]
        nombre = str(fila.get("nombre", "")).strip()
        if nombre in ["", "None", "nan"]:
            nombre = ticker

        tipo = inferir_tipo_instrumento_ibkr(ticker, nombre)
        moneda = str(fila.get("moneda", "USD") or "USD").upper().strip()

        catalogo_df = upsert_instrumento_ibkr(
            ticker=ticker,
            nombre=nombre,
            tipo=tipo,
            moneda=moneda,
            source_symbol=ticker,
            fuente_precio="Yahoo Finance",
            activo=True,
        )
        tickers_catalogo.add(ticker)
        agregados.append(ticker)

    return cargar_catalogo_ibkr(), agregados


@st.cache_data(ttl=900, show_spinner=False)
def consultar_precio_yahoo_ibkr(source_symbol):
    """Consulta Yahoo Finance directamente desde Streamlit como fallback cuando Airflow aún no tiene el ticker."""
    source_symbol = str(source_symbol or "").strip()
    if not source_symbol:
        return None

    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{source_symbol}"
        response = requests.get(
            url,
            params={"range": "5d", "interval": "1d"},
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        response.raise_for_status()
        data = response.json()

        result = data.get("chart", {}).get("result", [])
        if not result:
            return None

        result0 = result[0]
        meta = result0.get("meta", {})
        indicators = result0.get("indicators", {})
        quotes = indicators.get("quote", [])

        precio = _parse_float_tc(meta.get("regularMarketPrice"))
        if precio is None and quotes:
            closes = quotes[0].get("close", [])
            closes_validos = [c for c in closes if c is not None]
            if closes_validos:
                precio = _parse_float_tc(closes_validos[-1])

        if precio is None or precio <= 0:
            return None

        market_time = meta.get("regularMarketTime")
        if market_time:
            dt_lima = pd.to_datetime(int(market_time), unit="s", utc=True).tz_convert("America/Lima")
        else:
            timestamps = result0.get("timestamp", [])
            if timestamps:
                dt_lima = pd.to_datetime(int(timestamps[-1]), unit="s", utc=True).tz_convert("America/Lima")
            else:
                dt_lima = pd.Timestamp.now(tz=ZoneInfo("America/Lima"))

        return {
            "precio_actual_usd": float(precio),
            "fecha_precio": dt_lima.date().isoformat(),
            "hora_precio": dt_lima.strftime("%H:%M:%S"),
            "moneda_precio": meta.get("currency", "USD"),
            "exchange": meta.get("exchangeName", ""),
        }

    except Exception:
        return None


def completar_precios_faltantes_con_yahoo(df_precios, tickers_comprados, catalogo_df):
    """
    Si Airflow todavía no trajo un ticker nuevo, la app intenta consultar Yahoo Finance
    en vivo y usa ese precio como fallback visual. Airflow sigue siendo la fuente primaria.
    """
    if tickers_comprados is None:
        return df_precios, []

    tickers = sorted({str(t or "").upper().strip() for t in tickers_comprados if str(t or "").strip()})
    if not tickers:
        return df_precios, []

    if df_precios is None or df_precios.empty:
        df_base = pd.DataFrame()
        tickers_con_precio = set()
    else:
        df_base = df_precios.copy()
        df_base["ticker"] = df_base["ticker"].astype(str).str.upper().str.strip()
        tickers_con_precio = set(df_base["ticker"].dropna().astype(str))

    if catalogo_df is None or catalogo_df.empty:
        catalogo_df = cargar_catalogo_ibkr()

    catalogo_df = normalizar_catalogo_ibkr(catalogo_df)
    filas_fallback = []
    tickers_fallback = []
    now_lima = pd.Timestamp.now(tz=ZoneInfo("America/Lima")).strftime("%Y-%m-%d %H:%M:%S")

    for ticker in tickers:
        if ticker in tickers_con_precio:
            continue

        match = catalogo_df[catalogo_df["ticker"].astype(str).str.upper().str.strip() == ticker]
        if match.empty:
            nombre = ticker
            tipo = inferir_tipo_instrumento_ibkr(ticker, nombre)
            moneda = "USD"
            source_symbol = ticker
        else:
            row = match.iloc[0]
            nombre = str(row.get("nombre", ticker)).strip() or ticker
            tipo = str(row.get("tipo", inferir_tipo_instrumento_ibkr(ticker, nombre))).strip()
            moneda = str(row.get("moneda", "USD")).upper().strip()
            source_symbol = str(row.get("source_symbol", ticker)).strip() or ticker

        info = consultar_precio_yahoo_ibkr(source_symbol)
        if info is None:
            continue

        filas_fallback.append({
            "fecha": pd.Timestamp.now(tz=ZoneInfo("America/Lima")).date().isoformat(),
            "ticker": ticker,
            "nombre": nombre,
            "tipo": tipo,
            "moneda": moneda,
            "source_symbol": source_symbol,
            "precio_actual_usd": info["precio_actual_usd"],
            "fecha_precio": info["fecha_precio"],
            "hora_precio": info["hora_precio"],
            "moneda_precio": info["moneda_precio"],
            "exchange": info["exchange"],
            "fuente_precio": "Yahoo Finance (fallback app)",
            "updated_at_lima": now_lima,
            "archivo": "consulta directa desde app.py",
        })
        tickers_fallback.append(ticker)

    if filas_fallback:
        df_fallback = pd.DataFrame(filas_fallback)
        if df_base.empty:
            df_base = df_fallback
        else:
            df_base = pd.concat([df_base, df_fallback], ignore_index=True)

    return df_base, tickers_fallback



def calcular_total_transferencias_ibkr_usd():
    """Suma el cash USD generado por transferencias desde cuentas locales hacia IBKR."""
    try:
        df = pd.DataFrame(st.session_state.get("ibkr_transferencias", []))
        if df.empty or "monto_usd" not in df.columns:
            return 0.0
        df["monto_usd"] = pd.to_numeric(df["monto_usd"], errors="coerce").fillna(0.0)
        return float(df["monto_usd"].sum())
    except Exception:
        return 0.0


def calcular_total_cash_manual_ibkr_usd():
    """Suma movimientos manuales de cash IBKR registrados en la sección de portafolio."""
    try:
        df = pd.DataFrame(st.session_state.get("ibkr_cash_movimientos", []))
        if df.empty or "monto_usd" not in df.columns:
            return 0.0
        df["monto_usd"] = pd.to_numeric(df["monto_usd"], errors="coerce").fillna(0.0)
        return float(df["monto_usd"].sum())
    except Exception:
        return 0.0


def calcular_total_cash_ibkr_usd():
    """Cash total disponible en IBKR: transferencias a IBKR + movimientos manuales de cash."""
    return float(calcular_total_cash_manual_ibkr_usd() + calcular_total_transferencias_ibkr_usd())


def calcular_total_debitado_transferencia_ibkr(row):
    """Monto que sale de la cuenta local en soles, incluyendo comisión."""
    try:
        total = pd.to_numeric(row.get("total_debitado_pen", None), errors="coerce")
        if pd.notna(total):
            return float(total)
    except Exception:
        pass

    try:
        monto_pen = float(row.get("monto_pen", 0.0) or 0.0)
        comision_pen = float(row.get("comision_pen", 0.0) or 0.0)
        return float(monto_pen + comision_pen)
    except Exception:
        return 0.0


def calcular_resumen_ibkr_global(tc_usd_pen=None, usar_fallback_yahoo=True):
    """
    Calcula el valor total actual del portafolio IBKR para integrarlo con los saldos generales.

    Incluye:
    - valor actual de acciones/ETFs comprados,
    - cash IBKR disponible,
    - conversión a soles con el TC configurado.

    No modifica las compras; solo sincroniza catálogo si detecta tickers nuevos para mantener
    consistencia con Airflow y con el fallback de Yahoo Finance.
    """
    try:
        tc = float(tc_usd_pen if tc_usd_pen is not None else 3.85)
    except Exception:
        tc = 3.85

    resultado = {
        "activos_usd": 0.0,
        "cash_usd": 0.0,
        "total_usd": 0.0,
        "total_pen": 0.0,
        "tickers": [],
        "tickers_sin_precio": [],
        "fuente": "Sin posiciones",
        "hay_datos": False,
    }

    # Cash disponible IBKR
    # Incluye movimientos manuales de cash + transferencias desde cuentas locales hacia IBKR.
    resultado["cash_manual_usd"] = calcular_total_cash_manual_ibkr_usd()
    resultado["cash_transferencias_usd"] = calcular_total_transferencias_ibkr_usd()
    resultado["cash_usd"] = calcular_total_cash_ibkr_usd()

    # Posiciones en acciones / ETFs
    df_inv = pd.DataFrame(st.session_state.get("inversiones_ibkr", []))
    if not df_inv.empty:
        for col in ["ticker", "cantidad", "monto_invertido_usd"]:
            if col not in df_inv.columns:
                df_inv[col] = 0.0 if col != "ticker" else ""

        df_inv["ticker"] = df_inv["ticker"].fillna("").astype(str).str.upper().str.strip()
        df_inv["cantidad"] = pd.to_numeric(df_inv["cantidad"], errors="coerce").fillna(0.0)
        df_inv["monto_invertido_usd"] = pd.to_numeric(df_inv["monto_invertido_usd"], errors="coerce").fillna(0.0)
        df_inv = df_inv[(df_inv["ticker"] != "") & (df_inv["cantidad"] > 0)].copy()

    if df_inv.empty:
        resultado["hay_datos"] = abs(resultado["cash_usd"]) > 0
        resultado["total_usd"] = float(resultado["cash_usd"])
        resultado["total_pen"] = float(resultado["total_usd"] * tc)
        resultado["fuente"] = "Cash IBKR" if resultado["hay_datos"] else "Sin posiciones"
        return resultado

    try:
        # Asegura que todo ticker comprado exista en el catálogo para Airflow / Yahoo fallback.
        catalogo_df, _ = sincronizar_catalogo_desde_compras_ibkr(
            st.session_state.get("inversiones_ibkr", [])
        )
    except Exception:
        catalogo_df = cargar_catalogo_ibkr()

    tickers = sorted(df_inv["ticker"].unique().tolist())
    resultado["tickers"] = tickers

    df_precios = cargar_precios_ibkr_airflow()
    fuente = "Airflow"
    if usar_fallback_yahoo:
        df_precios, tickers_fallback = completar_precios_faltantes_con_yahoo(
            df_precios,
            tickers,
            catalogo_df,
        )
        if tickers_fallback:
            fuente = "Airflow + Yahoo fallback"

    df_pos = (
        df_inv.groupby("ticker", as_index=False)
        .agg(cantidad_total=("cantidad", "sum"), invertido_total_usd=("monto_invertido_usd", "sum"))
    )

    if df_precios is None or df_precios.empty:
        df_pos["precio_actual_usd"] = pd.NA
    else:
        df_precios = df_precios.copy()
        df_precios["ticker"] = df_precios["ticker"].astype(str).str.upper().str.strip()
        if "precio_actual_usd" not in df_precios.columns:
            df_precios["precio_actual_usd"] = pd.NA
        df_precios["precio_actual_usd"] = pd.to_numeric(df_precios["precio_actual_usd"], errors="coerce")
        df_precios = df_precios.dropna(subset=["ticker", "precio_actual_usd"])
        df_precios = df_precios[df_precios["precio_actual_usd"] > 0].copy()
        df_precios = df_precios.drop_duplicates(subset=["ticker"], keep="last")
        df_pos = df_pos.merge(df_precios[["ticker", "precio_actual_usd"]], on="ticker", how="left")

    df_pos["precio_actual_usd"] = pd.to_numeric(df_pos["precio_actual_usd"], errors="coerce")
    df_pos["tiene_precio"] = df_pos["precio_actual_usd"].notna() & (df_pos["precio_actual_usd"] > 0)
    df_pos["valor_actual_usd"] = df_pos["cantidad_total"] * df_pos["precio_actual_usd"].fillna(0.0)

    resultado["activos_usd"] = float(df_pos.loc[df_pos["tiene_precio"], "valor_actual_usd"].sum())
    resultado["tickers_sin_precio"] = df_pos.loc[~df_pos["tiene_precio"], "ticker"].tolist()
    resultado["total_usd"] = float(resultado["activos_usd"] + resultado["cash_usd"])
    resultado["total_pen"] = float(resultado["total_usd"] * tc)
    resultado["hay_datos"] = True
    resultado["fuente"] = fuente if resultado["activos_usd"] > 0 else "Cash IBKR"

    return resultado


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
# LOGIN SUPABASE — pantalla completa, desaparece al entrar
# ==================================================
if "user" not in st.session_state:
    st.markdown(
        "<h1 style='text-align:center;margin-top:80px'>📊 Finanzas Personales</h1>"
        "<p style='text-align:center;color:gray;margin-bottom:40px'>Inicia sesión para continuar</p>",
        unsafe_allow_html=True
    )
    _lc, _lm, _rc = st.columns([1, 2, 1])
    with _lm:
        with st.container(border=True):
            _modo = st.radio("", ["Iniciar sesión", "Crear cuenta"], horizontal=True, label_visibility="collapsed")
            _email    = st.text_input("📧 Email", placeholder="tu@email.com")
            _password = st.text_input("🔑 Contraseña", type="password", placeholder="••••••••")
            st.write("")
            if _modo == "Crear cuenta":
                if st.button("Crear cuenta", use_container_width=True, type="primary"):
                    try:
                        supabase.auth.sign_up({"email": _email, "password": _password})
                        st.success("✅ Cuenta creada. Ahora inicia sesión.")
                    except Exception as _e:
                        st.error(f"Error: {_e}")
            else:
                if st.button("Ingresar →", use_container_width=True, type="primary"):
                    try:
                        _res = supabase.auth.sign_in_with_password({"email": _email, "password": _password})
                        st.session_state["user"]          = _res.user
                        st.session_state["access_token"]  = _res.session.access_token
                        st.session_state["refresh_token"] = _res.session.refresh_token
                        st.rerun()
                    except Exception:
                        st.error("❌ Usuario o contraseña incorrectos")
    st.stop()

try:
    supabase.auth.set_session(
        st.session_state["access_token"],
        st.session_state["refresh_token"]
    )
except Exception:
    # Sesión expirada — limpiar y pedir login de nuevo
    for _k in ["user", "access_token", "refresh_token"]:
        st.session_state.pop(_k, None)
    st.warning("⏳ Tu sesión expiró. Por favor vuelve a iniciar sesión.")
    st.rerun()

user_id = st.session_state["user"].id

# Sidebar minimalista: solo usuario y cerrar sesión
with st.sidebar:
    st.caption(f"👤 {st.session_state['user'].email}")
    if st.button("🚪 Cerrar sesión", use_container_width=True):
        for _k in ["user", "access_token", "refresh_token"]:
            st.session_state.pop(_k, None)
        st.rerun()

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
"gastos_reembolsables": [],
"simulaciones_prestamo": [],
"inversiones_ibkr": [],
"ibkr_cash_movimientos": [],
"ibkr_transferencias": [],
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
    "gastos_reembolsables",
    "simulaciones_prestamo",
    "inversiones_ibkr",
    "ibkr_cash_movimientos",
    "ibkr_transferencias",
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
        _fuentes_tc_airflow = cargar_tipos_cambio_airflow()

        if _fuentes_tc_airflow:
            _fuente_default_tc = seleccionar_fuente_default_tc(
                _fuentes_tc_airflow,
                conf.get("fuente_tipo_cambio_default")
            )
            _opciones_tc = list(_fuentes_tc_airflow.keys())
            _fuente_tc_cfg = st.selectbox(
                "Fuente TC Airflow",
                _opciones_tc,
                index=_opciones_tc.index(_fuente_default_tc),
                key="fuente_tipo_cambio_default_cfg",
                help="Selecciona qué archivo generado por Airflow usará la app como TC por defecto."
            )

            _tc_airflow = _fuentes_tc_airflow[_fuente_tc_cfg]
            st.metric(
                f"💱 TC USD → PEN ({_fuente_tc_cfg})",
                f"S/ {_tc_airflow['usd_pen']:.4f}",
                help=(
                    f"Archivo: {_tc_airflow['archivo']} | "
                    f"Fuente CSV: {_tc_airflow['fuente_csv']} | "
                    f"Fecha: {_tc_airflow['fecha']} | "
                    f"Actualizado: {_tc_airflow['updated_at_lima']}"
                )
            )
            _tc_val_default = _tc_airflow["usd_pen"]
            _tc_widget_key = f"tipo_cambio_default_input_{_fuente_tc_cfg}_{_tc_airflow['fecha']}"
        else:
            _fuente_tc_cfg = "Manual"
            _tc_val_default = float(conf.get("tipo_cambio_default", 3.85))
            _tc_widget_key = "tipo_cambio_default_input_manual"
            st.warning("No se encontraron CSVs de tipo de cambio generados por Airflow.")

        tipo_cambio_default = st.number_input(
            "TC USD → PEN (defecto/manual)",
            min_value=1.0, step=0.01,
            value=round(float(_tc_val_default), 4),
            format="%.4f",
            key=_tc_widget_key,
            help="Se auto-rellena desde Airflow si hay datos. Puedes ajustarlo manualmente."
        )

    st.session_state["configuracion"] = {
        "fecha_inicio_sim": fecha_inicio_sim.isoformat(),
        "fecha_fin_sim": fecha_fin_sim.isoformat(),
        "ahorro_inicial": ahorro_inicial,
        "nombre_cuenta_principal": nombre_cuenta_principal,
        "tipo_cambio_default": tipo_cambio_default,
        "fuente_tipo_cambio_default": _fuente_tc_cfg
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

# TC global de trabajo para cálculos que ocurren antes del bloque de simulación.
# Sale de la configuración guardada arriba, que a su vez se auto-rellena desde Airflow.
_tc_default = float(st.session_state["configuracion"].get("tipo_cambio_default", 3.85))

# ==================================================
# 2. INGRESOS Y GASTOS RECURRENTES / FIJOS
# ==================================================
with st.expander("📌 2. Gastos e ingresos recurrentes / fijos", expanded=False):

    with st.expander("💰 Ingresos recurrentes", expanded=False):

        with st.form("form_ingreso_rec"):
            _ci1, _ci2 = st.columns(2)
            with _ci1:
                nombre   = st.text_input("📝 Nombre", "Sueldo")
                fecha_ini = st.date_input("📅 Fecha inicio", fecha_inicio_sim)
            with _ci2:
                monto = st.number_input("💰 Monto mensual (S/)", min_value=0.0, step=100.0)
                dia   = st.number_input("📆 Día de cobro", 1, 31, 25)
            if st.form_submit_button("➕ Agregar ingreso recurrente", use_container_width=True, type="primary"):
                st.session_state["ingresos_recurrentes"].append({
                    "nombre": nombre, "monto": monto,
                    "fecha_inicio": fecha_ini.isoformat(), "dia_cobro": dia
                })
                guardar("ingresos_recurrentes")
                st.rerun()

        df_ing_rec = pd.DataFrame(st.session_state["ingresos_recurrentes"])
        if not df_ing_rec.empty:
            df_ing_rec["fecha_inicio"] = pd.to_datetime(df_ing_rec["fecha_inicio"], errors="coerce").dt.date
            df_ing_rec["monto"] = pd.to_numeric(df_ing_rec["monto"], errors="coerce").fillna(0)
            st.caption("✏️ Edita celdas · selecciona fila + **Delete** para borrar · luego **Guardar**")
            ed_ing_rec = st.data_editor(
                df_ing_rec, use_container_width=True, hide_index=True,
                num_rows="dynamic", height=min(38 * len(df_ing_rec) + 46, 300),
                column_config={
                    "nombre":       st.column_config.TextColumn("📝 Nombre", width="medium"),
                    "monto":        st.column_config.NumberColumn("💰 Monto (S/)", min_value=0.0, step=100.0, format="S/ %,.0f", width="small"),
                    "fecha_inicio": st.column_config.DateColumn("📅 Desde", width="small"),
                    "dia_cobro":    st.column_config.NumberColumn("📆 Día cobro", min_value=1, max_value=31, width="small"),
                }, key="editor_ingresos_recurrentes"
            )
            if st.button("💾 Guardar cambios — Ingresos recurrentes", type="primary"):
                df_ed = ed_ing_rec.copy()
                df_ed["fecha_inicio"] = pd.to_datetime(df_ed["fecha_inicio"], errors="coerce").dt.strftime("%Y-%m-%d")
                df_ed["monto"] = pd.to_numeric(df_ed["monto"], errors="coerce").fillna(0)
                df_ed["dia_cobro"] = pd.to_numeric(df_ed["dia_cobro"], errors="coerce").fillna(1).astype(int)
                df_ed["nombre"] = df_ed["nombre"].fillna("").astype(str)
                st.session_state["ingresos_recurrentes"] = df_ed.dropna(subset=["fecha_inicio"]).to_dict("records")
                guardar("ingresos_recurrentes")
                st.success("✅ Guardado.")
                st.rerun()
        else:
            st.info("No hay ingresos recurrentes registrados.")

    with st.expander("💰 Gastos recurrentes con débito", expanded=False):

        nombre_cuenta_principal = st.session_state["configuracion"].get("nombre_cuenta_principal", "Cuenta principal")
        cuentas_debito_map = {nombre_cuenta_principal: "principal"}
        for c in st.session_state["cuentas_ahorro"]:
            cuentas_debito_map[c["nombre"]] = c["id"]

        with st.form("form_gasto_fijo"):
            _cf1, _cf2 = st.columns(2)
            with _cf1:
                nombre             = st.text_input("📝 Nombre")
                fecha_ini          = st.date_input("📅 Fecha inicio", fecha_inicio_sim)
                cuenta_origen_nombre = st.selectbox("🏦 Cuenta de origen", list(cuentas_debito_map.keys()), key="cuenta_origen_gasto_fijo")
            with _cf2:
                monto = st.number_input("💰 Monto mensual (S/)", min_value=0.0, step=10.0)
                dia   = st.number_input("📆 Día de cobro", 1, 31, 5)
            if st.form_submit_button("➕ Agregar gasto fijo débito", use_container_width=True, type="primary"):
                st.session_state["gastos_fijos"].append({
                    "id": str(uuid.uuid4()), "nombre": nombre, "monto": float(monto),
                    "fecha_inicio": fecha_ini.isoformat(), "dia_cobro": int(dia),
                    "cuenta_origen": cuentas_debito_map[cuenta_origen_nombre],
                    "cuenta_origen_nombre": cuenta_origen_nombre
                })
                guardar("gastos_fijos")
                st.rerun()

        df_fijos = pd.DataFrame(st.session_state["gastos_fijos"])
        if not df_fijos.empty:
            df_fijos["fecha_inicio"] = pd.to_datetime(df_fijos["fecha_inicio"], errors="coerce").dt.date
            df_fijos["monto"] = pd.to_numeric(df_fijos["monto"], errors="coerce").fillna(0)
            st.caption("✏️ Edita celdas · selecciona fila + **Delete** para borrar · luego **Guardar**")
            ed_fijos = st.data_editor(
                df_fijos, use_container_width=True, hide_index=True,
                num_rows="dynamic", height=min(38 * len(df_fijos) + 46, 300),
                column_config={
                    "id":                   None,
                    "cuenta_origen":        None,
                    "nombre":               st.column_config.TextColumn("📝 Nombre", width="medium"),
                    "monto":                st.column_config.NumberColumn("💰 Monto (S/)", min_value=0.0, step=10.0, format="S/ %,.0f", width="small"),
                    "dia_cobro":            st.column_config.NumberColumn("📆 Día", min_value=1, max_value=31, width="small"),
                    "fecha_inicio":         st.column_config.DateColumn("📅 Desde", width="small"),
                    "cuenta_origen_nombre": st.column_config.TextColumn("🏦 Cuenta", disabled=True, width="small"),
                }, key="editor_gastos_fijos"
            )
            if st.button("💾 Guardar cambios — Gastos fijos débito", type="primary"):
                df_ed = ed_fijos.copy()
                _ncp = st.session_state["configuracion"].get("nombre_cuenta_principal", "Cuenta principal")
                def _san(x, d): return d if (x is None or (isinstance(x, float) and pd.isna(x)) or str(x) in ["", "None", "nan"]) else str(x)
                df_ed["id"]                   = df_ed["id"].apply(lambda x: _san(x, str(uuid.uuid4())) if "id" in df_ed.columns else str(uuid.uuid4()))
                df_ed["cuenta_origen"]        = df_ed.get("cuenta_origen", pd.Series(dtype=str)).apply(lambda x: _san(x, "principal"))
                df_ed["cuenta_origen_nombre"] = df_ed.get("cuenta_origen_nombre", pd.Series(dtype=str)).apply(lambda x: _san(x, _ncp))
                df_ed["monto"]    = pd.to_numeric(df_ed["monto"], errors="coerce").fillna(0.0)
                df_ed["dia_cobro"]= pd.to_numeric(df_ed["dia_cobro"], errors="coerce").fillna(1).astype(int)
                df_ed["fecha_inicio"] = pd.to_datetime(df_ed["fecha_inicio"], errors="coerce").dt.strftime("%Y-%m-%d")
                st.session_state["gastos_fijos"] = df_ed.dropna(subset=["fecha_inicio"]).to_dict("records")
                guardar("gastos_fijos")
                st.success("✅ Guardado.")
                st.rerun()
        else:
            st.info("No hay gastos fijos registrados.")

    with st.expander("💳 Gastos recurrentes con tarjeta de crédito", expanded=False):

        if not st.session_state["tarjetas"]:
            st.info("Primero agrega una tarjeta en la sección de Configuración.")
        else:
         mapa_tarjetas = {
            t["nombre"]: t["id"]
            for t in st.session_state["tarjetas"]
         }

        # ==================================================
        # GASTOS RECURRENTES CON TARJETA
        # ==================================================
        
        with st.form("form_gasto_recurrente_tarjeta"):
            _gr1, _gr2 = st.columns(2)
            with _gr1:
                nombre        = st.text_input("📝 Nombre", "Gimnasio")
                tarjeta_nombre = st.selectbox("💳 Tarjeta", list(mapa_tarjetas.keys()), key="tarjeta_gasto_recurrente")
                fecha_inicio  = st.date_input("📅 Fecha inicio", fecha_inicio_sim, key="fecha_inicio_gasto_recurrente_tarjeta")
                fecha_fin     = st.date_input("📅 Fecha fin", fecha_fin_sim, key="fecha_fin_gasto_recurrente_tarjeta")
            with _gr2:
                _cats_grt = sorted(st.session_state["categorias"]) if st.session_state["categorias"] else ["Sin categoría"]
                categoria  = st.selectbox("🏷️ Categoría", _cats_grt, key="categoria_gasto_rec_tarjeta")
                _mc2, _mm2 = st.columns([1, 2])
                with _mc2:
                    moneda_rec = st.selectbox("💱", ["PEN", "USD"], key="moneda_gasto_recurrente_tarjeta")
                with _mm2:
                    monto = st.number_input("💰 Monto mensual", min_value=0.0, step=10.0, key="monto_gasto_recurrente_tarjeta")
                dia_cargo = st.number_input("📆 Día de cargo", 1, 31, 15, key="dia_cargo_gasto_recurrente_tarjeta")
            if st.form_submit_button("➕ Agregar gasto recurrente tarjeta", use_container_width=True, type="primary"):
                st.session_state["gastos_recurrentes_tarjeta"].append({
                    "id": str(uuid.uuid4()), "nombre": nombre,
                    "tarjeta_id": mapa_tarjetas[tarjeta_nombre], "tarjeta_nombre": tarjeta_nombre,
                    "categoria": categoria, "moneda": moneda_rec, "monto": float(monto),
                    "dia_cargo": int(dia_cargo), "fecha_inicio": fecha_inicio.isoformat(), "fecha_fin": fecha_fin.isoformat()
                })
                guardar("gastos_recurrentes_tarjeta")
                st.rerun()

        df_grt = pd.DataFrame(st.session_state["gastos_recurrentes_tarjeta"])
        if not df_grt.empty:
            df_grt["fecha_inicio"] = pd.to_datetime(df_grt["fecha_inicio"], errors="coerce").dt.date
            df_grt["fecha_fin"]    = pd.to_datetime(df_grt["fecha_fin"],    errors="coerce").dt.date
            df_grt["monto"]        = pd.to_numeric(df_grt["monto"], errors="coerce").fillna(0)
            _cats_grt_ed = sorted(st.session_state["categorias"]) if st.session_state["categorias"] else ["Sin categoría"]
            _tars_ed     = [t["nombre"] for t in st.session_state["tarjetas"]]
            st.caption("✏️ Edita celdas · selecciona fila + **Delete** para borrar · luego **Guardar**")
            ed_grt = st.data_editor(
                df_grt, use_container_width=True, hide_index=True,
                num_rows="dynamic", height=min(38 * len(df_grt) + 46, 300),
                column_config={
                    "id":            None,
                    "tarjeta_id":    None,
                    "nombre":        st.column_config.TextColumn("📝 Nombre", width="medium"),
                    "tarjeta_nombre":st.column_config.SelectboxColumn("💳 Tarjeta", options=_tars_ed, width="small"),
                    "categoria":     st.column_config.SelectboxColumn("🏷️ Categoría", options=_cats_grt_ed, width="medium"),
                    "moneda":        st.column_config.SelectboxColumn("💱", options=["PEN", "USD"], width="small"),
                    "monto":         st.column_config.NumberColumn("💰 Monto (S/)", min_value=0.0, step=10.0, format="S/ %,.0f", width="small"),
                    "dia_cargo":     st.column_config.NumberColumn("📆 Día", min_value=1, max_value=31, width="small"),
                    "fecha_inicio":  st.column_config.DateColumn("📅 Desde", width="small"),
                    "fecha_fin":     st.column_config.DateColumn("📅 Hasta", width="small"),
                }, key="editor_gastos_recurrentes_tarjeta"
            )
            if st.button("💾 Guardar cambios — Gastos recurrentes tarjeta", type="primary"):
                df_ed = ed_grt.copy()
                _mapa_id = {t["nombre"]: t["id"] for t in st.session_state["tarjetas"]}
                df_ed["tarjeta_id"]   = df_ed["tarjeta_nombre"].map(_mapa_id).fillna("")
                df_ed["fecha_inicio"] = pd.to_datetime(df_ed["fecha_inicio"], errors="coerce").dt.strftime("%Y-%m-%d")
                df_ed["fecha_fin"]    = pd.to_datetime(df_ed["fecha_fin"],    errors="coerce").dt.strftime("%Y-%m-%d")
                df_ed["monto"]        = pd.to_numeric(df_ed["monto"], errors="coerce").fillna(0.0)
                df_ed["dia_cargo"]    = pd.to_numeric(df_ed["dia_cargo"], errors="coerce").fillna(1).astype(int)
                for _c in ["id"]:
                    if _c in df_ed.columns:
                        df_ed[_c] = df_ed[_c].apply(lambda x: str(uuid.uuid4()) if (x is None or str(x) in ["", "None", "nan"]) else str(x))
                    else:
                        df_ed[_c] = [str(uuid.uuid4()) for _ in range(len(df_ed))]
                st.session_state["gastos_recurrentes_tarjeta"] = df_ed.dropna(subset=["fecha_inicio"]).to_dict("records")
                guardar("gastos_recurrentes_tarjeta")
                st.success("✅ Guardado.")
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
    with st.expander("💳 3.1a Gastos diarios débito", expanded=False):

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


        # ── Gestionar categorías ─────────────────────────────────
        with st.popover("🏷️ Agregar / eliminar categoría", use_container_width=False):
            st.markdown("**Categorías guardadas**")
            _cats = sorted(st.session_state["categorias"])
            for _c in _cats:
                _col_c, _col_del = st.columns([4, 1])
                _col_c.write(_c)
                if _col_del.button("🗑️", key=f"del_cat_{_c}", help=f"Eliminar {_c}"):
                    st.session_state["categorias"] = [x for x in st.session_state["categorias"] if x != _c]
                    guardar("categorias")
                    st.rerun()
            st.divider()
            _nueva_cat_input = st.text_input("➕ Nueva categoría", placeholder="ej: Educación", key="popover_nueva_cat")
            if st.button("Guardar categoría", key="popover_save_cat", type="primary"):
                _nc = _nueva_cat_input.strip()
                if not _nc:
                    st.warning("Escribe un nombre.")
                elif _nc in st.session_state["categorias"]:
                    st.info(f'"{_nc}" ya existe.')
                else:
                    st.session_state["categorias"].append(_nc)
                    st.session_state["categorias"] = sorted(list(set(st.session_state["categorias"])))
                    guardar("categorias")
                    st.success(f'✅ "{_nc}" guardada.')
                    st.rerun()

        with st.form("form_gasto_diario", clear_on_submit=True):

            _col_izq, _col_der = st.columns(2)

            with _col_izq:
                fecha = st.date_input(
                    "📅 Fecha",
                    value=hoy_peru,
                    key="fecha_gasto_diario_debito"
                )
                cuenta_origen_nombre = st.selectbox(
                    "🏦 Cuenta",
                    list(cuentas_debito_map.keys()),
                    key="cuenta_origen_gasto_diario"
                )

            with _col_der:
                categoria = st.selectbox(
                    "🏷️ Categoría",
                    sorted(st.session_state["categorias"]) if st.session_state["categorias"] else ["Sin categoría"],
                    key="categoria_gasto_diario_debito"
                )
                descripcion = st.text_input("📝 Descripción")
                monto = st.number_input(
                    "💰 Monto (S/)",
                    min_value=0.0,
                    step=1.0,
                    key="monto_gasto_diario_debito"
                )

            submitted = st.form_submit_button("➕ Agregar gasto débito", use_container_width=True, type="primary")

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
            df_g["cuenta_origen_nombre"] = df_g["cuenta_origen_nombre"].fillna(nombre_cuenta_principal)
            df_g["fecha"] = pd.to_datetime(df_g["fecha"], errors="coerce")
            df_g["monto"] = pd.to_numeric(df_g["monto"], errors="coerce").fillna(0)
            df_g = df_g.sort_values(by="fecha", ascending=False).reset_index(drop=True)
            df_g["fecha"] = df_g["fecha"].dt.date

            _cats_debito = sorted(st.session_state["categorias"]) if st.session_state["categorias"] else ["Sin categoría"]

            st.caption("✏️ Edita celdas · selecciona fila + **Delete** para borrar · luego **Guardar**")

            ed_g = st.data_editor(
                df_g,
                use_container_width=True,
                hide_index=True,
                num_rows="dynamic",
                height=min(38 * len(df_g) + 46, 320),
                column_config={
                    "id":                   None,
                    "cuenta_origen":        None,
                    "fecha":                st.column_config.DateColumn("📅 Fecha", required=True, width="small"),
                    "cuenta_origen_nombre": st.column_config.TextColumn("🏦 Cuenta", disabled=True, width="small"),
                    "categoria":            st.column_config.SelectboxColumn("🏷️ Categoría", options=_cats_debito, required=True, width="medium"),
                    "descripcion":          st.column_config.TextColumn("📝 Descripción", width="large"),
                    "monto":                st.column_config.NumberColumn("💰 Monto (S/)", min_value=0.0, step=0.1, required=True, format="S/ %,.1f", width="small"),
                },
                key="editor_gastos_debito"
            )

            if st.button("💾 Guardar cambios — Gastos débito", type="primary"):
                df_editado = ed_g.copy()
                # Restaurar columnas ocultas que el editor pudo haber perdido
                for _col in ["id", "cuenta_origen"]:
                    if _col not in df_editado.columns:
                        df_editado[_col] = df_g[_col].values[:len(df_editado)] if _col in df_g.columns else ""
                # Asegurar IDs únicos para filas nuevas
                df_editado["id"] = df_editado["id"].apply(
                    lambda x: str(uuid.uuid4()) if (x is None or str(x) in ["", "None", "nan"]) else str(x)
                )
                df_editado["cuenta_origen"] = df_editado["cuenta_origen"].fillna("principal")
                df_editado["descripcion"]   = df_editado["descripcion"].fillna("").astype(str)
                df_editado["categoria"]     = df_editado["categoria"].fillna("Sin categoría").astype(str)
                df_editado["monto"]         = pd.to_numeric(df_editado["monto"], errors="coerce").fillna(0.0)
                df_editado["fecha"]         = pd.to_datetime(df_editado["fecha"], errors="coerce").dt.strftime("%Y-%m-%d")
                df_editado = df_editado.dropna(subset=["fecha"]).sort_values("fecha", ascending=False)
                st.session_state["gastos_diarios"] = df_editado.to_dict("records")
                guardar("gastos_diarios")
                st.success("✅ Guardado.")
                st.rerun()

        else:
            st.info("No hay gastos débito registrados.")

    with st.expander("💳 3.1b Gastos diarios con tarjeta de crédito", expanded=False):

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

                _col_izq_t, _col_der_t = st.columns(2)

                with _col_izq_t:
                    fecha = st.date_input(
                        "📅 Fecha",
                        value=hoy_peru,
                        key="fecha_gasto_tarjeta"
                    )
                    tarjeta_nombre = st.selectbox(
                        "💳 Tarjeta",
                        list(mapa_tarjetas.keys()),
                        key="tarjeta_gasto_diario"
                    )

                with _col_der_t:
                    categoria = st.selectbox(
                        "🏷️ Categoría",
                        sorted(st.session_state["categorias"]) if st.session_state["categorias"] else ["Sin categoría"],
                        key="categoria_gasto_tarjeta"
                    )
                    descripcion = st.text_input(
                        "📝 Descripción",
                        key="descripcion_gasto_tarjeta"
                    )
                    _mc, _mm = st.columns([1, 2])
                    with _mc:
                        moneda_gt = st.selectbox(
                            "Moneda",
                            ["PEN", "USD"],
                            key="moneda_gasto_tarjeta",
                            help="USD se convierte al tipo de cambio del día de pago"
                        )
                    with _mm:
                        monto = st.number_input(
                            "💰 Monto",
                            min_value=0.0,
                            step=1.0,
                            key="monto_gasto_tarjeta"
                        )

                if st.form_submit_button("➕ Agregar gasto tarjeta", use_container_width=True, type="primary"):

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

                if "id" not in df_gt.columns:
                    df_gt["id"] = None
                df_gt["id"] = df_gt["id"].apply(
                    lambda x: str(uuid.uuid4()) if pd.isna(x) or x in ["", "None", None] else x
                )
                df_gt = df_gt.drop_duplicates(
                    subset=["fecha", "tarjeta_id", "tarjeta_nombre", "categoria", "descripcion", "monto"],
                    keep="first"
                )
                df_gt["fecha"] = pd.to_datetime(df_gt["fecha"], errors="coerce")
                df_gt["monto"] = pd.to_numeric(df_gt["monto"], errors="coerce").fillna(0)
                df_gt = df_gt.sort_values("fecha", ascending=False).reset_index(drop=True)
                df_gt["fecha"] = df_gt["fecha"].dt.date

                _cats_tarjeta = sorted(st.session_state["categorias"]) if st.session_state["categorias"] else ["Sin categoría"]
                _tarjetas_nombres = [t["nombre"] for t in st.session_state["tarjetas"]]

                st.caption("✏️ Edita celdas · selecciona fila + **Delete** para borrar · luego **Guardar**")

                ed_gt = st.data_editor(
                    df_gt,
                    use_container_width=True,
                    hide_index=True,
                    num_rows="dynamic",
                    height=min(38 * len(df_gt) + 46, 320),
                    column_config={
                        "id":             None,
                        "tarjeta_id":     None,
                        "fecha":          st.column_config.DateColumn("📅 Fecha", required=True, width="small"),
                        "tarjeta_nombre": st.column_config.SelectboxColumn("💳 Tarjeta", options=_tarjetas_nombres, required=True, width="small"),
                        "categoria":      st.column_config.SelectboxColumn("🏷️ Categoría", options=_cats_tarjeta, required=True, width="medium"),
                        "descripcion":    st.column_config.TextColumn("📝 Descripción", width="large"),
                        "moneda":         st.column_config.SelectboxColumn("💱", options=["PEN", "USD"], width="small"),
                        "monto":          st.column_config.NumberColumn("💰 Monto", min_value=0.0, step=0.1, required=True, format="%,.1f", width="small"),
                    },
                    key="editor_gastos_tarjeta"
                )

                if st.button("💾 Guardar cambios — Gastos tarjeta", type="primary"):
                    df_editado = ed_gt.copy()
                    # Restaurar tarjeta_id desde el nombre (puede haber cambiado)
                    _mapa_id = {t["nombre"]: t["id"] for t in st.session_state["tarjetas"]}
                    df_editado["tarjeta_id"] = df_editado["tarjeta_nombre"].map(_mapa_id).fillna("")
                    # Asegurar IDs únicos
                    df_editado["id"] = df_editado.get("id", pd.Series(dtype=str)).apply(
                        lambda x: str(uuid.uuid4()) if (x is None or str(x) in ["", "None", "nan"]) else str(x)
                    ) if "id" in df_editado.columns else [str(uuid.uuid4()) for _ in range(len(df_editado))]
                    # Sanear
                    for _c, _d in {"moneda": "PEN", "descripcion": "", "categoria": "", "tarjeta_nombre": "", "tarjeta_id": ""}.items():
                        if _c in df_editado.columns:
                            df_editado[_c] = df_editado[_c].apply(
                                lambda x: _d if (x is None or (isinstance(x, float) and pd.isna(x)) or str(x) in ["", "None", "nan"]) else str(x)
                            )
                    df_editado["monto"] = pd.to_numeric(df_editado["monto"], errors="coerce").fillna(0.0)
                    df_editado["fecha"] = pd.to_datetime(df_editado["fecha"], errors="coerce").dt.strftime("%Y-%m-%d")
                    df_editado = df_editado.dropna(subset=["fecha"]).sort_values("fecha", ascending=False)
                    st.session_state["gastos_tarjeta"] = df_editado.to_dict("records")
                    guardar("gastos_tarjeta")
                    st.success("✅ Guardado.")
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
        with st.expander("💵 Ingresos puntuales", expanded=False):
            # Mapa de cuentas
            _ip_ncp  = st.session_state["configuracion"].get("nombre_cuenta_principal", "Cuenta principal")
            _ip_ctas = {_ip_ncp: "principal"}
            for _ipc in st.session_state["cuentas_ahorro"]:
                _ip_ctas[_ipc["nombre"]] = _ipc["id"]
            _ip_ctas_nombres = list(_ip_ctas.keys())

            with st.form("form_ingreso_puntual"):
                _ip1, _ip2 = st.columns(2)
                with _ip1:
                    concepto  = st.text_input("📝 Concepto")
                    fecha     = st.date_input("📅 Fecha", value=hoy_peru, key="fecha_ingreso_puntual")
                with _ip2:
                    monto     = st.number_input("💰 Monto (S/)", min_value=0.0)
                    _ip_cta   = st.selectbox("🏦 Cuenta que recibe", _ip_ctas_nombres, key="cta_ingreso_puntual")
                if st.form_submit_button("➕ Agregar ingreso puntual", use_container_width=True, type="primary"):
                    st.session_state["ingresos_puntuales"].append({
                        "concepto":          concepto,
                        "fecha":             fecha.isoformat(),
                        "monto":             monto,
                        "cuenta_destino_id": _ip_ctas[_ip_cta],
                        "cuenta_destino_nombre": _ip_cta,
                    })
                    guardar("ingresos_puntuales")
                    st.rerun()

            df_ing_punt = pd.DataFrame(st.session_state["ingresos_puntuales"])
            if not df_ing_punt.empty:
                # Asegurar columnas nuevas en registros viejos
                if "cuenta_destino_id" not in df_ing_punt.columns:
                    df_ing_punt["cuenta_destino_id"] = "principal"
                if "cuenta_destino_nombre" not in df_ing_punt.columns:
                    df_ing_punt["cuenta_destino_nombre"] = _ip_ncp
                df_ing_punt["cuenta_destino_id"]     = df_ing_punt["cuenta_destino_id"].fillna("principal")
                df_ing_punt["cuenta_destino_nombre"] = df_ing_punt["cuenta_destino_nombre"].fillna(_ip_ncp)
                df_ing_punt["fecha"] = pd.to_datetime(df_ing_punt["fecha"], errors="coerce").dt.date
                df_ing_punt["monto"] = pd.to_numeric(df_ing_punt["monto"], errors="coerce").fillna(0)
                df_ing_punt = df_ing_punt.sort_values("fecha", ascending=False).reset_index(drop=True)
                st.caption("✏️ Edita celdas · selecciona fila + **Delete** para borrar · luego **Guardar**")
                ed_ing_punt = st.data_editor(
                    df_ing_punt, use_container_width=True, hide_index=True,
                    num_rows="dynamic", height=min(38 * len(df_ing_punt) + 46, 320),
                    column_config={
                        "concepto":              st.column_config.TextColumn("📝 Concepto", width="large"),
                        "fecha":                 st.column_config.DateColumn("📅 Fecha", width="small"),
                        "monto":                 st.column_config.NumberColumn("💰 Monto (S/)", min_value=0.0, format="S/ %,.0f", width="small"),
                        "cuenta_destino_nombre": st.column_config.SelectboxColumn("🏦 Cuenta", options=_ip_ctas_nombres, width="medium"),
                        "cuenta_destino_id":     None,
                    }, key="editor_ingresos_puntuales"
                )
                if st.button("💾 Guardar cambios — Ingresos puntuales", type="primary"):
                    df_ed = ed_ing_punt.copy()
                    df_ed["fecha"]   = pd.to_datetime(df_ed["fecha"], errors="coerce").dt.strftime("%Y-%m-%d")
                    df_ed["monto"]   = pd.to_numeric(df_ed["monto"], errors="coerce").fillna(0)
                    df_ed["concepto"]= df_ed["concepto"].fillna("").astype(str)
                    # Sync cuenta_destino_id from nombre
                    df_ed["cuenta_destino_id"] = df_ed["cuenta_destino_nombre"].map(
                        lambda n: _ip_ctas.get(str(n), "principal")
                    )
                    st.session_state["ingresos_puntuales"] = (
                        df_ed.dropna(subset=["fecha"])
                             .sort_values("fecha", ascending=False)
                             .to_dict("records")
                    )
                    guardar("ingresos_puntuales")
                    st.success("✅ Guardado.")
                    st.rerun()
            else:
                st.info("No hay ingresos puntuales registrados.")

        with st.expander("🔁 Transferencias entre cuentas", expanded=False):
            nombre_cuenta_principal = st.session_state["configuracion"].get("nombre_cuenta_principal", "Cuenta principal")
            cuentas_map = {nombre_cuenta_principal: "principal"}
            for c in st.session_state["cuentas_ahorro"]:
                cuentas_map[c["nombre"]] = c["id"]

            with st.form("form_transferencia"):
                _tr1, _tr2 = st.columns(2)
                with _tr1:
                    fecha   = st.date_input("📅 Fecha", value=hoy_peru, key="fecha_transferencia")
                    origen  = st.selectbox("🏦 Cuenta origen",  list(cuentas_map.keys()), key="transferencia_origen")
                with _tr2:
                    monto   = st.number_input("💰 Monto (S/)", min_value=0.0, key="monto_transferencia")
                    destino = st.selectbox("➡️ Cuenta destino", list(cuentas_map.keys()), key="transferencia_destino")
                if st.form_submit_button("➕ Registrar transferencia", use_container_width=True, type="primary"):
                    if origen == destino:
                        st.warning("Origen y destino deben ser distintos.")
                    else:
                        st.session_state["transferencias"].append({
                            "fecha": fecha.isoformat(), "origen": cuentas_map[origen],
                            "destino": cuentas_map[destino], "monto": monto
                        })
                        guardar("transferencias")
                        st.rerun()

            df_transf = pd.DataFrame(st.session_state["transferencias"])
            if not df_transf.empty:
                df_transf["fecha"] = pd.to_datetime(df_transf["fecha"], errors="coerce").dt.date
                df_transf["monto"] = pd.to_numeric(df_transf["monto"], errors="coerce").fillna(0)
                df_transf = df_transf.sort_values("fecha", ascending=False).reset_index(drop=True)
                st.caption("✏️ Edita celdas · selecciona fila + **Delete** para borrar · luego **Guardar**")
                ed = st.data_editor(
                    df_transf, use_container_width=True, hide_index=True,
                    num_rows="dynamic", height=min(38 * len(df_transf) + 46, 300),
                    column_config={
                        "fecha":   st.column_config.DateColumn("📅 Fecha", width="small"),
                        "origen":  st.column_config.TextColumn("🏦 Origen", width="small"),
                        "destino": st.column_config.TextColumn("➡️ Destino", width="small"),
                        "monto":   st.column_config.NumberColumn("💰 Monto (S/)", min_value=0.0, format="S/ %,.0f", width="small"),
                    }, key="editor_transferencias"
                )
                if st.button("💾 Guardar cambios — Transferencias", type="primary"):
                    df_ed = ed.copy()
                    df_ed["fecha"] = pd.to_datetime(df_ed["fecha"], errors="coerce").dt.strftime("%Y-%m-%d")
                    df_ed["monto"] = pd.to_numeric(df_ed["monto"], errors="coerce").fillna(0)
                    st.session_state["transferencias"] = df_ed.dropna(subset=["fecha"]).sort_values("fecha", ascending=False).to_dict("records")
                    guardar("transferencias")
                    st.success("✅ Guardado.")
                    st.rerun()
            else:
                st.info("No hay transferencias registradas.")

    with st.expander("🔄 3.3 Gastos reembolsables", expanded=False):
        st.caption("Registra gastos que otra persona o empresa te devolverá. No se suman a tus gastos personales. Al marcarlos como reembolsados, el monto se registra automáticamente como ingreso puntual.")

        _remb_list  = st.session_state.get("gastos_reembolsables", [])
        _remb_pend  = [r for r in _remb_list if r.get("estado") == "pendiente"]
        _remb_total = sum(
            float(r["monto"]) * (_tc_default if r.get("moneda") == "USD" else 1.0)
            for r in _remb_pend
        ) if _remb_pend else 0.0

        if _remb_pend:
            st.info(
                "Tienes " + str(len(_remb_pend)) + " gasto(s) pendiente(s) de reembolso"
                " por un total de S/ " + f"{_remb_total:,.0f}"
            )

        # Mapas de cuentas y tarjetas
                # Mapas de cuentas y tarjetas
        _r_ncp  = st.session_state["configuracion"].get("nombre_cuenta_principal", "Cuenta principal")
        _r_ctas = {_r_ncp: "principal"}
        for _rc in st.session_state["cuentas_ahorro"]:
            _r_ctas[_rc["nombre"]] = _rc["id"]
        _r_tarjs = {t["nombre"]: t["id"] for t in st.session_state["tarjetas"]}

        # ── Selector de medio FUERA del form → renderizado condicional real ──
        _medio_sel = st.radio(
            "Medio de pago del gasto",
            ["💳 Débito", "💳 Tarjeta de crédito"],
            horizontal=True, key="remb_medio_radio"
        )
        _es_cred_f = (_medio_sel == "💳 Tarjeta de crédito")

        with st.form("form_reembolsable", clear_on_submit=True):
            _rr1, _rr2 = st.columns(2)
            with _rr1:
                _r_fecha    = st.date_input("Fecha del gasto", value=hoy_peru, key="fecha_reembolsable")
                _r_desc     = st.text_input("Descripcion", placeholder="ej: Taxi para reunion con cliente")
                _r_empresa  = st.text_input("Quien reembolsa", placeholder="ej: Mi empresa")
                _r_fecha_esp = st.date_input("Fecha esperada de reembolso",
                                              value=hoy_peru + timedelta(days=14),
                                              key="fecha_esp_reembolsable")
            with _rr2:
                if _es_cred_f:
                    _r_tarj_n = st.selectbox("Tarjeta de crédito usada",
                                              list(_r_tarjs.keys()) if _r_tarjs else ["(agrega una tarjeta primero)"],
                                              key="tarj_remb_origen")
                    _r_cta_origen_n = ""
                else:
                    _r_cta_origen_n = st.selectbox("Cuenta débito de origen",
                                                    list(_r_ctas.keys()), key="cta_remb_origen")
                    _r_tarj_n = ""
                _r_cta_remb = st.selectbox("Cuenta que recibe el reembolso",
                                            list(_r_ctas.keys()), key="cta_remb_destino")
                _rm_c, _rm_m = st.columns([1, 2])
                with _rm_c:
                    _r_moneda = st.selectbox("Moneda", ["PEN", "USD"], key="moneda_reembolsable")
                with _rm_m:
                    _r_monto = st.number_input("Monto", min_value=0.0, step=1.0, key="monto_reembolsable")

            if st.form_submit_button("Agregar gasto reembolsable", use_container_width=True, type="primary"):
                if _r_monto > 0 and _r_desc.strip():
                    _tarj_id_r   = _r_tarjs.get(_r_tarj_n, "") if _es_cred_f else ""
                    _cta_orig_id = _r_ctas.get(_r_cta_origen_n, "principal") if not _es_cred_f else ""
                    st.session_state["gastos_reembolsables"].append({
                        "id":                      str(uuid.uuid4()),
                        "fecha":                   _r_fecha.isoformat(),
                        "descripcion":             _r_desc.strip(),
                        "empresa":                 _r_empresa.strip(),
                        "medio_pago":              "Tarjeta de credito" if _es_cred_f else "Debito",
                        "tarjeta_nombre":          _r_tarj_n if _es_cred_f else "",
                        "tarjeta_id":              _tarj_id_r,
                        "cuenta_origen_nombre":    _r_cta_origen_n if not _es_cred_f else "",
                        "cuenta_origen_id":        _cta_orig_id,
                        "cuenta_reembolso_nombre": _r_cta_remb,
                        "cuenta_reembolso_id":     _r_ctas.get(_r_cta_remb, "principal"),
                        "moneda":                  _r_moneda,
                        "monto":                   float(_r_monto),
                        "fecha_esperada":          _r_fecha_esp.isoformat(),
                        "estado":                  "pendiente",
                        "fecha_reembolso":         None,
                    })
                    guardar("gastos_reembolsables")
                    st.success("Gasto reembolsable registrado.")
                    st.rerun()
                else:
                    st.warning("Completa descripcion y monto.")

        df_remb = pd.DataFrame(st.session_state.get("gastos_reembolsables", []))
        if not df_remb.empty:
            df_remb["fecha"]          = pd.to_datetime(df_remb["fecha"],          errors="coerce").dt.date
            df_remb["fecha_esperada"] = pd.to_datetime(df_remb["fecha_esperada"], errors="coerce").dt.date
            df_remb["monto"]          = pd.to_numeric(df_remb["monto"],           errors="coerce").fillna(0)

            _tab_pend, _tab_done = st.tabs(["Pendientes de reembolso", "Reembolsados"])

            with _tab_pend:
                _df_pend = df_remb[df_remb["estado"] == "pendiente"].copy().reset_index(drop=True)
                if not _df_pend.empty:
                    for _idx, _row in _df_pend.iterrows():
                        _mon     = _row.get("moneda", "PEN")
                        _monto_s = ("USD " + f"{_row['monto']:,.2f}") if _mon == "USD" else ("S/ " + f"{_row['monto']:,.1f}")
                        _desc_s  = str(_row["descripcion"])
                        _es_cred = _row.get("medio_pago","") == "Tarjeta de credito"
                        _origen_s = (str(_row.get("tarjeta_nombre","")) if _es_cred
                                     else str(_row.get("cuenta_origen_nombre",""))) or "—"
                        _remb_s  = str(_row.get("cuenta_reembolso_nombre","—"))
                        _fkey = "fecha_remb_" + str(_row["id"])
                        _bkey = "btn_remb_"   + str(_row["id"])
                        _dkey = "btn_del_"    + str(_row["id"])

                        _ca, _cb, _cc, _cd = st.columns([3, 2, 2, 1])
                        _tip = "Tarjeta: " if _es_cred else "Debito: "
                        _ca.caption("**" + _desc_s + "**")
                        _ca.caption(_tip + _origen_s + " | Reembolso a: " + _remb_s)
                        _cb.caption(_monto_s + " | " + str(_row["fecha"]))
                        with _cc:
                            _val_esp = _row["fecha_esperada"] if pd.notna(_row["fecha_esperada"]) else hoy_peru
                            _fecha_esp_edit = st.date_input("Fecha esperada", value=_val_esp,
                                                             key="esp_" + str(_row["id"]))
                            if _fecha_esp_edit != _row["fecha_esperada"]:
                                for _r in st.session_state["gastos_reembolsables"]:
                                    if _r["id"] == _row["id"]:
                                        _r["fecha_esperada"] = _fecha_esp_edit.isoformat()
                                        break
                                guardar("gastos_reembolsables")
                                st.rerun()
                            _fecha_remb_input = st.date_input("Fecha real reembolso",
                                                               value=_fecha_esp_edit, key=_fkey)
                            if st.button("Reembolsado", key=_bkey, use_container_width=True):
                                for _r in st.session_state["gastos_reembolsables"]:
                                    if _r["id"] == _row["id"]:
                                        _r["estado"] = "reembolsado"
                                        _r["fecha_reembolso"] = _fecha_remb_input.isoformat()
                                        break
                                _tc_remb    = _tc_default if _mon == "USD" else 1.0
                                _monto_remb = float(_row["monto"]) * _tc_remb
                                _cta_remb_id = _row.get("cuenta_reembolso_id", "principal") or "principal"
                                st.session_state["ingresos_puntuales"].append({
                                    "concepto":          "Reembolso: " + _desc_s + " (a " + _remb_s + ")",
                                    "fecha":             _fecha_remb_input.isoformat(),
                                    "monto":             _monto_remb,
                                    "cuenta_destino_id": _cta_remb_id,
                                })
                                guardar("gastos_reembolsables")
                                guardar("ingresos_puntuales")
                                st.rerun()
                        with _cd:
                            st.write("")
                            if st.button("Del", key=_dkey, help="Eliminar", use_container_width=True):
                                st.session_state["gastos_reembolsables"] = [
                                    _r for _r in st.session_state["gastos_reembolsables"]
                                    if _r["id"] != str(_row["id"])
                                ]
                                guardar("gastos_reembolsables")
                                st.rerun()
                        st.divider()
                else:
                    st.success("No tienes gastos reembolsables pendientes.")

            with _tab_done:
                _df_done = df_remb[df_remb["estado"] == "reembolsado"].copy().reset_index(drop=True)
                if not _df_done.empty:
                    _df_done["fecha_reembolso"] = pd.to_datetime(_df_done["fecha_reembolso"], errors="coerce").dt.date
                    for _idx2, _row2 in _df_done.iterrows():
                        _mon2   = _row2.get("moneda", "PEN")
                        _monto2 = ("USD " + f"{_row2['monto']:,.2f}") if _mon2 == "USD" else ("S/ " + f"{_row2['monto']:,.1f}")
                        _dkey2  = "btn_del_done_" + str(_row2["id"])
                        _da, _db, _dc = st.columns([4, 2, 1])
                        _da.caption("**" + str(_row2["descripcion"]) + "** | " + str(_row2.get("empresa","—")))
                        _da.caption("Reembolso a: " + str(_row2.get("cuenta_reembolso_nombre","—")))
                        _db.caption(_monto2 + " | " + str(_row2.get("fecha_reembolso","—")))
                        with _dc:
                            st.write("")
                            if st.button("Del", key=_dkey2, help="Eliminar", use_container_width=True):
                                st.session_state["gastos_reembolsables"] = [
                                    _r for _r in st.session_state["gastos_reembolsables"]
                                    if _r["id"] != str(_row2["id"])
                                ]
                                guardar("gastos_reembolsables")
                                st.rerun()
                        st.divider()
                else:
                    st.info("Aun no tienes reembolsos completados.")
        else:
                st.info("No hay gastos reembolsables registrados.")


# ==================================================
# ==================================================
# 4. FUNCIONES AVANZADAS
# ==================================================
with st.expander("🧩 4. Funciones avanzadas", expanded=False):
    st.caption("Módulos complementarios: simulación de préstamos y flujo completo de IBKR: cash, compras, valorización y seguimiento.")

# 4.1 SIMULACIÓN DE PRÉSTAMOS
    # ==================================================
    with st.expander("🏦 4.1 Simulación de préstamos", expanded=False):
        st.caption("Simula el impacto de un préstamo en tus ahorros. Puedes guardar la simulación y activar/desactivar su efecto en los gráficos.")

        # ── Mapas de cuentas y tarjetas ──────────────────────────────
        _p_ncp  = st.session_state["configuracion"].get("nombre_cuenta_principal", "Cuenta principal")
        _p_ctas = {_p_ncp: "principal"}
        for _pc in st.session_state["cuentas_ahorro"]:
            _p_ctas[_pc["nombre"]] = _pc["id"]
        _p_tarjs = {t["nombre"]: t["id"] for t in st.session_state["tarjetas"]}
        _p_medios = list(_p_ctas.keys()) + [f"Tarjeta: {n}" for n in _p_tarjs.keys()]

        # ── Formulario nueva simulación ───────────────────────────────
        with st.form("form_prestamo", clear_on_submit=True):
            st.markdown("#### ➕ Nueva simulación")

            st.markdown("**🏦 Préstamo**")
            _fp1, _fp2 = st.columns(2)
            with _fp1:
                _p_nombre    = st.text_input("📝 Nombre", placeholder="ej: Préstamo vehículo")
                _p_monto_pre = st.number_input("💰 Monto del préstamo (S/)", min_value=0.0, step=1000.0)
                _p_cta_desembolso = st.selectbox(
                    "🏦 Cuenta que recibe el préstamo",
                    list(_p_ctas.keys()), key="prestamo_cta_desembolso"
                )
            with _fp2:
                _p_fecha_desembolso = st.date_input("📅 Fecha de desembolso", value=hoy_peru, key="prestamo_fecha_desembolso")
                _p_desc = st.text_area("📝 Notas", placeholder="Condiciones, banco, tasa, etc.", height=80)

            st.markdown("**🛒 Compra del bien**")
            _fg1, _fg2 = st.columns(2)
            with _fg1:
                _p_monto_tot = st.number_input(
                    "🏷️ Costo total del bien (S/)", min_value=0.0, step=1000.0,
                    help="Si es mayor al préstamo, la diferencia sale de la cuenta seleccionada"
                )
                _p_cta_pago_bien = st.selectbox(
                    "💳 Cuenta que paga el bien",
                    list(_p_ctas.keys()), key="prestamo_cta_pago_bien"
                )
            with _fg2:
                _p_fecha_compra = st.date_input("📅 Fecha de compra del bien", value=hoy_peru, key="prestamo_fecha_compra")

            st.markdown("**📆 Cuotas mensuales**")
            _fq1, _fq2, _fq3, _fq4 = st.columns(4)
            with _fq1:
                _p_cuota = st.number_input("💰 Cuota mensual (S/)", min_value=0.0, step=100.0)
            with _fq2:
                _p_medio_pago = st.selectbox("💳 Cuenta/tarjeta de cuotas", _p_medios, key="prestamo_medio")
            with _fq3:
                _p_fecha_primera_cuota = st.date_input("📅 Primera cuota", value=hoy_peru, key="prestamo_fecha_primera")
                _p_dia_cuota = st.number_input("📆 Día del mes", min_value=1, max_value=31, value=5, key="prestamo_dia")
            with _fq4:
                _p_fecha_ultima_cuota = st.date_input("📅 Última cuota", value=hoy_peru, key="prestamo_fecha_fin")

            st.markdown("**💥 Pago de cierre anticipado** *(opcional)*")
            _fc1, _fc2 = st.columns(2)
            with _fc1:
                _p_monto_cierre = st.number_input(
                    "💰 Monto de cierre (S/)", min_value=0.0, step=1000.0,
                    help="Pago único que cancela el préstamo. Después de esta fecha no se generan más cuotas."
                )
            with _fc2:
                _p_fecha_cierre = st.date_input("📅 Fecha de pago de cierre", value=hoy_peru, key="prestamo_fecha_cierre")

            if st.form_submit_button("💾 Guardar simulación", use_container_width=True, type="primary"):
                if _p_nombre.strip() and _p_monto_pre > 0 and _p_cuota > 0:
                    if _p_medio_pago.startswith("Tarjeta: "):
                        _tarj_name  = _p_medio_pago.replace("Tarjeta: ", "")
                        _medio_id   = _p_tarjs.get(_tarj_name, "")
                        _medio_tipo = "tarjeta"
                    else:
                        _medio_id   = _p_ctas.get(_p_medio_pago, "principal")
                        _medio_tipo = "cuenta"
                    st.session_state["simulaciones_prestamo"].append({
                        "id":                    str(uuid.uuid4()),
                        "nombre":                _p_nombre.strip(),
                        "monto_prestamo":        float(_p_monto_pre),
                        "monto_total":           float(_p_monto_tot) if _p_monto_tot > 0 else float(_p_monto_pre),
                        "cta_desembolso":        _p_cta_desembolso,
                        "cta_desembolso_id":     _p_ctas.get(_p_cta_desembolso, "principal"),
                        "fecha_desembolso":      _p_fecha_desembolso.isoformat(),
                        "cta_pago_bien":         _p_cta_pago_bien,
                        "cta_pago_bien_id":      _p_ctas.get(_p_cta_pago_bien, "principal"),
                        "fecha_compra":          _p_fecha_compra.isoformat(),
                        "cuota":                 float(_p_cuota),
                        "medio_pago":            _p_medio_pago,
                        "medio_id":              _medio_id,
                        "medio_tipo":            _medio_tipo,
                        "fecha_primera_cuota":   _p_fecha_primera_cuota.isoformat(),
                        "dia_cuota":             int(_p_dia_cuota),
                        "fecha_fin":             _p_fecha_ultima_cuota.isoformat(),
                        "descripcion":           _p_desc.strip(),
                        "monto_cierre":          float(_p_monto_cierre) if _p_monto_cierre > 0 else 0.0,
                        "fecha_cierre":          _p_fecha_cierre.isoformat() if _p_monto_cierre > 0 else None,
                        "activo":                True,
                    })
                    guardar("simulaciones_prestamo")
                    st.success("✅ Simulación guardada.")
                    st.rerun()
                else:
                    st.warning("Completa nombre, monto del préstamo y cuota.")

        # ── Lista de simulaciones guardadas ───────────────────────────
        _sims = st.session_state.get("simulaciones_prestamo", [])
        if _sims:
            st.markdown("#### 📋 Simulaciones guardadas")
            for _sim in _sims:
                _s_activo = _sim.get("activo", True)
                with st.container(border=True):
                    _sc1, _sc2, _sc3, _sc4 = st.columns([3, 2, 1, 1])
                    _gasto_propio = max(0, float(_sim["monto_total"]) - float(_sim["monto_prestamo"]))
                    _sc1.markdown(f"**{_sim['nombre']}**")
                    _sc1.caption(
                        f"Préstamo: S/ {_sim['monto_prestamo']:,.0f}  →  "
                        f"{_sim.get('cta_desembolso','—')} el {_sim.get('fecha_desembolso', _sim.get('fecha_inicio','—'))}"
                    )
                    _sc1.caption(
                        f"Bien: S/ {_sim['monto_total']:,.0f}  ·  "
                        f"Paga: {_sim.get('cta_pago_bien','—')} el {_sim.get('fecha_compra', _sim.get('fecha_inicio','—'))}  ·  "
                        f"De tus ahorros: S/ {_gasto_propio:,.0f}"
                    )
                    _sc1.caption(
                        f"Cuota: S/ {_sim['cuota']:,.0f}/mes día {_sim.get('dia_cuota','?')}  ·  "
                        f"{_sim['medio_pago']}  ·  "
                        f"{_sim.get('fecha_primera_cuota', _sim.get('fecha_inicio','—'))} → {_sim['fecha_fin']}"
                    )
                    if _sim.get("descripcion"):
                        _sc1.caption(f"📝 {_sim['descripcion']}")
                    if _sim.get("monto_cierre", 0) > 0:
                        _sc1.caption(
                            f"💥 Cierre anticipado: S/ {_sim['monto_cierre']:,.0f} "
                            f"el {_sim.get('fecha_cierre','—')} → cuotas se detienen ahí"
                        )
                    # Calcular cuotas totales y monto pagado/restante
                    _f_ini_ref = _sim.get("fecha_primera_cuota") or _sim.get("fecha_desembolso") or _sim.get("fecha_inicio") or hoy_peru.isoformat()
                    _f_ini = pd.to_datetime(_f_ini_ref)
                    _f_fin = pd.to_datetime(_sim["fecha_fin"])
                    _meses_total = max(1, (_f_fin.year - _f_ini.year) * 12 + (_f_fin.month - _f_ini.month) + 1)
                    _meses_pag   = max(0, (hoy_peru.year - _f_ini.year) * 12 + (hoy_peru.month - _f_ini.month))
                    _pagado      = min(_meses_pag, _meses_total) * float(_sim["cuota"])
                    _pendiente   = max(0, _meses_total - _meses_pag) * float(_sim["cuota"])
                    _sc2.metric("Total cuotas", f"S/ {_meses_total * _sim['cuota']:,.0f}")
                    _sc2.caption(f"Pagado: S/ {_pagado:,.0f}  |  Pendiente: S/ {_pendiente:,.0f}")
                    with _sc3:
                        _tog_key = f"tog_sim_{_sim['id']}"
                        _nuevo_estado = st.toggle(
                            "Simular",
                            value=_s_activo,
                            key=_tog_key,
                            help="Activa para ver el impacto en los gráficos de ahorros"
                        )
                        if _nuevo_estado != _s_activo:
                            _sim["activo"] = _nuevo_estado
                            guardar("simulaciones_prestamo")
                            st.rerun()
                    with _sc4:
                        st.write("")
                        if st.button("🗑️", key=f"del_sim_{_sim['id']}", help="Eliminar simulación"):
                            st.session_state["simulaciones_prestamo"] = [
                                s for s in st.session_state["simulaciones_prestamo"]
                                if s["id"] != _sim["id"]
                            ]
                            guardar("simulaciones_prestamo")
                            st.rerun()
        else:
            st.info("No hay simulaciones de préstamo guardadas.")



    # ==================================================
    # 4.2 PORTAFOLIO IBKR
    # ==================================================
    with st.expander("📈 4.2 IBKR: cash e inversiones", expanded=False):
        st.caption(
            "Primero agrega cash a IBKR desde una cuenta local; luego usa ese cash para comprar acciones o ETFs. Si compras un ticker nuevo, "
            "la app lo agrega automáticamente al catálogo y puede consultar Yahoo Finance como respaldo hasta que Airflow lo actualice."
        )

        _tc_inv = float(st.session_state["configuracion"].get("tipo_cambio_default", _tc_default))
        _df_catalogo_ibkr = cargar_catalogo_ibkr()
        _df_precios_ibkr = cargar_precios_ibkr_airflow()

        def _normalizar_cash_ibkr():
            _df_cash = pd.DataFrame(st.session_state.get("ibkr_cash_movimientos", []))

            if _df_cash.empty:
                return pd.DataFrame(columns=["id", "fecha", "tipo_movimiento", "descripcion", "monto_usd"])

            for _col, _default in {
                "id": "",
                "fecha": hoy_peru.isoformat(),
                "tipo_movimiento": "Depósito",
                "descripcion": "",
                "monto_usd": 0.0,
            }.items():
                if _col not in _df_cash.columns:
                    _df_cash[_col] = _default

            _df_cash["id"] = _df_cash["id"].apply(
                lambda x: str(uuid.uuid4()) if (x is None or str(x) in ["", "None", "nan"]) else str(x)
            )
            _df_cash["fecha"] = pd.to_datetime(_df_cash["fecha"], errors="coerce").dt.date
            _df_cash["tipo_movimiento"] = _df_cash["tipo_movimiento"].fillna("Depósito").astype(str)
            _df_cash["descripcion"] = _df_cash["descripcion"].fillna("").astype(str)
            _df_cash["monto_usd"] = pd.to_numeric(_df_cash["monto_usd"], errors="coerce").fillna(0.0)
            _df_cash = _df_cash.dropna(subset=["fecha"]).sort_values("fecha", ascending=False).reset_index(drop=True)

            return _df_cash

        _df_cash_ibkr = _normalizar_cash_ibkr()
        _total_cash_manual_ibkr_usd = float(_df_cash_ibkr["monto_usd"].sum()) if not _df_cash_ibkr.empty else 0.0
        _total_cash_transferencias_ibkr_usd = calcular_total_transferencias_ibkr_usd()
        _total_cash_ibkr_usd = float(_total_cash_manual_ibkr_usd + _total_cash_transferencias_ibkr_usd)

        # ──────────────────────────────────────────────
        # Paso 1: Transferir fondos desde cuentas locales hacia IBKR
        # ──────────────────────────────────────────────
        st.markdown("#### 1️⃣ Agregar cash a IBKR desde una cuenta")
        st.caption(
            "Primero registra el dinero que sale de una cuenta local y llega como cash USD a IBKR. "
            "Puedes ingresar el monto enviado en soles o dólares, y la comisión en soles o dólares."
        )

        _tf_ncp = st.session_state["configuracion"].get("nombre_cuenta_principal", "Cuenta principal")
        _tf_ctas = {_tf_ncp: "principal"}
        for _tf_c in st.session_state.get("cuentas_ahorro", []):
            _tf_nombre = str(_tf_c.get("nombre", "")).strip()
            if _tf_nombre and "IBKR" not in _tf_nombre.upper():
                _tf_ctas[_tf_nombre] = _tf_c.get("id")

        _tf_tc_default = float(st.session_state["configuracion"].get("tipo_cambio_default", _tc_default))

        with st.form("form_transferencia_a_ibkr", clear_on_submit=True):
            st.markdown("##### ➕ Nueva transferencia / depósito a IBKR")
            _tf1, _tf2, _tf3 = st.columns(3)

            with _tf1:
                _tf_fecha = st.date_input("Fecha", value=hoy_peru, key="fecha_transferencia_ibkr")
                _tf_origen_nombre = st.selectbox(
                    "Cuenta origen",
                    list(_tf_ctas.keys()),
                    key="cuenta_origen_transferencia_ibkr"
                )

            with _tf2:
                _tf_moneda_monto = st.selectbox(
                    "Moneda del monto enviado",
                    ["PEN", "USD"],
                    key="moneda_monto_transferencia_ibkr",
                    help="Elige PEN si retiras soles de tu cuenta; elige USD si ya envías dólares."
                )
                _tf_monto_origen = st.number_input(
                    "Monto enviado a IBKR",
                    min_value=0.0,
                    step=100.0,
                    format="%.2f",
                    key="monto_origen_transferencia_ibkr",
                    help="Monto bruto que llegará a IBKR como cash, antes de registrar la comisión."
                )
                _tf_tc = st.number_input(
                    "TC USD → PEN usado",
                    min_value=1.0,
                    step=0.01,
                    value=round(_tf_tc_default, 4),
                    format="%.4f",
                    key="tc_transferencia_ibkr"
                )

            with _tf3:
                _tf_comision_monto = st.number_input(
                    "Comisión",
                    min_value=0.0,
                    step=1.0,
                    format="%.2f",
                    key="comision_transferencia_ibkr"
                )
                _tf_comision_moneda = st.selectbox(
                    "Moneda comisión",
                    ["PEN", "USD"],
                    key="moneda_comision_transferencia_ibkr"
                )

            _tf_desc = st.text_input(
                "Descripción / referencia",
                placeholder="Ej.: Transferencia BCP → IBKR, wire fee, depósito para invertir",
                key="descripcion_transferencia_ibkr"
            )

            if _tf_moneda_monto == "PEN":
                _tf_monto_pen = float(_tf_monto_origen)
                _tf_monto_usd = float(_tf_monto_origen) / float(_tf_tc) if _tf_tc > 0 else 0.0
            else:
                _tf_monto_usd = float(_tf_monto_origen)
                _tf_monto_pen = float(_tf_monto_origen) * float(_tf_tc)

            _tf_comision_pen = float(_tf_comision_monto) if _tf_comision_moneda == "PEN" else float(_tf_comision_monto) * float(_tf_tc)
            _tf_total_debitado_pen = float(_tf_monto_pen) + float(_tf_comision_pen)

            st.info(
                f"Vista previa: se descontará **S/ {_tf_total_debitado_pen:,.2f}** de {_tf_origen_nombre} "
                f"y se agregará **US$ {_tf_monto_usd:,.2f}** al cash IBKR. "
                f"Comisión equivalente: S/ {_tf_comision_pen:,.2f}."
            )

            if st.form_submit_button("➕ Registrar cash en IBKR", use_container_width=True, type="primary"):
                if _tf_monto_origen <= 0:
                    st.warning("Ingresa un monto enviado a IBKR mayor a cero.")
                elif _tf_tc <= 0:
                    st.warning("El tipo de cambio debe ser mayor a cero.")
                else:
                    st.session_state["ibkr_transferencias"].append({
                        "id": str(uuid.uuid4()),
                        "fecha": _tf_fecha.isoformat(),
                        "cuenta_origen_id": _tf_ctas.get(_tf_origen_nombre, "principal"),
                        "cuenta_origen_nombre": _tf_origen_nombre,
                        "monto_origen": float(_tf_monto_origen),
                        "moneda_monto": _tf_moneda_monto,
                        "monto_pen": float(_tf_monto_pen),
                        "tc_usd_pen": float(_tf_tc),
                        "monto_usd": float(_tf_monto_usd),
                        "comision_monto": float(_tf_comision_monto),
                        "comision_moneda": _tf_comision_moneda,
                        "comision_pen": float(_tf_comision_pen),
                        "total_debitado_pen": float(_tf_total_debitado_pen),
                        "descripcion": _tf_desc,
                    })
                    guardar("ibkr_transferencias")
                    st.success("✅ Cash registrado. El monto USD ya se suma al cash IBKR y el total debitado se descuenta de la cuenta origen.")
                    st.rerun()

        _df_tf_ibkr = pd.DataFrame(st.session_state.get("ibkr_transferencias", []))
        if not _df_tf_ibkr.empty:
            for _col, _default in {
                "id": "",
                "fecha": hoy_peru.isoformat(),
                "cuenta_origen_id": "principal",
                "cuenta_origen_nombre": _tf_ncp,
                "monto_origen": 0.0,
                "moneda_monto": "PEN",
                "monto_pen": 0.0,
                "tc_usd_pen": _tf_tc_default,
                "monto_usd": 0.0,
                "comision_monto": 0.0,
                "comision_moneda": "PEN",
                "comision_pen": 0.0,
                "total_debitado_pen": 0.0,
                "descripcion": "",
            }.items():
                if _col not in _df_tf_ibkr.columns:
                    _df_tf_ibkr[_col] = _default

            # Compatibilidad con transferencias antiguas registradas solo en PEN.
            _df_tf_ibkr["monto_origen"] = pd.to_numeric(_df_tf_ibkr["monto_origen"], errors="coerce")
            _df_tf_ibkr["monto_pen"] = pd.to_numeric(_df_tf_ibkr["monto_pen"], errors="coerce").fillna(0.0)
            _df_tf_ibkr["monto_origen"] = _df_tf_ibkr["monto_origen"].fillna(_df_tf_ibkr["monto_pen"])
            _mask_monto_origen_vacio = (_df_tf_ibkr["monto_origen"] <= 0) & (_df_tf_ibkr["monto_pen"] > 0)
            _df_tf_ibkr.loc[_mask_monto_origen_vacio, "monto_origen"] = _df_tf_ibkr.loc[_mask_monto_origen_vacio, "monto_pen"]
            _df_tf_ibkr["moneda_monto"] = _df_tf_ibkr["moneda_monto"].fillna("PEN").astype(str).str.upper()
            _df_tf_ibkr.loc[~_df_tf_ibkr["moneda_monto"].isin(["PEN", "USD"]), "moneda_monto"] = "PEN"

            _df_tf_ibkr["id"] = _df_tf_ibkr["id"].apply(
                lambda x: str(uuid.uuid4()) if (x is None or str(x) in ["", "None", "nan"]) else str(x)
            )
            _df_tf_ibkr["fecha"] = pd.to_datetime(_df_tf_ibkr["fecha"], errors="coerce").dt.date
            _df_tf_ibkr["tc_usd_pen"] = pd.to_numeric(_df_tf_ibkr["tc_usd_pen"], errors="coerce").fillna(_tf_tc_default)
            _df_tf_ibkr["tc_usd_pen"] = _df_tf_ibkr["tc_usd_pen"].apply(lambda x: x if x > 0 else _tf_tc_default)
            _df_tf_ibkr["monto_usd"] = _df_tf_ibkr.apply(
                lambda r: float(r["monto_origen"]) if r["moneda_monto"] == "USD" else float(r["monto_origen"]) / float(r["tc_usd_pen"]),
                axis=1
            )
            _df_tf_ibkr["monto_pen"] = _df_tf_ibkr.apply(
                lambda r: float(r["monto_origen"]) * float(r["tc_usd_pen"]) if r["moneda_monto"] == "USD" else float(r["monto_origen"]),
                axis=1
            )
            _df_tf_ibkr["comision_monto"] = pd.to_numeric(_df_tf_ibkr["comision_monto"], errors="coerce").fillna(0.0)
            _df_tf_ibkr["comision_moneda"] = _df_tf_ibkr["comision_moneda"].fillna("PEN").astype(str).str.upper()
            _df_tf_ibkr.loc[~_df_tf_ibkr["comision_moneda"].isin(["PEN", "USD"]), "comision_moneda"] = "PEN"
            _df_tf_ibkr["comision_pen"] = _df_tf_ibkr.apply(
                lambda r: float(r["comision_monto"]) if r["comision_moneda"] == "PEN" else float(r["comision_monto"]) * float(r["tc_usd_pen"]),
                axis=1
            )
            _df_tf_ibkr["total_debitado_pen"] = _df_tf_ibkr["monto_pen"] + _df_tf_ibkr["comision_pen"]
            _df_tf_ibkr["descripcion"] = _df_tf_ibkr["descripcion"].fillna("").astype(str)
            _df_tf_ibkr["Eliminar"] = False

            _df_tf_ibkr = _df_tf_ibkr[[
                "id", "fecha", "cuenta_origen_id", "cuenta_origen_nombre",
                "monto_origen", "moneda_monto", "tc_usd_pen", "monto_usd", "monto_pen",
                "comision_monto", "comision_moneda", "comision_pen", "total_debitado_pen",
                "descripcion", "Eliminar"
            ]]

            _cash_tf_usd = float(_df_tf_ibkr["monto_usd"].sum())
            _debito_tf_pen = float(_df_tf_ibkr["total_debitado_pen"].sum())
            _metric_tf1, _metric_tf2, _metric_tf3 = st.columns(3)
            _metric_tf1.metric("Cash agregado por transferencias", f"US$ {_cash_tf_usd:,.2f}")
            _metric_tf2.metric("Total debitado de cuentas", f"S/ {_debito_tf_pen:,.0f}")
            _metric_tf3.metric("TC actual configuración", f"{_tf_tc_default:.4f}")

            with st.expander("🧾 Historial de cash agregado desde cuentas", expanded=False):
                st.caption("Puedes editar una transferencia; al guardar se recalculan USD, comisión equivalente y total debitado.")
                _ed_tf_ibkr = st.data_editor(
                    _df_tf_ibkr,
                    use_container_width=True,
                    hide_index=True,
                    num_rows="dynamic",
                    height=min(38 * len(_df_tf_ibkr) + 46, 320),
                    column_config={
                        "id": None,
                        "fecha": st.column_config.DateColumn("Fecha", required=True, width="small"),
                        "cuenta_origen_id": None,
                        "cuenta_origen_nombre": st.column_config.SelectboxColumn("Cuenta origen", options=list(_tf_ctas.keys()), width="medium"),
                        "monto_origen": st.column_config.NumberColumn("Monto enviado", min_value=0.0, step=100.0, format="%.2f", width="small"),
                        "moneda_monto": st.column_config.SelectboxColumn("Moneda monto", options=["PEN", "USD"], width="small"),
                        "tc_usd_pen": st.column_config.NumberColumn("TC", min_value=1.0, step=0.01, format="%.4f", width="small"),
                        "monto_usd": st.column_config.NumberColumn("Cash IBKR USD", format="US$ %.2f", width="small", disabled=True),
                        "monto_pen": st.column_config.NumberColumn("Monto equiv. PEN", format="S/ %.2f", width="small", disabled=True),
                        "comision_monto": st.column_config.NumberColumn("Comisión", min_value=0.0, step=1.0, format="%.2f", width="small"),
                        "comision_moneda": st.column_config.SelectboxColumn("Moneda comisión", options=["PEN", "USD"], width="small"),
                        "comision_pen": st.column_config.NumberColumn("Comisión PEN", format="S/ %.2f", width="small", disabled=True),
                        "total_debitado_pen": st.column_config.NumberColumn("Total debitado PEN", format="S/ %.2f", width="small", disabled=True),
                        "descripcion": st.column_config.TextColumn("Descripción", width="large"),
                        "Eliminar": st.column_config.CheckboxColumn("🗑"),
                    },
                    key="editor_transferencias_ibkr"
                )

                if st.button("💾 Guardar transferencias a IBKR", type="primary"):
                    _df_tf_save = _ed_tf_ibkr.copy()
                    _df_tf_save = _df_tf_save[_df_tf_save["Eliminar"] == False].drop(columns=["Eliminar"]).copy()

                    if not _df_tf_save.empty:
                        _df_tf_save["id"] = _df_tf_save["id"].apply(
                            lambda x: str(uuid.uuid4()) if (x is None or str(x) in ["", "None", "nan"]) else str(x)
                        )
                        _df_tf_save["fecha"] = pd.to_datetime(_df_tf_save["fecha"], errors="coerce").dt.strftime("%Y-%m-%d")
                        _df_tf_save["cuenta_origen_nombre"] = _df_tf_save["cuenta_origen_nombre"].fillna(_tf_ncp).astype(str)
                        _df_tf_save["cuenta_origen_id"] = _df_tf_save["cuenta_origen_nombre"].map(lambda n: _tf_ctas.get(str(n), "principal"))
                        _df_tf_save["monto_origen"] = pd.to_numeric(_df_tf_save["monto_origen"], errors="coerce").fillna(0.0)
                        _df_tf_save["moneda_monto"] = _df_tf_save["moneda_monto"].fillna("PEN").astype(str).str.upper()
                        _df_tf_save.loc[~_df_tf_save["moneda_monto"].isin(["PEN", "USD"]), "moneda_monto"] = "PEN"
                        _df_tf_save["tc_usd_pen"] = pd.to_numeric(_df_tf_save["tc_usd_pen"], errors="coerce").fillna(_tf_tc_default)
                        _df_tf_save["tc_usd_pen"] = _df_tf_save["tc_usd_pen"].apply(lambda x: x if x > 0 else _tf_tc_default)
                        _df_tf_save["monto_usd"] = _df_tf_save.apply(
                            lambda r: float(r["monto_origen"]) if r["moneda_monto"] == "USD" else float(r["monto_origen"]) / float(r["tc_usd_pen"]),
                            axis=1
                        )
                        _df_tf_save["monto_pen"] = _df_tf_save.apply(
                            lambda r: float(r["monto_origen"]) * float(r["tc_usd_pen"]) if r["moneda_monto"] == "USD" else float(r["monto_origen"]),
                            axis=1
                        )
                        _df_tf_save["comision_monto"] = pd.to_numeric(_df_tf_save["comision_monto"], errors="coerce").fillna(0.0)
                        _df_tf_save["comision_moneda"] = _df_tf_save["comision_moneda"].fillna("PEN").astype(str).str.upper()
                        _df_tf_save.loc[~_df_tf_save["comision_moneda"].isin(["PEN", "USD"]), "comision_moneda"] = "PEN"
                        _df_tf_save["comision_pen"] = _df_tf_save.apply(
                            lambda r: float(r["comision_monto"]) if r["comision_moneda"] == "PEN" else float(r["comision_monto"]) * float(r["tc_usd_pen"]),
                            axis=1
                        )
                        _df_tf_save["total_debitado_pen"] = _df_tf_save["monto_pen"] + _df_tf_save["comision_pen"]
                        _df_tf_save["descripcion"] = _df_tf_save["descripcion"].fillna("").astype(str)
                        _df_tf_save = _df_tf_save.dropna(subset=["fecha"]).sort_values("fecha", ascending=False)
                        st.session_state["ibkr_transferencias"] = _df_tf_save.to_dict("records")
                    else:
                        st.session_state["ibkr_transferencias"] = []

                    guardar("ibkr_transferencias")
                    st.success("✅ Transferencias a IBKR actualizadas.")
                    st.rerun()
        else:
            st.info("Todavía no hay cash agregado a IBKR desde cuentas locales.")

        # Recalcular cash después de normalizar transferencias y movimientos anteriores.
        _df_cash_ibkr = _normalizar_cash_ibkr()
        _total_cash_manual_ibkr_usd = float(_df_cash_ibkr["monto_usd"].sum()) if not _df_cash_ibkr.empty else 0.0
        _total_cash_transferencias_ibkr_usd = calcular_total_transferencias_ibkr_usd()
        _total_cash_ibkr_usd = float(_total_cash_manual_ibkr_usd + _total_cash_transferencias_ibkr_usd)
        st.markdown("#### 2️⃣ Comprar acciones o ETFs usando el cash IBKR")
        st.info(f"Cash IBKR disponible para invertir: **US$ {_total_cash_ibkr_usd:,.2f}**")
# Paso 2: compra de acciones o ETFs
        # ──────────────────────────────────────────────
        with st.form("form_inversion_ibkr_portfolio", clear_on_submit=True):
            st.markdown("##### ➕ Nueva compra usando cash IBKR")

            _iv1, _iv2, _iv3 = st.columns(3)

            with _iv1:
                _inv_fecha = st.date_input(
                    "📅 Fecha de compra",
                    value=hoy_peru,
                    key="fecha_compra_ibkr_portfolio"
                )
                _inv_ticker_raw = st.text_input(
                    "Ticker",
                    placeholder="Ej.: VOO, SCCO, GLD, CCOEY, MSFT",
                    key="ticker_compra_ibkr_portfolio"
                )
                _inv_broker = st.selectbox(
                    "Broker",
                    ["IBKR"],
                    key="broker_compra_ibkr_portfolio"
                )

            with _iv2:
                _inv_nombre_raw = st.text_input(
                    "Nombre del activo",
                    placeholder="Ej.: Vanguard S&P 500 ETF",
                    key="nombre_compra_ibkr_portfolio"
                )
                _inv_tipo = st.selectbox(
                    "Tipo",
                    ["ETF", "Accion", "ADR", "Fondo", "Otro"],
                    key="tipo_compra_ibkr_portfolio"
                )
                _inv_source_symbol_raw = st.text_input(
                    "Source symbol Yahoo",
                    placeholder="Déjalo vacío si es igual al ticker",
                    key="source_symbol_compra_ibkr_portfolio"
                )

            with _iv3:
                _inv_cantidad = st.number_input(
                    "Cantidad de acciones/participaciones",
                    min_value=0.0,
                    step=0.0001,
                    format="%.4f",
                    key="cantidad_compra_ibkr_portfolio"
                )
                _inv_monto_usd = st.number_input(
                    "Monto invertido total (USD)",
                    min_value=0.0,
                    step=10.0,
                    format="%.2f",
                    key="monto_compra_ibkr_portfolio"
                )
                _inv_moneda = st.selectbox(
                    "Moneda",
                    ["USD"],
                    key="moneda_compra_ibkr_portfolio"
                )
                st.caption("Esta compra se descontará automáticamente del cash IBKR para evitar doble conteo.")
                _inv_descontar_cash = True

            if st.form_submit_button("➕ Registrar compra IBKR", use_container_width=True, type="primary"):
                _inv_ticker = str(_inv_ticker_raw or "").upper().strip()
                _inv_nombre = str(_inv_nombre_raw or "").strip()
                _inv_source_symbol = str(_inv_source_symbol_raw or "").strip()

                if not _inv_ticker:
                    st.warning("Debes ingresar un ticker.")
                elif _inv_cantidad <= 0 or _inv_monto_usd <= 0:
                    st.warning("Debes ingresar una cantidad y un monto invertido mayor a cero.")
                elif _inv_monto_usd > (_total_cash_ibkr_usd + 0.01):
                    st.warning(
                        f"Cash IBKR insuficiente. Tienes US$ {_total_cash_ibkr_usd:,.2f} disponibles "
                        f"y la compra requiere US$ {_inv_monto_usd:,.2f}. Primero agrega cash en el paso 1."
                    )
                else:
                    _nombre_catalogo = obtener_nombre_instrumento_ibkr(_inv_ticker, _df_catalogo_ibkr)
                    _symbol_catalogo = obtener_source_symbol_ibkr(_inv_ticker, _df_catalogo_ibkr)

                    if not _inv_nombre:
                        _inv_nombre = _nombre_catalogo if _nombre_catalogo != _inv_ticker else _inv_ticker

                    if not _inv_source_symbol:
                        _inv_source_symbol = _symbol_catalogo if _symbol_catalogo else _inv_ticker

                    try:
                        upsert_instrumento_ibkr(
                            ticker=_inv_ticker,
                            nombre=_inv_nombre,
                            tipo=_inv_tipo,
                            moneda=_inv_moneda,
                            source_symbol=_inv_source_symbol,
                            fuente_precio="Yahoo Finance",
                            activo=True,
                        )
                    except Exception as _e:
                        st.warning(
                            "La compra se registrará, pero no se pudo actualizar el catálogo CSV "
                            f"para Airflow: {_e}"
                        )

                    _precio_promedio = _inv_monto_usd / _inv_cantidad

                    st.session_state["inversiones_ibkr"].append({
                        "id": str(uuid.uuid4()),
                        "fecha_compra": _inv_fecha.isoformat(),
                        "ticker": _inv_ticker,
                        "nombre": _inv_nombre,
                        "broker": _inv_broker,
                        "cantidad": float(_inv_cantidad),
                        "monto_invertido_usd": float(_inv_monto_usd),
                        "precio_promedio_compra_usd": float(_precio_promedio),
                        "moneda": _inv_moneda,
                    })

                    guardar("inversiones_ibkr")

                    if _inv_descontar_cash:
                        st.session_state["ibkr_cash_movimientos"].append({
                            "id": str(uuid.uuid4()),
                            "fecha": _inv_fecha.isoformat(),
                            "tipo_movimiento": "Retiro / uso de cash",
                            "descripcion": f"Uso de cash para compra {_inv_ticker}",
                            "monto_usd": -float(_inv_monto_usd),
                        })
                        guardar("ibkr_cash_movimientos")

                    st.success(
                        f"✅ Compra registrada. {_inv_ticker} quedó agregado al catálogo si era nuevo. "
                        "El monto invertido fue descontado automáticamente del cash IBKR. "
                        "La app intentará mostrar precio vía Yahoo; ejecuta ./run_daily_finance_dags.sh para consolidarlo por Airflow."
                    )
                    st.rerun()

        # ──────────────────────────────────────────────
        # Paso 3: historial y ajustes de cash IBKR
        # ──────────────────────────────────────────────
        with st.expander("🧾 3️⃣ Historial y ajustes de cash IBKR", expanded=False):
            st.caption(
                "Aquí puedes revisar el cash generado por transferencias, los descuentos automáticos por compras "
                "y hacer ajustes manuales solo si necesitas cuadrar con el saldo real de IBKR."
            )

            with st.form("form_cash_ibkr", clear_on_submit=True):
                _cash_c1, _cash_c2, _cash_c3 = st.columns(3)

                with _cash_c1:
                    _cash_fecha = st.date_input("Fecha", value=hoy_peru, key="fecha_cash_ibkr")
                    _cash_tipo = st.selectbox(
                        "Tipo de movimiento",
                        ["Depósito", "Retiro / uso de cash"],
                        key="tipo_cash_ibkr"
                    )

                with _cash_c2:
                    _cash_monto = st.number_input(
                        "Monto USD",
                        min_value=0.0,
                        step=10.0,
                        format="%.2f",
                        key="monto_cash_ibkr"
                    )

                with _cash_c3:
                    _cash_desc = st.text_input(
                        "Descripción",
                        placeholder="Ej.: Depósito IBKR, cash pendiente de invertir",
                        key="descripcion_cash_ibkr"
                    )

                if st.form_submit_button("➕ Registrar ajuste manual de cash", use_container_width=True, type="primary"):
                    if _cash_monto <= 0:
                        st.warning("Ingresa un monto mayor a cero.")
                    else:
                        _cash_monto_signed = float(_cash_monto)
                        if _cash_tipo == "Retiro / uso de cash":
                            _cash_monto_signed = -_cash_monto_signed

                        st.session_state["ibkr_cash_movimientos"].append({
                            "id": str(uuid.uuid4()),
                            "fecha": _cash_fecha.isoformat(),
                            "tipo_movimiento": _cash_tipo,
                            "descripcion": _cash_desc,
                            "monto_usd": _cash_monto_signed,
                        })
                        guardar("ibkr_cash_movimientos")
                        st.success("✅ Movimiento de cash IBKR registrado.")
                        st.rerun()

            _df_cash_ibkr = _normalizar_cash_ibkr()
            _total_cash_manual_ibkr_usd = float(_df_cash_ibkr["monto_usd"].sum()) if not _df_cash_ibkr.empty else 0.0
            _total_cash_transferencias_ibkr_usd = calcular_total_transferencias_ibkr_usd()
            _total_cash_ibkr_usd = float(_total_cash_manual_ibkr_usd + _total_cash_transferencias_ibkr_usd)
            st.metric("Cash disponible IBKR", f"US$ {_total_cash_ibkr_usd:,.2f}")
            st.caption(f"Transferencias a IBKR: US$ {_total_cash_transferencias_ibkr_usd:,.2f} | Movimientos manuales: US$ {_total_cash_manual_ibkr_usd:,.2f}")

            if not _df_cash_ibkr.empty:
                _df_cash_show = _df_cash_ibkr.copy()
                _df_cash_show["Eliminar"] = False

                _ed_cash = st.data_editor(
                    _df_cash_show,
                    use_container_width=True,
                    hide_index=True,
                    num_rows="dynamic",
                    height=min(38 * len(_df_cash_show) + 46, 280),
                    column_config={
                        "id": None,
                        "fecha": st.column_config.DateColumn("Fecha", required=True, width="small"),
                        "tipo_movimiento": st.column_config.SelectboxColumn(
                            "Tipo", options=["Depósito", "Retiro / uso de cash", "Ajuste"], width="medium"
                        ),
                        "descripcion": st.column_config.TextColumn("Descripción", width="large"),
                        "monto_usd": st.column_config.NumberColumn(
                            "Monto neto USD", step=10.0, format="US$ %.2f", width="small",
                            help="Depósitos positivos. Retiros o uso de cash negativos."
                        ),
                        "Eliminar": st.column_config.CheckboxColumn("🗑"),
                    },
                    key="editor_cash_ibkr"
                )

                if st.button("💾 Guardar cash IBKR", type="primary"):
                    _df_cash_save = _ed_cash.copy()
                    _df_cash_save = _df_cash_save[_df_cash_save["Eliminar"] == False].drop(columns=["Eliminar"]).copy()

                    if not _df_cash_save.empty:
                        _df_cash_save["id"] = _df_cash_save["id"].apply(
                            lambda x: str(uuid.uuid4()) if (x is None or str(x) in ["", "None", "nan"]) else str(x)
                        )
                        _df_cash_save["fecha"] = pd.to_datetime(
                            _df_cash_save["fecha"], errors="coerce"
                        ).dt.strftime("%Y-%m-%d")
                        _df_cash_save["tipo_movimiento"] = _df_cash_save["tipo_movimiento"].fillna("Ajuste").astype(str)
                        _df_cash_save["descripcion"] = _df_cash_save["descripcion"].fillna("").astype(str)
                        _df_cash_save["monto_usd"] = pd.to_numeric(
                            _df_cash_save["monto_usd"], errors="coerce"
                        ).fillna(0.0)
                        _df_cash_save = _df_cash_save.dropna(subset=["fecha"]).sort_values("fecha", ascending=False)
                        st.session_state["ibkr_cash_movimientos"] = _df_cash_save.to_dict("records")
                    else:
                        st.session_state["ibkr_cash_movimientos"] = []

                    guardar("ibkr_cash_movimientos")
                    st.success("✅ Cash IBKR actualizado.")
                    st.rerun()
            else:
                if _total_cash_transferencias_ibkr_usd != 0:
                    st.info("No hay movimientos manuales de cash. El cash actual proviene de transferencias a IBKR.")
                else:
                    st.info("No hay cash IBKR registrado.")

        # ──────────────────────────────────────────────
        # Compras registradas
        # ──────────────────────────────────────────────
        _df_inv = pd.DataFrame(st.session_state.get("inversiones_ibkr", []))

        if not _df_inv.empty:
            # Normalizar columnas para registros antiguos o filas editadas.
            for _col, _default in {
                "id": "",
                "fecha_compra": hoy_peru.isoformat(),
                "ticker": "VOO",
                "nombre": "",
                "broker": "IBKR",
                "cantidad": 0.0,
                "monto_invertido_usd": 0.0,
                "precio_promedio_compra_usd": 0.0,
                "moneda": "USD",
            }.items():
                if _col not in _df_inv.columns:
                    _df_inv[_col] = _default

            _df_inv["id"] = _df_inv["id"].apply(
                lambda x: str(uuid.uuid4()) if (x is None or str(x) in ["", "None", "nan"]) else str(x)
            )
            _df_inv["fecha_compra"] = pd.to_datetime(_df_inv["fecha_compra"], errors="coerce").dt.date
            _df_inv["ticker"] = _df_inv["ticker"].fillna("VOO").astype(str).str.upper().str.strip()
            _df_inv["nombre"] = _df_inv.apply(
                lambda r: str(r["nombre"]).strip()
                if str(r.get("nombre", "")).strip() not in ["", "None", "nan"]
                else obtener_nombre_instrumento_ibkr(r["ticker"], _df_catalogo_ibkr),
                axis=1
            )
            _df_inv["broker"] = _df_inv["broker"].fillna("IBKR").astype(str)
            _df_inv["moneda"] = _df_inv["moneda"].fillna("USD").astype(str)
            _df_inv["cantidad"] = pd.to_numeric(_df_inv["cantidad"], errors="coerce").fillna(0.0)
            _df_inv["monto_invertido_usd"] = pd.to_numeric(_df_inv["monto_invertido_usd"], errors="coerce").fillna(0.0)

            _df_inv["precio_promedio_compra_usd"] = _df_inv.apply(
                lambda r: (r["monto_invertido_usd"] / r["cantidad"]) if r["cantidad"] > 0 else 0.0,
                axis=1
            )

            _df_inv = _df_inv.sort_values("fecha_compra", ascending=False).reset_index(drop=True)

            st.markdown("#### 📋 Compras registradas")
            st.caption(
                "Puedes editar ticker, cantidad o monto. El precio promedio se recalcula al guardar. "
                "Si agregas un ticker nuevo, la app lo agrega automáticamente al catálogo."
            )

            _df_inv_show = _df_inv.copy()
            _df_inv_show["Eliminar"] = False

            _ed_inv = st.data_editor(
                _df_inv_show,
                use_container_width=True,
                hide_index=True,
                num_rows="dynamic",
                height=min(38 * len(_df_inv_show) + 46, 360),
                column_config={
                    "id": None,
                    "fecha_compra": st.column_config.DateColumn("📅 Fecha compra", required=True, width="small"),
                    "ticker": st.column_config.TextColumn("Ticker", required=True, width="small"),
                    "nombre": st.column_config.TextColumn("Nombre", width="medium"),
                    "broker": st.column_config.SelectboxColumn("Broker", options=["IBKR"], required=True, width="small"),
                    "cantidad": st.column_config.NumberColumn("Cantidad", min_value=0.0, step=0.0001, format="%.4f", width="small"),
                    "monto_invertido_usd": st.column_config.NumberColumn("Invertido USD", min_value=0.0, step=10.0, format="US$ %.2f", width="small"),
                    "precio_promedio_compra_usd": st.column_config.NumberColumn("Precio promedio USD", disabled=True, format="US$ %.2f", width="small"),
                    "moneda": st.column_config.SelectboxColumn("Moneda", options=["USD"], width="small"),
                    "Eliminar": st.column_config.CheckboxColumn("🗑"),
                },
                key="editor_inversiones_ibkr"
            )

            if st.button("💾 Guardar cambios — Portafolio IBKR", type="primary"):
                _df_save = _ed_inv.copy()
                _df_save = _df_save[_df_save["Eliminar"] == False].drop(columns=["Eliminar"]).copy()

                if not _df_save.empty:
                    _df_save["id"] = _df_save["id"].apply(
                        lambda x: str(uuid.uuid4()) if (x is None or str(x) in ["", "None", "nan"]) else str(x)
                    )
                    _df_save["fecha_compra"] = pd.to_datetime(_df_save["fecha_compra"], errors="coerce").dt.strftime("%Y-%m-%d")
                    _df_save["ticker"] = _df_save["ticker"].fillna("").astype(str).str.upper().str.strip()
                    _df_save["nombre"] = _df_save.apply(
                        lambda r: str(r["nombre"]).strip()
                        if str(r.get("nombre", "")).strip() not in ["", "None", "nan"]
                        else obtener_nombre_instrumento_ibkr(r["ticker"], _df_catalogo_ibkr),
                        axis=1
                    )
                    _df_save["broker"] = _df_save["broker"].fillna("IBKR").astype(str)
                    _df_save["moneda"] = _df_save["moneda"].fillna("USD").astype(str).str.upper()
                    _df_save["cantidad"] = pd.to_numeric(_df_save["cantidad"], errors="coerce").fillna(0.0)
                    _df_save["monto_invertido_usd"] = pd.to_numeric(
                        _df_save["monto_invertido_usd"], errors="coerce"
                    ).fillna(0.0)
                    _df_save["precio_promedio_compra_usd"] = _df_save.apply(
                        lambda r: (r["monto_invertido_usd"] / r["cantidad"]) if r["cantidad"] > 0 else 0.0,
                        axis=1
                    )

                    _df_save = _df_save.dropna(subset=["fecha_compra"])
                    _df_save = _df_save[
                        (_df_save["ticker"] != "") &
                        (_df_save["cantidad"] > 0) &
                        (_df_save["monto_invertido_usd"] > 0)
                    ].copy()

                    # Asegurar que todo ticker comprado exista en el catálogo, sin sobreescribir
                    # tipo/source_symbol si ya estaban correctamente definidos.
                    for _, _row_inv in _df_save.iterrows():
                        try:
                            _ticker_tmp = str(_row_inv["ticker"]).upper().strip()
                            _cat_match = _df_catalogo_ibkr[
                                _df_catalogo_ibkr["ticker"].astype(str).str.upper().str.strip() == _ticker_tmp
                            ]

                            if not _cat_match.empty:
                                _tipo_tmp = str(_cat_match.iloc[0].get("tipo", "Accion"))
                                _source_tmp = str(_cat_match.iloc[0].get("source_symbol", _ticker_tmp)).strip() or _ticker_tmp
                                _fuente_tmp = str(_cat_match.iloc[0].get("fuente_precio", "Yahoo Finance"))
                            else:
                                _tipo_tmp = "Accion"
                                _source_tmp = _ticker_tmp
                                _fuente_tmp = "Yahoo Finance"

                            upsert_instrumento_ibkr(
                                ticker=_ticker_tmp,
                                nombre=_row_inv["nombre"],
                                tipo=_tipo_tmp,
                                moneda=_row_inv["moneda"],
                                source_symbol=_source_tmp,
                                fuente_precio=_fuente_tmp,
                                activo=True,
                            )
                        except Exception:
                            pass

                    st.session_state["inversiones_ibkr"] = _df_save.sort_values(
                        "fecha_compra", ascending=False
                    ).to_dict("records")
                else:
                    st.session_state["inversiones_ibkr"] = []

                guardar("inversiones_ibkr")
                st.success("✅ Portafolio IBKR actualizado.")
                st.rerun()

            # ──────────────────────────────────────────────
            # Resumen por ticker y valorización
            # ──────────────────────────────────────────────
            st.markdown("#### 📊 Resumen del portafolio")

            _df_pos = (
                _df_inv.groupby("ticker", as_index=False)
                .agg(
                    nombre=("nombre", "last"),
                    cantidad_total=("cantidad", "sum"),
                    invertido_total_usd=("monto_invertido_usd", "sum"),
                )
            )
            _df_pos["precio_promedio_compra_usd"] = _df_pos.apply(
                lambda r: (r["invertido_total_usd"] / r["cantidad_total"]) if r["cantidad_total"] > 0 else 0.0,
                axis=1
            )

            # Autodetección: todo ticker comprado se agrega al catálogo sin intervención manual.
            try:
                _df_catalogo_ibkr, _tickers_auto_catalogo = sincronizar_catalogo_desde_compras_ibkr(
                    st.session_state.get("inversiones_ibkr", []),
                    _df_catalogo_ibkr,
                )
                if _tickers_auto_catalogo:
                    st.info(
                        "Tickers agregados automáticamente al catálogo IBKR: "
                        + ", ".join(_tickers_auto_catalogo)
                        + ". Airflow los tomará en la siguiente corrida."
                    )
            except Exception as _e:
                st.warning(f"No se pudo sincronizar automáticamente el catálogo IBKR: {_e}")

            # Fallback visual: si Airflow aún no tiene precio de un ticker nuevo,
            # la app consulta Yahoo Finance en vivo para mostrar valorización inmediata.
            _df_precios_ibkr, _tickers_fallback_yahoo = completar_precios_faltantes_con_yahoo(
                _df_precios_ibkr,
                _df_pos["ticker"].tolist(),
                _df_catalogo_ibkr,
            )

            if _tickers_fallback_yahoo:
                st.info(
                    "Precios consultados directamente desde Yahoo Finance mientras Airflow se actualiza: "
                    + ", ".join(_tickers_fallback_yahoo)
                    + ". Para consolidarlos en CSV, ejecuta ./run_daily_finance_dags.sh."
                )

            if not _df_precios_ibkr.empty:
                _price_cols = [
                    c for c in [
                        "ticker",
                        "precio_actual_usd",
                        "fecha_precio",
                        "hora_precio",
                        "fuente_precio",
                        "exchange",
                        "updated_at_lima",
                        "archivo",
                    ]
                    if c in _df_precios_ibkr.columns
                ]
                _df_resumen = _df_pos.merge(_df_precios_ibkr[_price_cols], on="ticker", how="left")
            else:
                _df_resumen = _df_pos.copy()
                _df_resumen["precio_actual_usd"] = pd.NA
                _df_resumen["fecha_precio"] = ""
                _df_resumen["hora_precio"] = ""
                _df_resumen["fuente_precio"] = ""
                _df_resumen["exchange"] = ""
                _df_resumen["updated_at_lima"] = ""
                _df_resumen["archivo"] = ""

            _df_resumen["precio_actual_usd"] = pd.to_numeric(
                _df_resumen["precio_actual_usd"], errors="coerce"
            )
            _df_resumen["tiene_precio"] = _df_resumen["precio_actual_usd"].notna() & (_df_resumen["precio_actual_usd"] > 0)
            _df_resumen["valor_actual_usd"] = _df_resumen["cantidad_total"] * _df_resumen["precio_actual_usd"].fillna(0.0)
            _df_resumen["ganancia_usd"] = (
                _df_resumen["valor_actual_usd"] - _df_resumen["invertido_total_usd"]
            ).where(_df_resumen["tiene_precio"], 0.0)
            _df_resumen["rendimiento_pct"] = _df_resumen.apply(
                lambda r: (r["ganancia_usd"] / r["invertido_total_usd"] * 100)
                if r["tiene_precio"] and r["invertido_total_usd"] > 0
                else 0.0,
                axis=1
            )
            _df_resumen["valor_actual_pen"] = _df_resumen["valor_actual_usd"] * _tc_inv
            _df_resumen["ganancia_pen"] = _df_resumen["ganancia_usd"] * _tc_inv
            def _estado_precio_ibkr(row):
                if not row.get("tiene_precio", False):
                    return "Sin precio"
                fuente = str(row.get("fuente_precio", ""))
                if "fallback" in fuente.lower() or "app" in fuente.lower():
                    return "OK Yahoo app"
                return "OK Airflow"

            _df_resumen["estado_precio"] = _df_resumen.apply(_estado_precio_ibkr, axis=1)

            _total_invertido_usd = float(_df_resumen["invertido_total_usd"].sum())
            _total_invertido_con_precio_usd = float(_df_resumen.loc[_df_resumen["tiene_precio"], "invertido_total_usd"].sum())
            _total_valor_activos_usd = float(_df_resumen.loc[_df_resumen["tiene_precio"], "valor_actual_usd"].sum())
            _total_cash_manual_ibkr_usd = float(_df_cash_ibkr["monto_usd"].sum()) if not _df_cash_ibkr.empty else 0.0
            _total_cash_transferencias_ibkr_usd = calcular_total_transferencias_ibkr_usd()
            _total_cash_ibkr_usd = float(_total_cash_manual_ibkr_usd + _total_cash_transferencias_ibkr_usd)
            _total_valor_actual_usd = _total_valor_activos_usd + _total_cash_ibkr_usd
            _total_ganancia_usd = _total_valor_activos_usd - _total_invertido_con_precio_usd
            _total_rendimiento_pct = (
                _total_ganancia_usd / _total_invertido_con_precio_usd * 100
                if _total_invertido_con_precio_usd > 0
                else 0.0
            )

            _m1, _m2, _m3, _m4, _m5 = st.columns(5)
            _m1.metric("Invertido activos", f"US$ {_total_invertido_usd:,.2f}")
            _m2.metric("Cash IBKR", f"US$ {_total_cash_ibkr_usd:,.2f}")
            _m3.metric("Valor total IBKR", f"US$ {_total_valor_actual_usd:,.2f}")
            _m4.metric("Ganancia/Pérdida activos", f"US$ {_total_ganancia_usd:,.2f}")
            _m5.metric("Rend. activos", f"{_total_rendimiento_pct:,.2f}%")

            st.caption(
                f"Valor total IBKR estimado en soles: S/ {_total_valor_actual_usd * _tc_inv:,.0f} | "
                f"Cash: S/ {_total_cash_ibkr_usd * _tc_inv:,.0f} | "
                f"Ganancia/Pérdida de activos: S/ {_total_ganancia_usd * _tc_inv:,.0f} | "
                f"TC usado: {_tc_inv:.4f}"
            )

            if _df_precios_ibkr.empty:
                st.info(
                    "No se encontró data/market_prices_portfolio.csv ni precios fallback. "
                    "Ejecuta ./run_daily_finance_dags.sh para actualizar precios desde Airflow."
                )
            else:
                _ultima_actualizacion = ""
                if "updated_at_lima" in _df_precios_ibkr.columns:
                    _vals = _df_precios_ibkr["updated_at_lima"].dropna().astype(str)
                    if not _vals.empty:
                        _ultima_actualizacion = _vals.iloc[-1]

                _fuentes_usadas = []
                if "fuente_precio" in _df_precios_ibkr.columns:
                    _fuentes_usadas = sorted(_df_precios_ibkr["fuente_precio"].dropna().astype(str).unique().tolist())

                st.caption(
                    "Precios desde Airflow y/o fallback Yahoo: data/market_prices_portfolio.csv"
                    + (f" | Fuentes: {', '.join(_fuentes_usadas)}" if _fuentes_usadas else "")
                    + (f" | Última actualización: {_ultima_actualizacion}" if _ultima_actualizacion else "")
                )

            _faltantes = _df_resumen.loc[~_df_resumen["tiene_precio"], "ticker"].tolist()
            if _faltantes:
                st.warning(
                    "Hay tickers sin precio disponible: "
                    + ", ".join(_faltantes)
                    + ". Si Yahoo Finance usa un símbolo distinto, edita source_symbol en el catálogo."
                )

            _df_tabla = _df_resumen.copy()
            if _total_cash_ibkr_usd != 0:
                _cash_row = {
                    "ticker": "CASH",
                    "nombre": "Cash disponible IBKR",
                    "cantidad_total": _total_cash_ibkr_usd,
                    "invertido_total_usd": _total_cash_ibkr_usd,
                    "precio_promedio_compra_usd": 1.0,
                    "precio_actual_usd": 1.0,
                    "valor_actual_usd": _total_cash_ibkr_usd,
                    "ganancia_usd": 0.0,
                    "rendimiento_pct": 0.0,
                    "valor_actual_pen": _total_cash_ibkr_usd * _tc_inv,
                    "ganancia_pen": 0.0,
                    "fecha_precio": "",
                    "hora_precio": "",
                    "exchange": "IBKR",
                    "fuente_precio": "Cash",
                    "updated_at_lima": "",
                    "archivo": "",
                    "tiene_precio": True,
                    "estado_precio": "Cash",
                }
                _df_tabla = pd.concat([_df_tabla, pd.DataFrame([_cash_row])], ignore_index=True)

            _df_tabla = _df_tabla.sort_values("valor_actual_usd", ascending=False)

            st.dataframe(
                _df_tabla,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "ticker": st.column_config.TextColumn("Ticker", width="small"),
                    "nombre": st.column_config.TextColumn("Nombre", width="medium"),
                    "cantidad_total": st.column_config.NumberColumn("Cantidad", format="%.4f", width="small"),
                    "invertido_total_usd": st.column_config.NumberColumn("Invertido USD", format="US$ %.2f", width="small"),
                    "precio_promedio_compra_usd": st.column_config.NumberColumn("Precio prom. compra", format="US$ %.2f", width="small"),
                    "precio_actual_usd": st.column_config.NumberColumn("Precio actual", format="US$ %.2f", width="small"),
                    "valor_actual_usd": st.column_config.NumberColumn("Valor actual USD", format="US$ %.2f", width="small"),
                    "ganancia_usd": st.column_config.NumberColumn("Ganancia USD", format="US$ %.2f", width="small"),
                    "rendimiento_pct": st.column_config.NumberColumn("Rend. %", format="%.2f%%", width="small"),
                    "valor_actual_pen": st.column_config.NumberColumn("Valor PEN", format="S/ %.0f", width="small"),
                    "ganancia_pen": st.column_config.NumberColumn("Ganancia PEN", format="S/ %.0f", width="small"),
                    "fecha_precio": st.column_config.TextColumn("Fecha precio", width="small"),
                    "hora_precio": st.column_config.TextColumn("Hora precio", width="small"),
                    "exchange": st.column_config.TextColumn("Exchange", width="small"),
                    "fuente_precio": st.column_config.TextColumn("Fuente", width="small"),
                    "updated_at_lima": st.column_config.TextColumn("Actualizado", width="medium"),
                    "archivo": None,
                    "tiene_precio": None,
                    "estado_precio": st.column_config.TextColumn("Estado", width="medium"),
                }
            )

            # ──────────────────────────────────────────────
            # Gráficas simples
            # ──────────────────────────────────────────────
            _df_graf = _df_resumen[_df_resumen["tiene_precio"]].copy()

            if not _df_graf.empty:
                st.markdown("#### 📈 Gráficas rápidas")

                _fig_gain = px.bar(
                    _df_graf.sort_values("ganancia_usd", ascending=False),
                    x="ticker",
                    y="ganancia_usd",
                    text="ganancia_usd",
                    title="Ganancia / Pérdida por ticker (USD)",
                    labels={"ticker": "Ticker", "ganancia_usd": "Ganancia/Pérdida USD"},
                )
                _fig_gain.update_traces(texttemplate="US$ %{text:,.2f}", textposition="outside")
                _fig_gain.update_layout(yaxis_tickprefix="US$ ", uniformtext_minsize=8, uniformtext_mode="hide")
                st.plotly_chart(_fig_gain, use_container_width=True)

                _df_dist = _df_graf[_df_graf["valor_actual_usd"] > 0].copy()
                if _total_cash_ibkr_usd > 0:
                    _df_dist = pd.concat([
                        _df_dist,
                        pd.DataFrame([{
                            "ticker": "CASH",
                            "valor_actual_usd": _total_cash_ibkr_usd,
                        }])
                    ], ignore_index=True)

                if not _df_dist.empty:
                    _fig_dist = px.pie(
                        _df_dist,
                        names="ticker",
                        values="valor_actual_usd",
                        hole=0.45,
                        title="Distribución del portafolio por valor actual",
                    )
                    st.plotly_chart(_fig_dist, use_container_width=True)

        else:
            if _total_cash_ibkr_usd != 0:
                st.markdown("#### 📊 Resumen del portafolio")
                _valor_total_cash_pen = _total_cash_ibkr_usd * _tc_inv
                _c1, _c2 = st.columns(2)
                _c1.metric("Cash IBKR", f"US$ {_total_cash_ibkr_usd:,.2f}")
                _c2.metric("Valor total IBKR", f"US$ {_total_cash_ibkr_usd:,.2f}")
                st.caption(
                    f"Valor total estimado en soles: S/ {_valor_total_cash_pen:,.0f} | "
                    f"TC usado: {_tc_inv:.4f}"
                )
                st.dataframe(
                    pd.DataFrame([{
                        "ticker": "CASH",
                        "nombre": "Cash disponible IBKR",
                        "valor_actual_usd": _total_cash_ibkr_usd,
                        "valor_actual_pen": _valor_total_cash_pen,
                    }]),
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "ticker": st.column_config.TextColumn("Ticker", width="small"),
                        "nombre": st.column_config.TextColumn("Nombre", width="medium"),
                        "valor_actual_usd": st.column_config.NumberColumn("Valor actual USD", format="US$ %.2f"),
                        "valor_actual_pen": st.column_config.NumberColumn("Valor PEN", format="S/ %.0f"),
                    }
                )
            else:
                st.info("Aún no hay compras ni cash registrados en IBKR. Registra tu primera compra o movimiento de cash arriba.")






# Catálogo técnico de instrumentos
        # ──────────────────────────────────────────────
        with st.expander("⚙️ Catálogo técnico IBKR / Airflow", expanded=False):
            st.caption(
                "Este catálogo alimenta al DAG market_prices_ibkr_portfolio. Normalmente se actualiza solo cuando registras una compra nueva. "
                "Edita source_symbol solo si Yahoo Finance usa un símbolo especial."
            )

            _df_catalogo_show = _df_catalogo_ibkr.copy()
            _ed_catalogo = st.data_editor(
                _df_catalogo_show,
                use_container_width=True,
                hide_index=True,
                num_rows="dynamic",
                height=min(38 * max(len(_df_catalogo_show), 1) + 46, 320),
                column_config={
                    "ticker": st.column_config.TextColumn("Ticker", required=True, width="small"),
                    "nombre": st.column_config.TextColumn("Nombre", width="large"),
                    "tipo": st.column_config.SelectboxColumn(
                        "Tipo",
                        options=["ETF", "Accion", "ADR", "Fondo", "Otro"],
                        width="small",
                    ),
                    "moneda": st.column_config.SelectboxColumn("Moneda", options=["USD"], width="small"),
                    "source_symbol": st.column_config.TextColumn(
                        "Source symbol",
                        width="small",
                        help="Símbolo usado por Yahoo Finance. Ej.: VOO, SCCO, GLD, CCOEY, 7203.T, ticker.L."
                    ),
                    "fuente_precio": st.column_config.SelectboxColumn(
                        "Fuente precio",
                        options=["Yahoo Finance"],
                        width="medium",
                    ),
                    "activo": st.column_config.CheckboxColumn(
                        "Activo",
                        help="Si está activo, Airflow intentará actualizar su precio."
                    ),
                },
                key="editor_catalogo_ibkr"
            )

            if st.button("💾 Guardar catálogo IBKR", type="primary"):
                try:
                    _df_catalogo_guardado = guardar_catalogo_ibkr(_ed_catalogo)
                    st.success("✅ Catálogo guardado. En la próxima corrida, Airflow leerá estos tickers.")
                    st.rerun()
                except Exception as _e:
                    st.error(f"No se pudo guardar el catálogo: {_e}")

        # ──────────────────────────────────────────────
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

ing_punt     = pd.Series(0.0, index=fechas)
ing_punt_sec = {}   # keyed by cuenta_id for secondary-account reimbursements
for _, r in df_ing_punt.iterrows():
    f = pd.to_datetime(r["fecha"])
    _cta_d = r.get("cuenta_destino_id", "principal") if hasattr(r, "get") else "principal"
    if not _cta_d or str(_cta_d) in ["principal", "", "None", "nan"]:
        if f in ing_punt.index:
            ing_punt.loc[f] += r["monto"]
    else:
        if _cta_d not in ing_punt_sec:
            ing_punt_sec[_cta_d] = pd.Series(0.0, index=fechas)
        if f in ing_punt_sec[_cta_d].index:
            ing_punt_sec[_cta_d].loc[f] += r["monto"]

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

# Tipo de cambio default usado en simulaciones y conversiones USD/PEN.
# Se usa el valor guardado en configuración, que puede venir de BCRP, BCP, API internacional o ajuste manual.
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

# ── Reembolsables con tarjeta: agregar al ciclo de pago ──────
for _r in st.session_state.get("gastos_reembolsables", []):
    if _r.get("medio_pago") != "Tarjeta de credito":
        continue
    _tarj_id_r = _r.get("tarjeta_id", "")
    _f_r = pd.to_datetime(_r.get("fecha"), errors="coerce")
    if pd.isna(_f_r) or not _tarj_id_r:
        continue
    # Buscar la tarjeta para obtener dia_cierre y dia_pago
    _t_match = next((t for t in st.session_state["tarjetas"] if t["id"] == _tarj_id_r), None)
    if _t_match is None:
        continue
    _, _cierre_r = obtener_ciclo_tarjeta(_f_r, int(_t_match["dia_cierre"]))
    _fecha_pago_r = (pd.Timestamp(_cierre_r) + pd.DateOffset(months=1)).replace(day=int(_t_match["dia_pago"]))
    _anio_mes_r = _fecha_pago_r.strftime("%Y-%m")
    _tc_r = _tc_lookup.get((_tarj_id_r, _anio_mes_r), _tc_default)
    _mon_r = _r.get("moneda", "PEN")
    _monto_pen_r = float(_r["monto"]) * _tc_r if _mon_r == "USD" else float(_r["monto"])
    # Cuenta de pago de la tarjeta (igual que gastos normales)
    _t_pago_r = next(
        (t.get("cuenta_pago", "principal") for t in st.session_state["tarjetas"] if t["id"] == _tarj_id_r),
        "principal"
    )
    if _t_pago_r not in egresos_tarjeta_por_cuenta:
        egresos_tarjeta_por_cuenta[_t_pago_r] = pd.Series(0.0, index=fechas)
    if _fecha_pago_r in egresos_tarjeta_por_cuenta[_t_pago_r].index:
        egresos_tarjeta_por_cuenta[_t_pago_r].loc[_fecha_pago_r] += _monto_pen_r
    else:
        _idx_nearest = int((egresos_tarjeta_por_cuenta[_t_pago_r].index - _fecha_pago_r).abs().argmin())
        egresos_tarjeta_por_cuenta[_t_pago_r].iloc[_idx_nearest] += _monto_pen_r

# egresos de cuenta principal (para saldo principal y gráfico)
egresos_tarjeta = egresos_tarjeta_por_cuenta.get("principal", pd.Series(0.0, index=fechas))

# ── Gastos reembolsables: impacto NETO en cuenta ─────────────
# Para cada reembolsable:
#   - Resta en la fecha del gasto (o fecha de pago para crédito)
#   - Suma de vuelta en fecha_esperada si está PENDIENTE
#     (si ya está reembolsado, la suma viene de ingresos_puntuales)
_g_remb = pd.Series(0.0, index=fechas)

def _nearest(series, fecha):
    """Agrega monto a la fecha más cercana disponible en el índice."""
    f = pd.Timestamp(fecha)
    if f in series.index:
        return f
    if len(series.index) == 0:
        return None
    return series.index[int((series.index - f).abs().argmin())]

for _r in st.session_state.get("gastos_reembolsables", []):
    _f = pd.to_datetime(_r.get("fecha"), errors="coerce")
    if pd.isna(_f):
        continue
    _monto_r     = float(_r.get("monto", 0))
    _mon_r       = _r.get("moneda", "PEN")
    _monto_pen_r = _monto_r * _tc_default if _mon_r == "USD" else _monto_r
    _estado_r    = _r.get("estado", "pendiente")

    # ── Fecha en que sale el dinero (solo débito) ────────────
    # Crédito ya va por egresos_tarjeta_por_cuenta (ciclo de pago real)
    if _r.get("medio_pago", "Debito") == "Debito":
        _fs = _nearest(_g_remb, _f)
        if _fs is not None:
            _g_remb.loc[_fs] += _monto_pen_r


    # ── Fecha en que vuelve el dinero (solo débito pendiente) ───
    # Crédito: el reembolso va a la cuenta de ahorro seleccionada → se registra
    # como ingreso puntual al marcar reembolsado.
    if _estado_r == "pendiente" and _r.get("medio_pago", "Debito") == "Debito":
        _f_esp = pd.to_datetime(_r.get("fecha_esperada"), errors="coerce")
        if not pd.isna(_f_esp):
            _fe = _nearest(_g_remb, _f_esp)
            if _fe is not None:
                _g_remb.loc[_fe] -= _monto_pen_r   # resta negativa = suma

# ── Simulaciones de préstamo activas (por cuenta) ─────────────
# Cada operación se registra en la cuenta correcta:
#   _ing_prestamos_cta[cta_id]  → ingreso del préstamo en esa cuenta
#   _g_prestamos_cta[cta_id]    → pago del bien + cuotas desde esa cuenta

def _add_to(series, fecha, monto):
    f = pd.Timestamp(fecha)
    if len(series.index) == 0:
        return
    if f < series.index[0] or f > series.index[-1]:
        return
    if f in series.index:
        series.loc[f] += monto
    else:
        _idx = int((series.index.astype("int64") - f.value).abs().argmin())
        series.iloc[_idx] += monto

def _get_or_create(dct, key):
    if key not in dct:
        dct[key] = pd.Series(0.0, index=fechas)
    return dct[key]

_ing_prestamos_cta = {}  # cta_id -> Series
_g_prestamos_cta   = {}  # cta_id -> Series

for _sim in st.session_state.get("simulaciones_prestamo", []):
    if not _sim.get("activo", True):
        continue
    _f_desembolso = pd.to_datetime(_sim.get("fecha_desembolso", _sim.get("fecha_inicio", hoy_peru)))
    _f_compra     = pd.to_datetime(_sim.get("fecha_compra",     _sim.get("fecha_inicio", hoy_peru)))
    _f_primera    = pd.to_datetime(_sim.get("fecha_primera_cuota", _sim.get("fecha_inicio", hoy_peru)))
    _f_fin_s      = pd.to_datetime(_sim["fecha_fin"])
    _dia_cuota_s  = int(_sim.get("dia_cuota", 5))
    _monto_pre_s  = float(_sim["monto_prestamo"])
    _monto_tot_s  = float(_sim.get("monto_total", _monto_pre_s))
    _cuota_s      = float(_sim["cuota"])

    # Cuenta que RECIBE el préstamo
    _cta_desembolso = _sim.get("cta_desembolso_id", "principal") or "principal"
    # Cuenta que PAGA el bien
    _cta_bien = _sim.get("cta_pago_bien_id", "principal") or "principal"
    # Cuenta/tarjeta que PAGA las cuotas
    _medio_cuota = _sim.get("medio_id", "principal") or "principal"
    _tipo_cuota  = _sim.get("medio_tipo", "cuenta")

    # 1. Desembolso → ingreso en la cuenta seleccionada
    _add_to(_get_or_create(_ing_prestamos_cta, _cta_desembolso), _f_desembolso, _monto_pre_s)

    # 2. Pago del bien → gasto desde la cuenta seleccionada
    _add_to(_get_or_create(_g_prestamos_cta, _cta_bien), _f_compra, _monto_tot_s)

    # 3. Cuotas mensuales → gasto desde cuenta/tarjeta seleccionada
    _cta_cuota_id  = _medio_cuota if _tipo_cuota == "cuenta" else "principal"
    _monto_cierre  = float(_sim.get("monto_cierre", 0) or 0)
    _fecha_cierre_s = pd.to_datetime(_sim["fecha_cierre"]) if _sim.get("fecha_cierre") and _monto_cierre > 0 else None
    # Límite real: la cuota más temprana entre fecha_fin y fecha_cierre
    _f_limite = min(_f_fin_s, _fecha_cierre_s) if _fecha_cierre_s else _f_fin_s

    _cur_s = _f_primera.replace(day=min(_dia_cuota_s, 28))
    while _cur_s <= _f_limite:
        _add_to(_get_or_create(_g_prestamos_cta, _cta_cuota_id), _cur_s, _cuota_s)
        try:
            _cur_s = (_cur_s + pd.DateOffset(months=1)).replace(day=min(_dia_cuota_s, 28))
        except Exception:
            _cur_s = _cur_s + pd.DateOffset(months=1)

    # Pago de cierre anticipado (si existe) en la misma cuenta de cuotas
    if _fecha_cierre_s and _monto_cierre > 0:
        _add_to(_get_or_create(_g_prestamos_cta, _cta_cuota_id), _fecha_cierre_s, _monto_cierre)

# Totales para cuenta principal
_ing_prestamos_principal = _ing_prestamos_cta.get("principal", pd.Series(0.0, index=fechas))
_g_prestamos_principal   = _g_prestamos_cta.get("principal",   pd.Series(0.0, index=fechas))

saldo = (
    ahorro_inicial
    + ing_rec.cumsum()
    + ing_punt.cumsum()
    + _ing_prestamos_principal.cumsum()
    - g_diarios_principal.cumsum()
    - g_fijos.cumsum()
    - egresos_tarjeta.cumsum()
    - _g_remb.cumsum()
    - _g_prestamos_principal.cumsum()
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

# Transferencias desde cuenta principal hacia IBKR.
# El monto debitado incluye el monto enviado y la comisión equivalente en soles.
for _t_ibkr in st.session_state.get("ibkr_transferencias", []):
    _f_ibkr = pd.to_datetime(_t_ibkr.get("fecha"), errors="coerce")
    if pd.notna(_f_ibkr) and _f_ibkr in serie_cuenta_principal.index:
        if str(_t_ibkr.get("cuenta_origen_id", "")) == "principal":
            serie_cuenta_principal.loc[_f_ibkr:] -= calcular_total_debitado_transferencia_ibkr(_t_ibkr)

# ==================================================
# SALDOS DE CUENTAS DE AHORRO SECUNDARIAS
# ==================================================

# Valor total actual del portafolio IBKR para integrarlo en saldos generales.
# Reemplaza cualquier cuenta secundaria llamada IBKR para evitar doble conteo.
_resumen_ibkr_global = calcular_resumen_ibkr_global(_tc_default)
_valor_total_ibkr_pen = float(_resumen_ibkr_global.get("total_pen", 0.0))
_hay_ibkr_global = bool(_resumen_ibkr_global.get("hay_datos", False))

saldos_sec = {}
_cuentas_ibkr_reemplazadas = []

for cuenta in st.session_state["cuentas_ahorro"]:
    nombre_cuenta = cuenta["nombre"]

    if "IBKR" in str(nombre_cuenta).upper():
        _cuentas_ibkr_reemplazadas.append(str(nombre_cuenta))
        continue

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

    # Transferencias desde esta cuenta secundaria hacia IBKR
    for _t_ibkr in st.session_state.get("ibkr_transferencias", []):
        _f_ibkr = pd.to_datetime(_t_ibkr.get("fecha"), errors="coerce")

        if pd.notna(_f_ibkr) and _f_ibkr in serie_sec.index:
            if str(_t_ibkr.get("cuenta_origen_id", "")) == str(cuenta["id"]):
                serie_sec.loc[_f_ibkr:] -= calcular_total_debitado_transferencia_ibkr(_t_ibkr)

    # Pagos de tarjeta de crédito desde esta cuenta secundaria
    egr_tc_sec = egresos_tarjeta_por_cuenta.get(cuenta["id"], pd.Series(0.0, index=fechas))
    serie_sec = serie_sec - egr_tc_sec.cumsum()


    # Reembolsos recibidos en esta cuenta secundaria
    if cuenta["id"] in ing_punt_sec:
        serie_sec = serie_sec + ing_punt_sec[cuenta["id"]].cumsum()

    # Préstamos: desembolso recibido y pagos del bien/cuotas desde esta cuenta
    if cuenta["id"] in _ing_prestamos_cta:
        serie_sec = serie_sec + _ing_prestamos_cta[cuenta["id"]].cumsum()
    if cuenta["id"] in _g_prestamos_cta:
        serie_sec = serie_sec - _g_prestamos_cta[cuenta["id"]].cumsum()
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

# Agrega IBKR como cuenta dinámica si existe portafolio o cash registrado.
# El valor se calcula con precios actuales y TC configurado. Se mantiene constante en la línea temporal
# porque representa el valor de mercado actual disponible para el resumen de patrimonio.
if _hay_ibkr_global:
    saldos_sec["IBKR"] = pd.Series(_valor_total_ibkr_pen, index=fechas)

# ==================================================
# AHORRO TOTAL (SUMA DE CUENTAS + VALOR TOTAL IBKR)
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
with st.expander("📊 5. Gráficos y resultados", expanded=True):

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

    # ── Agregar cuotas de préstamos activos a gastos fijos ──────
    for _sim_f in st.session_state.get("simulaciones_prestamo", []):
        if not _sim_f.get("activo", True):
            continue
        _sf_primera = pd.to_datetime(_sim_f.get("fecha_primera_cuota", _sim_f.get("fecha_inicio", hoy_peru)))
        _sf_fin     = pd.to_datetime(_sim_f["fecha_fin"])
        _sf_dia     = int(_sim_f.get("dia_cuota", 5))
        _sf_cuota   = float(_sim_f["cuota"])
        _sf_cierre  = pd.to_datetime(_sim_f["fecha_cierre"]) if _sim_f.get("fecha_cierre") and _sim_f.get("monto_cierre", 0) > 0 else None
        _sf_limite  = min(_sf_fin, _sf_cierre) if _sf_cierre else _sf_fin
        _cur_f = _sf_primera.replace(day=min(_sf_dia, 28))
        while _cur_f <= _sf_limite:
            gastos_fijos_expandido.append({"fecha": _cur_f, "monto": _sf_cuota})
            try:
                _cur_f = (_cur_f + pd.DateOffset(months=1)).replace(day=min(_sf_dia, 28))
            except Exception:
                _cur_f = _cur_f + pd.DateOffset(months=1)

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
    # Calcular total reembolsables pendientes al día de hoy
    _remb_pend_monto = sum(
        float(r["monto"]) * (_tc_default if r.get("moneda") == "USD" else 1.0)
        for r in st.session_state.get("gastos_reembolsables", [])
        if r.get("estado") == "pendiente"
    )

    with st.container(border=True):
        st.caption(f"💰 Saldos al {_lbl_fecha} | IBKR valorizado con precio actual de mercado y TC configurado")
        _sb_cols = st.columns(2 + len(saldos_sec) + (1 if _remb_pend_monto > 0 else 0))
        _sb_cols[0].metric(nombre_cuenta_principal, f"S/ {_saldo_principal_hoy:,.0f}")
        for _i, (_nc, _ss) in enumerate(saldos_sec.items()):
            _v = float(_ss.iloc[_idx_ref])
            _sb_cols[1 + _i].metric(f"↳ {_nc}", f"S/ {_v:,.0f}")
        _sb_cols[1 + len(saldos_sec)].metric("🏦 Total ahorros + IBKR", f"S/ {_saldo_total_hoy:,.0f}")
        if _remb_pend_monto > 0:
            _sb_cols[-1].metric(
                "🔄 Por reembolsar",
                f"S/ {_remb_pend_monto:,.0f}",
                delta="incluido en saldo",
                delta_color="off"
            )
        if _hay_ibkr_global and _cuentas_ibkr_reemplazadas:
            st.caption(
                "📌 La cuenta secundaria IBKR fue reemplazada por el valor total actual del portafolio IBKR "
                "para evitar doble conteo."
            )

    # ── Controles del gráfico ──────────────────────────────────
    ctrl_col1, ctrl_col2, ctrl_col3 = st.columns([1, 1, 1])
    with ctrl_col1:
        _opciones_h = [3, 6, 9, 12, 18, 24, 36, 48, 60]
        _labels_h   = {3:"3 meses", 6:"6 meses", 9:"9 meses", 12:"1 año",
                       18:"1.5 años", 24:"2 años", 36:"3 años", 48:"4 años", 60:"5 años"}
        horizonte_meses = st.selectbox(
            "Horizonte",
            _opciones_h,
            index=0,
            format_func=lambda x: _labels_h[x],
            key="horizonte_evol"
        )
        # Warn if horizon exceeds simulation range
        _h_max_date = fechas.min() + pd.DateOffset(months=horizonte_meses)
        if _h_max_date > fechas.max():
            st.caption(f"⚠️ Tu simulación llega hasta {fechas.max().strftime('%d/%m/%Y')}. "
                       f"Extiende la **Fecha fin** en Configuración para ver más.")
    with ctrl_col2:
        mostrar_ahorro_total = st.toggle("Mostrar ahorro total", value=True, key="tog_total")
    with ctrl_col3:
        mostrar_secundarias = st.toggle("Mostrar cuentas secundarias", value=True, key="tog_sec")

    # ── Rango Y: auto-calculado + inputs numéricos ───────────────
    # Máximo por defecto = múltiplo de 10k por encima del máximo en el horizonte visible
    _mask_3m = (fechas >= fechas.min()) & (fechas <= min(fechas.min() + pd.DateOffset(months=horizonte_meses), fechas.max()))
    _max_en_horizonte = max(
        int(serie_ahorro_total[_mask_3m].max()) if _mask_3m.any() else 0,
        int(serie_cuenta_principal[_mask_3m].max()) if _mask_3m.any() else 0,
        10000
    )
    # Redondear al siguiente múltiplo de 10k
    _y_max_auto = ((_max_en_horizonte // 10000) + 1) * 10000

    _sl_col1, _sl_col2 = st.columns(2)
    with _sl_col1:
        _y_min = st.number_input(
            "Eje Y — mínimo (S/)",
            min_value=0, value=0, step=5000,
            key="y1_min"
        )
    with _sl_col2:
        _y_max = st.number_input(
            "Eje Y — máximo (S/)",
            min_value=1000, value=_y_max_auto, step=10000,
            key="y1_max"
        )
    rango_y1 = (_y_min, max(_y_max, _y_min + 10000))


    fecha_x_inicio = fechas.min()
    fecha_x_fin = min(fecha_x_inicio + pd.DateOffset(months=horizonte_meses), fechas.max())

    mask = (fechas >= fecha_x_inicio) & (fechas <= fecha_x_fin)
    fechas_vis = fechas[mask]

    fig_evol = go.Figure()

    # Línea cuenta principal
    fig_evol.add_trace(go.Scatter(
        x=fechas_vis, y=serie_cuenta_principal[mask],
        name=nombre_cuenta_principal,
        line=dict(color=PALETTE["principal"], width=2.5),
        hovertemplate=f"<b>{nombre_cuenta_principal}</b><br>%{{x|%d %b %Y}}<br>S/ %{{y:,.0f}}<extra></extra>"
    ))

    # Cuentas secundarias
    if mostrar_secundarias:
        for i, (nc, ss) in enumerate(saldos_sec.items()):
            fig_evol.add_trace(go.Scatter(
                x=fechas_vis, y=ss[mask],
                name=f"↳ {nc}",
                line=dict(color=COLORES_SEC[i % len(COLORES_SEC)], width=1.8, dash="dash"),
                hovertemplate=f"<b>{nc}</b><br>%{{x|%d %b %Y}}<br>S/ %{{y:,.0f}}<extra></extra>"
            ))

    # Ahorro total
    if mostrar_ahorro_total:
        fig_evol.add_trace(go.Scatter(
            x=fechas_vis, y=serie_ahorro_total[mask],
            name="Ahorro total + IBKR",
            line=dict(color=PALETTE["total"], width=2, dash="dot"),
            hovertemplate="<b>Ahorro total + IBKR</b><br>%{x|%d %b %Y}<br>S/ %{y:,.0f}<extra></extra>"
        ))

    # Área de relleno bajo la cuenta principal
    fig_evol.add_trace(go.Scatter(
        x=fechas_vis, y=serie_cuenta_principal[mask],
        fill="tozeroy",
        fillcolor=f"rgba(38,194,129,0.07)",
        line=dict(width=0),
        showlegend=False,
        hoverinfo="skip"
    ))

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
        height=520,
        hovermode="x unified",
        legend={**_LEGEND_BASE, "orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "right", "x": 1},
    )
    fig_evol.update_yaxes(
        title_text="Saldo (S/)",
        gridcolor=_grid_col, tickformat=",d", color=_font_col,
        range=[rango_y1[0], rango_y1[1]],
        nticks=8,
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
        _meta_saved = float(st.session_state["configuracion"].get("meta_ahorro_mensual", 2000.0))
        meta_ahorro = st.number_input(
            "¿Cuánto quieres ahorrar este mes? (S/)",
            min_value=0.0, step=100.0, value=_meta_saved,
            key="meta_ahorro_input"
        )
        if meta_ahorro != _meta_saved:
            st.session_state["configuracion"]["meta_ahorro_mensual"] = meta_ahorro
            guardar("configuracion")

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

        tab_ingegr, tab_debcred, tab_fijvar, tab_tabla = st.tabs(
            ["📈 Ingresos vs Egresos", "💳 Débito vs Crédito", "📌 Fijos vs Variables", "📋 Tabla detallada"]
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

        mensual_tab = mensual.copy()
        mensual_tab["Mes"] = mensual_tab["fecha_mes"].dt.strftime("%b %Y")

        with tab_ingegr:
            fig_ing = go.Figure()
            fig_ing.add_trace(go.Bar(
                x=mensual_tab["Mes"], y=mensual_tab["ingresos"],
                name="Ingresos", marker_color=PALETTE["ingresos"],
                hovertemplate="<b>Ingresos</b><br>%{x}<br>S/ %{y:,.0f}<extra></extra>"
            ))
            fig_ing.add_trace(go.Bar(
                x=mensual_tab["Mes"], y=mensual_tab["egresos"],
                name="Egresos", marker_color=PALETTE["egresos"],
                hovertemplate="<b>Egresos</b><br>%{x}<br>S/ %{y:,.0f}<extra></extra>"
            ))
            # Línea de balance neto
            _neto = mensual_tab["ingresos"] - mensual_tab["egresos"]
            fig_ing.add_trace(go.Scatter(
                x=mensual_tab["Mes"], y=_neto,
                name="Balance neto",
                mode="lines+markers",
                line=dict(color=PALETTE["hoy"], width=2),
                marker=dict(size=7),
                hovertemplate="<b>Balance neto</b><br>%{x}<br>S/ %{y:,.0f}<extra></extra>"
            ))
            fig_ing.update_layout(
                **PLOTLY_LAYOUT,
                barmode="group", height=380,
                legend={**_LEGEND_BASE, "orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "right", "x": 1},
                hovermode="x unified"
            )
            fig_ing.update_xaxes(**_XAXIS_DEF, tickangle=-30, showgrid=False)
            fig_ing.update_yaxes(**_YAXIS_DEF, tickformat=",d", title_text="S/")
            st.plotly_chart(fig_ing, use_container_width=True)

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

    if not df_gt_calc.empty or any(
        r.get("medio_pago") == "Tarjeta de credito"
        for r in st.session_state.get("gastos_reembolsables", [])
    ):
        resumen = []
        for t in st.session_state["tarjetas"]:
            df_t = df_gt_calc[df_gt_calc["tarjeta_id"] == t["id"]] if not df_gt_calc.empty else pd.DataFrame()
            for _, g in df_t.iterrows():
                fecha_gasto = pd.to_datetime(g["fecha"], errors="coerce")
                if pd.isna(fecha_gasto):
                    continue
                inicio, cierre = obtener_ciclo_tarjeta(fecha_gasto, int(t["dia_cierre"]))
                fecha_pago = (pd.Timestamp(cierre) + pd.DateOffset(months=1)).replace(day=int(t["dia_pago"]))
                _anio_mes_pago = fecha_pago.strftime("%Y-%m")
                tc = _tc_lookup.get((t["id"], _anio_mes_pago), _tc_default)
                moneda_g = g.get("moneda", "PEN")
                monto_orig = float(g["monto"])
                monto_usd  = monto_orig if moneda_g == "USD" else 0.0
                monto_pen  = monto_orig * tc if moneda_g == "USD" else monto_orig
                resumen.append({
                    "Tarjeta": t["nombre"],
                    "Tarjeta ID": t["id"],
                    "Inicio ciclo": inicio,
                    "Cierre ciclo": cierre,
                    "Fecha pago": fecha_pago.date(),
                    "Monto PEN": monto_pen,
                    "Monto USD": monto_usd,
                    "Monto remb PEN": 0.0,
                    "TC usado": tc if moneda_g == "USD" else None,
                })

        # ── Agregar reembolsables con tarjeta al resumen ──────────
        for _rr in st.session_state.get("gastos_reembolsables", []):
            if _rr.get("medio_pago") != "Tarjeta de credito":
                continue
            _t_rr = next((t for t in st.session_state["tarjetas"] if t["id"] == _rr.get("tarjeta_id","")), None)
            if _t_rr is None:
                continue
            _f_rr = pd.to_datetime(_rr.get("fecha"), errors="coerce")
            if pd.isna(_f_rr):
                continue
            _inicio_rr, _cierre_rr = obtener_ciclo_tarjeta(_f_rr, int(_t_rr["dia_cierre"]))
            _fp_rr = (pd.Timestamp(_cierre_rr) + pd.DateOffset(months=1)).replace(day=int(_t_rr["dia_pago"]))
            _anio_mes_rr = _fp_rr.strftime("%Y-%m")
            _tc_rr = _tc_lookup.get((_t_rr["id"], _anio_mes_rr), _tc_default)
            _mon_rr = _rr.get("moneda", "PEN")
            _monto_usd_rr = float(_rr["monto"]) if _mon_rr == "USD" else 0.0
            _monto_pen_rr = float(_rr["monto"]) * _tc_rr if _mon_rr == "USD" else float(_rr["monto"])
            resumen.append({
                "Tarjeta": _t_rr["nombre"],
                "Tarjeta ID": _t_rr["id"],
                "Inicio ciclo": _inicio_rr,
                "Cierre ciclo": _cierre_rr,
                "Fecha pago": _fp_rr.date(),
                "Monto PEN": _monto_pen_rr,
                "Monto USD": _monto_usd_rr,
                "Monto remb PEN": _monto_pen_rr,
                "TC usado": _tc_rr if _mon_rr == "USD" else None,
            })

        df_res = pd.DataFrame(resumen)
        if not df_res.empty:
            resumen_ciclo = (
                df_res.groupby(["Tarjeta", "Tarjeta ID", "Inicio ciclo", "Cierre ciclo", "Fecha pago"], as_index=False)
                .agg({"Monto PEN": "sum", "Monto USD": "sum",
                      "Monto remb PEN": "sum"})
                .sort_values("Fecha pago")
            )
            # TC representativo del ciclo (promedio ponderado si hay varios USD)
            _tc_rep = (
                df_res[df_res["Monto USD"] > 0]
                .groupby(["Tarjeta ID", "Inicio ciclo"])["TC usado"]
                .mean()
                .reset_index()
                .rename(columns={"TC usado": "TC rep"})
            )
            resumen_ciclo = resumen_ciclo.merge(
                _tc_rep, on=["Tarjeta ID", "Inicio ciclo"], how="left"
            )
            resumen_ciclo["TC rep"] = resumen_ciclo["TC rep"].fillna(_tc_default)

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
                    elif _d <= 5:
                        _urgencia = f"🔴 {_d} días"
                    elif _d <= 15:
                        _urgencia = f"🟡 {_d} días"
                    else:
                        _urgencia = f"🟢 {_d} días"

                    with _pcols[_ci]:
                        with st.container(border=True):
                            st.caption(f"💳 {_row['Tarjeta']}")
                            _remb_row = float(_row.get("Monto remb PEN", 0.0))
                            _total_banco = _row["Monto PEN"]
                            _neto = _total_banco - _remb_row
                            # Número grande = total que cobra el banco
                            st.markdown(f"### S/ {_total_banco:,.0f}")
                            if _row["Monto USD"] > 0:
                                st.caption(f"💵 USD {_row['Monto USD']:,.2f} × {_row['TC rep']:.2f}")
                            if _remb_row > 0:
                                st.caption(f"🏦 Total banco: S/ {_total_banco:,.0f}")
                                st.caption(f"🔄 Reembolsable: S/ {_remb_row:,.0f}")
                                st.caption(f"💰 **Tu gasto neto: S/ {_neto:,.0f}**")
                            st.caption(f"📆 Pago: **{_row['_fecha_pago_dt'].strftime('%d/%m/%Y')}**")
                            st.caption(f"🗓 Cierre: {pd.to_datetime(_row['Cierre ciclo']).strftime('%d/%m/%Y')}")
                            st.markdown(f"**{_urgencia}**")

            # ── Timeline de pagos futuros (gráfico) ────────────────
            if not pagos_futuros.empty:
                st.markdown("#### 📊 Timeline de pagos futuros")
                _timeline = pagos_futuros.sort_values("_dias").copy()
                _timeline["color"] = _timeline["_dias"].apply(
                    lambda d: "#E74C3C" if d <= 5 else ("#F39C12" if d <= 15 else "#26C281")
                )

                fig_tl = go.Figure()
                for _, _row in _timeline.iterrows():
                    _usd_txt  = f" | USD {_row['Monto USD']:,.2f}×{_row['TC rep']:.2f}" if _row["Monto USD"] > 0 else ""
                    _remb_val = _row.get("Monto remb PEN", 0.0)
                    _remb_txt = f" | 🔄 remb S/ {_remb_val:,.0f}" if _remb_val > 0 else ""
                    fig_tl.add_trace(go.Bar(
                        x=[_row["Monto PEN"]],
                        y=[f"{_row['Tarjeta']} — {_row['_fecha_pago_dt'].strftime('%d/%m')}"],
                        orientation="h",
                        marker_color=_row["color"],
                        text=f"S/ {_row['Monto PEN']:,.0f}  ({int(_row['_dias'])} días){_usd_txt}{_remb_txt}",
                        textposition="outside",
                        hovertemplate=(
                            f"<b>{_row['Tarjeta']}</b><br>"
                            f"Ciclo: {_row['Ciclo facturación']}<br>"
                            f"Pago: {_row['_fecha_pago_dt'].strftime('%d/%m/%Y')}<br>"
                            f"<b>Total S/ {_row['Monto PEN']:,.2f}</b><br>"
                            + (f"💵 USD {_row['Monto USD']:,.2f} @ TC {_row['TC rep']:.2f}<br>" if _row["Monto USD"] > 0 else "")
                            + (f"🔄 Reembolsable S/ {_remb_val:,.2f}<br>" if _remb_val > 0 else "")
                            + (f"Neto a pagar S/ {_row['Monto PEN']-_remb_val:,.2f}<br>" if _remb_val > 0 else "")
                            + f"<extra></extra>"
                        ),
                        showlegend=False
                    ))

                fig_tl.update_layout(
                    **PLOTLY_LAYOUT,
                    height=max(200, len(_timeline) * 52 + 60),
                    showlegend=False,
                    barmode="overlay",
                )
                fig_tl.update_xaxes(tickformat=",d", gridcolor=_grid_col, color=_font_col, title_text="Monto (S/)")
                fig_tl.update_yaxes(gridcolor="rgba(0,0,0,0)", color=_font_col, autorange="reversed")
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
                    ["Tarjeta", "Ciclo facturación", "Cierre ciclo", "Fecha pago",
                     "Monto PEN", "Monto remb PEN", "Monto USD", "TC rep", "_dias"]
                ].copy()
                _tabla_show["Estado"] = _tabla_show["_dias"].apply(
                    lambda d: "✅ Pagado" if d < 0 else ("🔴 Urgente" if d <= 5 else ("🟡 Próximo" if d <= 15 else "🟢 Futuro"))
                )
                _tabla_show = _tabla_show.drop(columns=["_dias"])
                _tabla_show["TC rep"] = _tabla_show.apply(
                    lambda r: f"{r['TC rep']:.2f}" if r["Monto USD"] > 0 else "—", axis=1
                )
                _tabla_show["Monto USD"] = _tabla_show["Monto USD"].apply(
                    lambda x: f"USD {x:,.2f}" if x > 0 else "—"
                )
                st.dataframe(
                    _tabla_show,
                    use_container_width=True, hide_index=True,
                    column_config={
                        "Monto PEN":      st.column_config.NumberColumn("Total (S/)",      format="S/ %,.0f"),
                        "Monto remb PEN": st.column_config.NumberColumn("Reembolsable (S/)", format="S/ %,.0f"),
                        "Monto USD":      st.column_config.TextColumn("En USD"),
                        "TC rep":         st.column_config.TextColumn("TC usado"),
                        "Estado":         st.column_config.TextColumn("Estado"),
                    }
                )
        else:
            st.info("No hay gastos válidos con tarjeta para calcular ciclos.")
    else:
        st.info("No hay gastos con tarjeta registrados.")
