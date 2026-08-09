"""
NUOVO 2026-08-02 — task #167: "Vademecum di viaggio", valigia e bagaglio.

Richiesta di Lorenzo, alla lettera:

  "aggiungi una parte di «vademecum di viaggio» e di suggerimenti di cosa
   portare in valigia su come strutturarla, in base a dove si va e alla
   stagione (in base al clima e alle previsioni metereologiche) + per
   eventuali aerei low cost o quando venga richiesto quale tipologia di
   bagaglio conviene prendere (stiva o cabina) e il costo di quest'ultimo"

LA TENSIONE DA RISOLVERE, PRIMA DI SCRIVERE UNA RIGA DI CODICE
---------------------------------------------------------------
Lorenzo scrive "in base al clima E ALLE PREVISIONI METEOROLOGICHE". Ma il
prodotto ha già una regola opposta, scritta nel prompt dei consigli:
"Non dare MAI una previsione meteo: parla di clima tipico, non di che tempo
farà". Le due cose sembrano in conflitto. Non lo sono, e la ragione è banale
appena la si guarda in faccia: **una previsione meteo non esiste ancora**.

Il documento viene generato quando il cliente compila il form. Fra quel
momento e la partenza passano, tipicamente, settimane. Nessun servizio
meteorologico al mondo produce una previsione utile oltre i 10-14 giorni: ciò
che si trova a 30 giorni non è una previsione, è la media climatica travestita
da previsione. Stampare "il 14 settembre a Lisbona ci saranno 24° e sole"
dentro un PDF scritto ad agosto non è un servizio: è una bugia con l'aria di
un dato, e il cliente se ne accorge il giorno in cui piove.

Quindi la risposta onesta alla richiesta è una sola, ed è in due pezzi:

  1. Stampiamo il CLIMA TIPICO di quella destinazione in quel mese — un dato
     vero, stabile, verificabile, che serve esattamente a decidere cosa
     mettere in valigia (che è la domanda che Lorenzo sta ponendo).
  2. Diamo al cliente il modo di guardare la PREVISIONE VERA nel solo momento
     in cui esiste: un link, e la riga che gli dice quando aprirlo (tre giorni
     prima, non un mese prima) e cosa farne.

Il cliente ottiene entrambe le cose che ha chiesto Lorenzo. Nessuna delle due
è inventata. È la stessa soluzione che il prodotto applica già ai menù dei
ristoranti: mai un URL indovinato, ma una ricerca dichiarata come tale.

PERCHÉ TUTTO DETERMINISTICO (NESSUNA CHIAMATA A CLAUDE, NESSUNA RETE)
----------------------------------------------------------------------
Stessa logica di `local_info.py` e `predeparture.py`, per tre ragioni:

1. COSTO E LATENZA. La misura reale del 2026-08-01 dice che un itinerario
   costa 1,5056 € e che gira in 239-356 secondi contro un tetto di 300. Una
   sezione che non chiede niente a nessuno è una sezione che possiamo
   permetterci SEMPRE, anche nel giorno in cui il tetto ci morde.

2. VERIFICABILITÀ. Il conto dei cambi di vestiti e la fascia di prezzo di un
   bagaglio in stiva sono aritmetica: farli fare a un modello linguistico
   significa ottenere un risultato plausibile e non controllabile. È
   esattamente l'errore che il 2026-08-02 abbiamo appena finito di correggere
   in `pacing.py` — non lo rifacciamo il giorno stesso in un altro modulo.

3. ONESTÀ. Una tabella climatica scritta a mano si legge, si discute e si
   corregge in un punto solo. Una tabella climatica "ricordata" da un LLM è
   probabilmente giusta, e "probabilmente giusto" non è una categoria
   accettabile per il numero che decide se il cliente porta il cappotto.

LA REGOLA DI OMISSIONE, IDENTICA AL RESTO DEL PRODOTTO
--------------------------------------------------------
Destinazione non riconoscibile ⇒ niente scheda clima, e la valigia resta sui
soli consigli universali. Data non leggibile ⇒ niente mese, niente stagione.
Mai un valore di ripiego inventato per far sembrare la sezione più piena.
"""
from __future__ import annotations

from datetime import date
from urllib.parse import quote_plus

from . import local_info
from . import sun_times

GOOGLE_SEARCH_URL = "https://www.google.com/search"

# Data dell'ultima revisione a mano delle fasce di prezzo dei bagagli. Viene
# STAMPATA nel documento: un prezzo senza la data a cui si riferisce è un
# prezzo di cui il cliente non può giudicare l'affidabilità.
BAGGAGE_PRICES_UPDATED = "agosto 2026"

MONTH_NAMES = (
    "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
    "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre",
)

# --- Il clima tipico, per zona e per mese --------------------------------
#
# Ogni riga è (temperatura minima media, temperatura massima media, pioggia).
# Sono MEDIE MENSILI di lungo periodo, non previsioni, e il documento lo dice
# al cliente con queste parole esatte. Le zone sono sette perché sette è il
# numero minimo che tiene distinte situazioni che cambiano davvero il
# contenuto della valigia: sotto questo numero il gennaio di Siviglia e quello
# di Berlino finiscono nella stessa riga, e la riga diventa inutile.
#
# I livelli di pioggia sono qualitativi apposta: "12 giorni di pioggia al mese"
# suona più preciso e serve a meno di "frequente", perché nessuno mette in
# valigia 12 giorni di pioggia — ci si mette, o non ci si mette, l'impermeabile.
_RAIN_RARE = "raro"
_RAIN_POSSIBLE = "possibile"
_RAIN_FREQUENT = "frequente"
_RAIN_VERY_LIKELY = "molto probabile"

