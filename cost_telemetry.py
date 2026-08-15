"""
Costo reale per itinerario — src/cost_telemetry.py.

[AGGIUNTO 2026-08-01 — punto 2 del feedback "da investitore" del
2026-08-01: "non sai quanto ti costa produrre un itinerario. È un numero
che si misura in un pomeriggio e che cambia ogni decisione successiva.
Finché non c'è, tutto il resto è opinione."]

Il problema che risolve: un itinerario costa una chiamata a Claude
(grande), UNA CHIAMATA A CLAUDE IN PIÙ PER OGNI LUOGO con guida
tascabile, più i consigli, più il messaggio di recensione, più
Geocoding, Places, Distance Matrix, una cartina statica per giornata e
LiteAPI. Nessuno di questi numeri era mai stato sommato. A 4,90 € di
prezzo di vendita, con la commissione di Stripe che si mangia da sola
circa il 7-8%, la differenza fra "margine del 60%" e "perdo soldi su
ogni viaggio lungo" sta tutta in quella somma.

## Come funziona

Un `Ledger` raccoglie gli eventi; `measure()` lo installa come "corrente"
per il thread/la richiesta in corso, e i moduli che fanno le chiamate lo
alimentano con una riga sola:

    from . import cost_telemetry
    cost_telemetry.record_llm(model, response.usage)
    cost_telemetry.record_api_call("google_places_nearby")

Fuori da un blocco `measure()` quelle funzioni sono **no-op assolute**:
nessuno stato globale, nessun errore, nessun costo. Questo è il motivo
per cui si usa un `ContextVar` invece di passare un parametro a mano
attraverso otto firme di funzione: il conteggio non deve poter rompere la
pipeline, e la pipeline non deve doversi ricordare di propagarlo.

## Onestà sui numeri

I conteggi delle UNITÀ (token, chiamate, elementi di matrice) sono
esatti: vengono dalle risposte reali delle API. I PREZZI per unità no:
sono un listino scritto qui sotto, che i fornitori cambiano quando
vogliono. Per questo ogni voce di listino è sovrascrivibile da variabile
d'ambiente e ogni risultato porta con sé `prezzi_da_verificare: true` e la
data del listino usato. **Un numero che si spaccia per esatto quando non
lo è è peggio di nessun numero.**

Variabili d'ambiente riconosciute (tutte opzionali, tutte numeriche):

    COST_EUR_PER_USD                 cambio usato (default 0.92)
    COST_USD_IN_PER_MTOK_SONNET      $ per milione di token in ingresso
    COST_USD_OUT_PER_MTOK_SONNET     $ per milione di token in uscita
    COST_USD_IN_PER_MTOK_OPUS
    COST_USD_OUT_PER_MTOK_OPUS
    COST_USD_PER_1K_GEOCODING
    COST_USD_PER_1K_PLACES_NEARBY
    COST_USD_PER_1K_DISTANCE_ELEMENTS
    COST_USD_PER_1K_DISTANCE_ELEMENTS_ADVANCED   tariffa con traffico (doppia)
    COST_USD_PER_1K_STATIC_MAPS
    COST_EUR_STRIPE_FIXED            parte fissa della commissione (0.25)
    COST_STRIPE_PERCENT              parte percentuale (1.5 = 1,5%)
    COST_SALE_PRICE_EUR              prezzo di vendita, per calcolare il margine
"""
from __future__ import annotations

import contextvars
import os
from contextlib import contextmanager
from dataclasses import dataclass, field

# Data a cui il listino qui sotto è stato scritto. Compare in ogni risultato:
# serve a capire a colpo d'occhio quanto è vecchia la stima.
LISTINO_DEL = "2026-08-01"

