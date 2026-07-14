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
        if self.date_start >= self.date_end:
            errors.append("date_start non è precedente a date_end")
        if not isinstance(self.budget_eur, (int, float)):
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
        if not self.destination or not self.destination.strip():
            errors.append("destination è vuota")
        if not self.email or "@" not in self.email:
            errors.append(f"email non valida: '{self.email}'")
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
