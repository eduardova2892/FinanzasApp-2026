import os
from pathlib import Path
from datetime import timedelta

import pandas as pd
import pendulum
import requests

from airflow.sdk import dag, task


LOCAL_TZ = pendulum.timezone("America/Lima")

PROJECT_HOME = Path(os.environ.get("FINANZAS_APP_HOME", os.getcwd()))
DATA_PATH = PROJECT_HOME / "data" / "exchange_rate_usd_pen.csv"


@dag(
    dag_id="daily_usd_pen_finanzas",
    description="Actualiza diariamente el tipo de cambio USD/PEN para la app de finanzas personales",
    schedule="0 7 * * *",
    start_date=pendulum.datetime(2026, 6, 14, tz=LOCAL_TZ),
    catchup=False,
    default_args={
        "retries": 3,
        "retry_delay": timedelta(minutes=5),
    },
    tags=["finanzas", "usd_pen", "streamlit"],
)
def daily_usd_pen_finanzas():

    @task
    def extract_usd_pen() -> dict:
        url = "https://open.er-api.com/v6/latest/USD"

        response = requests.get(url, timeout=20)
        response.raise_for_status()

        data = response.json()
        rate = data["rates"]["PEN"]

        return {
            "fecha_fuente": data.get("time_last_update_utc"),
            "base": "USD",
            "moneda_destino": "PEN",
            "usd_pen": float(rate),
            "fuente": "ExchangeRate-API",
        }

    @task
    def validate_usd_pen(payload: dict) -> dict:
        rate = payload["usd_pen"]

        if rate <= 0:
            raise ValueError(f"Tipo de cambio inválido: {rate}")

        if rate < 2.5 or rate > 5.5:
            raise ValueError(f"Tipo de cambio fuera de rango esperado: {rate}")

        return payload

    @task
    def save_usd_pen(payload: dict) -> str:
        DATA_PATH.parent.mkdir(parents=True, exist_ok=True)

        today_lima = pendulum.now(LOCAL_TZ).date().isoformat()

        row = {
            "fecha": today_lima,
            "base": payload["base"],
            "moneda_destino": payload["moneda_destino"],
            "usd_pen": payload["usd_pen"],
            "fuente": payload["fuente"],
            "fecha_fuente": payload["fecha_fuente"],
            "updated_at_lima": pendulum.now(LOCAL_TZ).to_iso8601_string(),
        }

        if DATA_PATH.exists():
            df = pd.read_csv(DATA_PATH)
            df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
            df = df.drop_duplicates(subset=["fecha"], keep="last")
        else:
            df = pd.DataFrame([row])

        df = df.sort_values("fecha")
        df.to_csv(DATA_PATH, index=False)

        return str(DATA_PATH)

    raw_rate = extract_usd_pen()
    valid_rate = validate_usd_pen(raw_rate)
    save_usd_pen(valid_rate)


daily_usd_pen_finanzas()