_CLIMATE_ZONES: dict[str, dict] = {
    "subtropicale": {
        "label": "oceanico subtropicale",
        "months": [
            (15, 21, _RAIN_POSSIBLE), (15, 21, _RAIN_POSSIBLE),
            (15, 22, _RAIN_POSSIBLE), (16, 23, _RAIN_RARE),
            (17, 24, _RAIN_RARE), (19, 26, _RAIN_RARE),
            (21, 28, _RAIN_RARE), (21, 29, _RAIN_RARE),
            (21, 28, _RAIN_RARE), (20, 26, _RAIN_POSSIBLE),
            (18, 24, _RAIN_POSSIBLE), (16, 22, _RAIN_POSSIBLE),
        ],
        "note": (
            "Le temperature qui cambiano pochissimo fra inverno ed estate: è "
            "il vento, non il mese, a decidere come ci si sente."
        ),
    },
    "mediterraneo": {
        "label": "mediterraneo",
        "months": [
            (4, 13, _RAIN_FREQUENT), (5, 14, _RAIN_FREQUENT),
            (7, 17, _RAIN_POSSIBLE), (9, 20, _RAIN_POSSIBLE),
            (13, 25, _RAIN_POSSIBLE), (17, 29, _RAIN_RARE),
            (20, 32, _RAIN_RARE), (20, 32, _RAIN_RARE),
            (17, 28, _RAIN_POSSIBLE), (13, 23, _RAIN_FREQUENT),
            (8, 17, _RAIN_FREQUENT), (5, 14, _RAIN_FREQUENT),
        ],
        "note": (
            "L'estate mediterranea non è calda in modo uniforme: fra le 13 e "
            "le 17 il sole sulle pietre è il vero motivo per cui le piazze si "
            "svuotano, e non è una questione di gusto."
        ),
    },
    "temperato_sud": {
        "label": "temperato di pianura interna",
        "months": [
            (-1, 7, _RAIN_FREQUENT), (1, 10, _RAIN_POSSIBLE),
            (4, 15, _RAIN_POSSIBLE), (8, 19, _RAIN_FREQUENT),
            (13, 24, _RAIN_FREQUENT), (17, 28, _RAIN_POSSIBLE),
            (19, 31, _RAIN_RARE), (19, 30, _RAIN_POSSIBLE),
            (15, 26, _RAIN_POSSIBLE), (10, 19, _RAIN_FREQUENT),
            (5, 12, _RAIN_FREQUENT), (0, 7, _RAIN_FREQUENT),
        ],
        "note": (
            "Pianura interna: d'estate il caldo è umido e non cala la sera, "
            "d'inverno l'umidità fa percepire qualche grado in meno di quelli "
            "che segna il termometro."
        ),
    },
    "atlantico": {
        "label": "oceanico atlantico",
        "months": [
            (2, 7, _RAIN_VERY_LIKELY), (2, 8, _RAIN_FREQUENT),
            (4, 12, _RAIN_FREQUENT), (6, 15, _RAIN_FREQUENT),
            (9, 19, _RAIN_FREQUENT), (12, 22, _RAIN_POSSIBLE),
            (14, 24, _RAIN_POSSIBLE), (14, 24, _RAIN_POSSIBLE),
            (11, 21, _RAIN_FREQUENT), (8, 16, _RAIN_FREQUENT),
            (5, 11, _RAIN_VERY_LIKELY), (3, 8, _RAIN_VERY_LIKELY),
        ],
        "note": (
            "Clima oceanico: raramente fa molto freddo o molto caldo, ma la "
            "pioggia arriva e passa più volte nella stessa giornata. Qui "
            "l'impermeabile leggero batte l'ombrello grande, sempre."
        ),
    },
    "continentale": {
        "label": "continentale",
        "months": [
            (-3, 3, _RAIN_FREQUENT), (-2, 5, _RAIN_FREQUENT),
            (1, 10, _RAIN_POSSIBLE), (5, 16, _RAIN_POSSIBLE),
            (9, 21, _RAIN_FREQUENT), (13, 24, _RAIN_FREQUENT),
            (15, 26, _RAIN_FREQUENT), (15, 26, _RAIN_FREQUENT),
            (11, 21, _RAIN_POSSIBLE), (6, 15, _RAIN_POSSIBLE),
            (2, 8, _RAIN_FREQUENT), (-1, 4, _RAIN_FREQUENT),
        ],
        "note": (
            "Clima continentale: l'inverno è secco e pungente, l'estate ha "
            "temporali brevi e violenti di pomeriggio. Fra le due stagioni "
            "cambia tutto, anche a poche settimane di distanza."
        ),
    },
    "nordico": {
        "label": "nordico",
        "months": [
            (-6, 0, _RAIN_FREQUENT), (-6, 1, _RAIN_FREQUENT),
            (-3, 5, _RAIN_POSSIBLE), (1, 11, _RAIN_POSSIBLE),
            (6, 17, _RAIN_POSSIBLE), (10, 21, _RAIN_POSSIBLE),
            (13, 23, _RAIN_FREQUENT), (12, 21, _RAIN_FREQUENT),
            (8, 16, _RAIN_FREQUENT), (3, 9, _RAIN_FREQUENT),
            (-1, 4, _RAIN_FREQUENT), (-4, 1, _RAIN_FREQUENT),
        ],
        "note": (
            "Alle latitudini nordiche la lunghezza della giornata pesa più "
            "della temperatura: a dicembre il buio arriva a metà pomeriggio, a "
            "giugno non arriva quasi mai."
        ),
    },
    "alpino": {
        "label": "alpino d'alta quota",
        "months": [
            (-8, 2, _RAIN_FREQUENT), (-7, 4, _RAIN_FREQUENT),
            (-4, 8, _RAIN_POSSIBLE), (0, 13, _RAIN_POSSIBLE),
            (4, 18, _RAIN_FREQUENT), (8, 21, _RAIN_FREQUENT),
            (10, 24, _RAIN_FREQUENT), (10, 23, _RAIN_FREQUENT),
            (6, 19, _RAIN_POSSIBLE), (2, 13, _RAIN_POSSIBLE),
            (-3, 7, _RAIN_FREQUENT), (-6, 3, _RAIN_FREQUENT),
        ],
        "note": (
            "In quota il tempo cambia in un'ora e la temperatura cala di "
            "circa 6 gradi ogni mille metri di dislivello: la giacca serve "
            "anche a Ferragosto, e serve davvero."
        ),
    },
}

