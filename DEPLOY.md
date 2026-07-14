# Deploy del microservizio (`service.py`) e wiring in Make.com

Questo documento copre il passo confermato da Lorenzo il 12/07/2026:
**"Wrappo la pipeline Python esistente (consigliato)"** — la pipeline
Python già testata (vedi CHANGELOG.md/prototipo-status.md per il
conteggio esatto e sempre aggiornato dei test verdi) viene esposta come
microservizio HTTP, così Make.com può chiamarla con un semplice modulo
HTTP invece di reimplementare la logica di validazione (Fedeltà RAG,
no-leak-id, pacing energetico, budget...) nei moduli visivi di Make —
che rischierebbe di reintrodurre bug già chiusi (vedi
`certainty-matrix.md`).

## Perché Render.com

Piattaforma consigliata per un prototipo di questo tipo: piano gratuito/
economico sufficiente per iniziare, deploy da repository Git con build
automatico, variabili d'ambiente gestite nella dashboard (mai nel
codice), supporto nativo per `gunicorn` + Python. Nessun vincolo tecnico
che leghi il codice a Render specificamente: `service.py` è una app Flask
pura, `Procfile`/`render.yaml`/`Dockerfile` sono lo strato di deploy — la
stessa app funzionerebbe identica su Railway, Fly.io, un VPS qualunque con
`gunicorn service:app`, ecc. Cambia solo la procedura di questa pagina.

**[AGGIORNATO 2026-07-14] Deploy via Docker, non più il buildpack Python
nativo.** Il nuovo endpoint `POST /v1/pdf` (vedi sezione 5) chiama
`wkhtmltopdf`, un binario ESTERNO che il buildpack Python nativo di
Render non fornisce — solo un'immagine Docker può installarlo. Questo
repo include già un `Dockerfile` pronto (installa `wkhtmltopdf` 0.12.6
"Qt patchata", la stessa versione già in uso e verificata nel resto del
prototipo, dal pacchetto ufficiale del progetto — NON dal repository apt
di Debian, che l'ha rimosso da Trixie e porta comunque una CVE nota sulla
build Bookworm ancora disponibile) e `render.yaml` è già configurato per
usarlo (`runtime: docker`). Non devi scrivere nulla tu su questo fronte,
solo essere consapevole che il passo 2 sotto ora fa un build Docker
(qualche minuto in più al primo deploy) invece del buildpack nativo.

**Nota di onestà**: il `Dockerfile` è stato scritto sulla base di
documentazione ufficiale verificata via ricerca web, ma NON è stato
possibile costruirlo e testarlo end-to-end da questo ambiente sandbox —
l'accesso a github.com da qui è limitato dal proxy di rete di Anthropic
Code (i download di release binarie da repository non esplicitamente
abilitati vengono bloccati), quindi non ho potuto scaricare davvero il
pacchetto `.deb` per verificarlo dal vivo. Resta quindi "scritto", non
ancora "pronto" — per questo il passo 4 sotto include ora un test
specifico di `/v1/pdf` da fare SUBITO dopo il primo deploy, prima di
collegare Make.com: se il build Docker fallisce o `wkhtmltopdf` non
funziona come atteso, lo scopriamo lì, non a metà di uno scenario Make.com.

## 0. Prerequisito: le tue chiavi API reali

**Importante — per policy di sicurezza non posso mai vedere, gestire o
inserire le tue chiavi reali.** Le devi procurare/avere già tu e
inserirle TU direttamente nella dashboard di Render (passo 3):

- `ANTHROPIC_API_KEY` — la tua chiave Claude reale.
- `GOOGLE_MAPS_KEY` — necessaria solo per `mode="live"` (Geocoding + Places
  + Distance Matrix). Se per ora vuoi testare solo in `mode="mock"`, puoi
  ometterla: il servizio la richiederà solo quando arriva una richiesta
  `live`, con un errore 500 leggibile, non un crash.
- `LITEAPI_KEY` — stesso discorso, necessaria solo per `mode="live"`.
- `SERVICE_API_KEY` — **questa te la inventi tu ora**, non è una chiave di
  nessun fornitore esterno: è la password che Make.com userà per
  autenticarsi con IL TUO servizio (impedisce a chiunque su internet di
  chiamarlo e bruciare il tuo budget Anthropic/Google/LiteAPI). Genera
  una stringa lunga e casuale, ad esempio con:

  ```
  python3 -c "import secrets; print(secrets.token_urlsafe(32))"
  ```

  Conservala: ti servirà due volte, identica, sia nella dashboard di
  Render (passo 3) sia nel modulo HTTP di Make.com (passo 5).

## 1. Metti il codice su GitHub (o GitLab)

Render fa il deploy da un repository Git. Se il codice di
`prototype/` non è già in un repo:

