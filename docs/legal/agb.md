# Allgemeine Geschäftsbedingungen (AGB)

**FiBu-Agent — KI-gestützte Belegverarbeitung**

Stand: April 2026

---

## § 1 Geltungsbereich

(1) Diese Allgemeinen Geschäftsbedingungen (nachfolgend „AGB") gelten für alle Verträge zwischen [Ihr Unternehmen, Adresse, Handelsregister] (nachfolgend „Anbieter") und dem Kunden (nachfolgend „Kunde") über die Nutzung der Software „FiBu-Agent" als Software-as-a-Service (SaaS).

(2) Der Kunde ist ausschließlich Unternehmer im Sinne von § 14 BGB. Diese AGB gelten nicht gegenüber Verbrauchern.

(3) Abweichende, entgegenstehende oder ergänzende AGB des Kunden werden nicht Vertragsbestandteil, es sei denn, der Anbieter stimmt ihrer Geltung ausdrücklich schriftlich zu.

## § 2 Vertragsgegenstand

(1) Der Anbieter stellt dem Kunden die Software „FiBu-Agent" als Cloud-basierte oder selbst gehostete Anwendung zur Verfügung. Die Software umfasst:

- KI-gestützte optische Zeichenerkennung (OCR) auf Buchungsbelegen
- Automatische Kontierung nach SKR03/SKR04
- Validierung und Plausibilitätsprüfung
- Export im DATEV-Buchungsstapelformat (EXTF)
- Web-basierte Benutzeroberfläche zur Verwaltung

(2) Der genaue Leistungsumfang ergibt sich aus der jeweiligen Leistungsbeschreibung bzw. dem individuellen Angebot.

(3) Die Software dient als **Unterstützungswerkzeug** für die Finanzbuchhaltung. Sie ersetzt nicht die Prüfpflicht des Kunden oder seines Steuerberaters. Der Anbieter erbringt **keine Steuerberatung** im Sinne des Steuerberatungsgesetzes (StBerG).

## § 3 Vertragsschluss und Laufzeit

(1) Der Vertrag kommt durch Annahme des Angebots des Anbieters zustande, spätestens mit Beginn der Nutzung der Software.

(2) Der Vertrag wird auf unbestimmte Zeit geschlossen und kann von beiden Seiten mit einer Frist von **einem Monat zum Monatsende** gekündigt werden.

(3) Das Recht zur außerordentlichen Kündigung aus wichtigem Grund bleibt unberührt.

(4) Nach Vertragsende stellt der Anbieter dem Kunden seine Daten in einem gängigen Format (CSV/JSON) für 30 Tage zum Download bereit. Danach werden die Daten gelöscht, sofern keine gesetzlichen Aufbewahrungspflichten entgegenstehen.

## § 4 Leistungserbringung

(1) Der Anbieter stellt die Software in der jeweils aktuellen Version bereit.

(2) Bei der Self-Hosted-Variante stellt der Anbieter die Software als Docker-Container zur Verfügung. Der Kunde ist für den Betrieb der Infrastruktur (Server, Netzwerk, Backups) selbst verantwortlich.

(3) Die Verfügbarkeit der Software wird durch die gewählte Betriebsart bestimmt:
- **Self-Hosted**: Der Kunde ist für die Verfügbarkeit seiner Infrastruktur verantwortlich.
- **Cloud-Hosting** (falls angeboten): Der Anbieter strebt eine Verfügbarkeit von 99,0 % im Monatsmittel an, ausgenommen geplante Wartungsfenster.

(4) Der Anbieter ist berechtigt, die Software weiterzuentwickeln und Funktionen zu ändern, sofern der vertraglich vereinbarte Funktionsumfang nicht wesentlich eingeschränkt wird.

## § 5 Pflichten des Kunden

(1) Der Kunde ist verpflichtet:
- a) die Software ausschließlich bestimmungsgemäß zu nutzen,
- b) seine Zugangsdaten vertraulich zu behandeln und vor dem Zugriff Dritter zu schützen,
- c) die von der Software erzeugten Buchungssätze vor dem Import in sein Buchhaltungssystem stichprobenartig zu prüfen,
- d) regelmäßige Datensicherungen durchzuführen (bei Self-Hosted-Betrieb),
- e) den Anbieter unverzüglich über erkannte Fehler oder Sicherheitsvorfälle zu informieren.

(2) Der Kunde stellt sicher, dass er über die erforderlichen Rechte zur Verarbeitung der hochgeladenen Belege verfügt und — soweit personenbezogene Daten Dritter betroffen sind — eine Rechtsgrundlage gemäß DSGVO vorliegt.

(3) Die **Verantwortung für die korrekte Buchführung** verbleibt beim Kunden bzw. dessen Steuerberater. Der FiBu-Agent ist ein Hilfswerkzeug, kein Ersatz für fachkundige Prüfung.

## § 6 Vergütung

(1) Die Vergütung richtet sich nach der jeweiligen Preisliste oder dem individuellen Angebot.

(2) Alle Preise verstehen sich zuzüglich der gesetzlichen Umsatzsteuer.

