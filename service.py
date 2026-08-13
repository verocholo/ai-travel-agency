#!/usr/bin/env python3
"""
service.py — Microservizio HTTP che wrappa la pipeline Python già testata
(vedi tests/ — il conteggio esatto e sempre aggiornato è calcolato in
automatico all'avvio, vedi `_compute_test_suite_label()` sotto e la
risposta di `GET /health`, così questo commento non può più andare stale
come già successo una volta con un numero scritto a mano qui) per l'uso
da Make.com (Nodo 8/9 di BLUEPRINT_MAKE.md).

[AGGIUNTO 2026-07-12 — Lorenzo: "il prossimo passo è make.com?" -> "Non
ancora, ma andiamo lo stesso" (customer discovery non ancora fatta, ma si
procede comunque con Make.com) -> scelta esplicita di architettura fra due
alternative proposte, Lorenzo ha scelto: "Wrappo la pipeline Python
esistente (consigliato)"]

Perché un wrapper e non una riscrittura nativa nei moduli Make.com: la
pipeline Python ha 389 test verdi che verificano bug REALI già trovati e
corretti in questo stesso progetto (Fedeltà RAG, leak di id grezzi nel
testo libero, pacing energetico, alert di budget, enum sicuri prima di
ogni chiamata a Claude — vedi certainty-matrix.md). Riscrivere la stessa
logica nei moduli visuali di Make.com rischierebbe concretamente di
reintrodurre esattamente quei bug già chiusi (es. la regex a bordo di
parola per il leak di id non è banale da replicare in un modulo Make
nativo). Questo file espone quella stessa logica, invariata, dietro poche
righe di trasporto HTTP.

Endpoint:
  GET  /health         — liveness check, nessuna autenticazione (per il
                          monitoraggio uptime di Render.com/Make.com)
  POST /v1/itinerary   — Nodo 2->9: genera un itinerario completo da zero
                          (mode=mock usa dati RAG finti, utile per testare
                          il wiring Make.com senza spendere in Google/
                          LiteAPI; mode=live usa la pipeline reale)
  POST /v1/refine      — secondo turno: affina un itinerario già generato
                          in base a una richiesta del cliente in linguaggio
                          naturale (stessa logica di --refine nel CLI)
  GET  /f/<consegna>/<token>/<nome>
                        — [AGGIUNTO 2026-08-03] serve i documenti ospitati
                          (l'itinerario e le guide per attrazione). NON
                          autenticata di proposito: a chiamarla è il
                          CLIENTE dal suo PDF, non Make. La credenziale è
                          il token nella URL. Vedi src/hosting.py.
  GET  /v1/diagnostica  — [AGGIUNTO 2026-08-03] dice quali pezzi opzionali
                          del prodotto sono configurati sul server e cosa
                          perde il cliente per ognuno che manca. Autenticata.
  GET  /v1/diagnostica/immagini
                        — [AGGIUNTO 2026-08-03 (ter)] chiama davvero Google
                          e Wikimedia, una volta ciascuno, e dice se le
                          cartine e le fotografie vere funzionano. Costa
                          circa quattro centesimi invece dei ~1,50 € di un
                          itinerario intero. Autenticata.
  POST /v1/manutenzione/pulizia
                        — cancella i documenti ospitati scaduti.
                          Autenticata come tutto il resto.

Autenticazione: header `X-Service-Key` confrontato con la variabile
d'ambiente SERVICE_API_KEY (impostata SOLO sulla piattaforma di deploy,
mai in questo repo). Se SERVICE_API_KEY non è impostata sul server, ogni
richiesta viene rifiutata — fail-closed: un servizio inutilizzabile per
un errore di configurazione è preferibile a un servizio aperto a chiunque
su internet, capace di bruciare il budget Anthropic/Google/LiteAPI reale
di Lorenzo con richieste anonime.

Le chiavi API REALI (ANTHROPIC_API_KEY, GOOGLE_MAPS_KEY, LITEAPI_KEY) non
vengono MAI accettate nel body di una richiesta — vivono solo come
variabili d'ambiente sul server (stesso oggetto SETTINGS già usato da
main.py). Make.com non le vede mai, non può fare leak di credenziali reali
anche se un URL venisse loggato o intercettato per errore.
"""
from __future__ import annotations

import base64
import hmac
import os
import tempfile
import threading
import time
import pathlib
from pathlib import Path

from flask import Flask, jsonify, make_response, request
from werkzeug.exceptions import HTTPException

from src.config import SETTINGS
from src.pipeline import run_live_from_raw, run_mock_from_raw
from src.payload_builder import assemble_payload
from src.schemas import ApiPayload, Hotel, POI, Trip, TravelTime
from src.triage import normalize_raw_input
from src import refinement
from src import foto
from src import pdf_renderer
from src.pdf_extras import (
    build_pdf_extras,
    build_pdf_sections,
    aggiungi_ritorno_al_foglio_valigia,
    publish_hosted_guides,
    prepara_fascicolo,
    allega_foglio_valigia,
    split_render_kwargs,
)
# [AGGIUNTI 2026-08-01 — punti 2 e 5 del feedback "da investitore"]
# cost_telemetry: misura il costo REALE di ogni generazione (finora mai
# misurato, quindi ogni ragionamento su prezzo e margine era un'opinione).
# alerting: rende rumoroso un fallimento che finora era silenzioso.
from src import alerting
from src import cost_telemetry
from src import lavori
# [AGGIUNTO 2026-08-03 - task #185] Serve a /v1/diagnostica per dire non
# solo se la variabile del modulo Tally c'e', ma se il suo valore puo'
# davvero funzionare: e' la differenza fra i due difetti che Lorenzo ha
# visto, "manca" e "c'e' ma porta al 404".
from src import feedback_link
from src import hosting
from src import diagnostica_immagini

app = Flask(__name__)

# [AGGIUNTO 2026-07-31 — audit di perfezionamento] Limite dimensione body: senza
# `MAX_CONTENT_LENGTH`, `request.get_json` bufferizza in memoria l'intero body
# PRIMA che l'auth venga controllata — pochi POST giganti concorrenti su un
# piano Render starter (RAM limitata, 2 worker) possono causare OOM/kill dei
# worker (DoS). I payload legittimi (form Tally + api_payload) stanno ampiamente
# sotto: 2 MB è un tetto generoso. Werkzeug risponde 413 (JSON, via l'error
# handler globale) prima di leggere tutto.
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024


