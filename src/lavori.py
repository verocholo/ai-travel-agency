"""I lavori lunghi, presi in carico e ritirati dopo — src/lavori.py.

[NUOVO 2026-08-10 — nasce da un guasto vero, misurato.]

## Il problema, con i numeri

Otto esecuzioni di produzione fallite di fila, tutte identiche: errore
`ModuleTimeoutError` sul modulo HTTP che chiama `/v1/itinerary`, e durata
**300,3 / 300,4 / 300,5 secondi**. Non è un caso limite: è il tetto rigido di
300 secondi del modulo HTTP di Make, colpito in pieno ogni volta.

Quel tetto **non si alza**, su nessun piano a pagamento. L'ultima esecuzione
riuscita è del 31 luglio e durava 96 secondi; da allora il documento è
cresciuto e la generazione ha superato i cinque minuti.

Il costo di ognuno di quei fallimenti non è zero: Make chiude la connessione,
ma il server continua a lavorare fino in fondo. Il cliente non riceve niente e
la generazione è stata pagata lo stesso.

## La soluzione, e perché questa

Si smette di tenere Make appeso. Chi chiede un itinerario riceve subito un
numero d'ordine; il lavoro va avanti per conto suo; chi ha chiesto ripassa a
ritirare quando è pronto.

Le alternative erano due, e sono state scartate per lo stesso motivo:
accorciare il ragionamento del modello o ridurre il documento avrebbero
riportato la chiamata sotto i 300 secondi **pagando con la qualità**, che è
esattamente ciò che non si vuole toccare. Qui il modello fa esattamente quello
che faceva ieri, con lo stesso prompt e lo stesso tempo: cambia solo chi
aspetta.

## Perché su disco e non in memoria

Il servizio gira con più processi (`gunicorn --workers 2`). Chi ripassa a
ritirare può finire su un processo diverso da quello che ha preso in carico il
lavoro: un dizionario in memoria sarebbe vuoto per metà delle richieste, in
modo intermittente e impossibile da riprodurre. Il disco è condiviso fra i
processi della stessa istanza.

Il disco di Render è effimero — a ogni deploy riparte vuoto. Va benissimo: un
lavoro dura minuti, non giorni, e un lavoro perso durante un riavvio è un
lavoro che comunque nessuno stava aspettando.

## Cosa NON fa

Non è una coda di lavoro seria: niente ritentativi, niente priorità, niente
garanzia di consegna. Se il processo muore a metà, il lavoro resta «in corso»
per sempre e chi ritira riceve un errore leggibile dopo la scadenza. Per il
volume di questo prodotto — un itinerario alla volta — è la scelta giusta:
un sistema di code vero costerebbe più di tutto il resto del servizio messo
insieme.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import tempfile
import time
from pathlib import Path

# I nomi ammessi per un numero d'ordine. Questa espressione NON è cosmesi: il
# numero arriva dall'esterno dentro l'indirizzo (`/v1/itinerary/esito/<id>`) e
# viene usato per comporre il nome di un file. Senza questo filtro, un id come
# `../../etc/passwd` farebbe leggere al servizio un file qualunque del disco.
# È la vulnerabilità più banale che esista e anche una delle più frequenti.
_ID_AMMESSO = re.compile(r"^[A-Za-z0-9_-]{8,64}$")

# Dopo quanto un lavoro si considera abbandonato. Più lungo della generazione
# più lenta mai misurata (356 s) con un margine largo: serve a distinguere
# «sta ancora lavorando» da «il processo è morto e nessuno finirà mai».
SCADENZA_SECONDI = 1800

# Da quanto tempo un file di lavoro può restare sul disco prima di essere
# buttato. I lavori finiti servono solo finché Make non li ritira.
ETA_MASSIMA_SECONDI = 24 * 3600

# Quanto a lungo, al massimo, chi ritira può restare in ascolto in una sola
# chiamata. Il numero non è arbitrario: il modulo HTTP di Make stacca a 300
# secondi esatti, e una risposta che arriva a 300,1 è una risposta persa. Dieci
# secondi di margine sono la differenza fra «ha aspettato il massimo possibile»
# e «ha aspettato invano».
ATTESA_MASSIMA_SECONDI = 290

# Ogni quanto si guarda se il lavoro è finito. Due secondi: abbastanza spesso
# da non aggiungere ritardo percepibile a una generazione di quattro minuti,
# abbastanza raro da non consumare la macchina leggendo un file.
INTERVALLO_CONTROLLO_SECONDI = 2.0


def cartella() -> Path:
    """Dove vivono i lavori. Si può spostare con `LAVORI_DIR`.

    Si legge a ogni chiamata invece di calcolarla una volta all'avvio: così i
    test possono spostarla senza reimportare il modulo, ed è anche il motivo
    per cui non c'è nessuna variabile globale da tenere allineata.

    ## Perché il disco vero, e non la cartella temporanea

    [CORRETTO 2026-08-11 — errore mio, scoperto un'ora dopo averlo commesso.]

    La traccia che un lavoro lascia mentre è vivo serve a una cosa sola:
    sopravvivere a chi l'ha scritta. Il primo giro la scriveva nella cartella
    temporanea, che su Render riparte VUOTA a ogni riavvio del contenitore —
    cioè esattamente nell'unico caso per cui la traccia era stata scritta.
    Una scatola nera che si cancella nell'incidente non è una scatola nera.

    Il servizio ha già un disco vero e permanente (`PUBLIC_FILES_DIR`, dove
    vivono le guide pubblicate): i lavori vanno lì. Effetto secondario e
    gradito: un documento già generato non si perde più a ogni riavvio, e chi
    ripassa a ritirarlo lo trova comunque.

    La cartella temporanea resta come ultima spiaggia — in sviluppo il disco
    non c'è, e un servizio che non parte perché manca una cartella sarebbe un
    guaio peggiore del problema che stiamo risolvendo.
    """
    scelta = (os.getenv("LAVORI_DIR") or "").strip()
    if not scelta:
        permanente = (os.getenv("PUBLIC_FILES_DIR") or "").strip()
        if permanente and Path(permanente).is_dir():
            scelta = str(Path(permanente) / "lavori")
    percorso = Path(scelta) if scelta else Path(tempfile.gettempdir()) / "lavori-itinerario"
    try:
        percorso.mkdir(parents=True, exist_ok=True)
    except OSError:
        # Il disco permanente può non essere scrivibile (permessi, spazio):
        # meglio un lavoro che vive nella cartella temporanea che un servizio
        # che non risponde più a nessuno.
        percorso = Path(tempfile.gettempdir()) / "lavori-itinerario"
        percorso.mkdir(parents=True, exist_ok=True)
    return percorso


def _file(identificativo: str) -> Path | None:
    if not isinstance(identificativo, str) or not _ID_AMMESSO.match(identificativo):
        return None
    return cartella() / f"{identificativo}.json"


def _scrivi(percorso: Path, dati: dict) -> None:
    """Scrittura atomica: prima un file temporaneo, poi lo si sposta.

    Senza questo, chi ritira mentre il file si sta scrivendo leggerebbe un
    JSON tagliato a metà — raro, non riproducibile, e proprio per questo il
    tipo di guasto che si scopre in produzione.
    """
    temporaneo = percorso.with_suffix(".tmp")
    temporaneo.write_text(json.dumps(dati), encoding="utf-8")
    os.replace(temporaneo, percorso)


def nuovo() -> str:
    """Prende in carico un lavoro e ne restituisce il numero d'ordine."""
    identificativo = secrets.token_urlsafe(12)
    percorso = _file(identificativo)
    _scrivi(percorso, {
        "stato": "in_corso",
        "creato": time.time(),
    })
    return identificativo


def salva_esito(identificativo: str, corpo, codice: int) -> None:
    """Il lavoro è finito: si mette da parte la risposta, com'è.

    `codice` è lo stato HTTP che avrebbe avuto la vecchia chiamata sincrona.
    Si conserva per intero, errori compresi: chi ritira deve ricevere
    esattamente quello che avrebbe ricevuto aspettando, altrimenti la strada
    nuova e quella vecchia si comporterebbero in modo diverso — ed è il tipo
    di differenza che si scopre solo dal cliente.
    """
    percorso = _file(identificativo)
    if percorso is None:
        return
    _scrivi(percorso, {
        "stato": "pronto",
        "creato": time.time(),
        "codice": int(codice),
        "corpo": corpo,
    })


def salva_guasto(identificativo: str, messaggio: str) -> None:
    """Il lavoro è morto per un'eccezione imprevista."""
    percorso = _file(identificativo)
    if percorso is None:
        return
    _scrivi(percorso, {
        "stato": "errore",
        "creato": time.time(),
        "codice": 500,
        "corpo": {"error": str(messaggio)[:500]},
    })


def leggi(identificativo: str) -> dict | None:
    """Lo stato di un lavoro, oppure `None` se quel numero non esiste.

    Un lavoro «in corso» da più della scadenza viene dichiarato morto: senza
    questo, un processo caduto lascerebbe Make a ripassare all'infinito su un
    lavoro che nessuno finirà mai.
    """
    percorso = _file(identificativo)
    if percorso is None or not percorso.exists():
        return None
    try:
        dati = json.loads(percorso.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(dati, dict):
        return None
    if dati.get("stato") == "in_corso":
        eta = time.time() - float(dati.get("creato") or 0)
        if eta > SCADENZA_SECONDI:
            return {
                "stato": "errore",
                "codice": 504,
                "corpo": {"error": "la generazione non è mai finita: il processo "
                                   "che la stava eseguendo è stato interrotto"},
            }
    return dati


def attendi(identificativo: str, secondi) -> dict | None:
    """Come `leggi()`, ma resta in ascolto finché il lavoro non è pronto.

    [AGGIUNTO 2026-08-10, dopo il primo giro con le attese a occhio.]

    La prima versione del meccanismo faceva aspettare CHI CHIEDE, a tempo
    fisso: Make dormiva 300 secondi, chiedeva, dormiva altri 180, richiedeva.
    Due difetti, entrambi seri:

      - se la generazione finiva in 200 secondi, si buttavano via 280 secondi
        di attesa inutile a ogni singolo cliente;
      - se finiva in 500, l'ultima domanda arrivava troppo presto e **tutto il
        lavoro veniva buttato** — otto minuti di generazione, pagata, persa.

    Un'attesa indovinata è sbagliata due volte su due. Qui non si indovina
    più: chi ritira resta in ascolto e riceve la risposta **nell'istante** in
    cui è pronta. Chi chiede non deve più sapere quanto ci vuole.

    Il tetto (`ATTESA_MASSIMA_SECONDI`) esiste perché chi ascolta dall'altra
    parte ha comunque il suo limite: si torna indietro poco prima, con un
    onesto «non ancora», e chi vuole richiama.
    """
    limite = _secondi_validi(secondi)
    scadenza = time.monotonic() + limite
    while True:
        dati = leggi(identificativo)
        # Sconosciuto, pronto, o dichiarato morto: in tutti e tre i casi non
        # c'è più niente da aspettare.
        if dati is None or dati.get("stato") != "in_corso":
            return dati
        rimasto = scadenza - time.monotonic()
        if rimasto <= 0:
            return dati
        time.sleep(min(INTERVALLO_CONTROLLO_SECONDI, rimasto))


def _secondi_validi(secondi) -> float:
    """Quanti secondi si può davvero aspettare, qualunque cosa sia arrivata.

    Il valore arriva dall'indirizzo (`?attendi=...`), cioè da fuori: può
    essere una parola, un numero negativo, o un milione. Nessuno di questi
    deve poter bloccare un processo del servizio.
    """
    try:
        richiesti = float(secondi)
    except (TypeError, ValueError):
        return 0.0
    if richiesti != richiesti:  # NaN: ogni confronto con NaN è falso
        return 0.0
    return max(0.0, min(richiesti, float(ATTESA_MASSIMA_SECONDI)))


def pulisci() -> int:
    """Butta i lavori vecchi. Ritorna quanti ne ha tolti. Non solleva mai."""
    tolti = 0
    adesso = time.time()
    try:
        for percorso in cartella().glob("*.json"):
            try:
                if adesso - percorso.stat().st_mtime > ETA_MASSIMA_SECONDI:
                    percorso.unlink()
                    tolti += 1
            except OSError:
                continue
    except OSError:
        return tolti
    return tolti


# ---------------------------------------------------------------------------
# Il battito: cosa stava facendo, e con quanta memoria, quando e' morto
# ---------------------------------------------------------------------------
# [AGGIUNTO 2026-08-11 — dopo due guasti identici e nessun modo di vederli.]
#
# Due esecuzioni di produzione morte allo stesso identico punto (368,9 s e
# 372,9 s, stesse quattro operazioni, stessi 4.185 byte) con un `502 Bad
# Gateway`: cioe' il contenitore che si spegne mentre lavora. Un 502 non dice
# niente — non viene dal nostro codice, e il nostro codice, essendo morto, non
# ha potuto scrivere nemmeno una riga.
#
# Da qui in poi il lavoro lascia una traccia mentre e' vivo: ogni pochi
# secondi scrive su disco da quanto sta lavorando e quanta memoria sta
# occupando. Quando il processo muore, l'ultima riga scritta resta — e dice
# se e' morto con 480 MB occupati (allora e' la memoria, e si compra il piano
# piu' grande sapendo perche') oppure con 120 MB (allora non e' la memoria, e
# si cerca altrove invece di spendere).
#
# La traccia non contiene NIENTE del cliente: solo secondi e megabyte.

INTERVALLO_BATTITO_SECONDI = 5.0


def memoria_mb() -> float | None:
    """Quanta memoria occupa adesso questo processo, in megabyte.

    Si legge da `/proc/self/status`, che su Linux c'e' sempre e non costa
    niente: nessuna libreria in piu' da installare per una misura che serve
    proprio quando le cose vanno male.
    """
    try:
        with open("/proc/self/status", encoding="utf-8") as f:
            for riga in f:
                if riga.startswith("VmRSS:"):
                    return round(int(riga.split()[1]) / 1024, 1)
    except (OSError, ValueError, IndexError):
        return None
    return None


def batti(identificativo: str) -> None:
    """Aggiorna la traccia di un lavoro vivo. Non solleva mai."""
    percorso = _file(identificativo)
    if percorso is None or not percorso.exists():
        return
    try:
        dati = json.loads(percorso.read_text(encoding="utf-8"))
        if not isinstance(dati, dict) or dati.get("stato") != "in_corso":
            return
        adesso = memoria_mb()
        dati["da_secondi"] = round(time.time() - float(dati.get("creato") or 0), 1)
        dati["memoria_mb"] = adesso
        if adesso is not None:
            dati["memoria_massima_mb"] = max(adesso, dati.get("memoria_massima_mb") or 0)
        _scrivi(percorso, dati)
    except (OSError, ValueError):
        return


def _errore_mostrabile(messaggio) -> str | None:
    """Un messaggio d'errore ripulito di quel poco che non deve uscire."""
    if not messaggio:
        return None
    testo = re.sub(r"[\w.+-]+@[\w-]+\.[\w.-]+", "<email>", str(messaggio))
    return testo[:400]


def ultimo() -> dict:
    """Il lavoro toccato piu' di recente, ridotto a cio' che si puo' mostrare.

    Serve a una pagina di stato pubblica: per questo esce SOLO quello che non
    dice niente di nessuno — stato, secondi, megabyte. Mai il corpo, mai il
    numero d'ordine per intero.
    """
    try:
        percorsi = sorted(cartella().glob("*.json"),
                          key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return {}
    for percorso in percorsi[:1]:
        try:
            dati = json.loads(percorso.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(dati, dict):
            return {}
        corpo = dati.get("corpo")
        errore = corpo.get("error") if isinstance(corpo, dict) else None
        return {
            "riferimento": percorso.stem[:4] + "\u2026",
            "stato": dati.get("stato"),
            "da_secondi": dati.get("da_secondi"),
            "memoria_mb": dati.get("memoria_mb"),
            "memoria_massima_mb": dati.get("memoria_massima_mb"),
            "codice": dati.get("codice"),
            # [AGGIUNTO 2026-08-11] Il messaggio d'errore, e solo quello.
            #
            # Make mostra il corpo di una risposta 4xx, ma di una 5xx scrive
            # soltanto «Couldn't connect»: la frase che spiega il guasto c'e',
            # viaggia, e non la legge nessuno. Un errore che non si puo'
            # leggere e' un errore che non aiuta.
            #
            # Qui esce ripulito: le email vanno via — un messaggio d'errore
            # non e' il posto dove far comparire l'indirizzo di un cliente su
            # una pagina senza chiave — e la lunghezza e' tagliata, perche'
            # questa e' una spia, non un archivio.
            "errore": _errore_mostrabile(errore),
        }
    return {}
