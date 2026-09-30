# Testbelege

Die PDFs in diesem Ordner sind **erzeugte Testdaten**, keine echten Rechnungen.
Sie entstehen aus `tests/generate_test_belege.py` und dienen den Tests für
Extraktion, Kontierung und DATEV-Export.

Die Lieferantennamen (etwa Vodafone, Shell, Allianz) sind absichtlich echte
Firmennamen, weil das Regelwerk in `workflows/skr03_rules.json` genau solche
Namen erkennen soll; ein Test mit „Musterfirma GmbH" würde die Regeln nicht
prüfen. Alles Übrige ist erfunden: Anschriften („Musterstraße 1"),
Rechnungsnummern, Beträge, IBANs, Daten. Keine der Rechnungen wurde je
ausgestellt oder bezahlt, und keine stammt von den genannten Unternehmen.

Wer die Belege neu erzeugen will:

```
python tests/generate_test_belege.py
```