def _conta_i_test_senza_eseguirli() -> int:
    """Quanti test ha la suite, contati LEGGENDO i file, non importandoli.

    [RISCRITTO 2026-08-11 — e la riscrittura nasce da un guasto di produzione.]

    Prima qui c'era `unittest.TestLoader().discover(...)`, con questa
    rassicurazione nel commento: «sola ENUMERAZIONE dei test — nessuno viene
    eseguito, quindi nessun impatto sul tempo di avvio». La frase e' vera e
    completamente fuorviante: per enumerare i test, `discover()` **importa
    ogni singolo file di test**. E un modulo importato non si scarica piu'.

    Cosa vuol dire in produzione: il contenitore che serve i clienti teneva in
    memoria, per sempre, tutti i moduli di prova del progetto — con le loro
    finte, i loro dati di esempio costruiti all'importazione e tutte le
    librerie che tirano dentro. Non per lavorare: per **scrivere un numero su
    una pagina di stato**.

    E il costo cresceva da solo. Quando questa funzione e' stata scritta la
    suite aveva 404 test; oggi ne ha piu' di 1600. Nessuno ha cambiato niente
    qui: e' peggiorata quattro volte da sola, in silenzio, mentre il servizio
    gira su un piano da 512 MB.

    Contare leggendo la struttura del file — senza importare niente — da' lo
    STESSO numero, e non lascia niente in memoria. L'ereditarieta' va
    considerata: una classe di prova che ne estende un'altra eredita anche i
    suoi test, ed e' esattamente la differenza (dieci test) che separava una
    prima versione ingenua dal numero vero.
    """
    import ast as _ast

    cartella = pathlib.Path(os.path.dirname(os.path.abspath(__file__))) / "tests"
    propri: dict = {}
    basi: dict = {}
    per_nome: dict = {}

    for percorso in sorted(cartella.glob("test_*.py")):
        try:
            albero = _ast.parse(percorso.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        for nodo in albero.body:
            if not isinstance(nodo, _ast.ClassDef):
                continue
            chiave = (percorso.name, nodo.name)
            propri[chiave] = {
                c.name for c in nodo.body
                if isinstance(c, (_ast.FunctionDef, _ast.AsyncFunctionDef))
                and c.name.startswith("test")
            }
            basi[chiave] = [b.id for b in nodo.bases if isinstance(b, _ast.Name)]
            per_nome.setdefault(nodo.name, []).append(chiave)

    def _con_ereditati(chiave, visti=None):
        visti = visti if visti is not None else set()
        if chiave in visti:
            return set()
        visti.add(chiave)
        nomi = set(propri.get(chiave, ()))
        for base in basi.get(chiave, ()):
            for candidata in per_nome.get(base, ()):
                nomi |= _con_ereditati(candidata, visti)
        return nomi

    return sum(len(_con_ereditati(chiave)) for chiave in propri)


def _compute_test_suite_label() -> str:
    """L'etichetta mostrata su /health.

    Resta calcolata e non scritta a mano: era una costante («404/404») gia'
    disallineata dalla realta' il giorno in cui e' stata trovata, ed e' il
    motivo per cui questa funzione esiste. Cambia solo il MODO di contare —
    vedi `_conta_i_test_senza_eseguirli()`.

    Se il deploy non include la cartella `tests/`, degrada in modo esplicito
    invece di mostrare uno 0/0 fuorviante.
    """
    try:
        quanti = _conta_i_test_senza_eseguirli()
        if quanti == 0:
            return "sconosciuto (cartella tests/ non trovata in questo deploy)"
        return f"{quanti}/{quanti} (conteggio automatico all'avvio del servizio)"
    except Exception as e:  # noqa: BLE001 — una pagina di stato non fa cadere niente
        return f"sconosciuto (conteggio della suite fallito: {e})"


TEST_SUITE_STATUS = _compute_test_suite_label()

# Da quando questo processo e' vivo. Serve a una cosa sola ma decisiva: se la
# pagina di stato dice «acceso da 40 secondi» mentre un lavoro dovrebbe essere
# in corso da sei minuti, allora il processo e' stato riavviato — ed e' il
# riavvio, non la lentezza, la cosa da spiegare.
_ACCESO_DA = time.time()

# Il codice con cui il servizio dice «ho lavorato, e quello che e' venuto fuori
# non si puo' consegnare».
#
# [SCELTO 2026-08-11, dopo averci perso mezza giornata.] Era 502. Sembrava la
# scelta giusta — «l'aiuto a monte mi ha dato una risposta inservibile» e' la
# definizione da manuale di un 502 — ed e' stata la scelta piu' costosa di
# tutta la settimana: **Make, davanti a una risposta 5xx, scrive soltanto
# «Couldn't connect» e butta via il corpo.** La frase in italiano che spiega
# esattamente cosa e' andato storto veniva scritta, spedita, e non letta da
# nessuno. Tre esecuzioni fallite di fila e mezza giornata passata a cercare un
# guasto di infrastruttura che non c'era, mentre la risposta viaggiava dentro
# ogni singola richiesta.
#
# 422 e' altrettanto corretto — «ho capito la richiesta, ma il contenuto non e'
# lavorabile» — e Make il corpo di un 4xx lo mostra. La regola generale, che
# vale oltre questo progetto: **il codice giusto e' quello che fa arrivare il
# messaggio a chi deve leggerlo.** Un errore illeggibile non e' un errore: e'
# un silenzio con un numero sopra.
_CODICE_ERRORE_LEGGIBILE = 422


def _check_auth() -> str | None:
    """Ritorna un messaggio di errore se l'autenticazione fallisce, None se ok.

    [AGGIUNTO 2026-07-13 — audit di revisione completa] Il confronto era
    `provided != expected` (`!=` sulle stringhe) — un confronto normale
    interrompe il confronto carattere per carattere non appena trova la
    prima differenza, quindi il tempo di risposta varia leggermente in
    base a QUANTI caratteri iniziali della chiave indovinata sono
    corretti (timing attack: un aggressore che misura con precisione la
    latenza di molte richieste può, in teoria, ricostruire la chiave un
    carattere alla volta). `hmac.compare_digest()` confronta sempre in
    tempo costante, indipendentemente da dove/se le stringhe divergono —
    stesso principio raccomandato dalla documentazione Python stessa per
    confronti di credenziali/token."""
    expected = os.getenv("SERVICE_API_KEY")
    provided = request.headers.get("X-Service-Key")
    if not expected:
        return "servizio non configurato: SERVICE_API_KEY assente sul server (fail-closed)"
    # [AGGIORNATO 2026-07-31 — audit di perfezionamento, bug reale eseguito]
    # `hmac.compare_digest()` su stringhe con caratteri NON-ASCII solleva
    # `TypeError: comparing strings with non-ASCII characters is not supported`
    # → un header X-Service-Key con accenti/emoji dava 500 invece del 401
    # uniforme (un aggressore poteva distinguere i due casi). Confronto in
    # BYTE: elimina il TypeError mantenendo il tempo costante. `provided`
    # None è già escluso dal `not provided`.
    if not provided or not hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8")):
        return "non autorizzato: header X-Service-Key mancante o non valido"
    return None


@app.errorhandler(Exception)
def _handle_unexpected_error(e):
    """
    [AGGIUNTO 2026-07-13 — audit di revisione completa, bug reale
    riprodotto] Rete di sicurezza finale che garantisce il contratto
    documentato in DEPLOY.md ("ogni risposta è JSON con uno status code
    chiaro") anche per eccezioni non previste esplicitamente da nessuna
    route. Riprodotto concretamente: un body con JSON annidato a
    dismisura (es. migliaia di `[` innestati) fa sollevare a
    `request.get_json(silent=True)` un `RecursionError` — `silent=True`
    sopprime solo gli errori di parsing "normali" (JSON malformato), NON
    RecursionError, che quindi si propagava fino a diventare una pagina
    HTML generica di Werkzeug invece di un errore leggibile — rompendo
    il parsing lato Make.com (Nodo 8/9), che si aspetta sempre JSON.
    Senza questo handler, QUALUNQUE altro bug non ancora scoperto
    avrebbe lo stesso problema; con questo handler, degrada sempre a un
    500 JSON leggibile invece che a una pagina HTML.
    """
    if isinstance(e, HTTPException):
        # 404, 405, 413... sono errori del CHIAMANTE: rumorosi per niente se
        # finissero nell'allarme. Restano nei log, come oggi.
        return jsonify({"error": e.description}), e.code
    app.logger.exception("Errore interno non gestito")
    # [AGGIUNTO 2026-08-01] Un 500 non previsto da nessuna route è, per
    # definizione, il caso che non abbiamo saputo anticipare: è esattamente
    # quello che non deve restare sepolto in un log che nessuno guarda.
    # `notify()` non solleva mai — vedi la regola 1 in src/alerting.py — quindi
    # non può trasformare un 500 leggibile in una pagina HTML di Werkzeug.
    alerting.notify("errore_interno", f"{e.__class__.__name__}: {e}")
    return jsonify({
        "error": f"errore interno del servizio ({e.__class__.__name__}): {e}"
    }), 500


def _preview_trip_error(raw_trip: dict) -> str | None:
    """
    [AGGIUNTO 2026-07-12 — bug reale trovato dalla propria suite di test di
    service.py, non da Lorenzo] Bug: l'ordine originale controllava PRIMA
    le variabili d'ambiente del server (SETTINGS.missing_for_*_mode()) e
    SOLO DOPO provava a interpretare 'trip' — quindi un cliente che manda
    un 'trip' malformato (es. senza 'email') riceveva un fuorviante 500
    "variabili d'ambiente mancanti sul server" invece di un chiaro 400
    "campo obbligatorio mancante", ogni volta che il server non ha ancora
    le chiavi reali impostate (esattamente la situazione di QUESTO sandbox
    — vedi src/config.py — ma anche di un deploy reale con un tipo di
    errore del cliente mascherato da un problema lato server). Un errore
    del CLIENTE deve sempre essere un 400 leggibile, mai un 500, a
    prescindere da cos'altro non sia ancora configurato lato server.

    Ritorna un messaggio di errore se 'trip' non ha la forma attesa,
    altrimenti None. Richiama `normalize_raw_input()`/`Trip.validate()` —
    le STESSE funzioni pure richiamate di nuovo dentro
    run_mock_from_raw()/run_live_from_raw(): la doppia chiamata è
    volutamente ridondante (stessa rete di sicurezza già usata per
    Trip.validate() nel resto della pipeline, vedi certainty-matrix.md),
    non una seconda implementazione parallela che rischia di disallinearsi.
    """
    try:
        trip = normalize_raw_input(raw_trip)
    except KeyError as e:
        return f"campo obbligatorio mancante in 'trip': {e}"
    except (ValueError, TypeError, AttributeError) as e:
        # [AGGIORNATO 2026-07-31 — audit di perfezionamento] TypeError/
        # AttributeError aggiunti: un campo del form col TIPO sbagliato (numero
        # al posto di testo, ecc. — output tipico di un modulo HTTP Make.com che
        # interpola campi Tally grezzi) può ancora produrre queste eccezioni. Un
        # errore del CLIENTE deve sempre essere un 400 leggibile, mai un 500.
        return f"campo 'trip' malformato: {e}"
    trip_errors = trip.validate()
    if trip_errors:
        return f"Trip non valido: {trip_errors}"
    return None


def _serialize_validation_report(vr) -> dict | None:
    if vr is None:
        return None
    return {
        "passed": vr.passed,
        "summary": vr.summary(),
        "format_compliance_ok": vr.format_compliance_ok,
        "format_errors": vr.format_errors,
        "rag_fidelity_ok": vr.rag_fidelity_ok,
        "hallucinated_poi_ids": vr.hallucinated_poi_ids,
        "geospatial_overlap_ok": vr.geospatial_overlap_ok,
        "geospatial_errors": vr.geospatial_errors,
        "no_id_leakage_ok": vr.no_id_leakage_ok,
        "leaked_raw_ids": vr.leaked_raw_ids,
        "energy_pacing_ok": vr.energy_pacing_ok,
        "energy_pacing_violations": vr.energy_pacing_violations,
        "budget_compliance_ok": vr.budget_compliance_ok,
        "budget_compliance_violations": vr.budget_compliance_violations,
        # [AGGIUNTO 2026-07-31 — regola anti-noia, [HARD_CONSTRAINTS] punto 9]
        # Warning NON bloccanti: `passed` resta vero anche a lista piena (vedi
        # validator.check_day_density). Esposti qui perché Make possa
        # loggarli/allertare senza bloccare la consegna del PDF al cliente.
        "day_density_warnings": getattr(vr, "day_density_warnings", []),
    }


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "test_suite": TEST_SUITE_STATUS})


@app.route("/salute-lavori", methods=["GET"])
def salute_lavori():
    """Come sta il servizio, e com'e' andato l'ultimo lavoro. Senza chiave.

    [AGGIUNTO 2026-08-11 — perche' la diagnosi non puo' dipendere da chi ha
    tempo di aprire un cruscotto.]

    Due esecuzioni di produzione morte allo stesso punto con un `502 Bad
    Gateway`: il contenitore si spegne mentre lavora, e un 502 non spiega
    niente. La domanda che decide tutto e' una sola — **con quanta memoria
    stava girando quando e' morto?** Se erano 480 MB su 512, e' la memoria e
    si compra il piano piu' grande sapendo perche'. Se erano 120, non e' la
    memoria e cercarla sarebbe buttare soldi.

    Questa pagina risponde a quella domanda con un tocco, da telefono, senza
    chiavi da incollare in un browser. Non e' protetta di proposito, e puo'
    permetterselo: qui non passa niente di nessuno. Escono lo stato del
    processo e due numeri in megabyte — nessuna destinazione, nessuna email,
    nessun documento, e del numero d'ordine solo le prime quattro lettere,
    che non bastano a ritirare niente (il ritiro vuole comunque la chiave).
    """
    return jsonify({
        "memoria_adesso_mb": lavori.memoria_mb(),
        "acceso_da_secondi": round(time.time() - _ACCESO_DA, 1),
        "ultimo_lavoro": lavori.ultimo(),
        "test_suite": TEST_SUITE_STATUS,
    })


@app.route("/prova-collegamenti", methods=["GET"])
def prova_collegamenti():
    """I rimandi interni sopravvivono al motore di stampa DI QUESTA macchina?

    [AGGIUNTO 2026-08-13 — richiesta di Lorenzo: «ho la necessita' che tu
    trovi un modo per avere la certezza matematica».]

    E' l'unica domanda di questo progetto a cui in sviluppo non si puo'
    rispondere, perche' in sviluppo il difetto non esiste: il binario di
    `wkhtmltopdf` di produzione ha le patch, quello della sandbox no, e la
    differenza fra i due ha azzerato per una settimana tutta la navigazione
    del documento venduto senza che nessuna prova diventasse rossa.

    Qui la domanda viene posta al motore che sta girando adesso, su questa
    macchina, con le stesse identiche parole con cui si stampa il documento
    vero (`pdf_renderer.COMANDO_STAMPA`). Si legge la riga `verdetto`.

    Senza chiave, come `/salute-lavori`, e per lo stesso motivo: e' una
    diagnosi che deve poter fare Lorenzo da telefono con un tocco, e qui non
    passa niente di nessuno — due paginette bianche fatte in casa, nessun
    dato, nessuna rete, nessuna chiamata a pagamento.
    """
    from src import prova_stampa

    if not prova_stampa.prova_abilitata():
        return jsonify({"errore": "prova spenta da PROVA_STAMPA_SPENTA"}), 403
    return jsonify(prova_stampa.prova_collegamenti())


