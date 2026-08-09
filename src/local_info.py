"""
NUOVO 2026-07-31 — informazioni pratiche del paese di destinazione.

Aggiunta mia alla lista di Lorenzo ("stupiscimi"), al servizio delle direttrici
"pratico e sicurezza" e "risparmio e pagamenti" degli architect's tips.

PERCHÉ UNA TABELLA CURATA E NON L'LLM
--------------------------------------
Il numero di emergenza è l'informazione del documento in cui un errore fa il
danno più grave e più veloce. Un LLM che "ricorda" il numero dei pompieri in
Croazia è, nella migliore delle ipotesi, probabilmente corretto — e
"probabilmente corretto" non è una categoria accettabile per un numero che si
compone in un'emergenza. Quindi: tabella scritta a mano, verificabile leggendo
questo file, aggiornabile in un punto solo; e un paese non presente in tabella
NON produce un'invenzione, produce l'omissione della sezione (o il solo 112 se
il paese è nell'Unione Europea, dove il numero unico è per legge).

Il resto (prese elettriche, valuta, acqua del rubinetto, mancia) sono fatti
stabili che valgono per l'intero paese: non cambiano tra un viaggio e l'altro,
e quindi non hanno alcuna ragione di essere rigenerati (e sbagliati) ogni volta.
"""
from __future__ import annotations

# 112 è il numero unico di emergenza europeo, valido per legge in tutti gli
# stati UE + Regno Unito, Svizzera, Norvegia, Islanda e altri.
_EU_SINGLE_EMERGENCY = "112"

# chiave = nome del paese in italiano, minuscolo e senza accenti dove ambiguo.
_COUNTRY_INFO = {
    "italia": {
        "emergency": _EU_SINGLE_EMERGENCY, "currency": "Euro (€)",
        "plug": "Tipo F/L, 230V", "tap_water": "potabile ovunque",
        "tipping": "non obbligatoria; spesso c'è il coperto in conto",
    },
    "francia": {
        "emergency": _EU_SINGLE_EMERGENCY, "currency": "Euro (€)",
        "plug": "Tipo E, 230V", "tap_water": "potabile",
        "tipping": "servizio incluso per legge; si arrotonda e basta",
    },
    "spagna": {
        "emergency": _EU_SINGLE_EMERGENCY, "currency": "Euro (€)",
        "plug": "Tipo F, 230V", "tap_water": "potabile (a Madrid ottima)",
        "tipping": "non attesa; si lascia qualche moneta",
    },
    "portogallo": {
        "emergency": _EU_SINGLE_EMERGENCY, "currency": "Euro (€)",
        "plug": "Tipo F, 230V", "tap_water": "potabile",
        "tipping": "non attesa; attenzione al couvert servito senza ordinarlo (si può rifiutare)",
    },
    "germania": {
        "emergency": _EU_SINGLE_EMERGENCY, "currency": "Euro (€)",
        "plug": "Tipo F, 230V", "tap_water": "potabile",
        "tipping": "5–10%, si dice l'importo totale al momento di pagare",
    },
    "austria": {
        "emergency": _EU_SINGLE_EMERGENCY, "currency": "Euro (€)",
        "plug": "Tipo F, 230V", "tap_water": "potabile, di montagna",
        "tipping": "5–10%",
    },
    "paesi bassi": {
        "emergency": _EU_SINGLE_EMERGENCY, "currency": "Euro (€)",
        "plug": "Tipo F, 230V", "tap_water": "potabile",
        "tipping": "non obbligatoria; carta accettata quasi ovunque, contanti rari",
    },
    "belgio": {
        "emergency": _EU_SINGLE_EMERGENCY, "currency": "Euro (€)",
        "plug": "Tipo E, 230V", "tap_water": "potabile",
        "tipping": "servizio incluso",
    },
    "grecia": {
        "emergency": _EU_SINGLE_EMERGENCY, "currency": "Euro (€)",
        "plug": "Tipo F, 230V", "tap_water": "potabile ad Atene; in molte isole meglio in bottiglia",
        "tipping": "5–10% apprezzata",
    },
    "croazia": {
        "emergency": _EU_SINGLE_EMERGENCY, "currency": "Euro (€)",
        "plug": "Tipo F, 230V", "tap_water": "potabile",
        "tipping": "10% nei ristoranti",
    },
    "regno unito": {
        "emergency": "999 (funziona anche il 112)", "currency": "Sterlina (£)",
        "plug": "Tipo G, 230V — serve l'adattatore", "tap_water": "potabile",
        "tipping": "10–12,5%, spesso già in conto come service charge",
    },
    "irlanda": {
        "emergency": "999 (funziona anche il 112)", "currency": "Euro (€)",
        "plug": "Tipo G, 230V — serve l'adattatore", "tap_water": "potabile",
        "tipping": "10%",
    },
    "svizzera": {
        "emergency": "112", "currency": "Franco svizzero (CHF)",
        "plug": "Tipo J, 230V — serve l'adattatore", "tap_water": "potabile, eccellente; fontane ovunque",
        "tipping": "servizio incluso; si arrotonda",
    },
    "danimarca": {
        "emergency": _EU_SINGLE_EMERGENCY, "currency": "Corona danese (DKK)",
        "plug": "Tipo K/F, 230V", "tap_water": "potabile",
        "tipping": "servizio incluso",
    },
    "svezia": {
        "emergency": _EU_SINGLE_EMERGENCY, "currency": "Corona svedese (SEK)",
        "plug": "Tipo F, 230V", "tap_water": "potabile",
        "tipping": "non attesa; paese quasi senza contanti, porta la carta",
    },
    "norvegia": {
        "emergency": "112 (polizia), 113 (ambulanza)", "currency": "Corona norvegese (NOK)",
        "plug": "Tipo F, 230V", "tap_water": "potabile, eccellente",
        "tipping": "non attesa",
    },
    "repubblica ceca": {
        "emergency": _EU_SINGLE_EMERGENCY, "currency": "Corona ceca (CZK)",
        "plug": "Tipo E, 230V", "tap_water": "potabile",
        "tipping": "10%; occhio agli uffici cambio in centro a Praga",
    },
    "polonia": {
        "emergency": _EU_SINGLE_EMERGENCY, "currency": "Złoty (PLN)",
        "plug": "Tipo E, 230V", "tap_water": "potabile nelle grandi città",
        "tipping": "10%",
    },
    "ungheria": {
        "emergency": _EU_SINGLE_EMERGENCY, "currency": "Fiorino (HUF)",
        "plug": "Tipo F, 230V", "tap_water": "potabile",
        "tipping": "10%; verifica che non sia già in conto",
    },
    "slovenia": {
        "emergency": _EU_SINGLE_EMERGENCY, "currency": "Euro (€)",
        "plug": "Tipo F, 230V", "tap_water": "potabile, ottima",
        "tipping": "non obbligatoria",
    },
}

