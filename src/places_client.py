"""
NODO 5 — POI Radius Search. HTTP_MODULES_REALI.md §NODO 5.
Google Places API (New) — places:searchNearby.
"""
from __future__ import annotations
import re

import requests

from . import cost_telemetry
from .schemas import POI

SEARCH_NEARBY_URL = "https://places.googleapis.com/v1/places:searchNearby"
PLACE_DETAILS_URL = "https://places.googleapis.com/v1/places/{place_id}"

# [AGGIORNATO 2026-07-31 — richiesta di Lorenzo: "per i ristoranti è utile che
# crei un collegamento con il menù del ristorante che spesso trovi su internet
# ed un altro collegamento con le info utili sul ristorante (indirizzo, numero,
# ecc...)"]
# Aggiunti `websiteUri`, `nationalPhoneNumber`, `formattedAddress`,
# `googleMapsUri`: campi REALI della Places API (New), semplicemente mai
# richiesti finora. Nota sui costi: il field mask determina la fascia di
# fatturazione della chiamata; questi quattro campi stanno nella fascia
# "Enterprise"/Contact già toccata da `regularOpeningHours`, quindi non
# spostano la chiamata in una fascia superiore a quella attuale. Il sito
# ufficiale è, nella pratica, la via più affidabile al menù di un ristorante
# (il menù non è un campo dell'API: non esiste, e non lo inventiamo — vedi
# src/place_links.py).
# [AGGIORNATO 2026-08-01 — collaudo PDF reale] Aggiunto `places.userRatingCount`.
# `places.rating` era già qui (quindi già pagato a ogni chiamata) ma non veniva
# mappato su POI: lo chiedevamo e lo buttavamo via. Da solo però un rating è un
# dato ingannevole — 5,0 stelle con due recensioni non è un'attrazione, è un
# rumore statistico. `userRatingCount` è il campo che rende il rating
# utilizzabile, sta nella stessa fascia di fatturazione (Pro) di `rating` e
# `priceLevel` già richiesti, quindi non sposta il costo della chiamata.
FIELD_MASK = (
    "places.id,places.displayName,places.location,places.types,"
    "places.primaryType,places.rating,places.userRatingCount,places.priceLevel,"
    "places.regularOpeningHours,places.servesVegetarianFood,"
    "places.websiteUri,places.nationalPhoneNumber,"
    "places.formattedAddress,places.googleMapsUri,"
    # [AGGIUNTO 2026-08-03 — task #181, richiesta di Lorenzo: «inserisci alcune
    # immagini con senso», «meno testo piu' immagini, non deve essere noioso»]
    # `places.photos` NON scarica nessuna immagine: restituisce il NOME della
    # foto e l'attribuzione del suo autore. E' un campo della fascia Pro, la
    # stessa gia' toccata da `rating` e `priceLevel` qui sopra, quindi non
    # sposta la fascia di fatturazione di questa chiamata: costo aggiuntivo
    # zero. La spesa vera arriva dopo, una foto alla volta, e la decide
    # `src/foto.py` con un tetto esplicito — vedi `fetch_place_photo`.
    "places.photos"
)

# Endpoint della singola foto. E' l'unico posto del progetto dove una chiamata
# a Google restituisce byte invece che JSON.
PLACE_PHOTO_URL = "https://places.googleapis.com/v1/{photo_ref}/media"

# Field mask per il Place Details di riparazione linguistica (vedi
# `repair_name_languages`): chiediamo il minimo indispensabile, perché il
# field mask determina la fascia di prezzo della chiamata e `displayName` da
# solo sta nella fascia Essentials (la più economica).
DETAILS_FIELD_MASK = "id,displayName"

