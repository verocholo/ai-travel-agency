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

import re
from pathlib import Path

from . import cost_telemetry
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


# --- Chi merita una guida ------------------------------------------------
#
# [NUOVO 2026-08-02 — richiesta di Lorenzo: «deve esserci una guida per ogni
# cosa che lo richieda, non aver paura di sembrare prolisso»]
#
# Prima di oggi la regola era implicita e viveva dentro un ciclo in
# `pdf_extras.py`: "una guida per ogni `poi_id` che compare nell'itinerario".
# Sembra generosa, ma sbaglia da tutte e due le parti.
#
# Sbaglia per DIFETTO perché un programma vero non è fatto solo di POI con un
# id di Google: "mattinata nel quartiere di Alfama", "salita al belvedere di
# Santa Luzia", "mercato della Ribeira" arrivano spesso come blocchi SENZA
# `poi_id` — sono esattamente le tappe che un cliente non conosce e su cui
# vorrebbe leggere qualcosa, ed erano precisamente quelle che restavano mute.
#
# Sbaglia per ECCESSO perché generava una "guida turistica con storia e
# contesto culturale" anche per la trattoria da trenta coperti scelta per la
# cena di martedì. Su un luogo che il modello non può conoscere, quel campo
# non è ricco: è inventato. E il cliente che legge la storia secolare di un
# locale aperto nel 2019 smette di fidarsi anche delle pagine giuste. Per i
# ristoranti il prodotto ha già il trattamento corretto e verificato — la
# scheda con menù, telefono, indirizzo e link reali (`place_links.py`).
#
# Da qui la regola esplicita qui sotto, in un solo posto, testabile senza
# rete e senza modello.
#
# Soglia di notorietà per i ristoranti: un locale con molte migliaia di
# recensioni NON è la trattoria di quartiere — è un'istituzione cittadina
# (Café A Brasileira, Katz's, Antico Caffè Greco) di cui esiste davvero una
# storia pubblica. Il numero è un compromesso dichiarato, non una verità:
# alto abbastanza da escludere il locale di quartiere, basso abbastanza da
# non escludere l'istituzione di una città piccola. Se un giorno si scoprirà
# sbagliato, si cambia QUESTO numero, in un punto solo.
NOTABLE_REVIEW_COUNT = 1500

# Tipi normalizzati (vedi `places_client._TYPE_NORMALIZE`) che ottengono una
# guida sempre, senza condizioni: sono luoghi che si visitano, ed è
# esattamente ciò di cui una guida parla.
_ALWAYS_GUIDED_TYPES = {"museum", "activity", "shopping"}

# Parole che, da sole, descrivono un pezzo di LOGISTICA e non un luogo:
# un'attività fatta solo di queste non ha niente da raccontare.
#
# Nota sul metodo: questa lista NON decide da sola. Serve a evitare di
# spendere una chiamata a Claude (e mezzo minuto di orologio, dentro un
# tetto di 300 secondi) per chiedere una guida su "check-in in hotel". La
# decisione vera — «di questa descrizione riconosco un luogo reale?» — resta
# al modello, che può rispondere `{"skip": true}` (vedi
# `SKIP_MARKER` e `prompts/system_prompt_guide.txt`). Un filtro di parole
# chiave che decidesse da solo sarebbe fragile in modo invisibile.
_LOGISTIC_WORDS = {
    "check", "checkin", "check-in", "checkout", "check-out", "hotel",
    "trasferimento", "transfer", "spostamento", "volo", "aereo", "treno",
    "bus", "taxi", "navetta", "partenza", "arrivo", "rientro", "ritorno",
    "bagagli", "valigie", "deposito", "riposo", "relax", "pausa", "sosta",
    "colazione", "pranzo", "cena", "aperitivo", "libero", "libera", "slot",
    "tempo", "serata", "mattinata", "pomeriggio", "notte", "sveglia",
    # [AGGIUNTO 2026-08-02 — trovato dai test scritti in questa stessa
    # tornata: "Check-in e sistemazione bagagli" superava il filtro perché
    # "sistemazione" non era in lista, e sarebbe costato una chiamata a
    # Claude per farsi rispondere {"skip": true}. Insieme a quella sono
    # entrati i plurali dei termini presenti solo al singolare: la stessa
    # svista, di cui il caso trovato era soltanto l'istanza più visibile.]
    "sistemazione", "sistemarsi", "bagaglio", "trasferimenti", "spostamenti",
    "attesa", "imbarco", "pernottamento", "pernotto", "brunch", "merenda",
    "spuntino", "mattina", "mattino", "sera", "giornata", "resto",
    "in", "a", "al", "alla", "allo", "ai", "agli", "alle", "il", "lo", "la",
    "i", "gli", "le", "un", "uno", "una", "di", "del", "della", "dei",
    "degli", "delle", "e", "ed", "con", "per", "da", "dal", "dalla", "su",
    "sul", "sulla", "tra", "fra", "poi", "quindi", "verso", "presso",
}

