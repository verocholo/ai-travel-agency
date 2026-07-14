"""
Orchestratore end-to-end — equivalente allo scenario Make.com completo
(BLUEPRINT_MAKE.md), Nodi 1→10A. Due modalità:

  mock  — usa RAG data pre-costruiti (src/mock_rag_data.py), chiama Claude
          davvero. Utile per validare il system prompt senza spendere in
          Google/Amadeus e senza dipendere dalla loro disponibilità.
  live  — pipeline completa con chiamate reali a Geocoding, LiteAPI, Places,
          Distance Matrix, poi Claude. Richiede tutte e 3 le chiavi.
          [AGGIORNATO 2026-07-10: era Amadeus (4 chiavi) — vedi CHANGELOG.md]
"""
from __future__ import annotations
import json
from dataclasses import dataclass

import requests

from .schemas import Trip
from .triage import normalize_raw_input
from . import geocoding, liteapi_client, places_client, distance_matrix, temporal_filter, modules
from .payload_builder import assemble_payload
from .claude_engine import call_claude, ClaudeEngineError
from .validator import parse_claude_output, validate_itinerary, strip_reasoning, ParseError
from .renderer import render_markdown
from .mock_rag_data import get_mock_payload
from .schemas import ApiPayload


@dataclass
class PipelineResult:
    trip: Trip
    payload: dict
    raw_claude_output: str
    itinerary: dict | None
    parse_error: str | None
    validation_report: object | None
    rendered_markdown: str | None
    # [AGGIUNTI 2026-07-11 — audit qualità pre-lancio] Due campi opzionali
    # (default None: nessuna rottura per run_mock() o per codice esistente
    # che costruisce PipelineResult senza di essi):
    # - data_layer_error: un fallimento nei Nodi 2b-4 (Geocoding/LiteAPI/
    #   Places/Distance Matrix) di run_live() prima ERA un traceback Python
    #   non gestito — vedi il try/except aggiunto sotto. Distinto da
    #   parse_error (che riguarda solo l'output di Claude) per non
    #   confondere le due cause molto diverse di fallimento.
    # - geocoding_warning: espone is_imprecise_match() (già scritto per il
    #   bug "Val d'Orcia" di Fase 3, ma mai collegato a run_live() finora —
    #   solo agli script debug_*.py) al chiamante reale della pipeline,
    #   invece di lasciare che un match impreciso passi silenzioso.
    data_layer_error: str | None = None
    geocoding_warning: str | None = None
    # [AGGIUNTO 2026-07-12 — bug reale trovato ED ESEGUITO da Lorenzo dal
    # vivo] `--check-freshness --mode live` produceva silenziosamente lo
    # STESSO identico output di `--check-freshness` in mock mode — vedi la
    # nota estesa in main.py:_run_freshness_check(). Causa: PipelineResult
    # non esponeva mai l'ApiPayload (hotel/POI con ID/coordinate REALI)
    # costruito da run_live(), quindi il chiamante non aveva altra scelta
    # che richiamare sempre get_mock_payload(). Esposto qui così i
    # chiamanti (come --check-freshness) possono riusare i dati reali
    # invece di ricostruirli.
    api_payload: object | None = None


def run_mock(fixture_trip_path: str, scenario_key: str, api_key: str) -> PipelineResult:
    with open(fixture_trip_path, encoding="utf-8") as f:
        raw = json.load(f)
    return run_mock_from_raw(raw, scenario_key, api_key)


def run_mock_from_raw(raw: dict, scenario_key: str, api_key: str) -> PipelineResult:
    """
    [AGGIUNTO 2026-07-12 — microservizio HTTP per Make.com, scelta di
    Lorenzo: "Wrappo la pipeline Python esistente (consigliato)"]
    Stessa identica logica di `run_mock()`, ma parte da un dict Python già
    in memoria invece che da un path su disco — è quello che serve a un
    servizio web (il body JSON della richiesta HTTP è già un dict, non ha
    senso scriverlo su un file temporaneo solo per poterlo rileggere).
    `run_mock()` sopra ora è un wrapper sottile che legge il file e
    delega qui: nessuna logica duplicata, nessun rischio di disallineamento
    fra le due strade (stesso principio "anti-desync" già applicato altrove
    in questo progetto, es. scenario_checks.py -> validator.py).
    """
    trip = normalize_raw_input(raw)
    trip_errors = trip.validate()
    if trip_errors:
        raise ValueError(f"Trip non valido: {trip_errors}")

    api_payload: ApiPayload = get_mock_payload(scenario_key)
    payload = assemble_payload(trip, api_payload.hotels, api_payload.travel_times, api_payload.poi)

    return _call_claude_and_validate(trip, payload, api_payload, api_key)


def run_live(fixture_trip_path: str, settings) -> PipelineResult:
    with open(fixture_trip_path, encoding="utf-8") as f:
        raw = json.load(f)
    return run_live_from_raw(raw, settings)