(3) Die API-Kosten für die KI-Verarbeitung (Anthropic Claude API) werden nach tatsächlichem Verbrauch abgerechnet oder sind im Pauschalpreis enthalten, je nach Vereinbarung.

(4) Der Anbieter ist berechtigt, die Preise mit einer Ankündigungsfrist von **drei Monaten** zum nächsten Vertragshalbjahr anzupassen. Der Kunde hat in diesem Fall ein Sonderkündigungsrecht zum Zeitpunkt des Inkrafttretens der Preisänderung.

## § 7 Gewährleistung

(1) Die Software wird in dem bei Vertragsschluss beschriebenen Funktionsumfang bereitgestellt.

(2) Der Anbieter gewährleistet **nicht**, dass:
- a) die OCR-Erkennung fehlerfrei arbeitet — Erkennungsraten sind abhängig von der Qualität der Eingangsdokumente,
- b) die automatische Kontierung in jedem Fall korrekt ist — komplexe oder ungewöhnliche Geschäftsvorfälle können eine manuelle Korrektur erfordern,
- c) der DATEV-Export ohne Anpassungen in jede DATEV-Version importiert werden kann.

(3) Mängel hat der Kunde unverzüglich nach Entdeckung schriftlich anzuzeigen. Der Anbieter wird angezeigte Mängel in angemessener Frist beheben.

(4) Die Gewährleistungsfrist beträgt 12 Monate ab Bereitstellung.

## § 8 Haftung

(1) Der Anbieter haftet unbeschränkt für Schäden aus der Verletzung des Lebens, des Körpers oder der Gesundheit sowie für Vorsatz und grobe Fahrlässigkeit.

(2) Bei leichter Fahrlässigkeit haftet der Anbieter nur bei Verletzung wesentlicher Vertragspflichten (Kardinalpflichten). Die Haftung ist in diesem Fall beschränkt auf den vertragstypisch vorhersehbaren Schaden, maximal jedoch auf die **Gesamtvergütung der letzten 12 Monate**.

(3) Der Anbieter haftet **nicht** für:
- a) Schäden durch fehlerhafte Buchungssätze, die der Kunde ohne Prüfung übernommen hat (§ 5 Abs. 1 lit. c),
- b) Schäden durch unzureichende Belegqualität (unleserliche Scans, beschädigte PDFs),
- c) Datenverlust, soweit der Kunde seiner Datensicherungspflicht nicht nachgekommen ist,
- d) Ausfälle oder Fehler der Anthropic Claude API oder anderer Drittdienste.

(4) Die vorstehenden Haftungsbeschränkungen gelten auch zugunsten der Erfüllungsgehilfen des Anbieters.

## § 9 Datenschutz

(1) Die Verarbeitung personenbezogener Daten richtet sich nach der Datenschutzerklärung des Anbieters sowie dem separat abzuschließenden Auftragsverarbeitungsvertrag (AVV) gemäß Art. 28 DSGVO.

(2) Der Anbieter verarbeitet Belege ausschließlich zum Zweck der vertraglich vereinbarten Leistungserbringung.

(3) Soweit die Software die Anthropic Claude API nutzt, werden Belegdaten zur OCR-Verarbeitung an Server von Anthropic, Inc. (USA) übermittelt. Die Übermittlung erfolgt auf Grundlage der EU-Standardvertragsklauseln (SCC). Anthropic verwendet API-Daten nicht zum Training von KI-Modellen.

## § 10 Geheimhaltung

(1) Beide Parteien verpflichten sich, vertrauliche Informationen der jeweils anderen Partei geheim zu halten und nur für die Vertragsdurchführung zu verwenden.

(2) Diese Pflicht gilt nicht für Informationen, die:
- a) öffentlich bekannt sind oder werden,
- b) der empfangenden Partei bereits bekannt waren,
- c) aufgrund gesetzlicher Verpflichtung offengelegt werden müssen.

(3) Die Geheimhaltungspflicht besteht über die Vertragslaufzeit hinaus für 3 Jahre fort.

## § 11 Höhere Gewalt

Im Falle höherer Gewalt (insbesondere Naturkatastrophen, Pandemien, behördliche Anordnungen, Ausfall von Drittdiensten) ist der Anbieter für die Dauer der Störung von der Leistungspflicht befreit. Der Anbieter wird den Kunden unverzüglich informieren.

## § 12 Schlussbestimmungen

(1) Es gilt das Recht der Bundesrepublik Deutschland unter Ausschluss des UN-Kaufrechts (CISG).

(2) Gerichtsstand für alle Streitigkeiten ist — soweit gesetzlich zulässig — der Sitz des Anbieters.

(3) Änderungen und Ergänzungen dieses Vertrages bedürfen der Schriftform. Dies gilt auch für die Aufhebung dieses Schriftformerfordernisses.

(4) Sollten einzelne Bestimmungen unwirksam sein, bleibt die Wirksamkeit der übrigen Bestimmungen unberührt.

---

*Hinweis: Diese AGB sind eine Vorlage und müssen vor der Verwendung von einem Rechtsanwalt geprüft werden. Sie ersetzen keine Rechtsberatung.*