```bash
cd prototype
git init
git add .
git commit -m "Prototipo AI Travel Agency + microservizio Make.com"
```

Poi crea un repository (privato, consigliato — questo codice contiene la
logica di business) su GitHub e fai push seguendo le istruzioni che
GitHub mostra dopo averlo creato.

## 2. Crea il Web Service su Render

1. Vai su [render.com](https://render.com) e accedi (o registrati).
2. "New +" -> "Blueprint" -> collega il repository appena creato. Render
   troverà `render.yaml` in questo repo e proporrà automaticamente il
   servizio `ai-travel-agency-service` con build/start command già
   corretti — conferma.
   - In alternativa, senza Blueprint: "New +" -> "Web Service", collega il
     repo, Root Directory = `prototype` (se il repo contiene anche altro),
     Build Command = `pip install -r requirements.txt`, Start Command =
     `gunicorn service:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120`.
3. Scegli il piano (Starter è sufficiente per iniziare).

## 3. Imposta le variabili d'ambiente

Nella dashboard del servizio -> "Environment" -> aggiungi (i valori sono
TUOI, non li scrivo né li vedo mai):

| Chiave | Valore |
|---|---|
| `SERVICE_API_KEY` | la stringa casuale generata al passo 0 |
| `ANTHROPIC_API_KEY` | la tua chiave Claude reale |
| `GOOGLE_MAPS_KEY` | la tua chiave Google Maps reale (solo se userai `mode="live"`) |
| `LITEAPI_KEY` | la tua chiave LiteAPI reale (solo se userai `mode="live"`) |

Salva -> Render fa il deploy automaticamente.

## 4. Verifica che sia vivo

```bash
curl https://IL-TUO-SERVIZIO.onrender.com/health
```

Risposta attesa: `{"status": "ok", "test_suite": "534/534 (conteggio
automatico all'avvio del servizio)"}` — il numero esatto cresce da solo
a ogni nuovo test aggiunto al progetto (`service.py` lo calcola contando
la suite reale via `unittest` discovery all'avvio, non è più
un'etichetta scritta a mano: vedi `service.py::_compute_test_suite_label()`).

Poi un test end-to-end in `mode="mock"` (non spende nulla su Google/
LiteAPI, ma chiama Claude davvero — spende sulla tua chiave Anthropic):

```bash
curl -X POST https://IL-TUO-SERVIZIO.onrender.com/v1/itinerary \
  -H "Content-Type: application/json" \
  -H "X-Service-Key: LA-TUA-SERVICE_API_KEY" \
  -d '{
    "mode": "mock",
    "scenario_key": "happy_path",
    "trip": {
      "email": "cliente@mail.com",
      "scopo": "Torneo di tennis amatoriale",
      "destinazione": "Val d'\''Orcia, Toscana",
      "arrivo": "2026-09-14",
      "partenza": "2026-09-17",
      "budget": 0,
      "note": "Preferisco cene leggere la sera prima delle partite."
    }
  }'
```

Se ricevi una risposta 200 con `"itinerary": {...}` e `"validation":
{"passed": true, ...}`, il deploy funziona end-to-end.

**[AGGIUNTO 2026-07-14] Verifica specifica di `/v1/pdf` — fai questo test
SUBITO dopo il primo deploy**, prima di procedere a Make.com (vedi la nota
di onestà sul Dockerfile sopra: questo pezzo non è stato verificato dal
vivo da questo sandbox). Usa `include_guides`/`include_feedback`/
`include_map` a `false` per un test rapido che non spende sulla tua
chiave Anthropic e non richiede un `api_payload` completo:

```bash
curl -X POST https://IL-TUO-SERVIZIO.onrender.com/v1/pdf \
  -H "Content-Type: application/json" \
  -H "X-Service-Key: LA-TUA-SERVICE_API_KEY" \
  -d '{
    "trip": {
      "email": "test@test.com", "destination": "Roma",
      "date_start": "2026-09-01", "date_end": "2026-09-04",
      "duration_days": 3, "budget_eur": 0, "budget_mode": "UNLIMITED",
      "objective_function": "ENERGY_PACING"
    },
    "api_payload": {"hotels": [], "travel_times": [], "poi": []},
    "itinerary": {
      "destination": "Roma", "executive_summary": "Test.",
      "days": [{"day": 1, "title": "Giorno 1", "blocks": [
        {"time": "09:00", "activity": "Visita libera", "location": "Roma", "poi_id": null}
      ]}]
    },
    "include_guides": false, "include_feedback": false, "include_map": false
  }' | head -c 200
```

Se ricevi una risposta 200 con `"pdf_base64": "JVBERi0x..."` (l'inizio di
un vero PDF codificato in base64 inizia sempre con `JVBERi0`), il build
Docker e `wkhtmltopdf` funzionano sul server. Se invece ricevi un 500 con
un messaggio tipo "wkhtmltopdf non è installato" o il build Docker fallisce
nella dashboard di Render, il `Dockerfile` va corretto — probabile causa:
il pacchetto `.deb` scaricato da GitHub non è più disponibile a quell'URL
esatto (i pacchetti versionati a volte vengono spostati), verificare la
pagina release più recente su
https://github.com/wkhtmltopdf/packaging/releases e aggiornare l'URL nel
`Dockerfile` di conseguenza.

## 5. Contratto API (per il modulo HTTP di Make.com)

### `POST /v1/itinerary` — genera un itinerario da zero

Header richiesti: `Content-Type: application/json`, `X-Service-Key: <SERVICE_API_KEY>`.

Body:
```json
{
  "mode": "mock" | "live",
  "scenario_key": "happy_path",           // richiesto SOLO se mode="mock" — vedi src/mock_rag_data.py
  "trip": {
    "email": "...", "scopo": "...", "destinazione": "...",
    "arrivo": "YYYY-MM-DD", "partenza": "YYYY-MM-DD",
    "budget": 0, "note": "..."
  }
}
```
`trip` è esattamente la forma "stile Typeform" già usata da
`fixtures/trip_*.json` — lo stesso output grezzo che Make.com riceve dal
Nodo 1 (form del cliente), passato qui senza trasformazioni.

Risposta 200:
```json
{
  "trip": { ... Trip normalizzato, incluso objective_function dedotto ... },
  "api_payload": { "hotels": [...], "travel_times": [...], "poi": [...] },
  "itinerary": { ... JSON itinerario di Claude ... } | null,
  "parse_error": "..." | null,
  "geocoding_warning": "..." | null,
  "validation": {
    "passed": true | false,
    "summary": "PASS" | "FAIL — vedi dettagli sotto\n  [...]",
    "...vari campi *_ok e liste di violazioni, uno per ogni HARD_CONSTRAINT..."
  },
  "rendered_markdown": "# Il tuo viaggio a...\n..." | null
}
```

**Importante per Make.com**: salva la risposta intera (specialmente
`trip` e `api_payload`) da qualche parte persistente (es. Airtable — vedi
`airtable-data-moat-schema.md`) — servono INVARIATI per una eventuale
chiamata futura a `/v1/refine` per lo stesso cliente.

Errori: 400 (input del cliente malformato — `trip` incompleto o
`Trip.validate()` ha trovato errori, es. date incoerenti), 401 (header
`X-Service-Key` mancante/sbagliato, o il server non ha `SERVICE_API_KEY`
configurata), 500 (chiavi API mancanti sul server per la modalità
richiesta), 502 (fallimento nello strato dati per `mode="live"` —
Geocoding/LiteAPI/Places/Distance Matrix).

### `POST /v1/refine` — affina un itinerario già generato

Stessi header. Body:
```json
{
  "trip": { ... esattamente il campo "trip" restituito da /v1/itinerary ... },
  "api_payload": { ... esattamente il campo "api_payload" restituito da /v1/itinerary ... },
  "current_itinerary": { ... l'itinerario attuale da modificare ... },
  "customer_request": "Il cliente scrive: cambia il giorno 2, vorrei un ristorante vegetariano"
}
```

Risposta 200: `{"itinerary": {...}, "parse_error": ..., "validation": {...}, "rendered_markdown": "..."}`.

Non richiede una nuova chiamata dati dal vivo — riusa gli stessi dati già
verificati della generazione originale (stessa garanzia di Fedeltà RAG,
vedi il docstring di `src/refinement.py`).

### `POST /v1/pdf` — Nodo 10A, genera il PDF cliente finale [AGGIUNTO 2026-07-14]

Stessi header. Prende un itinerario già generato (uscito INVARIATO da
`/v1/itinerary` o `/v1/refine`) e produce lo stesso PDF che il CLI
produce con `--pdf` — guide turistiche per i POI usati, feedback
post-viaggio, cartina, sezioni curate "Dove mangiare"/"Shopping"/"Cosa
fare". Endpoint separato da `/v1/itinerary` apposta: chi non vuole un PDF
non paga il costo extra (le guide sono una chiamata Claude aggiuntiva per
ciascun POI usato, più una per il feedback).

Body:
```json
{
  "trip": { ... esattamente il campo "trip" restituito da /v1/itinerary/refine ... },
  "api_payload": { ... esattamente il campo "api_payload" restituito ... },
  "itinerary": { ... esattamente il campo "itinerary" restituito ... },
  "include_guides": true,    // opzionale, default true — richiede ANTHROPIC_API_KEY
  "include_feedback": true,  // opzionale, default true — richiede ANTHROPIC_API_KEY
  "include_map": true        // opzionale, default true — richiede GOOGLE_MAPS_KEY, degrada senza cartina se assente (mai un errore)
}
```

Con `include_guides` e `include_feedback` entrambi `false`, il PDF si
genera senza bisogno di `ANTHROPIC_API_KEY` sul server — utile per un
test rapido o per un PDF "leggero" più veloce da generare.

Risposta 200:
```json
{
  "pdf_base64": "JVBERi0xLjQK...",   // il PDF vero, codificato in base64
  "guides_requested": 3,             // quanti POI usati avrebbero avuto una guida (0 se include_guides=false)
  "guides_generated": 2,             // quante sono state generate con successo (può essere < requested, degrada senza rompere il PDF — vedi src/pdf_extras.py)
  "feedback_included": true,
  "map_included": true
}
```

In Make.com, il modulo successivo a questa chiamata HTTP dovrà convertire
`pdf_base64` in un file binario vero (Make.com ha un modulo nativo
"Base64 > Convert to file" o simile) prima di allegarlo a un'email o
salvarlo su Google Drive/Airtable.

Errori: 400 (campi mancanti o `trip`/`api_payload`/`itinerary` malformati
— stessa logica di validazione di `/v1/refine`), 401 (auth), 500
(`ANTHROPIC_API_KEY` mancante sul server quando richiesta da
`include_guides`/`include_feedback`, oppure `wkhtmltopdf` non disponibile/
fallito sul server — vedi la nota di onestà sul Dockerfile più sopra).

### `GET /health` — nessuna autenticazione, per il monitoraggio uptime

## 6. Configurazione del modulo HTTP in Make.com

Nel tuo scenario Make.com, dopo il Nodo 1 (raccolta dati cliente) e prima
del Nodo 10 (invio email/PDF al cliente):

1. Aggiungi un modulo **HTTP > Make a request**.
2. URL: `https://IL-TUO-SERVIZIO.onrender.com/v1/itinerary`
3. Method: `POST`
4. Headers:
   - `Content-Type: application/json`
   - `X-Service-Key: <la tua SERVICE_API_KEY>` — **salvala come variabile
     d'ambiente/connessione in Make.com, non incollarla in chiaro nel
     modulo**, così non finisce nei log dello scenario.
5. Body type: `Raw` / JSON, con il body descritto sopra, mappando i campi
   dal Nodo 1 (es. `{{1.email}}`, `{{1.scopo}}`, ecc. — la sintassi esatta
   dipende da come è configurato il tuo Nodo 1 in Make.com).
6. Parse response: attiva "Parse response" così Make.com espone i campi
   della risposta (`itinerary`, `validation.passed`, `rendered_markdown`,
   ...) come variabili per i moduli successivi.
7. Aggiungi un modulo condizionale (Router/Filter) su
   `validation.passed = true` per decidere se procedere con l'invio al
   cliente o deviare verso una revisione umana quando `false`.

**[AGGIORNATO 2026-07-14] Il connettore Make.com è già collegato a questa
sessione** — non serve più seguire la configurazione manuale sopra passo
per passo: posso costruire/configurare lo scenario direttamente tramite i
miei strumenti, appena il servizio è deployato e verificato (passo 4). La
procedura manuale resta qui come riferimento/documentazione del contratto
API, utile anche se un giorno lavori sullo scenario da un altro account
Make.com non collegato a una sessione Claude.

## 7. Testare la logica localmente (senza deploy)

Questo sandbox non ha accesso a PyPI (solo `api.anthropic.com`), quindi
`gunicorn` non è installabile qui — ma Flask ha un server di sviluppo già
disponibile, sufficiente per verificare la logica prima del deploy:

```bash
cd prototype
export SERVICE_API_KEY="qualcosa-a-caso-per-test-locali"
export ANTHROPIC_API_KEY="la-tua-chiave-vera-se-vuoi-un-test-reale"
python service.py
# in un altro terminale:
curl http://localhost:5000/health
```

La suite automatica (`tests/test_service.py` — il conteggio esatto cresce
da solo, vedi `/health` sopra per come vederlo sempre aggiornato; nessuna
vera chiamata API, sempre mockata) è comunque il modo principale con cui
questa logica è stata verificata in questo prototipo, non il server dev
manuale. Fa eccezione `wkhtmltopdf` stesso (il binario chiamato da
`/v1/pdf`): quello è realmente installato e usato in questo sandbox
(verificato con un vero PDF generato end-to-end, 2026-07-14) — solo la
sua installazione TRAMITE DOCKER su Render non è stata verificata dal
vivo, per il limite di rete già spiegato sopra.