# [AGGIORNATO 2026-07-10] Le tabelle originali riconoscevano solo un pugno di
# primaryType generici (es. "restaurant"). La prima chiamata reale su San
# Quirico d'Orcia ha mostrato che Google restituisce sottotipi molto più
# specifici anche quando la richiesta filtra su una categoria larga: una
# pizzeria è tornata con primaryType="pizza_restaurant", non "restaurant" —
# è caduta nel default (type=activity, energy_tag=MEDIUM) invece di essere
# riconosciuta come ristorante a basso carico. Tabelle espanse sulla
# tassonomia ufficiale completa (fonte:
# developers.google.com/maps/documentation/places/web-service/place-types,
# verificata 2026-07-10), non più su un elenco ipotizzato a mano.
#
# [AGGIORNATO 2026-07-11] Le categorie "Food and Drink" e "Culture" sono
# espanse per intero qui sotto. Le categorie "Sports" (tennis_court, gym,
# sports_complex, ecc.) e "Entertainment and Recreation" per famiglie
# (zoo, aquarium, water_park, ecc.) NON sono più hardcoded qui: vivono in
# src/modules.py come parte dei moduli "sport_active_travel" e
# "famiglia_con_bambini" — l'architettura "Nucleo Universale + Moduli
# Verticali" concordata con Lorenzo (vedi prototipo-status.md).
# fetch_nearby_raw()/search_nearby() qui sotto accettano ora un parametro
# `included_types` esplicito: se non passato, usano ancora le 4 categorie
# originali (comportamento invariato per compatibilità), ma pipeline.py
# passa oggi le categorie del modulo attivo — questo risolve il gap
# ENERGY_PACING segnalato in Fase 3 (nessun sottotipo Sports/Entertainment
# compariva mai con le sole 4 categorie originali).
# [AGGIUNTO 2026-07-11 — audit qualità pre-lancio] "deli" mancava dalla
# tabella ufficiale "Food and Drink" (unico omesso su 165+ voci, verificato
# per confronto diretto con la tassonomia ufficiale Google) — stesso tipo
# di gap già trovato e corretto per "pizza_restaurant": senza questa voce,
# una salumeria/gastronomia reale cadrebbe nel default (activity/MEDIUM)
# invece di (restaurant/LOW).
_FOOD_AND_DRINK_TYPES = [
    "acai_shop", "afghani_restaurant", "african_restaurant", "american_restaurant",
    "argentinian_restaurant", "asian_fusion_restaurant", "asian_restaurant",
    "australian_restaurant", "austrian_restaurant", "bagel_shop", "bakery",
    "bangladeshi_restaurant", "bar", "bar_and_grill", "barbecue_restaurant",
    "basque_restaurant", "bavarian_restaurant", "beer_garden", "belgian_restaurant",
    "bistro", "brazilian_restaurant", "breakfast_restaurant", "brewery", "brewpub",
    "british_restaurant", "brunch_restaurant", "buffet_restaurant", "burmese_restaurant",
    "burrito_restaurant", "cafe", "cafeteria", "cajun_restaurant", "cake_shop",
    "californian_restaurant", "cambodian_restaurant", "candy_store", "cantonese_restaurant",
    "caribbean_restaurant", "cat_cafe", "chicken_restaurant", "chicken_wings_restaurant",
    "chilean_restaurant", "chinese_noodle_restaurant", "chinese_restaurant",
    "chocolate_factory", "chocolate_shop", "cocktail_bar", "coffee_roastery",
    "coffee_shop", "coffee_stand", "colombian_restaurant", "confectionery",
    "croatian_restaurant", "cuban_restaurant", "czech_restaurant", "danish_restaurant",
    "deli", "dessert_restaurant", "dessert_shop", "dim_sum_restaurant", "diner", "dog_cafe",
    "donut_shop", "dumpling_restaurant", "dutch_restaurant", "eastern_european_restaurant",
    "ethiopian_restaurant", "european_restaurant", "falafel_restaurant", "family_restaurant",
    "fast_food_restaurant", "filipino_restaurant", "fine_dining_restaurant",
    "fish_and_chips_restaurant", "fondue_restaurant", "food_court", "french_restaurant",
    "fusion_restaurant", "gastropub", "german_restaurant", "greek_restaurant",
    "gyro_restaurant", "halal_restaurant", "hamburger_restaurant", "hawaiian_restaurant",
    "hookah_bar", "hot_dog_restaurant", "hot_dog_stand", "hot_pot_restaurant",
    "hungarian_restaurant", "ice_cream_shop", "indian_restaurant", "indonesian_restaurant",
    "irish_pub", "irish_restaurant", "israeli_restaurant", "italian_restaurant",
    "japanese_curry_restaurant", "japanese_izakaya_restaurant", "japanese_restaurant",
    "juice_shop", "kebab_shop", "korean_barbecue_restaurant", "korean_restaurant",
    "latin_american_restaurant", "lebanese_restaurant", "lounge_bar", "malaysian_restaurant",
    "meal_delivery", "meal_takeaway", "mediterranean_restaurant", "mexican_restaurant",
    "middle_eastern_restaurant", "mongolian_barbecue_restaurant", "moroccan_restaurant",
    "noodle_shop", "north_indian_restaurant", "oyster_bar_restaurant", "pakistani_restaurant",
    "pastry_shop", "persian_restaurant", "peruvian_restaurant", "pizza_delivery",
    "pizza_restaurant", "polish_restaurant", "portuguese_restaurant", "pub",
    "ramen_restaurant", "restaurant", "romanian_restaurant", "russian_restaurant",
    "salad_shop", "sandwich_shop", "scandinavian_restaurant", "seafood_restaurant",
    "shawarma_restaurant", "snack_bar", "soul_food_restaurant", "soup_restaurant",
    "south_american_restaurant", "south_indian_restaurant", "southwestern_us_restaurant",
    "spanish_restaurant", "sports_bar", "sri_lankan_restaurant", "steak_house",
    "sushi_restaurant", "swiss_restaurant", "taco_restaurant", "taiwanese_restaurant",
    "tapas_restaurant", "tea_house", "tex_mex_restaurant", "thai_restaurant",
    "tibetan_restaurant", "tonkatsu_restaurant", "turkish_restaurant", "ukrainian_restaurant",
    "vegan_restaurant", "vegetarian_restaurant", "vietnamese_restaurant",
    "western_restaurant", "wine_bar", "winery", "yakiniku_restaurant", "yakitori_restaurant",
]

_CULTURE_TYPES = [
    "art_gallery", "art_museum", "art_studio", "auditorium", "castle",
    "cultural_landmark", "fountain", "historical_place", "history_museum",
    "monument", "museum", "performing_arts_theater", "sculpture",
]

# [AGGIUNTO 2026-07-13 (ter) — richiesta di Lorenzo: "categoria shopping",
# confermata come miglioramento generale di prodotto via AskUserQuestion]
# Sottoinsieme CURATO della categoria ufficiale "Shopping"
# (developers.google.com/maps/documentation/places/web-service/place-types,
# verificata 2026-07-13 con fetch diretto della pagina, non ipotizzata a
# mano — stesso rigore già applicato a _FOOD_AND_DRINK_TYPES/_CULTURE_TYPES
# sopra). La tabella ufficiale include 43 tipi; qui ne includiamo solo
# quelli che un itinerario di VIAGGIO consiglierebbe davvero come
# attività/tappa (negozi/mercati che un turista visita per l'esperienza o
# per un acquisto specifico legato al viaggio) — deliberatamente ESCLUSI
# i negozi di uso quotidiano/utilitario che un residente frequenta per
# commissioni, non un cliente in vacanza: "asian_grocery_store",
# "auto_parts_store", "bicycle_store", "building_materials_store",
# "butcher_shop", "cell_phone_store", "convenience_store",
# "discount_store", "discount_supermarket", "food_store",
# "garden_center", "general_store", "grocery_store", "hardware_store",
# "health_food_store", "home_improvement_store", "hypermarket",
# "liquor_store", "pet_store", "store" (troppo generico/ambiguo),
# "supermarket", "warehouse_store", "wholesaler". Se le interviste di
# validazione mostrassero che i clienti vogliono comunque vedere
# supermercati/farmacie (es. per un viaggio lungo con autogestione), è
# un'estensione futura esplicita, non un'omissione silenziosa.
_SHOPPING_TYPES = [
    "book_store", "clothing_store", "cosmetics_store", "department_store",
    "electronics_store", "farmers_market", "flea_market", "furniture_store",
    "gift_shop", "home_goods_store", "jewelry_store", "market", "shoe_store",
    "shopping_mall", "sporting_goods_store", "sportswear_store", "tea_store",
    "thrift_store", "toy_store", "womens_clothing_store",
]

