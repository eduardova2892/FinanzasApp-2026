"""Parsers reutilizables para correos bancarios de gastos diarios.

Ubicación recomendada en el proyecto:
    scripts/bank_email_parsers.py

Objetivo:
- Mantener app.py liviano.
- Centralizar la lógica de extracción de correos bancarios.
- Permitir agregar nuevos bancos sin reescribir la app.

Actualmente implementado:
- BCP: consumos con Tarjeta de Crédito y Tarjeta de Débito.

Preparado para futuro:
- GNB, BBVA, Interbank, etc. mediante parsers adicionales.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, List, Optional


MESES_ES = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}

PENDING_COLUMNS = [
    "gmail_id",
    "gmail_thread_id",
    "gmail_date",
    "subject",
    "banco",
    "medio_pago",
    "monto",
    "moneda",
    "empresa",
    "fecha",
    "hora",
    "fecha_hora_texto",
    "tarjeta_ultimos4",
    "numero_operacion",
    "categoria_sugerida",
    "descripcion_sugerida",
    "hash_importacion",
    "estado",
    "fecha_detectado_lima",
    "fecha_importado_lima",
    "resultado_importacion",
    "fuente",
]


def normalizar_ascii(texto: Any) -> str:
    """Quita tildes y normaliza texto para facilitar búsquedas."""
    if texto is None:
        return ""
    txt = str(texto)
    txt = unicodedata.normalize("NFKD", txt)
    return "".join(ch for ch in txt if not unicodedata.combining(ch))


def limpiar_espacios(texto: Any) -> str:
    """Convierte saltos de línea, tabs y espacios múltiples en un solo espacio."""
    return re.sub(r"\s+", " ", str(texto or "")).strip()


def parse_monto(valor: Any) -> Optional[float]:
    """Convierte montos tipo '1,234.50' o '1.234,50' a float."""
    if valor is None:
        return None
    s = str(valor).strip().replace(" ", "")
    if not s:
        return None

    # Caso latino: 1.234,50
    if "," in s and "." in s and s.rfind(",") > s.rfind("."):
        s = s.replace(".", "").replace(",", ".")
    else:
        # Caso común BCP: 1,234.50
        s = s.replace(",", "")

    try:
        return float(s)
    except Exception:
        return None


def parse_fecha_hora_es(texto: Any) -> tuple[str, str, str]:
    """Extrae fechas tipo '16 de junio de 2026 - 11:45 AM'.

    Retorna:
        fecha_iso, hora_24h, texto_original
    """
    original = limpiar_espacios(texto)
    txt = normalizar_ascii(original).lower()

    m = re.search(
        r"(\d{1,2})\s+de\s+([a-z]+)\s+de\s+(\d{4})\s*[-–]\s*(\d{1,2}):(\d{2})\s*(am|pm)",
        txt,
        flags=re.IGNORECASE,
    )
    if not m:
        return "", "", ""

    dia = int(m.group(1))
    mes_nombre = m.group(2).lower()
    mes = MESES_ES.get(mes_nombre)
    anio = int(m.group(3))
    hora = int(m.group(4))
    minuto = int(m.group(5))
    ampm = m.group(6).lower()

    if not mes:
        return "", "", ""
    if ampm == "pm" and hora != 12:
        hora += 12
    if ampm == "am" and hora == 12:
        hora = 0

    try:
        dt = datetime(anio, mes, dia, hora, minuto)
        return dt.date().isoformat(), dt.strftime("%H:%M"), m.group(0)
    except Exception:
        return "", "", ""


def sugerir_categoria(empresa: Any) -> str:
    """Clasificador simple por reglas. Ajustable y extensible."""
    e = normalizar_ascii(empresa).upper()
    reglas = [
        (["RAPPI", "PEDIDOSYA", "RESTAUR", "POLLO", "CAFE", "CAFETER", "PIZZA", "BURGER", "KFC", "MCDON", "STARBUCKS", "TAMBO"], "Alimentación"),
        (["UBER", "CABIFY", "YANGO", "TAXI", "DIDI", "BEAT"], "Movilidad"),
        (["WONG", "TOTTUS", "PLAZA VEA", "VIVANDA", "METRO", "MAKRO", "SUPERMERC"], "Supermercado"),
        (["INKAFARMA", "MIFARMA", "FARMACIA", "CLINICA", "MEDIC", "SALUD"], "Salud"),
        (["PET", "VET", "VETERIN"], "Mascotas"),
        (["PLIN", "YAPE", "TRANSFER", "ENVIO"], "Otros"),
        (["SHELL", "PRIMAX", "REPSOL", "GRIFO", "PECSA"], "Combustible"),
        (["NETFLIX", "SPOTIFY", "STEAM", "PLAYSTATION", "APPLE", "GOOGLE", "AMAZON", "CINE"], "Entretenimiento"),
    ]
    for keywords, categoria in reglas:
        if any(k in e for k in keywords):
            return categoria
    return "Otros"


def crear_hash_importacion(
    banco: str,
    medio_pago: str,
    fecha: str,
    monto: float,
    moneda: str,
    empresa: str,
    tarjeta_ultimos4: str = "",
    numero_operacion: str = "",
    gmail_id: str = "",
) -> str:
    """Crea hash estable para evitar duplicados."""
    base = "|".join(
        [
            str(banco).upper().strip(),
            str(medio_pago).upper().strip(),
            str(fecha).strip(),
            f"{float(monto):.2f}",
            str(moneda).upper().strip(),
            str(empresa).upper().strip(),
            str(tarjeta_ultimos4).strip(),
            str(numero_operacion).strip(),
            str(gmail_id).strip(),
        ]
    )
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:16]


def es_operacion_excluida(texto: Any) -> bool:
    """Evita registrar correos que no son gastos salientes."""
    low = normalizar_ascii(texto).lower()
    palabras_exclusion = [
        "rechazada",
        "rechazado",
        "anulada",
        "anulado",
        "reverso",
        "devolucion",
        "extorno",
        "abono",
        "recibiste",
        "transferencia recibida",
        "deposito recibido",
        "te depositaron",
    ]
    return any(p in low for p in palabras_exclusion)


def parse_bcp_email(
    texto: Any,
    *,
    gmail_id: str = "",
    gmail_thread_id: str = "",
    gmail_date: str = "",
    subject: str = "",
) -> Optional[Dict[str, Any]]:
    """Interpreta correos de consumo BCP.

    Soporta formatos como:
    - Realizaste un consumo de S/ 33.78 con tu Tarjeta de Crédito BCP en RAPPI SAC.
    - Tabla HTML con 'Total del consumo', 'Operación realizada', 'Empresa', etc.

    No importa abonos, reversos, operaciones rechazadas o transferencias recibidas.
    """
    original = str(texto or "")
    compacto = limpiar_espacios(original)
    ascii_compacto = normalizar_ascii(compacto)
    low = ascii_compacto.lower()

    if "bcp" not in low:
        return None
    if "realizaste un consumo" not in low and "consumo tarjeta" not in low and "total del consumo" not in low:
        return None
    if es_operacion_excluida(compacto):
        return None

    moneda = "PEN"
    monto: Optional[float] = None
    medio_pago: Optional[str] = None
    empresa = ""

    # 1) Formato del encabezado del correo.
    patron_principal = re.search(
        r"Realizaste\s+un\s+consumo\s+de\s+(S/|US\$|USD|\$)\s*([\d\.,]+)\s+con\s+tu\s+Tarjeta\s+de\s+(Cr[eé]dito|D[eé]bito)\s+BCP\s+en\s+(.+?)(?:\.|\n|$)",
        compacto,
        flags=re.IGNORECASE,
    )

    if patron_principal:
        simbolo = patron_principal.group(1).upper().replace(" ", "")
        monto = parse_monto(patron_principal.group(2))
        medio_txt = normalizar_ascii(patron_principal.group(3)).lower()
        medio_pago = "Credito" if "cr" in medio_txt else "Debito"
        empresa = patron_principal.group(4).strip(" .-\n\t")
        if simbolo in ["US$", "USD", "$"]:
            moneda = "USD"

    # 2) Formato de tabla HTML / texto extraído.
    if monto is None:
        m_monto = re.search(
            r"Total\s+del\s+consumo\s+(S/|US\$|USD|\$)\s*([\d\.,]+)",
            compacto,
            flags=re.IGNORECASE,
        )
        if not m_monto:
            m_monto = re.search(
                r"consumo\s+de\s+(S/|US\$|USD|\$)\s*([\d\.,]+)",
                compacto,
                flags=re.IGNORECASE,
            )
        if m_monto:
            simbolo = m_monto.group(1).upper().replace(" ", "")
            monto = parse_monto(m_monto.group(2))
            if simbolo in ["US$", "USD", "$"]:
                moneda = "USD"

    if not medio_pago:
        if re.search(r"Consumo\s+Tarjeta\s+de\s+Cr[eé]dito", compacto, flags=re.IGNORECASE) or re.search(r"Tarjeta\s+de\s+Cr[eé]dito\s+BCP", compacto, flags=re.IGNORECASE):
            medio_pago = "Credito"
        elif re.search(r"Consumo\s+Tarjeta\s+de\s+D[eé]bito", compacto, flags=re.IGNORECASE) or re.search(r"Tarjeta\s+de\s+D[eé]bito\s+BCP", compacto, flags=re.IGNORECASE):
            medio_pago = "Debito"

    if not empresa:
        m_emp = re.search(
            r"Empresa\s+(.+?)(?:\s+N[uú]mero\s+de\s+operaci[oó]n|\s+Monto|$)",
            compacto,
            flags=re.IGNORECASE,
        )
        if m_emp:
            empresa = m_emp.group(1).strip(" .-\n\t")
        else:
            m_emp2 = re.search(r"\s+en\s+([A-Z0-9ÁÉÍÓÚÑ\-\.\s]+?)\.", compacto)
            if m_emp2:
                empresa = m_emp2.group(1).strip()

    fecha, hora, fecha_hora_texto = parse_fecha_hora_es(compacto)

    tarjeta_ultimos4 = ""
    m_tar = re.search(r"(?:\*{4,}|x{4,}|X{4,})(\d{4})", compacto)
    if m_tar:
        tarjeta_ultimos4 = m_tar.group(1)

    numero_operacion = ""
    m_op = re.search(
        r"N[uú]mero\s+de\s+operaci[oó]n\s+([A-Za-z0-9\-]+)",
        compacto,
        flags=re.IGNORECASE,
    )
    if m_op:
        numero_operacion = m_op.group(1).strip()

    if monto is None or monto <= 0 or not medio_pago or not empresa:
        return None

    categoria = sugerir_categoria(empresa)
    hash_importacion = crear_hash_importacion(
        banco="BCP",
        medio_pago=medio_pago,
        fecha=fecha,
        monto=float(monto),
        moneda=moneda,
        empresa=empresa,
        tarjeta_ultimos4=tarjeta_ultimos4,
        numero_operacion=numero_operacion,
        gmail_id=gmail_id,
    )

    return {
        "gmail_id": gmail_id,
        "gmail_thread_id": gmail_thread_id,
        "gmail_date": gmail_date,
        "subject": subject,
        "banco": "BCP",
        "medio_pago": medio_pago,
        "monto": float(monto),
        "moneda": moneda,
        "empresa": empresa,
        "fecha": fecha,
        "hora": hora,
        "fecha_hora_texto": fecha_hora_texto,
        "tarjeta_ultimos4": tarjeta_ultimos4,
        "numero_operacion": numero_operacion,
        "categoria_sugerida": categoria,
        "descripcion_sugerida": f"{empresa} | BCP {medio_pago}",
        "hash_importacion": hash_importacion,
        "estado": "pendiente",
        "fecha_detectado_lima": "",
        "fecha_importado_lima": "",
        "resultado_importacion": "",
        "fuente": "Gmail BCP",
    }


def parse_gnb_email(
    texto: Any,
    *,
    gmail_id: str = "",
    gmail_thread_id: str = "",
    gmail_date: str = "",
    subject: str = "",
) -> Optional[Dict[str, Any]]:
    """Placeholder para GNB.

    Cuando tengamos ejemplos reales de correos GNB, implementaremos aquí su lógica.
    Mantener esta función permite que el DAG y app.py ya sean escalables.
    """
    return None


PARSER_REGISTRY: Dict[str, Callable[..., Optional[Dict[str, Any]]]] = {
    "BCP": parse_bcp_email,
    "GNB": parse_gnb_email,
}

# Queries por banco para Gmail. El DAG puede iterar esta configuración.
GMAIL_BANK_QUERIES = {
    "BCP": 'from:notificaciones@notificacionesbcp.com.pe newer_than:{days}d ("Tarjeta de Crédito BCP" OR "Tarjeta de Débito BCP" OR "Realizaste un consumo")',
    # GNB se activará cuando validemos remitente/asunto reales.
    "GNB": 'newer_than:{days}d ("GNB" OR "Banco GNB") ("consumo" OR "compra" OR "cargo")',
}


def parse_bank_email(
    text: str,
    banco: str = "BCP",
    gmail_id: str = "",
    gmail_thread_id: str = "",
    gmail_date: str = "",
    subject: str = "",
):
    """Parser robusto para correos bancarios BCP.

    Detecta consumos de tarjeta de cr?dito y d?bito, en PEN o USD.
    Usa subject + snippet/body cuando el correo HTML no trae todo el texto limpio.
    """
    import re
    import hashlib
    import unicodedata
    from datetime import datetime
    from email.utils import parsedate_to_datetime
    try:
        from zoneinfo import ZoneInfo
    except Exception:
        ZoneInfo = None

    def _norm(s):
        s = str(s or "")
        s = unicodedata.normalize("NFKD", s)
        return "".join(ch for ch in s if not unicodedata.combining(ch))

    def _clean(s):
        return re.sub(r"\s+", " ", str(s or "")).strip()

    def _parse_amount(s):
        s = str(s or "").strip().replace(" ", "")
        if "," in s and "." in s and s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
        try:
            return float(s)
        except Exception:
            return None

    def _categoria(empresa):
        e = _norm(empresa).upper()
        reglas = [
            (["RAPPI", "PEDIDOSYA", "RESTAUR", "POLLO", "CAFE", "PIZZA", "BURGER", "KFC", "MCDON", "STARBUCKS", "TAMBO"], "Alimentación"),
            (["UBER", "CABIFY", "YANGO", "TAXI", "DIDI", "BEAT"], "Movilidad"),
            (["WONG", "TOTTUS", "PLAZA VEA", "VIVANDA", "METRO", "MAKRO", "SUPERMERC"], "Supermercado"),
            (["INKAFARMA", "MIFARMA", "FARMACIA", "CLINICA", "MEDIC", "SALUD"], "Salud"),
            (["PET", "VET", "VETERIN"], "Mascotas"),
            (["PLIN", "YAPE", "TRANSFER", "PAGO", "ENVIO"], "Otros"),
            (["SHELL", "PRIMAX", "REPSOL", "GRIFO", "PECSA"], "Combustible"),
            (["NETFLIX", "SPOTIFY", "STEAM", "PLAYSTATION", "APPLE", "GOOGLE", "AMAZON"], "Entretenimiento"),
        ]
        for keys, cat in reglas:
            if any(k in e for k in keys):
                return cat
        return "Otros"

    meses = {
        "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
        "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
        "septiembre": 9, "setiembre": 9, "octubre": 10,
        "noviembre": 11, "diciembre": 12,
    }

    original = _clean(f"{subject} {text}")
    ascii_text = _clean(_norm(original))
    ascii_lower = ascii_text.lower()

    if banco.upper() == "BCP":
        if "bcp" not in ascii_lower:
            return None
        _tiene_consumo = (
            "realizaste un consumo" in ascii_lower
            or "consumo tarjeta" in ascii_lower
            or "realizaste un pago" in ascii_lower
            or "realizaste una transferencia" in ascii_lower
        )
        if not _tiene_consumo:
            return None

    monto = None
    moneda = "PEN"
    medio_pago = None
    empresa = ""

    # Principal: Realizaste un consumo de S/ 33.78 con tu Tarjeta de Cr?dito BCP en RAPPI SAC.
    m = re.search(
        r"Realizaste\s+un\s+(?:consumo|pago)\s+de\s+(S/|US\$|USD|\$)\s*([\d\.,]+)\s+con\s+tu\s+Tarjeta\s+de\s+(Credito|Debito)\s+BCP\s+en\s+(.+?)(?:\.(?:\s|$)|(?:\s+Fecha\s+y\s+hora)|\s+Por\s+tu\s+seguridad|$)",
        ascii_text,
        flags=re.IGNORECASE,
    )

    if m:
        simbolo = m.group(1).upper().replace(" ", "")
        monto = _parse_amount(m.group(2))
        medio_pago = "Credito" if m.group(3).lower().startswith("cred") else "Debito"
        empresa = m.group(4).strip(" .-\n\t")
        if simbolo in ["US$", "USD", "$"]:
            moneda = "USD"

    # Fallback por campos tipo tabla
    if monto is None:
        m_monto = re.search(
            r"Total\s+del\s+consumo\s+(S/|US\$|USD|\$)\s*([\d\.,]+)",
            ascii_text,
            flags=re.IGNORECASE,
        )
        if m_monto:
            simbolo = m_monto.group(1).upper().replace(" ", "")
            monto = _parse_amount(m_monto.group(2))
            if simbolo in ["US$", "USD", "$"]:
                moneda = "USD"

    if medio_pago is None:
        if re.search(r"Tarjeta\s+de\s+Credito|Consumo\s+Tarjeta\s+de\s+Credito", ascii_text, flags=re.IGNORECASE):
            medio_pago = "Credito"
        elif re.search(r"Tarjeta\s+de\s+Debito|Consumo\s+Tarjeta\s+de\s+Debito", ascii_text, flags=re.IGNORECASE):
            medio_pago = "Debito"

    if not empresa:
        m_emp = re.search(
            r"Empresa\s+(.+?)(?:\s+Numero\s+de\s+operacion|\s+Fecha|\s+Operacion|$)",
            ascii_text,
            flags=re.IGNORECASE,
        )
        if m_emp:
            empresa = m_emp.group(1).strip(" .-\n\t")

    # Fecha/hora BCP: 14 de junio de 2026 - 06:05 PM
    fecha = ""
    hora = ""
    fecha_hora_texto = ""

    mf = re.search(
        r"(\d{1,2})\s+de\s+([a-z]+)\s+de\s+(\d{4})\s*[-\u2013\u2014]\s*(\d{1,2}):(\d{2})\s*(am|pm)",
        ascii_text,
        flags=re.IGNORECASE,
    )

    if mf:
        dia = int(mf.group(1))
        mes = meses.get(mf.group(2).lower())
        anio = int(mf.group(3))
        hh = int(mf.group(4))
        mm = int(mf.group(5))
        ampm = mf.group(6).lower()

        if mes:
            if ampm == "pm" and hh < 12:
                hh += 12
            if ampm == "am" and hh == 12:
                hh = 0
            dt = datetime(anio, mes, dia, hh, mm)
            fecha = dt.date().isoformat()
            hora = dt.strftime("%H:%M")
            fecha_hora_texto = mf.group(0).lower()

    # Si no pudo extraer fecha del cuerpo, usa fecha Gmail en Lima.
    if not fecha and gmail_date:
        try:
            dtg = parsedate_to_datetime(gmail_date)
            if ZoneInfo is not None:
                dtg = dtg.astimezone(ZoneInfo("America/Lima"))
            fecha = dtg.date().isoformat()
            hora = dtg.strftime("%H:%M")
            fecha_hora_texto = str(gmail_date)
        except Exception:
            pass

    tarjeta_ultimos4 = ""
    mt = re.search(r"(?:\*{4,}|x{4,}|X{4,})(\d{4})", ascii_text)
    if mt:
        tarjeta_ultimos4 = mt.group(1)

    numero_operacion = ""
    mo = re.search(r"Numero\s+de\s+operacion\s+([A-Za-z0-9\-]+)", ascii_text, flags=re.IGNORECASE)
    if mo:
        numero_operacion = mo.group(1).strip()

    if monto is None or medio_pago is None or not empresa:
        return None

    categoria = _categoria(empresa)

    base_hash = "|".join([
        banco.upper(),
        medio_pago,
        str(fecha or ""),
        f"{float(monto):.2f}",
        moneda,
        empresa.upper(),
        tarjeta_ultimos4,
        numero_operacion,
        gmail_id,
    ])
    hash_importacion = hashlib.sha256(base_hash.encode("utf-8")).hexdigest()[:16]

    return {
        "gmail_id": gmail_id,
        "gmail_thread_id": gmail_thread_id,
        "gmail_date": gmail_date,
        "subject": subject,
        "banco": banco.upper(),
        "medio_pago": medio_pago,
        "monto": float(monto),
        "moneda": moneda,
        "empresa": empresa,
        "fecha": fecha,
        "hora": hora,
        "fecha_hora_texto": fecha_hora_texto,
        "tarjeta_ultimos4": tarjeta_ultimos4,
        "numero_operacion": numero_operacion,
        "categoria_sugerida": categoria,
        "descripcion_sugerida": f"{empresa} | {banco.upper()} {medio_pago}",
        "hash_importacion": hash_importacion,
        "estado": "pendiente",
        "fecha_detectado_lima": "",
        "fecha_importado_lima": "",
        "resultado_importacion": "",
        "fuente": f"Gmail {banco.upper()}",
    }


def normalize_pending_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """Asegura que todos los registros tengan las columnas esperadas."""
    return {col: record.get(col, "") for col in PENDING_COLUMNS}


def normalize_pending_records(records: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [normalize_pending_record(r) for r in records if r]


if __name__ == "__main__":
    # Smoke test mínimo desde terminal:
    sample = """
    Realizaste un consumo de S/ 33.78 con tu Tarjeta de Crédito BCP en RAPPI SAC.
    Fecha y hora 14 de junio de 2026 - 06:05 PM
    Número de Tarjeta de Crédito ************5654
    Empresa RAPPI SAC
    Número de operación 0000103738
    """
    print(parse_bank_email(sample))