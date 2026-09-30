# Haftungsausschluss und Nutzungshinweise

**FiBu-Agent — KI-gestützte Belegverarbeitung**

Stand: April 2026

---

## 1. Keine Steuerberatung

FiBu-Agent ist ein **technisches Hilfswerkzeug** zur automatisierten Vorkontierung von Buchungsbelegen. Die Software und der damit verbundene Service stellen **keine Steuerberatung** im Sinne des Steuerberatungsgesetzes (StBerG) dar.

Im Einzelnen:

- Die automatische Kontierung ist ein **Vorschlag**, keine verbindliche steuerliche Einordnung
- Die Software ersetzt **nicht** die Prüfung durch einen Steuerberater, Wirtschaftsprüfer oder vereidigten Buchprüfer
- Die Verantwortung für die ordnungsgemäße Buchführung gemäß §§ 238 ff. HGB und §§ 140 ff. AO verbleibt vollständig beim Anwender bzw. dessen Steuerberater
- Der Anbieter übt keine geschäftsmäßige Hilfeleistung in Steuersachen gemäß § 2 StBerG aus

## 2. Keine Gewähr für Korrektheit

Die KI-gestützte Verarbeitung arbeitet mit hoher, aber nicht hundertprozentiger Genauigkeit. Insbesondere:

### 2.1 OCR-Erkennung
- Die Texterkennungsqualität hängt von der Qualität der Eingangsdokumente ab (Auflösung, Kontrast, Layout)
- Handschriftliche Belege, stark beschädigte oder ungewöhnlich formatierte Dokumente können zu fehlerhaften Ergebnissen führen
- Bei Unsicherheit kennzeichnet das System Belege als „Rückfrage"

### 2.2 Automatische Kontierung
- Die Kontierung basiert auf regelbasierten Mustererkennungen (Lieferantenname, Rechnungstext)
- Unbekannte Lieferanten oder ungewöhnliche Geschäftsvorfälle werden einem Auffangkonto zugeordnet
- Die korrekte Kontierung erfordert eine abschließende fachliche Prüfung
- Branchenspezifische oder mandantenspezifische Besonderheiten müssen über Regelanpassungen abgebildet werden

### 2.3 DATEV-Export
- Der Export erfolgt im standardisierten EXTF-Format (Version 700)
- Die Kompatibilität mit allen DATEV-Versionen und -Konfigurationen wird nicht garantiert
- Ein **Prüflauf** vor dem produktiven Import ist zwingend empfohlen

## 3. Prüfpflicht des Anwenders

Der Anwender ist verpflichtet:

1. **Stichprobenartige Prüfung** — Mindestens 10 % der automatisch kontierten Buchungssätze vor dem DATEV-Import auf Richtigkeit zu prüfen
2. **Rückfragen bearbeiten** — Alle vom System als „Rückfrage" markierten Belege manuell zu prüfen, bevor sie exportiert werden
3. **DATEV-Prüflauf** — Vor dem ersten produktiven Import einen DATEV-Prüflauf durchzuführen
4. **Regelmäßige Kontrolle** — Die Kontierungsqualität regelmäßig zu evaluieren und Regelanpassungen vorzunehmen

## 4. Haftungsausschluss für Drittdienste

### 4.1 Anthropic Claude API
- Die OCR-Verarbeitung nutzt die API von Anthropic, Inc.
- Für Verfügbarkeit, Antwortzeiten und Verarbeitungsqualität der Anthropic API übernimmt der Anbieter keine Gewähr
- Änderungen an der API durch Anthropic (Modellversion, Preise, Nutzungsbedingungen) können die Funktionalität beeinflussen

### 4.2 DATEV-Kompatibilität
- DATEV ist eine eingetragene Marke der DATEV eG
- FiBu-Agent ist kein offizielles DATEV-Produkt und nicht von DATEV zertifiziert
- Die EXTF-Schnittstelle ist eine von DATEV dokumentierte Importschnittstelle, die nach bestem Wissen implementiert wurde

## 5. Hinweis zur KI-Nutzung

Der Anwender wird hiermit informiert, dass FiBu-Agent **künstliche Intelligenz** (Large Language Model, Claude von Anthropic) für die Texterkennung und Datenextraktion einsetzt.

Dies bedeutet:
- Ergebnisse sind **probabilistisch**, nicht deterministisch — die gleiche Rechnung kann bei wiederholter Verarbeitung minimal abweichende Ergebnisse liefern
- Die Kontierung selbst ist **deterministisch** (regelbasiert) — gleiche Eingabedaten führen immer zur gleichen Kontozuordnung
- Belegbilder werden zur Verarbeitung an die Anthropic API übermittelt (siehe Datenschutzerklärung)

## 6. Anzuzeigender Hinweis

Der folgende Hinweis muss in der Anwendung für alle Benutzer sichtbar sein:

> **Hinweis**: Die automatische Kontierung ist ein KI-gestützter Vorschlag und ersetzt nicht die fachliche Prüfung durch einen Steuerberater. Alle Buchungssätze sind vor dem Import in Ihre Buchhaltungssoftware stichprobenartig zu prüfen. Für Schäden aus ungeprüft übernommenen Buchungssätzen übernimmt der Anbieter keine Haftung.

---

*Dieser Haftungsausschluss ist Bestandteil der AGB und wird dem Kunden vor Vertragsschluss zur Verfügung gestellt. Er muss von einem Rechtsanwalt geprüft werden.*
