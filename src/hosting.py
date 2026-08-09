"""
Ospitalità dei file consegnati al cliente — src/hosting.py.

[AGGIUNTO 2026-08-03 — richiesta di Lorenzo: «zoom out dal macro al
micro». Il PDF principale deve diventare più scarno e ogni attrazione
deve avere la SUA guida in un documento separato, raggiungibile con un
link dal documento principale e con dentro un bottone "torna
all'itinerario". Fra le opzioni proposte Lorenzo ha scelto
esplicitamente: «PDF separati, ospitati su Render».]

Perché questo modulo esiste. Un link dentro un PDF può puntare solo a
qualcosa che ha una URL. Finché tutti i capitoli stavano dentro un unico
file, il rimando era un'ancora interna e non serviva niente; nel momento
in cui la guida del Duomo diventa un file a sé, quel file deve stare da
qualche parte su internet. E deve starci anche il documento PRINCIPALE,
altrimenti il bottone "torna all'itinerario" stampato sulla guida non ha
nessun posto dove tornare. Questo modulo è quel "da qualche parte": sa
salvare dei byte e restituire la URL con cui rileggerli.

Il modello di sicurezza, in una frase: **la URL è la credenziale**.

Non c'è login, non c'è una chiave HMAC, non c'è nessuna variabile
segreta nuova da configurare. Ogni "consegna" (= un itinerario, con
dentro il documento principale e tutte le sue guide) riceve alla nascita
un token casuale di 256 bit generato da `secrets.token_urlsafe`, e la
URL ha questa forma:

    https://<host>/f/<consegna>/<token>/<nome>.pdf

Chi ha la URL legge il file; chi non ce l'ha non può indovinarla. È lo
stesso schema di un link "chiunque abbia il link" di Google Drive o di
un link di reimpostazione password: si chiama URL a capacità. Le
conseguenze, dette per intero, sono tre e vanno sapute:

  1. il token non deve MAI finire in un log. Questo modulo non logga
     niente, mai — non ha nemmeno un logger. Ma il log degli accessi
     HTTP di Render registra il path completo di ogni richiesta, quindi
     il token ci finisce: vedi la nota nel capitolo 8 di DEPLOY.md, è un
     limite reale e dichiarato, non un dettaglio;
  2. il token va confrontato in tempo costante (`secrets.compare_digest`),
     altrimenti la latenza delle risposte lo rivela un carattere alla
     volta;
  3. il documento principale contiene i dati di una persona (nome,
     date, hotel). Un link non indovinabile NON è un'autenticazione.
     Il compromesso è scritto per esteso in DEPLOY.md ed è un punto da
     sottoporre all'avvocato: qui non si dichiara nessuna conformità.

Nella URL non compare nessun identificativo del cliente: né email, né
nome, né codice fiscale. `consegna` è una stringa opaca (nella pratica
il `ref` già usato da src/feedback_link.py, che è un HMAC troncato), e
`nome` descrive il CONTENUTO ("itinerario", "guida-duomo"), non la
persona.

API pubblica (le firme che chiamano gli altri moduli):

    is_configured() -> bool
    store(consegna, nome, blob, content_type="application/pdf") -> str | None
    resolve(consegna, token, nome) -> tuple[bytes, str] | None
    sweep(now=None) -> int

più tre aggiunte rispetto alla bozza iniziale, tutte e tre necessarie e
non decorative:

    reserve(consegna) -> str | None
    public_url(consegna, token, nome, content_type="application/pdf") -> str | None
    new_delivery_id() -> str

`reserve()` e `public_url()` esistono per un motivo preciso, che salta
fuori appena si prova a scrivere davvero il rimando incrociato: la guida
del Duomo contiene il bottone "torna all'itinerario", quindi deve
conoscere la URL del documento principale PRIMA che il documento
principale esista (il principale, a sua volta, contiene i link alle
guide, quindi non può essere costruito per primo). Con il solo `store()`
si avrebbe un uovo-e-gallina. `reserve()` fa nascere la consegna e
restituisce il token subito; `public_url()` calcola la URL di un file
che non è ancora stato scritto. L'ordine giusto per chi genera i PDF è:

    token = hosting.reserve(consegna)
    url_principale = hosting.public_url(consegna, token, "itinerario")
    # ...costruisci le guide con dentro url_principale, e salvale:
    url_guida = hosting.store(consegna, "guida-duomo", byte_guida)
    # ...costruisci il principale con dentro le url delle guide:
    hosting.store(consegna, "itinerario", byte_principale)

`store()` sulla stessa consegna riusa sempre lo stesso token, quindi la
URL calcolata da `public_url()` al passo 2 è esattamente quella che
`store()` restituirà al passo 4.

Nessuna di queste funzioni solleva mai un'eccezione e nessuna restituisce
mai una URL finta: quando qualcosa non va (non configurato, nome non
valido, disco pieno, tetto di spazio superato) il valore è `None`, così
chi genera il PDF può semplicemente non stampare il link invece di
stamparne uno morto. È la stessa regola già scritta in
src/feedback_link.py: meglio un capitolo senza riquadro che un riquadro
che porta al nulla.

Variabili d'ambiente:

    PUBLIC_FILES_DIR              cartella su disco dove vivono i file.
                                  Su Render deve stare sotto il punto di
                                  mount di un disco persistente, altrimenti
                                  ogni deploy cancella tutto (vedi
                                  render.yaml e il capitolo 8 di DEPLOY.md).
    PUBLIC_BASE_URL               base pubblica del servizio, `https://`
                                  assoluta con un host vero.
    PUBLIC_FILES_RETENTION_DAYS   dopo quanti giorni una consegna smette
                                  di esistere. Default 90.

Se le prime due mancano (o `PUBLIC_BASE_URL` non è `https://` con un host
vero) `is_configured()` è `False`, `store()` ritorna `None` e il prodotto
torna a essere esattamente quello di ieri: un unico PDF senza link. Nessun
crash, nessuna URL inventata.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

# ---------------------------------------------------------------------------
# Costanti. Sono costanti e non variabili d'ambiente di proposito: ogni
# variabile in più è una cosa che Lorenzo può impostare male a mano nella
# dashboard, e nessuna di queste ha bisogno di essere diversa fra un deploy
# e l'altro.
# ---------------------------------------------------------------------------

# 32 byte = 256 bit di entropia, ben oltre i 128 richiesti. `token_urlsafe`
# li codifica in 43 caratteri dell'alfabeto [A-Za-z0-9_-], cioè esattamente
# la stessa lista bianca usata per validare i segmenti della URL: il token
# non ha quindi mai bisogno di essere codificato per entrare in un path.
TOKEN_BYTES = 32

# La lista bianca. È volutamente più stretta del necessario: niente punto,
# niente barra, niente percento, niente lettere accentate. Tutto ciò che
# serve a costruire un `../` (o un `..%2f`, o un path assoluto, o un byte
# nullo) è fuori da questa classe di caratteri, quindi un nome che passa
# questo controllo NON PUÒ uscire dalla cartella della sua consegna. Il
# controllo viene fatto PRIMA di qualunque `os.path.join`, mai dopo.
#
# `re.fullmatch` e non `re.match` + `$`: `$` in Python accetta anche un
# `\n` finale ("abc\n" passerebbe), `fullmatch` no.
_SEGMENTO_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")
_TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{22,128}")

# Il registro di una consegna: token, data di nascita, elenco dei file.
_MANIFEST = "_consegna.json"

# `_consegna` passerebbe la lista bianca come nome di file. Il manifest non
# potrebbe comunque essere sovrascritto (l'estensione di un file salvato è
# sempre una di quelle qui sotto, mai `.json`), ma il nome resta riservato:
# due difese invece di una, al costo di una riga.
_NOMI_RISERVATI = frozenset({"_consegna"})

RETENTION_DEFAULT_DAYS = 90

# Tetto di spazio PER CONSEGNA. Il disco di Render è piccolo e finito, e un
# disco pieno non degrada: blocca il servizio intero, comprese le vendite.
# 20 MB sono molto più di un itinerario reale (un PDF principale scarno più
# trenta guide di poche pagine); superarli è il sintomo di un errore, non di
# un cliente esigente, quindi `store()` rifiuta invece di riempire il disco.
MAX_BYTES_PER_CONSEGNA = 20 * 1024 * 1024
MAX_FILE_PER_CONSEGNA = 60

# Lista bianca dei tipi. Non è burocrazia: servire `text/html` dal NOSTRO
# dominio significa regalare a chiunque riesca a far salvare un file un
# posto dove ospitare una pagina che sembra nostra (phishing) ed eseguire
# JavaScript nella nostra origine. I tipi ammessi sono quelli che il
# prodotto produce davvero, e nessun altro.
TIPI_AMMESSI = {
    "application/pdf": ".pdf",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
}

# Valore di confronto usato quando la consegna non esiste: serve solo a far
# costare uguale il caso "non esiste" e il caso "token sbagliato", così la
# latenza della risposta non dice a un curioso se una consegna sia mai
# esistita.
_ESCA = secrets.token_urlsafe(TOKEN_BYTES)


# ---------------------------------------------------------------------------
# Validazione
# ---------------------------------------------------------------------------

def _segmento_valido(valore: object) -> bool:
    """True se `valore` può entrare in un path senza poterne uscire."""
    return isinstance(valore, str) and _SEGMENTO_RE.fullmatch(valore) is not None


def _token_valido(valore: object) -> bool:
    return isinstance(valore, str) and _TOKEN_RE.fullmatch(valore) is not None


def _senza_estensione(nome: object) -> str | None:
    """`"guida-duomo.pdf"` -> `"guida-duomo"`, oppure None.

    La rotta HTTP riceve il nome CON l'estensione (è quello che sta nella
    URL e che il lettore PDF del cliente usa per decidere come aprire il
    file); il manifest lo indicizza SENZA. Qui si passa dall'uno all'altro,
    accettando solo le estensioni che questo modulo sa produrre: un
    `documento.php` o un `documento.` non arrivano nemmeno alla lista bianca
    del nome.
    """
    if not isinstance(nome, str) or len(nome) > 80:
        return None
    for ext in set(TIPI_AMMESSI.values()):
        if nome.endswith(ext):
            base = nome[: -len(ext)]
            return base if _segmento_valido(base) else None
    return None


def _valida_base_url(raw: object) -> str | None:
    """La base pubblica se può funzionare, None altrimenti. Non solleva mai.

    Scarta tutto ciò che non è una URL assoluta `https` con un host vero.
    `http://` è vietato in tutto il repo e a maggior ragione qui: su questa
    URL passa il documento con nome, date e hotel di una persona, e su
    `http` passerebbe in chiaro. Senza schema (`mio-servizio.onrender.com`)
    il link stampato nel PDF verrebbe risolto dal lettore come un file sul
    computer del cliente, cioè sarebbe un link morto e silenzioso — lo
    stesso identico modo di fallire già visto con FEEDBACK_FORM_URL il
    2026-08-03.

    Query e frammento vengono buttati: una base a cui si aggiunge un path
    non può averne. Anche l'eventuale `utente:password@` viene buttato,
    perché finirebbe stampato dentro il PDF.
    """
    if not isinstance(raw, str):
        return None
    testo = raw.strip()
    if not testo:
        return None
    try:
        pezzi = urlsplit(testo)
        host = (pezzi.hostname or "").lower()
    except ValueError:
        # URL sintatticamente indecifrabile (parentesi IPv6 sbilanciate...).
        return None
    if pezzi.scheme.lower() != "https" or not host:
        return None
    # Host che per definizione non ospitano niente di pubblico (RFC 2606 e
    # RFC 6761) più il caso "ho lasciato l'indirizzo di sviluppo".
    if host in {"localhost", "example.com", "example.net", "example.org"}:
        return None
    if host.endswith((".localhost", ".invalid", ".test", ".example",
                      ".example.com", ".example.net", ".example.org")):
        return None
    # Nessun host pubblico è privo di punto: `https://servizio/` è un nome di
    # rete interna, non un indirizzo che il cliente possa aprire da casa sua.
    if "." not in host:
        return None
    porta = f":{pezzi.port}" if pezzi.port else ""
    percorso = pezzi.path.rstrip("/")
    return f"https://{host}{porta}{percorso}"


# ---------------------------------------------------------------------------
# Configurazione
# ---------------------------------------------------------------------------

def base_url() -> str | None:
    """La base pubblica validata, senza barra finale, o None."""
    try:
        return _valida_base_url(os.getenv("PUBLIC_BASE_URL"))
    except Exception:  # noqa: BLE001 — nessun PDF fallisce per una variabile
        return None


def _radice() -> str | None:
    """La cartella su disco, o None se non impostata."""
    try:
        raw = (os.getenv("PUBLIC_FILES_DIR") or "").strip()
    except Exception:  # noqa: BLE001
        return None
    return raw or None


def retention_days() -> int:
    """Giorni di conservazione. Un valore assurdo torna al default invece di
    far fallire il servizio: 90 giorni sbagliati sono meglio di un 500."""
    try:
        raw = (os.getenv("PUBLIC_FILES_RETENTION_DAYS") or "").strip()
        if not raw:
            return RETENTION_DEFAULT_DAYS
        giorni = int(raw)
    except (TypeError, ValueError):
        return RETENTION_DEFAULT_DAYS
    if giorni < 1 or giorni > 3650:
        return RETENTION_DEFAULT_DAYS
    return giorni


def is_configured() -> bool:
    """True solo se ENTRAMBE le variabili sono impostate e utilizzabili.

    Non controlla che il disco esista o sia scrivibile: quello lo scopre
    `store()`, che in caso di problema ritorna `None` come per ogni altro
    fallimento. Questa funzione risponde a "il servizio è stato configurato
    per ospitare file?", non a "il disco funziona in questo istante?".
    """
    return _radice() is not None and base_url() is not None


# ---------------------------------------------------------------------------
# Manifest e scadenza
# ---------------------------------------------------------------------------

def _ora() -> datetime:
    return datetime.now(timezone.utc)


def _consapevole(momento: datetime) -> datetime:
    """Un `datetime` senza fuso viene letto come UTC invece di far esplodere
    il confronto con `TypeError`."""
    return momento if momento.tzinfo is not None else momento.replace(tzinfo=timezone.utc)


def _cartella(consegna: str) -> str | None:
    radice = _radice()
    if radice is None or not _segmento_valido(consegna):
        return None
    # [AGGIUNTO 2026-08-03] I nomi riservati valgono anche per la CONSEGNA e
    # non solo per i file dentro di essa. Non è una falla — `_consegna` non
    # esce da nessuna cartella — ma un'asimmetria: lo stesso nome era
    # rifiutato come file e accettato come consegna, e le asimmetrie in un
    # controllo di sicurezza sono il posto da cui poi nasce la falla vera.
    if consegna in _NOMI_RISERVATI:
        return None
    return os.path.join(radice, consegna)


def _leggi_manifest(cartella: str) -> dict | None:
    try:
        with open(os.path.join(cartella, _MANIFEST), "rb") as fh:
            dati = json.loads(fh.read().decode("utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    return dati if isinstance(dati, dict) else None


def _scrivi_atomico(percorso: str, contenuto: bytes) -> None:
    """Scrive tutto o niente. Un file mezzo scritto (deploy che riparte,
    disco che si riempie a metà) sarebbe un PDF corrotto consegnato a un
    cliente pagante, che è peggio di un PDF assente: stesso principio già
    applicato in src/pdf_renderer.py."""
    cartella = os.path.dirname(percorso)
    fd, temporaneo = tempfile.mkstemp(dir=cartella, suffix=".parziale")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(contenuto)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temporaneo, percorso)
    except BaseException:
        try:
            os.remove(temporaneo)
        except OSError:
            pass
        raise


def _scaduta(manifest: dict, adesso: datetime | None = None) -> bool:
    """True se la consegna non esiste più.

    Un manifest senza data, o con una data illeggibile, conta come SCADUTO:
    un registro che non si sa leggere non può essere servito in sicurezza
    (non si saprebbe nemmeno da quanto tempo esiste), e lasciarlo lì per
    sempre significherebbe solo occupare disco a vita.
    """
    creato = manifest.get("creato")
    if not isinstance(creato, str):
        return True
    try:
        nato = _consapevole(datetime.fromisoformat(creato))
    except (TypeError, ValueError):
        return True
    momento = _consapevole(adesso) if isinstance(adesso, datetime) else _ora()
    return momento >= nato + timedelta(days=retention_days())


# ---------------------------------------------------------------------------
# API pubblica
# ---------------------------------------------------------------------------

def new_delivery_id() -> str:
    """Un identificativo di consegna casuale, già conforme alla lista bianca.

    Serve solo a chi non ha già un codice opaco da usare. Chi genera i PDF
    dovrebbe invece passare il `ref` di src/feedback_link.py: è lo stesso
    codice che Make archivia in Airtable accanto al viaggio, quindi usarlo
    anche qui evita di avere due identificativi diversi per la stessa
    consegna.
    """
    return secrets.token_hex(8)


def public_url(consegna: str, token: str, nome: str,
               content_type: str = "application/pdf") -> str | None:
    """La URL di un file, anche se non è ancora stato scritto.

    Serve a rompere l'uovo-e-gallina descritto in cima al modulo: la guida
    di un'attrazione deve poter stampare il bottone "torna all'itinerario"
    prima che l'itinerario esista. Non tocca il disco e non verifica che il
    file ci sia: valida solo la forma dei tre segmenti.
    """
    base = base_url()
    if base is None:
        return None
    if not _segmento_valido(consegna) or not _token_valido(token):
        return None
    if not _segmento_valido(nome) or nome in _NOMI_RISERVATI:
        return None
    ext = TIPI_AMMESSI.get(content_type) if isinstance(content_type, str) else None
    if ext is None:
        return None
    return f"{base}/f/{consegna}/{token}/{nome}{ext}"


def reserve(consegna: str) -> str | None:
    """Fa nascere la consegna (se non esiste) e ritorna il suo token.

    Chiamarla due volte sulla stessa consegna ritorna lo stesso token: è
    quello che rende prevedibile la URL calcolata da `public_url()` prima
    ancora che `store()` scriva qualcosa.

    Una consegna già SCADUTA viene azzerata e rinasce con un token nuovo,
    invece di ritornare `None`: rigenerare il PDF di un viaggio vecchio
    (per una correzione, per un affinamento) deve continuare a funzionare
    per sempre. Il prezzo è che i vecchi link di quella consegna smettono
    di funzionare, ed è il prezzo giusto: erano già scaduti.
    """
    if not is_configured():
        return None
    cartella = _cartella(consegna)
    if cartella is None:
        return None
    try:
        manifest = _leggi_manifest(cartella)
        if manifest is not None and _scaduta(manifest):
            shutil.rmtree(cartella, ignore_errors=True)
            manifest = None
        if manifest is None:
            os.makedirs(cartella, exist_ok=True)
            manifest = {
                "token": secrets.token_urlsafe(TOKEN_BYTES),
                "creato": _ora().isoformat(),
                "file": {},
            }
            _scrivi_atomico(os.path.join(cartella, _MANIFEST),
                            json.dumps(manifest).encode("utf-8"))
        token = manifest.get("token")
        return token if _token_valido(token) else None
    except (OSError, ValueError):
        return None


def store(consegna: str, nome: str, blob: bytes,
          content_type: str = "application/pdf") -> str | None:
    """Salva `blob` dentro `consegna` col nome `nome` e ritorna la sua URL.

    `nome` è il nome SENZA estensione e descrive il contenuto, non il
    cliente: "itinerario", "guida-duomo", "cartina-giorno-2". L'estensione
    la mette questa funzione, derivandola dal tipo — così un chiamante non
    può far comparire un `.html` nella URL.

    Ritorna `None`, mai un'eccezione e mai una URL finta, quando: il
    servizio non è configurato; uno dei nomi non passa la lista bianca; il
    tipo non è fra quelli ammessi; il blob è vuoto o non è di byte; la
    consegna ha già raggiunto il tetto di spazio o di numero di file; il
    disco non collabora.
    """
    if not is_configured():
        return None
    if not _segmento_valido(consegna) or not _segmento_valido(nome):
        return None
    if nome in _NOMI_RISERVATI:
        return None
    if not isinstance(blob, (bytes, bytearray)) or len(blob) == 0:
        return None
    ext = TIPI_AMMESSI.get(content_type) if isinstance(content_type, str) else None
    if ext is None:
        return None

    cartella = _cartella(consegna)
    if cartella is None:
        return None

    try:
        if reserve(consegna) is None:
            return None
        manifest = _leggi_manifest(cartella)
        if manifest is None:
            return None
        voci = manifest.get("file")
        if not isinstance(voci, dict):
            voci = {}

        # Il tetto si calcola sui file DIVERSI da quello che stiamo per
        # scrivere: risalvare la stessa guida corretta non deve contare due
        # volte, altrimenti il secondo tentativo di generazione fallirebbe
        # per un motivo che non ha niente a che vedere col cliente.
        precedente = voci.get(nome) if isinstance(voci.get(nome), dict) else {}
        totale_altri = 0
        for chiave, voce in voci.items():
            if chiave == nome or not isinstance(voce, dict):
                continue
            try:
                totale_altri += int(voce.get("byte") or 0)
            except (TypeError, ValueError):
                continue
        if totale_altri + len(blob) > MAX_BYTES_PER_CONSEGNA:
            return None
        if nome not in voci and len(voci) >= MAX_FILE_PER_CONSEGNA:
            return None

        nome_file = f"{nome}{ext}"
        _scrivi_atomico(os.path.join(cartella, nome_file), bytes(blob))

        # Se lo stesso nome cambia tipo (una cartina prima png e poi jpg) il
        # vecchio file resterebbe sul disco senza più nessuna voce nel
        # manifest, cioè invisibile a `store()` e mai più cancellato prima
        # della scadenza: spazio perso in silenzio.
        vecchio = precedente.get("file") if isinstance(precedente, dict) else None
        if isinstance(vecchio, str) and vecchio != nome_file:
            try:
                os.remove(os.path.join(cartella, vecchio))
            except OSError:
                pass

        voci[nome] = {"file": nome_file, "tipo": content_type, "byte": len(blob)}
        manifest["file"] = voci
        _scrivi_atomico(os.path.join(cartella, _MANIFEST),
                        json.dumps(manifest).encode("utf-8"))
        return public_url(consegna, manifest.get("token"), nome, content_type)
    except (OSError, ValueError):
        return None


def resolve(consegna: str, token: str, nome: str) -> tuple[bytes, str] | None:
    """I byte e il tipo del file, oppure `None`.

    `nome` è quello che compare nella URL, quindi CON l'estensione.

    `None` è deliberatamente la risposta a ogni forma di fallimento —
    consegna inesistente, token sbagliato, consegna scaduta, file
    inesistente, nome malformato — e i casi non sono distinguibili né dal
    valore di ritorno né dal tempo impiegato. Distinguerli significherebbe
    rispondere a "questo codice è mai esistito?" a chiunque lo chieda, che
    è esattamente l'informazione che una URL a capacità non deve dare.
    """
    if not is_configured():
        return None
    if not _segmento_valido(consegna) or not _token_valido(token):
        return None
    base = _senza_estensione(nome)
    if base is None or base in _NOMI_RISERVATI:
        return None

    cartella = _cartella(consegna)
    if cartella is None:
        return None

    try:
        manifest = _leggi_manifest(cartella)
        if manifest is None:
            # Stesso costo del confronto vero: la latenza non deve dire se
            # la consegna esista.
            secrets.compare_digest(token, _ESCA)
            return None
        atteso = manifest.get("token")
        if not isinstance(atteso, str) or not secrets.compare_digest(token, atteso):
            return None
        if _scaduta(manifest):
            return None
        voci = manifest.get("file")
        voce = voci.get(base) if isinstance(voci, dict) else None
        if not isinstance(voce, dict):
            return None
        # Il nome su disco lo ha deciso `store()` (nome validato + estensione
        # da lista bianca). Confrontarlo con quello chiesto impedisce che
        # `guida.png` serva il contenuto di `guida.pdf` con il tipo sbagliato.
        if voce.get("file") != nome:
            return None
        tipo = voce.get("tipo")
        if tipo not in TIPI_AMMESSI:
            return None
        with open(os.path.join(cartella, nome), "rb") as fh:
            return fh.read(), tipo
    except (OSError, TypeError, ValueError):
        return None


def sweep(now=None) -> int:
    """Cancella le consegne scadute. Ritorna quante ne ha cancellate.

    Prudente di proposito: tocca solo le cartelle il cui nome passa la
    lista bianca E che contengono un `_consegna.json`. Una cartella che non
    ha quel file non è roba nostra (`lost+found` di un disco appena
    montato, un residuo di un altro strumento) e non viene sfiorata, perché
    il costo di sbagliare qui è cancellare dati di qualcun altro.
    """
    if not is_configured():
        return 0
    radice = _radice()
    try:
        elenco = os.listdir(radice)
    except OSError:
        return 0

    rimosse = 0
    for voce in elenco:
        if not _segmento_valido(voce):
            continue
        cartella = os.path.join(radice, voce)
        try:
            if not os.path.isdir(cartella):
                continue
            if not os.path.exists(os.path.join(cartella, _MANIFEST)):
                continue
            manifest = _leggi_manifest(cartella)
            if manifest is not None and not _scaduta(manifest, now):
                continue
            shutil.rmtree(cartella, ignore_errors=True)
            if not os.path.exists(cartella):
                rimosse += 1
        except (OSError, TypeError, ValueError):
            # Una cartella che dà problemi non deve impedire la pulizia
            # delle altre: il disco pieno è il problema che stiamo evitando.
            continue
    return rimosse
