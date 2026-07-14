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
    && wget -q -O /tmp/wkhtmltox.deb \
       "https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6.1-3/wkhtmltox_0.12.6.1-3.bookworm_amd64.deb" \
    && apt-get install -y --no-install-recommends /tmp/wkhtmltox.deb \
    && rm -f /tmp/wkhtmltox.deb \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Stessa start command già in uso su Render/Procfile — invariata, il
# passaggio a Docker cambia solo COME viene costruita l'immagine, non
# come il servizio viene avviato.
CMD gunicorn service:app --bind 0.0.0.0:$PORT --workers 2 --timeout 280