@app.route("/v1/itinerary", methods=["POST"])
def create_itinerary():
    """La strada di sempre: si chiede, si aspetta, si riceve.

    Resta invariata e continuera' a esistere: la usano i test, il CLI e
    chiunque non abbia il problema del tetto di cinque minuti. Chi ce l'ha
    — Make — usa `/v1/itinerary/avvia` qui sotto, che fa ESATTAMENTE lo
    stesso lavoro chiamando questa stessa funzione.
    """
    auth_error = _check_auth()
    if auth_error:
        return jsonify({"error": auth_error}), 401
    corpo, codice = _normalizza_esito(_esegui_itinerario(request.get_json(silent=True)))
    return jsonify(corpo), codice


def _normalizza_esito(esito) -> tuple:
    """`(corpo, codice)` sia che la funzione abbia dichiarato il codice o no."""
    if isinstance(esito, tuple):
        return esito[0], esito[1]
    return esito, 200


def _esegui_itinerario(body):
    """Genera l'itinerario e ritorna `(dizionario, codice HTTP)`.

    [ESTRATTO 2026-08-10] Era il corpo di `create_itinerary()`. E' stato
    tirato fuori senza cambiare UNA VIRGOLA della logica, perche' adesso
    serve a due chiamanti — la strada sincrona di sempre e quella presa in
    carico — e due copie della stessa logica sono il modo con cui, fra sei
    mesi, il documento generato in un modo diventa diverso da quello
    generato nell'altro senza che nessuno sappia dire quando e' successo.
    E' lo stesso principio gia' scritto in `_parse_trip_and_api_payload`.

    Il travestimento di `jsonify` qui sotto merita una spiegazione, perche'
    a prima vista sembra un trucco — e lo e', ma deliberato. Questo corpo
    contiene una dozzina di `return jsonify({...}), 400`. Riscriverli tutti
    a mano avrebbe voluto dire trascrivere novanta righe di codice che
    funziona, con la probabilita' di sbagliarne una in silenzio. Dichiarando
    qui dentro una funzione con lo stesso nome che restituisce il dizionario
    invece della risposta HTTP, il corpo resta IDENTICO carattere per
    carattere e produce naturalmente la coppia `(dizionario, codice)`.
    Il `jsonify` vero lo applica il chiamante.
    """
    def jsonify(x):  # noqa: A001 — vedi la spiegazione nel docstring
        return x

    if not isinstance(body, dict):
        return jsonify({"error": "body JSON mancante o non valido"}), 400

    mode = body.get("mode")
    raw_trip = body.get("trip")
    if mode not in ("mock", "live"):
        return jsonify({"error": "'mode' deve essere 'mock' o 'live'"}), 400
    if not isinstance(raw_trip, dict):
        return jsonify({"error": "'trip' mancante o non è un oggetto — atteso lo stesso "
                                  "formato 'stile Typeform' delle fixtures/trip_*.json "
                                  "(email, scopo, destinazione, arrivo, partenza, budget, note)"}), 400

    # Un 'trip' malformato è un errore del CLIENTE (400) — va controllato
    # PRIMA delle chiavi d'ambiente del server (500), altrimenti un server
    # non ancora configurato (come questo sandbox) maschererebbe l'errore
    # del cliente dietro un fuorviante 500 — vedi il docstring di
    # _preview_trip_error() per il bug reale trovato.
    if mode == "mock" and not body.get("scenario_key"):
        return jsonify({"error": "'scenario_key' richiesto quando mode='mock' "
                                  "(vedi src/mock_rag_data.py per le chiavi disponibili)"}), 400

    trip_error = _preview_trip_error(raw_trip)
    if trip_error:
        return jsonify({"error": trip_error}), 400

    # [AGGIUNTO 2026-08-01 — misura del costo reale] Il blocco `measure()`
    # installa un contatore per QUESTA richiesta: ogni chiamata a Claude e ogni
    # chiamata alle API esterne fatta qui dentro si registra da sola, senza che
    # nessuna funzione della pipeline debba passarsi un parametro in più. Fuori
    # da questo blocco quelle stesse registrazioni sono no-op — è per questo
    # che il CLI e i test non cambiano comportamento di una virgola.
    with cost_telemetry.measure("itinerary") as ledger:
        try:
            if mode == "mock":
                scenario_key = body.get("scenario_key")
                missing = SETTINGS.missing_for_mock_mode()
                if missing:
                    return jsonify({"error": f"variabili d'ambiente mancanti sul server: {missing}"}), 500
                result = run_mock_from_raw(raw_trip, scenario_key, SETTINGS.anthropic_api_key)
            else:
                missing = SETTINGS.missing_for_live_mode()
                if missing:
                    return jsonify({"error": f"variabili d'ambiente mancanti sul server: {missing}"}), 500
                result = run_live_from_raw(raw_trip, SETTINGS)
        except KeyError as e:
            return jsonify({"error": f"campo obbligatorio mancante in 'trip': {e}"}), 400
        except ValueError as e:
            # Trip non valido (Trip.validate() ha trovato errori) o data non ISO
            return jsonify({"error": str(e)}), 400

    if result.data_layer_error:
        # [AGGIUNTO 2026-08-01] Il cliente ha già pagato quando arriviamo qui:
        # un errore dello strato dati va saputo subito, non scoperto da chi ha
        # pagato e non riceve niente.
        alerting.notify(
            "data_layer_error",
            result.data_layer_error,
            context=alerting.safe_trip_context(result.trip),
        )
        return jsonify({
            "error": f"errore nello strato dati (Geocoding/LiteAPI/Places/Distance Matrix): "
                     f"{result.data_layer_error}",
            "trip": result.trip.to_dict(),
        }), 502

    if result.parse_error:
        # La risposta del modello non è JSON valido: l'itinerario esce vuoto e
        # tutto il resto del flusso Make fallisce a valle. È un fallimento
        # vero, anche se la risposta HTTP è 200.
        alerting.notify(
            "parse_error",
            result.parse_error,
            context=alerting.safe_trip_context(result.trip),
        )

    risposta = {
        "trip": result.trip.to_dict(),
        "api_payload": result.api_payload.to_dict() if result.api_payload else None,
        "itinerary": result.itinerary,
        "parse_error": result.parse_error,
        "geocoding_warning": result.geocoding_warning,
        "validation": _serialize_validation_report(result.validation_report),
        "rendered_markdown": result.rendered_markdown,
        # [AGGIUNTO 2026-08-01] Quanto è costato DAVVERO generare questo
        # itinerario, in euro. Vedi src/cost_telemetry.py: i conteggi di token
        # e di chiamate sono esatti, i prezzi unitari sono un listino
        # configurabile da confermare (campo `prezzi_da_verificare`).
        "cost_estimate": ledger.to_dict(),
    }

    # [AGGIUNTO 2026-08-10 — dopo che questa cosa e' arrivata fino in fondo.]
    #
    # Fino a oggi la riga qui sopra diceva, testualmente: «E' un fallimento
    # vero, anche se la risposta HTTP e' 200». Era scritto nero su bianco nel
    # codice, e nessuno aveva tirato la conseguenza: **allora non deve essere
    # 200**. Un itinerario senza giornate non e' un itinerario magro, e' un
    # oggetto vuoto che manda avanti tutta la catena a costruire un documento
    # su niente.
    #
    # E' esattamente quello che e' successo il 10 agosto: il modello non ha
    # prodotto niente di leggibile, questa rotta ha risposto 200, il modulo
    # dopo ha provato a stampare il vuoto ed e' morto con un `400 Bad
    # Request` — cioe' con l'errore piu' lontano possibile dalla causa. Otto
    # minuti per scoprire, nel posto sbagliato, una cosa che si sapeva gia'
    # qui.
    #
    # Il lavoro non si butta: il corpo esce per intero, `parse_error`
    # compreso. Cambia solo il codice, che e' l'unica cosa che Make guarda.
    if not _itinerario_utilizzabile(result.itinerary):
        risposta["error"] = (
            "il modello non ha prodotto un itinerario utilizzabile (nessuna "
            "giornata): non c'e' niente da stampare"
            + (f" — {result.parse_error}" if result.parse_error else ""))
        return jsonify(risposta), _CODICE_ERRORE_LEGGIBILE

    return jsonify(risposta)


def _itinerario_utilizzabile(itinerary) -> bool:
    """Un itinerario si puo' stampare solo se ha almeno una giornata.

    E' la stessa identica condizione che `/v1/pdf` controlla in ingresso. Che
    sia scritta due volte non e' una svista: qui serve a fermare la catena
    SUBITO, con un messaggio che nomina la causa vera; li' serve a difendersi
    da chiunque chiami quella rotta. La differenza che conta e' che adesso
    l'errore arriva nel punto in cui il guasto e' avvenuto, e non otto minuti
    dopo, travestito da «richiesta malformata».
    """
    return isinstance(itinerary, dict) and bool(itinerary.get("days"))


@app.route("/v1/itinerary/avvia", methods=["POST"])
def avvia_itinerario():
    """Prende in carico la generazione e risponde SUBITO con un numero d'ordine.

    [AGGIUNTO 2026-08-10 — da un guasto vero, misurato otto volte.]

    Il modulo HTTP di Make ha un tetto rigido di **300 secondi** che non si
    alza su nessun piano a pagamento. La generazione di un itinerario ha
    superato quel tetto — otto esecuzioni di produzione morte a 300,3 / 300,4
    / 300,5 secondi — e ogni volta il cliente non ha ricevuto niente mentre la
    generazione veniva pagata lo stesso, perche' il server continuava a
    lavorare anche dopo che Make aveva chiuso la connessione.

    Qui si smette di tenere qualcuno appeso: si risponde in un decimo di
    secondo con un numero d'ordine, il lavoro prosegue per conto suo, e chi ha
    chiesto ripassa a ritirare su `/v1/itinerary/esito/<numero>`.

    **La qualita' non c'entra e non e' stata toccata.** Il modello riceve lo
    stesso prompt di ieri e ci mette lo stesso tempo: cambia soltanto chi
    aspetta. Le due alternative — accorciare il ragionamento o ridurre il
    documento — avrebbero pagato il tempo con la qualita', ed erano proprio
    cio' che non si voleva.

    Risponde **202** (preso in carico), non 200: e' il codice che dice «ho
    accettato, non ho ancora finito», ed e' cio' che rende leggibile la
    differenza fra questa rotta e quella di sempre guardando solo i log.
    """
    auth_error = _check_auth()
    if auth_error:
        return jsonify({"error": auth_error}), 401

    body = request.get_json(silent=True)
    # Si controlla SOLO la forma del contenitore, non il contenuto. Tutto il
    # resto della validazione resta dentro `_esegui_itinerario`, in un posto
    # solo: se la ricopiassimo qui per rispondere 400 piu' in fretta, avremmo
    # due validazioni destinate a divergere, che e' il difetto che questo
    # progetto ha gia' pagato altrove. Un `trip` sbagliato produce quindi un
    # numero d'ordine, e l'errore 400 si legge al ritiro — identico a quello
    # che avrebbe dato la strada sincrona.
    if not isinstance(body, dict):
        return jsonify({"error": "body JSON mancante o non valido"}), 400

    return _prendi_in_carico(_esegui_itinerario, body, "itinerario")


