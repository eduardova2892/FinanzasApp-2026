"""
DAG: exchange_rate_bcrp
Fuente: BCRP (Banco Central de Reserva del Perú) — API oficial gratuita
Endpoint: https://estadisticas.bcrp.gob.pe/estadisticas/series/api/PD04638KD/json
Serie PD04638KD = Tipo de cambio venta USD/PEN (interbancario)
Frecuencia sugerida: diaria (lunes a viernes)
"""
from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta
import requests, pandas as pd
from pathlib import Path
from zoneinfo import ZoneInfo

LIMA_TZ  = ZoneInfo("America/Lima")
CSV_PATH = Path("data/exchange_rate_bcrp.csv")

default_args = {
    "owner": "finanzas",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}

def fetch_bcrp_tc(**context):
    """
    Llama a la API del BCRP para obtener el tipo de cambio USD/PEN más reciente.
    Documentación: https://estadisticas.bcrp.gob.pe/estadisticas/series/ayuda/api
    """
    # Serie PD04638KD: Tipo de cambio venta (S/ por USD)
    url = "https://estadisticas.bcrp.gob.pe/estadisticas/series/api/PD04638KD/json"
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    # La respuesta tiene estructura: {"config": {...}, "periods": [{"name": "Ene.2026", "values": ["3.70"]}]}
    periodos = data.get("periods", [])
    if not periodos:
        raise ValueError("BCRP no devolvió periodos")

    ultimo = periodos[-1]
    valor  = float(ultimo["values"][0])
    fecha  = datetime.now(tz=LIMA_TZ).date()

    CSV_PATH.parent.mkdir(exist_ok=True)
    df_new = pd.DataFrame([{
        "fecha":           str(fecha),
        "base":            "USD",
        "moneda_destino":  "PEN",
        "usd_pen":         valor,
        "fuente":          "BCRP",
        "fecha_fuente":    ultimo["name"],
        "updated_at_lima": datetime.now(tz=LIMA_TZ).strftime("%Y-%m-%d %H:%M"),
    }])

    if CSV_PATH.exists():
        df_old = pd.read_csv(CSV_PATH)
        df_out = pd.concat([df_old, df_new]).drop_duplicates("fecha", keep="last")
    else:
        df_out = df_new

    df_out.to_csv(CSV_PATH, index=False)
    print(f"BCRP TC guardado: 1 USD = S/ {valor:.4f} ({fecha})")

with DAG(
    "exchange_rate_bcrp",
    default_args=default_args,
    description="Tipo de cambio USD/PEN desde BCRP (oficial)",
    schedule_interval="0 9 * * 1-5",   # 9am Lima, lunes a viernes
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["finanzas", "tipo_cambio", "bcrp"],
) as dag:

    tarea = PythonOperator(
        task_id="fetch_bcrp",
        python_callable=fetch_bcrp_tc,
    )
