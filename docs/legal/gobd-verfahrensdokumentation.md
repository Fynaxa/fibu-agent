# GoBD-Verfahrensdokumentation

**FiBu-Agent — KI-gestützte Belegverarbeitung**

Stand: April 2026

Gemäß den Grundsätzen zur ordnungsmäßigen Führung und Aufbewahrung von Büchern, Aufzeichnungen und Unterlagen in elektronischer Form sowie zum Datenzugriff (GoBD, BMF-Schreiben vom 28.11.2019, BStBl I S. 1269).

---

## 1. Allgemeine Beschreibung

### 1.1 Einsatzzweck
FiBu-Agent ist ein KI-gestütztes System zur automatisierten Verarbeitung von Eingangsrechnungen (Buchungsbelegen). Das System unterstützt Steuerberater und Unternehmen bei der Vorkontierung von Belegen und dem Export in DATEV-kompatible Formate.

### 1.2 Einsatzgebiet
- Optische Zeichenerkennung (OCR) auf Buchungsbelegen (PDF, Bilddateien)
- Automatische Extraktion strukturierter Daten (Lieferant, Betrag, Datum, MwSt)
- Vorkontierung nach SKR03 oder SKR04 auf Basis regelbasierter Zuordnung
- Validierung der extrahierten Daten
- Export als DATEV-Buchungsstapel (EXTF-Format, Version 700)

### 1.3 Abgrenzung
FiBu-Agent ist ein **vorgelagertes System**. Es erzeugt Buchungssätze, die in DATEV oder vergleichbare Buchhaltungssoftware importiert werden. Die endgültige Buchführung erfolgt im nachgelagerten System. FiBu-Agent ist **kein Buchhaltungssystem** und ersetzt nicht die Prüfung durch den Steuerberater.

## 2. Ordnungsmäßigkeit (Tz. 36–58 GoBD)

### 2.1 Nachvollziehbarkeit und Nachprüfbarkeit

Jeder Beleg durchläuft eine dokumentierte Verarbeitungskette:

```
Eingang (Upload/Inbox) → OCR-Extraktion → Validierung → Kontierung → Export
```

Jeder Schritt wird im **Audit-Trail** protokolliert mit:
- Zeitstempel (ISO 8601)
- Schritt-Bezeichnung (z.B. `ocr_extraction`, `validation`, `kontierung`, `export`)
- Ergebnis (Daten, Fehlermeldungen, Konfidenzwerte)
- SHA-256-Hash des Verarbeitungsschritts
- Verketteter Hash (Verweis auf den vorherigen Hash)

Die Hash-Kette stellt sicher, dass nachträgliche Änderungen am Audit-Trail erkennbar sind.

### 2.2 Vollständigkeit

- Jeder in das System eingehende Beleg erhält eine eindeutige **Beleg-ID** (UUID v4)
- Belege können nicht gelöscht werden, nur als „verarbeitet" oder „fehlerhaft" markiert
- Ein Beleg kann die folgenden Status annehmen:

| Status | Bedeutung |
|---|---|
| `neu` | Eingegangen, noch nicht verarbeitet |
| `verarbeitet` | OCR und Kontierung abgeschlossen |
| `exportiert` | Im DATEV-Export enthalten |
| `rueckfrage` | Manuelle Prüfung erforderlich |
| `fehler` | Verarbeitung fehlgeschlagen |

### 2.3 Richtigkeit

- **Double-Check-OCR**: Zwei unabhängige KI-Durchläufe; bei Abweichung → Status „Rückfrage"
- **Plausibilitätsprüfung**: MwSt-Berechnung (Brutto = Netto + MwSt ±0,02 €)
- **Duplikaterkennung**: Prüfung auf identische Belegnummern innerhalb eines Mandanten
- **Kontierungsregeln**: Deterministische Regelzuordnung nach Lieferantenname/Rechnungstext (längster Match gewinnt)

### 2.4 Zeitgerechte Buchung

FiBu-Agent verarbeitet Belege zeitnah nach Eingang. Der Zeitpunkt des Eingangs und der Verarbeitung wird im Audit-Trail dokumentiert.

### 2.5 Ordnung

