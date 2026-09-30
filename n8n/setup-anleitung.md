# n8n + FiBu-Agent — Setup-Anleitung

## Voraussetzungen

- **Server**: VPS mit min. 4 GB RAM (z.B. Hetzner CX22, ~10 €/Monat)
- **Domain**: z.B. `fibu.deine-domain.de` + `n8n.deine-domain.de`
- **Docker + Docker Compose** installiert

## 1. Repository auf den Server

```bash
git clone <repo-url> ~/fibu-agent
cd ~/fibu-agent
```

## 2. Umgebungsvariablen

```bash
cp .env.example .env
nano .env
```

Folgende Keys eintragen:

```bash
# === Pflicht ===
ANTHROPIC_API_KEY=sk-ant-...          # Claude API
FLASK_SECRET_KEY=$(openssl rand -hex 32)
ADMIN_PASSWORD=sicheres-passwort

# === n8n ===
N8N_USER=admin
N8N_PASSWORD=sicheres-n8n-passwort
N8N_HOST=n8n.deine-domain.de
N8N_ENCRYPTION_KEY=$(openssl rand -hex 32)
POSTGRES_PASSWORD=$(openssl rand -hex 16)

# === E-Mail (SMTP) ===
SMTP_FROM=agent@deine-domain.de
ADMIN_EMAIL=du@deine-domain.de

# === Google Sheets ===
GSHEET_CRM_ID=1abc...xyz              # Sheet-ID aus der URL

# === Lead-Generierung ===
GOOGLE_PLACES_API_KEY=AIza...
HUNTER_API_KEY=...

# === Social Media (optional) ===
LINKEDIN_ACCESS_TOKEN=...
LINKEDIN_PERSON_ID=...
INSTAGRAM_BUSINESS_ID=...
INSTAGRAM_ACCESS_TOKEN=...
X_BEARER_TOKEN=...

# === Termine ===
CALENDLY_LINK=https://calendly.com/dein-name/15min

# === Rechnungen ===
FIRMA_NAME=Dein Unternehmen GmbH
FIRMA_ADRESSE=Musterstr. 1, 80331 München
FIRMA_UST_ID=DE123456789
FIRMA_IBAN=DE89 3704 0044 0532 0130 00

# === Budget ===
DAILY_BUDGET_EUR=10.00
MONTHLY_BUDGET_EUR=100.00
```

## 3. SSL-Zertifikat

### Option A: Self-Signed (Schnellstart)
```bash
./nginx/generate-cert.sh
```

### Option B: Let's Encrypt (Produktion)
```bash
sudo apt install certbot
sudo certbot certonly --standalone -d fibu.deine-domain.de -d n8n.deine-domain.de
# Zertifikate nach nginx/ssl/ kopieren
```

## 4. Google Sheets vorbereiten

1. Neues Google Sheet erstellen
2. Tabs anlegen gemäß `templates/crm_sheets_struktur.md`:
   - Suchaufträge
   - Leads
   - Kunden
   - Rechnungen
   - Content-Kalender
   - Content-Log
   - Regel-Log
   - Uptime-Log
3. Sheet-ID aus URL kopieren → `GSHEET_CRM_ID` in `.env`

## 5. Starten

```bash
cd n8n/
docker compose up -d
```

Dienste:
- **n8n**: `https://n8n.deine-domain.de` (oder `http://localhost:5678`)
- **FiBu-Agent**: `https://fibu.deine-domain.de` (oder `http://localhost:8080`)

## 6. n8n einrichten

### 6.1 Credentials anlegen

In n8n → Settings → Credentials:

| Name | Typ | Werte |
|---|---|---|
| **Anthropic** | Anthropic API | API Key aus `.env` |
| **Google Sheets** | Google Sheets OAuth2 | Service Account JSON oder OAuth |
| **SMTP** | SMTP | Host, Port, User, Password deines Mailservers |
| **IMAP E-Mail** | IMAP | Host, Port, User, Password |

### 6.2 Workflows importieren

In n8n → Workflows → Import from File:

1. `01_lead_generierung.json`
2. `02_email_eingang.json`
3. `03_sales_followup.json`
4. `04_fibu_pipeline.json`
5. `05_rechnungsstellung.json`
6. `06_ceo_report.json`
7. `07_onboarding.json`
8. `08_mahnwesen.json`
9. `09_kontierung_lernen.json`
10. `10_uptime_monitoring.json`
11. `11_backup.json`
12. `12_churn_praevention.json`
13. `13_social_media_content.json`

### 6.3 Credentials in Workflows zuordnen

Nach dem Import: Jeden Workflow öffnen und die Credentials den Nodes zuordnen:
- Alle "Anthropic"-Nodes → Anthropic Credential
- Alle "Google Sheets"-Nodes → Google Sheets Credential
- Alle "SMTP"-Nodes → SMTP Credential
- IMAP-Node (Workflow 02) → IMAP Credential

### 6.4 Workflows aktivieren

Empfohlene Reihenfolge:

| Phase | Workflows | Wann aktivieren |
|---|---|---|
| **Sofort** | 10 (Uptime), 11 (Backup) | Direkt nach Setup |
| **Tag 1** | 06 (CEO-Report), 04 (FiBu-Pipeline) | Wenn FiBu-Agent läuft |
| **Tag 2** | 02 (E-Mail-Eingang), 01 (Lead-Gen) | Wenn E-Mail + Sheets funktionieren |
| **Woche 1** | 03 (Follow-up), 07 (Onboarding) | Wenn erste Leads da sind |
| **Woche 2** | 05 (Rechnung), 08 (Mahnwesen) | Wenn erste Kunden da sind |
| **Woche 2** | 09 (Kontierung-Lernen), 12 (Churn) | Wenn FiBu-Pipeline stabil |
| **Woche 3** | 13 (Social Media) | Wenn Content-Strategie steht |

## 7. Erster Test

### Lead-Generierung testen
1. In Google Sheets → Tab "Suchaufträge" einen Eintrag anlegen:
   - suchbegriff: `Steuerberater`
   - stadt: `München`
   - radius_m: `10000`
   - aktiv: `TRUE`
2. In n8n → Workflow 01 → "Execute Workflow" (manuell)
3. Prüfen: Neue Einträge im Tab "Leads"?

### E-Mail testen
1. Sende eine Test-E-Mail an deine IMAP-Adresse
2. In n8n → Workflow 02 → "Execute Workflow" (manuell)
3. Prüfen: Antwort erhalten? CRM-Eintrag erstellt?

### FiBu-Pipeline testen
1. Im FiBu-Agent Web-UI einen Beleg hochladen
2. In n8n → Workflow 04 → "Execute Workflow" (manuell)
3. Prüfen: Pipeline gestartet? Benachrichtigung erhalten?

## 8. Monitoring

### Tägliche Kontrolle (automatisch)
- CEO-Report kommt täglich um 7:00 Uhr per E-Mail
- Uptime-Alerts kommen sofort bei Problemen

### Wöchentliche Kontrolle (empfohlen)
- n8n UI: Executions → Fehlgeschlagene Runs prüfen
- Google Sheets: Leads-Tab prüfen (Qualität, Score-Verteilung)
- Google Sheets: Rechnungen-Tab prüfen (offene Posten)

### n8n API für Claude-Zugriff
Falls du möchtest, dass Claude Code (dieses CLI) Workflows direkt in n8n ändern kann:

1. n8n → Settings → API → Create API Key
2. Notiere: `N8N_API_KEY` und `N8N_API_URL`
3. Claude kann dann per HTTP-Request Workflows erstellen/ändern

## Kosten-Übersicht

| Posten | Monatlich |
|---|---|
| Hetzner VPS (CX22) | 10 € |
| Claude API (200 Belege + Content + E-Mails) | 20–50 € |
| Domain | 1 € |
| Mailgun/Postmark (500 E-Mails) | 0–10 € |
| Google Sheets | 0 € |
| Hunter.io (100 Lookups) | 0–35 € |
| **Gesamt** | **~30–100 €/Monat** |

