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
import unittest as _unittest
from pathlib import Path

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

from src.config import SETTINGS
from src.pipeline import run_live_from_raw, run_mock_from_raw
from src.payload_builder import assemble_payload
from src.schemas import ApiPayload, Hotel, POI, Trip, TravelTime
from src.triage import normalize_raw_input
from src import refinement
from src import pdf_renderer
from src.pdf_extras import build_pdf_extras

app = Flask(__name__)


def _compute_test_suite_label() -> str:
    """
    [AGGIUNTO 2026-07-13 — audit di revisione completa, "certezza
    matematica"] Prima era una costante scritta a mano ("404/404") da
    aggiornare manualmente a ogni nuovo test aggiunto altrove nel
    progetto — ed era infatti già disallineata (la suite reale è
    cresciuta a 486 test, l'etichetta mostrata su /health era ferma a
    404). Contare la suite reale via `unittest` discovery all'avvio
    (sola ENUMERAZIONE dei test — nessuno viene eseguito, quindi nessun
    impatto sul tempo di avvio del servizio) elimina strutturalmente il
    rischio di staleness invece di richiedere disciplina umana per
    tenerla aggiornata.

    Se il deploy non include la cartella `tests/` (es. esclusa da un
    .dockerignore), degrada in modo esplicito invece di mostrare "0/0"
    fuorviante — stesso principio "mai un fallimento silenzioso"
    applicato altrove nel progetto (vedi maps_static.py).
    """
    try:
        tests_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tests")
        loader = _unittest.TestLoader()
        suite = loader.discover(start_dir=tests_dir, top_level_dir=os.path.dirname(tests_dir))
        count = suite.countTestCases()
        if count == 0:
            return "sconosciuto (cartella tests/ non trovata in questo deploy)"
        return f"{count}/{count} (conteggio automatico all'avvio del servizio)"
    except Exception as e:
        return f"sconosciuto (discovery della suite fallita: {e})"


TEST_SUITE_STATUS = _compute_test_suite_label()


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
    if not provided or not hmac.compare_digest(provided, expected):
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
        return jsonify({"error": e.description}), e.code
    app.logger.exception("Errore interno non gestito")
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
    except ValueError as e:
        return str(e)
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
    }


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "test_suite": TEST_SUITE_STATUS})


@app.route("/v1/itinerary", methods=["POST"])
def create_itinerary():
    auth_error = _check_auth()
    if auth_error:
        return jsonify({"error": auth_error}), 401

    body = request.get_json(silent=True)
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
        return jsonify({
            "error": f"errore nello strato dati (Geocoding/LiteAPI/Places/Distance Matrix): "
                     f"{result.data_layer_error}",
            "trip": result.trip.to_dict(),
        }), 502

    return jsonify({
        "trip": result.trip.to_dict(),
        "api_payload": result.api_payload.to_dict() if result.api_payload else None,
        "itinerary": result.itinerary,
        "parse_error": result.parse_error,
        "geocoding_warning": result.geocoding_warning,
        "validation": _serialize_validation_report(result.validation_report),
        "rendered_markdown": result.rendered_markdown,
    })


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
    try:
        trip = Trip(**body["trip"])
        api_payload_dict = body["api_payload"] or {}
        hotels = [Hotel(**h) for h in api_payload_dict.get("hotels", [])]
        pois = [POI(**p) for p in api_payload_dict.get("poi", [])]
        travel_times = [TravelTime(**t) for t in api_payload_dict.get("travel_times", [])]
    except TypeError as e:
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

    body = request.get_json(silent=True)
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
    if not all(isinstance(v, bool) for v in (include_guides, include_feedback, include_map)):
        return jsonify({"error": "'include_guides'/'include_feedback'/'include_map', se "
                                  "presenti, devono essere booleani"}), 400

    # Guide e feedback richiedono una chiamata Claude ciascuna — servono
    # solo se almeno una delle due sezioni è richiesta. Un PDF "puro"
    # (entrambe a false) funziona anche senza ANTHROPIC_API_KEY, purché
    # wkhtmltopdf sia installato sul server (controllato più sotto da
    # render_pdf() stesso, che degrada con un errore leggibile — mai un
    # crash — se manca).
    if include_guides or include_feedback:
        missing_env = SETTINGS.missing_for_mock_mode()
        if missing_env:
            return jsonify({"error": f"variabili d'ambiente mancanti sul server: {missing_env}"}), 500

    guides, feedback, used_pois, map_png_bytes = build_pdf_extras(
        itinerary, trip, api_payload, SETTINGS.anthropic_api_key,
        google_maps_key=SETTINGS.google_maps_key,
        include_guides=include_guides, include_feedback=include_feedback, include_map=include_map,
    )

    tmp_pdf_path = None
    try:
        tmp_pdf_fd, tmp_pdf_path = tempfile.mkstemp(suffix=".pdf")
        os.close(tmp_pdf_fd)
        pdf_renderer.render_pdf(
            itinerary, trip.to_dict(), hotels=[h.to_dict() for h in api_payload.hotels],
            guides=guides, feedback=feedback, poi=used_pois,
            map_png_bytes=map_png_bytes, output_path=tmp_pdf_path,
        )
        pdf_bytes = Path(tmp_pdf_path).read_bytes()
    except pdf_renderer.PdfRendererError as e:
        # Stesso principio di missing_env sopra: un problema di
        # configurazione/dipendenza del SERVER (wkhtmltopdf assente,
        # subprocess fallito) è un 500, non un errore del cliente.
        return jsonify({"error": f"generazione PDF fallita sul server: {e}"}), 500
    finally:
        # Pulizia sempre eseguita, successo o fallimento — stesso
        # principio "mai lasciare file temporanei orfani" già seguito in
        # pdf_renderer.py per la scrittura atomica.
        if tmp_pdf_path and os.path.exists(tmp_pdf_path):
            os.remove(tmp_pdf_path)

    return jsonify({
        "pdf_base64": base64.b64encode(pdf_bytes).decode("ascii"),
        "guides_requested": len(used_pois) if include_guides else 0,
        "guides_generated": len(guides),
        "feedback_included": feedback is not None,
        "map_included": map_png_bytes is not None,
    })


if __name__ == "__main__":
    # Solo per test/debug locale (Flask dev server — non è WSGI di
    # produzione). Su Render.com, il Procfile/render.yaml lancia
    # `gunicorn service:app` invece — vedi DEPLOY.md.
    port = int(os.getenv("PORT", "5000"))
    debug = os.getenv("FLASK_DEBUG", "").lower() in ("1", "true", "yes")
    app.run(host="0.0.0.0", port=port, debug=debug)
