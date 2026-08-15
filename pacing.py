"""
[NUOVO 2026-08-02 — task #166, richiesta testuale di Lorenzo dopo aver letto
un PDF reale: "tra le varie attività mi sembra che ci sia ancora troppo
tempo con il rischio che la gente si annoi oppure finisca prima, valuta tu
caso per caso ma stacci molto attento"]

Il ritmo della giornata, calcolato invece che sperato.

PERCHÉ QUESTO MODULO ESISTE, dato che una regola anti-noia c'era già.
Il 2026-07-31 la stessa lamentela aveva prodotto due difese: il punto 9 di
[HARD_CONSTRAINTS] nel system prompt (una tabella di durate di riferimento,
scritta in prosa) e `validator.check_day_density()` (un termometro che
segnala i blocchi oltre le 3 ore). Lorenzo ha riletto un PDF generato DOPO
quelle due difese e ha trovato lo stesso difetto. Vale la pena capire
perché, perché la ragione dice anche qual è la correzione giusta:

- la regola nel prompt chiede al modello di fare un'ARITMETICA (orario
  successivo − orario − spostamento, confrontato con una tabella) su ogni
  blocco di ogni giorno. È esattamente il tipo di compito su cui un modello
  linguistico è inaffidabile in modo silenzioso: non sbaglia sempre, e
  quando sbaglia il risultato è comunque plausibile a leggersi;
- il termometro nel validator è tarato su 180 minuti UGUALI PER TUTTI e
  non è bloccante. Una visita da 40 minuti a cui sono state assegnate due
  ore e mezza — il caso che Lorenzo ha letto — passa sotto la soglia senza
  emettere niente. E anche quando emette, emette verso un operatore che in
  produzione non c'è: il PDF parte lo stesso.

Quindi la correzione non è l'ennesima frase nel prompt. È spostare
l'aritmetica dove l'aritmetica non sbaglia, cioè qui, e usarne il risultato
in due modi diversi e complementari:

  1) TARARE IL TERMOMETRO CASO PER CASO ("valuta tu caso per caso"). La
     soglia non è più un 180 unico: è la durata tipica di QUEL tipo di
     luogo. Due ore in un grande museo nazionale sono giuste; due ore
     davanti a una fontana sono un buco.

  2) DIRLO AL CLIENTE. Questa è la parte che nessuna delle due difese
     precedenti faceva, ed è quella che risolve davvero la frase di
     Lorenzo — che contiene DUE paure, non una: "la gente si annoia"
     OPPURE "finisce prima". La seconda non è un difetto dell'itinerario,
     è un difetto del DOCUMENTO: il cliente legge "09:00 Visita al museo"
     e poi "12:30 Pranzo", e non ha modo di sapere se il museo lo terrà
     occupato tre ore o quaranta minuti. Se finisce alle 10, si ritrova in
     mezzo a una città che non conosce senza un piano — e il documento che
     ha pagato non gliel'aveva detto. Un orario di fine stimato e un
     margine dichiarato ("la visita dura in genere 1h-1h30: avrai circa
     un'ora di margine prima di ...") trasformano un buco muto in tempo
     che il cliente può usare.

Il modulo è puro: nessuna rete, nessun file, nessuna chiamata a Claude.
L'aritmetica del tempo costa zero token e non entra nei 300 secondi di
Make — al contrario di un secondo giro di generazione, che sarebbe stato
l'altra strada possibile e che avrebbe pagato in latenza e in costo
esattamente ciò che qui si ottiene gratis.
"""

from __future__ import annotations

