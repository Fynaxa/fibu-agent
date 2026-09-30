"""E-Rechnung Parser: ZUGFeRD (PDF+XML) und XRechnung (reines XML).

Unterstützte Formate:
- ZUGFeRD 1.0 / 2.0 (Factur-X): eingebettetes XML im PDF
- XRechnung 2.x: reines XML nach EN 16931 / CII-Syntax

Das Modul extrahiert alle Rechnungsfelder ohne LLM-Aufruf —
strukturierte E-Rechnungen liefern 100% zuverlässige Daten.
"""
from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path

logger = logging.getLogger(__name__)

# XML-Namespaces für ZUGFeRD 1.0, 2.0 / Factur-X und XRechnung (CII)
_NS = {
    # ZUGFeRD 1.0
    "rsm10": "urn:ferd:CrossIndustryDocument:invoice:1p0",
    "ram10": "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:12",
    "udt10": "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:15",
    # ZUGFeRD 2.0 / Factur-X / XRechnung (CII)
    "rsm": "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100",
    "ram": "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100",
    "udt": "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100",
    "qdt": "urn:un:unece:uncefact:data:standard:QualifiedDataType:100",
}


def _find(elem: ET.Element, *paths: str) -> str | None:
    """Sucht einen Textwert in mehreren alternativen XPath-Pfaden."""
    for path in paths:
        found = elem.find(path, _NS)
        if found is not None and found.text:
            return found.text.strip()
    return None


def _find_amount(elem: ET.Element, *paths: str) -> float | None:
    val = _find(elem, *paths)
    if val is None:
        return None
    try:
        return float(val.replace(",", "."))
    except ValueError:
        return None


def _parse_cii_xml(root: ET.Element) -> dict:
    """Parst CII-Syntax (ZUGFeRD 2.0 / Factur-X / XRechnung)."""
    result: dict = {"erechnung_format": "cii", "ocr_konfidenz": 1.0}

    # Rechnungsnummer
    result["rechnungsnummer"] = _find(
        root,
        "rsm:ExchangedDocument/ram:ID",
        "rsm10:HeaderExchangedDocument/ram10:ID",
    )

    # Rechnungsdatum
    datum_raw = _find(
        root,
        "rsm:ExchangedDocument/ram:IssueDateTime/udt:DateTimeString",
        "rsm10:HeaderExchangedDocument/ram10:IssueDateTime/udt10:DateTimeString",
    )
    if datum_raw:
        # Format meist YYYYMMDD
        d = datum_raw.strip()
        if len(d) == 8 and d.isdigit():
            result["belegdatum"] = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
        else:
            result["belegdatum"] = d

    # Lieferant (SellerTradeParty)
    result["lieferant"] = _find(
        root,
        ".//ram:SellerTradeParty/ram:Name",
        ".//ram10:SellerTradeParty/ram10:Name",
    )

    # Beträge aus MonetarySummation
    netto = _find_amount(
        root,
        ".//ram:SpecifiedTradeSettlementHeaderMonetarySummation/ram:TaxBasisTotalAmount",
        ".//ram10:SpecifiedTradeSettlementMonetarySummation/ram10:TaxBasisTotalAmount",
    )
    mwst = _find_amount(
        root,
        ".//ram:SpecifiedTradeSettlementHeaderMonetarySummation/ram:TaxTotalAmount",
        ".//ram10:SpecifiedTradeSettlementMonetarySummation/ram10:TaxTotalAmount",
    )
    brutto = _find_amount(
        root,
        ".//ram:SpecifiedTradeSettlementHeaderMonetarySummation/ram:GrandTotalAmount",
        ".//ram10:SpecifiedTradeSettlementMonetarySummation/ram10:GrandTotalAmount",
    )

    if netto is not None:
        result["nettobetrag"] = round(netto, 2)
    if mwst is not None:
        result["mwst_betrag"] = round(abs(mwst), 2)
    if brutto is not None:
        result["bruttobetrag"] = round(brutto, 2)

    # MwSt-Satz
    mwst_rate = _find_amount(
        root,
        ".//ram:ApplicableTradeTax/ram:RateApplicablePercent",
        ".//ram10:ApplicableTradeTax/ram10:ApplicablePercent",
    )
    if mwst_rate is not None:
        result["mwst_satz"] = mwst_rate

    # Reverse Charge prüfen
    steuer_typ = _find(
        root,
        ".//ram:ApplicableTradeTax/ram:CategoryCode",
        ".//ram10:ApplicableTradeTax/ram10:CategoryCode",
    )
    if steuer_typ in ("AE", "K", "G"):
        result["reverse_charge"] = True
        result["mwst_satz"] = 0.0

    # Währung
    waehrung = _find(
        root,
        ".//ram:InvoiceCurrencyCode",
        ".//ram:TaxCurrencyCode",
        ".//ram10:InvoiceCurrencyCode",
    )
    result["waehrung"] = waehrung or "EUR"

    # IBAN des Lieferanten
    iban = _find(
        root,
        ".//ram:PayeeSpecifiedCreditorFinancialInstitution/ram:IBANID",
        ".//ram:SpecifiedTradeSettlementPaymentMeans/ram:PayeePartyCreditorFinancialAccount/ram:IBANID",
        ".//ram10:PayeePartyCreditorFinancialAccount/ram10:IBANID",
    )
    if iban:
        result["iban"] = iban

    # Verwendungszweck aus Zahlungsreferenz
    verwendung = _find(
        root,
        ".//ram:PaymentReference",
        ".//ram10:PaymentReference",
    )
    if not verwendung:
        verwendung = _find(root, ".//ram:Name", ".//ram10:Name")
    result["verwendungszweck"] = verwendung or result.get("lieferant", "E-Rechnung")

    return result


