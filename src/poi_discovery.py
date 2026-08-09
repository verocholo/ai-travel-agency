"""
NODO 5b — Composizione dell'insieme di POI.

[NUOVO 2026-08-01 — collaudo del primo PDF venduto davvero]

Perché questo modulo esiste. Il collaudo ha restituito nove POI per un
itinerario di tre giorni: sette ristoranti e due attrazioni. Da quel momento in
poi nessun prompt, nessun modello e nessuna revisione grafica avrebbero potuto
produrre un buon itinerario, perché l'itinerario non può proporre visite che
non ha — e infatti il PDF conteneva quattro blocchi vuoti e attività da tre ore
per cose che ne richiedono quaranta minuti. Il cliente lo ha letto come
"itinerario povero". Era, alla lettera, un problema di ingredienti.

Tre cause, tutte nella singola richiesta che facevamo a Google:

1. Una sola ricerca, centrata sul centroide della città. In una città grande il
   centroide non è dove si dorme né dove si visita: è un punto medio che non
   corrisponde a niente.
2. Ordinamento per DISTANZA. Le cose più vicine a un punto qualsiasi di un
   centro urbano sono bar e ristoranti; i monumenti stanno dove stanno.
3. `maxResultCount` a 9. Google fattura la Nearby Search A RICHIESTA, non a
   risultato: chiedere venti luoghi costa esattamente quanto chiederne nove.
   Stavamo lasciando sul tavolo undici risultati gratis per richiesta.

La soluzione qui è una ricerca in DUE passate, con due centri diversi perché
rispondono a due domande diverse:

- «Che cosa vale la pena vedere in questa destinazione?» → centro sul centroide
  della destinazione, raggio proporzionato alla sua dimensione reale (dal
  viewport del geocoding, vedi `geocoding._viewport_radius_m`), ordinamento per
  rilevanza.
- «Dove mangio, partendo da dove dormo?» → centro sull'HOTEL-ANCORA, raggio
  pedonale. Un ristorante eccellente dall'altra parte della città è, per un
  turista senza auto alle nove di sera, un ristorante che non esiste.

Costo: una richiesta Places in più per itinerario (32 $/1000 richieste, cioè
circa 0,029 € in più). A fronte di questo, la correzione sul traffico della
Distance Matrix fatta lo stesso giorno ne libera circa 0,46 €. Il saldo della
giornata resta ampiamente positivo.
"""
from __future__ import annotations

from . import places_client
from .schemas import POI

# Raggio pedonale attorno all'hotel per la passata "dove mangio". 1200 m è
# circa un quarto d'ora di cammino: oltre, dopo cena e al buio, in una città
# che non si conosce, un consiglio smette di essere un consiglio.
HOTEL_FOOD_RADIUS_M = 1200

# Raggio di ripiego quando il geocoding non fornisce un viewport utilizzabile.
# È il valore storico, mantenuto apposta: un default che cambia in silenzio è
# un default che nessuno ha deciso.
FALLBACK_DESTINATION_RADIUS_M = 3000

# Quanti risultati chiedere per passata. Vedi sopra: è gratis. Il tetto di 20 è
# il massimo consentito da `places:searchNearby`.
MAX_RESULTS_PER_PASS = 20

# Quota massima di ristoranti nell'insieme finale. Nel collaudo reale erano
# sette su nove: il 78 % del "materiale" per costruire tre giorni di viaggio
# era cibo. Con tre pasti al giorno al massimo, e non tutti da consigliare, una
# quota attorno al 40 % è abbondante e lascia spazio a ciò che si va a vedere.
MAX_FOOD_SHARE = 0.40


def split_types_by_food(included_types: list[str] | None) -> tuple[list[str], list[str]]:
    """Separa i tipi richiesti in (cibo, non-cibo) usando la stessa tassonomia
    già usata per normalizzare i POI — nessuna seconda lista da tenere
    allineata a mano.

    `None` significa "i quattro tipi di default": lo espandiamo esplicitamente
    qui, perché le due passate hanno bisogno di sapere quali tipi chiedere e
    non possono delegare il default al livello sotto.
    """
    # `None` e `[]` NON sono la stessa cosa e vanno distinti PRIMA del test di
    # verità, altrimenti `[]` (= nessun filtro, tutti i tipi) viene silenziosamente
    # tradotto nelle quattro categorie di default — esattamente lo stesso
    # scambio che il 2026-07-31 rendeva `freshness_check` un generatore di
    # falsi allarmi. Trovato da un test, non in produzione, questa volta.
    types = list(places_client._DEFAULT_INCLUDED_TYPES) if included_types is None else list(included_types)
    if not types:  # [] = nessun filtro; entrambe le passate restano senza filtro
        return [], []
    food = [t for t in types if places_client._TYPE_NORMALIZE.get(t) == "restaurant"]
    other = [t for t in types if places_client._TYPE_NORMALIZE.get(t) != "restaurant"]
    return food, other


