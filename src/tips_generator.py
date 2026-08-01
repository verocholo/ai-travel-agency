"""
NUOVO 2026-07-31 — "Consigli dell'Architetto" estesi + "Piani B se piove".

Richiesta letterale di Lorenzo:
  "manca tutta quella parte che ti avevo chiesto di inserire alla fine:
   architect'tips molto più articolato secondo direttrici ben precise:
   biglietti e prenotazioni, bagagli e logistica, risparmio e pagamenti,
   meteo luce e stagione, pratico e sicurezza, vita notturna, ecc... (vedi se
   aggiungerne altri standard per tutti e valuta tu caso per caso se inserirne
   altri personalizzati)"
  "manca la parte dei piani b se piove"

COME È COSTRUITA QUESTA SEZIONE
--------------------------------
Il campo `architect_tips` dell'itinerario esisteva già, ma era una lista piatta
di frasi generate insieme all'itinerario: nella pratica produceva 3-4 consigli
generici, perché nello stesso turno il modello sta risolvendo un problema di
ottimizzazione logistica e i consigli sono l'ultima cosa a cui dedica
attenzione. Qui la generazione è SEPARATA e STRUTTURATA per direttrici, che è
esattamente ciò che Lorenzo ha chiesto, ed è anche il motivo per cui funziona
meglio: una chiamata che ha come unico compito i consigli, con le categorie
imposte dall'esterno, non può "dimenticarsi" una direttrice.

LA DIVISIONE DEL LAVORO (il punto architetturale)
--------------------------------------------------
Un consiglio di viaggio è metà FATTO e metà GIUDIZIO, e le due metà hanno
requisiti di affidabilità opposti:

  - il FATTO (numero di emergenza, valuta, presa elettrica, ora del tramonto,
    stima dei costi) è calcolato in Python — `local_info`, `sun_times`,
    `cost_estimator` — e passato al modello dentro `[FATTI_VERIFICATI]` con
    l'istruzione di citarlo testualmente e di non aggiungerne di simili. Un
    numero di emergenza allucinato è il singolo errore più grave che questo
    documento possa contenere;
  - il GIUDIZIO ("il tuo terzo giorno è di domenica, sposta la colazione
    lunga a sabato") è il lavoro che solo il modello può fare, perché richiede
    di leggere l'itinerario nel suo insieme.

E la parte più delicata — quali luoghi al chiuso proporre se piove — NON è
lasciata al modello: le alternative sono estratte qui dai POI reali di
`DATI_API_FORNITI`, il modello può solo sceglierne tra quelle, e
`normalize_tips()` SCARTA in codice qualsiasi `poi_id` che non fosse nel
paniere. È la stessa Fedeltà RAG del Nodo 9, applicata a un contenuto nuovo:
un cliente sotto la pioggia che raggiunge un museo inventato è il peggior modo
possibile di scoprire che il documento non era affidabile.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from . import cost_telemetry
from .validator import parse_claude_output, ParseError

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


class TipsGeneratorError(Exception):
    """Sollevata se la chiamata a Claude fallisce, se l'output non è JSON
    valido o se non rispetta lo schema — mai un KeyError criptico a valle."""


# ---------------------------------------------------------------------------
# CATEGORIE
# ---------------------------------------------------------------------------
# Le prime sei sono le direttrici dettate da Lorenzo, con i suoi stessi nomi.
# Le successive sono le mie aggiunte "standard per tutti" (la sua richiesta
# diceva esplicitamente "vedi se aggiungerne altri standard per tutti"): ho
# scelto quelle che rispondono a una domanda che un viaggiatore si pone
# davvero il primo giorno e a cui oggi risponde cercando su internet — cioè
# quelle che tolgono lavoro al cliente, non quelle che allungano il documento.
# L'ultima, `su_misura`, è il "caso per caso personalizzato".
#
# `brief` non è documentazione: è il testo che finisce nel messaggio User e
# dice al modello cosa deve contenere quella sezione. Cambiarlo cambia
# l'output — è la vera specifica della categoria.
TIP_CATEGORIES: tuple[dict, ...] = (
    {
        "id": "biglietti_prenotazioni",
        "title": "Biglietti e prenotazioni",
        "brief": (
            "Cosa va prenotato PRIMA di partire e con quanto anticipo, cosa si può fare "
            "sul posto, cosa si salta con una prenotazione oraria. Nomina i luoghi "
            "specifici dell'itinerario che tipicamente richiedono prenotazione e i giorni "
            "in cui servono. Se un orario o un prezzo non ti è stato fornito non "
            "inventarlo: di' di verificarlo sul sito ufficiale."
        ),
    },
    {
        "id": "bagagli_logistica",
        "title": "Bagagli e logistica",
        "brief": (
            "Cosa mettere in valigia in funzione REALE di questo viaggio (stagione, tipo "
            "di attività previste, dislivelli, dress code di luoghi religiosi presenti "
            "nell'itinerario), e la logistica dei bagagli: dove lasciarli il giorno "
            "dell'arrivo prima del check-in e il giorno della partenza dopo il check-out, "
            "visto l'orario dei blocchi previsti in quelle due giornate."
        ),
    },
    {
        "id": "risparmio_pagamenti",
        "title": "Risparmio e pagamenti",
        "brief": (
            "Come si paga davvero in questo paese (contanti/carta, secondo i FATTI_VERIFICATI), "
            "dove si perdono soldi senza accorgersene (cambio valuta, commissioni, "
            "conversione dinamica in valuta all'ATM), e i risparmi concreti possibili su "
            "QUESTO itinerario: city pass sensato dato il numero di musei previsti, menù "
            "fisso a pranzo invece che a cena, giorni o fasce a ingresso ridotto se ne sei "
            "certo. Se ti è stata fornita la stima dei costi, commentala in relazione al "
            "budget dichiarato."
        ),
    },
    {
        "id": "meteo_luce_stagione",
        "title": "Meteo, luce e stagione",
        "brief": (
            "Cosa comporta viaggiare in QUESTE date in QUESTO posto: temperature e piogge "
            "tipiche della stagione, affollamento, festività o chiusure stagionali. Usa gli "
            "orari di alba e tramonto forniti nei FATTI_VERIFICATI per dire cose utili "
            "sull'ordine delle attività (quale belvedere o passeggiata cade nell'ora giusta, "
            "quale attività serale rischia il buio). Non dare MAI una previsione meteo: "
            "parla di clima tipico, non di che tempo farà."
        ),
    },
    {
        "id": "pratico_sicurezza",
        "title": "Pratico e sicurezza",
        "brief": (
            "Numero di emergenza, acqua del rubinetto, presa elettrica, documenti e "
            "assicurazione: usa SOLO i valori dei FATTI_VERIFICATI. Poi la sicurezza reale "
            "e non allarmistica, riferita ai luoghi e agli orari dell'itinerario (una zona "
            "che di sera cambia carattere, un rientro tardi, un trasferimento con bagagli). "
            "Niente paranoia generica: se non c'è nulla di specifico da segnalare, dillo."
        ),
    },
    {
        "id": "vita_notturna",
        "title": "Vita notturna",
        "brief": (
            "Come funziona la sera in questa città: a che ora si cena davvero, a che ora si "
            "esce, quali quartieri sono vivi e quali si spengono, cosa chiude presto. "
            "Aggancia il consiglio alle serate effettivamente libere dell'itinerario e alla "
            "posizione dell'alloggio (quanto è lontano il rientro)."
        ),
    },
    {
        "id": "trasporti_locali",
        "title": "Muoversi in città",
        "brief": (
            "Il pezzo che manca a ogni viaggiatore il primo giorno: come si arriva "
            "dall'aeroporto o dalla stazione all'alloggio, quale titolo di viaggio conviene "
            "davvero per il numero di giorni previsti, dove si comprano i biglietti, se si "
            "timbrano, come si prende un taxi in modo sicuro. Riferisciti alle distanze "
            "reali dell'itinerario."
        ),
    },
    {
        "id": "mangiare_locale",
        "title": "Mangiare come un locale",
        "brief": (
            "Gli orari veri dei pasti nel paese di destinazione (in molti posti sono "
            "incompatibili con le abitudini italiane), i due o tre piatti che ha senso "
            "mangiare proprio lì, e le trappole per turisti riconoscibili (menù tradotto in "
            "sei lingue, buttadentro, piazza principale). Rispetta le eventuali esigenze "
            "alimentari indicate nelle note del cliente."
        ),
    },
    {
        "id": "connettivita",
        "title": "Connettività, SIM e app utili",
        "brief": (
            "Come si sta connessi: roaming o eSIM in base al paese, dove c'è wifi pubblico "
            "affidabile, e le app che servono DAVVERO in questa destinazione (trasporti, "
            "taxi, pagamenti). Cita solo app di cui sei certo; niente elenchi generici."
        ),
    },
    {
        "id": "lingua_galateo",
        "title": "Lingua e galateo",
        "brief": (
            "Le cinque espressioni che cambiano la giornata nella lingua del posto (con la "
            "pronuncia scritta all'italiana), quanto si parla inglese, e le due o tre regole "
            "non scritte che un italiano rischia di violare senza saperlo (mancia secondo i "
            "FATTI_VERIFICATI, code, tono di voce, abbigliamento nei luoghi di culto "
            "presenti nell'itinerario)."
        ),
    },
    {
        "id": "salute_farmacie",
        "title": "Salute e farmacie",
        "brief": (
            "Tessera sanitaria europea o assicurazione a seconda del paese, come si trova "
            "una farmacia di turno, cosa portare nel beauty case in funzione delle attività "
            "previste. Nessuna indicazione medica: solo organizzazione pratica."
        ),
    },
    {
        "id": "fotografia",
        "title": "Fotografia e punti panoramici",
        "brief": (
            "Dove e QUANDO scattare: i punti panoramici raggiungibili dall'itinerario e "
            "l'ora giusta, usando l'orario dell'ora d'oro fornito nei FATTI_VERIFICATI. "
            "Segnala i luoghi dell'itinerario dove foto e treppiedi sono tipicamente "
            "vietati, se ne sei certo."
        ),
    },
    {
        "id": "su_misura",
        "title": "Su misura per te",
        "brief": (
            "I consigli che valgono per QUESTO cliente e per nessun altro: le sue note "
            "libere, il suo profilo di viaggio (objective_function), il suo budget, la "
            "composizione del gruppo. È la sezione in cui deve vedere che qualcuno ha letto "
            "davvero quello che ha scritto. Se le note sono vuote e non c'è nulla di "
            "distintivo, restituisci `tips` vuota invece di inventare un profilo."
        ),
    },
)

_CATEGORY_BY_ID = {c["id"]: c for c in TIP_CATEGORIES}

# La vita notturna non si propone a chi viaggia con bambini piccoli: non è
# prudenza, è pertinenza — occupa spazio che per quel cliente vale meno di
# zero. Il modulo verticale è il segnale forte; le note libere sono il
# ripiego, e volutamente cercano parole che indicano bambini PICCOLI.
_NIGHTLIFE_SKIP_MODULE_IDS = {"famiglia_con_bambini"}
_NIGHTLIFE_SKIP_HINTS = (
    "bambin", "bimb", "neonat", "passeggin", "figli piccoli", "mio figlio",
    "mia figlia", "nipotin", "culla", "seggiolon",
)

# POI al chiuso: piove e devi entrare da qualche parte. La lista è dei TIPI
# che il nostro stesso vocabolario (modules.py) può produrre — mai una
# deduzione dal nome del luogo, che sarebbe indovinare.
_INDOOR_TYPES = {
    "museum", "art_gallery", "aquarium", "library", "shopping_mall",
    "book_store", "movie_theater", "performing_arts_theater", "spa",
    "cafe", "restaurant", "bar", "church", "synagogue", "mosque",
    "hindu_temple", "tourist_attraction_indoor", "casino", "bowling_alley",
    "internet_cafe", "coworking_space", "business_center",
}
# Tipi esplicitamente all'aperto: servono a capire QUALI giornate hanno
# bisogno di un piano B, non a costruirlo.
_OUTDOOR_TYPES = {
    "park", "beach", "hiking_area", "national_park", "garden", "zoo",
    "campground", "marina", "plaza", "viewpoint", "amusement_park",
    "sports_complex", "stadium", "golf_course", "swimming_pool",
}


def select_categories(trip=None, module_id: str | None = None) -> list[dict]:
    """Le categorie da chiedere per QUESTO viaggio, nell'ordine di stampa.

    Deterministico e testabile: la scelta di cosa mostrare non è delegata al
    modello (che tenderebbe a produrre sempre tutto), sta qui in chiaro.
    """
    raw_notes = (getattr(trip, "raw_notes", "") or "").lower()
    skip_nightlife = module_id in _NIGHTLIFE_SKIP_MODULE_IDS or any(
        hint in raw_notes for hint in _NIGHTLIFE_SKIP_HINTS
    )
    return [
        c for c in TIP_CATEGORIES
        if not (c["id"] == "vita_notturna" and skip_nightlife)
    ]


# ---------------------------------------------------------------------------
# FATTI VERIFICATI (calcolati in Python, mai chiesti al modello)
# ---------------------------------------------------------------------------
def _iter_days(itinerary: dict):
    for day in (itinerary or {}).get("days") or []:
        if isinstance(day, dict):
            yield day


def _day_dates(trip, itinerary: dict) -> dict[int, date]:
    """Mappa numero-giorno → data reale. Vuota se `date_start` non è una data
    valida: senza data certa non si può parlare di stagione né di tramonto, e
    tacere è meglio che sbagliare di un giorno."""
    try:
        start = date.fromisoformat(str(getattr(trip, "date_start", ""))[:10])
    except (TypeError, ValueError):
        return {}
    out = {}
    for day in _iter_days(itinerary):
        number = day.get("day")
        if isinstance(number, int) and not isinstance(number, bool) and number >= 1:
            out[number] = start + timedelta(days=number - 1)
    return out


def build_light_facts(trip, itinerary: dict, hotels=None) -> list[dict]:
    """Alba/tramonto/ora d'oro per la prima, la mediana e l'ultima giornata.

    Non per tutte: in un viaggio di sei giorni il tramonto si sposta di pochi
    minuti, e tre righe dicono al modello tutto quello che gli serve senza
    sprecare contesto (e senza invitarlo a scrivere sei consigli sul sole).
    """
    from . import sun_times

    lat = getattr(trip, "dest_lat", None)
    lng = getattr(trip, "dest_lng", None)
    if lat is None or lng is None:
        for hotel in hotels or []:
            lat, lng = getattr(hotel, "lat", None), getattr(hotel, "lng", None)
            if lat is not None and lng is not None:
                break
    if lat is None or lng is None:
        return []

    dates = _day_dates(trip, itinerary)
    if not dates:
        return []
    numbers = sorted(dates)
    picked = sorted({numbers[0], numbers[len(numbers) // 2], numbers[-1]})

    facts = []
    for number in picked:
        light = sun_times.describe_light(dates[number], lat, lng)
        if not light.get("available"):
            continue
        facts.append({
            "day": number,
            "date": dates[number].isoformat(),
            "sunrise": light.get("sunrise", ""),
            "sunset": light.get("sunset", ""),
            "golden_evening_start": light.get("golden_evening_start", ""),
            "daylight_label": light.get("daylight_label", ""),
            "approximate": bool(light.get("approximate")),
        })
    return facts


def build_grounding_facts(trip, itinerary: dict, hotels=None, cost_summary: dict | None = None) -> dict:
    """Il blocco `[FATTI_VERIFICATI]`: tutto ciò che il modello NON deve pensare.

    Ogni chiave assente significa "non lo sappiamo", e il prompt istruisce il
    modello a non colmare il buco — l'omissione è un esito voluto, non un bug.
    """
    from . import local_info

    facts: dict = {}
    country = local_info.country_practical_info(getattr(trip, "destination", "") or "")
    if country:
        facts["paese"] = country

    light = build_light_facts(trip, itinerary, hotels=hotels)
    if light:
        facts["luce_del_giorno"] = light

    if isinstance(cost_summary, dict) and cost_summary.get("lines"):
        facts["stima_costi"] = {
            "totale_min_eur": round(cost_summary.get("total_min_eur", 0.0), 2),
            "totale_max_eur": round(cost_summary.get("total_max_eur", 0.0), 2),
            "budget_dichiarato_eur": cost_summary.get("budget_eur"),
            "verdetto": cost_summary.get("budget_verdict"),
            "voci_non_quantificate": cost_summary.get("unknown_count", 0),
            "nota": "Stima parziale: non include viaggio A/R, trasporti locali, acquisti, imprevisti.",
        }

    facts["date_viaggio"] = {
        "inizio": getattr(trip, "date_start", None),
        "fine": getattr(trip, "date_end", None),
        "giorni": getattr(trip, "duration_days", None),
    }
    return facts


# ---------------------------------------------------------------------------
# PIANI B: il paniere di alternative al chiuso (Fedeltà RAG)
# ---------------------------------------------------------------------------
def build_indoor_candidates(pois, itinerary: dict | None = None, limit: int = 25) -> list[dict]:
    """I POI REALI al chiuso tra cui il piano B può pescare.

    Preferisce i luoghi NON già usati nell'itinerario (proporre come piano B
    qualcosa che il cliente vedrà comunque martedì non è un piano B), ma non li
    esclude: se la città è piccola e il paniere è magro, un'anticipazione è
    meglio del nulla — e in coda, quindi il modello le sceglie per ultime.
    """
    used = set()
    for day in _iter_days(itinerary or {}):
        for block in day.get("blocks") or []:
            if isinstance(block, dict) and isinstance(block.get("poi_id"), str):
                used.add(block["poi_id"])

    fresh, already_used = [], []
    for poi in pois or []:
        poi_id = getattr(poi, "id", None)
        poi_type = getattr(poi, "type", None)
        if not isinstance(poi_id, str) or poi_type not in _INDOOR_TYPES:
            continue
        entry = {
            "poi_id": poi_id,
            "name": getattr(poi, "name", None) or poi_id,
            "type": poi_type,
            "price_level": getattr(poi, "price_level", None),
        }
        (already_used if poi_id in used else fresh).append(entry)
    return (fresh + already_used)[:limit]


def days_needing_rain_plan(itinerary: dict, pois) -> list[dict]:
    """Le giornate con almeno un blocco all'aperto — le uniche per cui un
    piano B ha senso. Il tipo del POI è un dato reale dell'API: non deduciamo
    "è all'aperto" dal nome dell'attività, che sarebbe indovinare."""
    poi_type_by_id = {
        getattr(p, "id", None): getattr(p, "type", None) for p in pois or []
    }
    out = []
    for day in _iter_days(itinerary):
        outdoor = []
        for block in day.get("blocks") or []:
            if not isinstance(block, dict):
                continue
            if poi_type_by_id.get(block.get("poi_id")) in _OUTDOOR_TYPES:
                outdoor.append(block.get("activity") or block.get("location") or "")
        if outdoor:
            out.append({
                "day": day.get("day"),
                "title": day.get("title"),
                "outdoor_blocks": [o for o in outdoor if o],
            })
    return out