# Alias e forme che arrivano davvero dal form del cliente (nomi di città,
# inglese, varianti). Mappano sul paese, mai su un'invenzione.
_ALIASES = {
    "uk": "regno unito", "united kingdom": "regno unito", "inghilterra": "regno unito",
    "gran bretagna": "regno unito", "scozia": "regno unito", "galles": "regno unito",
    "england": "regno unito", "scotland": "regno unito",
    "olanda": "paesi bassi", "netherlands": "paesi bassi", "holland": "paesi bassi",
    "france": "francia", "spain": "spagna", "espana": "spagna", "españa": "spagna",
    "germany": "germania", "deutschland": "germania", "austria ": "austria",
    "portugal": "portogallo", "greece": "grecia", "hellas": "grecia",
    "croatia": "croazia", "hrvatska": "croazia", "switzerland": "svizzera",
    "schweiz": "svizzera", "suisse": "svizzera", "czechia": "repubblica ceca",
    "cechia": "repubblica ceca", "czech republic": "repubblica ceca",
    "poland": "polonia", "polska": "polonia", "hungary": "ungheria",
    "magyarorszag": "ungheria", "slovenia ": "slovenia", "sweden": "svezia",
    "norway": "norvegia", "denmark": "danimarca", "danmark": "danimarca",
    "ireland": "irlanda", "eire": "irlanda", "italy": "italia", "belgium": "belgio",
}


