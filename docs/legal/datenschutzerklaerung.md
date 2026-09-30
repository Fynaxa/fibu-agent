# Datenschutzerklärung

**FiBu-Agent — KI-gestützte Belegverarbeitung**

Stand: April 2026

---

## 1. Verantwortlicher

KI-Automation-Agency
Inhaber: Konstantin Konradi
c/o COCENTER, Koppoldstr. 1, 86551 Aichach
konstantinkonradi6@gmail.com

Datenschutzbeauftragter: nicht bestellt (Kleinunternehmen unter 20 Mitarbeiter, § 38 BDSG)

## 2. Überblick

Diese Datenschutzerklärung informiert über die Verarbeitung personenbezogener Daten bei der Nutzung der Software „FiBu-Agent". Die Software verarbeitet Buchungsbelege (Rechnungen, Quittungen) mittels KI-gestützter OCR und automatischer Kontierung.

## 3. Verarbeitete Daten

### 3.1 Nutzungsdaten (Web-UI)

| Datenkategorie | Beispiele | Rechtsgrundlage |
|---|---|---|
| Zugangsdaten | Benutzername, Passwort-Hash | Art. 6 Abs. 1 lit. b DSGVO (Vertragsdurchführung) |
| Sitzungsdaten | Session-Cookie, IP-Adresse | Art. 6 Abs. 1 lit. f DSGVO (berechtigtes Interesse) |
| Protokolldaten | Login-Zeitpunkt, Aktionen | Art. 6 Abs. 1 lit. f DSGVO (Sicherheit) |

### 3.2 Belegdaten

| Datenkategorie | Beispiele | Rechtsgrundlage |
|---|---|---|
| Geschäftsdaten | Rechnungsbeträge, Datum, Belegnummern | Art. 6 Abs. 1 lit. b DSGVO |
| Lieferantendaten | Firmenname, Adresse, USt-IdNr. | Art. 6 Abs. 1 lit. b DSGVO |
| Personenbezogene Daten auf Belegen | Ansprechpartner, E-Mail, IBAN | Art. 6 Abs. 1 lit. b/f DSGVO |

### 3.3 Buchungsdaten

| Datenkategorie | Beispiele | Rechtsgrundlage |
|---|---|---|
| Kontierungsergebnis | Soll-/Haben-Konto, BU-Schlüssel | Art. 6 Abs. 1 lit. b DSGVO |
| Audit-Trail | Verarbeitungsschritte, Zeitstempel, Hash-Kette | Art. 6 Abs. 1 lit. c DSGVO (rechtliche Verpflichtung, GoBD) |
| DATEV-Export | Buchungsstapel CSV | Art. 6 Abs. 1 lit. b DSGVO |

## 4. Zweck der Verarbeitung

Die Verarbeitung dient ausschließlich folgenden Zwecken:

1. **Vertragsdurchführung**: OCR-Extraktion, Kontierung und DATEV-Export von Buchungsbelegen
2. **Qualitätssicherung**: Double-Check-OCR, Validierung, Plausibilitätsprüfung
3. **Gesetzliche Pflichten**: GoBD-konforme Protokollierung, Aufbewahrungsfristen
4. **Sicherheit**: Zugangskontrolle, Audit-Logging, Verschlüsselung
5. **Abrechnung**: Erfassung der API-Nutzung zur Kostenabrechnung

## 5. Empfänger und Drittanbieter

### 5.1 Anthropic, Inc. (KI-Verarbeitung)

Für die OCR-Extraktion werden Belegbilder an die API von **Anthropic, Inc.** (San Francisco, USA) übermittelt.

- **Zweck**: Texterkennung und Datenextraktion aus Belegbildern
- **Rechtsgrundlage**: Art. 6 Abs. 1 lit. b DSGVO i.V.m. Art. 28 DSGVO
- **Drittlandtransfer**: USA — Absicherung über EU-Standardvertragsklauseln (SCC) gemäß Art. 46 Abs. 2 lit. c DSGVO
- **Datenverwendung durch Anthropic**: Anthropic verwendet API-Daten **nicht** für das Training von KI-Modellen (gemäß Anthropic API Terms of Service)
- **Speicherdauer bei Anthropic**: API-Anfragen werden für max. 30 Tage zu Sicherheits- und Missbrauchszwecken gespeichert

### 5.2 Keine weiteren Empfänger

Belegdaten werden an keine weiteren Dritten übermittelt, es sei denn, der Kunde exportiert sie selbst (z.B. DATEV-Export, Google Sheets).

## 6. Technische und organisatorische Maßnahmen

### 6.1 Verschlüsselung
- **At Rest**: Sensible Felder (IBAN, E-Mail, Telefon, Ansprechpartner) werden mit AES-128 (Fernet) verschlüsselt in der Datenbank gespeichert
- **In Transit**: Alle Verbindungen über HTTPS mit TLS 1.2+
- **Passwörter**: bcrypt-Hash (Kostenfaktor 12), niemals im Klartext gespeichert

