"""
Guida turistica per singolo POI (contenuto bonus) — src/guide_generator.py.

[NUOVO 2026-07-12 — richiesta di Lorenzo, chiarita esplicitamente: "ci
permetterebbe di creare delle vere e proprie guide turistiche sulla base
dell'itinerario generato (es. giro al colosseo, guida turistica sul
colosseo a tutto tondo)"]

Questo modulo è DISTINTO dal Nodo 8 (`claude_engine.py`, generazione
dell'itinerario) e ha un profilo di rischio diverso, non uguale — è
importante non confonderli:

- Nell'itinerario, ogni hotel/POI/orario DEVE provenire da
  [DATI_API_FORNITI] (Fedeltà RAG) — inventare che un luogo esista è
  l'errore critico che l'intera architettura del Nodo 9 esiste per
  impedire.
- Qui il POI (es. "Colosseo") è un luogo reale e noto, la cui esistenza
  non è in discussione — normalmente proviene già da un `poi_id` reale
  dell'itinerario appena generato. Il rischio qui non è "inventare che il
  luogo esista", ma il normale rischio di accuratezza di un LLM su
  contenuto storico/culturale generico, e — soprattutto — il rischio di
  affermare come fatto certo un dato che cambia nel tempo (orari, prezzi).
  Il system prompt dedicato (`prompts/system_prompt_guide.txt`) istruisce
  esplicitamente Claude a non affermare orari/prezzi specifici come fatto
  e a restare generico sui dettagli storici incerti — e ogni guida include
  sempre un campo `disclaimer` esplicito. Non è un sostituto della
  Fedeltà RAG, è una mitigazione onesta per un tipo di contenuto diverso.

Segue la stessa convenzione di `claude_engine.py`: import locale di
`anthropic` (il resto del modulo resta testabile senza il pacchetto),
riuso di `validator.parse_claude_output()` per il parsing JSON (stessa
difesa contro una fence markdown avvolgente già trovata come bug reale
nella generazione dell'itinerario — vedi CHANGELOG.md, capstone
lavoro/Lisbona — non reinventata qui apposta, per non rischiare la stessa
classe di bug due volte in due punti diversi del codice).
"""
from __future__ import annotations

from pathlib import Path

from .validator import parse_claude_output, ParseError

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

_REQUIRED_FIELDS = [
    "poi_name",
    "title",
    "history_summary",
    "practical_tips",
    "best_time_to_visit",
    "estimated_visit_duration",
    "consiglio_personalizzato",
    "disclaimer",
]


class GuideGeneratorError(Exception):
    """Sollevata se la chiamata a Claude fallisce, se l'output non è JSON
    valido (dopo lo stesso strip di fence markdown già usato nel Nodo 9),
    o se manca uno dei campi richiesti dallo schema — mai un
    `KeyError`/`AttributeError` criptico a valle."""


def _load_system_prompt() -> str:
    return (PROMPTS_DIR / "system_prompt_guide.txt").read_text(encoding="utf-8")


def build_guide_user_message(
    poi_name: str,
    destination: str,
    objective_function: str | None = None,
    module_id: str | None = None,
) -> str:
    """
    Funzione pura (nessuna chiamata di rete) — costruisce il messaggio
    User per Claude. Separata da `generate_poi_guide()` così è testabile
    senza bisogno di una API key, stesso principio già applicato a
    `render_html()` in pdf_renderer.py e a `build_search_links()` in
    affiliate_links.py.
    """
    lines = [
        f"Scrivi una guida turistica per il seguente punto di interesse:",
        f"- Nome POI: {poi_name}",
        f"- Destinazione/città: {destination}",
    ]
    if objective_function:
        lines.append(f"- objective_function del viaggiatore: {objective_function}")
    if module_id:
        lines.append(f"- modulo verticale del viaggiatore: {module_id}")
    lines.append(
        "\nRispondi seguendo esattamente lo schema JSON descritto in [OUTPUT_CONTRACT]."
    )
    return "\n".join(lines)