def _prendi_in_carico(esecutore, body, nome_lavoro):
    """Avvia un lavoro lungo in disparte e risponde con il numero d'ordine.

    [FATTORIZZATO 2026-08-10] Nasce dalla presa in carico dell'itinerario e
    adesso serve anche al fascicolo, che ha lo stesso identico problema. Una
    sola copia per un motivo preciso: qui dentro c'e' la rete che salva un
    lavoro morto (`salva_guasto`). Duplicandola, la seconda copia
    dimenticherebbe un pezzo — e il pezzo dimenticato sarebbe proprio quello
    che si vede solo quando qualcosa va storto, cioe' mai in prova.
    """
    lavori.pulisci()
    identificativo = lavori.nuovo()

    finito = threading.Event()

    def _battito():
        """Lascia una traccia mentre il lavoro e' vivo.

        [AGGIUNTO 2026-08-11] Due esecuzioni di produzione sono morte allo
        stesso identico punto con un `502 Bad Gateway`, cioe' con il
        contenitore che si spegne mentre lavora. Un processo morto non scrive
        niente, per definizione: l'unico modo di sapere com'e' morto e' che
        abbia gia' scritto qualcosa PRIMA. Ogni cinque secondi finiscono su
        disco da quanto sta lavorando e quanta memoria occupa — e quando muore
        l'ultima riga resta li'.
        """
        while not finito.wait(lavori.INTERVALLO_BATTITO_SECONDI):
            lavori.batti(identificativo)

    threading.Thread(target=_battito, daemon=True).start()

    def _lavora():
        try:
            with app.app_context():
                corpo, codice = _normalizza_esito(esecutore(body))
            lavori.salva_esito(identificativo, corpo, codice)
        except Exception as e:  # noqa: BLE001 — vedi sotto
            # Qualunque eccezione qui NON ha piu' nessuno a cui risalire: siamo
            # in un thread staccato, e senza questa rete il lavoro resterebbe
            # «in corso» per sempre e Make ripasserebbe all'infinito. Meglio un
            # errore scritto e leggibile al ritiro.
            lavori.salva_guasto(identificativo, f"{type(e).__name__}: {e}")
            alerting.notify(f"lavoro_{nome_lavoro}_fallito", f"{type(e).__name__}: {e}")
        finally:
            finito.set()

    threading.Thread(target=_lavora, daemon=True).start()

    return jsonify({
        "stato": "in_corso",
        "job_id": identificativo,
        # L'indirizzo di ritiro e' sempre quello generico, e non quello
        # "dell'itinerario" o "del pdf": esiste una sola strada per ritirare
        # qualunque lavoro, quindi non puo' esistere il caso in cui questo
        # campo indica una strada che non c'e'. (Prima lo componeva il nome
        # del lavoro — «itinerario» — e sarebbe uscito /v1/itinerario/esito/,
        # che non e' una rotta di questo servizio: sbagliato, e sbagliato in
        # silenzio, perche' oggi nessuno lo legge.)
        "ritira_su": f"/v1/esito/{identificativo}",
        # Un'indicazione onesta a chi deve decidere ogni quanto ripassare. La
        # generazione piu' lenta mai misurata e' stata di 356 secondi.
        "riprova_fra_secondi": 45,
    }), 202


@app.route("/v1/pdf/avvia", methods=["POST"])
def avvia_pdf():
    """Prende in carico la costruzione del fascicolo. Gemella di `/v1/itinerary/avvia`.

    [AGGIUNTO 2026-08-10] Il tetto di 300 secondi del modulo HTTP di Make vale
    per ogni chiamata, non solo per la prima. Con le guide davvero generate —
    cinque chiamate al modello — piu' le fotografie e sei documenti da
    stampare e cucire, questa fase ci arriva. Non e' una previsione prudente:
    e' la stessa aritmetica che la settimana scorsa ha ucciso otto esecuzioni
    di fila sull'altra rotta.

    Il ritiro si fa su `/v1/pdf/esito/<numero>`, con lo stesso `?attendi=`.
    """
    auth_error = _check_auth()
    if auth_error:
        return jsonify({"error": auth_error}), 401

    body = request.get_json(silent=True)
    # Stesso principio della gemella: qui si guarda solo la forma del
    # contenitore, la validazione vera resta in un posto solo.
    if not isinstance(body, dict):
        return jsonify({"error": "body JSON mancante o non valido"}), 400

    return _prendi_in_carico(_esegui_pdf, body, "pdf")


@app.route("/v1/itinerary/esito/<identificativo>", methods=["GET"])
@app.route("/v1/pdf/esito/<identificativo>", methods=["GET"])
@app.route("/v1/esito/<identificativo>", methods=["GET"])
def esito_itinerario(identificativo):
    """Ritira un itinerario preso in carico.

    Tre risposte possibili, e sono pensate per essere distinguibili da un
    modulo HTTP senza dover leggere il contenuto:

      - **202** — non e' ancora pronto, ripassa;
      - **200** — eccolo, ed e' esattamente il corpo che avrebbe restituito la
        vecchia chiamata sincrona, senza una virgola di differenza;
      - **404** — questo numero d'ordine non esiste (o e' scaduto).

    Se la generazione e' fallita, qui esce lo stesso codice di errore che
    sarebbe uscito aspettando (400, 502, 500...). E' deliberato: la strada
    nuova e quella vecchia devono comportarsi allo stesso modo anche quando
    vanno male, altrimenti la differenza si scopre dal cliente.

    ## `?attendi=<secondi>` — e perche' esiste

    [AGGIUNTO 2026-08-10, dopo il primo giro in produzione.]

    Senza, chi ritira deve indovinare quanto dormire prima di ripassare. Il
    primo giro dormiva 300 secondi e poi altri 180: se la generazione finiva
    prima si buttava via l'attesa, e se finiva dopo si buttava via **la
    generazione intera**, gia' pagata. Un'attesa a tempo fisso e' sbagliata
    in tutti e due i versi.

    Con `?attendi=280` la domanda resta aperta e la risposta arriva
    nell'istante in cui e' pronta. Chi chiede non deve piu' sapere niente su
    quanto ci vuole — che e' esattamente cio' che non puo' sapere.
    """
    auth_error = _check_auth()
    if auth_error:
        return jsonify({"error": auth_error}), 401

    dati = lavori.attendi(identificativo, request.args.get("attendi"))
    if dati is None:
        return jsonify({
            "error": "numero d'ordine sconosciuto: o non e' mai esistito, o il "
                     "servizio e' stato riavviato, o e' passato troppo tempo",
        }), 404

    if dati.get("stato") == "in_corso":
        return jsonify({"stato": "in_corso", "job_id": identificativo,
                        "riprova_fra_secondi": 45}), 202

    corpo = dati.get("corpo")
    if not isinstance(corpo, dict):
        corpo = {"error": "esito illeggibile"}
    return jsonify({"stato": dati.get("stato"), **corpo}), int(dati.get("codice") or 200)


def _parse_trip_and_api_payload(body: dict) -> tuple:
    """
    [AGGIUNTO 2026-07-14 — preparativi Make.com] Fattorizzato da dentro
    refine() per essere riusato anche da /v1/pdf — stesso 'trip' +
    'api_payload' nella stessa identica forma (quella restituita da
    /v1/itinerary), stesso principio anti-desync già seguito altrove in
    questo progetto: mai due implementazioni parallele dello stesso
    parsing/validazione (vedi anche src/pdf_extras.py per lo stesso
    principio applicato alla logica di generazione PDF).

    Assume che il chiamante abbia già verificato che 'trip' e
    'api_payload' siano chiavi presenti in `body` — i campi TOP-LEVEL
    richiesti non sono gli stessi per ogni endpoint (es. /v1/refine
    richiede anche 'current_itinerary'/'customer_request', /v1/pdf
    richiede anche 'itinerary'), quindi quel controllo resta specifico
    di ciascuna route.

    Ritorna `(trip, api_payload, None)` se valido, oppure
    `(None, None, (error_body, status_code))` — un errore CLIENTE (400)
    da restituire subito, PRIMA di controllare le variabili d'ambiente
    del server (stesso principio già applicato a _preview_trip_error()).
    """
    # [AGGIORNATO 2026-07-31 — audit di perfezionamento, bug reale eseguito]
    # `body["api_payload"] or {}` protegge solo None/falsy: un api_payload
    # TRUTHY ma non-dict (lista/stringa, da un wiring Make.com sbagliato o da un
    # client ostile) passava, e poi `.get("hotels")` → AttributeError NON
    # catturato (l'except era solo TypeError) → HTTP 500. Guardia esplicita di
    # tipo + AttributeError/ValueError aggiunti all'except come rete.
    if not isinstance(body.get("trip"), dict):
        return None, None, ({"error": "'trip' deve essere un oggetto"}, 400)
    if body.get("api_payload") is not None and not isinstance(body.get("api_payload"), dict):
        return None, None, ({"error": "'api_payload' deve essere un oggetto (o assente)"}, 400)
    try:
        trip = Trip(**body["trip"])
        api_payload_dict = body["api_payload"] or {}
        hotels = [Hotel(**h) for h in api_payload_dict.get("hotels", [])]
        pois = [POI(**p) for p in api_payload_dict.get("poi", [])]
        travel_times = [TravelTime(**t) for t in api_payload_dict.get("travel_times", [])]
    except (TypeError, AttributeError, ValueError) as e:
        return None, None, ({"error": f"'trip' o 'api_payload' non hanno la forma attesa "
                                       f"(devono essere esattamente quelli restituiti da "
                                       f"/v1/itinerary): {e}"}, 400)

    # [AGGIUNTO 2026-07-13 — audit di revisione completa, bug reale
    # trovato ed eseguito] `Trip(**body["trip"])` sopra costruisce
    # l'oggetto senza controllare i VALORI dei campi (solo `TypeError` per
    # campi mancanti/in più) — un 'trip' con, ad es., date_start >=
    # date_end, un budget_eur negativo, o un objective_function non
    # valido veniva costruito comunque e passava indenne fino
    # all'affinamento, esattamente il bug che `Trip.validate()` esiste
    # per impedire in create_itinerary()/_preview_trip_error(). Stesso
    # principio applicato qui: un `trip` malformato deve dare un 400
    # leggibile, mai un comportamento indefinito a valle.
    trip_errors = trip.validate()
    if trip_errors:
        return None, None, ({"error": f"'trip' non valido: {trip_errors}"}, 400)

    api_payload = ApiPayload(hotels=hotels, travel_times=travel_times, poi=pois)
    return trip, api_payload, None