# Una descrizione che non contiene NESSUNA parola oltre a quelle logistiche
# è scartata prima di spendere una chiamata. Serve almeno una parola
# "portante" di questa lunghezza: sotto, sono quasi sempre preposizioni o
# abbreviazioni.
_MIN_CONTENT_WORD_LEN = 4

_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)

# Marcatore con cui il modello può dichiarare che dietro una descrizione non
# riconosce nessun luogo reale. Vedi `prompts/system_prompt_guide.txt`.
SKIP_MARKER = "skip"


class GuideSkipped(Exception):
    """Il modello ha dichiarato di non riconoscere un luogo reale dietro la
    descrizione ricevuta, e ha rifiutato di scrivere.

    È un esito CORRETTO, non un errore: è la valvola che permette di essere
    generosi con i candidati (ogni blocco del programma, non solo i POI con
    un id di Google) senza pagarlo in contenuto inventato. Ha una classe sua
    proprio perché il chiamante possa contarlo separatamente dai guasti veri
    — "tre guide saltate perché non erano luoghi" e "tre guide perse per un
    errore di rete" sono due situazioni che richiedono due reazioni diverse,
    e un log che le confonde non serve a nessuno."""


def _content_words(text: str) -> list[str]:
    return [
        w for w in (m.group(0).lower() for m in _WORD_RE.finditer(text or ""))
        if w not in _LOGISTIC_WORDS and len(w) >= _MIN_CONTENT_WORD_LEN
    ]


def looks_like_a_place(activity: str) -> bool:
    """Vero se la descrizione di un blocco PUÒ nascondere un luogo reale.

    Volutamente permissiva: il costo di un falso positivo è una chiamata
    sprecata a cui il modello risponde `skip`; il costo di un falso negativo
    è una tappa del viaggio che resta senza racconto — che è il difetto che
    Lorenzo ha segnalato. Nel dubbio si chiede."""
    return bool(_content_words(activity))


def select_guide_targets(itinerary: dict, poi_by_id: dict) -> list[dict]:
    """Decide COSA merita una guida tascabile. Funzione pura: nessuna rete,
    nessun modello, nessuna chiave API — quindi verificabile con un test.

    Ritorna una lista ordinata e deduplicata di dizionari:
        {"key", "poi_id", "name", "kind", "reason"}
    - `key`   — identificatore stabile usato come ancora nel PDF;
    - `poi_id`— l'id di Google se il bersaglio è un POI, altrimenti `None`;
    - `name`  — cosa chiedere a Claude;
    - `kind`  — "poi" | "blocco" (il secondo va chiesto con più prudenza);
    - `reason`— perché è entrato, in italiano, per i log e per i test.

    L'ordine è quello di VISITA (giorno, poi posizione nel giorno), non
    alfabetico né per id: il capitolo delle guide in fondo al documento
    scorre così nello stesso ordine del programma, e chi lo sfoglia senza
    usare i link interni ritrova le sue tappe nella sequenza in cui le vive.
    Prima si ordinava per `poi_id`, cioè per una stringa opaca di Google:
    un ordine perfettamente deterministico e perfettamente insensato per chi
    legge.
    """
    targets: list[dict] = []
    seen: set[str] = set()
    if not isinstance(itinerary, dict):
        return targets

    for day in itinerary.get("days") or []:
        if not isinstance(day, dict):
            continue
        for block in day.get("blocks") or []:
            if not isinstance(block, dict):
                continue
            poi_id = block.get("poi_id")
            if isinstance(poi_id, str) and poi_id in poi_by_id:
                poi = poi_by_id[poi_id]
                decision = _judge_poi(poi)
                if decision is None:
                    continue
                if poi_id in seen:
                    continue
                seen.add(poi_id)
                targets.append({
                    "key": poi_id,
                    "poi_id": poi_id,
                    "name": getattr(poi, "name", "") or "",
                    "kind": "poi",
                    "reason": decision,
                })
                continue

            # Blocco senza POI: è qui che vivevano le tappe mute.
            activity = block.get("activity") or block.get("title") or ""
            activity = str(activity).strip()
            if not activity or not looks_like_a_place(activity):
                continue
            key = "blocco-" + re.sub(r"[^a-z0-9]+", "-", activity.lower()).strip("-")[:60]
            if not key or key in seen:
                continue
            seen.add(key)
            targets.append({
                "key": key,
                "poi_id": None,
                "name": activity,
                "kind": "blocco",
                "reason": "tappa del programma senza scheda Google",
            })

    return targets


