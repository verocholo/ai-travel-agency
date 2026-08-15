"""
NUOVO 2026-07-11 — livello "Moduli Verticali" dell'architettura
"Nucleo Universale + Moduli Verticali" decisa con Lorenzo (vedi
prototipo-status.md nel progetto Claude). Un TravelModule definisce SOLO
ciò che è specifico di un tipo di viaggio — oggi solo le categorie
aggiuntive da chiedere a Google Places. Il nucleo (fetch HTTP, Fedeltà
RAG, format compliance, filtro temporale) resta identico per tutti i
moduli e vive altrove (places_client.py, validator.py, ecc.) — non
duplicato qui.

Primo modulo implementato: "sport_active_travel" (il beachhead attuale,
l'unico oggi rivolto al pubblico). Risolve il gap ENERGY_PACING/
includedTypes segnalato in Fase 3 del piano: prima l'unica richiesta a
Places filtrava su ["restaurant","tourist_attraction","museum","park"] —
nessuna categoria sportiva veniva mai richiesta, quindi energy_tag=HIGH
(il trigger di ENERGY_PACING) non poteva mai scattare da dati Places
reali. Le categorie sportive aggiunte qui vengono dalla tassonomia
ufficiale Google Places (New), categoria "Sports", già recuperata e
verificata in Fase 3 (vedi CHANGELOG.md) — non ipotizzate a mano.

Secondo modulo implementato (2026-07-11): "famiglia_con_bambini". Stessa
logica: categorie verificate sulla tassonomia ufficiale Google Places
(New) via fetch diretto della pagina developers.google.com (non
ipotizzate a mano), prese dalle tabelle "Entertainment and Recreation" e
"Natural Features".

Terzo modulo implementato (2026-07-11): "lavoro_nomadi_digitali". A
differenza dei primi due, "lavoro" non aveva alcun ramo dedicato in
`triage.py::deduce_objective_function()` — sarebbe finito silenziosamente
su BALANCED. Aggiunto un quarto objective_function, WORK_CONNECTIVITY, in
`SYSTEM_PROMPT_MASTER.md` §[DYNAMIC_OBJECTIVE_FUNCTION] e nello switch di
`triage.py`, seguendo esattamente il meccanismo di estensione già
previsto nelle "Note di design" del system prompt.

Prossimi moduli (luna di miele, ecc.) si aggiungono qui allo stesso modo,
ciascuno con le proprie categorie — vedi prototipo-status.md per la
sequenza concordata (costruzione in parallelo, apertura al pubblico
modulo per modulo).
"""
from __future__ import annotations
from dataclasses import dataclass

# [AGGIUNTO 2026-07-13 (ter) — categoria shopping, confermata come
# miglioramento generale di prodotto via AskUserQuestion] Importata da
# places_client.py (unica fonte di verità sulla tassonomia curata di
# tipi "Shopping") invece di essere ridichiarata qui — stesso principio
# "anti-desync" già seguito altrove nel progetto (vedi
# itinerary_utils.py/price_display.py): due liste parallele della stessa
# categoria in due file diversi sono esattamente la classe di bug già
# trovata e corretta in passato (vedi BLUEPRINT_MAKE.md, ramo
# WORK_CONNECTIVITY mancante in una copia ma non nell'altra).
from .places_client import _SHOPPING_TYPES


@dataclass(frozen=True)
class TravelModule:
    id: str
    name: str
    included_place_types: list[str]


# Le 4 categorie originali — restano valide per qualsiasi modulo:
# ristorazione e cultura a basso carico sono rilevanti indipendentemente
# dal tipo di viaggio. [ESTESO 2026-07-13 (ter)] + le categorie
# "Shopping" curate (vedi places_client.py::_SHOPPING_TYPES): shopping è
# rilevante quanto ristorazione/cultura per QUALSIASI tipo di viaggio,
# non specifico di un modulo verticale come sport/famiglia/lavoro — resta
# quindi nel nucleo universale, non in un modulo dedicato.
_BASE_TYPES = ["restaurant", "tourist_attraction", "museum", "park"] + _SHOPPING_TYPES

# Categoria "Sports" della tassonomia ufficiale Google Places (New),
# fonte: developers.google.com/maps/documentation/places/web-service/place-types
# (verificata 2026-07-10). Sottoinsieme rilevante per tennis/padel e
# sport agonistico amatoriale in generale — esclusi tipi chiaramente
# fuori target per questo modulo (es. "fishing_pond", "ski_resort").
_SPORT_TYPES = [
    "athletic_field",
    "fitness_center",
    "golf_course",
    "gym",
    "ice_skating_rink",
    "sports_activity_location",
    "sports_club",
    "sports_complex",
    "stadium",
    "swimming_pool",
    "tennis_court",
]

# Categorie "Entertainment and Recreation" + "Natural Features" rilevanti
# per famiglie con bambini, fonte: developers.google.com/maps/documentation/
# places/web-service/place-types (verificata 2026-07-11 con fetch diretto
# della pagina, non ipotizzata a mano). Esclusi deliberatamente
# "childrens_camp" (struttura di custodia/campo estivo, non un'attrazione
# da itinerario di viaggio) e attrazioni da fiera permanente troppo di
# nicchia per un primo modulo (es. "dance_hall", "karaoke", "casino" —
# fuori target famiglia).
_FAMILY_TYPES = [
    "amusement_center",
    "amusement_park",
    "aquarium",
    "beach",
    "botanical_garden",
    "ferris_wheel",
    "go_karting_venue",
    "indoor_playground",
    "miniature_golf_course",
    "picnic_ground",
    "roller_coaster",
    "water_park",
    "wildlife_park",
    "wildlife_refuge",
    "zoo",
]