def parse_xml(xml_content: str | bytes) -> dict:
    """Parst ZUGFeRD/XRechnung XML-Inhalt in ein Beleg-Dict."""
    if isinstance(xml_content, str):
        xml_content = xml_content.encode("utf-8")
    try:
        root = ET.fromstring(xml_content)
        # Namespace aus Root-Tag ermitteln
        tag = root.tag
        if "CrossIndustryInvoice" in tag or "CrossIndustryDocument" in tag:
            return _parse_cii_xml(root)
        # Fallback: trotzdem versuchen
        return _parse_cii_xml(root)
    except ET.ParseError as exc:
        raise ValueError(f"Ungültiges XML: {exc}") from exc


def _extract_xml_from_pdf_bytes(pdf_bytes: bytes) -> bytes | None:
    """Extrahiert eingebettetes ZUGFeRD-XML aus rohen PDF-Bytes.

    Strategie: sucht nach komprimierten Streams die XML-Inhalt enthalten,
    oder direkt nach <?xml ... im Byte-Stream.
    """
    # 1. Direkter XML-Block im PDF (manchmal unkomprimiert eingebettet)
    xml_start = pdf_bytes.find(b"<?xml")
    if xml_start != -1:
        # Ende des XML-Blocks suchen (letztes > vor nächstem PDF-Objekt)
        chunk = pdf_bytes[xml_start:xml_start + 200_000]
        # ZUGFeRD Root-Tags
        for root_tag in (b"CrossIndustryInvoice", b"CrossIndustryDocument", b"Invoice"):
            close_tag = b"</" + root_tag + b">"
            xml_end = chunk.rfind(close_tag)
            if xml_end != -1:
                raw = chunk[: xml_end + len(close_tag)]
                logger.info("ZUGFeRD-XML direkt gefunden (%d Bytes)", len(raw))
                return raw

    # 2. Komprimierte Streams (FlateDecode) durchsuchen
    for match in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", pdf_bytes, re.DOTALL):
        stream_data = match.group(1)
        if len(stream_data) < 50:
            continue
        try:
            decompressed = zlib.decompress(stream_data)
            if b"<?xml" in decompressed and b"CrossIndustry" in decompressed:
                logger.info("ZUGFeRD-XML in komprimiertem Stream gefunden")
                xml_start = decompressed.find(b"<?xml")
                return decompressed[xml_start:]
        except zlib.error:
            continue

    return None


def beleg_aus_erechnung(path: Path) -> dict | None:
    """Hauptfunktion: Extrahiert Belegdaten aus ZUGFeRD-PDF oder XRechnung-XML.

    Gibt None zurück wenn kein E-Rechnung-Format erkannt wurde.
    Bei Erfolg: dict kompatibel mit dem restlichen Pipeline-Format.
    """
    path = Path(path)
    suffix = path.suffix.lower()

    try:
        if suffix == ".xml":
            xml_content = path.read_bytes()
            if b"CrossIndustry" not in xml_content and b"Invoice" not in xml_content:
                logger.debug("%s enthält kein erkanntes E-Rechnung-Format", path.name)
                return None
            result = parse_xml(xml_content)
            result["erechnung_quelle"] = "xrechnung_xml"
            logger.info("XRechnung geparst: %s → %s", path.name, result.get("lieferant"))
            return result

        if suffix == ".pdf":
            pdf_bytes = path.read_bytes()
            xml_bytes = _extract_xml_from_pdf_bytes(pdf_bytes)
            if xml_bytes is None:
                logger.debug("%s enthält kein eingebettetes ZUGFeRD-XML", path.name)
                return None
            result = parse_xml(xml_bytes)
            result["erechnung_quelle"] = "zugferd_pdf"
            logger.info("ZUGFeRD-XML geparst: %s → %s", path.name, result.get("lieferant"))
            return result

    except Exception as exc:
        logger.warning("E-Rechnung Parse-Fehler für %s: %s", path.name, exc)
        return None

    return None


def ist_erechnung(path: Path) -> bool:
    """Schnellcheck: enthält dieses PDF eine ZUGFeRD-XML-Einbettung?"""
    path = Path(path)
    if path.suffix.lower() == ".xml":
        try:
            content = path.read_bytes()
            return b"CrossIndustry" in content
        except Exception:
            return False
    if path.suffix.lower() == ".pdf":
        try:
            pdf_bytes = path.read_bytes()
            # Schnellcheck: ZUGFeRD-Kennzeichen im PDF
            return (
                b"ZUGFeRD" in pdf_bytes
                or b"Factur-X" in pdf_bytes
                or b"factur-x" in pdf_bytes
                or b"CrossIndustryInvoice" in pdf_bytes
                or b"CrossIndustryDocument" in pdf_bytes
            )
        except Exception:
            return False
    return False