# Tabella di riferimento delle durate tipiche di una visita, in minuti.
#
# È la stessa tabella che vive in prosa nel punto 9 di [HARD_CONSTRAINTS]
# (`prompts/system_prompt_master.txt`), portata qui in forma eseguibile. Le
# due copie DEVONO restare allineate, e un test lo verifica: una tabella nel
# prompt che dicesse una cosa e una nel codice che ne dicesse un'altra
# produrrebbe warning su itinerari che hanno seguito le istruzioni alla
# lettera — il peggior tipo di falso positivo, quello che insegna a
# ignorare i warning.
#
# Le chiavi sono i `primaryType` grezzi di Google Places (i più informativi:
# "art_gallery" non è "museum") più i quattro tipi normalizzati di
# `places_client._TYPE_NORMALIZE` come rete di sicurezza. La ricerca prova
# prima il primaryType, poi il tipo normalizzato, poi il default.
TYPICAL_VISIT_MINUTES: dict[str, tuple[int, int]] = {
    # Musei e gallerie. `museum` copre sia il museo medio (60-120) sia il
    # grande museo nazionale (120-180): il tipo Google non li distingue, e
    # accorciare la forbice qui produrrebbe warning sugli Uffizi.
    "museum": (60, 180),
    "art_gallery": (60, 120),
    "history_museum": (60, 150),
    "science_museum": (90, 180),
    # Luoghi di culto e monumenti: si entra, si guarda, si esce.
    "church": (30, 60),
    "cathedral": (30, 60),
    "mosque": (30, 60),
    "synagogue": (30, 60),
    "monument": (20, 45),
    "historical_landmark": (30, 75),
    "historical_place": (30, 75),
    "castle": (60, 120),
    "palace": (60, 120),
    "cultural_landmark": (30, 75),
    # Spazi aperti: una piazza si attraversa, un parco si percorre.
    "plaza": (20, 45),
    "town_square": (20, 45),
    "park": (45, 90),
    "national_park": (120, 300),
    "garden": (45, 90),
    "botanical_garden": (60, 120),
    "beach": (120, 300),
    "hiking_area": (120, 300),
    "observation_deck": (20, 45),
    "viewpoint": (20, 45),
    "scenic_point": (20, 45),
    "bridge": (15, 30),
    "fountain": (20, 45),
    # Mercati e negozi.
    "market": (30, 60),
    "shopping_mall": (60, 120),
    "store": (30, 60),
    "book_store": (30, 60),
    "clothing_store": (30, 60),
    "gift_shop": (20, 45),
    "shopping": (30, 60),
    # Esperienze.
    "zoo": (120, 240),
    "aquarium": (90, 150),
    "amusement_park": (180, 360),
    "spa": (90, 150),
    "winery": (60, 120),
    "performing_arts_theater": (120, 180),
    "movie_theater": (120, 180),
    "night_club": (120, 240),
    "bar": (60, 120),
    # Tavola. Un pranzo e una cena non hanno la stessa durata: la
    # distinzione la fa `typical_minutes_for()` guardando l'ora del blocco,
    # perché il tipo Google è lo stesso per entrambi.
    "restaurant": (60, 90),
    "cafe": (30, 45),
    "coffee_shop": (30, 45),
    "bakery": (15, 30),
    "ice_cream_shop": (15, 30),
    # Tipi normalizzati (rete di sicurezza).
    "activity": (45, 120),
}

# Usato quando il tipo è ignoto: volutamente LARGO. Un default stretto
# produrrebbe warning su ogni luogo che la tabella non conosce, cioè
# rumore sistematico proprio nei casi in cui sappiamo di non sapere.
DEFAULT_VISIT_MINUTES: tuple[int, int] = (45, 150)

# Un pasto serale è più lungo di un pranzo, sempre, ovunque. Il tipo Google
# non lo distingue: lo distingue l'orario.
DINNER_MINUTES: tuple[int, int] = (90, 120)
_DINNER_FROM_MINUTE = 19 * 60

# Sotto questa soglia il margine non è un buco: è il buffer di spostamento e
# di respiro che [HARD_CONSTRAINTS] punto 2 chiede esplicitamente di
# prevedere (30-45 min tra i blocchi). Segnalarlo sarebbe segnalare come
# difetto una regola del prodotto.
IDLE_TOLERANCE_MINUTES = 45

