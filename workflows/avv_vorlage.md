# Auftragsverarbeitungsvertrag (AVV) — Vorlage

*gemäß Art. 28 DSGVO*

---

## 1. Gegenstand und Dauer

**Auftraggeber (Verantwortlicher):** [Steuerkanzlei / Mandant]
**Auftragnehmer (Auftragsverarbeiter):** [Ihr Unternehmen]

**Gegenstand:** Automatisierte Verarbeitung von Buchungsbelegen (Rechnungen, Quittungen) mittels KI-gestützter OCR-Extraktion, Kontierung und DATEV-Export.

**Dauer:** Entsprechend der Laufzeit des Dienstleistungsvertrags.

## 2. Art und Zweck der Verarbeitung

- Optische Zeichenerkennung (OCR) auf Belegbildern und PDFs
- Extraktion strukturierter Daten (Beträge, Daten, Lieferantennamen, IBAN)
- Automatische Kontierung nach SKR03/SKR04
- Export im DATEV-Buchungsstapelformat
- Archivierung verarbeiteter Belege (GoBD-konform)

## 3. Art der personenbezogenen Daten

- Lieferanten-/Rechnungsstellernamen
- IBAN und Bankverbindungen
- Ansprechpartner auf Rechnungen
- Rechnungsadressen
- E-Mail-Adressen und Telefonnummern (soweit auf Belegen)

## 4. Kategorien betroffener Personen

- Lieferanten und Geschäftspartner des Mandanten
- Mitarbeiter (bei Reisekostenabrechnungen, Gehaltsbelegen)

## 5. Technische und organisatorische Maßnahmen (TOMs)

### 5.1 Vertraulichkeit
- **Verschlüsselung at rest:** Sensible Felder (IBAN, E-Mail, Telefon) werden mit AES-128 (Fernet) verschlüsselt in der Datenbank gespeichert
- **Verschlüsselung in transit:** Alle API-Kommunikation über HTTPS/TLS 1.2+
- **Zugriffskontrolle:** Web-UI nur über authentifizierten Zugang (zu konfigurieren)
- **Mandantentrennung:** Strikt getrennte Verzeichnisse und Datenbankeinträge pro Mandant

### 5.2 Integrität
- **Audit-Log:** GoBD-konforme, manipulationssichere Protokollierung mit SHA-256-Hash-Kette
- **Double-Check OCR:** Zweifache unabhängige Extraktion zur Fehlererkennung
- **Validierung:** Pflichtfeld-, Betrags- und MwSt-Plausibilitätsprüfung vor Export

### 5.3 Verfügbarkeit
- **Backup:** Regelmäßige Sicherung der SQLite-Datenbank und Belegarchive empfohlen
- **Fehlerbehandlung:** Fehlerhafte Belege werden als Rückfrage markiert, nicht verworfen

### 5.4 Belastbarkeit
- **Budget-Cap:** Automatischer Stopp bei Erreichen des API-Kostenlimits
- **Rate-Limiting:** Kontrollierte API-Nutzung

## 6. Unterauftragsverarbeiter

| Dienst | Anbieter | Zweck | Standort |
|--------|----------|-------|----------|
| Claude API | Anthropic, Inc. | OCR & Kontierung | USA* |

*Hinweis: Die Nutzung der Claude API für OCR-Extraktion bedeutet, dass Belege temporär an Anthropic übermittelt werden. Anthropic verarbeitet API-Daten gemäß ihren Nutzungsbedingungen nicht für Modelltraining. Es wird empfohlen, dies dem Mandanten transparent zu kommunizieren.

## 7. Löschkonzept und Aufbewahrungsfristen

| Datenart | Aufbewahrungsfrist | Grundlage |
|----------|-------------------|-----------|
| Buchungsbelege (Original) | 10 Jahre | § 147 AO, § 257 HGB |
| DATEV-Exportdateien | 10 Jahre | § 147 AO |
| Audit-Logs | 10 Jahre | GoBD |
| API-Kosten-Logs | 2 Jahre | Betrieblich |
| Temporäre OCR-Daten | 24 Stunden | DSGVO Art. 5(1)(e) |

## 8. Pflichten des Auftragnehmers

- Verarbeitung nur auf dokumentierte Weisung des Auftraggebers
- Gewährleistung der Vertraulichkeit (alle Mitarbeiter sind auf Vertraulichkeit verpflichtet)
- Unterstützung bei Auskunfts-, Lösch- und Berichtigungsanfragen Betroffener
- Meldung von Datenschutzverletzungen innerhalb von 24 Stunden
- Löschung aller Daten nach Vertragsende (oder Rückgabe an Auftraggeber)

## 9. Kontrollrechte

Der Auftraggeber hat das Recht, die Einhaltung der TOMs zu überprüfen, einschließlich:
- Einsicht in Audit-Logs
- Prüfung der Verschlüsselungsmaßnahmen
- Verifizierung der Mandantentrennung

---

**Ort, Datum:** _______________

**Auftraggeber:** _______________

**Auftragnehmer:** _______________
