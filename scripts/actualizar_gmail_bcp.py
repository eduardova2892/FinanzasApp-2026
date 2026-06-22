import sys
from pathlib import Path
import pandas as pd

project = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project / "scripts"))

from gmail_bank_reader import fetch_bcp_consumption_emails
from bank_email_parsers import parse_bank_email

DIAS = 10
MAX_CORREOS = 200

emails = fetch_bcp_consumption_emails(project, days=DIAS, max_results=MAX_CORREOS)

rows = []

for email in emails:
    d = email.to_dict()

    texto_parse = " ".join([
        str(d.get("subject", "")),
        str(d.get("snippet", "")),
        str(d.get("text", "")),
        str(d.get("body", "")),
    ])

    parsed = parse_bank_email(
        texto_parse,
        banco="BCP",
        gmail_id=d.get("gmail_id", ""),
        gmail_thread_id=d.get("thread_id", ""),
        gmail_date=d.get("date", ""),
        subject=d.get("subject", ""),
    )

    if parsed:
        rows.append(parsed)

cols = [
    "gmail_id","gmail_thread_id","gmail_date","subject","banco","medio_pago",
    "monto","moneda","empresa","fecha","hora","fecha_hora_texto",
    "tarjeta_ultimos4","numero_operacion","categoria_sugerida",
    "descripcion_sugerida","hash_importacion","estado",
    "fecha_detectado_lima","fecha_importado_lima","resultado_importacion","fuente"
]

df = pd.DataFrame(rows)

out = project / "data" / "bank_gmail_expenses_pending.csv"
out.parent.mkdir(exist_ok=True)

if df.empty:
    df = pd.DataFrame(columns=cols)
else:
    for c in cols:
        if c not in df.columns:
            df[c] = ""

    df = df[cols]
    df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce").dt.strftime("%Y-%m-%d")
    df = df.sort_values(["fecha", "hora"], ascending=[False, False])

df.to_csv(out, index=False, encoding="utf-8-sig")

print(f"Días revisados: {DIAS}")
print(f"Correos leídos: {len(emails)}")
print(f"Gastos detectados: {len(df)}")

if not df.empty:
    print("Conteo por medio:")
    print(df["medio_pago"].value_counts(dropna=False).to_string())

print(f"CSV actualizado: {out}")