# Oltre questo margine il buco non è più "un po' di respiro": è mezza
# mattina in cui il cliente non sa cosa fare. È la soglia con cui
# `validator.check_day_density()` decide se emettere un warning.
IDLE_WARNING_MINUTES = 75


def _poi_id_of(block) -> str | None:
    """
    L'identificativo del luogo di un blocco, o None se non è utilizzabile.

    [AGGIUNTO 2026-08-02 — difetto reale trovato dai test di robustezza:
    `render_html()` NON è protetto dall'esito del validator (main.py e
    /v1/pdf possono renderizzare un itinerario mai validato), quindi qui
    arriva anche un `poi_id` che è una lista. Usarlo come chiave di un
    dizionario sollevava `TypeError: unhashable type` e faceva fallire
    l'intero PDF per un campo malformato in un singolo blocco: il tipo di
    guasto peggiore, perché il cliente non riceve niente invece di
    ricevere un documento con una riga in meno.]
    """
    value = block.get("poi_id") if isinstance(block, dict) else None
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    return value


def _to_minutes(hhmm) -> int | None:
    """"09:30" -> 570. Qualsiasi altra cosa -> None, senza sollevare."""
    if not isinstance(hhmm, str):
        return None
    parts = hhmm.strip().split(":")
    if len(parts) != 2:
        return None
    try:
        hours, minutes = int(parts[0]), int(parts[1])
    except (TypeError, ValueError):
        return None
    if not (0 <= hours <= 23 and 0 <= minutes <= 59):
        return None
    return hours * 60 + minutes


def _to_hhmm(minutes: int) -> str:
    """570 -> "09:30". Oltre la mezzanotte resta dentro le 24h."""
    minutes = int(minutes) % (24 * 60)
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def typical_minutes_for(poi, start_minute: int | None = None) -> tuple[int, int]:
    """
    Quanto dura, di norma, la visita a questo luogo — (minimo, massimo).

    `poi` può essere un POI, un dict, o None (blocco senza scheda Google:
    si torna al default largo). `start_minute` serve solo a distinguere un
    pranzo da una cena, che per Google sono lo stesso `restaurant`.
    """
    def _get(name):
        if poi is None:
            return None
        if isinstance(poi, dict):
            return poi.get(name)
        return getattr(poi, name, None)

    primary = str(_get("primary_type") or "").strip().lower()
    normalized = str(_get("type") or "").strip().lower()

    if normalized == "restaurant" or primary == "restaurant":
        if start_minute is not None and start_minute >= _DINNER_FROM_MINUTE:
            return DINNER_MINUTES

    for key in (primary, normalized):
        if key and key in TYPICAL_VISIT_MINUTES:
            return TYPICAL_VISIT_MINUTES[key]
    return DEFAULT_VISIT_MINUTES


def describe_duration(minutes: int) -> str:
    """
    45 -> "45 min"; 90 -> "1h30"; 120 -> "2h".

    Nessun "1.5 ore": un cliente che legge un orario non fa la conversione
    dai decimali, e "1h30" è come la gente scrive davvero un'ora e mezza.
    """
    minutes = max(0, int(minutes))
    if minutes < 60:
        return f"{minutes} min"
    hours, rest = divmod(minutes, 60)
    return f"{hours}h" if rest == 0 else f"{hours}h{rest:02d}"


def describe_typical(span: tuple[int, int]) -> str:
    """(60, 105) -> "1h-1h45". Se gli estremi coincidono, uno solo."""
    low, high = span
    if low >= high:
        return describe_duration(high)
    return f"{describe_duration(low)}-{describe_duration(high)}"


