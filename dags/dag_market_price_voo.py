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

DATA_PATH = PROJECT_HOME / "data" / "market_prices_voo.csv"
HISTORY_PATH = PROJECT_HOME / "data" / "market_prices_history.csv"


def _parse_float(value):
    try:
        return float(str(value).strip().replace(",", "."))
    except Exception:
        return None


@dag(
    dag_id="market_price_voo",
    description="Actualiza el precio de mercado de VOO para la sección de inversiones IBKR",
    schedule="0 18 * * 1-5",
    start_date=pendulum.datetime(2026, 6, 15, tz=LOCAL_TZ),
    catchup=False,
    default_args={
        "retries": 3,
        "retry_delay": timedelta(minutes=5),
    },
    tags=["finanzas", "ibkr", "voo", "market_price"],
)
def market_price_voo():

    @task
    def extract_voo_price() -> dict:
        """
        Consulta el último precio disponible de VOO desde Yahoo Finance Chart API.
        No es una conexión directa con IBKR.
        """
        url = "https://query1.finance.yahoo.com/v8/finance/chart/VOO"

        params = {
            "range": "5d",
            "interval": "1d",
        }

        response = requests.get(
            url,
            params=params,
            timeout=20,
            headers={"User-Agent": "Mozilla/5.0"}
        )
        response.raise_for_status()

        data = response.json()

        chart = data.get("chart", {})
        result = chart.get("result", [])

        if not result:
            raise ValueError(f"Respuesta inesperada de Yahoo Finance: {str(data)[:500]}")

        result0 = result[0]
        meta = result0.get("meta", {})
        timestamps = result0.get("timestamp", [])
        indicators = result0.get("indicators", {})
        quotes = indicators.get("quote", [])

        price = _parse_float(meta.get("regularMarketPrice"))

        fecha_precio = ""
        hora_precio = ""

        if timestamps:
            ts = timestamps[-1]
            dt_lima = pendulum.from_timestamp(ts, tz=LOCAL_TZ)
            fecha_precio = dt_lima.date().isoformat()
            hora_precio = dt_lima.time().strftime("%H:%M:%S")

        if price is None and quotes:
            closes = quotes[0].get("close", [])
            closes_validos = [c for c in closes if c is not None]
            if closes_validos:
                price = _parse_float(closes_validos[-1])

        if price is None or price <= 0:
            raise ValueError(f"No se pudo obtener precio válido para VOO. Respuesta: {str(data)[:500]}")

        return {
            "ticker": "VOO",
            "nombre": "Vanguard S&P 500 ETF",
            "precio_actual_usd": float(price),
            "fecha_precio": fecha_precio,
            "hora_precio": hora_precio,
            "fuente_precio": "Yahoo Finance",
        }

    @task
    def validate_voo_price(payload: dict) -> dict:
        price = float(payload["precio_actual_usd"])

        if price <= 0:
            raise ValueError(f"Precio inválido para VOO: {price}")

        if price < 100 or price > 1500:
            raise ValueError(f"Precio fuera de rango esperado para VOO: {price}")

        return payload

    @task
    def save_voo_price(payload: dict) -> str:
        DATA_PATH.parent.mkdir(parents=True, exist_ok=True)

        now_lima = pendulum.now(LOCAL_TZ)

        row = {
            "fecha": now_lima.date().isoformat(),
            "ticker": payload["ticker"],
            "nombre": payload["nombre"],
            "precio_actual_usd": payload["precio_actual_usd"],
            "fecha_precio": payload["fecha_precio"],
            "hora_precio": payload["hora_precio"],
            "fuente_precio": payload["fuente_precio"],
            "updated_at_lima": now_lima.to_datetime_string(),
        }

        df_current = pd.DataFrame([row])
        df_current.to_csv(DATA_PATH, index=False)

        if HISTORY_PATH.exists():
            df_hist = pd.read_csv(HISTORY_PATH)
            df_hist = pd.concat([df_hist, df_current], ignore_index=True)
            df_hist = df_hist.drop_duplicates(
                subset=["fecha", "ticker"],
                keep="last"
            )
        else:
            df_hist = df_current

        df_hist = df_hist.sort_values(["fecha", "ticker"])
        df_hist.to_csv(HISTORY_PATH, index=False)

        return str(DATA_PATH)

    raw_price = extract_voo_price()
    valid_price = validate_voo_price(raw_price)
    save_voo_price(valid_price)


market_price_voo()
