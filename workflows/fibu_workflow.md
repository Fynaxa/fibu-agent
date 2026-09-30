# FiBu-Workflow: Laufende Buchführung

## Kontenrahmen
- Standard: **SKR03** (überschreibbar via `KONTENRAHMEN` in `.env`)
- Regelwerk: `skr03_rules.json` — Pattern-basiertes Matching auf Lieferant + Verwendungszweck
- Haben-Konto Default: `1200` (Bank). Bei Erkennung von „bar"/„kasse" → `1000` (Kasse)
- MwSt-Schlüssel: `9` (19%), `8` (7%), `0` (steuerfrei/Versicherung/Miete)

## Kontierungs-Hierarchie
1. **Regel-Match** aus `skr03_rules.json` (Pattern im Lieferant oder Verwendungszweck)
2. **LLM-Kontierung** via Claude API — bekommt extrahierte Belegdaten + SKR03-Kontenrahmen als Kontext
3. **Rückfrage-Queue** wenn LLM-Konfidenz < 0.7 — Beleg wird als `status: rueckfrage` markiert

## Validierungsregeln
- Pflichtfelder: `belegdatum`, `bruttobetrag`, `lieferant`
- Betragsplausibilität: > 0 und < 100.000 EUR
- MwSt-Plausibilität: `mwst_betrag` ≈ `nettobetrag × mwst_satz / 100` (±2% Toleranz)
- Duplikatcheck: gleiche Rechnungsnummer + Lieferant + Betrag = Duplikat

## DATEV-Export
- Format: DATEV Buchungsstapel CSV (Semikolon-getrennt, UTF-8)
- Datumsformat im Export: TTMM (4-stellig)
- Dezimaltrennzeichen: Komma
- Ein Export pro Tag, Dateiname: `EXTF_YYYYMMDD.csv`