@app.route("/v1/refine", methods=["POST"])
def refine():
    auth_error = _check_auth()
    if auth_error:
        return jsonify({"error": auth_error}), 401

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"error": "body JSON mancante o non valido"}), 400

    required = ["trip", "api_payload", "current_itinerary", "customer_request"]
    missing_fields = [k for k in required if k not in body]
    if missing_fields:
        return jsonify({
            "error": f"campi mancanti nel body: {missing_fields} — 'trip' e 'api_payload' "
                     f"sono quelli restituiti da /v1/itinerary, da conservare (es. in Airtable, "
                     f"vedi airtable-data-moat-schema.md) e reinviati qui invariati"
        }), 400

    # [Stesso bug/fix di create_itinerary — vedi _preview_trip_error()]
    # Un body malformato dal cliente deve dare 400 PRIMA di controllare le
    # variabili d'ambiente del server, altrimenti un server non ancora
    # configurato maschera l'errore del cliente dietro un fuorviante 500.
    trip, api_payload, parse_error = _parse_trip_and_api_payload(body)
    if parse_error:
        error_body, status_code = parse_error
        return jsonify(error_body), status_code

    # Basta ANTHROPIC_API_KEY per l'affinamento — nessuna nuova chiamata
    # dati dal vivo, stesso principio dichiarato nel docstring di
    # refinement.py ("mai richieste nuove API dal vivo").
    missing_env = SETTINGS.missing_for_mock_mode()
    if missing_env:
        return jsonify({"error": f"variabili d'ambiente mancanti sul server: {missing_env}"}), 500

    payload = assemble_payload(trip, api_payload.hotels, api_payload.travel_times, api_payload.poi)

    try:
        result = refinement.refine_itinerary(
            current_itinerary=body["current_itinerary"],
            payload=payload,
            api_payload=api_payload,
            trip=trip,
            customer_request=body["customer_request"],
            api_key=SETTINGS.anthropic_api_key,
        )
    except refinement.RefinementError as e:
        return jsonify({"error": str(e)}), 502

    return jsonify({
        "itinerary": result.itinerary,
        "parse_error": result.parse_error,
        "validation": _serialize_validation_report(result.validation_report),
        "rendered_markdown": result.rendered_markdown,
    })


@app.route("/v1/pdf", methods=["POST"])
def generate_pdf():
    """
    [AGGIUNTO 2026-07-14 — preparativi Make.com, Nodo 10A] Prende un
    itinerario già generato (uscito invariato da /v1/itinerary o
    /v1/refine) e produce il PDF cliente finale — stessa identica logica
    già usata dal CLI con `--pdf` (guide turistiche per i POI
    EFFETTIVAMENTE usati, feedback post-viaggio, cartina, sezioni curate),
    fattorizzata in `src/pdf_extras.py` + `src/pdf_renderer.py` — mai
    duplicata qui (stesso principio anti-desync di
    `_parse_trip_and_api_payload()` sopra).

    Endpoint SEPARATO da /v1/itinerary (invece di un flag `pdf: true` in
    quella route) per due motivi: (1) /v1/itinerary resta leggero e non
    richiede `wkhtmltopdf` installato sul server per funzionare — solo chi
    vuole davvero un PDF paga il costo extra (guide+feedback sono
    chiamate Claude aggiuntive, una per POI usato più una per il
    feedback); (2) lo stesso endpoint serve anche per un itinerario
    uscito da /v1/refine, senza duplicare la generazione PDF in due punti
    diversi del wiring Make.com.

    Il PDF vero viene restituito come base64 dentro 'pdf_base64', non
    come corpo HTTP binario diretto: stesso contratto "sempre JSON" di
    ogni altra route di questo servizio (vedi _handle_unexpected_error) —
    un corpo a volte-JSON-a-volte-binario romperebbe il parsing lato
    Make.com anche solo per un errore, non solo per il caso di successo.
    """
    auth_error = _check_auth()
    if auth_error:
        return jsonify({"error": auth_error}), 401
    corpo, codice = _normalizza_esito(_esegui_pdf(request.get_json(silent=True)))
    return jsonify(corpo), codice