# Lookup energy_tag — HTTP_MODULES_REALI.md §NODO 5 "Lookup energy_tag"
_ENERGY_LOOKUP: dict[str, str] = {t: "LOW" for t in _FOOD_AND_DRINK_TYPES}
_ENERGY_LOOKUP.update({t: "LOW" for t in _CULTURE_TYPES})
# [AGGIUNTO 2026-07-13 (ter) — categoria shopping] MEDIUM su tutta la
# linea, coerente con "shopping_mall" già presente più sotto (stesso
# giudizio: camminare/curiosare tra negozi è un carico intermedio, né
# riposante come un pasto seduto né intenso come un'attività sportiva).
_ENERGY_LOOKUP.update({t: "MEDIUM" for t in _SHOPPING_TYPES})
_ENERGY_LOOKUP.update({
    "spa": "LOW", "aquarium": "LOW",
    "tourist_attraction": "MEDIUM", "park": "MEDIUM", "zoo": "MEDIUM",
    "shopping_mall": "MEDIUM", "church": "MEDIUM",
    "garden": "MEDIUM", "botanical_garden": "MEDIUM", "city_park": "MEDIUM",
    "national_park": "MEDIUM", "state_park": "MEDIUM", "plaza": "MEDIUM",
    "wildlife_park": "MEDIUM", "wildlife_refuge": "MEDIUM", "vineyard": "MEDIUM",
    "marina": "MEDIUM", "movie_theater": "MEDIUM", "observation_deck": "MEDIUM",
    "visitor_center": "MEDIUM", "golf_course": "MEDIUM", "swimming_pool": "MEDIUM",
    # [AGGIORNATO 2026-07-11] Prima "morti" perché l'unica richiesta a
    # Places non chiedeva mai categorie sportive (vedi nota sopra). Ora
    # richiedibili esplicitamente dal modulo "sport_active_travel"
    # (src/modules.py), quindi possono davvero comparire in dati reali.
    "hiking_area": "HIGH", "amusement_park": "HIGH", "gym": "HIGH",
    "stadium": "HIGH", "sports_complex": "HIGH", "tennis_court": "HIGH",
    "athletic_field": "HIGH", "fitness_center": "HIGH",
    "sports_activity_location": "HIGH", "sports_club": "HIGH",
    "ice_skating_rink": "HIGH",
    # [AGGIUNTO 2026-07-11] Modulo "famiglia_con_bambini" (src/modules.py).
    # Stesso principio ENERGY_PACING, riletto per un gruppo con bambini:
    # HIGH = giornata fisicamente/mentalmente intensa (code, camminate
    # lunghe, stimolazione alta), LOW = pausa/riposo, MEDIUM = via di
    # mezzo. ATTENZIONE — onestamente segnalato: a differenza delle
    # categorie sportive (dove "alto carico fisico" è quasi oggettivo),
    # qui la classificazione è un giudizio ragionevole ma non misurato
    # empiricamente (nessuna interviste/dato reale ancora raccolto su
    # famiglie) — "beach", "indoor_playground" e "ferris_wheel" in
    # particolare sono chiamate di merito discutibili, da rivedere se le
    # interviste di validazione (Mago di Oz) mostrano che non riflettono
    # l'esperienza reale.
    "amusement_center": "HIGH", "water_park": "HIGH",
    "go_karting_venue": "HIGH", "roller_coaster": "HIGH",
    "beach": "MEDIUM", "indoor_playground": "MEDIUM",
    "ferris_wheel": "MEDIUM",
    "miniature_golf_course": "LOW", "picnic_ground": "LOW",
    # [AGGIUNTO 2026-07-11] Modulo "lavoro_nomadi_digitali" (src/modules.py).
    # Ambienti di lavoro indoor, sedentari per definizione — LOW su tutta
    # la linea (nessuna ambiguità come per beach/indoor_playground sopra).
    "business_center": "LOW", "coworking_space": "LOW",
    "internet_cafe": "LOW", "library": "LOW",
})

