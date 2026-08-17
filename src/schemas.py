"""
Schemi dati — rispecchiano 1:1 DATA_STRUCTURES_MAKE.md (DS_TRIP, DS_PAYLOAD_API,
DS_ITINERARY). Uso dataclass + dict, niente dipendenze esterne (no pydantic)
per restare aderenti allo spirito "0 lock-in" del progetto no-code originale.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Optional


VALID_OBJECTIVE_FUNCTIONS = {
    "ENERGY_PACING",
    "FRICTION_SAFETY",
    "WORK_CONNECTIVITY",  # [AGGIUNTO 2026-07-11] quarto objective_function, modulo lavoro_nomadi_digitali
    "EXCLUSIVITY_ZERO_FRICTION",
    "BALANCED",
}


@dataclass
class Trip:
    """DS_TRIP — DATA_STRUCTURES_MAKE.md §NODO 2"""
    email: str
    destination: str
    date_start: str  # ISO YYYY-MM-DD
    date_end: str  # ISO YYYY-MM-DD
    duration_days: int
    budget_eur: float
    budget_mode: str  # "LIMITED" | "UNLIMITED"
    objective_function: str  # vedi VALID_OBJECTIVE_FUNCTIONS
    raw_notes: str = ""
    dest_lat: Optional[float] = None  # aggiunto dal Nodo 2b (geocoding), HTTP_MODULES_REALI.md
    dest_lng: Optional[float] = None

    def validate(self) -> list[str]:
        """[Filter] di validazione — BLUEPRINT_MAKE.md NODO 2.

        [AGGIUNTO 2026-07-11 — audit qualità pre-lancio] Tre gap trovati:
        un budget_eur negativo, una destination vuota, e un'email
        palesemente malformata passavano tutti indenni. Non sono casi
        ipotetici astratti — sono i tipici errori di digitazione/dati
        mancanti di un form Typeform reale. Aggiunti qui, all'origine
        (Nodo 2), non lasciati propagare a valle: stessa filosofia
        "fallisci in modo esplicito e presto" già applicata al resto del
        prototipo (LiteApiError, ClaudeEngineError, GeocodingError).
        """
        errors = []
        # [AGGIUNTO 2026-07-31 — audit di perfezionamento, bug reale eseguito]
        # `validate()` crashava sui dati malformati che dovrebbe RIFIUTARE,
        # quando i campi non erano stringhe: `date_start >= date_end` con un
        # int → `TypeError: '>=' not supported`; `destination.strip()` con un
        # int → `AttributeError`; `"@" in email` con un int → `TypeError`.
        # Raggiungibile in produzione: /v1/refine e /v1/pdf costruiscono
        # `Trip(**body["trip"])` col body grezzo di Make.com e chiamano
        # `.validate()` FUORI dal try/except di parsing → HTTP 500 invece del
        # 400 pulito. Ora ogni campo di tipo sbagliato diventa un errore di
        # validazione nella lista (fallimento esplicito), mai un crash.
        if not isinstance(self.date_start, str) or not isinstance(self.date_end, str):
            errors.append(
                f"date_start/date_end devono essere stringhe ISO (ricevuti: "
                f"{type(self.date_start).__name__}/{type(self.date_end).__name__})"
            )
        elif self.date_start >= self.date_end:
            errors.append("date_start non è precedente a date_end")
        if not isinstance(self.budget_eur, (int, float)) or isinstance(self.budget_eur, bool):
            errors.append("budget_eur non è numerico")
        elif self.budget_eur < 0:
            errors.append(f"budget_eur non può essere negativo (ricevuto: {self.budget_eur})")
        if self.objective_function not in VALID_OBJECTIVE_FUNCTIONS:
            errors.append(
                f"objective_function '{self.objective_function}' non valida "
                f"(attese: {sorted(VALID_OBJECTIVE_FUNCTIONS)})"
            )
        if self.budget_mode not in ("LIMITED", "UNLIMITED"):
            errors.append("budget_mode deve essere LIMITED o UNLIMITED")
        if not isinstance(self.destination, str) or not self.destination.strip():
            errors.append("destination è vuota o non è una stringa")
        if not isinstance(self.email, str) or "@" not in self.email:
            errors.append(f"email non valida: {self.email!r}")
        return errors

    def to_dict(self) -> dict:
        d = asdict(self)
        # dest_lat/dest_lng None finché il Nodo 2b non li popola
        return d


@dataclass
class Hotel:
    id: str
    name: str
    lat: float
    lng: float
    price_night_eur: Optional[float] = None
    stars: Optional[float] = None
    tags: list[str] = field(default_factory=list)
    affiliate_url: str = "[Da Verificare]"
    # [AGGIUNTO 2026-07-11 — richiesta di prodotto di Lorenzo: espandere
    # oltre Booking/hotel classici] Nome leggibile del tipo di proprietà
    # (es. "Apartments", "Villas", "Hotels" — vocabolario reale di LiteAPI,
    # confermato dal vivo su Lisbona: 20/20 risultati reali per
    # Apartments/Villas/Aparthotels/Holiday homes/Private vacation home,
    # non solo teoria di tassonomia). None se il fornitore non lo riporta o
    # se l'id non è tra quelli noti — mai inventato, stesso principio di
    # onestà di affiliate_url="[Da Verificare]". Serve a permettere a
    # Claude di riferirsi correttamente all'alloggio nel testo (es. "nel
    # tuo appartamento" invece di "nel tuo hotel" quando non è un hotel).
    property_type: Optional[str] = None

    @property
    def coord(self) -> str:
        return f"{self.lat},{self.lng}"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class POI:
    id: str
    type: str  # restaurant | museum | activity | ...
    name: str
    lat: float
    lng: float
    energy_tag: str = "MEDIUM"  # LOW | MEDIUM | HIGH
    dietary_tags: list[str] = field(default_factory=list)
    open_days: list[str] = field(default_factory=list)  # Mon..Sun, canonico
    # [AGGIUNTO 2026-08-03 — task #180, richiesta di Lorenzo: «tenendo conto
    # degli orari di apertura delle strutture»] Gli ORARI, non solo i giorni:
    # {"Mon": [["09:00", "19:00"]], ...}. Arrivano dallo stesso campo Google
    # (`regularOpeningHours`) da cui gia' ricavavamo `open_days`, quindi non
    # costano una chiamata in piu' ne' spostano la fascia di fatturazione: fino
    # a oggi li scartavamo e basta. Senza di essi la richiesta di programmare
    # la giornata "tenendo conto degli orari" non era una regola disattesa, era
    # una regola che nessuno — ne' il modello ne' un controllo in Python —
    # aveva i dati per rispettare. `None` = il fornitore non li ha dati, e in
    # quel caso il documento lo dichiara invece di presumere "aperto".
    open_hours: Optional[dict] = None
    affiliate_url: str = "[Da Verificare]"
    # [AGGIUNTO 2026-07-12 — richiesta di Lorenzo: "segnare ogni costo
    # (hotel, ristoranti)"] Google Places API (New) fornisce già questo
    # campo (`priceLevel`) — lo chiediamo nel field mask da tempo (vedi
    # places_client.py) ma finora veniva scartato, mai mappato qui. Fascia
    # di prezzo, non un importo esatto: Google non dà un prezzo preciso per
    # un ristorante o un'attività (a differenza dell'hotel-ancora, che ha
    # `price_night_eur` reale da LiteAPI) — mostrare una fascia (€/€€/€€€)
    # invece di un numero inventato rispetta lo stesso principio di
    # Fedeltà RAG di tutto il resto del progetto: mai un dato che i dati
    # forniti non supportano davvero. None = non specificato dal
    # fornitore (mai un valore inventato per riempire il vuoto). Valori
    # ammessi: "FREE" | "INEXPENSIVE" | "MODERATE" | "EXPENSIVE" |
    # "VERY_EXPENSIVE" | None — vedi src/price_display.py per la
    # conversione in simbolo mostrato al cliente.
    price_level: Optional[str] = None
    # [AGGIUNTI 2026-07-31 — richiesta di Lorenzo: "per i ristoranti è utile
    # che crei un collegamento con il menù del ristorante che spesso trovi su
    # internet ed un altro collegamento con le info utili sul ristorante
    # (indirizzo, numero, ecc...)"]
    # Sono TUTTI campi che Google Places API (New) restituisce già davvero
    # (`websiteUri`, `nationalPhoneNumber`, `formattedAddress`,
    # `googleMapsUri`): finora semplicemente non li chiedevamo nel field mask
    # (vedi places_client.FIELD_MASK) e non c'era dove metterli. Nessuno di
    # questi dati viene MAI inventato: `None` significa "il fornitore non ce
    # l'ha dato", e src/place_links.py ricade su una ricerca onesta invece che
    # su un sito plausibile — stesso principio di Fedeltà RAG del resto.
    # Optional con default None -> `POI(**p)` (service.py) resta retro-
    # compatibile con i payload che non li contengono.
    website: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    google_maps_uri: Optional[str] = None
    # [AGGIUNTI 2026-08-01 — collaudo PDF reale del 2026-08-01, difetti 1/2/3]
    # `rating` era GIÀ nel field mask di places_client (quindi già pagato in
    # ogni chiamata) ma non veniva mappato da nessuna parte: lo chiedevamo a
    # Google e lo buttavamo via. Insieme a `user_rating_count` è il segnale che
    # distingue un'attrazione vera da un risultato di scarto con lo stesso
    # `primaryType` — la differenza fra "Colosseo, 4,7 con 380.000 recensioni" e
    # un ufficio con la stessa etichetta e nessuna recensione. Serve sia per
    # ordinare i POI per rilevanza, sia per scartare il rumore, sia per dare a
    # Claude un motivo esplicito per preferire una tappa a un'altra.
    # `name_language` è il `displayName.languageCode` che Google restituisce
    # accanto al nome: senza di esso non c'era modo di ACCORGERSI che un nome
    # era tornato in una lingua diversa da quella richiesta (difetto 3).
    # Tutti Optional con default: `POI(**p)` in service.py resta
    # retro-compatibile con i payload che non li contengono.
    rating: Optional[float] = None
    user_rating_count: Optional[int] = None
    name_language: Optional[str] = None
    # [AGGIUNTO 2026-08-01 — perché i "Piani B se piove" non potevano esistere]
    # `type` qui sopra è il tipo NORMALIZZATO, e la normalizzazione collassa
    # l'intera tassonomia di Google in quattro sole etichette: restaurant,
    # museum, shopping, activity. Un parco, una spiaggia, un belvedere, uno
    # stadio e un centro congressi diventano tutti, indistintamente,
    # "activity". Il che significa che qualunque logica basata sull'ESSERE
    # ALL'APERTO — e il piano B per la pioggia è esattamente quella — stava
    # interrogando un dato che era già stato distrutto a monte: la lista dei
    # tipi "outdoor" in tips_generator.py aveva intersezione VUOTA con i valori
    # realmente possibili, quindi `days_needing_rain_plan()` restituiva sempre
    # [] e la sezione non poteva comparire in nessun PDF, mai.
    # Conserviamo quindi il `primaryType` grezzo di Google accanto a quello
    # normalizzato: costa zero (è già nella risposta) e rende di nuovo
    # possibile una domanda che l'itinerario ha bisogno di porre.
    primary_type: Optional[str] = None
    # [AGGIUNTI 2026-08-03 — task #181, richiesta di Lorenzo: «inserisci alcune
    # immagini con senso» e «meno testo piu' immagini, non deve essere noioso»]
    # `photo_ref` NON e' una foto: e' il nome-risorsa della foto dentro Google
    # ("places/<id>/photos/<ref>"), che arriva gratis dentro la stessa risposta
    # di ricerca dei POI. Scaricare l'immagine vera e' una chiamata SEPARATA e
    # a pagamento (vedi `places_client.fetch_place_photo`), quindi il ref sta
    # qui e la spesa la decide chi costruisce il documento, non chi cerca i
    # luoghi.
    # `photo_credit` e' l'attribuzione dell'autore che Google OBBLIGA a
    # mostrare accanto alla foto. Sta accanto al ref e non altrove per una
    # ragione pratica: se un giorno si perde per strada, la foto non viene
    # stampata affatto (vedi `poi_pdf.build_guide_html`). Meglio una pagina
    # senza foto che una foto altrui senza il nome di chi l'ha scattata su un
    # documento che vendiamo.
    photo_ref: Optional[str] = None
    photo_credit: Optional[str] = None
    # [AGGIUNTI 2026-08-17 — task #226, richiesta di Lorenzo: «foto diverse,
    # non usare sempre le solite tre ripetute».] La SECONDA fotografia del
    # luogo, quando Google ne restituisce piu' di una — stessa logica del
    # campo sopra, indice diverso. Serve a `src/foto.py` per dare a un
    # luogo che compare in piu' punti del documento (la sua guida, e le
    # bande "altre tappe" di altre guide) un'immagine diversa da quella
    # gia' usata come sua di apertura.
    photo_ref_2: Optional[str] = None
    photo_credit_2: Optional[str] = None

    @property
    def coord(self) -> str:
        return f"{self.lat},{self.lng}"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TravelTime:
    origin_id: str
    dest_id: str
    minutes: int
    mode: str = "driving"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ApiPayload:
    """DATI_API_FORNITI — DATA_STRUCTURES_MAKE.md §NODO 7"""
    hotels: list[Hotel]
    travel_times: list[TravelTime]
    poi: list[POI]

    def to_dict(self) -> dict:
        return {
            "hotels": [h.to_dict() for h in self.hotels],
            "travel_times": [t.to_dict() for t in self.travel_times],
            "poi": [p.to_dict() for p in self.poi],
        }


def build_full_payload(trip: Trip, api_payload: ApiPayload) -> dict:
    """DS_PAYLOAD_API completo — questo è il {{7.json}} del Nodo 7."""
    return {
        "trip": trip.to_dict(),
        "DATI_API_FORNITI": api_payload.to_dict(),
    }