def _judge_poi(poi) -> str | None:
    """Motivo per cui questo POI merita una guida, oppure `None`."""
    poi_type = (getattr(poi, "type", "") or "").lower()
    if poi_type in _ALWAYS_GUIDED_TYPES:
        return f"tipo '{poi_type}': è un luogo che si visita"
    if poi_type == "restaurant":
        reviews = getattr(poi, "user_rating_count", None) or 0
        if reviews >= NOTABLE_REVIEW_COUNT:
            return f"locale storico/notissimo ({reviews} recensioni)"
        # Nessuna guida: il ristorante ha già la sua scheda con menù e info
        # reali, e una storia inventata varrebbe meno di niente.
        return None
    # Tipo sconosciuto o assente: si concede la guida. Un tipo non
    # riconosciuto è quasi sempre un luogo vero con un'etichetta che non
    # abbiamo mappato, non un ristorante travestito.
    return "tipo non classificato: trattato come luogo da visitare"


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
    kind: str = "poi",
) -> str:
    """
    Funzione pura (nessuna chiamata di rete) — costruisce il messaggio
    User per Claude. Separata da `generate_poi_guide()` così è testabile
    senza bisogno di una API key, stesso principio già applicato a
    `render_html()` in pdf_renderer.py e a `build_search_links()` in
    affiliate_links.py.

    [AGGIUNTO 2026-08-02] `kind`. Un nome arrivato da Google Places è un
    luogo, punto. Una riga del programma ("mattinata nel quartiere di
    Alfama") è una FRASE che PUÒ contenere un luogo — e va chiesta in modo
    diverso, dicendo esplicitamente al modello che ha il permesso di
    rispondere «qui non riconosco nessun posto reale». Senza questa
    differenza, allargare i candidati ai blocchi del programma avrebbe
    significato solo produrre guide inventate più in fretta.
    """
    lines = [
        "Scrivi una guida turistica per il seguente punto di interesse:",
        f"- Nome POI: {poi_name}",
        f"- Destinazione/città: {destination}",
    ]
    if objective_function:
        lines.append(f"- objective_function del viaggiatore: {objective_function}")
    if module_id:
        lines.append(f"- modulo verticale del viaggiatore: {module_id}")
    if kind == "blocco":
        lines.append(
            "\nATTENZIONE — il testo del campo 'Nome POI' qui sopra NON viene da una "
            "scheda di Google Places: è la riga con cui questa attività compare nel "
            "programma del viaggiatore, scritta in linguaggio naturale. Può contenere "
            "il nome di un luogo reale (un quartiere, una piazza, un belvedere, un "
            "mercato, una via) oppure descrivere solo un momento della giornata. "
            "Se riconosci con sicurezza un luogo reale e identificabile, scrivi la "
            "guida su QUEL luogo. Se non lo riconosci, o se la riga descrive solo "
            "un'attività generica, rispondi ESATTAMENTE con {\"skip\": true} e nulla "
            "altro: una guida inventata vale meno di una guida assente."
        )
    lines.append(
        "\nRispondi seguendo esattamente lo schema JSON descritto in [OUTPUT_CONTRACT]."
    )
    return "\n".join(lines)