# ---------------------------------------------------------------------------
# Listino (USD per milione di token / USD per 1000 chiamate).
# NON sono verificati dal vivo da questo sandbox: sono i valori di riferimento
# da confermare sui listini ufficiali. Vedi la nota "Onestà sui numeri" sopra.
# ---------------------------------------------------------------------------
_DEFAULT_PRICES = {
    "usd_in_per_mtok_sonnet": 3.0,
    "usd_out_per_mtok_sonnet": 15.0,
    "usd_in_per_mtok_opus": 15.0,
    "usd_out_per_mtok_opus": 75.0,
    "usd_per_1k_geocoding": 5.0,
    "usd_per_1k_places_nearby": 32.0,
    "usd_per_1k_distance_elements": 5.0,
    # [AGGIUNTO 2026-08-01 — verificato sul listino ufficiale di Google]
    # La Distance Matrix ha DUE SKU, non uno. "Essentials" costa 5 $/1000
    # elementi; "Advanced/Pro" ne costa 10 — cioè il DOPPIO — e si attiva da
    # sola nel momento in cui la richiesta contiene informazioni di traffico
    # (`departure_time`) o modificatori di posizione. Finché qui c'era una
    # voce sola a 5 $, ogni richiesta "driving con traffico" veniva contata
    # a metà del suo prezzo reale: sulla prima misura in produzione questo
    # da solo nascondeva circa 0,46 € per itinerario, cioè quasi il 10% del
    # prezzo di vendita.
    "usd_per_1k_distance_elements_advanced": 10.0,
    "usd_per_1k_static_maps": 2.0,
    # [AGGIUNTO 2026-08-03 — task #181] Places Photo: SKU a se', fatturato per
    # foto scaricata, non compreso nella ricerca dei luoghi. E' il motivo per
    # cui `src/foto.py` ha un tetto: a questo prezzo venti foto per itinerario
    # costerebbero circa 0,13 € — piu' delle cartine e del geocoding messi
    # insieme — e nessuno le guarderebbe tutte.
    "usd_per_1k_place_photo": 7.0,
    # LiteAPI: modello a commissione sulla prenotazione, nessun costo per
    # chiamata di ricerca. Contato lo stesso in unità (serve a vedere quante
    # chiamate si fanno), a costo zero finché il contratto resta questo.
    "usd_per_1k_liteapi": 0.0,
}

# Sconto/sovrapprezzo della cache di Anthropic rispetto al prezzo in ingresso:
# la lettura da cache costa circa un decimo, la scrittura circa il 25% in più.
_CACHE_READ_MULTIPLIER = 0.1
_CACHE_WRITE_MULTIPLIER = 1.25

_DEFAULT_EUR_PER_USD = 0.92
_DEFAULT_STRIPE_FIXED_EUR = 0.25
_DEFAULT_STRIPE_PERCENT = 1.5
_DEFAULT_SALE_PRICE_EUR = 4.90

# Etichette leggibili per il resoconto — chiave tecnica → cosa è, per un umano.
_PROVIDER_LABELS = {
    "google_geocoding": "Google Geocoding",
    "google_places_nearby": "Google Places (ricerca luoghi)",
    "google_distance_matrix": "Google Distance Matrix (tempi di percorrenza)",
    "google_distance_matrix_advanced": "Google Distance Matrix con traffico (tariffa Advanced, doppia)",
    "google_static_maps": "Google Static Maps (cartine)",
    "google_place_photo": "Google Places (foto delle attrazioni)",
    "liteapi": "LiteAPI (hotel)",
}

_PROVIDER_PRICE_KEYS = {
    "google_geocoding": "usd_per_1k_geocoding",
    "google_places_nearby": "usd_per_1k_places_nearby",
    "google_distance_matrix": "usd_per_1k_distance_elements",
    "google_distance_matrix_advanced": "usd_per_1k_distance_elements_advanced",
    "google_static_maps": "usd_per_1k_static_maps",
    "google_place_photo": "usd_per_1k_place_photo",
    "liteapi": "usd_per_1k_liteapi",
}


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    return value if value >= 0 else default


def _price(key: str) -> float:
    return _env_float("COST_" + key.upper(), _DEFAULT_PRICES[key])


def eur_per_usd() -> float:
    return _env_float("COST_EUR_PER_USD", _DEFAULT_EUR_PER_USD)


def sale_price_eur() -> float:
    return _env_float("COST_SALE_PRICE_EUR", _DEFAULT_SALE_PRICE_EUR)


def stripe_fee_eur(amount_eur: float) -> float:
    """Commissione di incasso su un pagamento con carta.

    Non è un costo di produzione ma esce dallo stesso euro: tenerla fuori dal
    conto è il modo più facile per convincersi di avere un margine che non c'è.
    """
    fixed = _env_float("COST_EUR_STRIPE_FIXED", _DEFAULT_STRIPE_FIXED_EUR)
    percent = _env_float("COST_STRIPE_PERCENT", _DEFAULT_STRIPE_PERCENT)
    return fixed + amount_eur * percent / 100.0