- Belege werden pro **Mandant** getrennt verarbeitet und gespeichert
- Kontenrahmen (SKR03/SKR04) wird pro Mandant konfiguriert
- DATEV-Exporte enthalten Berater-Nr. und Mandant-Nr. im Header

## 3. Datensicherheit (Tz. 103–109 GoBD)

### 3.1 Zugriffskontrolle

| Maßnahme | Umsetzung |
|---|---|
| Authentifizierung | Benutzername + Passwort (bcrypt-Hash, Kostenfaktor 12) |
| Autorisierung | Rollenbasiert (Admin/Benutzer), Mandantentrennung |
| Brute-Force-Schutz | Rate-Limiting (5 Versuche/Minute) |
| Session-Schutz | CSRF-Token auf allen Formularen |
| Transportverschlüsselung | HTTPS/TLS 1.2+ (nginx Reverse Proxy) |

### 3.2 Datenverschlüsselung

Sensible Felder werden mit AES-128 (Fernet) verschlüsselt in der Datenbank gespeichert:
- IBAN
- E-Mail-Adressen
- Telefonnummern
- Ansprechpartnernamen

### 3.3 Datensicherung

- SQLite Online-Backup-API für konsistente Sicherungen im laufenden Betrieb
- Konfigurierbare Backup-Rotation (Standard: 30 Sicherungen)
- Restore-Funktion mit automatischer Sicherheitskopie des aktuellen Zustands

## 4. Unveränderbarkeit (Tz. 59–67 GoBD)

### 4.1 Audit-Trail

Der Audit-Trail ist das zentrale Instrument zur Sicherstellung der Unveränderbarkeit:

```
Audit-Event:
{
  beleg_id:    "550e8400-e29b-41d4-a716-446655440000"
  schritt:     "ocr_extraction"
  zeitpunkt:   "2026-04-12T14:30:00+02:00"
  ergebnis:    { ... extrahierte Daten ... }
  hash:        "a1b2c3...  (SHA-256 über den Inhalt)"
  prev_hash:   "x9y8z7...  (Hash des vorherigen Eintrags)"
}
```

- Jeder Eintrag enthält den SHA-256-Hash des vorherigen Eintrags
- Nachträgliche Manipulation eines Eintrags bricht die Hash-Kette
- Die Integrität kann jederzeit über die Web-UI oder per Skript verifiziert werden

### 4.2 Belegarchivierung

- Original-Belege (PDFs/Bilder) werden im Archiv-Verzeichnis pro Mandant abgelegt
- Original-Dateien werden nach der Verarbeitung nicht verändert
- Verschiebung: `inbox/<mandant>/` → `archiv/<mandant>/`

### 4.3 Keine Löschfunktion für Belege

Das System bietet **keine Funktion zum Löschen** von Belegen oder Buchungssätzen innerhalb der Aufbewahrungsfrist. Belege können nur als fehlerhaft markiert, aber nicht entfernt werden.

## 5. Maschinelle Auswertbarkeit (Tz. 124 GoBD)

### 5.1 Exportformate

| Datenart | Format | Beschreibung |
|---|---|---|
| Buchungssätze | DATEV EXTF CSV | Standardformat für DATEV-Import |
| Belegdaten | JSON | Strukturierte Daten aller Belege |
| Audit-Trail | SQLite / JSON | Komplett exportierbar |

### 5.2 Datenzugriff

- Z1 (Unmittelbarer Zugriff): Über Web-UI — Suche, Filterung, Anzeige einzelner Belege
- Z2 (Mittelbarer Zugriff): Über DATEV-Export und JSON-Export
- Z3 (Datenträgerüberlassung): Über Datenbank-Backup und Datei-Export

## 6. Aufbewahrung (Tz. 113–123 GoBD)

### 6.1 Aufbewahrungsfristen

| Dokumentenart | Frist | Rechtsgrundlage |
|---|---|---|
| Buchungsbelege (Original) | 10 Jahre | § 147 Abs. 1 Nr. 4 AO, § 257 Abs. 1 Nr. 4 HGB |
| Buchungssätze (DATEV-Export) | 10 Jahre | § 147 Abs. 1 Nr. 1 AO |
| Audit-Trail | 10 Jahre | GoBD Tz. 64 |
| Verfahrensdokumentation (dieses Dokument) | Für die Dauer der Aufbewahrungsfrist der Unterlagen | GoBD Tz. 154 |