def _validate_guide_shape(guide: dict, poi_name: str) -> None:
    # [AGGIUNTO 2026-07-31 — audit di perfezionamento, bug reale eseguito]
    # se `parse_claude_output` restituisce uno scalare JSON (es. un numero),
    # `f not in guide` faceva `argument of type 'int' is not iterable` →
    # TypeError criptico invece del GuideGeneratorError pulito promesso.
    if not isinstance(guide, dict):
        raise GuideGeneratorError(
            f"La guida generata per '{poi_name}' non è un oggetto JSON "
            f"(trovato {type(guide).__name__})."
        )
    # [AGGIUNTO 2026-08-02] La rinuncia dichiarata dal modello. Va
    # intercettata QUI, prima del controllo dei campi obbligatori: altrimenti
    # `{"skip": true}` verrebbe letto come una guida rotta e finirebbe nel
    # log dei guasti insieme ai timeout di rete, nascondendo entrambi.
    if guide.get(SKIP_MARKER) is True:
        raise GuideSkipped(
            f"Nessun luogo reale riconosciuto dietro '{poi_name}': guida non scritta."
        )
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
    guide["highlights"] = normalize_highlights(guide.get("highlights"))
    # [AGGIUNTI 2026-08-02 — richiesta di Lorenzo: «non aver paura di
    # sembrare prolisso»] Tre campi nuovi, tutti OPZIONALI per la stessa
    # ragione già scritta sotto per `highlights`: sono arricchimento, e una
    # voce malformata non deve costare al cliente anche la storia e i
    # consigli pratici di quel luogo. Una guida generata prima di oggi resta
    # valida e continua a essere impaginata senza.
    guide["curiosita"] = normalize_string_list(guide.get("curiosita"))
    guide["dintorni"] = normalize_highlights(guide.get("dintorni"))
    guide["errore_da_evitare"] = str(guide.get("errore_da_evitare") or "").strip()


def normalize_string_list(raw) -> list[str]:
    """Ripulisce una lista di stringhe opzionale (es. `curiosita`).

    Tollera la stringa nuda al posto della lista — i modelli la producono
    quando la voce è una sola — invece di buttare via il contenuto."""
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    cleaned = []
    for item in raw:
        if isinstance(item, (str, int, float)):
            text = str(item).strip()
        elif isinstance(item, dict):
            # Alcune risposte "impacchettano" comunque in oggetti: si prende
            # il testo invece di scartare la voce.
            text = str(item.get("text") or item.get("why") or item.get("name") or "").strip()
        else:
            continue
        if text:
            cleaned.append(text)
    return cleaned


def normalize_highlights(raw) -> list[dict]:
    """
    [AGGIUNTO 2026-07-31 — richiesta di Lorenzo: "piccola guida per un museo
    che spiega le opere principali al suo interno"] Ripulisce il campo
    OPZIONALE `highlights` (cosa guardare una volta dentro).

    Scelta deliberata — questo campo NON entra in `_REQUIRED_FIELDS` e una
    voce malformata viene scartata invece di far fallire l'intera guida: è un
    arricchimento, e una guida senza "cosa cercare dentro" resta una guida
    utile, mentre un'eccezione qui costerebbe al cliente anche la storia, i
    consigli pratici e la durata consigliata di quel POI. Vale il contrario
    per `practical_tips`, che è nel contratto minimo e infatti solleva.

    Accetta sia `{"name", "why"}` sia una stringa nuda (i modelli a volte
    "appiattiscono" le liste di oggetti): la stringa diventa
    `{"name": ..., "why": ""}` invece di essere buttata via.
    """
    if not isinstance(raw, list):
        return []
    cleaned: list[dict] = []
    for item in raw:
        if isinstance(item, dict):
            name = str(item.get("name") or "").strip()
            why = str(item.get("why") or "").strip()
        elif isinstance(item, str):
            name, why = item.strip(), ""
        else:
            continue
        if name:
            cleaned.append({"name": name, "why": why})
    return cleaned


