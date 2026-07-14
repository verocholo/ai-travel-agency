"""
NODO 5 — POI Radius Search. HTTP_MODULES_REALI.md §NODO 5.
Google Places API (New) — places:searchNearby.
"""
from __future__ import annotations
import requests
from .schemas import POI

SEARCH_NEARBY_URL = "https://places.googleapis.com/v1/places:searchNearby"

FIELD_MASK = (
    "places.id,places.displayName,places.location,places.types,"
    "places.primaryType,places.rating,places.priceLevel,"
    "places.regularOpeningHours,places.servesVegetarianFood"
)

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
    if not regular_opening_hours:
        return []
    days = set()
    for period in regular_opening_hours.get("periods", []):
        day_num = period.get("open", {}).get("day")
        if day_num is not None and day_num in _DOW_MAP:
            days.add(_DOW_MAP[day_num])
    return sorted(days)


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
    for item in data.get("places", []):
        primary_type = item.get("primaryType", "")
        try:
            poi_id = item["id"]
            lat = item["location"]["latitude"]
            lng = item["location"]["longitude"]
        except (KeyError, TypeError):
            skipped += 1
            continue
        pois.append(
            POI(
                id=poi_id,
                type=_normalize_type(primary_type),
                name=item.get("displayName", {}).get("text", "[Da Verificare]"),
                lat=lat,
                lng=lng,
                energy_tag=_energy_tag(primary_type),
                dietary_tags=(
                    ["vegetarian_verified:true"]
                    if item.get("servesVegetarianFood")
                    else []
                ),
                open_days=_open_days(item.get("regularOpeningHours")),
                affiliate_url="[Da Verificare]",
                price_level=_normalize_price_level(item.get("priceLevel")),
            )
        )
    if skipped:
        print(f"⚠️  map_places_response: {skipped} place scartati (schema inatteso: id/location mancanti)")
    return pois


_DEFAULT_INCLUDED_TYPES = ["restaurant", "tourist_attraction", "museum", "park"]


def fetch_nearby_raw(
    dest_lat: float, dest_lng: float, api_key: str,
    radius_m: int = 3000, max_results: int = 9,
    included_types: list[str] | None = None,
) -> dict:
    """[ESTRATTO 2026-07-10] Isola la sola chiamata HTTP, senza mapping —
    stesso principio già applicato a LiteAPI (debug_liteapi_raw.py):
    ispeziona il JSON reale prima di fidarti di map_places_response().

    [AGGIORNATO 2026-07-11] `included_types`: se omesso, usa ancora le 4
    categorie originali (`_DEFAULT_INCLUDED_TYPES`) — nessuna rottura per
    chi chiamava questa funzione prima. Il chiamante (oggi pipeline.py)
    passa le categorie del modulo verticale attivo (src/modules.py), che
    per "sport_active_travel" includono anche le categorie sportive."""
    body = {
        "includedTypes": included_types if included_types is not None else _DEFAULT_INCLUDED_TYPES,
        "maxResultCount": max_results,
        "rankPreference": "DISTANCE",
        "languageCode": "it",
        "locationRestriction": {
            "circle": {
                "center": {"latitude": dest_lat, "longitude": dest_lng},
                "radius": radius_m,
            }
        },
    }
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
) -> list[POI]:
    data = fetch_nearby_raw(dest_lat, dest_lng, api_key, radius_m, max_results, included_types)
    return map_places_response(data)