def _is_opus(model: str) -> bool:
    return "opus" in (model or "").lower()


@dataclass
class LlmCall:
    label: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    def usd(self) -> float:
        suffix = "opus" if _is_opus(self.model) else "sonnet"
        in_rate = _price(f"usd_in_per_mtok_{suffix}") / 1_000_000
        out_rate = _price(f"usd_out_per_mtok_{suffix}") / 1_000_000
        return (
            self.input_tokens * in_rate
            + self.output_tokens * out_rate
            + self.cache_read_tokens * in_rate * _CACHE_READ_MULTIPLIER
            + self.cache_write_tokens * in_rate * _CACHE_WRITE_MULTIPLIER
        )


@dataclass
class ApiCall:
    provider: str
    units: int = 1

    def usd(self) -> float:
        key = _PROVIDER_PRICE_KEYS.get(self.provider)
        if key is None:
            # Fornitore sconosciuto: contato in unità, costo 0. Meglio una voce
            # visibile a zero che una chiamata che sparisce dal conto.
            return 0.0
        return self.units * _price(key) / 1000.0


@dataclass
class Ledger:
    """Raccoglie gli eventi di una singola generazione e ne calcola il costo."""

    label: str = ""
    llm_calls: list[LlmCall] = field(default_factory=list)
    api_calls: list[ApiCall] = field(default_factory=list)

    def add_llm(
        self,
        label: str,
        model: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
    ) -> None:
        self.llm_calls.append(
            LlmCall(
                label=str(label), model=str(model or ""),
                input_tokens=_as_int(input_tokens),
                output_tokens=_as_int(output_tokens),
                cache_read_tokens=_as_int(cache_read_tokens),
                cache_write_tokens=_as_int(cache_write_tokens),
            )
        )

    def add_api_call(self, provider: str, units: int = 1) -> None:
        self.api_calls.append(ApiCall(provider=str(provider), units=max(_as_int(units), 0)))

    # -- totali ------------------------------------------------------------

    def llm_usd(self) -> float:
        return sum(c.usd() for c in self.llm_calls)

    def api_usd(self) -> float:
        return sum(c.usd() for c in self.api_calls)

    def total_usd(self) -> float:
        return self.llm_usd() + self.api_usd()

    def total_eur(self) -> float:
        return self.total_usd() * eur_per_usd()

    def to_dict(self, carryover_eur: float = 0.0) -> dict:
        """Resoconto leggibile, pronto da restituire in una risposta HTTP.

        Tutti gli importi sono in euro e arrotondati a 4 decimali: su
        centesimi di euro per chiamata, arrotondare a 2 nasconderebbe
        esattamente le voci che si vuole vedere.

        `carryover_eur` è il costo già sostenuto nelle FASI PRECEDENTI della
        stessa vendita. Serve perché un cliente paga 4,90 € una volta sola, ma
        il lavoro si svolge in due chiamate HTTP distinte (/v1/itinerary e poi
        /v1/pdf): calcolare il margine su una sola delle due lo farebbe
        sembrare quasi il doppio di quello vero. Make passa a /v1/pdf il
        `costo_produzione_eur` uscito da /v1/itinerary e il margine torna
        quello reale.
        """
        rate = eur_per_usd()
        carryover = max(_as_float(carryover_eur), 0.0)
        per_llm = {}
        for call in self.llm_calls:
            entry = per_llm.setdefault(
                call.label,
                {"chiamate": 0, "modello": call.model, "token_in": 0,
                 "token_out": 0, "euro": 0.0},
            )
            entry["chiamate"] += 1
            entry["token_in"] += call.input_tokens + call.cache_read_tokens + call.cache_write_tokens
            entry["token_out"] += call.output_tokens
            entry["euro"] = round(entry["euro"] + call.usd() * rate, 4)

        per_api = {}
        for call in self.api_calls:
            entry = per_api.setdefault(
                _PROVIDER_LABELS.get(call.provider, call.provider),
                {"chiamate": 0, "unita": 0, "euro": 0.0},
            )
            entry["chiamate"] += 1
            entry["unita"] += call.units
            entry["euro"] = round(entry["euro"] + call.usd() * rate, 4)

        produzione = round(self.total_eur(), 4)
        totale = round(produzione + carryover, 4)
        prezzo = sale_price_eur()
        commissione = round(stripe_fee_eur(prezzo), 4)
        margine = round(prezzo - commissione - totale, 4)
        return {
            "costo_produzione_eur": produzione,
            "costo_fasi_precedenti_eur": round(carryover, 4),
            "costo_totale_eur": totale,
            "costo_modello_eur": round(self.llm_usd() * rate, 4),
            "costo_api_esterne_eur": round(self.api_usd() * rate, 4),
            "dettaglio_modello": per_llm,
            "dettaglio_api": per_api,
            "prezzo_di_vendita_eur": round(prezzo, 2),
            "commissione_incasso_eur": commissione,
            "margine_lordo_eur": margine,
            "margine_lordo_percento": (
                round(margine / prezzo * 100, 1) if prezzo > 0 else None
            ),
            "cambio_eur_per_usd": rate,
            "listino_del": LISTINO_DEL,
            "prezzi_da_verificare": True,
            "nota": (
                "Le UNITÀ (token e chiamate) sono conteggi reali. I PREZZI per "
                "unità vengono dal listino interno del "
                f"{LISTINO_DEL} e vanno confermati sui listini ufficiali dei "
                "fornitori: sovrascrivibili con le variabili d'ambiente COST_*. "
                "Il margine è calcolato su costo_totale_eur (questa fase più "
                "le precedenti) e NON include i costi fissi (Render, Make.com, "
                "dominio) né le rigenerazioni per un cliente insoddisfatto."
            ),
        }