# ---------------------------------------------------------------------------
# MESSAGGIO USER
# ---------------------------------------------------------------------------
def build_tips_user_message(
    trip,
    itinerary: dict,
    categories: list[dict],
    facts: dict,
    indoor_candidates: list[dict],
    outdoor_days: list[dict],
    objective_function: str | None = None,
    module_id: str | None = None,
) -> str:
    """Funzione pura (nessuna rete) — testabile senza API key, stessa
    convenzione di `build_guide_user_message` e `build_feedback_user_message`."""
    parts = [
        "[VIAGGIO]",
        json.dumps({
            "destinazione": getattr(trip, "destination", None),
            "date": [getattr(trip, "date_start", None), getattr(trip, "date_end", None)],
            "giorni": getattr(trip, "duration_days", None),
            "budget_eur": getattr(trip, "budget_eur", None),
            "budget_mode": getattr(trip, "budget_mode", None),
            "objective_function": objective_function or getattr(trip, "objective_function", None),
            "modulo": module_id,
            "note_del_cliente": getattr(trip, "raw_notes", "") or "",
        }, ensure_ascii=False, indent=2),
        "",
        "[ITINERARIO_GIÀ_DECISO — contesto, non modificarlo]",
        json.dumps(itinerary, ensure_ascii=False, indent=2),
        "",
        "[FATTI_VERIFICATI — calcolati fuori da te: citali testualmente, non aggiungerne di simili]",
        json.dumps(facts, ensure_ascii=False, indent=2),
        "",
        "[CATEGORIE_RICHIESTE — una sezione per ciascuna, con questi id esatti]",
        json.dumps(
            [{"category_id": c["id"], "titolo": c["title"], "cosa_contiene": c["brief"]} for c in categories],
            ensure_ascii=False, indent=2,
        ),
        "",
        "[GIORNATE_CON_ATTIVITÀ_ALL_APERTO — quelle che hanno bisogno di un piano B]",
        json.dumps(outdoor_days, ensure_ascii=False, indent=2),
        "",
        "[ALTERNATIVE_AL_CHIUSO_DISPONIBILI — l'UNICO paniere da cui puoi scegliere per i piani B]",
        json.dumps(indoor_candidates, ensure_ascii=False, indent=2),
        "",
        "Rispondi seguendo esattamente lo schema JSON descritto in [OUTPUT_CONTRACT].",
    ]
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# NORMALIZZAZIONE (dove la Fedeltà RAG viene fatta rispettare in codice)
# ---------------------------------------------------------------------------
def _clean_tip(value) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    return text or None


