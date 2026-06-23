"""
Módulo genérico para leer correos bancarios desde Gmail.

Uso esperado:
- Airflow importa este módulo para buscar correos bancarios recientes.
- Los parsers específicos de cada banco viven en scripts/bank_email_parsers.py.

Archivos sensibles requeridos, NO subir a GitHub:
- secrets/credentials_gmail.json
- secrets/token_gmail.json
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from bs4 import BeautifulSoup
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build


SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


@dataclass
class GmailMessage:
    """Representación limpia de un correo Gmail leído por API."""

    gmail_id: str
    thread_id: str
    subject: str
    sender: str
    recipient: str
    date: str
    snippet: str
    text: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def project_root_from_file(current_file: str | Path) -> Path:
    """Devuelve la raíz del proyecto asumiendo que este módulo vive en /scripts."""
    return Path(current_file).resolve().parents[1]


def _json_from_streamlit_secret(key: str):
    """Lee JSON desde Streamlit Secrets.

    Soporta:
    [gmail]
    credentials_json = """..."""
    token_json = """..."""
    """
    import json

    try:
        import streamlit as st
    except Exception:
        return None

    try:
        gmail_group = st.secrets.get("gmail", {})
    except Exception:
        gmail_group = {}

    value = None

    try:
        if isinstance(gmail_group, dict):
            value = gmail_group.get(key)
        else:
            value = gmail_group[key]
    except Exception:
        value = None

    if value is None:
        try:
            value = st.secrets.get(key)
        except Exception:
            value = None

    if value is None:
        return None

    if isinstance(value, dict):
        return dict(value)

    value = str(value).strip()
    if not value:
        return None

    return json.loads(value)


def get_gmail_service(project_dir: str | Path):
    """Crea servicio Gmail usando primero Streamlit Secrets y luego archivos locales.

    En local usa:
    secrets/credentials_gmail.json
    secrets/token_gmail.json

    En Streamlit Cloud usa:
    [gmail]
    credentials_json = """..."""
    token_json = """..."""
    """
    import json
    from pathlib import Path

    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    project_dir = Path(project_dir)

    credentials_path = project_dir / "secrets" / "credentials_gmail.json"
    token_path = project_dir / "secrets" / "token_gmail.json"

    credentials_info = _json_from_streamlit_secret("credentials_json")
    token_info = _json_from_streamlit_secret("token_json")

    creds = None

    # 1. Token desde Streamlit Secrets
    if token_info:
        creds = Credentials.from_authorized_user_info(token_info, SCOPES)

    # 2. Token desde archivo local
    elif token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    # 3. Refrescar token si venci?
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())

        # En local, actualizamos token_gmail.json.
        # En Streamlit Cloud no escribimos secrets.
        try:
            if token_path.exists():
                token_path.write_text(creds.to_json(), encoding="utf-8")
        except Exception:
            pass

    # 4. Si no hay token v?lido, crear flujo OAuth solo en local
    if not creds or not creds.valid:
        if credentials_info:
            raise RuntimeError(
                "Existe credentials_json en Streamlit Secrets, pero falta token_json v?lido. "
                "Debes copiar tambi?n el contenido de secrets/token_gmail.json a Streamlit Secrets."
            )

        if not credentials_path.exists():
            raise FileNotFoundError(
                f"No existe credentials Gmail: {credentials_path}. "
                "En Streamlit Cloud configura [gmail].credentials_json y [gmail].token_json en Secrets."
            )

        flow = InstalledAppFlow.from_client_secrets_file(
            str(credentials_path),
            SCOPES,
        )
        creds = flow.run_local_server(port=0)

        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json(), encoding="utf-8")

    return build("gmail", "v1", credentials=creds)

def _decode_gmail_base64(data: str | None) -> str:
    """Decodifica contenido base64url de Gmail."""
    if not data:
        return ""

    raw = base64.urlsafe_b64decode(data.encode("utf-8"))
    return raw.decode("utf-8", errors="ignore")


def _html_to_text(html: str) -> str:
    """Convierte HTML simple de correos a texto plano preservando saltos."""
    soup = BeautifulSoup(html, "html.parser")
    return soup.get_text("\n")


def extract_text_from_payload(payload: Dict[str, Any]) -> str:
    """Extrae texto plano y/o HTML convertido desde un payload Gmail."""
    texts: List[str] = []

    def walk(part: Dict[str, Any]) -> None:
        mime_type = part.get("mimeType", "")
        body = part.get("body", {}) or {}
        data = body.get("data")

        if data and mime_type in {"text/plain", "text/html"}:
            content = _decode_gmail_base64(data)
            if mime_type == "text/html":
                content = _html_to_text(content)
            texts.append(content)

        for child in part.get("parts", []) or []:
            walk(child)

    walk(payload)
    return "\n".join(t for t in texts if t).strip()


def _header(headers: Iterable[Dict[str, str]], name: str, default: str = "") -> str:
    name_lower = name.lower()
    for h in headers:
        if h.get("name", "").lower() == name_lower:
            return h.get("value", default)
    return default


def fetch_gmail_messages(
    service,
    query: str,
    max_results: int = 50,
) -> List[GmailMessage]:
    """Busca mensajes Gmail con una query y devuelve correos normalizados."""

    response = service.users().messages().list(
        userId="me",
        q=query,
        maxResults=max_results,
    ).execute()

    items = response.get("messages", []) or []
    messages: List[GmailMessage] = []

    for item in items:
        raw_msg = service.users().messages().get(
            userId="me",
            id=item["id"],
            format="full",
        ).execute()

        payload = raw_msg.get("payload", {}) or {}
        headers = payload.get("headers", []) or []

        text = extract_text_from_payload(payload)

        messages.append(
            GmailMessage(
                gmail_id=raw_msg.get("id", ""),
                thread_id=raw_msg.get("threadId", ""),
                subject=_header(headers, "Subject"),
                sender=_header(headers, "From"),
                recipient=_header(headers, "To"),
                date=_header(headers, "Date"),
                snippet=raw_msg.get("snippet", ""),
                text=text,
            )
        )

    return messages


def build_bcp_query(days: int = 30, medio: str | None = None) -> str:
    """Query amplia Gmail para notificaciones BCP recientes.

    No filtramos por Cr?dito/D?bito en Gmail porque puede fallar por tildes/codificaci?n.
    El parser local se encarga de decidir si es consumo, cr?dito o d?bito.
    """
    return (
        'from:notificaciones@notificacionesbcp.com.pe '
        f'newer_than:{int(days)}d'
    )


def fetch_bcp_consumption_emails(
    project_dir: str | Path,
    days: int = 30,
    max_results: int = 200,
) -> List[GmailMessage]:
    """Lee notificaciones BCP recientes y deja que el parser filtre los consumos."""
    service = get_gmail_service(project_dir)

    query = build_bcp_query(days=days)

    msgs = fetch_gmail_messages(
        service,
        query=query,
        max_results=max_results,
    )

    print(f"Query Gmail amplia: {query} -> {len(msgs)} correos")

    return msgs


if __name__ == "__main__":
    project_dir = project_root_from_file(__file__)
    messages = fetch_bcp_consumption_emails(project_dir, days=30, max_results=10)

    print(f"Correos BCP encontrados: {len(messages)}")
    print("=" * 80)

    for msg in messages:
        print("Gmail ID:", msg.gmail_id)
        print("Subject:", msg.subject)
        print("Date:", msg.date)
        print("Snippet:", msg.snippet[:180])
        print("-" * 80)
