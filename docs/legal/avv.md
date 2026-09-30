# Auftragsverarbeitungsvertrag (AVV)

**gemäß Art. 28 DSGVO**

Stand: April 2026

---

## 1. Gegenstand und Dauer

**Auftraggeber (Verantwortlicher):** [Steuerkanzlei / Unternehmen — nachfolgend „Kunde"]

**Auftragnehmer (Auftragsverarbeiter):** [Ihr Unternehmen — nachfolgend „Anbieter"]

**Gegenstand:** Automatisierte Verarbeitung von Buchungsbelegen (Rechnungen, Quittungen) mittels KI-gestützter OCR-Extraktion, Kontierung und DATEV-Export im Rahmen der Software „FiBu-Agent".

**Dauer:** Dieser AVV gilt für die Laufzeit des Dienstleistungsvertrages. Er endet automatisch mit Beendigung des Hauptvertrags, unbeschadet der Pflichten aus § 10.

## 2. Art und Zweck der Verarbeitung

Die Verarbeitung umfasst:

1. Optische Zeichenerkennung (OCR) auf Belegbildern und PDFs
2. Extraktion strukturierter Daten (Beträge, Daten, Lieferantennamen, IBAN, Ansprechpartner)
3. Verschlüsselte Speicherung sensibler Daten (IBAN, E-Mail, Telefon)
4. Automatische Kontierung nach SKR03/SKR04
5. Validierung und Plausibilitätsprüfung
6. Export im DATEV-Buchungsstapelformat
7. GoBD-konforme Archivierung verarbeiteter Belege
8. Protokollierung im manipulationssicheren Audit-Trail

## 3. Art der personenbezogenen Daten

- Lieferanten-/Rechnungsstellernamen und -adressen
- IBAN und Bankverbindungen
- Ansprechpartner auf Rechnungen (Name, Funktion)
- E-Mail-Adressen und Telefonnummern (soweit auf Belegen enthalten)
- Rechnungsadressen
- USt-Identifikationsnummern

## 4. Kategorien betroffener Personen

- Lieferanten und Geschäftspartner des Kunden
- Mitarbeiter des Kunden (bei Reisekosten, Auslagen, Gehaltsbelegen)
- Ansprechpartner bei Lieferanten

## 5. Weisungsbindung

(1) Der Anbieter verarbeitet personenbezogene Daten ausschließlich auf dokumentierte Weisung des Kunden (Art. 28 Abs. 3 lit. a DSGVO). Die in diesem AVV festgelegte Verarbeitung gilt als Weisung.

(2) Der Anbieter informiert den Kunden unverzüglich, wenn er der Auffassung ist, dass eine Weisung gegen datenschutzrechtliche Vorschriften verstößt (Art. 28 Abs. 3 Satz 3 DSGVO).

(3) Weisungen, die über die vertraglich vereinbarte Leistung hinausgehen, bedürfen einer gesonderten Vereinbarung.

## 6. Vertraulichkeit

(1) Der Anbieter stellt sicher, dass alle Personen, die Zugang zu personenbezogenen Daten haben, zur Vertraulichkeit verpflichtet sind (Art. 28 Abs. 3 lit. b DSGVO).

(2) Die Vertraulichkeitsverpflichtung besteht auch nach Beendigung des Vertrages fort.

## 7. Technische und organisatorische Maßnahmen (TOMs)

Der Anbieter setzt die folgenden Maßnahmen gemäß Art. 32 DSGVO um:

### 7.1 Vertraulichkeit (Art. 32 Abs. 1 lit. b DSGVO)

| Maßnahme | Umsetzung |
|---|---|
| Verschlüsselung at rest | Sensible Felder (IBAN, E-Mail, Telefon, Ansprechpartner) mit AES-128 (Fernet) verschlüsselt |
| Verschlüsselung in transit | HTTPS/TLS 1.2+ für alle Verbindungen (nginx Reverse Proxy) |
| Zugriffskontrolle | Rollenbasiert (Admin/Benutzer), bcrypt-Passwort-Hashing (Kostenfaktor 12) |
| Mandantentrennung | Strikt getrennte Verzeichnisse, Datenbankeinträge und Benutzerberechtigungen pro Mandant |
| Brute-Force-Schutz | Rate-Limiting (5 Login-Versuche/Minute) |
| CSRF-Schutz | Token-basierter Schutz auf allen Formularen |

### 7.2 Integrität (Art. 32 Abs. 1 lit. b DSGVO)

| Maßnahme | Umsetzung |
|---|---|
| Audit-Trail | GoBD-konform, manipulationssicher mit SHA-256-Hash-Kette |
| Double-Check OCR | Zwei unabhängige Extraktionsdurchläufe, bei Abweichung Rückfrage |
| Validierung | Pflichtfeld-, Betrags- und MwSt-Plausibilitätsprüfung |
| Duplikaterkennung | Prüfung auf identische Belegnummern |

### 7.3 Verfügbarkeit (Art. 32 Abs. 1 lit. c DSGVO)

| Maßnahme | Umsetzung |
|---|---|
| Datenbank-Backup | SQLite Online-Backup-API, konfigurierbare Rotation (30 Sicherungen) |
| Fehlerbehandlung | Fehlerhafte Belege als Rückfrage markiert, nicht verworfen |
| Docker Health-Check | Automatischer Neustart bei Ausfall |
| WAL-Modus | Write-Ahead-Logging für konsistente Datenbankzugriffe |

### 7.4 Belastbarkeit (Art. 32 Abs. 1 lit. c DSGVO)

| Maßnahme | Umsetzung |
|---|---|
| Budget-Cap | Automatischer Stopp bei Erreichen des API-Kostenlimits |
| Rate-Limiting | Kontrollierte API-Nutzung zur Vermeidung von Überlastung |

## 8. Unterauftragsverarbeiter (Art. 28 Abs. 2 DSGVO)

### 8.1 Genehmigte Unterauftragsverarbeiter

| Dienst | Anbieter | Zweck | Standort | Absicherung |
|---|---|---|---|---|
| Claude API | Anthropic, Inc. | OCR-Texterkennung und Datenextraktion | USA | EU-SCC (Art. 46 Abs. 2 lit. c DSGVO) |

### 8.2 Hinweis zur Anthropic API

- Belegbilder werden zur OCR-Verarbeitung an Anthropic übermittelt
- Anthropic verarbeitet API-Daten **nicht** zum Training von KI-Modellen (API Terms of Service)
- API-Daten werden von Anthropic für max. 30 Tage zu Sicherheits-/Missbrauchszwecken gespeichert
- Der Kunde wird über diesen Unterauftragsverarbeiter vor Vertragsschluss informiert und stimmt zu

### 8.3 Änderungen bei Unterauftragsverarbeitern

Der Anbieter informiert den Kunden über beabsichtigte Änderungen in Bezug auf Unterauftragsverarbeiter mindestens **30 Tage** vor der Änderung. Der Kunde hat das Recht, der Änderung zu widersprechen. Erfolgt kein Widerspruch innerhalb von 14 Tagen, gilt die Zustimmung als erteilt.

## 9. Rechte der betroffenen Personen (Art. 28 Abs. 3 lit. e DSGVO)

(1) Der Anbieter unterstützt den Kunden bei der Erfüllung der Betroffenenrechte gemäß Art. 15–22 DSGVO.

(2) Wendet sich eine betroffene Person direkt an den Anbieter, leitet der Anbieter die Anfrage unverzüglich an den Kunden weiter.

(3) Technische Unterstützung:
- **Auskunft**: Export aller Daten eines Betroffenen als JSON
- **Berichtigung**: Korrektur über Web-UI oder Datenbank
- **Löschung**: Gemäß Löschkonzept, unter Berücksichtigung gesetzlicher Aufbewahrungspflichten
- **Datenübertragbarkeit**: Export in maschinenlesbarem Format (JSON/CSV)

## 10. Löschung und Rückgabe (Art. 28 Abs. 3 lit. g DSGVO)

(1) Nach Beendigung des Vertrages löscht der Anbieter alle personenbezogenen Daten des Kunden, sofern nicht gesetzliche Aufbewahrungspflichten entgegenstehen.

(2) Ablauf:
1. **Sofort**: Zugangsdeaktivierung (Benutzerkonten sperren)
2. **30 Tage**: Datenexport bereitstellen (CSV/JSON) auf Wunsch des Kunden
3. **Nach 30 Tagen**: Löschung aller Mandantendaten (Belege, Buchungssätze, Audit-Logs)
4. **Ausnahme**: Belege innerhalb der 10-Jahres-Frist (§ 147 AO) — Rückgabe an Kunden oder Aufbewahrung in anonymisierter Form

(3) Die Löschung wird dem Kunden schriftlich bestätigt.

## 11. Meldung von Datenschutzverletzungen (Art. 33, 34 DSGVO)

(1) Der Anbieter meldet dem Kunden Datenschutzverletzungen **unverzüglich, spätestens innerhalb von 24 Stunden** nach Kenntnisnahme.

(2) Die Meldung enthält mindestens:
- Art der Verletzung
- Betroffene Datenkategorien und Personenzahl (geschätzt)
- Wahrscheinliche Folgen
- Ergriffene und vorgeschlagene Abhilfemaßnahmen

## 12. Kontrollrechte (Art. 28 Abs. 3 lit. h DSGVO)

(1) Der Kunde hat das Recht, die Einhaltung dieses AVV zu überprüfen, einschließlich:
- Einsicht in Audit-Logs (über Web-UI oder Export)
- Prüfung der Verschlüsselungsmaßnahmen
- Verifizierung der Mandantentrennung
- Einsicht in die technische Dokumentation

(2) Der Anbieter stellt dem Kunden alle erforderlichen Informationen zum Nachweis der Einhaltung seiner Pflichten zur Verfügung.

(3) Inspektionen vor Ort sind nach Abstimmung mit angemessener Vorlaufzeit (14 Tage) möglich.

## 13. Haftung

Die Haftung der Parteien richtet sich nach Art. 82 DSGVO sowie den Regelungen im Hauptvertrag (AGB).

---

## Anlagen

- **Anlage 1**: Technische und organisatorische Maßnahmen (§ 7 dieses AVV)
- **Anlage 2**: Genehmigte Unterauftragsverarbeiter (§ 8.1 dieses AVV)
- **Anlage 3**: Löschkonzept (separates Dokument)

---

**Ort, Datum:** _______________

**Auftraggeber (Kunde):**

Name: _______________
Funktion: _______________
Unterschrift: _______________

**Auftragnehmer (Anbieter):**

Name: _______________
Funktion: _______________
Unterschrift: _______________

---

*Hinweis: Dieser AVV ist eine Vorlage und muss vor der Verwendung von einem Datenschutzbeauftragten/Rechtsanwalt geprüft und an die konkrete Situation angepasst werden.*