def _validate_guide_shape(guide: dict, poi_name: str) -> None:
    missing = [f for f in _REQUIRED_FIELDS if f not in guide or guide[f] in (None, "")]
    if missing:
        raise GuideGeneratorError(
            f"La guida generata per '{poi_name}' non ha tutti i campi richiesti "
            f"dallo schema — mancanti o vuoti: {missing}. Risposta grezza (troncata a "
            f"500 char per leggibilità): {str(guide)[:500]}"
        )
    if not isinstance(guide["practical_tips"], list) or not guide["practical_tips"]:
        raise GuideGeneratorError(
            f"'practical_tips' per '{poi_name}' deve essere una lista non vuota, "
            f"ricevuto: {guide['practical_tips']!r}"
        )


def generate_poi_guide(
    poi_name: str,
    destination: str,
    api_key: str,
    objective_function: str | None = None,
    module_id: str | None = None,
    max_tokens: int = 4000,
) -> dict:
    """
    Genera una guida turistica per un singolo POI usando Claude. Ritorna
    un dict con lo schema descritto in `prompts/system_prompt_guide.txt`.

    Solleva `GuideGeneratorError` con un messaggio esplicito (non un
    traceback criptico) se:
    - Claude non risponde con JSON valido (stesso fix già applicato al
      Nodo 9 per una fence markdown avvolgente — vedi
      `parse_claude_output()` in validator.py);
    - manca un campo richiesto dallo schema.

    Nota deliberata: usa sempre `claude-sonnet-5` (non il selettore
    Opus/Sonnet di `claude_engine.select_model()`) — una guida turistica
    è un contenuto più breve e meno critico logisticamente di un
    itinerario completo multi-vincolo, non giustifica il costo/latenza di
    Opus.

    [FIX 2026-07-12 — trovato con una vera chiamata dal vivo, non in
    teoria] Il primo default di `max_tokens=2000` era troppo basso: la
    prima verifica reale con l'API (guida sul Colosseo) ha troncato la
    risposta a metà del JSON, esattamente la stessa classe di bug già
    trovata e corretta in `claude_engine.call_claude()` per l'itinerario
    completo (vedi CHANGELOG.md, fix #3 del 2026-07-10) — qui riprodotta
    perché `history_summary` (2-4 paragrafi) più lo schema JSON pesano più
    di quanto stimato. Alzato a 4000, poi riverificato con una nuova
    chiamata reale che è andata a buon fine.
    """
    import anthropic  # import locale: cosi il resto del modulo resta testabile senza il pacchetto

    client = anthropic.Anthropic(api_key=api_key)
    system_prompt = _load_system_prompt()
    user_message = build_guide_user_message(
        poi_name, destination, objective_function=objective_function, module_id=module_id
    )

    response = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    text = "".join(block.text for block in response.content if hasattr(block, "text"))

    if response.stop_reason == "max_tokens":
        raise GuideGeneratorError(
            f"Risposta di Claude troncata per la guida di '{poi_name}': ha raggiunto "
            f"max_tokens={max_tokens} prima di completare il JSON. Aumenta max_tokens "
            f"e riprova."
        )

    try:
        guide = parse_claude_output(text)
    except ParseError as e:
        raise GuideGeneratorError(
            f"Output di Claude per la guida di '{poi_name}' non è JSON valido: {e}"
        ) from e

    _validate_guide_shape(guide, poi_name)
    return guide


def render_guide_markdown(guide: dict) -> str:
    """Rende la guida in Markdown leggibile — stesso stile di
    `renderer.py` (documento di revisione interna/allegato, non il PDF
    impaginato per il cliente finale, che potrà integrare questo
    contenuto in futuro se Lorenzo lo desidera)."""
    tips = "\n".join(f"- {tip}" for tip in guide["practical_tips"])
    return (
        f"# {guide['title']}\n\n"
        f"*Guida turistica: {guide['poi_name']}*\n\n"
        f"## Storia e contesto\n\n{guide['history_summary']}\n\n"
        f"## Consigli pratici\n\n{tips}\n\n"
        f"## Quando visitare\n\n{guide['best_time_to_visit']}\n\n"
        f"## Durata consigliata della visita\n\n{guide['estimated_visit_duration']}\n\n"
        f"## Consiglio su misura per te\n\n{guide['consiglio_personalizzato']}\n\n"
        f"---\n*{guide['disclaimer']}*\n"
    )
