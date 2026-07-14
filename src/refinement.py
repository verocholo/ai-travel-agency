"""
Agente di affinamento conversazionale (prototipo) — src/refinement.py.

[NUOVO 2026-07-12 — richiesta di Lorenzo, idea proposta da Claude e
accettata: "il cliente può chiedere modifiche puntuali all'itinerario
già ricevuto (es. 'cambia il giorno 2') senza doverne generare uno
nuovo da zero"]

Deliberatamente NON un "vero agente" che chiama API dal vivo durante la
conversazione — userebbe dati diversi da quelli già verificati e
romperebbe la garanzia di Fedeltà RAG che è il punto di forza
dell'architettura attuale (vedi discussione con Lorenzo sugli "agenti").
Questo è invece un secondo turno della STESSA generazione: stesso
`system_prompt_master.txt` (stesse HARD_CONSTRAINTS/grounding), stessi
identici DATI_API_FORNITI già usati la prima volta (mai richieste nuove
API dal vivo) — solo un nuovo messaggio User che include l'itinerario
attuale e la richiesta del cliente, chiedendo una versione aggiornata.
Il Nodo 9 (validazione) viene rieseguito identico sul risultato, quindi
un affinamento che uscisse dai vincoli o inventasse dati verrebbe
comunque rilevato — nessuna scorciatoia sulla qualità rispetto alla
generazione originale.

Canale reale con cui il cliente invierebbe la richiesta (email, chat web,
WhatsApp) resta una decisione della fase Make.com, non affrontata qui —
qui costruiamo e verifichiamo solo la logica.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .claude_engine import load_system_prompt, select_model, select_max_tokens
from .schemas import Trip, ApiPayload
from .validator import parse_claude_output, validate_itinerary, strip_reasoning, ParseError, ValidationReport
from .renderer import render_markdown

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


class RefinementError(Exception):
    """Sollevata se la chiamata a Claude fallisce o la risposta è troncata
    (max_tokens) — non un ParseError, quello è gestito separatamente
    esponendo `RefinementResult.parse_error` (stesso pattern di
    `PipelineResult` in pipeline.py, per coerenza con il resto del
    progetto)."""


@dataclass
class RefinementResult:
    raw_claude_output: str
    itinerary: dict | None
    parse_error: str | None
    validation_report: ValidationReport | None
    rendered_markdown: str | None


def load_refinement_template() -> str:
    return (PROMPTS_DIR / "user_message_refinement_template.txt").read_text(encoding="utf-8")


def build_refinement_user_message(
    current_itinerary: dict, api_payload_dict: dict, customer_request: str
) -> str:
    """Funzione pura — costruisce il messaggio User per il turno di
    affinamento, riusando il template esternalizzato (stessa convenzione
    di `claude_engine.build_user_message()`)."""
    template = load_refinement_template()
    return (
        template.replace("{{richiesta_cliente}}", customer_request)
        .replace(
            "{{itinerario_attuale.json}}",
            json.dumps(current_itinerary, ensure_ascii=False, indent=2),
        )
        .replace("{{7.json}}", json.dumps(api_payload_dict, ensure_ascii=False, indent=2))
    )


def refine_itinerary(
    current_itinerary: dict,
    payload: dict,
    api_payload: ApiPayload,
    trip: Trip,
    customer_request: str,
    api_key: str,
    max_tokens: int | None = None,
) -> RefinementResult:
    """
    Rigenera l'itinerario applicando la richiesta del cliente, riusando
    system prompt e DATI_API_FORNITI originali. Rivalida il risultato con
    lo stesso Nodo 9 (`validate_itinerary`) usato per la generazione
    iniziale — stessa soglia di qualità, nessuna scorciatoia.

    [AGGIUNTO 2026-07-12 — audit di potenziamento massimo] `max_tokens`
    era fisso a 16000 come in claude_engine.py prima del fix gemello
    lì — stesso gap, stessa soluzione: se non esplicitamente passato,
    scala con `trip.duration_days` via `select_max_tokens()` (condivisa
    con la generazione iniziale, un solo posto dove questa logica vive).
    """
    import anthropic  # import locale, stessa convenzione di claude_engine.py

    if max_tokens is None:
        max_tokens = select_max_tokens(trip.duration_days)

    client = anthropic.Anthropic(api_key=api_key)
    model = select_model(trip.objective_function, trip.duration_days)
    system_prompt = load_system_prompt()
    user_message = build_refinement_user_message(current_itinerary, payload, customer_request)

    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    raw_output = "".join(block.text for block in response.content if hasattr(block, "text"))

    if response.stop_reason == "max_tokens":
        raise RefinementError(
            f"Risposta di Claude troncata durante l'affinamento (richiesta: "
            f"'{customer_request}'): ha raggiunto max_tokens={max_tokens} prima di "
            f"completare il JSON. Aumenta max_tokens e riprova."
        )

    parse_error = None
    itinerary = None
    try:
        itinerary = parse_claude_output(raw_output)
    except ParseError as e:
        parse_error = str(e)

    validation_report = None
    rendered = None
    if itinerary is not None:
        valid_ids = {h.id for h in api_payload.hotels} | {p.id for p in api_payload.poi}
        # [AGGIUNTO 2026-07-12 — richiesta di Lorenzo di "certezza
        # matematica sulla qualità"] Stesso fix gemello di
        # pipeline.py::_call_claude_and_validate(): il pacing energetico e
        # l'alert di budget vanno riverificati anche su un itinerario
        # RIFINITO, con la stessa severità della generazione originale —
        # nessuna scorciatoia di qualità sul secondo turno (stesso
        # principio già dichiarato nel docstring di refine_itinerary()).
        poi_energy_by_id = {p.id: p.energy_tag for p in api_payload.poi}
        known_prices = [h.price_night_eur for h in api_payload.hotels if h.price_night_eur is not None]
        min_cost_estimate = min(known_prices) * trip.duration_days if known_prices else None
        # [AGGIUNTO 2026-07-12 — audit di revisione completa, stesso gap di
        # pipeline.py::_call_claude_and_validate()] `expected_duration_days`
        # non era mai passato qui — un affinamento che silenziosamente
        # perdesse giorni (o ne duplicasse la numerazione) avrebbe ricevuto
        # un PASS, nessuna scorciatoia di qualità rispetto alla generazione
        # originale era davvero garantita su questo fronte specifico.
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
        rendered = render_markdown(
            sanitized, trip.to_dict(), hotels=[h.to_dict() for h in api_payload.hotels]
        )

    return RefinementResult(
        raw_claude_output=raw_output,
        itinerary=itinerary,
        parse_error=parse_error,
        validation_report=validation_report,
        rendered_markdown=rendered,
    )
