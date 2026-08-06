# Milan Calendar

Calendario `.ics` automatico della Prima Squadra maschile AC Milan.

## Fonte

Il programma legge il calendario ufficiale AC Milan:

`https://www.acmilan.com/it/stagione/attiva/calendario/completo`

Le amichevoli che non compaiono ancora nella pagina ufficiale possono essere aggiunte in `data/manual_events.json`.

## Funzionamento

GitHub Actions esegue `update_calendar.py` ogni 6 ore. Se date o orari cambiano, aggiorna `calendar.ics` mantenendo identificatori stabili per evitare doppioni.

## Prima attivazione

1. Carica tutti i file nel ramo `main`, inclusa la cartella `.github`.
2. In **Settings → Pages**, scegli **GitHub Actions** come sorgente.
3. In **Actions**, apri **Aggiorna calendario Milan** e premi **Run workflow**.
4. Dopo il completamento, apri:
   `https://NOMEUTENTE.github.io/milan-calendar/calendar.ics`
5. Su iPhone: **Impostazioni → App → Calendario → Account calendario → Aggiungi account → Altro → Aggiungi calendario con sottoscrizione**.

## Eventi manuali

Modifica `data/manual_events.json`. Imposta `enabled` su `true` e compila data, squadre e competizione. Puoi duplicare l'oggetto di esempio per aggiungere più partite.
