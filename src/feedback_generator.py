"""
Simulazione feedback post-viaggio (prototipo) — src/feedback_generator.py.

[NUOVO 2026-07-12 — richiesta di Lorenzo, idea proposta da Claude e
accettata: "un breve questionario di follow-up post-viaggio, personalizzato,
per alimentare sia il Data Moat sia le testimonianze di marketing"]

Genera un messaggio di follow-up con 2-3 domande ANCORATE A DETTAGLI REALI
dell'itinerario consegnato (non domande generiche) — vedi
`prompts/system_prompt_feedback.txt` per il razionale completo, incluso il
doppio scopo (qualità del Data Moat + Social Proof per il marketing,
PROGETTO.md §8.6) e la regola che il consenso alla testimonianza pubblica
va sempre richiesto esplicitamente, mai presunto.

Stesso pattern di `guide_generator.py`: import locale di `anthropic`,
riuso di `validator.parse_claude_output()` per il parsing JSON (stessa
difesa contro una fence markdown avvolgente già trovata come bug reale nel
Nodo 9).

Canale di invio reale (email automatica dopo la data di rientro) resta
una decisione della fase Make.com — qui costruiamo e verifichiamo solo il
contenuto generato.
"""
from __future__ import annotations

import json
from pathlib import Path

from .validator import parse_claude_output, ParseError

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

_REQUIRED_FIELDS = ["intro_message", "questions", "testimonial_request", "closing_message"]


class FeedbackGeneratorError(Exception):
    """Sollevata se la chiamata a Claude fallisce, se l'output non è JSON
    valido, o se manca un campo richiesto dallo schema."""


def _load_system_prompt() -> str:
    return (PROMPTS_DIR / "system_prompt_feedback.txt").read_text(encoding="utf-8")


def build_feedback_user_message(itinerary: dict, objective_function: str | None = None) -> str:
    """Funzione pura — costruisce il messaggio User. Passa l'itinerario
    (senza `reasoning`, che il chiamante dovrebbe già aver rimosso con
    `strip_reasoning()` come per il resto del progetto) così Claude può
    ancorare le domande a dettagli reali (giorni, attività specifiche)."""
    lines = ["Ecco l'itinerario completato dal cliente:"]
    if objective_function:
        lines.append(f"objective_function: {objective_function}")
    lines.append(json.dumps(itinerary, ensure_ascii=False, indent=2))
    lines.append(
        "\nGenera il messaggio di follow-up post-viaggio seguendo esattamente lo schema "
        "JSON descritto in [OUTPUT_CONTRACT]."
    )
    return "\n".join(lines)


def _validate_feedback_shape(feedback: dict) -> None:
    missing = [f for f in _REQUIRED_FIELDS if f not in feedback or feedback[f] in (None, "")]
    if missing:
        raise FeedbackGeneratorError(
            f"Il messaggio di feedback generato non ha tutti i campi richiesti — "
            f"mancanti o vuoti: {missing}. Risposta grezza (troncata a 500 char): "
            f"{str(feedback)[:500]}"
        )
    questions = feedback["questions"]
    if not isinstance(questions, list) or not (2 <= len(questions) <= 3):
        raise FeedbackGeneratorError(
            f"'questions' deve essere una lista di 2-3 elementi, ricevuto: {questions!r}"
        )


def generate_post_trip_feedback(
    itinerary: dict, api_key: str, objective_function: str | None = None, max_tokens: int = 2000
) -> dict:
    """
    Genera il messaggio di follow-up post-viaggio. Ritorna un dict con lo
    schema descritto in `prompts/system_prompt_feedback.txt`.

    Solleva `FeedbackGeneratorError` con un messaggio esplicito se Claude
    non risponde con JSON valido o se manca un campo richiesto — stesso
    principio già applicato in `guide_generator.py`.
    """
    import anthropic  # import locale, stessa convenzione degli altri moduli Claude

    client = anthropic.Anthropic(api_key=api_key)
    system_prompt = _load_system_prompt()
    user_message = build_feedback_user_message(itinerary, objective_function=objective_function)

    response = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    text = "".join(block.text for block in response.content if hasattr(block, "text"))

    if response.stop_reason == "max_tokens":
        raise FeedbackGeneratorError(
            f"Risposta di Claude troncata per il messaggio di feedback: ha raggiunto "
            f"max_tokens={max_tokens} prima di completare il JSON. Aumenta max_tokens e riprova."
        )

    try:
        feedback = parse_claude_output(text)
    except ParseError as e:
        raise FeedbackGeneratorError(
            f"Output di Claude per il messaggio di feedback non è JSON valido: {e}"
        ) from e

    _validate_feedback_shape(feedback)
    return feedback


def render_feedback_markdown(feedback: dict) -> str:
    """Rende il messaggio in Markdown leggibile, per revisione/demo —
    stesso stile degli altri renderer del progetto."""
    questions = "\n".join(f"{i+1}. {q}" for i, q in enumerate(feedback["questions"]))
    return (
        f"{feedback['intro_message']}\n\n"
        f"{questions}\n\n"
        f"{feedback['testimonial_request']}\n\n"
        f"{feedback['closing_message']}\n"
    )
