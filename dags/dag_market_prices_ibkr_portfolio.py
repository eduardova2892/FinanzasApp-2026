import os
from pathlib import Path
from datetime import timedelta

import pandas as pd
import pendulum
import requests

from airflow.sdk import dag, task


LOCAL_TZ = pendulum.timezone("America/Lima")

PROJECT_HOME = Path(
    os.environ.get(
        "FINANZAS_APP_HOME",
        "/mnt/c/Users/eduar/OneDrive/Documents/01_EduPC_Legion/04 AppMyFinances"
    )
)

INSTRUMENTS_PATH = PROJECT_HOME / "data" / "ibkr_instruments.csv"
CURRENT_PRICES_PATH = PROJECT_HOME / "data" / "market_prices_portfolio.csv"
HISTORY_PRICES_PATH = PROJECT_HOME / "data" / "market_prices_portfolio_history.csv"


def _parse_float(value):
    try:
        if value is None or pd.isna(value):
            return None
        return float(str(value).strip().replace(",", "."))
    except Exception:
        return None


def _is_active(value):
    return str(value).strip().upper() in ["TRUE", "1", "SI", "SÍ", "YES", "Y"]


def _get_yahoo_price(source_symbol: str) -> dict:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{source_symbol}"

    params = {
        "range": "5d",
        "interval": "1d",
    }

    response = requests.get(
        url,
        params=params,
        timeout=20,
        headers={"User-Agent": "Mozilla/5.0"},
    )
    response.raise_for_status()

    data = response.json()
    chart = data.get("chart", {})
    result = chart.get("result", [])

    if not result:
        error = chart.get("error")
        raise ValueError(f"Yahoo Finance no devolvió resultado para {source_symbol}. Error: {error}")

    result0 = result[0]
    meta = result0.get("meta", {})
    indicators = result0.get("indicators", {})
    quotes = indicators.get("quote", [])

    price = _parse_float(meta.get("regularMarketPrice"))

    if price is None and quotes:
        closes = quotes[0].get("close", [])
        closes_validos = [c for c in closes if c is not None]
        if closes_validos:
            price = _parse_float(closes_validos[-1])

    if price is None or price <= 0:
        raise ValueError(f"No se pudo obtener precio válido para {source_symbol}. Meta: {meta}")

    market_time = meta.get("regularMarketTime")
    if market_time:
        dt_lima = pendulum.from_timestamp(int(market_time), tz=LOCAL_TZ)
    else:
        timestamps = result0.get("timestamp", [])
        if timestamps:
            dt_lima = pendulum.from_timestamp(int(timestamps[-1]), tz=LOCAL_TZ)
        else:
            dt_lima = pendulum.now(LOCAL_TZ)

    return {
        "precio_actual_usd": float(price),
        "fecha_precio": dt_lima.date().isoformat(),
        "hora_precio": dt_lima.time().strftime("%H:%M:%S"),
        "moneda_precio": meta.get("currency", "USD"),
        "exchange": meta.get("exchangeName", ""),
    }


@dag(
    dag_id="market_prices_ibkr_portfolio",
    description="Actualiza precios de todos los instrumentos IBKR registrados en el catálogo",
    schedule="0 18 * * 1-5",
    start_date=pendulum.datetime(2026, 6, 15, tz=LOCAL_TZ),
    catchup=False,
    default_args={
        "retries": 3,
        "retry_delay": timedelta(minutes=5),
    },
    tags=["finanzas", "ibkr", "portfolio", "market_prices"],
)
def market_prices_ibkr_portfolio():

    @task
    def read_instruments() -> list[dict]:
        if not INSTRUMENTS_PATH.exists():
            raise FileNotFoundError(f"No existe el catálogo de instrumentos: {INSTRUMENTS_PATH}")

        df = pd.read_csv(INSTRUMENTS_PATH)

        required_cols = [
            "ticker",
            "nombre",
            "tipo",
            "moneda",
            "source_symbol",
            "fuente_precio",
            "activo",
        ]

        missing = [c for c in required_cols if c not in df.columns]
        if missing:
            raise ValueError(f"Faltan columnas en ibkr_instruments.csv: {missing}")

        df = df[df["activo"].apply(_is_active)].copy()

        if df.empty:
            raise ValueError("No hay instrumentos activos en ibkr_instruments.csv")

        df["ticker"] = df["ticker"].astype(str).str.upper().str.strip()
        df["source_symbol"] = df["source_symbol"].astype(str).str.strip()
        df["fuente_precio"] = df["fuente_precio"].astype(str).str.strip()

        return df.to_dict(orient="records")

    @task
    def extract_market_prices(instruments: list[dict]) -> list[dict]:
        rows = []
        errors = []

        now_lima = pendulum.now(LOCAL_TZ)

        for inst in instruments:
            ticker = str(inst["ticker"]).upper().strip()
            source_symbol = str(inst["source_symbol"]).strip()
            fuente_precio = str(inst.get("fuente_precio", "Yahoo Finance")).strip()

            try:
                if fuente_precio != "Yahoo Finance":
                    raise ValueError(f"Fuente no soportada todavía: {fuente_precio}")

                price_info = _get_yahoo_price(source_symbol)

                row = {
                    "fecha": now_lima.date().isoformat(),
                    "ticker": ticker,
                    "nombre": inst.get("nombre", ""),
                    "tipo": inst.get("tipo", ""),
                    "moneda": inst.get("moneda", "USD"),
                    "source_symbol": source_symbol,
                    "precio_actual_usd": price_info["precio_actual_usd"],
                    "fecha_precio": price_info["fecha_precio"],
                    "hora_precio": price_info["hora_precio"],
                    "moneda_precio": price_info["moneda_precio"],
                    "exchange": price_info["exchange"],
                    "fuente_precio": fuente_precio,
                    "updated_at_lima": now_lima.to_datetime_string(),
                }

                rows.append(row)

            except Exception as e:
                errors.append(f"{ticker} / {source_symbol}: {e}")

        if errors:
            raise ValueError("Errores al consultar precios: " + " | ".join(errors))

        return rows

    @task
    def validate_market_prices(rows: list[dict]) -> list[dict]:
        if not rows:
            raise ValueError("No hay precios para validar.")

        for row in rows:
            ticker = row["ticker"]
            price = _parse_float(row["precio_actual_usd"])

            if price is None or price <= 0:
                raise ValueError(f"Precio inválido para {ticker}: {price}")

            if price < 0.01 or price > 10000:
                raise ValueError(f"Precio fuera de rango para {ticker}: {price}")

        return rows

    @task
    def save_market_prices(rows: list[dict]) -> str:
        CURRENT_PRICES_PATH.parent.mkdir(parents=True, exist_ok=True)

        df_current = pd.DataFrame(rows)
        df_current = df_current.sort_values(["ticker"])

        df_current.to_csv(CURRENT_PRICES_PATH, index=False)

        if HISTORY_PRICES_PATH.exists():
            df_hist = pd.read_csv(HISTORY_PRICES_PATH)
            df_hist = pd.concat([df_hist, df_current], ignore_index=True)
            df_hist = df_hist.drop_duplicates(
                subset=["fecha", "ticker"],
                keep="last",
            )
        else:
            df_hist = df_current

        df_hist = df_hist.sort_values(["fecha", "ticker"])
        df_hist.to_csv(HISTORY_PRICES_PATH, index=False)

        return str(CURRENT_PRICES_PATH)

    instruments = read_instruments()
    raw_prices = extract_market_prices(instruments)
    valid_prices = validate_market_prices(raw_prices)
    save_market_prices(valid_prices)


market_prices_ibkr_portfolio()
