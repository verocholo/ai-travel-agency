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
        # [AGGIUNTA 2026-08-01] Questa è la mia aggiunta più convinta, ed è
        # nata rileggendo il PDF reale: l'itinerario comincia alle 10:00 del
        # primo giorno e finisce alle 18:00 dell'ultimo, come se il cliente si
        # materializzasse in albergo e svanisse alla fine. Le due ore peggiori
        # di un viaggio — quelle in cui si è stanchi, carichi di valigie, in un
        # posto sconosciuto e senza ancora una SIM che funzioni — sono proprio
        # quelle che il documento non copriva. È anche il momento in cui si
        # spende peggio (il taxi preso "perché non sapevo come altro fare").
        "id": "arrivo_partenza",
        "title": "Arrivo e partenza",
        "brief": (
            "Le due ore che il documento non racconta mai: dal punto di arrivo "
            "(aeroporto, stazione, porto) fino alla porta dell'alloggio, e il "
            "percorso inverso il giorno della partenza. Di' concretamente quali "
            "sono le opzioni reali per QUESTA destinazione (navetta, treno, "
            "metropolitana, taxi ufficiale), quanto tempo va messo in conto, e "
            "quale conviene con l'orario e i bagagli previsti. Poi: cosa fare "
            "se si arriva prima del check-in e cosa fare nelle ore fra il "
            "check-out e la partenza, agganciandoti agli orari veri del primo e "
            "dell'ultimo giorno dell'itinerario. Se non conosci con certezza "
            "prezzi o frequenze, dillo e indica dove si verificano: mai un "
            "numero inventato su un trasferimento, perché è quello su cui il "
            "cliente rischia di perdere un aereo."
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

# ---------------------------------------------------------------------------
# ESPOSIZIONE AL METEO
# ---------------------------------------------------------------------------
# [RISCRITTO 2026-08-01 — la sezione "Piani B se piove" non poteva esistere]
#
# La versione precedente confrontava questi insiemi con `POI.type`. Ma `type`
# è il tipo NORMALIZZATO, e la normalizzazione (places_client._TYPE_NORMALIZE)
# collassa tutta la tassonomia di Google in quattro etichette: restaurant,
# museum, shopping, activity. Verificato eseguendo il codice, non leggendolo:
# l'intersezione fra `_OUTDOOR_TYPES` e i valori realmente possibili di
# `POI.type` era VUOTA. Non "raramente vuota": vuota per costruzione. Quindi
# `days_needing_rain_plan()` restituiva `[]` in ogni esecuzione possibile, il
# prompt riceveva zero giornate da coprire, e la sezione non è mai comparsa in
# nessun PDF. Il cliente l'ha notata come una mancanza; era un bug muto.
#
# Ora si ragiona sul `primary_type` GREZZO di Google (conservato in POI da
# oggi), con tre livelli di ripiego perché i payload vecchi — e quelli che
# arrivano da Make — non hanno quel campo:
#   1. `primary_type` grezzo, se c'è  → insiemi espliciti qui sotto;
#   2. euristica sul SLUG del tipo (vocabolario controllato di Google, non il
#      nome del luogo: dedurre da "botanical_garden" è leggere un'etichetta,
#      non indovinare);
#   3. tipo normalizzato: restaurant/museum/shopping ⇒ al chiuso,
#      `activity` ⇒ ESPOSTO.
#
# Il punto 3 è una scelta asimmetrica deliberata. Un falso positivo costa al
# cliente un paragrafo in più che non gli serviva. Un falso negativo lo lascia
# sotto la pioggia in una città che non conosce, con in mano un documento che
# gli aveva promesso di aver pensato a tutto. I due errori non hanno lo stesso
# prezzo, quindi non hanno la stessa soglia.
_INDOOR_RAW_TYPES = {
    # cultura e spettacolo al coperto
    "museum", "art_museum", "history_museum", "art_gallery", "art_studio",
    "auditorium", "performing_arts_theater", "movie_theater", "opera_house",
    "concert_hall", "planetarium", "aquarium", "library", "cultural_center",
    "visitor_center", "philharmonic_hall",
    # culto (quasi sempre visitabile al coperto)
    "church", "synagogue", "mosque", "hindu_temple", "place_of_worship",
    # ristorazione (il vocabolario completo è quello di places_client)
    "restaurant", "cafe", "bar", "bakery", "pub",
    # commercio al coperto
    "shopping_mall", "department_store", "book_store", "clothing_store",
    "cosmetics_store", "electronics_store", "furniture_store", "gift_shop",
    "home_goods_store", "jewelry_store", "shoe_store", "sporting_goods_store",
    "sportswear_store", "tea_store", "thrift_store", "toy_store",
    "womens_clothing_store",
    # benessere, lavoro, svago al coperto
    "spa", "sauna", "wellness_center", "casino", "bowling_alley",
    "internet_cafe", "coworking_space", "business_center", "conference_center",
    "fitness_center", "gym", "indoor_playground", "amusement_center",
    "ice_skating_rink", "banquet_hall", "night_club", "karaoke",
}
_OUTDOOR_RAW_TYPES = {
    # verde e natura
    "park", "national_park", "state_park", "dog_park", "garden",
    "botanical_garden", "picnic_ground", "campground", "camping_cabin",
    "hiking_area", "cycling_park", "off_roading_area", "skateboard_park",
    "wildlife_park", "wildlife_refuge", "zoo", "farm", "beach",
    # acqua e panorami
    "marina", "harbor", "pier", "viewpoint", "observation_deck",
    "water_park", "swimming_pool",
    # piazze, monumenti e luoghi civici all'aperto
    "plaza", "town_square", "monument", "fountain", "sculpture",
    "historical_landmark", "cultural_landmark", "historical_place",
    "cemetery", "bridge",
    # sport e intrattenimento all'aperto
    "stadium", "sports_complex", "athletic_field", "golf_course",
    "tennis_court", "amusement_park", "ferris_wheel", "roller_coaster",
    "go_karting_venue", "miniature_golf_course", "sports_activity_location",
    # mercati
    "market", "farmers_market", "flea_market",
    # la categoria-ombrello: nella pratica è dominata da piazze, belvedere e
    # monumenti. Esposta per default (vedi la nota sull'asimmetria sopra).
    "tourist_attraction",
}

# Frammenti di slug usati SOLO quando il tipo grezzo non è in nessuno dei due
# insiemi. L'ordine conta: si prova prima "al chiuso", perché un
# "shopping_mall_park" non esiste ma un "park_cafe" sì.
_INDOOR_SLUG_HINTS = (
    "museum", "gallery", "restaurant", "cafe", "coffee", "bar", "pub",
    "bakery", "store", "shop", "mall", "library", "theater", "theatre",
    "cinema", "spa", "gym", "hall", "center", "centre", "club", "hotel",
    "clinic", "school", "university",
)
_OUTDOOR_SLUG_HINTS = (
    "park", "beach", "garden", "trail", "hiking", "campground", "camping",
    "marina", "harbor", "plaza", "square", "viewpoint", "outdoor", "field",
    "lake", "river", "mountain", "island", "forest", "landmark", "monument",
    "stadium", "course", "court",
)

# Tipi normalizzati considerati al chiuso quando il tipo grezzo manca del tutto.
_INDOOR_NORMALIZED_TYPES = {"restaurant", "museum", "shopping"}


def weather_exposure(poi) -> str:
    """`"indoor"` | `"outdoor"` per un POI. Non ritorna mai "non lo so": vedi
    la nota sull'asimmetria — l'incertezza si risolve verso "esposto"."""
    raw = getattr(poi, "primary_type", None)
    if isinstance(raw, str) and raw.strip():
        slug = raw.strip().lower()
        if slug in _INDOOR_RAW_TYPES:
            return "indoor"
        if slug in _OUTDOOR_RAW_TYPES:
            return "outdoor"
        if any(hint in slug for hint in _INDOOR_SLUG_HINTS):
            return "indoor"
        if any(hint in slug for hint in _OUTDOOR_SLUG_HINTS):
            return "outdoor"
    normalized = getattr(poi, "type", None)
    if normalized in _INDOOR_NORMALIZED_TYPES:
        return "indoor"
    return "outdoor"


def is_indoor(poi) -> bool:
    return weather_exposure(poi) == "indoor"


def is_weather_exposed(poi) -> bool:
    return weather_exposure(poi) == "outdoor"


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
        # [AGGIORNATO 2026-08-01] la domanda "è al chiuso?" la pone
        # `weather_exposure()`, che guarda il `primaryType` GREZZO di Google e
        # solo in ultima istanza ricade sul tipo normalizzato. Confrontare qui
        # `poi.type` con una lista di slug era la ragione per cui il paniere
        # conteneva solo musei e ristoranti e mai un acquario, un teatro, una
        # libreria o un centro termale.
        if not isinstance(poi_id, str) or not is_indoor(poi):
            continue
        entry = {
            "poi_id": poi_id,
            "name": getattr(poi, "name", None) or poi_id,
            "type": getattr(poi, "primary_type", None) or poi_type,
            "price_level": getattr(poi, "price_level", None),
        }
        (already_used if poi_id in used else fresh).append(entry)
    return (fresh + already_used)[:limit]


def days_needing_rain_plan(itinerary: dict, pois) -> list[dict]:
    """Le giornate con almeno un blocco all'aperto — le uniche per cui un
    piano B ha senso. Il tipo del POI è un dato reale dell'API: non deduciamo
    "è all'aperto" dal nome dell'attività, che sarebbe indovinare.

    [AGGIORNATO 2026-08-01] la mappa porta il POI INTERO, non il suo tipo
    normalizzato: `weather_exposure()` ha bisogno del `primary_type` grezzo, e
    passargli solo `poi.type` era esattamente il motivo per cui questa funzione
    restituiva `[]` in ogni esecuzione possibile."""
    poi_by_id = {}
    for p in pois or []:
        pid = getattr(p, "id", None)
        if isinstance(pid, str):
            poi_by_id[pid] = p
    out = []
    for day in _iter_days(itinerary):
        outdoor = []
        for block in day.get("blocks") or []:
            if not isinstance(block, dict):
                continue
            poi = poi_by_id.get(block.get("poi_id"))
            if poi is not None and is_weather_exposed(poi):
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
    max_tokens: int = 16000,
    tentativi_massimi: int = 2,
) -> dict:
    """Genera consigli e piani B. Ritorna la struttura di `normalize_tips()`.

    `max_tokens` è alto di proposito: sono fino a quattordici sezioni più i
    piani B, ed è esattamente lo scenario in cui `guide_generator` si era già
    fatto troncare a metà JSON con un default troppo ottimista (CHANGELOG, fix
    del 2026-07-12). Il troncamento è rilevato e sollevato esplicitamente.

    [ALZATO DA 6000 A 16000 IL 2026-08-01 — e questo è il difetto, non il
    numero.] Nel PDF realmente venduto la sezione "Consigli dell'Architetto"
    conteneva tre righe generiche. Non perché il modello avesse poco da dire:
    perché con 6000 token si faceva troncare a metà JSON, l'eccezione di
    troncamento veniva sollevata correttamente qui — e poi INGHIOTTITA da un
    `except Exception` in `pdf_extras.py`, che ricadeva in silenzio sui tre
    bullet legacy dell'itinerario. Il cliente ha visto tre righe e ha concluso
    che il prodotto è povero; noi non abbiamo visto niente. Il costo del
    tetto più alto è zero finché non si usa (si paga l'output generato, non il
    massimo consentito); il costo di quello basso era l'intera sezione.
    Quattordici sezioni × ~250 token di media più i piani B stanno attorno ai
    5-7k reali: 16000 è margine, non spesa.

    [AGGIUNTO 2026-08-17 — task #229, secondo incidente identico al primo.]
    Un cliente ha ricevuto di nuovo tre righe generiche al posto di
    quattordici sezioni PIÙ i piani B, che sono spariti del tutto — stessa
    identica firma del guasto dell'1 agosto. Questa volta pero' il
    troncamento a max_tokens non c'entra (il tetto e' gia' a 16000): quello
    che manca qui e' un secondo tentativo. Una singola chiamata al modello
    che fallisce per una ragione transitoria — un errore di rete, un
    sovraccarico momentaneo dell'API, una risposta che quella particolare
    generazione non e' riuscita a rendere JSON valido — oggi arriva dritta
    al `except Exception` di `pdf_extras.py` e degrada IMMEDIATAMENTE, alla
    prima chiamata, senza che nessuno abbia mai riprovato.

    `tentativi_massimi` di proposito basso (2, non 5): un terzo tentativo
    costerebbe tempo dentro il tetto dei 300 secondi per chiamata che tutta
    la pipeline Make rispetta (vedi CHANGELOG dell'attesa intelligente), per
    un guadagno marginale — se due tentativi falliscono entrambi, il
    problema quasi certamente non è transitorio, e la terza chiamata
    costerebbe solo tempo aggiunto a un fallimento già deciso.
    """
    import anthropic  # import locale: stessa convenzione degli altri moduli Claude

    categories = select_categories(trip, module_id=module_id)
    facts = build_grounding_facts(trip, itinerary, hotels=hotels, cost_summary=cost_summary)
    indoor_candidates = build_indoor_candidates(pois, itinerary)
    outdoor_days = days_needing_rain_plan(itinerary, pois)
    messaggio_utente = build_tips_user_message(
        trip, itinerary, categories, facts, indoor_candidates, outdoor_days,
        objective_function=objective_function, module_id=module_id,
    )

    client = anthropic.Anthropic(api_key=api_key)
    ultimo_errore: Exception | None = None
    tentativi = max(1, int(tentativi_massimi))

    for tentativo in range(1, tentativi + 1):
        try:
            response = client.messages.create(
                model="claude-sonnet-5",
                max_tokens=max_tokens,
                system=_load_system_prompt(),
                messages=[{"role": "user", "content": messaggio_utente}],
            )
            # [AGGIUNTO 2026-08-01 — misura del costo reale] Registrata a ogni
            # tentativo, anche quelli poi scartati: la chiamata è stata fatta
            # e pagata, il tentativo successivo non la cancella.
            cost_telemetry.record_llm(
                "claude-sonnet-5", getattr(response, "usage", None), label="consigli"
            )
            text = "".join(block.text for block in response.content if hasattr(block, "text"))

            if response.stop_reason == "max_tokens":
                raise TipsGeneratorError(
                    f"Risposta di Claude troncata per i consigli dell'architetto: "
                    f"raggiunto max_tokens={max_tokens} prima di completare il JSON. "
                    f"Aumenta max_tokens."
                )

            try:
                raw = parse_claude_output(text)
            except ParseError as e:
                raise TipsGeneratorError(
                    f"Output di Claude per i consigli dell'architetto non è JSON "
                    f"valido: {e}"
                ) from e

            _validate_tips_shape(raw)
            return normalize_tips(raw, categories, indoor_candidates)

        except Exception as e:  # noqa: BLE001 — qualunque causa, si riprova una volta
            ultimo_errore = e
            if tentativo < tentativi:
                continue
            raise

    # Non dovrebbe mai arrivarci: il ciclo sopra o ritorna o rilancia. Se ci
    # arriva comunque (un domani `tentativi_massimi` diventasse 0 per un
    # bug altrove), meglio un errore leggibile che un `None` silenzioso.
    raise ultimo_errore or TipsGeneratorError("nessun tentativo eseguito")


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
