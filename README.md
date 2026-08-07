# Milan Calendar

Calendario iCalendar sottoscrivibile con le partite della Prima Squadra maschile dell'AC Milan: Serie A, Coppa Italia, Supercoppa Italiana, competizioni UEFA, amichevoli, tournée e altri incontri pubblicati dalle fonti.

- Pagina: <https://dizzle0987.github.io/milan-calendar/>
- Feed HTTPS: <https://dizzle0987.github.io/milan-calendar/calendar.ics>
- Sottoscrizione iPhone: <webcal://dizzle0987.github.io/milan-calendar/calendar.ics>

## Come sottoscrivere il calendario su iPhone

1. Apri <https://dizzle0987.github.io/milan-calendar/> con Safari su iPhone.
2. Tocca **Iscriviti su iPhone** e conferma se iOS mostra la schermata d'iscrizione.
3. Se Calendario si apre senza aggiungere il feed, torna alla pagina e tocca **Copia link calendario**.
4. In Calendario, tocca **Calendari → Aggiungi calendario → Aggiungi calendario con iscrizione**.
5. Incolla il link, tocca **Trova**, scegli **iCloud** come account e tocca **Fine**.

In alternativa, vai in **Impostazioni → App → Calendario → Account calendario → Aggiungi account → Altro → Aggiungi calendario con sottoscrizione** e incolla:

```text
https://dizzle0987.github.io/milan-calendar/calendar.ics
```

Non importare il file come calendario statico: usa sempre **Aggiungi calendario con iscrizione**, così iPhone riceverà gli aggiornamenti di date e orari.

Dopo la pubblicazione di un aggiornamento, l'app Calendario può impiegare qualche minuto per sincronizzare i nuovi eventi; non è necessario iscriversi di nuovo.

## Android, Mac e PC

- **Android / Google Calendar**: apri Google Calendar sul web, scegli **Altri calendari → + → Da URL**, incolla il feed HTTPS e aggiungilo. Su telefono può essere necessario attivare **Sito desktop**; il calendario comparirà poi nell'app Android.
- **Mac**: nell'app Calendario scegli **File → Nuova iscrizione calendario**, incolla il feed HTTPS e abilita l'aggiornamento automatico.
- **Windows / Outlook**: in Outlook sul web scegli **Aggiungi calendario → Sottoscrivi dal Web**, incolla il feed e conferma.
- **PC o Linux / Google Calendar**: usa **Altri calendari → + → Da URL**.

Usa sempre la sottoscrizione tramite URL. Scaricare o importare una copia statica di `calendar.ics` non consente di ricevere gli spostamenti successivi.

## Fonti e strategia di aggiornamento

Il generatore non usa SofaScore.

1. **Scoperta delle partite — AC Milan**: la pagina ufficiale del calendario della stagione rimane il riferimento principale per l'esistenza dell'incontro, le squadre, la competizione e lo stadio. Il programma legge i dati JSON strutturati incorporati dalla web app ufficiale.
2. **Fallback e integrazione — ESPN**: endpoint JSON pubblici per Serie A, Coppa Italia, Supercoppa, competizioni UEFA e amichevoli. ESPN integra anche incontri non ancora presenti nella risposta ufficiale.
3. **Controllo aggiuntivo — TheSportsDB**: API JSON pubblica usata per individuare la prossima partita, comprese amichevoli e tournée non ancora esposte dagli altri feed.
4. **Priorità degli orari — broadcaster italiani**: gli orari espliciti pubblicati da DAZN, Sky Sport/NOW, Mediaset e Prime Video possono completare o correggere un evento TBC. I broadcaster prevalgono sulle fonti editoriali e sul sito Milan per il solo orario; i metadati della partita restano quelli della fonte sportiva.
5. **Fallback editoriale degli orari — Gazzetta dello Sport**: viene consultato il programma delle amichevoli. Un orario viene usato soltanto se è scritto esplicitamente insieme a data e squadre; diciture come “da stabilire” vengono ignorate.
6. **Ultimo risultato valido**: almeno una fonte di scoperta (AC Milan, ESPN o TheSportsDB) deve restituire partite valide. Una risposta dei soli palinsesti TV non può sostituire o svuotare il calendario. Gli output vengono preparati su file temporanei e sostituiti atomicamente solo a elaborazione conclusa.
7. **Eventi manuali**: `data/manual_events.json` può integrare o correggere le fonti. A parità di partita, i dati manuali hanno precedenza e possono essere disattivati con `"enabled": false`.

