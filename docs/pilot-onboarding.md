# FiBu-Agent — Pilot-Onboarding

## Voraussetzungen

- Docker & Docker Compose installiert
- Anthropic API-Key (Claude Sonnet)
- 50–100 echte Eingangsrechnungen als PDF (idealerweise ein Monat)
- DATEV-Zugang zum Testimport

## 1. Installation

```bash
# Repository klonen / entpacken
cd FiBu-Agent

# SSL-Zertifikat generieren (einmalig)
./nginx/generate-cert.sh

# Konfiguration anlegen
cp .env.example .env
```

## 2. .env konfigurieren

Öffnen Sie `.env` und tragen Sie ein:

```
ANTHROPIC_API_KEY=sk-ant-...        # Ihr Claude API-Key
FLASK_SECRET_KEY=<zufälliger-string> # z.B. openssl rand -hex 32
ADMIN_PASSWORD=<sicheres-passwort>   # Initiales Admin-Passwort
DAILY_BUDGET_EUR=10.00               # Tägliches API-Budget
MONTHLY_BUDGET_EUR=100.00            # Monatliches API-Budget
```

## 3. System starten

```bash
docker compose up -d
```

Das System ist erreichbar unter:
- **https://localhost** (mit Sicherheitswarnung wegen Self-signed Cert)
- Login: `admin` / Ihr gewähltes `ADMIN_PASSWORD` (Standard: `admin`)

## 4. Mandant anlegen

1. Im Browser einloggen → **Mandanten** (Admin-Menü)
2. **Neuen Mandanten anlegen**:
   - **ID**: z.B. `M001`
   - **Name**: Firmenname des Mandanten
   - **Kontenrahmen**: SKR03 oder SKR04
   - **DATEV Berater-Nr.** und **Mandant-Nr.**: optional, wird im DATEV-Export verwendet
3. Speichern

## 5. Belege hochladen

1. Navigation → **Upload**
2. Mandant auswählen
3. PDF-Dateien auswählen (mehrere gleichzeitig möglich)
4. Unterstützte Formate: PDF, PNG, JPG, TIFF

## 6. Pipeline ausführen

1. Navigation → **Dashboard**
2. Mandant im Dropdown auswählen
3. **Run starten** klicken
4. Fortschritt wird live angezeigt (Balken + Log)

Die Pipeline durchläuft für jeden Beleg:
- OCR-Extraktion (Claude Vision)
- Automatische Kontierung nach Kontierungsregeln
- Validierung (Pflichtfelder, Beträge, Duplikate)
- Bei Unsicherheit: Rückfrage-Status

## 7. Ergebnisse prüfen

### Rückfragen bearbeiten
- Navigation → **Dashboard** → Rückfragen-Tabelle
- Jeder Beleg mit Status „Rückfrage" benötigt manuelle Prüfung
- Klick auf **Audit** zeigt den kompletten Verarbeitungsverlauf

### DATEV-Export herunterladen
- Navigation → **Mandant** → Details
- Unter **DATEV-Exporte**: CSV-Datei herunterladen
- Format: DATEV Buchungsstapel (EXTF, Version 700)

## 8. DATEV-Testimport

Siehe separate Anleitung: [DATEV-Testimport](datev-testimport.md)

## Täglicher Workflow

```
1. Neue Rechnungen als PDF sammeln
2. Im Web-UI hochladen (Upload-Seite)
3. Pipeline starten (Dashboard)
4. Rückfragen prüfen und ggf. korrigieren
5. DATEV-Export herunterladen
6. In DATEV importieren
```

## Fehlerbehebung

| Problem | Lösung |
|---------|--------|
| Login funktioniert nicht | `ADMIN_PASSWORD` in `.env` prüfen, Container neu starten |
| OCR-Ergebnis leer | PDF-Qualität prüfen (min. 150 DPI), Datei < 20 MB? |
| Falsche Kontierung | Kontierungsregeln in `workflows/skr03_rules.json` erweitern |
| API-Budget erschöpft | Budget in `.env` erhöhen, unter `/costs` aktuellen Verbrauch prüfen |
| Container startet nicht | `docker compose logs fibu-agent` prüfen |
| HTTPS-Warnung im Browser | Normal bei Self-signed Cert — Ausnahme hinzufügen |

## Kosten-Übersicht

- Pro Beleg ca. 0,02–0,05 € (Claude Sonnet, je nach Seitenzahl)
- 100 Belege/Monat ≈ 2–5 €
- Budget-Limits verhindern unerwartete Kosten

## Support

Bei Fragen oder Problemen:
- Monitoring-Seite: `/admin/monitoring` (nur Admin)
- Logs: `docker compose logs -f fibu-agent`
- API-Kosten: `/costs`
