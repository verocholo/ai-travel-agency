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
    # "Parigi, Francia" / "Lisbon, Portugal": cerca il paese come pezzo del
    # testo separato da virgola, non come sottostringa qualunque (per non far
    # scattare "italia" dentro un nome di via).
    parts = [p.strip() for p in text.replace("/", ",").split(",")]
    for part in reversed(parts):
        if part in _COUNTRY_INFO:
            return part
        if part in _ALIASES:
            return _ALIASES[part]
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