# Paese (chiave di `local_info`) → zona climatica di partenza.
_COUNTRY_ZONE = {
    "italia": "mediterraneo",
    "francia": "atlantico",
    "spagna": "mediterraneo",
    "portogallo": "mediterraneo",
    "germania": "continentale",
    "austria": "continentale",
    "paesi bassi": "atlantico",
    "belgio": "atlantico",
    "grecia": "mediterraneo",
    "croazia": "mediterraneo",
    "regno unito": "atlantico",
    "irlanda": "atlantico",
    "svizzera": "continentale",
    "danimarca": "nordico",
    "svezia": "nordico",
    "norvegia": "nordico",
    "repubblica ceca": "continentale",
    "polonia": "continentale",
    "ungheria": "continentale",
    "slovenia": "continentale",
}

# Correzioni per latitudine, applicate SOLO ai paesi che attraversano davvero
# più di una zona e SOLO quando `dest_lat` esiste (il geocoding la popola, ma
# non è garantita). Sono poche apposta: ogni riga qui è una cosa in più che
# può sbagliare, e una zona climatica sbagliata è peggio di una zona generica.
#   (paese, latitudine di soglia, "sopra"|"sotto", zona)
_LAT_OVERRIDES = (
    # Il nord Italia (Milano, Torino, Bologna, Verona) non ha il clima di Roma:
    # la pianura padana ha inverni nettamente più rigidi ed estati più afose.
    ("italia", 44.2, "sopra", "temperato_sud"),
    # La costa mediterranea francese (Nizza, Marsiglia, Cannes) non ha il clima
    # di Parigi.
    ("francia", 44.0, "sotto", "mediterraneo"),
    # Canarie (28°) e la costa cantabrica (Bilbao, San Sebastián, 43°+) sono i
    # due estremi della Spagna.
    ("spagna", 31.0, "sotto", "subtropicale"),
    ("spagna", 42.8, "sopra", "atlantico"),
    # Madeira (32,6°) è oceanica subtropicale, Lisbona no.
    ("portogallo", 34.0, "sotto", "subtropicale"),
    # Zagabria (45,8°) è entroterra continentale, la costa dalmata no.
    ("croazia", 45.4, "sopra", "temperato_sud"),
    # Le Highlands scozzesi (57°+) non hanno il clima di Londra.
    ("regno unito", 56.5, "sopra", "nordico"),
)

# Destinazioni di alta quota: il nome, da solo, dice che si va in montagna.
# Elenco volutamente corto e conservativo — vale la stessa regola di
# ammissione di `_CITY_TO_COUNTRY` in `local_info.py`.
_ALPINE_HINTS = (
    "cortina", "courmayeur", "chamonix", "zermatt", "st moritz", "saint moritz",
    "grindelwald", "interlaken", "engadina", "innsbruck", "tirolo", "hallstatt",
    "livigno", "madonna di campiglio", "val gardena", "dolomiti", "sestriere",
    "bormio", "cervinia", "alpe d'huez", "val thorens", "zakopane",
)


def _get(obj, name, default=None):
    """Legge un campo sia da un oggetto (`Trip`, `POI`) sia da un dizionario.

    Il `trip` arriva come oggetto da `pdf_extras` e come dizionario da
    `pdf_renderer`: una funzione che ne accetta una sola forma funziona in
    metà del prodotto e fallisce in silenzio nell'altra metà (è già successo,
    vedi `predeparture._attr`).
    """
    if isinstance(obj, dict):
        value = obj.get(name, default)
    else:
        value = getattr(obj, name, default)
    return default if value is None else value


def _as_float(value):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result:  # NaN: l'unico valore diverso da se stesso.
        return None
    return result


def _parse_date(value) -> date | None:
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def resolve_climate_zone(trip) -> str | None:
    """La zona climatica di questo viaggio, o `None` se non è determinabile.

    Ordine, dal segnale più esplicito al più debole:
      1. il nome della destinazione dice "montagna" (Cortina, Zermatt…);
      2. il paese, risolto dalla stessa tabella che alimenta la scheda
         pratica — così clima e numero di emergenza non possono mai riferirsi
         a due paesi diversi;
      3. la latitudine, ma solo come CORREZIONE del punto 2 e solo per i
         pochi paesi che attraversano davvero più zone.
    """
    destination = _get(trip, "destination", "") or ""
    text = " ".join(str(destination).strip().lower().split())
    for hint in _ALPINE_HINTS:
        if hint in text:
            return "alpino"

    country = local_info.resolve_country(destination)
    if country is None:
        return None
    zone = _COUNTRY_ZONE.get(country)
    if zone is None:
        return None

    lat = _as_float(_get(trip, "dest_lat"))
    if lat is not None:
        for override_country, threshold, direction, override_zone in _LAT_OVERRIDES:
            if override_country != country:
                continue
            if direction == "sopra" and lat >= threshold:
                zone = override_zone
            elif direction == "sotto" and lat <= threshold:
                zone = override_zone
    return zone


def _season_label(month: int) -> str:
    if month in (12, 1, 2):
        return "inverno"
    if month in (3, 4, 5):
        return "primavera"
    if month in (6, 7, 8):
        return "estate"
    return "autunno"


def forecast_link(trip) -> dict | None:
    """Una RICERCA dichiarata come tale, mai un URL di previsione indovinato.

    Stesso principio di `place_links`: se non abbiamo l'indirizzo esatto della
    pagina giusta, diamo al cliente la ricerca che la trova, e gli diciamo che
    è una ricerca.
    """
    destination = str(_get(trip, "destination", "") or "").strip()
    if not destination:
        return None
    query = f"meteo {destination} previsioni 15 giorni"
    return {
        "url": f"{GOOGLE_SEARCH_URL}?q={quote_plus(query)}",
        "label": f"Previsioni reali per {destination}",
    }


