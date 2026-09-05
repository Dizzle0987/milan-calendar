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
2. **Fallback e integrazione — ESPN**: endpoint JSON pubblici per Serie A, Serie B (fallback in caso di retrocessione), Coppa Italia, Supercoppa Italiana, Champions League, Europa League, Conference League, Supercoppa UEFA, Coppa del Mondo per Club FIFA, Coppa Intercontinentale FIFA, UEFA-CONMEBOL Club Challenge e amichevoli. ESPN integra anche incontri non ancora presenti nella risposta ufficiale.
3. **Controllo aggiuntivo — TheSportsDB**: API JSON pubblica usata per individuare la prossima partita, comprese amichevoli e tournée non ancora esposte dagli altri feed.
4. **Priorità degli orari — broadcaster italiani**: gli orari espliciti pubblicati da DAZN, Sky Sport/NOW, Mediaset e Prime Video possono completare o correggere un evento TBC. I broadcaster prevalgono sulle fonti editoriali e sul sito Milan per il solo orario; i metadati della partita restano quelli della fonte sportiva.
5. **Fallback editoriale degli orari — Gazzetta dello Sport**: viene consultato il programma delle amichevoli. Un orario viene usato soltanto se è scritto esplicitamente insieme a data e squadre; diciture come “da stabilire” vengono ignorate.
6. **Ultimo risultato valido**: almeno una fonte di scoperta (AC Milan, ESPN o TheSportsDB) deve restituire partite valide. Una risposta dei soli palinsesti TV non può sostituire o svuotare il calendario. Gli output vengono preparati su file temporanei e sostituiti atomicamente solo a elaborazione conclusa.
7. **Eventi manuali**: `data/manual_events.json` può integrare o correggere le fonti. I metadati manuali hanno precedenza, ma un palinsesto live con priorità uguale o superiore può correggere un vecchio orario manuale associato a un broadcaster. Usa `"lock_time": true` soltanto per un orario verificato che non deve essere sostituito. Le voci possono essere disattivate con `"enabled": false`.

