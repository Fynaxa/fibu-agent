# CRM — Google Sheets Struktur

Erstelle ein Google Sheet mit der ID `GSHEET_CRM_ID` und folgenden Tabs:

---

## Tab 1: Suchaufträge

| Spalte | Beschreibung | Beispiel |
|---|---|---|
| suchbegriff | Google Places Suchbegriff | Steuerberater |
| stadt | Zielstadt | München |
| radius_m | Suchradius in Metern | 10000 |
| aktiv | Soll gesucht werden? | TRUE |
| letzte_suche | Datum der letzten Suche | 2026-04-12 |

## Tab 2: Leads

| Spalte | Beschreibung | Beispiel |
|---|---|---|
| firma | Firmenname | Müller & Partner GmbH |
| website | URL | https://mueller-partner.de |
| stadt | Standort | München |
| branche | Branche | Steuerberatung |
| email | Kontakt-E-Mail | info@mueller-partner.de |
| telefon | Telefonnummer | 089-1234567 |
| score | Lead-Score (0-100) | 75 |
| status | Aktueller Status | neu / kontaktiert / follow-up-1 / follow-up-2 / follow-up-3 / qualifiziert / angebot / kunde / abgelehnt |
| kontaktiert_am | Letzter Kontakt | 2026-04-12 10:30 |
| quelle | Herkunft | Google Places / E-Mail / Website / Empfehlung |
| notizen | Freitext | Interesse an Belegautomatisierung |
| erstellt_am | Erstellungsdatum | 2026-04-12 |

## Tab 3: Kunden

| Spalte | Beschreibung | Beispiel |
|---|---|---|
| kunden_id | Mandant-ID (= FiBu-Agent Mandant-ID) | M001 |
| firma | Firmenname | Müller & Partner GmbH |
| ansprechpartner | Hauptkontakt | Dr. Thomas Müller |
| email | Kontakt-E-Mail | t.mueller@mueller-partner.de |
| adresse | Vollständige Adresse | Marienplatz 1, 80331 München |
| kontenrahmen | SKR03 oder SKR04 | SKR03 |
| preis_pro_beleg | Stückpreis in € | 0.15 |
| monatspauschale | Mindestbetrag/Monat in € | 0 |
| belege_vormonat | Anzahl Belege letzter Monat | 85 |
| status | aktiv / pausiert / gekündigt | aktiv |
| onboarding_am | Vertragsbeginn | 2026-04-01 |
| vertragsende | Vertragsende (leer = unbefristet) | |
| letzte_aktivitaet | Letzter Upload/Pipeline-Run | 2026-04-10 |

## Tab 4: Rechnungen

| Spalte | Beschreibung | Beispiel |
|---|---|---|
| rechnungsnummer | Eindeutige Nr. | RE-202604-M001 |
| kunde | Firmenname | Müller & Partner GmbH |
| email | Rechnungs-E-Mail | buchhaltung@mueller-partner.de |
| monat | Abrechnungsmonat | 2026-03 |
| netto | Nettobetrag | 12.75 |
| brutto | Bruttobetrag | 15.17 |
| status | versendet / zahlungserinnerung / mahnung_1 / mahnung_2 / bezahlt | versendet |
| datum | Rechnungsdatum | 2026-04-01 |
| bezahlt_am | Zahlungseingang | |

## Tab 5: Content-Kalender

| Spalte | Beschreibung | Beispiel |
|---|---|---|
| datum | Veröffentlichungsdatum | 2026-04-14 |
| typ | Content-Typ | tipp / case_study / behind_scenes / news |
| thema | Thema/Arbeitstitel | 5 Zeichen dass deine Buchhaltung KI braucht |
| plattformen | Zielplattformen (kommasep.) | linkedin,instagram |
| status | geplant / gepostet | geplant |
| notizen | Besondere Hinweise | Mit Screenshot vom Dashboard |

## Tab 6: Content-Log

| Spalte | Beschreibung | Beispiel |
|---|---|---|
| datum | Veröffentlichungsdatum | 2026-04-14 |
| plattform | Einzelne Plattform | linkedin |
| status | gepostet / fehler | gepostet |
| typ | Content-Typ | tipp |
| thema | Thema | 5 Zeichen dass deine Buchhaltung KI braucht |

## Tab 7: Regel-Log

| Spalte | Beschreibung | Beispiel |
|---|---|---|
| datum | Zeitpunkt | 2026-04-12 14:30 |
| lieferant | Lieferantenname | Hetzner Online GmbH |
| pattern | Suchtext-Pattern | hetzner online |
| altes_konto | Bisheriges Konto | 4900 |
| neues_konto | Korrigiertes Konto | 4963 |
| status | automatisch_hinzugefuegt / abgelehnt_einzelfall | automatisch_hinzugefuegt |
| begruendung | Warum ja/nein | Spezifischer Hosting-Anbieter, Konto 4963 = EDV/Hosting |

## Tab 8: Uptime-Log

| Spalte | Beschreibung | Beispiel |
|---|---|---|
| zeitpunkt | ISO-Timestamp | 2026-04-12T14:30:00Z |
| fibu_ok | FiBu-Agent erreichbar? | TRUE |
| n8n_mem_mb | n8n Memory-Verbrauch in MB | 256 |
| alert | Alert ausgelöst? | FALSE |