def _as_int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _as_float(value) -> float:
    """Come `_as_int` ma per gli importi. Un `carryover_eur` arrivato come
    stringa da un modulo Make.com (che interpola tutto come testo) non deve
    far fallire il resoconto: nel dubbio vale zero."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
# Registro "corrente" — per richiesta HTTP / per thread.
# ---------------------------------------------------------------------------
_CURRENT: contextvars.ContextVar = contextvars.ContextVar("cost_ledger", default=None)


def current_ledger() -> Ledger | None:
    return _CURRENT.get()


@contextmanager
def measure(label: str = ""):
    """Installa un `Ledger` come corrente per la durata del blocco.

        with cost_telemetry.measure("itinerary") as ledger:
            ...
        ledger.to_dict()

    I blocchi annidati NON si sommano fra loro: il più interno vince finché
    è aperto, e al termine il precedente torna corrente. Serve a poter
    misurare una sotto-fase senza sporcare il totale del chiamante.
    """
    ledger = Ledger(label=label)
    token = _CURRENT.set(ledger)
    try:
        yield ledger
    finally:
        _CURRENT.reset(token)


def record_llm(model: str, usage=None, label: str = "claude", **kwargs) -> None:
    """Registra una chiamata al modello. No-op fuori da `measure()`.

    `usage` è l'oggetto `response.usage` dell'SDK Anthropic (o un dict con
    le stesse chiavi). Qualunque cosa vada storta nella lettura dei campi
    viene ignorata: la telemetria non può far fallire una generazione già
    riuscita. Un conteggio mancante si vede (voce a zero token), un
    itinerario perso no.
    """
    ledger = _CURRENT.get()
    if ledger is None:
        return
    try:
        def _read(name: str) -> int:
            if usage is None:
                return _as_int(kwargs.get(name, 0))
            if isinstance(usage, dict):
                return _as_int(usage.get(name, 0))
            return _as_int(getattr(usage, name, 0))

        ledger.add_llm(
            label=label,
            model=model,
            input_tokens=_read("input_tokens"),
            output_tokens=_read("output_tokens"),
            cache_read_tokens=_read("cache_read_input_tokens"),
            cache_write_tokens=_read("cache_creation_input_tokens"),
        )
    except Exception:  # noqa: BLE001 — vedi docstring
        pass


def record_api_call(provider: str, units: int = 1) -> None:
    """Registra una chiamata a un'API esterna. No-op fuori da `measure()`."""
    ledger = _CURRENT.get()
    if ledger is None:
        return
    try:
        ledger.add_api_call(provider, units)
    except Exception:  # noqa: BLE001 — vedi record_llm
        pass