Il [calendario DAZN](https://www.dazn.com/it-IT/schedule), la [pagina Milan di NOW](https://www.nowtv.it/sport/calcio/milan), Sky Sport, Mediaset, Prime Video e Gazzetta vengono interrogati ogni sei ore. Si preferiscono i dati strutturati presenti nella pagina; il riconoscimento testuale è limitato a righe che contengono squadre, data e ora complete. Se due fonti indicano orari diversi, vince quella con priorità maggiore e le alternative restano in `time_conflicts` dentro `data/events.json` per il debug.

Palinsesti come Sisal possono essere consultati come segnalazione ulteriore, ma non vengono analizzati automaticamente: non offrono un'API pubblica documentata e uno scraping del sito sarebbe fragile. Prima della pubblicazione, una segnalazione viene confermata con una fonte ufficiale o strutturata.

Le richieste HTTP hanno timeout, retry con backoff e un User-Agent identificabile. Le fonti sono interrogate ogni 6 ore da GitHub Actions.

## UID, aggiornamenti e deduplicazione

Ogni UID è un hash stabile di stagione, squadre e competizione, indipendente dall'ordine casa/trasferta. Data, ora e turno non fanno parte dell'UID: quando una partita viene spostata o ne viene precisata la fase, l'app Calendario aggiorna lo stesso evento invece di crearne uno nuovo. A ogni modifica significativa aumenta anche il campo iCalendar `SEQUENCE`, migliorando il riconoscimento dell'aggiornamento da parte dei client.

Gli spostamenti di settimane o mesi sono riconosciuti senza limiti di 72 ore quando la fonte mantiene il proprio `source_id`. Se l'identificativo della fonte cambia, il generatore tenta un recupero prudente usando squadre in casa/trasferta, competizione e turno entro 240 giorni, ma riutilizza l'UID soltanto se trova una singola corrispondenza. Questo copre rinvii per meteo, ordine pubblico o ricalendarizzazioni di coppa senza confondere andata, ritorno o incontri diversi.

Gli eventi con stesse squadre, stessa famiglia di competizione e orari entro 72 ore vengono unificati. Sono riconosciute anche varianti comuni dei nomi delle squadre. Le voci di Milan Femminile, Milan Futuro, Primavera e categorie giovanili vengono escluse. AC Milan ha precedenza per i dati descrittivi; i broadcaster hanno precedenza specificamente per l'orario e la copertura televisiva. Ogni evento include, quando disponibile:

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
      "enabled": true,
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

Campi obbligatori: `home_team`, `away_team`, `competition`, `start`. `start` può essere un timestamp ISO 8601 con offset oppure una data `YYYY-MM-DD` per un evento senza orario. È possibile specificare un `uid` esplicito; in caso contrario viene generato automaticamente. Per correggere un evento recuperato, usa stesse squadre e competizione e una data entro 72 ore. Imposta `"enabled": false` per sospendere una voce senza cancellarla.

Per annotare manualmente un rinvio senza creare una seconda partita:

```json
{
  "postponed": true,
  "postponed_from": "2026-09-12T20:45:00+02:00",
  "postponed_to": "",
  "postponement_reason": "Maltempo"
}
```

Con `postponed_to` vuoto l'evento diventa giornaliero sulla data originaria, viene mostrato come **RINVIATA — DATA DA DESTINARSI** e il promemoria viene sospeso. Quando la nuova data è nota, aggiorna `start` e `postponed_to` con lo stesso valore: l'UID resta invariato, il titolo mostra **RINVIATA AL gg/mm/aaaa** e il promemoria torna attivo. Gli stati equivalenti pubblicati dalle fonti (`postponed`, `PST`, `rinviata`) vengono riconosciuti automaticamente.

Dopo la modifica esegui test e generatore, quindi committa sia il file manuale sia gli output aggiornati.

## Automazione GitHub

- `.github/workflows/update.yml` viene eseguito alle ore `00:17`, `06:17`, `12:17` e `18:17` UTC. Installa le dipendenze, esegue i test, rigenera il feed e committa solo quando gli output cambiano.
- GitHub Pages pubblica direttamente la cartella radice del branch `main`; ogni commit generato dall'aggiornamento rende quindi disponibile anche il nuovo feed.
- `.github/workflows/pages.yml` resta disponibile come workflow di pubblicazione alternativo.

Nel repository GitHub, apri **Settings → Pages** e imposta **Source: Deploy from a branch**, branch `main`, cartella `/ (root)`. In **Settings → Actions → General → Workflow permissions**, abilita **Read and write permissions** affinché il workflow di aggiornamento possa effettuare il commit.

## Test

La suite verifica:

- parsing del JSON incorporato nella pagina ufficiale;
- parsing della risposta JSON ESPN;
- esclusione delle squadre femminili, Futuro e giovanili;
- deduplicazione, alias e stabilità dell'UID dopo un cambio d'orario;
- rinvii a data da destinarsi e riprogrammazioni di più mesi con lo stesso UID;
- incremento di `SEQUENCE` dopo modifiche significative;
- priorità e tracciamento dei conflitti fra fonti orarie;
- fuso `Europe/Rome` e promemoria iCalendar;
- precedenza e disattivazione degli eventi manuali;
- conservazione degli output quando tutte le fonti falliscono o rispondono solo fonti TV.

Esecuzione:

```bash
pytest -q
```