def _esegui_pdf(body):
    """Costruisce il fascicolo e ritorna `(dizionario, codice HTTP)`.

    [ESTRATTO 2026-08-10] Era il corpo di `generate_pdf()`, ed e' stato tirato
    fuori senza cambiare una virgola — stessa operazione, stesso motivo e
    stesso travestimento di `jsonify` gia' spiegati in `_esegui_itinerario()`.

    Serve perche' anche QUESTA fase ha superato il tetto dei 300 secondi del
    modulo HTTP di Make. La generazione dell'itinerario e' stata sistemata il
    10 agosto; la costruzione del fascicolo e' la fase piu' lenta delle due
    quando le guide vengono davvero generate — cinque chiamate al modello, le
    fotografie da scaricare, sei documenti da stampare e da cucire insieme.
    Aspettare di vederla morire in produzione, sapendo gia' che sarebbe morta,
    sarebbe stato un difetto scelto.
    """
    def jsonify(x):  # noqa: A001 — vedi il docstring di _esegui_itinerario
        return x

    if not isinstance(body, dict):
        return jsonify({"error": "body JSON mancante o non valido"}), 400

    required = ["trip", "api_payload", "itinerary"]
    missing_fields = [k for k in required if k not in body]
    if missing_fields:
        return jsonify({
            "error": f"campi mancanti nel body: {missing_fields} — 'trip', 'api_payload' e "
                     f"'itinerary' sono quelli restituiti (invariati) da /v1/itinerary o "
                     f"/v1/refine"
        }), 400

    itinerary = body["itinerary"]
    if not isinstance(itinerary, dict) or not isinstance(itinerary.get("days"), list):
        return jsonify({"error": "'itinerary' non ha la forma attesa (atteso un oggetto con "
                                  "una chiave 'days' che è una lista, come quello restituito "
                                  "da /v1/itinerary o /v1/refine)"}), 400

    # Stesso ordine di controlli di refine(): un body malformato dal
    # cliente deve dare 400 PRIMA di controllare le variabili d'ambiente
    # del server.
    trip, api_payload, parse_error = _parse_trip_and_api_payload(body)
    if parse_error:
        error_body, status_code = parse_error
        return jsonify(error_body), status_code

    include_guides = body.get("include_guides", True)
    include_feedback = body.get("include_feedback", True)
    include_map = body.get("include_map", True)
    # [AGGIUNTI 2026-07-31 — richieste di Lorenzo del 2026-07-31: cartine per
    # giornata numerate, "cartina e come arrivare", "stima dei costi e
    # dettaglio budget", Architect's Tips per direttrici + "piani b se piove",
    # menù e info dei ristoranti]
    #
    # DEFAULT `True`, deliberatamente: la richiesta esplicita era che il
    # prodotto finale rispetti tutto questo "in maniera standard, senza
    # ulteriori prompt". Lo scenario Make.com in produzione oggi NON conosce
    # questi nomi e non li invierà mai: se il default fosse `False`, ogni
    # nuova sezione esisterebbe nel codice e non arriverebbe a un solo
    # cliente pagante. I flag restano solo come valvola per spegnere una
    # sezione in caso di problema, senza dover ri-deployare.
    include_day_maps = body.get("include_day_maps", True)
    include_directions = body.get("include_directions", True)
    include_costs = body.get("include_costs", True)
    include_tips = body.get("include_tips", True)
    include_place_links = body.get("include_place_links", True)
    include_predeparture = body.get("include_predeparture", True)
    include_vademecum = body.get("include_vademecum", True)
    include_checklist_sheet = body.get("include_checklist_sheet", True)
    _flags = {
        "include_guides": include_guides, "include_feedback": include_feedback,
        "include_map": include_map, "include_day_maps": include_day_maps,
        "include_directions": include_directions, "include_costs": include_costs,
        "include_tips": include_tips, "include_place_links": include_place_links,
        "include_predeparture": include_predeparture,
        "include_vademecum": include_vademecum,
        "include_checklist_sheet": include_checklist_sheet,
    }
    _bad_flags = sorted(k for k, v in _flags.items() if not isinstance(v, bool))
    if _bad_flags:
        return jsonify({"error": f"i seguenti campi, se presenti, devono essere "
                                  f"booleani: {_bad_flags}"}), 400

    # [AGGIUNTO 2026-07-31] Numero di viaggiatori: serve SOLO alla stima dei
    # costi (`cost_estimator.estimate_costs`), perché il totale di un viaggio
    # per due non è quello di un viaggio per uno. Non è un campo di `Trip`
    # (non esiste nello schema) e non lo diventa qui: il form Tally oggi non
    # lo chiede, quindi il default 1 è anche il comportamento reale odierno.
    # Se un giorno il form lo chiederà, basta passarlo nel body.
    travellers = body.get("travellers", 1)
    if not isinstance(travellers, int) or isinstance(travellers, bool) or not 1 <= travellers <= 20:
        return jsonify({"error": "'travellers', se presente, deve essere un intero "
                                  "tra 1 e 20"}), 400

    # Guide e feedback richiedono una chiamata Claude ciascuna — servono
    # solo se almeno una delle due sezioni è richiesta. Un PDF "puro"
    # (entrambe a false) funziona anche senza ANTHROPIC_API_KEY, purché
    # wkhtmltopdf sia installato sul server (controllato più sotto da
    # render_pdf() stesso, che degrada con un errore leggibile — mai un
    # crash — se manca).
    #
    # [DECISO 2026-07-31, dopo che il primo tentativo ha rotto due test
    # esistenti] `include_tips` NON entra in questo controllo, pur essendo
    # anch'esso una chiamata Claude. Il motivo: quel flag vale `True` di
    # default, quindi metterlo qui trasformerebbe in un 500 ogni richiesta di
    # PDF "puro" fatta da un chiamante che non ha mai nemmeno sentito
    # nominare i consigli — cioè romperebbe un contratto già pubblicato per
    # colpa di un default nuovo. `build_pdf_sections()` salta i consigli
    # quando la chiave manca (`if include_tips and api_key`) e in quel caso
    # `render_html()` ristampa la lista base `itinerary["architect_tips"]`:
    # la sezione degrada, il documento esce comunque.
    if include_guides or include_feedback:
        missing_env = SETTINGS.missing_for_mock_mode()
        if missing_env:
            return jsonify({"error": f"variabili d'ambiente mancanti sul server: {missing_env}"}), 500

    # [AGGIUNTO 2026-08-01] Costo già sostenuto da /v1/itinerary per QUESTA
    # stessa vendita. Opzionale: se Make non lo passa, vale zero e il margine
    # mostrato è solo quello di questa fase — vedi Ledger.to_dict().
    carryover_eur = body.get("cost_carryover_eur", 0.0)

    with cost_telemetry.measure("pdf") as ledger:
        # [MODIFICATO 2026-08-03 — «risolvi il problema delle cartine che non
        # si vedono»] `include_map=False` qui NON significa "niente cartina
        # d'insieme": significa che non la fa piu' questa funzione. La fa
        # `build_pdf_sections()` due righe sotto, con la stessa macchina delle
        # cartine per giornata — quindi con la rete di sicurezza disegnata in
        # casa quando Google non risponde, e con la posizione dei pallini, che
        # serve per renderli cliccabili. Il flag che arriva da Make continua a
        # comandare la stessa cosa di prima: viene solo inoltrato all'altra
        # porta (`include_overview_map`). Se lo lasciassimo acceso in tutte e
        # due, Google verrebbe pagato due volte per la stessa figura e il
        # documento resterebbe piu' a lungo sotto il tetto dei 300 secondi.
        guides, feedback, used_pois, map_png_bytes = build_pdf_extras(
            itinerary, trip, api_payload, SETTINGS.anthropic_api_key,
            google_maps_key=SETTINGS.google_maps_key,
            include_guides=include_guides, include_feedback=include_feedback,
            include_map=False,
        )

        # Ogni sezione qui dentro è best-effort e indipendente dalle altre: una
        # chiave Google scaduta costa al cliente le cartine, non il documento.
        sections = build_pdf_sections(
            itinerary, trip, api_payload, SETTINGS.anthropic_api_key,
            google_maps_key=SETTINGS.google_maps_key, travellers=travellers,
            include_overview_map=include_map,
            include_day_maps=include_day_maps, include_directions=include_directions,
            include_costs=include_costs, include_tips=include_tips,
            include_place_links=include_place_links,
            include_predeparture=include_predeparture,
            include_vademecum=include_vademecum,
            include_checklist_sheet=include_checklist_sheet,
        )
        # [AGGIUNTO 2026-08-03 — task #178, richiesta di Lorenzo: «zoom out dal
        # macro al micro»] Qui ogni attrazione diventa un documento a se',
        # stampato e messo online, e il documento principale dimagrisce di
        # altrettanto. Va fatto ADESSO, prima di `split_render_kwargs()`, per
        # due motivi indipendenti: (a) scrive `sections["guide_urls"]`, che e'
        # una chiave del renderer e quindi deve esistere prima del filtro,
        # altrimenti nasce e viene buttata nella riga successiva; (b) prenota
        # il posto del documento principale (`itinerary_url`) PRIMA che il
        # documento principale esista — le guide devono poter stampare il
        # bottone "Torna all'itinerario" con dentro una URL che al momento
        # della stampa non punta ancora a niente. E' il motivo per cui piu'
        # sotto, appena il PDF esiste davvero, va salvato in quel posto: se
        # quella riga sparisce, tutti i bottoni di ritorno diventano 404 e
        # nessun test del renderer se ne accorge.
        # Se l'ospitalita' non e' configurata (PUBLIC_BASE_URL assente) la
        # funzione torna vuota, `guide_urls` resta {} e il prodotto e'
        # esattamente quello di ieri: un PDF solo, con le guide dentro.
        # [AGGIUNTO 2026-08-03 — task #181, richiesta di Lorenzo: «inserisci
        # alcune immagini con senso», «meno testo piu' immagini, non deve
        # essere noioso», e sua scelta esplicita "Foto vere ovunque + grafica
        # interna"] Le immagini si raccolgono UNA volta e servono a DUE
        # documenti: la fotografia vera va sia in apertura della giornata nel
        # documento principale sia in cima alla guida di quell'attrazione.
        # Scaricarle due volte significherebbe pagare due volte la stessa
        # foto.
        # Il tetto e' dentro `foto.raccogli_foto` (MAX_FOTO): la spesa di
        # questa riga non puo' crescere con la lunghezza del viaggio senza
        # che qualcuno lo decida.
        # [AGGIUNTO 2026-08-03 — task #189] `citta` non e' un dettaglio: su
        # Commons «Duomo» da solo restituisce il duomo sbagliato, «Duomo
        # Siena» quello giusto. Senza questa riga la fonte gratuita
        # troverebbe fotografie vere di posti veri che non sono il posto.
        immagini = foto.raccogli_foto(
            guides, used_pois, api_key=SETTINGS.google_maps_key,
            citta=getattr(trip, "destination", "") or "",
        )
        # [AGGIUNTO 2026-08-05 — task #190] Prima di tutto il resto: le
        # guide diventano capitoli staccati cuciti dentro questo stesso file.
        # Va PRIMA della pubblicazione perche' quella si fa da parte per le
        # guide gia' diventate capitoli — stamparle due volte costerebbe
        # mezzo secondo a guida su un'esecuzione che ha gia' sfiorato il tetto
        # dei 300 secondi.
        _fascicolo = prepara_fascicolo(
            guides, sections, itinerary=itinerary, trip=trip, poi=used_pois,
            photos=immagini,
        )
        if _fascicolo.get("capitoli"):
            app.logger.info(
                "fascicolo: %s guide cucite come capitoli dentro il PDF",
                _fascicolo["capitoli"],
            )
        pubblicazione = publish_hosted_guides(
            # [AGGIUNTO 2026-08-03 — task #180] `used_pois` sono gli stessi
            # POI che finiscono nel documento principale: passarli qui e' cio'
            # che permette alla guida della singola attrazione di stampare i
            # suoi orari veri.
            guides, sections, trip=trip, poi=used_pois,
            # Alle guide vanno TUTTE le immagini, grafica interna compresa:
            # una guida senza figura in cima e' una pagina di testo, ed e'
            # esattamente cio' che Lorenzo ha chiesto di non consegnare piu'.
            photos=immagini,
        )
        # [AGGIUNTO 2026-08-03 — task #184, richiesta di Lorenzo: «un pulsante
        # sul foglio di calcolo che ti fa ritornare al pdf originario»] Il
        # foglio della valigia si rifa' ADESSO, e non prima, perche' solo
        # adesso l'indirizzo del documento principale esiste: e' la
        # prenotazione appena fatta qui sopra. Senza ospitalita' configurata
        # `itinerary_url` e' None, la funzione non fa niente e il foglio resta
        # quello di prima — completo, solo senza la strada di ritorno.
        if aggiungi_ritorno_al_foglio_valigia(
            sections, pubblicazione.get("itinerary_url"),
            trip=trip, itinerary=itinerary, travellers=travellers,
        ):
            app.logger.info("foglio valigia: bottone di ritorno all'itinerario incluso")
        # [SPOSTATO 2026-08-03 — task #184] Il foglio della valigia si prende
        # QUI: dopo la riga che ci mette dentro il bottone di ritorno, e
        # ancora PRIMA di `split_render_kwargs()`, che filtra per lista bianca
        # e butterebbe l'allegato perche' non e' un argomento del renderer.
        # Prenderlo prima significava allegare alla mail la versione senza
        # bottone: lo stesso file, e proprio senza la cosa che era stata
        # chiesta.
        # [AGGIUNTO 2026-08-05 — task #192] Il foglio entra anche DENTRO il
        # PDF, come allegato vero. Qui e non prima: la riga qui sopra l'ha
        # appena rifatto per metterci il bottone di ritorno.
        if allega_foglio_valigia(sections):
            app.logger.info("fascicolo: foglio valigia allegato dentro il PDF")
        checklist_file = sections.get("checklist_xlsx") or {}
        # [CAMBIATO 2026-08-03, stesso giorno] Al renderer vanno TUTTE le
        # immagini, non piu' le sole fotografie vere. Non e' un
        # ripensamento sulla regola — in cima a una giornata continua a
        # comparire solo una fotografia vera — e' uno spostamento del
        # controllo: la selezione ora la fa il renderer, che e' l'unico posto
        # che sa in quale parte del documento sta stampando. Serve perche' il
        # capitolo interno delle guide (quello che resta quando la guida non
        # e' stata pubblicata come documento a se') deve poter mostrare anche
        # la copertina disegnata in casa, altrimenti proprio le guide di
        # riserva sarebbero le uniche pagine di solo testo.
        sections["photos"] = immagini
        # [AGGIUNTO 2026-08-01] `section_errors` NON va a `render_pdf()`: è la
        # diagnostica che il 2026-08-01 mancava del tutto. Finisce nei
        # contatori della risposta (quindi visibile in Make.com) e nei log.
        sections, section_errors = split_render_kwargs(sections)
        for _name, _detail in sorted(section_errors.items()):
            app.logger.warning("sezione PDF '%s' non generata: %s", _name, _detail)

        tmp_pdf_path = None
        try:
            tmp_pdf_fd, tmp_pdf_path = tempfile.mkstemp(suffix=".pdf")
            os.close(tmp_pdf_fd)
            # [AGGIUNTO 2026-08-13] Il resoconto della riparazione dei
            # collegamenti interni risale fino ai contatori qui sotto. Vedi
            # `render_pdf(resoconto_collegamenti=...)`.
            collegamenti = {}
            pdf_renderer.render_pdf(
                itinerary, trip.to_dict(), hotels=[h.to_dict() for h in api_payload.hotels],
                guides=guides, feedback=feedback, poi=used_pois,
                map_png_bytes=map_png_bytes, output_path=tmp_pdf_path,
                resoconto_collegamenti=collegamenti,
                **sections,
            )
            pdf_bytes = Path(tmp_pdf_path).read_bytes()
            # [AGGIUNTO 2026-08-03 — task #178] La meta' mancante della
            # prenotazione fatta sopra: le guide hanno gia' stampato dentro
            # di se' l'indirizzo di questo file, quindi il file deve
            # arrivarci. Fallire qui non deve pero' far fallire la vendita —
            # il cliente il PDF ce l'ha via email comunque — percio' e'
            # best-effort come ogni altra sezione, ma rumoroso nei log.
            if pubblicazione.get("consegna"):
                # `store()` non solleva: torna None. Quindi il controllo va
                # fatto sul valore, non con un try/except — un except qui
                # sembrerebbe una rete di sicurezza e non prenderebbe niente.
                if not hosting.store(
                    pubblicazione["consegna"], "itinerario", pdf_bytes
                ):
                    app.logger.warning(
                        "itinerario non pubblicato: i bottoni di ritorno "
                        "dentro le guide porteranno a una pagina inesistente "
                        "(consegna %s)", pubblicazione["consegna"],
                    )
        except pdf_renderer.PdfRendererError as e:
            # Stesso principio di missing_env sopra: un problema di
            # configurazione/dipendenza del SERVER (wkhtmltopdf assente,
            # subprocess fallito) è un 500, non un errore del cliente.
            # [AGGIUNTO 2026-08-01] È il fallimento peggiore di tutti: il
            # cliente ha pagato, l'itinerario è stato generato (costo già
            # speso) e il documento non esiste. Va saputo subito.
            alerting.notify(
                "pdf_render_error", str(e), context=alerting.safe_trip_context(trip)
            )
            return jsonify({"error": f"generazione PDF fallita sul server: {e}"}), 500
        finally:
            # Pulizia sempre eseguita, successo o fallimento — stesso
            # principio "mai lasciare file temporanei orfani" già seguito in
            # pdf_renderer.py per la scrittura atomica.
            if tmp_pdf_path and os.path.exists(tmp_pdf_path):
                os.remove(tmp_pdf_path)

    counters = {
        "guides_requested": len(used_pois) if include_guides else 0,
        "guides_generated": len(guides),
        "feedback_included": feedback is not None,
        # [CORRETTO 2026-08-03] Da oggi la cartina d'insieme arriva dalle
        # sezioni, non dai byte: leggere solo `map_png_bytes` avrebbe
        # riportato a Make "cartina assente" per ogni documento che la
        # contiene — un allarme falso ripetuto una volta per vendita e
        # quindi, dopo poco, un allarme che nessuno guarda piu'.
        "map_included": (
            map_png_bytes is not None
            or bool((sections.get("overview_map") or {}).get("png"))
        ),
        # [AGGIUNTI 2026-07-31] Contatori per sezione. Non sono decorativi:
        # ogni sezione degrada in silenzio (best-effort), quindi senza questi
        # campi un PDF a cui mancano tutte le cartine è indistinguibile da uno
        # completo, sia in Make.com sia guardando i log. Sono numeri/booleani,
        # non stringhe, così un filtro Make può alzare un allarme da solo.
        "day_maps_included": len(sections["day_maps"]),
        "directions_included": len(sections["directions"]),
        "costs_included": sections["cost_summary"] is not None,
        "tips_included": sections["tips"] is not None,
        "place_cards_included": len(sections["place_cards"]),
        # [AGGIUNTO 2026-08-01] Non un booleano ma il NUMERO di voci: la
        # sezione "Prima di partire" e' costruita solo da dati reali, quindi
        # una lista corta e' il sintomo di un payload povero (nessun hotel,
        # nessun museo, paese fuori tabella) — informazione che un booleano
        # "presente/assente" nasconderebbe.
        "predeparture_items": len((sections.get("predeparture") or {}).get("checklist") or []),
        # [AGGIUNTO 2026-08-01] Il PERCHÉ, non solo il quanto. `tips_included:
        # false` dice che manca; `section_errors: {"tips": "TipsGeneratorError:
        # troncato..."}` dice cosa riparare. È la differenza fra accorgersi di
        # un problema e poterlo risolvere senza riprodurlo.
        # [AGGIUNTO 2026-08-02 — task #173] Quante righe ha il foglio della
        # valigia allegato. Zero non e' un errore (una destinazione fuori
        # tabella climatica produce meno voci), ma e' il numero che dice se
        # l'allegato vale la pena di essere spedito — e Make puo' decidere da
        # solo se allegarlo, senza aprire il file.
        "checklist_rows": (sections.get("checklist_sheet") or {}).get("rows", 0),
        "checklist_filename": checklist_file.get("filename"),
        # [AGGIUNTI 2026-08-13] La navigazione interna del fascicolo, in
        # numeri. `collegamenti_interni` e' quanti pulsanti «Apri la guida» e
        # quante zone cliccabili sulle cartine sono diventati un salto vero.
        # Nel documento consegnato l'11 agosto erano ZERO su un fascicolo di
        # nove capitoli, e non se n'era accorto nessuno perche' il numero
        # esisteva solo nei log di Render.
        "capitoli_staccati": len(sections.get("capitoli_pdf") or []),
        # `None` quando la stampa non ha nemmeno riferito — cosi' la regola
        # qui sotto distingue «zero collegamenti» da «non lo so», che sono
        # due cose diverse e vanno trattate in modo diverso.
        "collegamenti_interni": (collegamenti or {}).get("riscritti"),
        "collegamenti_non_risolti": len((collegamenti or {}).get("non_risolte") or []),
        "section_errors": section_errors,
    }

    # [AGGIUNTO 2026-08-01] Il PDF esce comunque, ma se gli mancano delle
    # sezioni qualcuno deve accorgersene: degradare bene in silenzio è
    # esattamente il problema che questo allarme risolve. `notify_degraded_pdf`
    # legge gli STESSI contatori restituiti qui sotto — nessuna seconda logica
    # da tenere allineata — ed è inerte se ALERT_WEBHOOK_URL non è impostata.
    alerting.notify_degraded_pdf(counters, alerting.safe_trip_context(trip))

    # [AGGIUNTO 2026-08-01] Il codice opaco della consegna, restituito perché
    # Make possa archiviarlo accanto al viaggio (Airtable, vedi
    # airtable-data-moat-schema.md): è la chiave che ricollega una risposta
    # del modulo al viaggio giusto, senza che il cliente debba ricordarsi
    # niente e senza mettere la sua email in una URL.
    _feedback_link = sections.get("feedback_link") or {}

    risposta = {
        "pdf_base64": base64.b64encode(pdf_bytes).decode("ascii"),
        # Il foglio della valigia, nello stesso formato del PDF, cosi' che
        # Make lo alleghi alla STESSA mail senza una seconda chiamata. Assente
        # (`None`) quando non c'e' niente da spuntare: meglio nessun allegato
        # di un foglio vuoto.
        "checklist_xlsx_base64": (
            base64.b64encode(checklist_file["content"]).decode("ascii")
            if checklist_file.get("content") else None
        ),
        **counters,
        "feedback_ref": _feedback_link.get("ref"),
        "feedback_url": _feedback_link.get("url"),
        # [AGGIUNTO 2026-08-01] Costo reale di QUESTA fase più, se passato,
        # quello dell'itinerario: è il numero che dice se 4,90 € sono un
        # prezzo o una perdita. Vedi src/cost_telemetry.py.
        "cost_estimate": ledger.to_dict(carryover_eur=carryover_eur),
    }

    # [AGGIUNTO 2026-08-10 — da un guasto vero, arrivato fino al cliente.]
    #
    # Il 10 agosto il credito del modello si e' esaurito a meta' lavoro. Il
    # servizio ha risposto **200 OK**, Make ha spedito la mail, e il cliente
    # ha ricevuto un documento a cui mancavano tutte e cinque le guide dei
    # luoghi — cioe' la meta' di quello che aveva comprato. Nessun errore da
    # nessuna parte: ne' nei log, ne' nella risposta, ne' nella casella di
    # Lorenzo. Se ne e' accorto qualcuno solo perche' stava guardando.
    #
    # E' la forma di tutti i guasti seri di questo progetto: **degradano
    # invece di rompersi**. Un errore rumoroso costa un pomeriggio; uno
    # silenzioso costa un cliente, e non si sa nemmeno quale.
    #
    # Qui la consegna si ferma. Il lavoro NON viene buttato — il documento
    # resta dentro la risposta, cosi' com'e' — ma il codice e' un errore, e
    # un errore Make non lo spedisce: si ferma, e manda una mail a Lorenzo.
    motivo = _fascicolo_troppo_incompleto(counters)
    if motivo:
        alerting.notify("fascicolo_incompleto", motivo,
                        context=alerting.safe_trip_context(trip))
        risposta["error"] = motivo
        return jsonify(risposta), _CODICE_ERRORE_LEGGIBILE

    return jsonify(risposta)


