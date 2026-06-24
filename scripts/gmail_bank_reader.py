from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


@dataclass
class GmailMessage:
    gmail_id: str
    thread_id: str
    date: str
    subject: str
    snippet: str
    text: str

    def to_dict(self) -> Dict[str, str]:
        return {
            "gmail_id": self.gmail_id,
            "thread_id": self.thread_id,
            "date": self.date,
            "subject": self.subject,
            "snippet": self.snippet,
            "text": self.text,
        }


def _debug_streamlit_secret_keys() -> str:
    """Devuelve solo nombres de keys, nunca valores."""
    try:
        import streamlit as st

        root_keys = list(st.secrets.keys())
        gmail_keys = []

        if "gmail" in st.secrets:
            try:
                gmail_keys = list(st.secrets["gmail"].keys())
            except Exception:
                gmail_keys = ["gmail_existe_pero_no_lista_keys"]

        return f"root_keys={root_keys}; gmail_keys={gmail_keys}"

    except Exception as exc:
        return f"no_se_pudo_leer_st_secrets: {exc}"


def _json_from_streamlit_secret(key: str):
    """Lee JSON desde Streamlit Secrets si existe.

    Espera:
    [gmail]
    credentials_json = """..."""
    token_json = """..."""
    """
    import json

    try:
        import streamlit as st
    except Exception:
        return None

    value = None

    # Forma principal: [gmail].credentials_json / [gmail].token_json
    try:
        if "gmail" in st.secrets:
            gmail_group = st.secrets["gmail"]
            if key in gmail_group:
                value = gmail_group[key]
    except Exception:
        value = None

    # Fallback: credentials_json / token_json en ra?z
    if value is None:
        try:
            if key in st.secrets:
                value = st.secrets[key]
        except Exception:
            pass

    if value is None:
        return None

    if isinstance(value, dict):
        return dict(value)

    value = str(value).strip()
    if not value:
        return None

    return json.loads(value)

def get_gmail_service(project_dir: str | Path):
    """Crea servicio Gmail usando Streamlit Secrets o archivos locales."""
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

    if token_info:
        creds = Credentials.from_authorized_user_info(token_info, SCOPES)
    elif token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())

        try:
            if token_path.exists():
                token_path.write_text(creds.to_json(), encoding="utf-8")
        except Exception:
            pass

    if not creds or not creds.valid:
        if credentials_info:
            raise RuntimeError(
                "Existe credentials_json en Streamlit Secrets, pero falta token_json válido. "
                "Copia también el contenido de secrets/token_gmail.json en Streamlit Secrets."
            )

        if not credentials_path.exists():
            raise FileNotFoundError(
                f"No existe credentials Gmail: {credentials_path}. "
                "En Streamlit Cloud configura [gmail].credentials_json y [gmail].token_json. "
                f"DEBUG_SECRETS: {_debug_streamlit_secret_keys()}"
            )

        flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES)
        creds = flow.run_local_server(port=0)

        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json(), encoding="utf-8")

    return build("gmail", "v1", credentials=creds)


def _get_header(headers: List[dict], name: str) -> str:
    name = name.lower()
    for h in headers or []:
        if str(h.get("name", "")).lower() == name:
            return str(h.get("value", "") or "")
    return ""


def _decode_base64url(data: str) -> str:
    if not data:
        return ""

    try:
        padded = data + "=" * (-len(data) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("utf-8"))
        return raw.decode("utf-8", errors="replace")
    except Exception:
        return ""


def _extract_text_from_payload(payload: Dict[str, Any]) -> str:
    if not payload:
        return ""

    mime_type = str(payload.get("mimeType", "") or "")
    body = payload.get("body", {}) or {}
    data = body.get("data", "")

    texts = []

    if data and ("text/plain" in mime_type or "text/html" in mime_type):
        texts.append(_decode_base64url(data))

    for part in payload.get("parts", []) or []:
        texts.append(_extract_text_from_payload(part))

    return "\n".join([t for t in texts if t])


def fetch_gmail_messages(service, query: str, max_results: int = 50) -> List[GmailMessage]:
    """Busca mensajes Gmail y devuelve texto usable para el parser."""
    results = (
        service.users()
        .messages()
        .list(userId="me", q=query, maxResults=int(max_results))
        .execute()
    )

    messages = results.get("messages", []) or []
    output: List[GmailMessage] = []

    for item in messages:
        msg_id = item.get("id")
        if not msg_id:
            continue

        msg = (
            service.users()
            .messages()
            .get(userId="me", id=msg_id, format="full")
            .execute()
        )

        payload = msg.get("payload", {}) or {}
        headers = payload.get("headers", []) or []

        subject = _get_header(headers, "Subject")
        date = _get_header(headers, "Date")
        snippet = msg.get("snippet", "") or ""
        text = _extract_text_from_payload(payload)

        output.append(
            GmailMessage(
                gmail_id=msg.get("id", ""),
                thread_id=msg.get("threadId", ""),
                date=date,
                subject=subject,
                snippet=snippet,
                text=text,
            )
        )

    return output


def build_bcp_query(days: int = 30, medio=None) -> str:
    """Query amplia para notificaciones BCP recientes."""
    return (
        "from:notificaciones@notificacionesbcp.com.pe "
        f"newer_than:{int(days)}d"
    )


def fetch_bcp_consumption_emails(
    project_dir: str | Path,
    days: int = 30,
    max_results: int = 200,
) -> List[GmailMessage]:
    """Lee notificaciones BCP recientes; el parser filtra crédito/débito."""
    service = get_gmail_service(project_dir)

    query = build_bcp_query(days=days)

    msgs = fetch_gmail_messages(
        service,
        query=query,
        max_results=int(max_results),
    )

    print(f"Query Gmail amplia: {query} -> {len(msgs)} correos")

    return msgs


if __name__ == "__main__":
    project = Path.cwd()
    emails = fetch_bcp_consumption_emails(project, days=5, max_results=20)

    print("Correos BCP encontrados:", len(emails))
    for e in emails[:10]:
        print("-", e.date, "|", e.subject, "|", e.snippet[:120])