## 9. Video-Pipeline einrichten (ElevenLabs + HeyGen)

Die Video-Pipeline erstellt automatisch Videos mit deiner geklonten Stimme und deinem geklonten Avatar.

### 9.1 ElevenLabs — Stimme klonen (einmalig, 2 Minuten)

1. Account erstellen: [elevenlabs.io](https://elevenlabs.io)
2. Plan: **Starter** (5 €/Monat, 30 Min Audio) reicht für ~12 Videos/Monat
3. **Voice Lab** → **Add Generative or Cloned Voice** → **Instant Voice Cloning**
4. 30 Sekunden Audio von dir hochladen:
   - Ruhige Umgebung, kein Hall
   - Normales Sprechtempo, Deutsch
   - Am besten: Einen Absatz aus einem deiner Texte vorlesen
5. Voice-ID kopieren → `ELEVENLABS_VOICE_ID` in `.env`
6. API Key: **Profile** → **API Key** → kopieren → `ELEVENLABS_API_KEY` in `.env`

### 9.2 HeyGen — Avatar klonen (einmalig, 5 Minuten)

1. Account erstellen: [heygen.com](https://heygen.com)
2. Plan: **Creator** (24 $/Monat, 15 Min Video) reicht für ~12 Videos/Monat
3. **Avatars** → **Create Avatar** → **Instant Avatar**
4. 2-Minuten-Video von dir aufnehmen:
   - Frontal in die Kamera schauen
   - Gute Beleuchtung (Tageslicht oder Ringlicht)
   - Neutraler Hintergrund
   - Normal sprechen (Inhalt egal — HeyGen lernt dein Gesicht, nicht den Text)
5. Avatar-ID kopieren → `HEYGEN_AVATAR_ID` in `.env`
6. API Key: **Settings** → **API** → kopieren → `HEYGEN_API_KEY` in `.env`

### 9.3 HeyGen + ElevenLabs verbinden

HeyGen hat ElevenLabs nativ integriert:
1. In HeyGen: **Settings** → **Integrations** → **ElevenLabs** → API Key eintragen
2. Deine ElevenLabs-Stimme erscheint jetzt in HeyGen als Voice-Option
3. Die Voice-ID in HeyGen kopieren → `HEYGEN_ELEVENLABS_VOICE_ID` in `.env`

### 9.4 Die komplette Video-Pipeline

```
Mo/Mi/Fr 7:00 Uhr (automatisch):

  1. Claude schreibt Skript
     ↓ (Titel, Szenen, Beschreibung, Tags)
  2. ElevenLabs generiert Audio
     ↓ (deine geklonte Stimme spricht das Skript)
  3. HeyGen erstellt Video
     ↓ (dein geklonter Avatar + Lippensync zum Audio)
  4. Upload zu YouTube / TikTok / Instagram Reels
     ↓ (automatisch, mit Titel, Beschreibung, Tags)
  5. Bestätigungs-E-Mail an dich
```

### 9.5 Kosten pro Video

| Komponente | 30-Sek-Short | 3-Min-YouTube | 12 Videos/Monat |
|---|---|---|---|
| Claude (Skript) | ~0,01 € | ~0,02 € | ~0,15 € |
| ElevenLabs (Audio) | ~0,15 € | ~0,90 € | ~5–10 € |
| HeyGen (Video) | ~0,50 € | ~3,00 € | ~15–35 € |
| **Gesamt** | **~0,65 €** | **~3,90 €** | **~20–45 €** |

## Troubleshooting

| Problem | Lösung |
|---|---|
| n8n nicht erreichbar | `docker compose logs n8n` prüfen |
| Workflow schlägt fehl | n8n → Executions → Details → Error-Message lesen |
| E-Mails kommen nicht an | SMTP-Credentials prüfen, SPF/DKIM/DMARC einrichten |
| Google Sheets Fehler | OAuth Token abgelaufen → neu authentifizieren |
| Claude API 429 | Rate Limit erreicht → Budget in `.env` prüfen |
| FiBu-Agent nicht erreichbar | `docker compose logs fibu-agent` prüfen |