def _fascicolo_troppo_incompleto(counters) -> str:
    """La frase che spiega perche' questo documento non si vende. Vuota se si vende.

    Una regola sola, e deliberatamente sola: **tutte** le guide chieste
    mancano. Non «qualcuna manca» — un luogo su nove senza scheda e' un
    documento un po' piu' magro, e fermare la consegna per quello vorrebbe
    dire non consegnare mai. Zero su cinque invece non e' un documento
    magro: e' un altro prodotto.
    """
    # [AGGIUNTO 2026-08-13] La navigazione interna morta.
    #
    # Un fascicolo con i capitoli staccati e nessun collegamento che ci porti
    # non e' un documento un po' meno comodo: e' un documento in cui meta'
    # del contenuto e' irraggiungibile a meno di scorrere ventotto pagine a
    # mano. E' successo davvero l'11 agosto — nove capitoli, zero salti — ed
    # e' arrivato al cliente perche' l'unico posto dove il numero compariva
    # erano i log di Render.
    capitoli = counters.get("capitoli_staccati") or 0
    salti = counters.get("collegamenti_interni")
    if capitoli > 0 and salti is not None and salti <= 0:
        return ("il documento ha " + str(capitoli) + " capitoli staccati e "
                "NESSUN collegamento interno che ci porti: chi legge non ha "
                "modo di arrivarci se non scorrendo il documento a mano")

    chieste = counters.get("guides_requested") or 0
    fatte = counters.get("guides_generated") or 0
    if chieste <= 0 or fatte > 0:
        return ""
    errori = counters.get("section_errors") or {}
    perche = "; ".join(f"{nome}: {dettaglio}"
                       for nome, dettaglio in sorted(errori.items()))
    quante = ("l'unica guida del luogo non e' stata generata"
              if chieste == 1
              else f"nessuna delle {chieste} guide dei luoghi e' stata generata")
    return (f"{quante}: il documento non contiene la parte per cui il cliente "
            f"ha pagato, e non va spedito cosi'"
            + (f" — {perche}" if perche else ""))


# ---------------------------------------------------------------------------
# I documenti ospitati
# ---------------------------------------------------------------------------
# [AGGIUNTO 2026-08-03 — richiesta di Lorenzo: "migliorare la guida turistica
# linkando un pdf per attrazione da te generato ad hoc ... con bottone di
# torna all'itinerario alla parte giusta", e sua scelta esplicita fra le
# alternative proposte: "PDF separati, ospitati su Render"]
#
# ATTENZIONE, la cosa più importante di questo blocco: la rotta di lettura
# NON chiama `_check_auth()`, e non è una dimenticanza. A cliccare quel link
# è il cliente dal PDF che ha in mano, non Make: se richiedesse
# `X-Service-Key` non si aprirebbe mai, e l'unico modo di farla funzionare
# sarebbe mettere la chiave del servizio dentro un documento che gira per
# posta. La credenziale è il token dentro la URL, generato da
# `src/hosting.py` con 256 bit di casualità e confrontato in tempo costante.
#
# In questo file l'autenticazione è per-rotta (`_check_auth()` chiamata
# dentro ogni handler) e non un `before_request`: significa che una rotta
# nuova nasce PUBBLICA. È il motivo per cui la rotta di manutenzione qui
# sotto ha il suo controllo esplicito, e per cui esistono due test dedicati
# — uno per verso — in tests/test_hosting_2026_08_03.py.

@app.route("/f/<consegna>/<token>/<nome>", methods=["GET"])
def serve_documento_ospitato(consegna, token, nome):
    esito = hosting.resolve(consegna, token, nome)
    if esito is None:
        # Un 404 asciutto e IDENTICO in ogni caso di fallimento: consegna
        # inesistente, token sbagliato, documento scaduto o nome malformato
        # devono essere indistinguibili, altrimenti il servizio risponde
        # alla domanda "questo codice è mai esistito?" a chiunque la faccia.
        return jsonify({"error": "non trovato"}), 404
    blob, content_type = esito
    risposta = make_response(blob)
    risposta.headers["Content-Type"] = content_type
    risposta.headers["Content-Disposition"] = "inline"
    # Fuori dai motori di ricerca: una URL a capacità che finisce indicizzata
    # non è più una URL a capacità. Nessun crawler dovrebbe mai vedere questi
    # link (stanno solo dentro PDF privati), ma la riga costa niente e il
    # giorno in cui uno di questi indirizzi finisce incollato in un forum è
    # l'unica cosa che impedisce che diventi pubblico per sempre.
    risposta.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    risposta.headers["Cache-Control"] = "private, max-age=3600"
    risposta.headers["X-Content-Type-Options"] = "nosniff"
    return risposta