Il [calendario DAZN](https://www.dazn.com/it-IT/schedule), la [pagina Milan di NOW](https://www.nowtv.it/sport/calcio/milan), Sky Sport, Mediaset, Prime Video e Gazzetta vengono interrogati ogni sei ore. Si preferiscono i dati strutturati presenti nella pagina; il riconoscimento testuale è limitato a righe che contengono squadre, data e ora complete. Se due fonti indicano orari diversi, vince quella con priorità maggiore e le alternative restano in `time_conflicts` dentro `data/events.json` per il debug. La classifica viene letta dal feed JSON che alimenta il sito ufficiale Lega Serie A, con ESPN come fallback, e viene aggiunta alle note della partita della giornata attuale (o dell'ultima appena passata) e della prossima; un errore della classifica non interrompe l'aggiornamento del calendario.

Le note visibili degli eventi sono intenzionalmente compatte: mostrano competizione, casa/trasferta, orario di Roma, stadio, emittente e fonte dell'orario. Nella partita della giornata attuale/appena passata e nella prossima compare anche una mini-classifica di cinque righe con il Milan, le due squadre davanti e le due dietro (oppure le cinque posizioni disponibili vicino agli estremi), l'ora di verifica e la fonte. Se le squadre non hanno disputato tutte lo stesso numero di gare viene indicata come provvisoria. Il calendario distingue `giornata in corso` da uno o più recuperi ufficialmente rinviati e, quando disponibili nel feed strutturato ESPN, ne mostra gli incontri ancora da disputare; gli eventi Milan già acquisiti sono il fallback. Quando i valori sono allineati viene indicata come `giornata completata`. Gli URL non affollano la descrizione: rimangono nel campo tecnico `URL` dell'evento e, insieme a tutte le fonti TV/orario, in `data/events.json`.

Palinsesti come Sisal possono essere consultati come segnalazione ulteriore, ma non vengono analizzati automaticamente: non offrono un'API pubblica documentata e uno scraping del sito sarebbe fragile. Prima della pubblicazione, una segnalazione viene confermata con una fonte ufficiale o strutturata.

Le richieste HTTP hanno timeout, retry con backoff e un User-Agent identificabile. Le fonti sono interrogate ogni 6 ore da GitHub Actions. Il workflow `standings.yml` effettua inoltre controlli ogni 15 minuti nelle consuete fasce delle partite italiane e crea un commit solo quando la classifica ufficiale cambia.

## UID, aggiornamenti e deduplicazione

Ogni UID è un hash stabile di stagione, squadra di casa, squadra in trasferta e competizione. L'ordine casa/trasferta distingue correttamente andata e ritorno; eventuali inversioni presenti soltanto nei feed di supporto vengono riconciliate durante la deduplicazione. Data, ora e turno non fanno parte dell'UID: quando una partita viene spostata o ne viene precisata la fase, l'app Calendario aggiorna lo stesso evento invece di crearne uno nuovo. A ogni modifica significativa aumenta anche il campo iCalendar `SEQUENCE`, migliorando il riconoscimento dell'aggiornamento da parte dei client.

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

## Dove vedere le partite

Il campo `broadcast_it` viene aggiunto automaticamente in base ai diritti nazionali noti della competizione:

- Serie A: DAZN;
- Coppa Italia e Supercoppa Italiana: reti Mediaset, Mediaset Infinity e SportMediaset.it;
- Europa League e Conference League: Sky Sport e NOW;
- Champions League: Sky Sport/NOW, con avviso di verificare l'eventuale selezione esclusiva Prime Video;
- amichevoli e altre competizioni: `Da definire` finché non viene pubblicato un palinsesto affidabile.

Per le competizioni esclusivamente italiane resta valida questa mappatura. Per le partite ufficiali UEFA, FIFA o intercontinentali non ancora iniziate viene invece richiesta una conferma della **singola partita**: possedere i diritti generali di un torneo non basta.

Le fonti controllate sono configurate in `data/broadcast_sources.json`. Il primo livello della verifica avanzata viene eseguito **soltanto sulla prossima partita ufficiale UEFA, FIFA o intercontinentale**: Serie A, Serie B, Coppa Italia, Supercoppa Italiana e amichevoli mantengono integralmente il proprio percorso già collaudato. Il generatore identifica automaticamente il Paese dell'avversaria tramite dati strutturati (con fallback sul registro delle fonti), verifica l'Italia e consulta almeno una guida TV/EPG affidabile di quel Paese. Non contiene eccezioni scritte per una singola partita ed è quindi riutilizzabile dopo i sorteggi successivi.

Ogni conferma riceve un punteggio verificabile: 100 per una pagina ufficiale della singola partita, 95 per un EPG ufficiale, 90 per due guide indipendenti concordi e 70 per una sola guida. Una guida sostenuta soltanto dalla pagina generica dei diritti arriva a 75: quel contesto non equivale alla conferma della singola partita. In Italia vengono conservate le opzioni confermate, incluse Sky/NOW quando applicabili. Per questo primo livello vengono controllati soltanto Portogallo, Germania, Austria e Svizzera; all'estero viene pubblicata **solo** un'alternativa gratuita con confidenza almeno 85. Negli altri casi appare `🌍 In chiaro all'estero — Da confermare`. Un broadcaster estero a pagamento può essere conservato nei metadati di debug, ma non viene proposto nelle note del calendario.

La verifica richiede che la fonte riguardi esattamente le due squadre e la data locale della gara. Per i palinsesti strutturati viene inoltre controllato che l'intervallo copra la partita, escludendo anteprime, notiziari, highlights e differite. L'inizio del programma TV resta separato dal calcio d'inizio e viene sempre convertito in `Europe/Rome`. I metadati interni comprendono partita, competizione, data, Paese, broadcaster, tipo e URL della fonte, ora della verifica, confidenza, gratuito/a pagamento, lingua e registrazione richiesta.

I palinsesti vengono interrogati entro il loro orizzonte configurato, normalmente 21 giorni; le pagine ufficiali dedicate possono essere cercate prima. Evidenze e punteggi sono salvati in `broadcast_candidates`, mentre le sole opzioni pubblicabili finiscono in `broadcast_options` dentro `data/events.json`. Ogni fonte è indipendente: timeout, blocco geografico, risposta 403/404 o cambio di formato non interrompono l'aggiornamento. L'ultima conferma valida viene conservata e l'errore resta soltanto nei dati di debug. Un evento passato non viene riscritto.

Una correzione manuale resta possibile quando viene pubblicato un annuncio ufficiale non leggibile automaticamente.

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
- `data/calendar_events.json`: fallback strutturato per i sorteggi ufficiali; le voci con `requires_participation: true` compaiono soltanto se il Milan partecipa alla competizione. `participation_confirmed: true` consente di inserirle già prima che le fonti abbiano pubblicato la prima partita del torneo.

La homepage usa lo stesso `data/events.json` per mostrare un Match Center sempre aggiornato con prossima partita, quattro gare successive e classifica Serie A contestuale. Il rendering avviene nel browser, usa il fuso `Europe/Rome` e non può interrompere il pulsante di iscrizione: se il JSON è temporaneamente indisponibile, la pagina mostra un messaggio discreto mentre il feed iCalendar continua a funzionare.

I nuovi sorteggi UEFA vengono cercati automaticamente ogni sei ore sulle pagine ufficiali di Champions League, Europa League e Conference League. Il parser accetta solo un `SportsEvent` strutturato con nome e timestamp completi, converte l'istante in `Europe/Rome` e pubblica soltanto la competizione del Milan. Un sorteggio già scoperto viene conservato quando UEFA aggiorna la pagina al turno successivo. Supercoppa Italiana, Supercoppa UEFA e Coppa Intercontinentale FIFA non hanno normalmente un sorteggio per il Milan; le loro partite vengono comunque cercate tra le fonti strutturate. La Coppa del Mondo per Club FIFA è inclusa tra le competizioni monitorate e un suo futuro sorteggio può essere inserito in `calendar_events.json` quando FIFA ne pubblica i dettagli ufficiali.

Il generatore controlla anche gli articoli recenti della Lega Serie A relativi a `sorteggio`, `calendario` e `tabellone`, creando l'evento solo quando nel testo è presente una data completa; l'orario viene aggiunto esclusivamente se dichiarato. Sono quindi incluse anche le presentazioni dei calendari e le pubblicazioni dei tabelloni ufficiali. `calendar_events.json` rimane il fallback in caso di indisponibilità temporanea delle fonti.

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
- `.github/workflows/health-alerts.yml` controlla la conclusione di aggiornamento, classifica e pubblicazione Pages. In caso di errore apre una sola Issue per il workflow interessato, aggiunge i successivi errori alla stessa Issue e la chiude automaticamente quando il servizio torna operativo. L'Issue menziona il proprietario e contiene il link diretto al log; l'ultimo calendario valido resta disponibile.

Per ricevere gli avvisi sia via email sia nell'app GitHub, nel repository seleziona **Watch → Custom → Issues**. Nelle impostazioni personali di GitHub, sotto **Notifications**, lascia abilitati **Email** e **GitHub Mobile** per le notifiche relative alle Issue. Non servono token o servizi esterni: il workflow usa il permesso `issues: write` del token GitHub Actions del repository.

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
