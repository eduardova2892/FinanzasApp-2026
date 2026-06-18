# Airflow DAG: Gmail bank expenses pending
"""
DAG genérico para detectar gastos bancarios desde Gmail y generar una bandeja
pendiente para revisión en Streamlit.

Ubicación recomendada:
    dags/dag_bank_gmail_expenses.py

Requiere:
    scripts/gmail_bank_reader.py
    scripts/bank_email_parsers.py
    secrets/credentials_gmail.json
    secrets/token_gmail.json

Salida:
    data/bank_gmail_expenses_pending.csv

Notas:
- No importa gastos directamente al dashboard.
- Solo genera pendientes para revisión manual.
- El diseño permite agregar GNB, BBVA, Interbank, etc. sin tocar app.py.
"""

from __future__ import annotations

import csv
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List

import pendulum
from airflow.decorators import dag, task


LIMA_TZ = pendulum.timezone("America/Lima")
PROJECT_HOME = Path(os.environ.get("FINANZAS_APP_HOME", "/mnt/c/Users/eduar/OneDrive/Documents/01_EduPC_Legion/04 AppMyFinances"))
SCRIPTS_DIR = PROJECT_HOME / "scripts"
DATA_DIR = PROJECT_HOME / "data"
PENDING_PATH = DATA_DIR / "bank_gmail_expenses_pending.csv"

# Permite importar módulos propios desde /scripts dentro del DAG.
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
if str(PROJECT_HOME) not in sys.path:
    sys.path.insert(0, str(PROJECT_HOME))


def _now_lima_str() -> str:
    return datetime.now(LIMA_TZ).strftime("%Y-%m-%d %H:%M:%S")


def _read_existing_pending(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _write_pending(path: Path, rows: Iterable[Dict[str, Any]], columns: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({col: row.get(col, "") for col in columns})


@dag(
    dag_id="bank_gmail_expenses_pending",
    description="Lee correos bancarios desde Gmail y genera gastos pendientes para revisión en FinanzasApp.",
    start_date=pendulum.datetime(2026, 6, 17, tz=LIMA_TZ),
    schedule="0 8,18 * * *",
    catchup=False,
    tags=["finanzas", "gmail", "bancos", "gastos"],
)
def bank_gmail_expenses_pending():
    @task
    def fetch_bank_emails(days: int = 30, max_results_per_bank: int = 50) -> List[Dict[str, Any]]:
        """Lee correos bancarios desde Gmail usando lectores específicos por banco."""
        from gmail_bank_reader import fetch_bcp_consumption_emails

        all_messages: List[Dict[str, Any]] = []

        # Por ahora dejamos activo solo BCP. Luego aquí agregamos GNB, BBVA, Interbank, etc.
        bcp_messages = fetch_bcp_consumption_emails(
            PROJECT_HOME,
            days=int(days),
            max_results=int(max_results_per_bank),
        )

        for msg in bcp_messages:
            d = msg.to_dict()
            d["banco_query"] = "BCP"
            all_messages.append(d)

        print(f"Correos bancarios leídos: {len(all_messages)}")
        return all_messages

    @task
    def parse_bank_emails(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Aplica parser bancario y devuelve gastos detectados."""
        from bank_email_parsers import normalize_pending_records, parse_bank_email

        parsed: List[Dict[str, Any]] = []
        failed = 0
        now_lima = _now_lima_str()

        for msg in messages or []:
            bank = msg.get("banco_query") or None
            text = msg.get("text") or msg.get("snippet") or ""
            result = parse_bank_email(
                text,
                banco=bank,
                gmail_id=msg.get("gmail_id", ""),
                gmail_thread_id=msg.get("thread_id", ""),
                gmail_date=msg.get("date", ""),
                subject=msg.get("subject", ""),
            )
            if result:
                result["fecha_detectado_lima"] = now_lima
                parsed.append(result)
            else:
                failed += 1
                print(f"No interpretado: {msg.get('gmail_id', '')} | {msg.get('subject', '')}")

        normalized = normalize_pending_records(parsed)
        print(f"Gastos detectados: {len(normalized)}")
        print(f"Correos no interpretados: {failed}")
        return normalized

    @task
    def save_pending_expenses(records: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Guarda gastos nuevos en CSV pendiente, sin duplicar hashes existentes."""
        from bank_email_parsers import PENDING_COLUMNS, normalize_pending_record

        DATA_DIR.mkdir(parents=True, exist_ok=True)

        existing = _read_existing_pending(PENDING_PATH)
        existing_hashes = {str(r.get("hash_importacion", "")).strip() for r in existing if r.get("hash_importacion")}
        existing_gmail_ids = {str(r.get("gmail_id", "")).strip() for r in existing if r.get("gmail_id")}

        new_rows: List[Dict[str, Any]] = []
        duplicates = 0

        for rec in records or []:
            norm = normalize_pending_record(rec)
            h = str(norm.get("hash_importacion", "")).strip()
            gid = str(norm.get("gmail_id", "")).strip()

            if h and h in existing_hashes:
                duplicates += 1
                continue
            if gid and gid in existing_gmail_ids:
                duplicates += 1
                continue

            new_rows.append(norm)
            if h:
                existing_hashes.add(h)
            if gid:
                existing_gmail_ids.add(gid)

        combined = existing + new_rows
        _write_pending(PENDING_PATH, combined, PENDING_COLUMNS)

        summary = {
            "archivo": str(PENDING_PATH),
            "existentes_previos": len(existing),
            "nuevos_agregados": len(new_rows),
            "duplicados_omitidos": duplicates,
            "total_pendientes_archivo": len(combined),
        }
        print(summary)
        return summary

    emails = fetch_bank_emails()
    detected = parse_bank_emails(emails)
    save_pending_expenses(detected)


dag = bank_gmail_expenses_pending()
