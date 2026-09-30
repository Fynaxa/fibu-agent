# DATEV-Testimport — Anleitung

## Überblick

Der FiBu-Agent exportiert Buchungssätze im Format **DATEV Buchungsstapel (EXTF, Version 700)**. Diese Anleitung beschreibt, wie Sie den Export in DATEV Kanzlei-Rechnungswesen oder DATEV Unternehmen Online testen.

## 1. Export herunterladen

1. Im FiBu-Agent einloggen
2. Navigation → Mandant → Details
3. Unter **DATEV-Exporte** die gewünschte CSV-Datei herunterladen
4. Dateiname-Format: `EXTF_Buchungsstapel_<Mandant>_<Datum>.csv`

## 2. Export vorab prüfen

Vor dem Import in DATEV empfehlen wir eine manuelle Sichtprüfung:

### Header (Zeile 1)
```
"EXTF";700;21;"Buchungsstapel";...;
```
- `EXTF` = externes Format
- `700` = Format-Version
- `21` = Kategorie Buchungsstapel
- Berater-Nr. und Mandant-Nr. müssen mit DATEV übereinstimmen

### Spaltenüberschriften (Zeile 2)
```
Umsatz (ohne Soll/Haben-Kz);Soll/Haben-Kennzeichen;WKZ Umsatz;Kurs;...
```

### Buchungszeilen (ab Zeile 3)
Prüfen Sie stichprobenartig:
- **Beträge**: Komma als Dezimaltrenner (z.B. `119,00`)
- **Soll/Haben-Kz**: `S` oder `H`
- **Kontonummern**: 4-5-stellig (SKR03/04)
- **Belegdatum**: Format `TTMM` (z.B. `1503` für 15. März)
- **Buchungstext**: max. 60 Zeichen

## 3. Import in DATEV Kanzlei-Rechnungswesen

### Variante A: Stapelverarbeitung

1. **DATEV öffnen** → Mandant auswählen
2. **Bestand** → **Daten holen** → **Stapelverarbeitung**
3. Importformat: **ASCII (EXTF)**
4. Datei auswählen (die heruntergeladene CSV)
5. **Prüflauf** aktivieren (wichtig beim ersten Test!)
6. **Starten**

### Variante B: Belegbuchung

1. **Buchen** → **Stapelbuchung**
2. **Datei** → **Import** → **DATEV-Format**
3. CSV-Datei auswählen
4. Import mit **Prüflauf** starten

### Prüflauf-Ergebnisse

| Meldung | Bedeutung | Aktion |
|---------|-----------|--------|
| Konto nicht vorhanden | Kontennummer existiert nicht im Kontenrahmen | Konto in DATEV anlegen oder Kontierungsregel anpassen |
| Belegdatum ungültig | Format-Fehler im Datum | In FiBu-Agent prüfen, ggf. OCR-Ergebnis korrigieren |
| Doppelte Belegnummer | Beleg wurde bereits importiert | Duplikat aus Export entfernen |
| Berater/Mandant-Nr. stimmt nicht | Header-Daten passen nicht zum Mandanten | In FiBu-Agent Mandant-Einstellungen anpassen |

## 4. Import in DATEV Unternehmen Online

1. **Belege** → **Belegübertragung**
2. **Import** → **Buchungsdaten importieren**
3. Format: **Buchungsstapel (EXTF)**
4. Datei hochladen
5. Zuordnung prüfen → **Importieren**

## 5. Validierung nach Import

Nach erfolgreichem Import prüfen Sie in DATEV:

- [ ] **Anzahl Buchungssätze** stimmt mit FiBu-Agent überein
- [ ] **Summe Soll = Summe Haben** (Kontrollsumme)
- [ ] **Stichprobe**: 5 zufällige Buchungen gegen Original-Rechnungen prüfen
  - Betrag korrekt?
  - Konto korrekt?
  - Datum korrekt?
  - Buchungstext sinnvoll?
- [ ] **Keine Fehlermeldungen** im DATEV-Protokoll

## 6. Typische Anpassungen

### Kontonummern anpassen
Falls Ihre Kanzlei abweichende Kontonummern verwendet:
1. FiBu-Agent: `workflows/skr03_rules.json` (oder `skr04_rules.json`) bearbeiten
2. Kontonummern in `soll_konto` und `haben_konto` anpassen
3. Pipeline erneut laufen lassen

### Steuerschlüssel (BU-Schlüssel)
- `9` = Vorsteuer 19%
- `8` = Vorsteuer 7%
- Weitere BU-Schlüssel: siehe DATEV-Dokumentation

### Berater- und Mandant-Nummer
In der Mandanten-Verwaltung des FiBu-Agents eintragen:
1. Admin → Mandanten → Bearbeiten
2. DATEV Berater-Nr. und Mandant-Nr. eintragen
3. Nächster Export verwendet die korrekten Nummern

## 7. Empfohlener Pilot-Ablauf

```
Woche 1:  10 einfache Rechnungen (Büromaterial, Telefon, Porto)
          → Export → DATEV Prüflauf → Fehler dokumentieren

Woche 2:  30 gemischte Rechnungen (inkl. 7% MwSt, Reisekosten)
          → Export → DATEV Prüflauf → Kontierungsregeln anpassen

Woche 3:  Kompletter Monat (50–100 Rechnungen)
          → Export → DATEV Echtimport → Stichprobenprüfung

Woche 4:  Evaluation: Zeitersparnis, Fehlerquote, Anpassungsbedarf
```

## Hinweise

- **Immer zuerst Prüflauf** — nie blind in die produktive Buchhaltung importieren
- **Backup vor Import** — DATEV-Sicherung des Mandanten erstellen
- **Rückfragen zuerst bearbeiten** — nur Belege mit Status „exportiert" landen im Export
- Bei Fragen zum DATEV-Import: DATEV-Hotline 0800 3283823