def analyze_day(
    blocks: list,
    poi_by_id: dict | None = None,
    travel_minutes_by_pair: dict | None = None,
) -> list[dict]:
    """
    Il ritmo di una giornata, blocco per blocco.

    Per ogni blocco ritorna un dict:
      {"index", "time", "start_minute", "next_start_minute",
       "window_minutes"      — quanto tempo separa questo blocco dal successivo,
       "travel_minutes"      — quanto ne serve per lo spostamento (0 se ignoto),
       "typical"             — (min, max) di riferimento per questo luogo,
       "typical_text"        — la stessa forbice, leggibile,
       "end_estimate"        — "HH:MM" di fine stimata (sul MASSIMO tipico:
                               ottimisti sulla durata = prudenti sul buco),
       "idle_minutes"        — margine residuo oltre spostamento e visita,
       "is_last"}

    L'ULTIMO blocco della giornata non ha un blocco successivo da cui
    dedurre la finestra: `window_minutes`, `idle_minutes` e `end_estimate`
    restano None. Inventare una fine della giornata produrrebbe un margine
    fantasma su ogni cena.

    `idle_minutes` è calcolato sul MASSIMO della forbice tipica, non sul
    minimo. È una scelta, non un dettaglio: usando il minimo, ogni visita
    con una forbice ampia genererebbe un margine enorme e il segnale
    diventerebbe rumore. Usando il massimo, un margine che resta positivo è
    un margine che esiste anche per il visitatore più lento.
    """
    poi_by_id = poi_by_id or {}
    travel_minutes_by_pair = travel_minutes_by_pair or {}
    clean = [b for b in (blocks or []) if isinstance(b, dict)]
    out: list[dict] = []

    for index, block in enumerate(clean):
        start = _to_minutes(block.get("time"))
        is_last = index == len(clean) - 1
        next_start = None if is_last else _to_minutes(clean[index + 1].get("time"))

        poi = poi_by_id.get(_poi_id_of(block))
        typical = typical_minutes_for(poi, start)

        travel = 0
        if not is_last:
            pair = (_poi_id_of(block), _poi_id_of(clean[index + 1]))
            measured = travel_minutes_by_pair.get(pair)
            if measured is None:
                measured = travel_minutes_by_pair.get((pair[1], pair[0]))
            if isinstance(measured, (int, float)) and not isinstance(measured, bool):
                travel = max(0, int(measured))

        window = None
        idle = None
        end_estimate = None
        if start is not None and next_start is not None and next_start > start:
            window = next_start - start
            idle = window - travel - typical[1]
            end_estimate = _to_hhmm(start + typical[1])

        out.append({
            "index": index,
            "time": block.get("time"),
            "activity": block.get("activity"),
            "start_minute": start,
            "next_start_minute": next_start,
            "window_minutes": window,
            "travel_minutes": travel,
            "typical": typical,
            "typical_text": describe_typical(typical),
            "end_estimate": end_estimate,
            "idle_minutes": idle,
            "is_last": is_last,
        })
    return out


def describe_margin(entry: dict, next_activity: str = "") -> str:
    """
    La frase che il cliente legge sotto un blocco con margine reale, o "".

    Dice tre cose e nessuna di più: quanto dura di solito la visita, a che
    ora ne uscirà verosimilmente, quanto tempo gli resta e prima di cosa.
    Sono tre fatti verificabili — nessun "godetevi l'atmosfera del
    quartiere", che è la frase che si scrive quando non si ha niente da
    dire e che il cliente riconosce per quello che è.
    """
    idle = entry.get("idle_minutes")
    if not isinstance(idle, int) or idle < IDLE_TOLERANCE_MINUTES:
        return ""
    frase = (
        f"Durata tipica della sosta {entry['typical_text']}: "
        f"conta di essere libero verso le {entry['end_estimate']}, "
        f"con circa {describe_duration(idle)} di margine"
    )
    activity = str(next_activity or "").strip()
    if activity:
        frase += f" prima di «{activity}»"
    return frase + "."