def build_climate(trip) -> dict | None:
    """La scheda del clima tipico, o `None` se manca destinazione o data.

    Non è una previsione e il documento lo scrive: vedi il docstring del
    modulo per il perché questa è l'unica risposta onesta possibile.
    """
    zone_key = resolve_climate_zone(trip)
    start = _parse_date(_get(trip, "date_start"))
    if zone_key is None or start is None:
        return None
    zone = _CLIMATE_ZONES.get(zone_key)
    if zone is None:
        return None

    temp_min, temp_max, rain = zone["months"][start.month - 1]
    swing = temp_max - temp_min

    climate = {
        "zone": zone_key,
        "zone_label": zone["label"],
        "month": start.month,
        "month_label": MONTH_NAMES[start.month - 1],
        "season": _season_label(start.month),
        "temp_min": temp_min,
        "temp_max": temp_max,
        "temp_swing": swing,
        "rain": rain,
        "note": zone["note"],
        "forecast_link": forecast_link(trip),
    }

    # La luce del giorno, ma SOLO la durata — non gli orari.
    #
    # `describe_light()` sa anche dire a che ora sorge e tramonta il sole, e la
    # tentazione di stamparlo qui è forte. Non lo facciamo, per un motivo che
    # si vede a occhio nudo su Lisbona: senza il fuso vero, `sun_times` ripiega
    # sulla stima da longitudine (15° = 1 ora) e si marca da solo come
    # approssimato. Su Lisbona (-9,14°) la stima dà -1, mentre il Portogallo a
    # settembre è a +1: due ore di errore, e un tramonto sbagliato di due ore
    # è esattamente il tipo di dato che, stampato con l'aria della precisione,
    # fa perdere fiducia in tutto il resto del documento.
    #
    # La DURATA della luce, invece, è la differenza fra due istanti: il fuso si
    # semplifica e sparisce dal conto. È corretta ovunque, e per la domanda che
    # questa sezione sta ponendo — quanto presto fa buio, quindi serve o no la
    # giacca per la sera e la torcia del telefono — è anche l'unica che serve.
    # Gli orari veri del tramonto stanno già nel piano giorno per giorno, dove
    # il fuso arriva dalla destinazione e non da una stima.
    lat = _as_float(_get(trip, "dest_lat"))
    lng = _as_float(_get(trip, "dest_lng"))
    if lat is not None and lng is not None:
        try:
            light = sun_times.describe_light(start, lat, lng)
        except Exception:  # noqa: BLE001 — il sole non deve poter far cadere la valigia
            light = {"available": False}
        if light.get("available") and light.get("daylight_label"):
            climate["daylight_label"] = light["daylight_label"]
    return climate


# --- La valigia -----------------------------------------------------------

# Tipi grezzi di Google che indicano un luogo di culto: l'unico posto in
# Europa dove un modo di vestire può farti rifiutare l'ingresso dopo che hai
# già pagato il biglietto e fatto la coda.
_WORSHIP_RAW_TYPES = (
    "church", "cathedral", "basilica", "mosque", "synagogue", "hindu_temple",
    "place_of_worship", "monastery", "abbey",
)
_WORSHIP_NAME_HINTS = (
    "chiesa", "basilica", "duomo", "cattedrale", "santuario", "abbazia",
    "moschea", "sinagoga", "monastero", "battistero",
)
_SWIM_RAW_TYPES = ("beach", "spa", "swimming_pool", "water_park", "hot_spring")
_SWIM_NAME_HINTS = ("spiaggia", "beach", "terme", "spa", "lido", "piscina")
_HIKE_RAW_TYPES = ("hiking_area", "national_park", "state_park", "volcano")
_FANCY_PRICE_LEVELS = ("EXPENSIVE", "VERY_EXPENSIVE")


def _poi_flags(itinerary: dict | None, pois=None) -> dict:
    """Cosa contiene DAVVERO questo itinerario, contato una volta sola.

    Ogni voce della valigia che segue è ancorata a uno di questi numeri: se il
    programma non ha chiese, la riga sul codice di abbigliamento non compare.
    Una lista di consigli generici lunga il doppio si smette di leggere al
    quarto punto — vale qui la stessa regola già scritta in `predeparture.py`.
    """
    from . import tips_generator

    used_ids: list[str] = []
    seen: set[str] = set()
    for day in (itinerary or {}).get("days") or []:
        if not isinstance(day, dict):
            continue
        for block in day.get("blocks") or []:
            if not isinstance(block, dict):
                continue
            poi_id = block.get("poi_id")
            if isinstance(poi_id, str) and poi_id and poi_id not in seen:
                seen.add(poi_id)
                used_ids.append(poi_id)

    by_id = {}
    for poi in pois or []:
        poi_id = _get(poi, "id")
        if isinstance(poi_id, str) and poi_id:
            by_id[poi_id] = poi
    # Senza itinerario utilizzabile si guardano comunque i POI ricevuti: è
    # meglio di non guardare niente, e non può inventare nulla.
    selected = [by_id[i] for i in used_ids if i in by_id] or list(by_id.values())

    flags = {
        "total": len(selected), "outdoor": 0, "museums": 0,
        "worship": 0, "swim": 0, "hike": 0, "fancy_meal": 0,
    }
    for poi in selected:
        raw = str(_get(poi, "primary_type", "") or "").strip().lower()
        name = str(_get(poi, "name", "") or "").strip().lower()
        normalized = str(_get(poi, "type", "") or "").strip().lower()
        try:
            if tips_generator.is_weather_exposed(poi):
                flags["outdoor"] += 1
        except Exception:  # noqa: BLE001
            pass
        if normalized == "museum":
            flags["museums"] += 1
        if raw in _WORSHIP_RAW_TYPES or any(h in name for h in _WORSHIP_NAME_HINTS):
            flags["worship"] += 1
        if raw in _SWIM_RAW_TYPES or any(h in name for h in _SWIM_NAME_HINTS):
            flags["swim"] += 1
        if raw in _HIKE_RAW_TYPES:
            flags["hike"] += 1
        if normalized == "restaurant" and _get(poi, "price_level") in _FANCY_PRICE_LEVELS:
            flags["fancy_meal"] += 1
    return flags