def _stato_configurazione() -> list[dict]:
    """Lo stato di ogni pezzo OPZIONALE del prodotto, in italiano.

    [AGGIUNTO 2026-08-03 — task #185, segnalazione di Lorenzo: «il link di
    tally non funziona ancora»]

    Perche' questa funzione esiste. Il collegamento al modulo di recensione
    era rotto in produzione per un motivo banale: la variabile non era
    impostata. Il codice era giusto, i controlli erano verdi, il documento
    usciva — semplicemente senza quel pezzo. E non c'era nessun modo di
    accorgersene se non generando un itinerario vero, cioe' spendendo un euro
    e mezzo e aspettando quattro minuti.

    E' la forma di difetto che questo progetto produce di piu', perche' ogni
    sezione e' best-effort per scelta: un pezzo che manca non fa rumore, il
    documento esce lo stesso, e nessuno se ne accorge fino al reclamo. Ci
    sono SEI variabili opzionali, quindi sei modi di consegnare in silenzio un
    prodotto piu' povero di quello che si crede di aver messo online.

    Questa risposta li rende visibili tutti insieme, senza spendere niente.
    Ogni voce dice tre cose e non una: com'e' messa, cosa perde IL CLIENTE se
    manca, e cosa si fa per sistemarla. "false" da solo non aiuta chi legge:
    Lorenzo non e' uno sviluppatore e la variabile la deve digitare lui.

    I VALORI non escono mai da qui — solo se ci sono e se sono utilizzabili.
    Meta' di queste variabili sono segreti (`FEEDBACK_REF_SECRET` deriva i
    codici delle recensioni, `ALERT_WEBHOOK_URL` e' a sua volta una
    credenziale), e una rotta che restituisce il proprio segreto e' una rotta
    che lo regala al primo log condiviso per sbaglio.
    """
    def _presente(nome: str) -> bool:
        return bool((os.getenv(nome) or "").strip())

    modulo_recensione = feedback_link.form_url()
    modulo_grezzo = (os.getenv("FEEDBACK_FORM_URL") or "").strip()

    return [
        {
            "voce": "modulo di recensione (Tally)",
            "variabili": ["FEEDBACK_FORM_URL"],
            "attivo": bool(modulo_recensione),
            # Il caso peggiore e il motivo per cui non basta un booleano: la
            # variabile c'e' ma il valore non puo' funzionare (segnaposto mai
            # sostituito, `http://`, indirizzo senza schema). Un "manca" e un
            # "c'e' ma e' sbagliato" si sistemano in due modi diversi, e chi
            # ha appena incollato qualcosa nel pannello di Render ha bisogno
            # di sapere quale dei due gli e' capitato.
            "stato": (
                "attivo" if modulo_recensione
                else "valore presente ma NON utilizzabile" if modulo_grezzo
                else "non configurato"
            ),
            "senza_questo": "il capitolo delle recensioni non esce: nessuna "
                            "risposta torna indietro, e l'unico segnale sulla "
                            "qualita' resta l'assenza di rimborsi chiesti",
            "come_si_sistema": "incolla su Render la URL https:// del modulo "
                               "Tally vero (non quella di esempio)",
        },
        {
            "voce": "codice stabile delle recensioni",
            "variabili": ["FEEDBACK_REF_SECRET"],
            "attivo": _presente("FEEDBACK_REF_SECRET"),
            "senza_questo": "le risposte arrivano lo stesso, ma rigenerare un "
                            "PDF cambia il codice e si perde il collegamento "
                            "con il viaggio",
            "come_si_sistema": "una frase lunga a caso, scritta una volta sola "
                               "e mai piu' cambiata",
        },
        {
            "voce": "documenti ospitati (guide per attrazione)",
            # DUE variabili, non una: l'indirizzo pubblico da stampare nei
            # documenti e la cartella su disco dove i file vengono scritti.
            # Impostarne una sola non accende niente, e finche' questa riga
            # ne nominava una sola la diagnostica avrebbe mandato a cercare
            # il guasto nel posto sbagliato — lo stesso difetto che sta
            # riparando.
            "variabili": ["PUBLIC_BASE_URL", "PUBLIC_FILES_DIR"],
            "attivo": hosting.is_configured(),
            "senza_questo": "le guide per attrazione e il bottone di ritorno "
                            "sul foglio della valigia non compaiono: resta "
                            "solo il documento principale",
            "come_si_sistema": "PUBLIC_BASE_URL e' l'indirizzo pubblico del "
                               "servizio (https://, senza barra finale); "
                               "PUBLIC_FILES_DIR e' il percorso del disco "
                               "montato su Render. Servono tutte e due",
        },
        {
            "voce": "allarme sui fallimenti",
            "variabili": ["ALERT_WEBHOOK_URL"],
            "attivo": _presente("ALERT_WEBHOOK_URL"),
            "senza_questo": "un documento consegnato con pezzi mancanti resta "
                            "solo nei log: lo scopre il cliente, non noi",
            "come_si_sistema": "un webhook che accetta un POST JSON (Slack, "
                               "oppure un modulo 'Custom webhook' di Make)",
        },
        {
            "voce": "foglio della valigia su Fogli Google",
            "variabili": ["CHECKLIST_SHEET_TEMPLATE_URL"],
            "attivo": _presente("CHECKLIST_SHEET_TEMPLATE_URL"),
            "senza_questo": "il foglio arriva solo come allegato .xlsx: si "
                            "apre, ma non si spunta dal telefono in due tocchi",
            "come_si_sistema": "la URL di un foglio Google in sola lettura, "
                               "che il cliente si copia",
        },
        {
            "voce": "cartine stradali e fotografie vere",
            "variabili": ["GOOGLE_MAPS_KEY"],
            "attivo": _presente("GOOGLE_MAPS_KEY"),
            "senza_questo": "cartine schematiche disegnate in casa e copertine "
                            "illustrate al posto delle fotografie: la rete di "
                            "sicurezza, non il risultato normale",
            "come_si_sistema": "la chiave Google, che resta solo su Render",
        },
    ]


@app.route("/v1/diagnostica", methods=["GET"])
def diagnostica():
    """Cosa e' acceso e cosa no, senza generare (e pagare) un itinerario.

    [AGGIUNTO 2026-08-03 — task #185] Autenticata come tutto il resto: dice
    quali pezzi del prodotto sono configurati, ed e' esattamente la mappa che
    servirebbe a un estraneo per sapere dove il servizio e' scoperto. Il
    controllo va DENTRO la funzione — in questo file l'autenticazione non e'
    globale, quindi una rotta nuova nasce pubblica.
    """
    auth_error = _check_auth()
    if auth_error:
        return jsonify({"error": auth_error}), 401
    voci = _stato_configurazione()
    # Di un pezzo spento si elencano le variabili che MANCANO davvero, non
    # tutte quelle che gli servono: chi ha gia' messo `PUBLIC_BASE_URL` e ha
    # dimenticato `PUBLIC_FILES_DIR` deve leggere il nome che gli manca, non
    # rimettere anche quello che c'e' gia'.
    mancanti = [
        nome
        for v in voci if not v["attivo"]
        for nome in v["variabili"]
        if not (os.getenv(nome) or "").strip()
    ]
    # I due elenchi NON sono nella stessa unita' di misura: `voci` conta
    # PEZZI del prodotto, `mancanti` conta VARIABILI, e un pezzo solo puo'
    # averne piu' di una (l'ospitalita' ne vuole due). Sottrarre l'uno
    # dall'altro dava numeri impossibili — con niente configurato usciva
    # "-1/6" — cioe' proprio il tipo di riga che fa perdere fiducia a una
    # diagnosi nel momento in cui la si sta leggendo per capire un guasto.
    # Gli accesi si contano sugli accesi.
    attivi = sum(1 for v in voci if v["attivo"])
    return jsonify({
        "status": "ok",
        "test_suite": TEST_SUITE_STATUS,
        # Il numero prima dell'elenco: e' la riga che si legge davvero.
        "pezzi_attivi": f"{attivi}/{len(voci)}",
        "variabili_mancanti": mancanti,
        "dettaglio": voci,
    })


@app.route("/v1/diagnostica/immagini", methods=["GET"])
def diagnostica_delle_immagini():
    """Le cartine e le fotografie vere funzionano davvero? Quattro centesimi.

    [AGGIUNTO 2026-08-03 (ter) — task #188] `/v1/diagnostica` dice se la
    chiave c'e'. Questa dice se la chiave FUNZIONA, che e' una domanda
    diversa e l'unica che conti: una chiave valida non produce nessuna
    cartina se la API non e' abilitata sul progetto, o se la chiave ha una
    restrizione che la esclude, o se manca la fatturazione. Tutti e tre danno
    lo stesso identico sintomo — la cartina disegnata in casa al posto di
    quella vera — e nessuno dei tre si vede senza chiamare l'API.

    Prima di questa rotta l'unico modo di distinguerli era generare un
    itinerario vero: ~1,50 € e quattro minuti, per scoprire alla fine di
    avere in mano un disegno.

    `?solo=cartina` salta la prova delle fotografie, che costa quindici volte
    tanto: chi sta sistemando le cartine la ricontrolla dieci volte di fila e
    non c'e' motivo di fargliela pagare ogni volta.

    L'autenticazione va DENTRO la funzione: qui non e' globale, quindi una
    rotta nuova nasce pubblica — e una rotta pubblica che spende soldi veri a
    ogni chiamata e' un rubinetto aperto sulla strada.
    """
    auth_error = _check_auth()
    if auth_error:
        return jsonify({"error": auth_error}), 401
    esito = diagnostica_immagini.esegui(
        os.getenv("GOOGLE_MAPS_KEY"),
        solo=request.args.get("solo"),
    )
    if "errore" in esito:
        return jsonify(esito), 400
    return jsonify(esito)


@app.route("/v1/manutenzione/pulizia", methods=["POST"])
def pulizia_documenti_ospitati():
    auth_error = _check_auth()
    if auth_error:
        return jsonify({"error": auth_error}), 401
    return jsonify({
        "configurato": hosting.is_configured(),
        "consegne_cancellate": hosting.sweep(),
        "retention_giorni": hosting.retention_days(),
    })


if __name__ == "__main__":
    # Solo per test/debug locale (Flask dev server — non è WSGI di
    # produzione). Su Render.com, il Procfile/render.yaml lancia
    # `gunicorn service:app` invece — vedi DEPLOY.md.
    port = int(os.getenv("PORT", "5000"))
    debug = os.getenv("FLASK_DEBUG", "").lower() in ("1", "true", "yes")
    app.run(host="0.0.0.0", port=port, debug=debug)
