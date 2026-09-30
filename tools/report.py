"""Tages-Reporting: Summary der verarbeiteten Belege."""
from __future__ import annotations

import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def generate_report(belege: list[dict]) -> str:
    """Erstellt einen Tages-Summary-Text."""
    total = len(belege)
    exportiert = sum(1 for b in belege if b.get("status") == "exportiert")
    rueckfragen = sum(1 for b in belege if b.get("status") == "rueckfrage")
    fehler = sum(1 for b in belege if b.get("status") == "fehler")
    gesamt_brutto = sum(b.get("bruttobetrag", 0) or 0 for b in belege if b.get("status") == "exportiert")

    # Kontierungsmethoden
    vendor_cache = sum(1 for b in belege if b.get("kontierung_methode") == "vendor_cache")
    regel = sum(1 for b in belege if b.get("kontierung_methode") == "regel")
    llm = sum(1 for b in belege if b.get("kontierung_methode") == "llm")

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    report = f"""═══════════════════════════════════════
  FiBu-Agent — Tages-Report
  {timestamp}
═══════════════════════════════════════

Belege gesamt:      {total}
  ✓ Exportiert:     {exportiert}
  ⚠ Rückfragen:     {rueckfragen}
  ✗ Fehler:         {fehler}

Kontierung:
  Vendor-Cache:     {vendor_cache}
  Regelbasiert:     {regel}
  LLM (Claude):     {llm}

Gesamtvolumen:      {gesamt_brutto:,.2f} EUR
═══════════════════════════════════════"""

    if rueckfragen > 0:
        report += "\n\n⚠ OFFENE RÜCKFRAGEN:\n"
        for b in belege:
            if b.get("status") == "rueckfrage":
                report += f"  - {b.get('lieferant', '?')}: {b.get('rueckfrage', 'Konto unklar')}\n"

    logger.info("Report generiert: %d Belege, %d exportiert, %d Rückfragen", total, exportiert, rueckfragen)
    return report
