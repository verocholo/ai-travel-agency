"""
NODO 8 — Anthropic Claude (Create a Message). HTTP_MODULES_REALI.md §NODO 8 /
SYSTEM_PROMPT_MASTER.md.

System = prompts/system_prompt_master.txt (statico, cacheabile).
User   = prompts/user_message_template.txt + payload JSON del Nodo 7.
"""
from __future__ import annotations
import json
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


class ClaudeEngineError(Exception):
    """Errore esplicito lato Nodo 8, distinto da ParseError (Nodo 9) — vedi
    call_claude() per il caso d'uso (risposta troncata da max_tokens)."""
    pass


def load_system_prompt() -> str:
    return (PROMPTS_DIR / "system_prompt_master.txt").read_text(encoding="utf-8")


def load_user_template() -> str:
    return (PROMPTS_DIR / "user_message_template.txt").read_text(encoding="utf-8")


def select_model(objective_function: str, duration_days: int) -> str:
    """
    Model selector dinamico — HTTP_MODULES_REALI.md §NODO 8:
    EXCLUSIVITY o viaggi >10gg -> Opus 4.8 (ragionamento logistico superiore)
    resto -> Sonnet 5 (rapporto qualità/COGS, Cap. 2.7)
    """
    if "EXCLUSIVITY" in objective_function or duration_days > 10:
        return "claude-opus-4-8"
    return "claude-sonnet-5"


# [AGGIUNTO 2026-07-12 — audit di potenziamento massimo, gap reale] Prima
# `max_tokens` era un valore fisso (16000) indipendente da `duration_days`.
# Un itinerario più lungo produce fisiologicamente più output: più oggetti
# in "days[]", più blocchi, e uno <scratchpad> di CHAIN_OF_THOUGHT
# proporzionalmente più lungo (l'"Incastro temporale" da verificare cresce
# con ogni giorno in più). 16000 è stato sufficiente per coincidenza — ogni
# viaggio testato dal vivo finora è stato di 3-4 giorni, mai abbastanza
# lungo da avvicinarsi al limite — non per una relazione esplicita nel
# codice. BASE_MAX_TOKENS resta il default per i viaggi fino a
# BASELINE_DAYS incluso (nessuna regressione per il caso già verificato);
# oltre quella soglia, il budget cresce linearmente per giorno aggiuntivo,
# con un tetto ben sotto il limite reale del modello (128.000 token,
# verificato su platform.claude.com/docs — vedi call_claude() sotto).
BASE_MAX_TOKENS = 16000
BASELINE_DAYS = 7
TOKENS_PER_EXTRA_DAY = 1500
MAX_TOKENS_CEILING = 64000


def select_max_tokens(duration_days: int) -> int:
    """Scala il budget di output in base alla durata del viaggio — vedi nota sopra."""
    if duration_days <= BASELINE_DAYS:
        return BASE_MAX_TOKENS
    extra_days = duration_days - BASELINE_DAYS
    return min(BASE_MAX_TOKENS + extra_days * TOKENS_PER_EXTRA_DAY, MAX_TOKENS_CEILING)


def build_user_message(payload: dict) -> str:
    template = load_user_template()
    # {{7.json}} nel template Make.com = qui il payload serializzato
    return template.replace("{{7.json}}", json.dumps(payload, ensure_ascii=False, indent=2))


