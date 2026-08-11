# [AGGIUNTO 2026-07-14 — preparativi Make.com, nuovo endpoint POST /v1/pdf]
#
# Perché un Dockerfile e non più solo `runtime: python` (buildpack nativo
# di Render): il nuovo endpoint `POST /v1/pdf` chiama `wkhtmltopdf`
# (binario ESTERNO, non installabile con `pip` — vedi la nota di onestà
# nel docstring di src/pdf_renderer.py), che il buildpack Python nativo di
# Render non fornisce. Serve quindi un'immagine Docker che lo installi
# esplicitamente.
#
# Verificato (ricerca web, 2026-07-14): il pacchetto `wkhtmltopdf` nei
# repository apt di Debian è stato rimosso da Debian Trixie e porta una
# CVE nota irrisolta (CVE-2022-35583) sulla build Bookworm ancora
# disponibile — non usarlo. Si usa invece il pacchetto .deb ufficiale
# "Qt patchata" (headless, nessun server X necessario) distribuito dal
# repository wkhtmltopdf/packaging su GitHub, stessa versione (0.12.6)
# già in uso e verificata in questo prototipo.
#
# [NOTA DI ONESTÀ] Questo Dockerfile è stato scritto sulla base di
# documentazione ufficiale verificata via ricerca web, MA non è stato
# possibile costruire e testare l'immagine end-to-end da questo ambiente
# sandbox: l'accesso a github.com da qui è limitato dal proxy di rete di
# Anthropic Code (i download di release binarie da repository non
# esplicitamente abilitati vengono bloccati), quindi non ho potuto
# scaricare davvero il pacchetto .deb per verificarlo. Resta quindi
# "scritto", non ancora "pronto" nel senso di verificato dal vivo — vedi
# il passo di verifica esplicito nella sezione 4 di DEPLOY.md, da fare
# SUBITO dopo il primo deploy, prima di collegare Make.com.

FROM python:3.11-slim

# Dipendenze runtime di wkhtmltopdf (patched Qt) — elenco verificato via
# ricerca web sulla documentazione ufficiale del progetto.
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget ca-certificates fontconfig libfontconfig1 libjpeg62-turbo libxrender1 \
    xfonts-75dpi xfonts-base \
    `# [2026-08-02] fonts-dejavu-core serve a src/map_render.py: python:3.11-slim` \
    `# non ha NESSUN font TrueType, e senza Pillow ripiega sul bitmap 6x11 di` \
    `# default — i nomi delle tappe uscirebbero illeggibili sulla cartina.` \
    fonts-dejavu-core \
    && wget -q -O /tmp/wkhtmltox.deb \
       "https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6.1-3/wkhtmltox_0.12.6.1-3.bookworm_amd64.deb" \
    && apt-get install -y --no-install-recommends /tmp/wkhtmltox.deb \
    && rm -f /tmp/wkhtmltox.deb \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# [AGGIORNATO 2026-07-31 — audit di perfezionamento] `--timeout 120` era un
# rischio latente: una generazione lenta (Opus per un viaggio >10gg/EXCLUSIVITY,
# o /v1/pdf che fa una chiamata Claude per ogni POI + il subprocess wkhtmltopdf)
# può superare 120s e vedersi killare il worker (il client riceve una
# connessione chiusa, NON il JSON che il contratto promette). Alzato a 300s,
# coerente col `timeout: 300` dei moduli HTTP di Make.com e col timeout=280 del
# client Anthropic. `--threads 4` (worker gthread): i worker non si bloccano più
# su I/O di rete, così l'health check di Render e le altre richieste rispondono
# anche mentre una generazione lunga è in corso (prima 2 chiamate lente
# saturavano entrambi i worker sync, /health incluso → riavvii a catena).
# Procfile allineato a questa stessa riga.
#
# [CAMBIATO 2026-08-10 — da un 502 vero, misurato.] Da due processi a UNO,
# con il doppio dei filoni: `--workers 1 --threads 8`.
#
# Il motivo. Il piano di Render e' `starter`, cioe' 512 MB. Ogni processo
# gunicorn tiene in piedi la sua copia completa dell'applicazione, e durante
# una generazione ci stanno dentro l'itinerario, le fotografie scaricate e sei
# documenti da stampare e cucire. Due copie di tutto questo in 512 MB e' una
# scommessa; quando la si perde Render non lo dice con un errore, spegne il
# contenitore — e chi stava aspettando riceve un `502 Bad Gateway` che non
# viene dal nostro codice e non spiega niente. E' successo alle 16:19 del 10
# agosto, dopo 369 secondi, e con ogni probabilita' e' anche il motivo per cui
# nel giro precedente la generazione «non era ancora pronta» dopo otto minuti:
# non era lenta, era morta a meta' senza dirlo a nessuno.
#
# Un solo processo dimezza la memoria di base e non toglie niente: il prodotto
# genera un itinerario alla volta, e gli otto filoni bastano largamente per
# l'health check di Render, per chi ritira un lavoro e per chi scarica una
# guida mentre una generazione e' in corso. In piu' toglie di mezzo
# un'ambiguita': con un processo solo, chi prende in carico un lavoro e chi
# passa a ritirarlo sono sempre lo stesso.
#
# `--timeout` alzato a 600. Da oggi una richiesta di ritiro puo' restare
# aperta fino a 290 secondi per aspettare che il lavoro finisca (vedi
# `src/lavori.py`): con il tetto a 300 si correva lungo il bordo per niente.
CMD gunicorn service:app --bind 0.0.0.0:$PORT --workers 1 --threads 8 --timeout 600