def generate_poi_guide(
    poi_name: str,
    destination: str,
    api_key: str,
    objective_function: str | None = None,
    module_id: str | None = None,
    max_tokens: int = 9000,
    kind: str = "poi",
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

    [ALZATO 2026-07-31 a 6000] Lo schema ha ora anche `highlights` (3-6 voci
    con motivazione, vedi `normalize_highlights()`): senza margine ci si
    ritroverebbe di nuovo nello stesso troncamento del 12 luglio, e stavolta
    proprio sull'ultimo campo generato. Il troncamento resta comunque
    rilevato ed esplicito, non silenzioso — il margine serve a non farlo
    scattare, non a nasconderlo.

    [ALZATO 2026-08-02 a 9000] Terza volta che questo numero sale, e per la
    terza volta per lo stesso motivo: lo schema si è allargato (storia da 3-5
    paragrafi invece di 2-4, `highlights` fino a 8, più `curiosita`,
    `dintorni`, `errore_da_evitare`). Vale la pena dirlo per esteso, perché è
    il tipo di conto che si dimentica di fare: `max_tokens` è un TETTO, non
    un consumo — si paga il testo davvero generato, quindi alzarlo non costa
    nulla di per sé. Ciò che costa è il testo in più, ed è una scelta
    deliberata: le guide sono la voce che moltiplica il costo di un
    itinerario (una chiamata per luogo) e questo giro le allunga di circa il
    settanta per cento. Il conto onesto è in `claude/misura-costo-reale`.

    [AGGIUNTO 2026-08-02] Solleva `GuideSkipped` — sottoclasse a sé, NON di
    `GuideGeneratorError` — quando il modello dichiara di non riconoscere un
    luogo reale dietro la descrizione ricevuta (`kind="blocco"`). Il
    chiamante deve poterlo contare separatamente da un guasto.
    """
    import anthropic  # import locale: cosi il resto del modulo resta testabile senza il pacchetto

    client = anthropic.Anthropic(api_key=api_key)
    system_prompt = _load_system_prompt()
    user_message = build_guide_user_message(
        poi_name, destination, objective_function=objective_function,
        module_id=module_id, kind=kind,
    )

    response = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    # [AGGIUNTO 2026-08-01 — misura del costo reale] Una guida per ogni luogo
    # del programma: e' la voce che moltiplica il costo di un itinerario.
    cost_telemetry.record_llm(
        "claude-sonnet-5", getattr(response, "usage", None), label="guide turistiche"
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

    def _named_list(items, heading: str) -> str:
        body = ""
        for item in items or []:
            if not isinstance(item, dict) or not item.get("name"):
                continue
            why = f" — {item['why']}" if item.get("why") else ""
            body += f"- **{item['name']}**{why}\n"
        return f"## {heading}\n\n{body}\n" if body else ""

    highlights = _named_list(guide.get("highlights"), "Cosa cercare, una volta dentro")
    dintorni = _named_list(guide.get("dintorni"), "A due passi")
    curiosita = "".join(f"- {c}\n" for c in guide.get("curiosita") or [])
    curiosita = f"## Da sapere\n\n{curiosita}\n" if curiosita else ""
    errore = guide.get("errore_da_evitare")
    errore = f"## L'errore che fanno quasi tutti\n\n{errore}\n\n" if errore else ""
    return (
        f"# {guide['title']}\n\n"
        f"*Guida turistica: {guide['poi_name']}*\n\n"
        f"## Storia e contesto\n\n{guide['history_summary']}\n\n"
        f"{highlights}"
        f"{curiosita}"
        f"## Consigli pratici\n\n{tips}\n\n"
        f"{errore}"
        f"{dintorni}"
        f"## Quando visitare\n\n{guide['best_time_to_visit']}\n\n"
        f"## Durata consigliata della visita\n\n{guide['estimated_visit_duration']}\n\n"
        f"## Consiglio su misura per te\n\n{guide['consiglio_personalizzato']}\n\n"
        f"---\n*{guide['disclaimer']}*\n"
    )