def _duration_days(trip) -> int:
    """Quanti giorni dura il viaggio, con la STESSA aritmetica del resto del PDF.

    `duration_days` è il campo dichiarato; le date sono il fatto. Quando ci
    sono entrambi vince la differenza fra le date, perché è quella che il
    cliente ha effettivamente scritto nel form.

    Il conto è `(fine - inizio).days`, SENZA il "+1" dei giorni di calendario.
    Non è una scelta di gusto: è la formula di `triage._date_difference_days()`,
    cioè quella che ha prodotto il numero già stampato in copertina e nella
    riga di intestazione. Il primo campione generato con il "+1" diceva
    "3 giorni" in cima alla pagina e "i giorni sono 4" dentro la valigia, nello
    stesso documento — e un documento che si contraddice da solo su un numero
    verificabile a occhio perde credibilità su tutti gli altri, compresi quelli
    che il cliente non può controllare.
    """
    start = _parse_date(_get(trip, "date_start"))
    end = _parse_date(_get(trip, "date_end"))
    if start and end and end > start:
        days = (end - start).days
    else:
        raw = _get(trip, "duration_days")
        days = int(raw) if isinstance(raw, int) and not isinstance(raw, bool) else 0
    # Un viaggio di 400 giorni è un errore di digitazione, non un viaggio: il
    # conto dei cambi va comunque tenuto dentro numeri che una valigia può
    # contenere, altrimenti la riga stampata diventa comica.
    return max(1, min(days, 30))


def _clothing_for_temperature(temp_min: int, temp_max: int) -> list[str]:
    """Cosa si indossa a queste temperature. Nessuna scelta lasciata al caso.

    La soglia che conta non è la massima: è la MINIMA, perché è quella che
    determina come si sta la sera, che è il momento in cui il cliente è fuori
    da un ristorante e non può tornare in hotel a cambiarsi.
    """
    items: list[str] = []
    if temp_max >= 28:
        items.append(
            "Capi leggeri in cotone o lino, di colore chiaro: sopra i 28° il "
            "tessuto sintetico non asciuga, si appiccica e basta"
        )
        items.append(
            "Cappello con visiera o tesa e occhiali da sole — le ore centrali "
            "si passano quasi tutte all'aperto, fra un luogo e l'altro"
        )
        items.append("Crema solare SPF 30 o superiore, anche in città")
    elif temp_max >= 22:
        items.append("Capi leggeri e traspiranti per il giorno")
        items.append("Occhiali da sole e crema solare per le ore centrali")
    elif temp_max >= 16:
        items.append(
            "Vestirsi a strati: maglietta, camicia o felpa leggera, giacca "
            "sfoderata da togliere quando il sole è alto"
        )
    elif temp_max >= 10:
        items.append("Giacca chiusa, maglione o pile, sciarpa leggera")
    else:
        items.append(
            "Cappotto o piumino vero, strato termico sotto (non una seconda "
            "maglietta: il termico pesa meno e scalda di più)"
        )
        items.append("Guanti, berretto, sciarpa: sono tre oggetti piccoli e ognuno pesa poco")

    if temp_min <= 0:
        items.append(
            "Calze di lana e scarpe impermeabili con suola scolpita: sotto lo "
            "zero il problema non è il freddo, è il ghiaccio sui marciapiedi"
        )
    elif temp_min <= 8:
        items.append(
            f"Uno strato in più per la sera: si scende intorno ai {temp_min}°, "
            "e la differenza si sente tutta appena cala il sole"
        )
    return items