def normalize_tips(raw: dict, categories: list[dict], indoor_candidates: list[dict]) -> dict:
    """Da output del modello a struttura pronta per il PDF, applicando in
    CODICE le regole che il prompt può solo chiedere:

    - le sezioni escono nell'ordine deterministico di `categories`, non in
      quello (variabile) in cui il modello le ha scritte;
    - una `category_id` che non abbiamo richiesto viene scartata, non
      rinominata: se il modello si inventa una direttrice, non finisce nel
      documento del cliente;
    - uno `swap` con un `poi_id` che non è nel paniere viene ELIMINATO. È il
      controllo che rende la promessa "solo luoghi verificati" vera anche
      quando il modello sbaglia — la stessa logica del Nodo 9, qui applicata
      in modo silenzioso perché un piano B parziale è ancora utile, mentre un
      PDF bloccato per un consiglio accessorio no.

    Ritorna `{"sections": [...], "rain_plans": [...], "dropped_swaps": int}` —
    `dropped_swaps` esiste per essere loggato: se cresce, il prompt va corretto.
    """
    by_id = {}
    for section in (raw or {}).get("sections") or []:
        if not isinstance(section, dict):
            continue
        category_id = section.get("category_id")
        if not isinstance(category_id, str):
            continue
        tips = [t for t in (_clean_tip(x) for x in section.get("tips") or []) if t]
        if tips:
            by_id.setdefault(category_id, []).extend(tips)

    sections = []
    for category in categories:
        tips = by_id.get(category["id"])
        if tips:
            sections.append({
                "category_id": category["id"],
                "title": category["title"],
                "tips": tips,
            })

    allowed = {c["poi_id"]: c for c in indoor_candidates or [] if isinstance(c.get("poi_id"), str)}
    rain_plans, dropped = [], 0
    for plan in (raw or {}).get("rain_plans") or []:
        if not isinstance(plan, dict):
            continue
        summary = _clean_tip(plan.get("summary"))
        if not summary:
            continue
        swaps = []
        for swap in plan.get("swaps") or []:
            if not isinstance(swap, dict):
                continue
            poi_id = swap.get("poi_id")
            if not isinstance(poi_id, str) or poi_id not in allowed:
                dropped += 1
                continue
            swaps.append({
                "replaces": _clean_tip(swap.get("replaces")) or "",
                "poi_id": poi_id,
                "name": allowed[poi_id]["name"],
                "why": _clean_tip(swap.get("why")) or "",
            })
        day = plan.get("day")
        rain_plans.append({
            "day": day if isinstance(day, int) and not isinstance(day, bool) else None,
            "summary": summary,
            "swaps": swaps,
        })

    rain_plans.sort(key=lambda p: (p["day"] is None, p["day"] or 0))
    return {"sections": sections, "rain_plans": rain_plans, "dropped_swaps": dropped}