### 6.2 Technische Umsetzung

- Aufbewahrung in SQLite-Datenbank + Dateisystem
- Regelmäßige Backups (empfohlen: täglich)
- Integrität durch Hash-Kette prüfbar
- Migration bei Systemwechsel über JSON/CSV-Export

## 7. Verarbeitungskette im Detail

### 7.1 Belegeingang

```
Quelle: Upload über Web-UI oder Ablage in Inbox-Verzeichnis
 → Dateiformate: PDF, PNG, JPG, TIFF
 → Max. Dateigröße: 20 MB
 → Prüfung: Datei nicht leer, PDF-Integrität
 → Ergebnis: Beleg-ID vergeben, Status "neu"
```

### 7.2 OCR-Extraktion

```
Eingabe: Original-Beleg (PDF/Bild)
 → Methode: Claude Vision API (Anthropic)
 → Optional: Double-Check (zweiter unabhängiger Durchlauf)
 → Extrahierte Felder:
   - Lieferant (Name, Adresse)
   - Rechnungsnummer
   - Rechnungsdatum
   - Nettobetrag, MwSt-Betrag, Bruttobetrag
   - MwSt-Satz
   - IBAN (verschlüsselt gespeichert)
   - Buchungstext
 → Ergebnis: Strukturierter Datensatz + Konfidenzwert
```

### 7.3 Validierung

```
Prüfungen:
 → Pflichtfelder vorhanden (Lieferant, Datum, Betrag)
 → MwSt-Plausibilität: Brutto = Netto + MwSt (±0,02 €)
 → Datumsformat gültig
 → Duplikatprüfung (Belegnummer + Mandant)
 → Bei Fehler: Status "rueckfrage" mit Begründung
```

### 7.4 Kontierung

```
Methode: Regelbasierte Zuordnung
 → Eingabe: Lieferantenname, Buchungstext
 → Regelwerk: workflows/skr03_rules.json bzw. skr04_rules.json
 → Algorithmus: Longest-Pattern-Match (spezifischste Regel gewinnt)
 → Ergebnis: Soll-Konto, Haben-Konto, BU-Schlüssel
 → Konfidenz: "matched" oder "default" (Fallback auf Konto 4900/6300)
```

### 7.5 DATEV-Export

```
Format: EXTF Buchungsstapel, Version 700
 → Header: Berater-Nr., Mandant-Nr., Wirtschaftsjahr
 → Spalten: 116 Felder gemäß DATEV-Spezifikation
 → Validierung vor Export:
   - Kontonummern 4-5-stellig
   - Datumsformat TTMM
   - S/H-Kennzeichen
   - Beträge mit Komma-Dezimaltrenner
   - Buchungstext ≤ 60 Zeichen
```

## 8. Systemkomponenten

| Komponente | Technologie | Zweck |
|---|---|---|
| Web-UI | Flask (Python) | Benutzerschnittstelle |
| OCR | Anthropic Claude API | Texterkennung |
| Datenbank | SQLite (WAL-Modus) | Belegdaten, Audit-Trail |
| Dateisystem | Verzeichnisstruktur pro Mandant | Original-Belege, Exporte |
| Kontierung | Python (regelbasiert) | Kontozuordnung |
| Export | Python | DATEV-EXTF-Generierung |
| Webserver | nginx + gunicorn | HTTPS, Reverse Proxy |
| Container | Docker | Deployment |

## 9. Rollen und Berechtigungen

| Rolle | Berechtigungen |
|---|---|
| **Admin** | Vollzugriff: Benutzerverwaltung, Mandantenverwaltung, Monitoring, alle Mandanten |
| **Benutzer** | Eingeschränkt: Upload, Pipeline-Start, Audit-Einsicht — nur für zugewiesene Mandanten |

## 10. Änderungshistorie

| Datum | Version | Änderung |
|---|---|---|
| April 2026 | 1.0 | Erstfassung |

---

*Diese Verfahrensdokumentation ist gemäß GoBD Tz. 151–155 zu pflegen und bei wesentlichen Änderungen am System zu aktualisieren. Sie ist für die Dauer der Aufbewahrungsfrist der mit dem System verarbeiteten Unterlagen aufzubewahren.*