# DOW_MAP (Google -> canonico) — HTTP_MODULES_REALI.md §NODO 6
_DOW_MAP = {0: "Sun", 1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri", 6: "Sat"}

_TYPE_NORMALIZE: dict[str, str] = {t: "restaurant" for t in _FOOD_AND_DRINK_TYPES}
_TYPE_NORMALIZE.update({t: "museum" for t in _CULTURE_TYPES})
# [AGGIUNTO 2026-07-13 (ter) — categoria shopping] Nuovo type normalizzato
# "shopping", distinto da "activity" (il fallback generico) — permette
# alle sezioni curate del documento cliente (pdf_renderer.py/renderer.py)
# di mostrare una sezione "Shopping" dedicata invece di far cadere questi
# POI nel generico "Cosa fare".
_TYPE_NORMALIZE.update({t: "shopping" for t in _SHOPPING_TYPES})


def _normalize_type(primary_type: str) -> str:
    return _TYPE_NORMALIZE.get(primary_type, "activity")


def _energy_tag(primary_type: str) -> str:
    return _ENERGY_LOOKUP.get(primary_type, "MEDIUM")


# [AGGIUNTO 2026-07-12 — richiesta di Lorenzo: "segnare ogni costo"]
# Valori enum verificati sulla documentazione ufficiale Places API (New)
# (developers.google.com/maps/documentation/places/web-service/reference/
# rest/v1/places, campo priceLevel) — non ipotizzati a mano, stesso rigore
# già applicato alle tabelle di primaryType sopra. "PRICE_LEVEL_UNSPECIFIED"
# e l'assenza del campo sono trattati identicamente (None, "non
# specificato"): Google stesso li tratta come equivalenti in questo campo.
_PRICE_LEVEL_PREFIX = "PRICE_LEVEL_"
_VALID_PRICE_LEVELS = {"FREE", "INEXPENSIVE", "MODERATE", "EXPENSIVE", "VERY_EXPENSIVE"}


def _normalize_price_level(raw: str | None) -> str | None:
    if not raw:
        return None
    value = raw[len(_PRICE_LEVEL_PREFIX):] if raw.startswith(_PRICE_LEVEL_PREFIX) else raw
    return value if value in _VALID_PRICE_LEVELS else None


def _open_days(regular_opening_hours: dict | None) -> list[str]:
    if not isinstance(regular_opening_hours, dict):
        return []
    days = set()
    # [AGGIORNATO 2026-07-31 — audit di perfezionamento, bug reale eseguito]
    # `regularOpeningHours: {"periods": null}` o un period `{"open": null}`
    # (campi presenti ma null nella risposta Google) crashavano con
    # TypeError/AttributeError, e la chiamata era FUORI dal try/except di
    # map_places_response → l'intero batch di POI andava perso. `or {}`/`or []`
    # coprono il null oltre all'assenza.
    for period in regular_opening_hours.get("periods") or []:
        if not isinstance(period, dict):
            continue
        day_num = (period.get("open") or {}).get("day")
        if day_num is not None and day_num in _DOW_MAP:
            days.add(_DOW_MAP[day_num])
    return sorted(days)


def _open_hours(regular_opening_hours: dict | None) -> dict | None:
    """Gli ORARI, non solo i giorni.

    [AGGIUNTO 2026-08-03 — task #180, richiesta di Lorenzo: «dare un criterio
    alla programmazione delle cose da vedere (minimizzare gli spostamenti,
    tenendo conto degli orari di apertura delle strutture e le varie pause
    durante la giornata)»]

    Fino a oggi di `regularOpeningHours` tenevamo soltanto l'insieme dei
    giorni (`_open_days`) e buttavamo via le ore. Il campo era gia' nel field
    mask, quindi era gia' PAGATO in ogni chiamata: la conseguenza e' che la
    regola «tieni conto degli orari di apertura» era impossibile da
    rispettare, perche' il modello che scrive l'itinerario non li aveva mai
    visti. Non era una regola disattesa: era una regola non formulabile.

    Forma: {"Mon": [["09:00", "19:00"]], ...}. Solo i giorni con almeno una
    finestra valida compaiono. Un locale aperto a cavallo della mezzanotte
    (`open.day` diverso da `close.day`) viene troncato a "23:59" del giorno di
    apertura invece di essere inventato sul giorno dopo: e' l'unica lettura
    che non puo' far arrivare qualcuno davanti a una porta chiusa.
    """
    if not isinstance(regular_opening_hours, dict):
        return None
    orari: dict[str, list[list[str]]] = {}
    for period in regular_opening_hours.get("periods") or []:
        if not isinstance(period, dict):
            continue
        apre = period.get("open") or {}
        chiude = period.get("close") or {}
        if not isinstance(apre, dict) or not isinstance(chiude, dict):
            continue
        giorno = _DOW_MAP.get(apre.get("day"))
        if giorno is None:
            continue
        inizio = _orario(apre)
        fine = _orario(chiude)
        if inizio is None:
            continue
        if fine is None or chiude.get("day") != apre.get("day"):
            # Aperto oltre la mezzanotte, oppure chiusura non dichiarata
            # (Google usa questa forma per i luoghi aperti 24 ore).
            fine = "23:59"
        if fine <= inizio:
            continue
        orari.setdefault(giorno, []).append([inizio, fine])
    if not orari:
        return None
    return {g: sorted(f) for g, f in sorted(orari.items())}


def _orario(punto) -> str | None:
    """"HH:MM" da {"hour": 9, "minute": 30}, oppure None se non e' un orario.

    [CORRETTO 2026-08-03, stesso giorno] Il controllo su `punto` non e'
    ridondante solo perche' oggi l'unico chiamante e' `_open_hours()`, che
    gia' scarta i periodi senza "open": questa funzione risponde a una
    risposta di un fornitore esterno, e la prossima persona che la richiama
    da un altro punto non ha modo di sapere che si aspetta un dizionario per
    forza. Una AttributeError qui dentro fa saltare l'intera ricerca dei POI,
    cioe' fa perdere il documento al cliente, per un campo null.
    """
    if not isinstance(punto, dict):
        return None
    ora = punto.get("hour")
    minuto = punto.get("minute", 0)
    if isinstance(ora, bool) or not isinstance(ora, int) or not 0 <= ora <= 23:
        return None
    if isinstance(minuto, bool) or not isinstance(minuto, int) or not 0 <= minuto <= 59:
        minuto = 0
    return f"{ora:02d}:{minuto:02d}"


def _clean_str(value) -> str | None:
    """[AGGIUNTO 2026-07-31] Un campo di contatto vale solo se è una stringa
    non vuota: qualunque altra cosa (None, numero, dict, stringa di soli spazi)
    diventa None, così `place_links.py` sa con certezza di dover ricadere sulla
    ricerca onesta invece di costruire un link rotto."""
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None


# ---------------------------------------------------------------- nomi dei POI
# [AGGIUNTO 2026-08-01 — collaudo del PDF reale, difetto 2 "nomi sporchi"]
#
# Nel primo itinerario venduto davvero comparivano, dentro il programma della
# giornata, cose come una ragione sociale completa di forma giuridica e un POI
# il cui unico nome era il proprio indirizzo. Sono entrambi nomi che Google
# restituisce onestamente — è quello che c'è scritto nella sua scheda — ma che
# in un documento pagato dal cliente si leggono come un errore, perché nessuno
# scrive "oggi pranzo da RISTORAZIONE ITALIA S.R.L. UNIPERSONALE".
#
# Il criterio guida di tutta questa sezione: PULIRE quando la pulizia è
# certa (una forma giuridica in coda è sempre rumore), SCARTARE quando il nome
# non identifica un luogo per un essere umano (un indirizzo, un numero), e non
# toccare NULLA in tutti gli altri casi. Un falso positivo qui — "Trattoria
# Sant'Anna" mutilata in "Trattoria" — sarebbe peggio del problema che stiamo
# risolvendo, quindi ogni regola qui sotto è deliberatamente conservativa e
# ancorata alla FINE della stringa.

# Forme giuridiche riconosciute in coda al nome. Le sigle ambigue di due o tre
# lettere (`spa` è anche una terme, `sa` è un nome proprio in molte lingue)
# sono ammesse SOLO nella variante puntata, che nessun nome commerciale reale
# usa per caso.
_LEGAL_SUFFIX_ALTERNATIVES = (
    r"s\.\s*r\.\s*l\.?\s*s?\.?",
    r"s\s*r\s*l\s*s?",
    r"s\.\s*p\.\s*a\.?",
    r"s\.\s*n\.\s*c\.?",
    r"s\s*n\s*c",
    r"s\.\s*a\.\s*s\.?",
    r"s\.\s*s\.\s*d\.?",
    r"s\.\s*a\.?",
    r"s\.\s*l\.?",
    r"b\.\s*v\.?",
    r"soc(?:iet[aà])?\.?\s*coop(?:erativa)?\.?(?:\s*a\s*r\.?\s*l\.?)?",
    r"societ[aà]\s+semplice",
    r"unipersonale",
    r"impresa\s+individuale",
    r"ditta\s+individuale",
    r"&\s*c\.?",
    r"ltd\.?", r"llc", r"inc\.?", r"gmbh", r"lda\.?", r"sarl", r"bvba",
)
# Il separatore è OBBLIGATORIO (`+`, non `*`) e sostituisce il `\b` che c'era
# prima. Due motivi, il secondo trovato da un test: (a) richiedere un
# separatore garantisce da solo che si stia tagliando un token intero e non la
# coda di una parola — "Bar Sports" non deve diventare "Bar Sport"; (b) `\b`
# NON funziona davanti a un'alternativa che inizia con un carattere non
# alfanumerico: in "Pizzeria Napoli & C." tra lo spazio e la "&" non esiste
# alcun confine di parola, quindi il suffisso "& C." non veniva mai rimosso.
_LEGAL_SUFFIX_RE = re.compile(
    r"[\s,\-–|]+(?:" + "|".join(_LEGAL_SUFFIX_ALTERNATIVES) + r")\s*$",
    re.IGNORECASE,
)

# Parole con cui inizia un indirizzo, non il nome di un luogo. Usate SOLO in
# combinazione con un numero civico in coda: "Piazza Navona" e "Corso Como"
# sono nomi veri e devono restare intatti, "Via Nazionale 47" no.
_STREET_PREFIX_RE = re.compile(
    r"^(?:via|viale|v\.le|corso|c\.so|piazza|p\.zza|piazzale|largo|vicolo|"
    r"lungomare|lungarno|strada|str|contrada|localit[aà]|"
    r"rua|avenida|av|calle|carrer|plaza|rue|boulevard|bd|"
    r"street|st|road|rd|avenue|ave|strasse|stra[sß]e)\b",
    re.IGNORECASE,
)
_TRAILING_NUMBER_RE = re.compile(r"[\s,]\d+[a-zA-Z]?\s*$")
_POSTCODE_RE = re.compile(r"\b\d{5}\b")
_HAS_LETTER_RE = re.compile(r"[^\W\d_]", re.UNICODE)
_WHITESPACE_RE = re.compile(r"\s+")

# Segnaposto che alcune schede usano al posto di un nome. Non sono nomi:
# scriverli nell'itinerario significherebbe far pagare al cliente una riga
# vuota travestita da tappa.
_NON_NAMES = frozenset({
    "n/a", "na", "n.d.", "nd", "unnamed", "senza nome", "sconosciuto",
    "unknown", "-", "--", "...", "?", "null", "none",
})


def _is_address_shaped(name: str) -> bool:
    """Vero se `name` è un indirizzo travestito da nome.

    Due firme, entrambe richieste in AND con qualcos'altro proprio per non
    colpire i nomi legittimi: un prefisso da odonimo seguito da un numero
    civico in coda, oppure un CAP a cinque cifre in mezzo alla stringa (che in
    un nome di luogo non compare mai, mentre in un indirizzo compare sempre).
    """
    if _POSTCODE_RE.search(name):
        return True
    return bool(_STREET_PREFIX_RE.match(name) and _TRAILING_NUMBER_RE.search(name))


def clean_poi_name(raw) -> str | None:
    """Normalizza il nome di un POI per un documento letto da un cliente.

    Restituisce il nome ripulito, oppure None se quel nome non identifica un
    luogo per un essere umano — nel qual caso il chiamante scarta il POI
    invece di stamparne uno inservibile. Non inventa mai un nome: se non c'è
    niente di buono da mostrare, la risposta è None, coerente con la Fedeltà
    RAG applicata in tutto il resto del prototipo.
    """
    if not isinstance(raw, str):
        return None
    name = _WHITESPACE_RE.sub(" ", raw).strip()
    if not name:
        return None
    # La rimozione è iterativa: "Alfa S.r.l. Unipersonale" ha due suffissi.
    for _ in range(3):
        stripped = _LEGAL_SUFFIX_RE.sub("", name).strip(" ,-–|")
        if stripped == name:
            break
        # Non svuotare mai il nome: se togliendo la forma giuridica non resta
        # niente (il nome ERA solo la forma giuridica), tieni l'originale e
        # lascia decidere ai controlli di scarto qui sotto.
        if not stripped:
            break
        name = stripped
    if name.casefold() in _NON_NAMES:
        return None
    if not _HAS_LETTER_RE.search(name):
        return None
    if _is_address_shaped(name):
        return None
    return name


# [AGGIUNTO 2026-08-01 — difetto 3 "nomi in lingua sbagliata"]
# Google allega a ogni `displayName` il suo `languageCode`. È il campo che
# permette di ACCORGERSI che un nome è tornato in una lingua diversa da quella
# richiesta — cosa che succede davvero e che nel collaudo reale ha prodotto un
# nome portoghese dentro un itinerario italiano. Non lo traduciamo noi: un
# toponimo tradotto a mano è un errore in agguato. Lo segnaliamo, e
# `repair_name_languages()` prova UNA riparazione mirata via Place Details.
def _display_name_language(item: dict) -> str | None:
    return _clean_str((item.get("displayName") or {}).get("languageCode"))


def _coerce_rating(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    rating = float(value)
    return rating if 0.0 < rating <= 5.0 else None


def _coerce_rating_count(value) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    count = int(value)
    return count if count >= 0 else None


def _foto_valide(item: dict) -> list:
    """Le fotografie del luogo che hanno un nome-risorsa valido, nell'ordine
    di rilevanza in cui Google le restituisce.

    [ESTRATTA 2026-08-17 — task #226, richiesta di Lorenzo: «foto diverse,
    non usare sempre le solite tre ripetute».] Prima questa lista si
    guardava una volta sola, per prendere SOLO la prima fotografia: bastava
    per la scheda della guida, ma lasciava senza risposta la domanda «e se
    lo stesso luogo serve una SECONDA immagine altrove nel documento?» — che
    e' esattamente il caso delle guide che si prestano fotografie a vicenda
    (`poi_pdf._altre_foto`): con un solo scatto disponibile per luogo, un
    itinerario di 5-6 tappe mostra la STESSA fotografia di uno stesso posto
    piu' volte in pagine diverse.
    """
    foto = item.get("photos")
    if not isinstance(foto, (list, tuple)):
        return []
    return [
        scatto for scatto in foto
        if isinstance(scatto, dict)
        and (_clean_str(scatto.get("name")) or "").startswith("places/")
    ]


def _photo_ref(item: dict, indice: int = 0) -> str | None:
    """Il nome-risorsa della fotografia all'INDICE dato, oppure None.

    Di proposito nell'ordine restituito da Google e non a caso: e' l'ordine
    di rilevanza, e la prima e' quella che vedresti aprendo la scheda del
    posto. Sceglierne una a caso per "varieta'" significherebbe stampare,
    ogni tanto, la foto del parcheggio.
    """
    valide = _foto_valide(item)
    if 0 <= indice < len(valide):
        nome = _clean_str(valide[indice].get("name"))
        if nome:
            return nome
    return None


def _photo_credit(item: dict, indice: int = 0) -> str | None:
    """L'attribuzione da stampare accanto alla fotografia all'INDICE dato,
    oppure None.

    Google chiede esplicitamente che le foto siano mostrate con il nome del
    loro autore. Non e' una formalita': la foto e' di una persona, e noi la
    stampiamo dentro un documento che vendiamo. Se l'attribuzione non c'e'
    questa funzione ritorna None, e la conseguenza a valle e' che la foto NON
    viene stampata affatto (`poi_pdf.build_guide_html`) — la pagina senza foto
    e' un peggioramento estetico, la foto senza il nome dell'autore e' un
    problema di un altro genere.
    """
    valide = _foto_valide(item)
    if not (0 <= indice < len(valide)):
        return None
    autori = valide[indice].get("authorAttributions")
    if not isinstance(autori, (list, tuple)):
        return None
    nomi = []
    for autore in autori:
        if not isinstance(autore, dict):
            continue
        nome = _clean_str(autore.get("displayName"))
        if nome:
            nomi.append(nome)
    if not nomi:
        return None
    return "Foto: " + ", ".join(nomi[:2]) + " / Google"


def fetch_place_photo(photo_ref: str, api_key: str, max_width_px: int = 800) -> bytes | None:
    """I byte dell'immagine di un luogo, oppure None se non si puo' averla.

    CHIAMATA A PAGAMENTO, una per foto: e' la ragione per cui non viene fatta
    qui in automatico per ogni POI trovato, ma solo dove `src/foto.py` decide
    che vale la pena, entro un tetto dichiarato.

    `max_width_px` non e' un dettaglio di qualita': e' meta' del costo del
    documento finale. La foto finisce dentro il PDF come base64, cioe' occupa
    un terzo in piu' dei suoi byte, moltiplicato per il numero di attrazioni.
    A 800 pixel una foto riempie la larghezza di una pagina stampata senza
    sgranare, e pesa un decimo dell'originale a 4000.

    Ritorna None — mai un'eccezione — su qualunque intoppo: senza rete,
    senza chiave, con una quota esaurita o con una risposta che non e'
    un'immagine. Una foto mancante deve costare una foto, non il documento.
    """
    if not photo_ref or not api_key:
        return None
    try:
        cost_telemetry.record_api_call("google_place_photo")
        resp = requests.get(
            PLACE_PHOTO_URL.format(photo_ref=photo_ref),
            params={"maxWidthPx": int(max_width_px), "key": api_key},
            timeout=15,
        )
        resp.raise_for_status()
        tipo = str(resp.headers.get("Content-Type") or "")
        if not tipo.startswith("image/"):
            return None
        contenuto = resp.content
        return contenuto if contenuto else None
    except Exception as e:  # noqa: BLE001 — vedi docstring
        print(f"⚠️  fetch_place_photo: foto non recuperata — {type(e).__name__}: {e}")
        return None


def map_places_response(data: dict) -> list[POI]:
    """Funzione pura — mapping [5.2]/[5.3] di HTTP_MODULES_REALI.md.

    [AGGIUNTO 2026-07-11 — audit qualità pre-lancio] Prima, un singolo
    place malformato nella risposta (es. manca "id" o "location") faceva
    fallire con un `KeyError` grezzo l'INTERA chiamata — un solo risultato
    sporco su 9 avrebbe buttato via l'intero batch di POI. Corretto per
    coerenza con lo stesso principio già applicato altrove nel prototipo
    (`liteapi_client.py::select_anchor_hotel` scarta una singola entry con
    schema inatteso invece di far fallire l'intera selezione): un place
    senza i campi minimi indispensabili (id, lat, lng) viene scartato e
    segnalato, il resto del batch resta utilizzabile.
    """
    pois = []
    skipped = 0
    rejected_names: list[str] = []
    for item in data.get("places", []) or []:
        # [AGGIORNATO 2026-07-31 — audit di perfezionamento, bug reale eseguito]
        # (1) l'INTERA costruzione del POI è ora dentro il try/except (prima
        # solo id/lat/lng lo erano): un `displayName: null` faceva
        # `None.get("text")` → AttributeError FUORI dal try, perdendo tutto il
        # batch, incluso il place valido già mappato. `(item.get("displayName")
        # or {})` copre il null; `AttributeError` aggiunto all'except come rete.
        # (2) `item` stesso non-dict (es. null nella lista places) viene saltato.
        if not isinstance(item, dict):
            skipped += 1
            continue
        primary_type = item.get("primaryType", "")
        try:
            poi_id = item["id"]
            lat = item["location"]["latitude"]
            lng = item["location"]["longitude"]
            # [AGGIORNATO 2026-08-01] Il nome passa da `clean_poi_name`. Se il
            # campo è ASSENTE o null si conserva il comportamento storico
            # ("[Da Verificare]": è un dato mancante, non un dato sbagliato).
            # Se invece il nome C'È ma è inservibile (un indirizzo, un numero,
            # un segnaposto), il POI viene scartato: meglio un POI in meno che
            # una riga dell'itinerario che il cliente non sa leggere.
            raw_name = (item.get("displayName") or {}).get("text")
            if raw_name is None:
                name = "[Da Verificare]"
            else:
                name = clean_poi_name(raw_name)
                if name is None:
                    rejected_names.append(str(raw_name)[:60])
                    skipped += 1
                    continue
            poi = POI(
                id=poi_id,
                type=_normalize_type(primary_type),
                name=name,
                lat=lat,
                lng=lng,
                energy_tag=_energy_tag(primary_type),
                dietary_tags=(
                    ["vegetarian_verified:true"]
                    if item.get("servesVegetarianFood")
                    else []
                ),
                open_days=_open_days(item.get("regularOpeningHours")),
                # [AGGIUNTO 2026-08-03 — task #180] Stesso campo, gia' pagato:
                # prima ne tenevamo solo i giorni.
                open_hours=_open_hours(item.get("regularOpeningHours")),
                affiliate_url="[Da Verificare]",
                price_level=_normalize_price_level(item.get("priceLevel")),
                # [AGGIUNTI 2026-07-31] `_clean_str` normalizza a None
                # qualunque valore non-stringa o vuoto: un campo presente ma
                # null non deve diventare la stringa "None" dentro un link.
                website=_clean_str(item.get("websiteUri")),
                phone=_clean_str(item.get("nationalPhoneNumber")),
                address=_clean_str(item.get("formattedAddress")),
                google_maps_uri=_clean_str(item.get("googleMapsUri")),
                rating=_coerce_rating(item.get("rating")),
                user_rating_count=_coerce_rating_count(item.get("userRatingCount")),
                name_language=_display_name_language(item),
                primary_type=_clean_str(primary_type),
                # [AGGIUNTI 2026-08-03 — task #181] Il nome della foto e il
                # nome di chi l'ha scattata. Nessuno dei due e' l'immagine:
                # l'immagine si scarica dopo, e solo per le attrazioni che
                # finiscono davvero nel documento.
                photo_ref=_photo_ref(item, 0),
                photo_credit=_photo_credit(item, 0),
                # [AGGIUNTI 2026-08-17 — task #226, «foto diverse, non le
                # solite ripetute»] La SECONDA fotografia, quando Google ne
                # restituisce piu' di una: costa zero in piu' qui (arriva
                # gratis nella stessa risposta), e serve a `src/foto.py` per
                # dare a un luogo che compare in piu' punti del documento
                # un'immagine diversa da quella gia' usata come sua di
                # apertura, invece di ripetere sempre lo stesso scatto.
                photo_ref_2=_photo_ref(item, 1),
                photo_credit_2=_photo_credit(item, 1),
            )
        except (KeyError, TypeError, AttributeError):
            skipped += 1
            continue
        pois.append(poi)
    if skipped:
        print(f"⚠️  map_places_response: {skipped} place scartati (schema inatteso: id/location mancanti)")
    if rejected_names:
        print(f"⚠️  map_places_response: nomi inservibili scartati → {rejected_names}")
    return pois


# ------------------------------------------------------- rilevanza e selezione
# [AGGIUNTO 2026-08-01 — collaudo del PDF reale, difetto 1 + densità]
#
# Il collaudo ha prodotto nove POI di cui sette ristoranti e due attrazioni: da
# lì in poi nessun prompt avrebbe potuto salvare la giornata, perché
# l'itinerario non può proporre visite che non ha. La causa non era il modello,
# era la richiesta: `rankPreference: "DISTANCE"` chiede a Google "dammi le cose
# PIÙ VICINE al punto", e le cose più vicine a un centroide urbano sono quasi
# sempre bar e ristoranti, non i monumenti, che stanno dove stanno.
# `POPULARITY` (il default di Google, che stavamo attivamente disattivando)
# chiede invece "dammi le cose che la gente cerca davvero lì".
_MIN_RATING_COUNT_FOR_TRUST = 15


def _relevance_key(poi: POI) -> tuple:
    """Chiave di ordinamento per rilevanza decrescente.

    Un luogo con molte recensioni e un voto alto viene prima di uno senza
    riscontri, a parità di tipo. Il conteggio pesa più del voto perché un 5,0
    con tre recensioni non dice nulla, mentre un 4,3 con quarantamila dice che
    quel posto esiste, è aperto e la gente ci va davvero.
    """
    count = poi.user_rating_count or 0
    rating = poi.rating or 0.0
    return (-min(count, 50000), -rating, poi.name or "")


def rank_by_relevance(pois: list[POI]) -> list[POI]:
    """Ordina i POI per rilevanza. Funzione pura, nessuna chiamata di rete."""
    return sorted(pois, key=_relevance_key)


def drop_low_signal(pois: list[POI], min_rating_count: int = _MIN_RATING_COUNT_FOR_TRUST) -> list[POI]:
    """Scarta i POI palesemente privi di riscontri, ma solo se ne resta
    abbastanza da lavorarci.

    La seconda metà di quella frase è la parte importante. In una destinazione
    piccola può essere del tutto normale che nessun luogo abbia quindici
    recensioni: applicare il filtro alla lettera lì significherebbe restituire
    zero POI e produrre un itinerario vuoto, cioè trasformare un filtro di
    qualità in un guasto. Se dopo il filtro resta meno della metà dei POI (o
    meno di sei in assoluto), il filtro si autoannulla e teniamo tutto.
    """
    if not pois:
        return []
    kept = [p for p in pois if (p.user_rating_count or 0) >= min_rating_count]
    if len(kept) < max(6, len(pois) // 2):
        return list(pois)
    return kept


_DEFAULT_INCLUDED_TYPES = ["restaurant", "tourist_attraction", "museum", "park"]

# [CAMBIATO 2026-08-01 — collaudo del PDF reale, difetto 1 "bolla geografica"]
# Era "DISTANCE". Vedi la nota estesa sopra `_relevance_key`: chiedere a Google
# i luoghi più VICINI a un punto, in una città, significa chiedergli i bar
# sotto casa; chiedergli i più RILEVANTI significa chiedergli i luoghi per cui
# quella città è quella città. "POPULARITY" è per altro il default dell'API:
# fino a oggi stavamo spendendo una riga di codice per disattivarlo.
DEFAULT_RANK_PREFERENCE = "POPULARITY"


def fetch_nearby_raw(
    dest_lat: float, dest_lng: float, api_key: str,
    radius_m: int = 3000, max_results: int = 9,
    included_types: list[str] | None = None,
    *,
    region_code: str | None = None,
    rank_preference: str = DEFAULT_RANK_PREFERENCE,
    language_code: str = "it",
) -> dict:
    """[ESTRATTO 2026-07-10] Isola la sola chiamata HTTP, senza mapping —
    stesso principio già applicato a LiteAPI (debug_liteapi_raw.py):
    ispeziona il JSON reale prima di fidarti di map_places_response().

    [AGGIORNATO 2026-07-11] `included_types`: se omesso (None), usa ancora le 4
    categorie originali (`_DEFAULT_INCLUDED_TYPES`) — nessuna rottura per
    chi chiamava questa funzione prima. Il chiamante (oggi pipeline.py)
    passa le categorie del modulo verticale attivo (src/modules.py), che
    per "sport_active_travel" includono anche le categorie sportive.

    [AGGIORNATO 2026-07-31 — audit di perfezionamento, bug reale eseguito]
    `included_types=[]` (lista vuota esplicita) ora significa "nessun filtro di
    tipo": il campo `includedTypes` viene OMESSO dal body, e Google restituisce
    place di qualsiasi tipo. Serviva per il controllo di freschezza dei POI
    (freshness_check.py): prima passava None credendo di non filtrare, ma None =
    default 4 categorie, quindi ogni POI dei moduli verticali (tennis_court,
    water_park, gym, ...) veniva sistematicamente segnalato "non trovato /
    forse chiuso" anche se aperto, perché quel filtro non poteva restituirlo."""
    body = {
        "maxResultCount": max_results,
        "rankPreference": rank_preference,
        "languageCode": language_code,
        "locationRestriction": {
            "circle": {
                "center": {"latitude": dest_lat, "longitude": dest_lng},
                "radius": radius_m,
            }
        },
    }
    # [AGGIUNTO 2026-08-01] `regionCode` dice a Google da quale paese guardare
    # il risultato: cambia le convenzioni di denominazione e la lingua di
    # ripiego quando il nome non esiste nella lingua richiesta. È il pezzo che
    # mancava dietro al difetto "nomi in lingua sbagliata". Omesso se il
    # chiamante non lo conosce — mai inventato.
    if region_code:
        body["regionCode"] = region_code
    if included_types is None:
        body["includedTypes"] = _DEFAULT_INCLUDED_TYPES
    elif len(included_types) > 0:
        body["includedTypes"] = included_types
    # included_types == [] → nessun filtro: campo omesso, tutti i tipi.
    cost_telemetry.record_api_call("google_places_nearby")
    resp = requests.post(
        SEARCH_NEARBY_URL,
        json=body,
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": FIELD_MASK,
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def search_nearby(
    dest_lat: float, dest_lng: float, api_key: str,
    radius_m: int = 3000, max_results: int = 9,
    included_types: list[str] | None = None,
    *,
    region_code: str | None = None,
    rank_preference: str = DEFAULT_RANK_PREFERENCE,
    language_code: str = "it",
) -> list[POI]:
    data = fetch_nearby_raw(
        dest_lat, dest_lng, api_key, radius_m, max_results, included_types,
        region_code=region_code, rank_preference=rank_preference,
        language_code=language_code,
    )
    return map_places_response(data)


# ------------------------------------------------- riparazione della lingua dei nomi

def fetch_place_details_raw(place_id: str, api_key: str, language_code: str = "it",
                            region_code: str | None = None) -> dict:
    """Place Details su un singolo place, field mask minima (`displayName`).

    Chiamata a pagamento (fascia Essentials, la più economica): il chiamante è
    responsabile di limitarne il numero — vedi il cap in
    `repair_name_languages()`.
    """
    params = {"languageCode": language_code}
    if region_code:
        params["regionCode"] = region_code
    cost_telemetry.record_api_call("google_place_details")
    resp = requests.get(
        PLACE_DETAILS_URL.format(place_id=place_id),
        params=params,
        headers={"X-Goog-Api-Key": api_key, "X-Goog-FieldMask": DETAILS_FIELD_MASK},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


MAX_LANGUAGE_REPAIRS = 3


def repair_name_languages(
    pois: list[POI], api_key: str, language_code: str = "it",
    region_code: str | None = None, max_repairs: int = MAX_LANGUAGE_REPAIRS,
) -> list[POI]:
    """Prova a recuperare il nome nella lingua giusta per i POI tornati in
    un'altra lingua.

    Onestà su cosa questa funzione può e non può fare. Se Google non possiede
    affatto una versione italiana di un toponimo, la seconda richiesta
    restituirà lo stesso nome della prima e il POI resterà com'è: è il
    comportamento corretto, perché il nome locale è quello scritto sui
    cartelli e sulla porta, e tradurlo a mano renderebbe il luogo più difficile
    da trovare, non più facile. Il caso che questa funzione risolve davvero è
    l'altro: la ricerca radiale che, per bias di posizione, ha restituito il
    nome in una TERZA lingua, né l'italiano né quella del posto — il difetto
    visto nel collaudo del 2026-08-01.

    Il cap a tre riparazioni è deliberato: oltre quella soglia non è più un
    caso isolato ma un problema sistemico della destinazione, che va guardato,
    non tamponato pagando decine di chiamate a itinerario.
    """
    if not api_key or max_repairs <= 0:
        return pois
    suspect = [
        p for p in pois
        if p.name_language and p.name_language.split("-")[0].lower() != language_code.split("-")[0].lower()
    ]
    if not suspect:
        return pois
    repaired = 0
    for poi in suspect:
        if repaired >= max_repairs:
            print(
                f"⚠️  repair_name_languages: {len(suspect) - repaired} nomi restano in lingua "
                f"diversa da '{language_code}' (cap di {max_repairs} riparazioni raggiunto)"
            )
            break
        try:
            data = fetch_place_details_raw(poi.id, api_key, language_code, region_code)
        except requests.exceptions.RequestException as e:
            print(f"⚠️  repair_name_languages: Place Details fallito per {poi.id}: {e}")
            continue
        new_name = clean_poi_name((data.get("displayName") or {}).get("text"))
        new_lang = _clean_str((data.get("displayName") or {}).get("languageCode"))
        repaired += 1
        if new_name and new_name != poi.name:
            print(f"ℹ️  Nome POI riparato: {poi.name!r} → {new_name!r} (lingua {poi.name_language!r} → {new_lang!r})")
            poi.name = new_name
            poi.name_language = new_lang
    return pois