# [AGGIUNTO 2026-08-01 — difetto trovato rigenerando il PDF di esempio, non
# dedotto a tavolino] Il campione ha `destinazione: "Siena"` e la scheda del
# paese spariva del tutto: nessun alias copriva i nomi di CITTÀ, che sono
# esattamente la forma in cui la destinazione arriva davvero dal form (quasi
# nessuno scrive "Firenze, Italia"; scrive "Firenze"). L'informazione pratica
# più utile del documento non arrivava alla maggioranza dei clienti — in
# silenzio, perché l'omissione è per costruzione indistinguibile da un paese
# legittimamente fuori tabella.
#
# LA REGOLA DI AMMISSIONE, restrittiva apposta: una città entra qui solo se il
# suo nome, DA SOLO, identifica un paese senza ambiguità. Valencia
# (Spagna/Venezuela), Cordoba (Spagna/Argentina), Toledo (Spagna/Ohio),
# Cambridge (UK/Massachusetts), Birmingham (UK/Alabama), Santiago
# (Cile/Spagna) e Monaco (principato / München) NON ci sono e non devono
# entrarci: da questa tabella dipende un numero di emergenza, e la città
# sbagliata è peggio di nessuna città. Chi scrive "Valencia" resta senza
# scheda — ed è l'esito corretto.
_CITY_TO_COUNTRY = {
    # --- Italia ---
    "roma": "italia", "rome": "italia", "milano": "italia", "milan": "italia",
    "firenze": "italia", "florence": "italia", "venezia": "italia", "venice": "italia",
    "napoli": "italia", "torino": "italia", "turin": "italia", "bologna": "italia",
    "palermo": "italia", "siena": "italia", "verona": "italia", "genova": "italia",
    "bari": "italia", "catania": "italia", "pisa": "italia", "lecce": "italia",
    "matera": "italia", "perugia": "italia", "trieste": "italia", "cagliari": "italia",
    "rimini": "italia", "sorrento": "italia", "positano": "italia", "amalfi": "italia",
    "capri": "italia", "taormina": "italia", "assisi": "italia", "orvieto": "italia",
    "ravenna": "italia", "padova": "italia", "mantova": "italia", "bergamo": "italia",
    "portofino": "italia", "cinque terre": "italia", "alberobello": "italia",
    "siracusa": "italia", "agrigento": "italia", "trapani": "italia", "olbia": "italia",
    "ischia": "italia", "cortina": "italia", "courmayeur": "italia",
    "sardegna": "italia", "sicilia": "italia", "toscana": "italia", "puglia": "italia",
    # --- Francia ---
    "parigi": "francia", "paris": "francia", "nizza": "francia", "marsiglia": "francia",
    "marseille": "francia", "lione": "francia", "lyon": "francia", "bordeaux": "francia",
    "tolosa": "francia", "toulouse": "francia", "strasburgo": "francia",
    "strasbourg": "francia", "cannes": "francia", "avignone": "francia",
    "montpellier": "francia", "nantes": "francia", "lille": "francia",
    "biarritz": "francia", "chamonix": "francia", "versailles": "francia",
    "carcassonne": "francia", "colmar": "francia", "provenza": "francia",
    "costa azzurra": "francia", "normandia": "francia", "bretagna": "francia",
    # --- Spagna ---
    "madrid": "spagna", "barcellona": "spagna", "barcelona": "spagna",
    "siviglia": "spagna", "sevilla": "spagna", "seville": "spagna",
    "granada": "spagna", "malaga": "spagna", "bilbao": "spagna",
    "san sebastian": "spagna", "maiorca": "spagna", "mallorca": "spagna",
    "palma di maiorca": "spagna", "ibiza": "spagna", "tenerife": "spagna",
    "gran canaria": "spagna", "lanzarote": "spagna", "formentera": "spagna",
    "minorca": "spagna", "saragozza": "spagna", "zaragoza": "spagna",
    "salamanca": "spagna", "girona": "spagna", "marbella": "spagna",
    "alicante": "spagna", "benidorm": "spagna", "cadice": "spagna", "ronda": "spagna",
    "andalusia": "spagna", "canarie": "spagna", "baleari": "spagna",
    # --- Portogallo ---
    "lisbona": "portogallo", "lisbon": "portogallo", "lisboa": "portogallo",
    "porto": "portogallo", "oporto": "portogallo", "faro": "portogallo",
    "algarve": "portogallo", "madeira": "portogallo", "funchal": "portogallo",
    "sintra": "portogallo", "coimbra": "portogallo", "braga": "portogallo",
    "evora": "portogallo", "azzorre": "portogallo",
    # --- Germania ---
    "berlino": "germania", "berlin": "germania", "monaco di baviera": "germania",
    "munich": "germania", "munchen": "germania", "münchen": "germania",
    "amburgo": "germania", "hamburg": "germania", "colonia": "germania",
    "cologne": "germania", "koln": "germania", "köln": "germania",
    "francoforte": "germania", "frankfurt": "germania", "stoccarda": "germania",
    "stuttgart": "germania", "dusseldorf": "germania", "düsseldorf": "germania",
    "dresda": "germania", "dresden": "germania", "norimberga": "germania",
    "nuremberg": "germania", "lipsia": "germania", "leipzig": "germania",
    "heidelberg": "germania", "baden-baden": "germania", "potsdam": "germania",
    "baviera": "germania", "foresta nera": "germania",
    # --- Austria ---
    "vienna": "austria", "wien": "austria", "salisburgo": "austria",
    "salzburg": "austria", "innsbruck": "austria", "graz": "austria",
    "hallstatt": "austria", "linz": "austria", "tirolo": "austria",
    # --- Paesi Bassi ---
    "amsterdam": "paesi bassi", "rotterdam": "paesi bassi", "l'aia": "paesi bassi",
    "den haag": "paesi bassi", "the hague": "paesi bassi", "utrecht": "paesi bassi",
    "delft": "paesi bassi", "haarlem": "paesi bassi", "maastricht": "paesi bassi",
    "eindhoven": "paesi bassi", "giethoorn": "paesi bassi", "leida": "paesi bassi",
    "leiden": "paesi bassi",
    # --- Belgio ---
    "bruxelles": "belgio", "brussels": "belgio", "bruges": "belgio",
    "brugge": "belgio", "gand": "belgio", "ghent": "belgio", "gent": "belgio",
    "anversa": "belgio", "antwerp": "belgio", "antwerpen": "belgio",
    "lovanio": "belgio", "leuven": "belgio", "liegi": "belgio", "ostenda": "belgio",
    # --- Grecia ---
    "atene": "grecia", "athens": "grecia", "salonicco": "grecia",
    "thessaloniki": "grecia", "santorini": "grecia", "mykonos": "grecia",
    "creta": "grecia", "crete": "grecia", "heraklion": "grecia", "rodi": "grecia",
    "rhodes": "grecia", "corfu": "grecia", "corfù": "grecia", "zante": "grecia",
    "zakynthos": "grecia", "naxos": "grecia", "paros": "grecia", "milos": "grecia",
    "meteora": "grecia", "delfi": "grecia", "nafplio": "grecia", "chania": "grecia",
    "cicladi": "grecia",
    # --- Croazia ---
    "zagabria": "croazia", "zagreb": "croazia", "spalato": "croazia",
    "split": "croazia", "dubrovnik": "croazia", "zara": "croazia", "zadar": "croazia",
    "rovigno": "croazia", "rovinj": "croazia", "pola": "croazia", "pula": "croazia",
    "hvar": "croazia", "sibenik": "croazia", "plitvice": "croazia",
    "makarska": "croazia", "korcula": "croazia", "istria": "croazia",
    # --- Regno Unito ---
    "londra": "regno unito", "london": "regno unito", "edimburgo": "regno unito",
    "edinburgh": "regno unito", "manchester": "regno unito",
    "liverpool": "regno unito", "glasgow": "regno unito", "oxford": "regno unito",
    "bath": "regno unito", "bristol": "regno unito", "york": "regno unito",
    "leeds": "regno unito", "brighton": "regno unito", "cardiff": "regno unito",
    "belfast": "regno unito", "inverness": "regno unito",
    "cornovaglia": "regno unito", "cotswolds": "regno unito",
    "stonehenge": "regno unito", "canterbury": "regno unito",
    "windsor": "regno unito", "highlands": "regno unito",
    # --- Irlanda ---
    "dublino": "irlanda", "dublin": "irlanda", "galway": "irlanda",
    "cork": "irlanda", "killarney": "irlanda", "limerick": "irlanda",
    "kilkenny": "irlanda", "connemara": "irlanda",
    # --- Svizzera ---
    "zurigo": "svizzera", "zurich": "svizzera", "zürich": "svizzera",
    "ginevra": "svizzera", "geneva": "svizzera", "geneve": "svizzera",
    "berna": "svizzera", "bern": "svizzera", "lucerna": "svizzera",
    "lucerne": "svizzera", "luzern": "svizzera", "losanna": "svizzera",
    "lausanne": "svizzera", "basilea": "svizzera", "basel": "svizzera",
    "interlaken": "svizzera", "zermatt": "svizzera", "lugano": "svizzera",
    "st moritz": "svizzera", "grindelwald": "svizzera", "montreux": "svizzera",
    "engadina": "svizzera",
    # --- Scandinavia ---
    "copenaghen": "danimarca", "copenhagen": "danimarca", "kobenhavn": "danimarca",
    "aarhus": "danimarca", "odense": "danimarca", "skagen": "danimarca",
    "stoccolma": "svezia", "stockholm": "svezia", "goteborg": "svezia",
    "gothenburg": "svezia", "malmo": "svezia", "uppsala": "svezia",
    "kiruna": "svezia", "abisko": "svezia", "visby": "svezia",
    "oslo": "norvegia", "bergen": "norvegia", "tromso": "norvegia",
    "stavanger": "norvegia", "trondheim": "norvegia", "lofoten": "norvegia",
    "geiranger": "norvegia", "alesund": "norvegia", "flam": "norvegia",
    "capo nord": "norvegia", "nordkapp": "norvegia",
    # --- Europa centrale ---
    "praga": "repubblica ceca", "prague": "repubblica ceca",
    "praha": "repubblica ceca", "brno": "repubblica ceca",
    "cesky krumlov": "repubblica ceca", "karlovy vary": "repubblica ceca",
    "olomouc": "repubblica ceca", "plzen": "repubblica ceca",
    "varsavia": "polonia", "warsaw": "polonia", "warszawa": "polonia",
    "cracovia": "polonia", "krakow": "polonia", "danzica": "polonia",
    "gdansk": "polonia", "breslavia": "polonia", "wroclaw": "polonia",
    "poznan": "polonia", "zakopane": "polonia", "torun": "polonia",
    "budapest": "ungheria", "debrecen": "ungheria", "szeged": "ungheria",
    "eger": "ungheria", "pecs": "ungheria", "balaton": "ungheria",
    "lubiana": "slovenia", "ljubljana": "slovenia", "bled": "slovenia",
    "lago di bled": "slovenia", "pirano": "slovenia", "piran": "slovenia",
    "capodistria": "slovenia", "koper": "slovenia", "postumia": "slovenia",
    "postojna": "slovenia", "maribor": "slovenia",
}