def run_live_from_raw(raw: dict, settings) -> PipelineResult:
    """Equivalente dict-based di `run_live()` — vedi il docstring di
    `run_mock_from_raw()` sopra per il motivo. `run_live()` è ora un
    wrapper sottile che legge il file e delega qui."""
    trip = normalize_raw_input(raw)
    trip_errors = trip.validate()
    if trip_errors:
        raise ValueError(f"Trip non valido: {trip_errors}")

    # [AGGIUNTO 2026-07-11 — audit qualità pre-lancio] Prima, un fallimento
    # in QUALSIASI chiamata reale qui sotto (Geocoding/LiteAPI/Places/
    # Distance Matrix — tutte documentate come possibili "Chaos Engineering"
    # nei rispettivi moduli: GeocodingError su ZERO_RESULTS, HTTPError su
    # un 4xx/5xx, LiteApiError su schema-prezzo non riconosciuto, RuntimeError
    # su status!=OK della Distance Matrix) propagava come traceback Python
    # grezzo fino al chiamante — un'asimmetria reale con _call_claude_and_validate
    # sotto, che già gestisce con grazia il fallimento del Nodo 8 (Claude).
    # Corretto racchiudendo l'intero Nodo 2b-4 in un try/except esplicito:
    # un fallimento qui produce comunque un PipelineResult leggibile
    # (data_layer_error), non un crash del CLI.
    try:
        # Nodo 2b — Geocoding
        # [AGGIORNATO 2026-07-11] geocode_full() invece di geocode(): la
        # protezione is_imprecise_match() (scritta apposta dopo il bug
        # "Val d'Orcia, Toscana" di Fase 3 — un match con status="OK" ma
        # 60-70km dal luogo reale) era finora collegata solo agli script
        # debug_*.py, mai alla pipeline che serve davvero i clienti.
        geo = geocoding.geocode_full(trip.destination, settings.google_maps_key)
        lat, lng = geo["lat"], geo["lng"]
        trip.dest_lat, trip.dest_lng = lat, lng
        geocoding_warning = None
        if geocoding.is_imprecise_match(geo["location_type"]):
            geocoding_warning = (
                f"Geocoding impreciso per '{trip.destination}' (location_type="
                f"{geo['location_type']!r}, indirizzo risolto: {geo['formatted_address']!r}) — "
                f"nessun punto univoco trovato (nome di area/regione/valle senza centro "
                f"preciso, stesso tipo di bug che ha causato l'errore Val d'Orcia in Fase 3). "
                f"Le coordinate sono comunque usate per la ricerca radiale, ma potrebbero "
                f"non rappresentare bene il luogo reale del cliente."
            )

        # Nodo 3 — LiteAPI anchor hotel [AGGIORNATO 2026-07-10, era Amadeus — vedi CHANGELOG.md]
        liteapi = liteapi_client.LiteApiClient(settings.liteapi_key)
        hotels_geo = liteapi.search_hotels_by_geocode(lat, lng)
        hotel_ids = [h["id"] for h in hotels_geo]
        offers = liteapi.search_hotel_offers(
            hotel_ids, trip.date_start, trip.date_end,
            budget_eur=trip.budget_eur if trip.budget_mode == "LIMITED" else None,
        )
        hotels = liteapi_client.select_anchor_hotel(hotels_geo, offers, lat, lng, trip.duration_days)

        # Nodo 5 — Places
        # [CORRETTO 2026-07-11] BUG CRITICO: qui c'era
        # modules.get_module(modules.DEFAULT_MODULE_ID) hardcoded, cioè SEMPRE
        # "sport_active_travel" indipendentemente dal tipo di cliente reale —
        # vedi il commento esteso in src/modules.py sopra
        # OBJECTIVE_FUNCTION_TO_MODULE per i dettagli completi di come è stato
        # trovato (mai coperto da test, invisibile in --mode mock) e perché la
        # mappa esplicita per objective_function è la correzione giusta.
        active_module = modules.get_module_for_objective_function(trip.objective_function)
        pois_raw = places_client.search_nearby(
            lat, lng, settings.google_maps_key,
            included_types=active_module.included_place_types,
        )

        # Nodo 6 — Filtro temporale
        travel_days = temporal_filter.compute_travel_days(trip.date_start, trip.duration_days)
        pois = temporal_filter.filter_open_pois(pois_raw, travel_days)

        # Nodo 4 — Distance Matrix (dopo il filtro, come da hard-cap del Nodo 4.0)
        # [AGGIORNATO 2026-07-11 — capstone live test] get_distance_matrix_multi_mode()
        # invece di get_distance_matrix(): vedi la nota estesa in
        # distance_matrix.py sul bug reale scoperto sul primo test dal vivo
        # a San Marino (centro storico pedonale, "in auto" tornava sempre
        # 0 minuti). Ora richiediamo anche "walking" e lasciamo a Claude la
        # scelta di quale tempo comunicare per ciascuna coppia di punti.
        points = distance_matrix.build_points(hotels, pois)
        travel_times = distance_matrix.get_distance_matrix_multi_mode(points, settings.google_maps_key) if points else []
    except (geocoding.GeocodingError, liteapi_client.LiteApiError,
            requests.exceptions.RequestException, RuntimeError) as e:
        return PipelineResult(
            trip=trip, payload={}, raw_claude_output="", itinerary=None,
            parse_error=None, validation_report=None, rendered_markdown=None,
            data_layer_error=f"{type(e).__name__}: {e}",
        )

    api_payload = ApiPayload(hotels=hotels, travel_times=travel_times, poi=pois)
    payload = assemble_payload(trip, hotels, travel_times, pois)

    result = _call_claude_and_validate(trip, payload, api_payload, settings.anthropic_api_key)
    result.geocoding_warning = geocoding_warning
    return result