# Categorie "Business" + "Entertainment and Recreation"/"Education"
# rilevanti per lavoro da remoto/nomadi digitali, fonte:
# developers.google.com/maps/documentation/places/web-service/place-types
# (verificata 2026-07-11 con fetch diretto della pagina). "cafe" è incluso
# esplicitamente perché molti nomadi digitali lavorano da lì — è già
# normalizzato a type="restaurant"/energy_tag=LOW tramite
# _FOOD_AND_DRINK_TYPES in places_client.py, qui serve solo per essere
# effettivamente RICHIESTO a Places (altrimenti "restaurant" da solo non
# lo includerebbe: sono due primaryType distinti nella tassonomia).
_WORK_TYPES = [
    "business_center",
    "cafe",
    "coworking_space",
    "internet_cafe",
    "library",
]

MODULES: dict[str, TravelModule] = {
    "sport_active_travel": TravelModule(
        id="sport_active_travel",
        name="Sport & Active Travel",
        included_place_types=_BASE_TYPES + _SPORT_TYPES,
    ),
    "famiglia_con_bambini": TravelModule(
        id="famiglia_con_bambini",
        name="Famiglia con bambini",
        included_place_types=_BASE_TYPES + _FAMILY_TYPES,
    ),
    "lavoro_nomadi_digitali": TravelModule(
        id="lavoro_nomadi_digitali",
        name="Lavoro & Nomadi Digitali",
        included_place_types=_BASE_TYPES + _WORK_TYPES,
    ),
}

DEFAULT_MODULE_ID = "sport_active_travel"


def get_module(module_id: str = DEFAULT_MODULE_ID) -> TravelModule:
    """Solleva ValueError su id sconosciuto invece di restituire None in
    silenzio — stesso principio "fallisci in modo esplicito" già usato
    altrove nel prototipo (es. LiteApiError, ClaudeEngineError)."""
    try:
        return MODULES[module_id]
    except KeyError:
        raise ValueError(f"Modulo sconosciuto: {module_id!r}. Disponibili: {list(MODULES)}")


# [AGGIUNTO 2026-07-11] BUG CRITICO trovato e risolto: pipeline.py::run_live()
# chiamava sempre get_module(DEFAULT_MODULE_ID), cioè SEMPRE
# "sport_active_travel", ignorando completamente trip.objective_function.
# Risultato: nonostante 3 moduli verticali completi e testati, in modalità
# --mode live (l'unica che chiama Google Places per davvero) solo le
# categorie sportive potevano mai essere richieste — famiglia e lavoro
# erano funzionalmente inerti per qualunque cliente reale. Mai scoperto
# prima perché run_mock() bypassa modules.py del tutto (usa payload
# pre-costruiti in mock_rag_data.py) e pipeline.py non aveva alcun test
# dedicato. Risolto con questa mappa esplicita 1:1 objective_function ->
# modulo, usata da run_live() al posto dell'hardcode.
#
# BALANCED e EXCLUSIVITY_ZERO_FRICTION non hanno ancora un modulo verticale
# dedicato (nessuna categoria Places specifica per "lusso generico" o
# "nessuna preferenza dichiarata" è stata ancora costruita/verificata) —
# per questi il fallback esplicito e documentato è DEFAULT_MODULE_ID
# (sport_active_travel), che comunque include le 4 categorie base
# (ristorazione, cultura, parchi) valide per qualsiasi tipo di viaggio.
# Questo NON è lo stesso bug: qui il fallback è una scelta esplicita e
# testata per objective_function senza modulo dedicato, non un hardcode
# che ignora silenziosamente tutti gli altri casi.
OBJECTIVE_FUNCTION_TO_MODULE: dict[str, str] = {
    "ENERGY_PACING": "sport_active_travel",
    "FRICTION_SAFETY": "famiglia_con_bambini",
    "WORK_CONNECTIVITY": "lavoro_nomadi_digitali",
    "EXCLUSIVITY_ZERO_FRICTION": DEFAULT_MODULE_ID,  # fallback esplicito, nessun modulo dedicato ancora
    "BALANCED": DEFAULT_MODULE_ID,  # fallback esplicito, nessun modulo dedicato ancora
}


def get_module_for_objective_function(objective_function: str) -> TravelModule:
    """Sceglie il modulo verticale corretto in base a trip.objective_function.
    Usata da pipeline.py::run_live() al posto dell'hardcode precedente (vedi
    commento sopra e CHANGELOG.md per i dettagli del bug). Un
    objective_function non presente nella mappa (non dovrebbe accadere,
    dato che VALID_OBJECTIVE_FUNCTIONS in schemas.py è la fonte di verità
    validata da Trip.validate() prima che questa funzione venga chiamata)
    fa comunque fallback esplicito a DEFAULT_MODULE_ID invece di sollevare
    un errore — coerente con il fatto che BALANCED/EXCLUSIVITY_ZERO_FRICTION
    già usano lo stesso fallback per design, non per assenza di controllo."""
    module_id = OBJECTIVE_FUNCTION_TO_MODULE.get(objective_function, DEFAULT_MODULE_ID)
    return get_module(module_id)