def call_claude(
    payload: dict,
    trip_objective_function: str,
    trip_duration_days: int,
    api_key: str,
    use_prefill: bool = False,
    max_tokens: int | None = None,
    temperature: float | None = None,
) -> str:
    """
    Ritorna il testo grezzo della risposta (da passare al Nodo 9 Parse JSON).
    Richiede `pip install anthropic` e una ANTHROPIC_API_KEY valida.

    [FIX 2026-07-10, #1] `temperature` di default era 0.4, fissato in ogni
    chiamata. Lorenzo ha riscontrato dal vivo un 400 reale dell'API:
    "`temperature` is deprecated for this model". Fix minimo: default None,
    incluso nella richiesta SOLO se esplicitamente passato da chi chiama.

    [VERIFICATO 2026-07-10, debug_temperature.py] Non era un problema del
    valore 0.4 specifico: QUALUNQUE valore esplicito viene rifiutato
    (testati 0.0, 0.4, 0.7 — tutti 400 "deprecated"), solo il default
    dell'API (equivalente a 1.0, cioè temperature NON impostata) è
    accettato. Conclusione chiusa, non più un'ipotesi: per questo modello
    non esiste una leva per abbassare la variabilità via `temperature` —
    la consistenza del prodotto deve venire dalla qualità delle regole nel
    system prompt (HARD_CONSTRAINTS/GROUNDING), non da un parametro di
    campionamento. Vedi prototipo-status.md per i test di consistenza
    (--repeat N) che misurano quanto questo sia comunque affidabile in
    pratica nonostante l'impossibilità di abbassare la temperature.

    [FIX 2026-07-10, #2] `use_prefill` di default era True (2° messaggio
    `assistant` con contenuto `{` per forzare il JSON dal primo carattere).
    Secondo 400 reale, subito dopo il fix #1: "This model does not support
    assistant message prefill. The conversation must end with a user
    message." Default cambiato a False. La difesa contro prosa prima/dopo
    il JSON resta l'`OUTPUT_CONTRACT` nel system prompt
    (SYSTEM_PROMPT_MASTER.md) — vedi HTTP_MODULES_REALI.md §Nodo 8 per la
    nota completa e per l'hardening alternativo (tool-use/structured
    output) da valutare se comparisse prosa residua nei test.

    [FIX 2026-07-10, #3] `max_tokens=8192` era insufficiente: il terzo test
    dal vivo di Lorenzo ha prodotto un JSON troncato a metà dello
    `<scratchpad>` (il CHAIN_OF_THOUGHT del system prompt è volutamente
    verboso), con conseguente `ParseError` a valle nel Nodo 9 ("Unterminated
    string"). Verificato su platform.claude.com/docs: il limite reale per
    Sonnet 5/Opus 4.8 in modalità sincrona è 128.000 token — 8192 era una
    scelta arbitraria molto sotto il tetto disponibile. Alzato a 16000
    (doppio, ancora ben sotto il tetto) come nuovo default. Se dovesse
    ripresentarsi il troncamento anche a 16000, alzalo ulteriormente: c'è
    ampio margine prima di 128k. La funzione ora rileva esplicitamente il
    troncamento (`response.stop_reason == "max_tokens"`) e solleva
    `ClaudeEngineError` con un messaggio diagnostico chiaro, invece di
    lasciare che il Nodo 9 fallisca con un errore di parsing criptico.
    """
    import anthropic  # import locale: cosi il resto del modulo resta testabile senza il pacchetto

    if max_tokens is None:
        # [AGGIUNTO 2026-07-12] nessun valore esplicito passato dal chiamante
        # -> scala col numero di giorni del viaggio, vedi select_max_tokens().
        max_tokens = select_max_tokens(trip_duration_days)

    client = anthropic.Anthropic(api_key=api_key)
    model = select_model(trip_objective_function, trip_duration_days)
    system_prompt = load_system_prompt()
    user_message = build_user_message(payload)

    messages = [{"role": "user", "content": user_message}]
    if use_prefill:
        # Assistant prefill "{" — forza il JSON dal primo carattere (hardening Nodo 9)
        messages.append({"role": "assistant", "content": "{"})

    create_kwargs = dict(
        model=model,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=messages,
    )
    if temperature is not None:
        create_kwargs["temperature"] = temperature

    response = client.messages.create(**create_kwargs)
    text = "".join(block.text for block in response.content if hasattr(block, "text"))
    if use_prefill:
        text = "{" + text

    if response.stop_reason == "max_tokens":
        used = getattr(response.usage, "output_tokens", "?")
        raise ClaudeEngineError(
            f"Risposta di Claude troncata: ha raggiunto il limite max_tokens={max_tokens} "
            f"(output_tokens usati: {used}) prima di completare il JSON. Non è un errore di "
            f"formato — aumenta max_tokens in call_claude() (tetto reale del modello: 128.000 "
            f"token, verificato su platform.claude.com/docs) e riprova."
        )
    return text
