# Löschkonzept

**FiBu-Agent — KI-gestützte Belegverarbeitung**

Stand: April 2026

Gemäß Art. 5 Abs. 1 lit. e DSGVO (Speicherbegrenzung) und Art. 17 DSGVO (Recht auf Löschung).

---

## 1. Grundsätze

- Personenbezogene Daten werden nur so lange gespeichert, wie es für den Verarbeitungszweck oder aufgrund gesetzlicher Aufbewahrungspflichten erforderlich ist
- Nach Ablauf der Aufbewahrungsfrist werden Daten **automatisch oder auf Weisung** gelöscht
- Die Löschung wird im Audit-Trail protokolliert
- Handelsrechtliche und steuerrechtliche Aufbewahrungspflichten gehen dem Löschungsanspruch vor (Art. 17 Abs. 3 lit. b DSGVO)

## 2. Datenkategorien und Fristen

### 2.1 Buchungsbelege und Buchungssätze

| Datenart | Speicherort | Aufbewahrungsfrist | Rechtsgrundlage | Löschmethode |
|---|---|---|---|---|
| Original-Belege (PDF/Bilder) | `archiv/<mandant>/` | 10 Jahre ab Ende des Kalenderjahres der Erstellung | § 147 Abs. 1 Nr. 4 AO, § 257 Abs. 1 Nr. 4 HGB | Datei löschen |
| Extrahierte Belegdaten | SQLite `belege`-Tabelle | 10 Jahre ab Ende des Kalenderjahres | § 147 Abs. 1 Nr. 4 AO | Datensatz löschen |
| Buchungssätze / DATEV-Export | `outbox/<mandant>/` + DB | 10 Jahre ab Ende des Kalenderjahres | § 147 Abs. 1 Nr. 1 AO | Datei + Datensatz löschen |
| Audit-Trail | SQLite `audit_events`-Tabelle | 10 Jahre ab Ende des Kalenderjahres | GoBD Tz. 64 | Datensatz löschen |

**Fristberechnung**: Die 10-Jahres-Frist beginnt mit dem Ende des Kalenderjahres, in dem der Beleg erstellt/eingegangen ist. Beispiel: Rechnung vom 15.03.2026 → Löschung ab 01.01.2037.

### 2.2 Benutzerdaten

| Datenart | Speicherort | Aufbewahrungsfrist | Löschmethode |
|---|---|---|---|
| Benutzerkonto (Name, Passwort-Hash, Rolle) | SQLite `users`-Tabelle | Vertragsende + 3 Monate | Datensatz löschen oder anonymisieren |
| Login-Protokoll | SQLite `audit_events` | 2 Jahre | Datensatz löschen |

### 2.3 Temporäre Daten

| Datenart | Speicherort | Aufbewahrungsfrist | Löschmethode |
|---|---|---|---|
| OCR-Zwischenergebnisse | `.tmp/` | Max. 24 Stunden | Automatische Bereinigung |
| Session-Daten | Arbeitsspeicher (Flask) | Sitzungsende (max. 24h) | Automatisch |
| Pipeline-Status | Arbeitsspeicher | Sitzungsende | Automatisch |

### 2.4 Betriebsdaten

| Datenart | Speicherort | Aufbewahrungsfrist | Löschmethode |
|---|---|---|---|
| API-Kosten-Logs | `.tmp/api_costs.json` | 2 Jahre | Datei löschen |
| Datenbank-Backups | Backup-Verzeichnis | 30 Tage (Rotation) | Automatische Rotation |

## 3. Löschprozesse

### 3.1 Routinemäßige Löschung (automatisch)

**Temporäre Dateien**: Ein Bereinigungsjob löscht Dateien in `.tmp/`, die älter als 24 Stunden sind. Dies kann per Cronjob oder manuell ausgeführt werden:

```bash
find .tmp/ -type f -mtime +1 -not -name ".gitkeep" -delete
```

**Backups**: Das Backup-System rotiert automatisch und behält maximal 30 Sicherungen.

### 3.2 Fristablauf-Löschung (manuell/jährlich)

Am Anfang jedes Kalenderjahres sollte eine Prüfung durchgeführt werden:

1. Identifikation aller Belege, deren 10-Jahres-Frist abgelaufen ist
2. Prüfung, ob eventuell laufende Betriebsprüfungen einer Löschung entgegenstehen
3. Dokumentation der zu löschenden Daten
4. Löschung der Belege, Buchungssätze und zugehörigen Audit-Einträge
5. Protokollierung der Löschung

### 3.3 Löschung auf Anfrage (Betroffenenrechte)

Bei einem Löschantrag gemäß Art. 17 DSGVO:

1. **Prüfung der Berechtigung**: Ist der Antragsteller die betroffene Person?
2. **Prüfung der Aufbewahrungspflichten**: Stehen gesetzliche Pflichten der Löschung entgegen?
3. **Durchführung**:
   - Falls keine Aufbewahrungspflicht: Vollständige Löschung der personenbezogenen Daten
   - Falls Aufbewahrungspflicht: Einschränkung der Verarbeitung (Art. 18 DSGVO) statt Löschung, Löschung nach Fristablauf
4. **Bestätigung**: Schriftliche Bestätigung an den Antragsteller innerhalb eines Monats

### 3.4 Löschung bei Vertragsende

Nach Beendigung des Kundenvertrags:

| Schritt | Frist | Aktion |
|---|---|---|
| 1 | Sofort | Zugang deaktivieren (Benutzerkonten sperren) |
| 2 | 30 Tage | Datenexport bereitstellen (CSV/JSON) |
| 3 | 30 Tage | Nach Download-Bestätigung oder Fristablauf: Löschung aller Daten des Mandanten |
| 4 | Ausnahme | Belege innerhalb der 10-Jahres-Frist: Aufbewahrung in anonymisierter Form oder Rückgabe an Kunden |

## 4. Löschmethoden

| Methode | Anwendungsfall | Beschreibung |
|---|---|---|
| **Datei löschen** | PDFs, Exporte, Logs | Datei aus dem Dateisystem entfernen (`os.remove`) |
| **Datensatz löschen** | Datenbankeinträge | SQL `DELETE` + anschließend `VACUUM` |
| **Anonymisieren** | Benutzerdaten bei Aufbewahrungspflicht | Personenbezogene Felder durch Platzhalter ersetzen |
| **Verschlüsselungsschlüssel vernichten** | Fernet-verschlüsselte Felder | Löschen des Encryption Keys macht Daten unwiederbringlich unlesbar |

## 5. Protokollierung

Jede Löschung wird protokolliert:

```
Löschprotokoll:
- Datum der Löschung
- Art der gelöschten Daten (Kategorie)
- Anzahl der gelöschten Datensätze/Dateien
- Grund der Löschung (Fristablauf / Betroffenenantrag / Vertragsende)
- Durchgeführt von (Person/System)
```

Das Löschprotokoll selbst enthält **keine personenbezogenen Daten** der gelöschten Datensätze.

## 6. Verantwortlichkeiten

| Aufgabe | Verantwortlich |
|---|---|
| Tägliche Bereinigung temporärer Daten | System (automatisch) |
| Jährliche Fristprüfung | Administrator / Datenschutzbeauftragter |
| Bearbeitung von Löschanträgen | Verantwortlicher (Art. 4 Nr. 7 DSGVO) |
| Löschung bei Vertragsende | Administrator |
| Pflege dieses Löschkonzepts | Datenschutzbeauftragter |

---

*Dieses Löschkonzept wird mindestens jährlich überprüft und bei Bedarf aktualisiert. Letzte Prüfung: April 2026.*