### 6.2 Zugriffskontrolle
- Rollenbasiertes Berechtigungssystem (Admin/Benutzer)
- Mandantentrennung: Benutzer sehen nur zugewiesene Mandanten
- Session-basierte Authentifizierung mit CSRF-Schutz
- Rate-Limiting gegen Brute-Force-Angriffe (5 Login-Versuche/Minute)

### 6.3 Integrität und Nachvollziehbarkeit
- GoBD-konformer Audit-Trail mit SHA-256-Hash-Kette
- Manipulationserkennung durch verkettete Hashes
- Unveränderliche Protokollierung aller Verarbeitungsschritte

### 6.4 Verfügbarkeit
- SQLite mit WAL-Modus für konsistente Datenbank
- Automatisiertes Backup-System mit Rotation
- Docker-basiertes Deployment mit Health-Checks

## 7. Speicherdauer und Löschung

| Datenart | Aufbewahrungsfrist | Grundlage |
|---|---|---|
| Buchungsbelege (Original-PDFs) | 10 Jahre | § 147 AO, § 257 HGB |
| Buchungssätze / DATEV-Export | 10 Jahre | § 147 AO |
| Audit-Logs | 10 Jahre | GoBD |
| Benutzerdaten | Dauer des Vertragsverhältnisses + 3 Monate | Art. 17 DSGVO |
| Session-Daten | Sitzungsdauer (max. 24h) | Art. 5 Abs. 1 lit. e DSGVO |
| API-Kosten-Logs | 2 Jahre | Betriebliche Notwendigkeit |
| Temporäre OCR-Daten (.tmp/) | Max. 24 Stunden | Datensparsamkeit |

Nach Ablauf der Aufbewahrungsfrist werden die Daten gelöscht. Die Löschung wird im Audit-Log protokolliert.

## 8. Betroffenenrechte

Als betroffene Person haben Sie folgende Rechte:

| Recht | Artikel | Erläuterung |
|---|---|---|
| **Auskunft** | Art. 15 DSGVO | Welche Daten wir über Sie speichern |
| **Berichtigung** | Art. 16 DSGVO | Korrektur unrichtiger Daten |
| **Löschung** | Art. 17 DSGVO | Löschung, soweit keine Aufbewahrungspflicht besteht |
| **Einschränkung** | Art. 18 DSGVO | Einschränkung der Verarbeitung |
| **Datenübertragbarkeit** | Art. 20 DSGVO | Export Ihrer Daten in maschinenlesbarem Format |
| **Widerspruch** | Art. 21 DSGVO | Widerspruch gegen Verarbeitung auf Basis berechtigter Interessen |

**Kontakt für Betroffenenanfragen**: konstantinkonradi6@gmail.com

Anfragen werden innerhalb von **einem Monat** beantwortet (Art. 12 Abs. 3 DSGVO).

## 9. Besondere Hinweise

### 9.1 Keine automatisierte Einzelentscheidung
Die Software trifft keine rechtsverbindlichen Entscheidungen über Personen. Die automatische Kontierung betrifft Geschäftsvorfälle, nicht Personen. Jedes Ergebnis kann vom Benutzer überprüft und korrigiert werden.

### 9.2 Auftragsverarbeitung
Wenn der Kunde (z.B. Steuerkanzlei) die Software im Auftrag seiner Mandanten nutzt, ist ein Auftragsverarbeitungsvertrag (AVV) gemäß Art. 28 DSGVO abzuschließen. Eine Vorlage wird vom Anbieter bereitgestellt.

### 9.3 Datenverarbeitung in den USA
Die OCR-Verarbeitung erfolgt über die Anthropic API (USA). Der Kunde wird hierüber vor Vertragsschluss informiert und muss dem explizit zustimmen. Alternativ kann der Kunde — sobald verfügbar — eine EU-basierte KI-API nutzen.

## 10. Cookies und Tracking

Die Software verwendet ausschließlich **technisch notwendige Session-Cookies** zur Aufrechterhaltung der Anmeldung. Es werden **keine** Tracking-, Analyse- oder Werbe-Cookies eingesetzt.

| Cookie | Zweck | Speicherdauer | Typ |
|---|---|---|---|
| `session` | Sitzungsidentifikation | Sitzung (max. 24h) | Technisch notwendig |

Auf Grund der ausschließlichen Verwendung technisch notwendiger Cookies ist **kein Cookie-Consent-Banner** erforderlich (§ 25 Abs. 2 TTDSG).

## 11. Änderungen

Änderungen dieser Datenschutzerklärung werden dem Kunden mindestens 30 Tage vor Inkrafttreten mitgeteilt.

## 12. Aufsichtsbehörde

Sie haben das Recht, sich bei einer Datenschutz-Aufsichtsbehörde zu beschweren:

Landesbeauftragte für den Datenschutz Niedersachsen (LfD Niedersachsen)
Prinzenstraße 5, 30159 Hannover
poststelle@lfd.niedersachsen.de

---

*Hinweis: Diese Datenschutzerklärung ist eine Vorlage und muss vor der Verwendung von einem Datenschutzbeauftragten / Rechtsanwalt geprüft und an die konkrete Situation angepasst werden.*