def build_packing(trip, itinerary: dict | None = None, pois=None, climate: dict | None = None) -> list[dict]:
    """La valigia di QUESTO viaggio: `[{"group", "items": [str]}]`.

    Ogni gruppo compare solo se ha almeno una voce, e ogni voce o è
    universalmente vera per chiunque parta, o è ancorata a un dato reale di
    questo viaggio (il mese, la zona climatica, i luoghi in programma, la
    presa elettrica del paese). Nessun riempitivo.
    """
    days = _duration_days(trip)
    flags = _poi_flags(itinerary, pois)
    country = local_info.country_practical_info(_get(trip, "destination", "") or "")
    groups: list[dict] = []

    # --- Quanto, non solo cosa: qui il conto lo fa Python ------------------
    changes = min(days + 1, 8)
    tops = max(2, min(days, 7))
    bottoms = max(1, min(1 + days // 3, 4))
    quantity: list[str] = [
        f"{changes} cambi di intimo e calze: uno per ogni giorno passato sul "
        "posto, contando anche quello della partenza e quello del ritorno",
        f"{tops} fra magliette, camicie e top",
        f"{bottoms} fra pantaloni, gonne o vestiti — si riusano, l'intimo no",
        "Due paia di scarpe al massimo: quelle che indossi in aereo e un "
        "secondo paio. Il terzo paio è il modo più comune di superare il peso "
        "consentito senza accorgersene",
    ]
    if days > 7:
        quantity.append(
            f"Oltre i 7 giorni ({days} in questo caso) conviene una lavanderia "
            "a gettoni sul posto invece di una valigia più grande: costa meno "
            "del bagaglio in stiva supplementare e pesa zero"
        )
    groups.append({"group": "Quanto portare", "items": quantity})

    # --- Il clima, tradotto in capi ---------------------------------------
    if climate:
        clothing = _clothing_for_temperature(climate["temp_min"], climate["temp_max"])
        rain = climate.get("rain")
        if rain in (_RAIN_FREQUENT, _RAIN_VERY_LIKELY):
            clothing.append(
                "Giacca impermeabile leggera con cappuccio: a "
                f"{climate['month_label']} qui la pioggia è {rain}, e arriva e "
                "passa più volte al giorno — l'ombrello grande si porta a "
                "mano tutto il giorno per usarlo venti minuti"
            )
            clothing.append(
                "Un secondo paio di scarpe che possa bagnarsi, e la certezza "
                "di non dover camminare per otto ore con i piedi umidi"
            )
        elif rain == _RAIN_POSSIBLE:
            clothing.append(
                "Ombrello pieghevole o poncho da pochi grammi: a "
                f"{climate['month_label']} la pioggia qui è possibile, non "
                "probabile — non serve attrezzarsi, serve non farsi sorprendere"
            )
        elif rain == _RAIN_RARE and flags["outdoor"] >= 3:
            clothing.append(
                "Un poncho ripiegabile da pochi grammi: la pioggia in questo "
                "mese è rara, ma il programma è quasi tutto all'aperto e il "
                "peso è quello di un fazzoletto"
            )
        if climate["temp_swing"] >= 12:
            clothing.append(
                f"Fra la minima e la massima ci sono circa {climate['temp_swing']} "
                "gradi nella stessa giornata: qualunque capo unico sarà "
                "sbagliato due volte su tre. Strati, non un capo pesante"
            )
        groups.append({
            "group": f"Il clima di {climate['month_label']} ({climate['zone_label']})",
            "items": clothing,
        })

    # --- Quello che il programma richiede, e nient'altro -------------------
    program: list[str] = []
    if flags["outdoor"] >= 2 or flags["hike"]:
        program.append(
            "Scarpe da camminata GIÀ RODATE, mai un paio nuovo: una vescica al "
            "secondo giorno non toglie una tappa, toglie il resto del viaggio"
        )
    if flags["worship"]:
        # La barra obliqua "luogo/luoghi" è il modo pigro di non decidere il
        # plurale, e in un documento che il cliente ha pagato si vede subito:
        # sembra un modulo prestampato. Il conto ce l'abbiamo, il plurale si fa.
        # Il verbo va accordato insieme al nome, non solo il nome: "c'è 2 luoghi"
        # è lo stesso difetto di "luogo/luoghi", solo spostato di una parola.
        quanti = (
            "c'è un luogo di culto" if flags["worship"] == 1
            else f"ci sono {flags['worship']} luoghi di culto"
        )
        program.append(
            f"Spalle e ginocchia coperte: nel programma {quanti}, ed è un "
            "requisito d'ingresso, non un'usanza. Una sciarpa leggera nello "
            "zaino risolve tutto e occupa niente"
        )
    if flags["museums"] >= 2:
        program.append(
            f"Uno zaino piccolo: con {flags['museums']} musei in programma, gli "
            "zaini grandi vanno lasciati al guardaroba, che spesso costa e "
            "sempre fa perdere il momento in cui si entra"
        )
    if flags["swim"]:
        program.append(
            "Costume e un asciugamano in microfibra: nel programma c'è almeno "
            "un luogo dove servono, e sul posto si comprano al triplo"
        )
    if flags["fancy_meal"]:
        program.append(
            "Un capo elegante e un paio di scarpe non sportive: fra i "
            "ristoranti selezionati ce n'è almeno uno di fascia alta, dove il "
            "dress code esiste anche quando non è scritto"
        )
    if program:
        groups.append({"group": "Quello che chiede questo programma", "items": program})

    # --- Elettronica e documenti ------------------------------------------
    tech: list[str] = []
    plug = (country or {}).get("plug") or ""
    if plug:
        if _needs_adapter(plug):
            tech.append(
                f"Adattatore per le prese: qui sono {plug}, diverse da quelle "
                "italiane. Compralo prima di partire — in aeroporto costa tre "
                "volte tanto e in hotel spesso non c'è"
            )
        else:
            tech.append(
                f"Prese {plug}: la spina italiana entra senza adattatore. "
                "Porta comunque una ciabatta piccola, le prese libere in hotel "
                "sono sempre meno di quelle che servono"
            )
    tech.append(
        "Batteria esterna e cavo: questo itinerario si legge dal telefono, e "
        "lo schermo acceso con la mappa aperta consuma più di quanto chiunque "
        "preveda. La batteria esterna va nel bagaglio a mano, sempre: nella "
        "stiva è vietata per legge"
    )
    tap_water = (country or {}).get("tap_water") or ""
    if "potabile" in tap_water.lower():
        tech.append(
            f"Borraccia: l'acqua del rubinetto qui è {tap_water}, e riempirla "
            "due volte al giorno per una settimana è una ventina di euro che "
            "restano in tasca"
        )
    groups.append({"group": "Elettronica e piccole cose", "items": tech})

    documents: list[str] = [
        "Documento d'identità valido, più una foto sul telefono e una copia "
        "in una tasca diversa da quella dell'originale",
        "Tessera sanitaria (TEAM) sul retro: in Unione Europea è quella che "
        "rende gratuito il pronto soccorso, e nessuno se la ricorda",
        "I farmaci che prendi abitualmente, nella confezione originale e nel "
        "bagaglio a mano — non nella stiva, che a volte arriva un giorno dopo",
    ]
    groups.append({"group": "Documenti e salute", "items": documents})

    return [g for g in groups if g["items"]]


def _needs_adapter(plug: str) -> bool:
    """`True` se la spina italiana NON entra in quella presa.

    Il cliente di questo prodotto parte dall'Italia (tipo F/L). Tipo E accetta
    comunque la spina italiana a due poli; G (Regno Unito, Irlanda), J
    (Svizzera) e K (Danimarca) no.
    """
    text = plug.upper()
    if "ADATTATORE" in text:
        return True
    for letter in ("G", "J", "K"):
        if f"TIPO {letter}" in text or f"/{letter}," in text or f"/{letter} " in text:
            return True
    return False


# --- Come si struttura la valigia ----------------------------------------

def build_suitcase_layout(has_hold_luggage: bool = False) -> list[dict]:
    """"Come strutturarla": `[{"title", "detail"}]`, in ordine di riempimento.

    Non dipende dalla destinazione — dipende dalla fisica di una valigia — e
    per questo è l'unico blocco della sezione che c'è sempre. L'ordine è
    quello in cui si mettono davvero le cose dentro, non un elenco tematico:
    una guida al riempimento che non segue il riempimento non si usa.
    """
    steps = [
        {
            "title": "Il peso in basso, vicino alle ruote",
            "detail": (
                "Scarpe, beauty case e libri contro il lato delle ruote. Con "
                "il peso in alto il trolley si ribalta a ogni cordolo e ogni "
                "scala, e ci si passa il viaggio a raddrizzarlo."
            ),
        },
        {
            "title": "Arrotolare, non piegare",
            "detail": (
                "I capi arrotolati stretti occupano circa un terzo in meno e "
                "arrivano con meno pieghe. Le camicie e le giacche restano "
                "distese SOPRA il rotolo, per ultime."
            ),
        },
        {
            "title": "Le scarpe in un sacchetto, e piene",
            "detail": (
                "Suola verso il bordo della valigia, calze e caricabatterie "
                "dentro le scarpe: quello spazio esiste già e altrimenti "
                "viaggia vuoto."
            ),
        },
        {
            "title": "I liquidi in cima, nella busta trasparente",
            "detail": (
                "Contenitori da massimo 100 ml in un sacchetto trasparente "
                "richiudibile da un litro. Alcuni aeroporti con i nuovi "
                "scanner hanno tolto la regola, ma non puoi sapere in anticipo "
                "com'è messo quello del ritorno: prepara la valigia come se "
                "valesse ancora, e in cima, così esce in dieci secondi ai "
                "controlli invece di far disfare tutto."
            ),
        },
        {
            "title": "Pesala a casa, non al gate",
            "detail": (
                "Sali sulla bilancia di casa con la valigia in braccio e poi "
                "senza: la differenza è il peso del bagaglio. Il sovrapprezzo "
                "al gate è la voce più cara dell'intero viaggio, e si evita "
                "con trenta secondi in bagno."
            ),
        },
        {
            "title": "Lascia un quinto della valigia vuoto",
            "detail": (
                "Al ritorno ci sarà qualcosa in più che all'andata, sempre. In "
                "alternativa una borsa ripiegabile da 100 grammi nel fondo: "
                "costa poco e vale un bagaglio extra comprato all'ultimo."
            ),
        },
        {
            "title": "Un'etichetta con il nome, e una anche dentro",
            "detail": (
                "Nome e numero di telefono all'esterno, e un foglietto con lo "
                "stesso dato più l'indirizzo dell'alloggio all'interno: se "
                "l'etichetta esterna si stacca — succede — è l'unica cosa che "
                "permette di restituirti la valigia."
            ),
        },
    ]
    if has_hold_luggage:
        steps.insert(4, {
            "title": "Un cambio completo nel bagaglio a mano",
            "detail": (
                "Anche con la stiva pagata: un cambio, i farmaci, i "
                "caricabatterie e i documenti viaggiano con te. La valigia "
                "imbarcata che arriva un giorno dopo è molto più frequente di "
                "quella persa, e la differenza fra le due situazioni la fa "
                "esattamente questo cambio."
            ),
        })
    return steps


# --- Stiva o cabina, e quanto costa --------------------------------------

# Fasce di prezzo INDICATIVE, per persona e per tratta, acquisto online al
# momento della prenotazione. Sono fasce e non numeri esatti perché il prezzo
# reale dipende da rotta, data, riempimento del volo e momento dell'acquisto:
# scrivere "22 €" sarebbe più bello da leggere ed è sbagliato per costruzione.
# La data di ultima revisione viene stampata accanto (BAGGAGE_PRICES_UPDATED).
_CARRIERS = (
    {"name": "Ryanair", "personal": "40x20x25 cm sotto il sedile, incluso",
     "cabin": (6, 36), "hold": (19, 60), "hold_kg": "20 kg"},
    {"name": "Wizz Air", "personal": "40x30x20 cm sotto il sedile, incluso",
     "cabin": (5, 40), "hold": (20, 70), "hold_kg": "20 kg"},
    {"name": "easyJet", "personal": "45x36x20 cm sotto il sedile, incluso",
     "cabin": (6, 35), "hold": (15, 50), "hold_kg": "15 kg"},
    {"name": "Vueling", "personal": "40x30x20 cm sotto il sedile, incluso",
     "cabin": (10, 40), "hold": (20, 60), "hold_kg": "23 kg"},
    {"name": "Volotea", "personal": "40x30x20 cm sotto il sedile, incluso",
     "cabin": (10, 35), "hold": (20, 55), "hold_kg": "20 kg"},
    {"name": "Transavia", "personal": "40x30x20 cm sotto il sedile, incluso",
     "cabin": (10, 30), "hold": (20, 55), "hold_kg": "20 kg"},
)

# Parole che, nelle note del cliente, dicono che l'aereo non c'entra.
_NO_FLIGHT_HINTS = (
    "in auto", "in macchina", "con l'auto", "con la macchina", "in treno",
    "col treno", "in camper", "in moto", "in nave", "in traghetto",
    "road trip", "viaggio in auto", "andiamo in macchina",
)
_FLIGHT_HINTS = (
    "volo", "voli", "aereo", "low cost", "lowcost", "ryanair", "wizz",
    "easyjet", "vueling", "volotea", "bagaglio", "stiva", "cabina",
    "imbarco", "aeroporto",
)


def build_baggage(trip, climate: dict | None = None, travellers: int = 1) -> dict | None:
    """Stiva o cabina, con il conto fatto — o `None` se il volo non c'entra.

    `None` quando le note del cliente dicono esplicitamente che si va in auto,
    in treno o in camper E non nominano mai un volo: stampare le tariffe dei
    bagagli a chi parte in macchina è rumore, ed è il tipo di rumore che fa
    perdere fiducia nel resto del documento.

    La raccomandazione NON è un'opinione: è una funzione della durata del
    viaggio e della temperatura tipica (i vestiti invernali occupano circa il
    doppio a parità di giorni), e il conto del costo totale è aritmetica su
    numeri stampati accanto.
    """
    notes = str(_get(trip, "raw_notes", "") or "").lower()
    mentions_flight = any(h in notes for h in _FLIGHT_HINTS)
    if not mentions_flight and any(h in notes for h in _NO_FLIGHT_HINTS):
        return None

    days = _duration_days(trip)
    cold = bool(climate) and climate["temp_max"] <= 12
    try:
        people = max(1, int(travellers))
    except (TypeError, ValueError):
        people = 1

    if days <= 3 and not cold:
        choice = "cabina"
        reason = (
            f"{days} giorni entrano in un bagaglio a mano senza sforzo. La "
            "stiva, oltre a costare, aggiunge la coda al check-in all'andata e "
            "l'attesa al nastro al ritorno: fra i due voli sono in media "
            "un'ora e mezza di viaggio in più, pagata."
        )
    elif days <= 6 and not cold:
        choice = "cabina"
        reason = (
            f"{days} giorni stanno ancora in cabina se si riusano i pantaloni "
            "e si porta un secondo paio di scarpe soltanto. Conviene la stiva "
            "solo se hai in programma acquisti ingombranti o attrezzatura "
            "(scarponi, tavola, passeggino)."
        )
    elif cold and days <= 4:
        choice = "cabina, ma stretta"
        reason = (
            f"{days} giorni sono pochi, ma con massime intorno ai "
            f"{climate['temp_max']}° i capi invernali occupano il doppio: il "
            "cappotto e le scarpe pesanti vanno INDOSSATI in aereo, non nella "
            "valigia. Fatto questo, la cabina basta."
        )
    else:
        choice = "stiva"
        reason = (
            f"{days} giorni"
            + (" con temperature invernali" if cold else "")
            + " superano quello che una cabina può contenere senza che il "
            "viaggio diventi un esercizio di incastro. Comprala al momento "
            "della prenotazione: dopo, e soprattutto al gate, costa da due a "
            "quattro volte tanto."
        )

    # Il costo totale, calcolato e non lasciato al cliente: andata e ritorno,
    # per il numero di persone che ha indicato.
    trips_paid = 2 * people
    hold_low = min(c["hold"][0] for c in _CARRIERS) * trips_paid
    hold_high = max(c["hold"][1] for c in _CARRIERS) * trips_paid
    cabin_low = min(c["cabin"][0] for c in _CARRIERS) * trips_paid
    cabin_high = max(c["cabin"][1] for c in _CARRIERS) * trips_paid
    people_label = (
        f"{people} persone, andata e ritorno" if people > 1
        else "una persona, andata e ritorno"
    )
    total = (
        f"Per {people_label}, sono {trips_paid} acquisti: il trolley in cabina "
        f"viene {cabin_low}–{cabin_high} € in tutto, la stiva "
        f"{hold_low}–{hold_high} €. È la voce di spesa del viaggio che si "
        "riduce di più con una decisione presa prima, invece che al gate."
    )

    # Le note valgono tutte per chiunque tranne l'ultima coppia, che ha senso
    # solo se si viaggia in più di uno: a chi parte da solo stampare "dividete
    # la stiva" è una riga sprecata, e le righe sprecate sono esattamente il
    # difetto che Lorenzo ha segnalato sull'impaginazione.
    notes_out = [
        "Il metro di misura al gate è vero e viene usato: se il trolley "
        "entra nella sagoma solo spingendo, non entra.",
        "Batterie esterne, sigarette elettroniche e accendini viaggiano "
        "SOLO in cabina: sono vietati in stiva per legge, e vengono "
        "sequestrati al controllo.",
    ]
    if people > 1:
        notes_out.append(
            f"In {people} conviene quasi sempre una sola stiva condivisa più "
            "un bagaglio a mano a testa, invece di una stiva ciascuno: "
            "il peso ammesso si somma, il numero di colli no."
        )
        notes_out.append(
            "Prima di dividere il peso fra due valigie della stessa "
            "prenotazione, verifica che la compagnia lo consenta: alcune "
            "pesano ogni collo separatamente."
        )

    return {
        "choice": choice,
        "reason": reason,
        "total": total,
        "people": people,
        "days": days,
        "carriers": [dict(c) for c in _CARRIERS],
        "updated": BAGGAGE_PRICES_UPDATED,
        "caveat": (
            f"Fasce indicative riviste a {BAGGAGE_PRICES_UPDATED}, per persona "
            "e per tratta, acquistate online insieme al biglietto. Il prezzo "
            "reale dipende dalla rotta, dalla data e da quanto è pieno il "
            "volo: verificalo sul sito della compagnia prima di decidere. "
            f"L'unica costante è che al gate costa sempre molto di più — e il "
            "bagaglio a mano fuori misura misurato all'imbarco è la voce più "
            "cara di tutte."
        ),
        "notes": notes_out,
        "people_label": people_label,
    }


def build_vademecum(trip, itinerary: dict | None = None, hotels=None, pois=None,
                    travellers: int = 1) -> dict:
    """`{"climate", "packing", "suitcase", "baggage"}` — mai un'eccezione.

    Stessa rete di sicurezza di `predeparture.build_predeparture()`: un
    ingrediente mancante toglie il suo blocco, non la sezione, e non il
    documento.
    """
    try:
        climate = build_climate(trip)
    except Exception as e:  # noqa: BLE001
        print(f"⚠️  Vademecum: scheda clima saltata: {type(e).__name__}: {e}")
        climate = None
    try:
        baggage = build_baggage(trip, climate, travellers=travellers)
    except Exception as e:  # noqa: BLE001
        print(f"⚠️  Vademecum: sezione bagagli saltata: {type(e).__name__}: {e}")
        baggage = None
    try:
        packing = build_packing(trip, itinerary, pois, climate)
    except Exception as e:  # noqa: BLE001
        print(f"⚠️  Vademecum: lista valigia saltata: {type(e).__name__}: {e}")
        packing = []
    try:
        has_hold = bool(baggage) and baggage.get("choice") == "stiva"
        suitcase = build_suitcase_layout(has_hold)
    except Exception as e:  # noqa: BLE001
        print(f"⚠️  Vademecum: struttura della valigia saltata: {type(e).__name__}: {e}")
        suitcase = []
    return {
        "climate": climate,
        "packing": packing,
        "suitcase": suitcase,
        "baggage": baggage,
    }