def _validate_tips_shape(raw) -> None:
    if not isinstance(raw, dict):
        raise TipsGeneratorError(
            f"L'output dei consigli non è un oggetto JSON (trovato {type(raw).__name__})."
        )
    sections = raw.get("sections")
    if not isinstance(sections, list) or not sections:
        raise TipsGeneratorError(
            f"'sections' deve essere una lista non vuota, ricevuto: {str(sections)[:300]}"
        )
    if "rain_plans" in raw and not isinstance(raw["rain_plans"], list):
        raise TipsGeneratorError(
            f"'rain_plans', se presente, deve essere una lista — ricevuto "
            f"{type(raw['rain_plans']).__name__}"
        )


def _load_system_prompt() -> str:
    return (PROMPTS_DIR / "system_prompt_tips.txt").read_text(encoding="utf-8")


def generate_architect_tips(
    trip,
    itinerary: dict,
    api_key: str,
    hotels=None,
    pois=None,
    cost_summary: dict | None = None,
    objective_function: str | None = None,
    module_id: str | None = None,
    max_tokens: int = 6000,
) -> dict:
    """Genera consigli e piani B. Ritorna la struttura di `normalize_tips()`.

    `max_tokens` è alto di proposito: sono fino a tredici sezioni più i piani
    B, ed è esattamente lo scenario in cui `guide_generator` si era già fatto
    troncare a metà JSON con un default troppo ottimista (CHANGELOG, fix del
    2026-07-12). Il troncamento è rilevato e sollevato esplicitamente.
    """
    import anthropic  # import locale: stessa convenzione degli altri moduli Claude

    categories = select_categories(trip, module_id=module_id)
    facts = build_grounding_facts(trip, itinerary, hotels=hotels, cost_summary=cost_summary)
    indoor_candidates = build_indoor_candidates(pois, itinerary)
    outdoor_days = days_needing_rain_plan(itinerary, pois)

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=max_tokens,
        system=_load_system_prompt(),
        messages=[{
            "role": "user",
            "content": build_tips_user_message(
                trip, itinerary, categories, facts, indoor_candidates, outdoor_days,
                objective_function=objective_function, module_id=module_id,
            ),
        }],
    )
    # [AGGIUNTO 2026-08-01 — misura del costo reale]
    cost_telemetry.record_llm(
        "claude-sonnet-5", getattr(response, "usage", None), label="consigli"
    )
    text = "".join(block.text for block in response.content if hasattr(block, "text"))

    if response.stop_reason == "max_tokens":
        raise TipsGeneratorError(
            f"Risposta di Claude troncata per i consigli dell'architetto: raggiunto "
            f"max_tokens={max_tokens} prima di completare il JSON. Aumenta max_tokens."
        )

    try:
        raw = parse_claude_output(text)
    except ParseError as e:
        raise TipsGeneratorError(
            f"Output di Claude per i consigli dell'architetto non è JSON valido: {e}"
        ) from e

    _validate_tips_shape(raw)
    return normalize_tips(raw, categories, indoor_candidates)


def render_tips_markdown(tips: dict) -> str:
    """Markdown di revisione interna — stesso stile degli altri renderer."""
    out = ["# Consigli dell'Architetto\n"]
    for section in tips.get("sections") or []:
        out.append(f"## {section['title']}\n")
        out.extend(f"- {tip}" for tip in section["tips"])
        out.append("")
    plans = tips.get("rain_plans") or []
    if plans:
        out.append("# Piani B se piove\n")
        for plan in plans:
            label = f"Giorno {plan['day']}" if plan.get("day") else "Piano B"
            out.append(f"## {label}\n")
            out.append(plan["summary"])
            for swap in plan.get("swaps") or []:
                replaces = f"al posto di {swap['replaces']}: " if swap["replaces"] else ""
                out.append(f"- {replaces}{swap['name']} — {swap['why']}")
            out.append("")
    return "\n".join(out)
