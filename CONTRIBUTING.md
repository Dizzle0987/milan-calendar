# Contribuire a Milan Calendar

Grazie per voler migliorare il progetto.

## Segnalare una partita mancante o errata

Apri una issue usando il modello dedicato e indica:

- squadre, competizione, data e orario;
- stadio e broadcaster italiano, se noti;
- almeno una fonte pubblica affidabile, preferibilmente ufficiale.

Le quote o i palinsesti di scommesse possono essere usati come segnalazione, ma una partita viene confermata con una fonte ufficiale o strutturata.

## Modifiche al codice

1. Crea un branch dal branch `main`.
2. Installa le dipendenze con `python -m pip install -r requirements.txt`.
3. Esegui `pytest -q`.
4. Esegui `python update_calendar.py` quando la modifica riguarda dati o generazione.
5. Apri una pull request descrivendo modifica, fonti e verifiche eseguite.

Non inserire credenziali, token o dati personali nel repository.