def _dedupe_by_id(pois: list[POI]) -> list[POI]:
    seen: set[str] = set()
    out: list[POI] = []
    for poi in pois:
        if poi.id in seen:
            continue
        seen.add(poi.id)
        out.append(poi)
    return out


def compose(pois_other: list[POI], pois_food: list[POI], limit: int) -> list[POI]:
    """Compone l'insieme finale bilanciando visite e ristoranti.

    Funzione pura: l'intera regola di bilanciamento è qui, testabile senza
    rete. Prima si riempie la quota cibo (al massimo `MAX_FOOD_SHARE` del
    totale, almeno un ristorante se ne esiste uno), poi tutto il resto va alle
    visite; se una delle due categorie non basta a riempire la sua quota,
    l'altra la eredita invece di lasciare posti vuoti.
    """
    if limit <= 0:
        return []
    ranked_other = places_client.rank_by_relevance(_dedupe_by_id(pois_other))
    seen_other = {p.id for p in ranked_other}
    ranked_food = places_client.rank_by_relevance(
        [p for p in _dedupe_by_id(pois_food) if p.id not in seen_other]
    )
    food_quota = min(len(ranked_food), max(1, int(limit * MAX_FOOD_SHARE))) if ranked_food else 0
    other_quota = limit - food_quota
    chosen_other = ranked_other[:other_quota]
    # La categoria che avanza posti li cede all'altra.
    leftover = limit - len(chosen_other) - food_quota
    if leftover > 0:
        food_quota = min(len(ranked_food), food_quota + leftover)
    chosen_food = ranked_food[:food_quota]
    leftover = limit - len(chosen_other) - len(chosen_food)
    if leftover > 0:
        chosen_other = ranked_other[: other_quota + leftover]
    return _dedupe_by_id(chosen_other + chosen_food)


def discover(
    *,
    dest_lat: float,
    dest_lng: float,
    api_key: str,
    included_types: list[str] | None = None,
    anchor_lat: float | None = None,
    anchor_lng: float | None = None,
    region_code: str | None = None,
    destination_radius_m: int | None = None,
    limit: int = 13,
    search_fn=None,
) -> list[POI]:
    """Esegue le due passate e restituisce l'insieme composto.

    `search_fn` è iniettabile per i test (firma di
    `places_client.search_nearby`). Il fallimento della SECONDA passata non
    fa fallire la prima: stesso principio di resilienza già applicato alle
    modalità non primarie della Distance Matrix — meglio un insieme parziale
    che nessun insieme.
    """
    search = search_fn or places_client.search_nearby
    radius = destination_radius_m or FALLBACK_DESTINATION_RADIUS_M
    food_types, other_types = split_types_by_food(included_types)

    # Passata 1 — che cosa vedere. Centro: la destinazione.
    pois_other = search(
        dest_lat, dest_lng, api_key,
        radius_m=radius, max_results=MAX_RESULTS_PER_PASS,
        included_types=other_types or included_types,
        region_code=region_code,
    )

    # Passata 2 — dove mangiare. Centro: l'hotel, se lo conosciamo.
    pois_food: list[POI] = []
    if food_types:
        food_lat = anchor_lat if anchor_lat is not None else dest_lat
        food_lng = anchor_lng if anchor_lng is not None else dest_lng
        food_radius = HOTEL_FOOD_RADIUS_M if anchor_lat is not None else min(radius, HOTEL_FOOD_RADIUS_M * 2)
        try:
            pois_food = search(
                food_lat, food_lng, api_key,
                radius_m=food_radius, max_results=MAX_RESULTS_PER_PASS,
                included_types=food_types,
                region_code=region_code,
            )
        except Exception as e:  # noqa: BLE001 — vedi docstring: resilienza deliberata
            print(f"⚠️  poi_discovery: passata ristoranti fallita, proseguo con le sole visite: {e}")
            pois_food = []

    # Se la prima passata ha già restituito ristoranti (perché `included_types`
    # era [] o non separabile), non li buttiamo: li spostiamo nel secchio
    # giusto, così la quota cibo li governa comunque.
    from_other_food = [p for p in pois_other if p.type == "restaurant"]
    if from_other_food:
        pois_other = [p for p in pois_other if p.type != "restaurant"]
        pois_food = pois_food + from_other_food

    pois_other = places_client.drop_low_signal(pois_other)
    pois_food = places_client.drop_low_signal(pois_food)
    return compose(pois_other, pois_food, limit)