def _normalize(text: str) -> str:
    return " ".join(str(text or "").strip().lower().split())


def resolve_country(destination_or_country: str) -> str | None:
    """Dal testo di destinazione al paese in tabella, o `None`.

    Riconosce sia "Francia" sia "Parigi, Francia" sia "Paris, France" —
    perché il campo `destinazione` del form è testo libero. Se non riconosce
    nulla con CERTEZZA, ritorna None: meglio nessuna sezione informazioni
    pratiche che informazioni del paese sbagliato.
    """
    text = _normalize(destination_or_country)
    if not text:
        return None
    if text in _COUNTRY_INFO:
        return text
    if text in _ALIASES:
        return _ALIASES[text]
    # [AGGIUNTO 2026-08-01] Le città DOPO i paesi e gli alias, mai prima: se un
    # giorno una chiave comparisse in entrambe le tabelle, il paese scritto per
    # esteso è sempre l'intenzione più esplicita delle due e deve vincere.
    if text in _CITY_TO_COUNTRY:
        return _CITY_TO_COUNTRY[text]
    # "Parigi, Francia" / "Lisbon, Portugal": cerca il paese come pezzo del
    # testo separato da virgola, non come sottostringa qualunque (per non far
    # scattare "italia" dentro un nome di via).
    parts = [p.strip() for p in text.replace("/", ",").split(",")]
    for part in reversed(parts):
        if part in _COUNTRY_INFO:
            return part
        if part in _ALIASES:
            return _ALIASES[part]
    # Solo se NESSUN pezzo era un paese: "Siena, Toscana" e "Firenze" devono
    # funzionare, ma un paese esplicito scritto in coda vince sempre sulla
    # città scritta in testa — anche quando le due si contraddicono, perché in
    # quel caso è il paese il dato che il cliente ha voluto precisare.
    for part in parts:
        if part in _CITY_TO_COUNTRY:
            return _CITY_TO_COUNTRY[part]
    return None


def country_practical_info(destination_or_country: str) -> dict | None:
    """`{"country", "emergency", "currency", "plug", "tap_water", "tipping"}`
    oppure `None` se il paese non è in tabella — mai un dato inventato."""
    country = resolve_country(destination_or_country)
    if country is None:
        return None
    return {"country": country.title(), **_COUNTRY_INFO[country]}


def known_countries() -> list[str]:
    """Utile ai test e alla manutenzione: cosa copriamo oggi."""
    return sorted(_COUNTRY_INFO)
