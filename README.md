# Milan Calendar

Calendario iCalendar sottoscrivibile con le partite della Prima Squadra maschile dell'AC Milan: Serie A, Coppa Italia, Supercoppa Italiana, competizioni UEFA, amichevoli, tournée e altri incontri pubblicati dalle fonti.

- Pagina: <https://dizzle0987.github.io/milan-calendar/>
- Feed HTTPS: <https://dizzle0987.github.io/milan-calendar/calendar.ics>
- Sottoscrizione iPhone: <webcal://dizzle0987.github.io/milan-calendar/calendar.ics>

## Come sottoscrivere il calendario su iPhone

1. Apri <https://dizzle0987.github.io/milan-calendar/> con Safari su iPhone.
2. Tocca **Prova iscrizione automatica** e conferma se iOS mostra la schermata d'iscrizione.
3. Se Calendario si apre senza aggiungere il feed, torna alla pagina e tocca **Copia link calendario**.
4. In Calendario, tocca **Calendari → Aggiungi calendario → Aggiungi calendario con iscrizione**.
5. Incolla il link, tocca **Trova**, scegli **iCloud** come account e tocca **Fine**.

In alternativa, vai in **Impostazioni → App → Calendario → Account calendario → Aggiungi account → Altro → Aggiungi calendario con sottoscrizione** e incolla:

```text
https://dizzle0987.github.io/milan-calendar/calendar.ics
```

Non importare il file come calendario statico: usa sempre **Aggiungi calendario con iscrizione**, così iPhone riceverà gli aggiornamenti di date e orari.

## Fonti e strategia di aggiornamento

Il generatore non usa SofaScore.

1. **Fonte primaria — AC Milan**: la pagina ufficiale del calendario della stagione. Il programma legge i dati JSON strutturati incorporati dalla web app ufficiale, non interpreta il testo o il layout visivo della pagina.
2. **Fallback e integrazione — ESPN**: endpoint JSON pubblici per Serie A, Coppa Italia, Supercoppa, competizioni UEFA e amichevoli. ESPN integra anche incontri non ancora presenti nella risposta ufficiale.
3. **Ultimo risultato valido**: se nessuna fonte remota risponde con eventi validi, il programma termina con errore prima di scrivere. `calendar.ics` e `data/events.json` rimangono quindi intatti.
4. **Eventi manuali**: `data/manual_events.json` può integrare o correggere le fonti. A parità di partita, i dati manuali hanno precedenza.

Le richieste HTTP hanno timeout, retry con backoff e un User-Agent identificabile. Le fonti sono interrogate ogni 6 ore da GitHub Actions.

## UID, aggiornamenti e deduplicazione

Ogni UID è un hash stabile di stagione, squadre e competizione. Data, ora e turno non fanno parte dell'UID: quando una partita viene spostata o ne viene precisata la fase, l'app Calendario aggiorna lo stesso evento invece di crearne uno nuovo.

Gli eventi AC Milan ed ESPN con stesse squadre, stessa famiglia di competizione e orari entro 48 ore vengono unificati. La fonte ufficiale ha precedenza; i campi mancanti possono essere completati dal fallback. Ogni evento include, quando disponibile:

- competizione e turno;
- stadio;
- indicazione casa/trasferta del Milan;
- URL della fonte;
- emittente o piattaforma che trasmette la partita in Italia;
- fuso `Europe/Rome`;
- promemoria 2 ore e 30 minuti prima.

Gli orari indicati come TBC/TBD sono pubblicati come eventi giornalieri. Quando l'orario viene confermato, lo stesso UID viene trasformato in un evento con orario.

## Dove vedere le partite in Italia

Il campo `broadcast_it` viene aggiunto automaticamente in base ai diritti nazionali noti della competizione:

- Serie A: DAZN;
- Coppa Italia e Supercoppa Italiana: reti Mediaset, Mediaset Infinity e SportMediaset.it;
- Europa League e Conference League: Sky Sport e NOW;
- Champions League: Sky Sport/NOW, con avviso di verificare l'eventuale selezione esclusiva Prime Video;
- amichevoli e altre competizioni: `Da definire` finché non viene pubblicato un palinsesto affidabile.

La piattaforma esatta può essere precisata manualmente quando viene annunciato il palinsesto della singola partita. La correzione manuale ha sempre precedenza sulla mappatura per competizione.

## Esecuzione locale

Richiede Python 3.12 o successivo.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
pytest -q
python update_calendar.py
```

Output:

- `calendar.ics`: feed iCalendar pubblico;
- `data/events.json`: snapshot normalizzato utile per debug, con fonte, UID e metadati di ogni evento.

Il comando restituisce codice `1` se tutte le fonti remote falliscono e non sovrascrive gli output precedenti.

## Eventi manuali

Modifica `data/manual_events.json`. Il file accetta un oggetto con la proprietà `events`:

```json
{
  "events": [
    {
      "id": "trofeo-estivo-2026",
      "home_team": "AC Milan",
      "away_team": "Real Madrid",
      "competition": "Amichevole",
      "start": "2026-08-14T20:45:00+02:00",
      "venue": "Stadio San Siro",
      "round": "Trofeo estivo",
      "source_url": "https://www.acmilan.com/",
      "broadcast_it": "Canale 5 e Mediaset Infinity",
      "broadcast_source_url": "https://mediasetinfinity.mediaset.it/"
    }
  ]
}
```

Campi obbligatori: `home_team`, `away_team`, `competition`, `start`. `start` può essere un timestamp ISO 8601 con offset oppure una data `YYYY-MM-DD` per un evento senza orario. È possibile specificare un `uid` esplicito; in caso contrario viene generato automaticamente. Per correggere un evento recuperato, usa stesse squadre e competizione e una data entro 48 ore.

Dopo la modifica esegui test e generatore, quindi committa sia il file manuale sia gli output aggiornati.

## Automazione GitHub

- `.github/workflows/update.yml` viene eseguito alle ore `00:17`, `06:17`, `12:17` e `18:17` UTC. Installa le dipendenze, esegue i test, rigenera il feed e committa solo quando gli output cambiano.
- `.github/workflows/pages.yml` pubblica `index.html` e `calendar.ics` con GitHub Pages dopo modifiche su `main` e dopo ogni aggiornamento automatico riuscito.

Nel repository GitHub, apri **Settings → Pages** e imposta **Source: GitHub Actions** se non è già selezionato. In **Settings → Actions → General → Workflow permissions**, abilita **Read and write permissions** affinché il workflow di aggiornamento possa effettuare il commit.

## Test

La suite verifica:

- parsing del JSON incorporato nella pagina ufficiale;
- parsing della risposta JSON ESPN;
- deduplicazione e stabilità dell'UID dopo un cambio d'orario;
- fuso `Europe/Rome` e promemoria iCalendar;
- precedenza degli eventi manuali;
- conservazione degli output quando tutte le fonti falliscono.

Esecuzione:

```bash
pytest -q
```
