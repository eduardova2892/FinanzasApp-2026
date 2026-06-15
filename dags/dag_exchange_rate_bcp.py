"""
DAG: exchange_rate_bcp
Fuente: BCP (Banco de Crédito del Perú) — scraping de la web
URL: https://www.viabcp.com/tipo-de-cambio
Alternativa API-like: https://www.sbs.gob.pe (SBS publica TC de todos los bancos)
Frecuencia sugerida: diaria

NOTA: BCP no tiene API pública. Dos opciones:
  A) Scraping directo de viabcp.com (puede cambiar el HTML)
  B) Usar la SBS que publica TC de todos los bancos regulados (RECOMENDADO)
     URL SBS: https://www.sbs.gob.pe/app/pp/sistip_portal/paginas/publicacion/tipocambiopromedio.aspx
"""
from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta
import requests, pandas as pd
from pathlib import Path
from zoneinfo import ZoneInfo

LIMA_TZ  = ZoneInfo("America/Lima")
CSV_PATH = Path("data/exchange_rate_bcp.csv")

default_args = {
    "owner": "finanzas",
    "retries": 2,
    "retry_delay": timedelta(minutes=10),
}

def fetch_bcp_via_sbs(**context):
    """
    OPCIÓN B (RECOMENDADA): Lee el TC del BCP desde la SBS.
    La SBS tiene un endpoint JSON no oficial pero estable:
    https://www.sbs.gob.pe/app/pp/sistip_portal/paginas/publicacion/tipocambiopromedio.aspx
    
    Alternativa más estable: SBS Excel diario
    https://www.sbs.gob.pe/Portals/0/jer/TASA-CAMBIO-PROMEDIO/TPCAMMON.xlsx
    """
    fecha_hoy = datetime.now(tz=LIMA_TZ).strftime("%d/%m/%Y")

    # Endpoint de la SBS (TC promedio ponderado del sistema bancario)
    url = (
        "https://www.sbs.gob.pe/app/pp/sistip_portal/paginas/publicacion/"
        "tipocambiopromedio.aspx"
    )
    headers = {"User-Agent": "Mozilla/5.0 (compatible; FinanzasBot/1.0)"}

    # ── Intentar Excel de la SBS (más fiable) ──────────────────
    excel_url = "https://www.sbs.gob.pe/Portals/0/jer/TASA-CAMBIO-PROMEDIO/TPCAMMON.xlsx"
    resp = requests.get(excel_url, headers=headers, timeout=20)
    resp.raise_for_status()

    df_sbs = pd.read_excel(resp.content, header=3)   # las primeras filas son título

    # Buscar columna USD y fila de BCP
    # El Excel tiene: Entidad | USD Compra | USD Venta | EUR... etc.
    # Filtramos la fila donde "Entidad" contenga "BCP" o "CREDITO"
    col_entidad = df_sbs.columns[0]
    df_sbs[col_entidad] = df_sbs[col_entidad].astype(str)
    fila_bcp = df_sbs[df_sbs[col_entidad].str.upper().str.contains("CREDITO|BCP", na=False)]

    if fila_bcp.empty:
        raise ValueError("No se encontró BCP en el Excel de la SBS")

    # Columna USD Venta (posición 2, puede variar según versión del Excel)
    usd_venta_col = [c for c in df_sbs.columns if "VENTA" in str(c).upper() and "USD" in str(c).upper()]
    if not usd_venta_col:
        # Fallback: segunda columna numérica
        usd_venta = float(fila_bcp.iloc[0, 2])
    else:
        usd_venta = float(fila_bcp.iloc[0][usd_venta_col[0]])

    fecha = datetime.now(tz=LIMA_TZ).date()
    CSV_PATH.parent.mkdir(exist_ok=True)

    df_new = pd.DataFrame([{
        "fecha":           str(fecha),
        "base":            "USD",
        "moneda_destino":  "PEN",
        "usd_pen":         usd_venta,
        "fuente":          "BCP (vía SBS)",
        "fecha_fuente":    fecha_hoy,
        "updated_at_lima": datetime.now(tz=LIMA_TZ).strftime("%Y-%m-%d %H:%M"),
    }])

    if CSV_PATH.exists():
        df_old = pd.read_csv(CSV_PATH)
        df_out = pd.concat([df_old, df_new]).drop_duplicates("fecha", keep="last")
    else:
        df_out = df_new

    df_out.to_csv(CSV_PATH, index=False)
    print(f"BCP TC guardado: 1 USD = S/ {usd_venta:.4f} ({fecha})")

with DAG(
    "exchange_rate_bcp",
    default_args=default_args,
    description="Tipo de cambio USD/PEN del BCP vía SBS",
    schedule_interval="30 9 * * 1-5",  # 9:30am Lima, lunes a viernes
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["finanzas", "tipo_cambio", "bcp", "sbs"],
) as dag:

    tarea = PythonOperator(
        task_id="fetch_bcp_via_sbs",
        python_callable=fetch_bcp_via_sbs,
    )