def _call_claude_and_validate(trip: Trip, payload: dict, api_payload, api_key: str) -> PipelineResult:
    itinerary = None
    parse_error = None
    validation_report = None
    rendered = None
    raw_output = ""

    try:
        raw_output = call_claude(
            payload,
            trip_objective_function=trip.objective_function,
            trip_duration_days=trip.duration_days,
            api_key=api_key,
        )
    except ClaudeEngineError as e:
        # [AGGIUNTO 2026-07-10] risposta troncata (max_tokens) -> stesso
        # percorso di errore "leggibile" di un ParseError, non un crash.
        parse_error = str(e)

    if raw_output and parse_error is None:
        try:
            itinerary = parse_claude_output(raw_output)
        except ParseError as e:
            parse_error = str(e)

    if itinerary is not None:
        valid_ids = {h.id for h in api_payload.hotels} | {p.id for p in api_payload.poi}
        # [AGGIUNTO 2026-07-12 — richiesta di Lorenzo di "certezza
        # matematica sulla qualità"] Prima, il pacing energetico
        # (HARD_CONSTRAINT punto 3) e l'alert di budget (punto 4) erano
        # verificati SOLO per scenari di test specifici in
        # main.py::_apply_scenario_checks() — mai per una vera chiamata
        # attraverso questa pipeline. `poi_energy_by_id` e
        # `min_cost_estimate` sono entrambi calcolabili da dati già
        # disponibili qui (ApiPayload.poi[].energy_tag,
        # ApiPayload.hotels[].price_night_eur), per QUALSIASI itinerario —
        # non serve più uno scenario di test scritto a mano.
        poi_energy_by_id = {p.id: p.energy_tag for p in api_payload.poi}
        known_prices = [h.price_night_eur for h in api_payload.hotels if h.price_night_eur is not None]
        min_cost_estimate = min(known_prices) * trip.duration_days if known_prices else None
        # [AGGIUNTO 2026-07-12 — audit di revisione completa, gap reale
        # trovato] `expected_duration_days` esisteva in validator.py da un
        # giro di audit precedente (verifica che days[] abbia esattamente
        # trip.duration_days elementi, numerati 1..N senza buchi né
        # duplicati) ma non era mai stato passato qui: era codice scritto,
        # testato in isolamento, MAI eseguito per un vero cliente — stessa
        # classe di bug già trovata altrove in questo progetto (una
        # funzione di controllo esistente ma mai collegata in produzione).
        # Un itinerario di 5 giorni che ne restituisse solo 2 avrebbe
        # ricevuto un PASS silenzioso. Wired qui, `trip.duration_days` è
        # già in scope.
        validation_report = validate_itinerary(
            itinerary, valid_ids,
            expected_duration_days=trip.duration_days,
            objective_function=trip.objective_function,
            poi_energy_by_id=poi_energy_by_id,
            budget_mode=trip.budget_mode,
            budget_eur=trip.budget_eur,
            min_cost_estimate=min_cost_estimate,
        )
        sanitized = strip_reasoning(itinerary)
        # [AGGIORNATO 2026-07-11 — link di ricerca multi-piattaforma] passa
        # gli hotel (già disponibili qui, mai stati inoltrati al renderer
        # prima d'ora) così render_markdown() può aggiungere i link di
        # confronto Booking/Airbnb/Vrbo — vedi affiliate_links.py.
        rendered = render_markdown(sanitized, trip.to_dict(), hotels=[h.to_dict() for h in api_payload.hotels])

    return PipelineResult(
        trip=trip,
        payload=payload,
        raw_claude_output=raw_output,
        itinerary=itinerary,
        parse_error=parse_error,
        validation_report=validation_report,
        rendered_markdown=rendered,
        api_payload=api_payload,
    )
