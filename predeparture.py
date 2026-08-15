"""
NUOVO 2026-08-01 — "Prima di partire": promemoria e numeri utili.

Aggiunta mia alla lista di Lorenzo, sotto la voce che ha scritto lui:
  "io credo che anche tu abbia delle bellissime idee di miglioramento oppure
   qualche funzione da aggiungere per cui aggiungile o migliora, stupiscimi"

COSA RISOLVE, IN CONCRETO
--------------------------
Il documento diceva al cliente tutto su cosa fare UNA VOLTA ARRIVATO, e niente
su cosa fare la sera prima. Ma il momento in cui un itinerario si rompe non è
il martedì al museo: è il lunedì all'aeroporto, senza il biglietto prenotato,
con la carta bloccata per l'estero e l'indirizzo dell'hotel dentro una mail che
non si apre perché non c'è rete.

PERCHÉ È TUTTO DETERMINISTICO (NESSUNA CHIAMATA A CLAUDE)
----------------------------------------------------------
Due ragioni, entrambe forti:

1. SICUREZZA. Il numero di emergenza è il dato del documento in cui un errore
   fa il danno più grave e più veloce. `local_info.py` esiste esattamente per
   questo — tabella scritta a mano, verificabile — e finora alimentava solo il
   prompt dei consigli, cioè finiva comunque nelle mani di un modello che
   poteva parafrasarlo. Qui viene stampato TALE E QUALE, senza intermediari.

2. COSTO E LATENZA. Questa sezione non aggiunge un solo token né un solo
   millisecondo alla generazione: è una lettura di dati che abbiamo già.
   Dentro un tetto di 300 secondi su Make, ogni sezione che non chiede nulla a
   nessuno è una sezione che possiamo permetterci sempre.

LA REGOLA DI ONESTÀ, IDENTICA AL RESTO DEL PRODOTTO
-----------------------------------------------------
Ogni voce della checklist o è universalmente vera per chiunque parta, o è
ancorata a un dato REALE di QUESTO viaggio (l'indirizzo dell'hotel, i musei
effettivamente in programma, la valuta del paese). Nessuna voce generica
inventata per far sembrare la lista più lunga: una checklist di venti punti in
cui tre non c'entrano nulla viene abbandonata al quarto.
"""
from __future__ import annotations

from . import local_info

# I tipi che, nella tassonomia già normalizzata di `places_client`, indicano
# qualcosa che si visita con un biglietto — e che quindi ha senso citare nella
# riga "prenota prima di partire".
_BOOKABLE_TYPES = {"museum"}

# Oltre questo numero di luoghi citati la riga diventa un elenco illeggibile:
# si nominano i primi e si dice quanti sono gli altri.
_MAX_NAMED_PLACES = 4


def _used_poi_ids(itinerary: dict | None) -> list[str]:
    """Gli id nell'ordine di apparizione, senza ripetizioni — l'ordine è
    l'informazione: il primo museo in programma è quello che scade prima."""
    seen: list[str] = []
    known: set[str] = set()
    for day in (itinerary or {}).get("days") or []:
        if not isinstance(day, dict):
            continue
        for block in day.get("blocks") or []:
            if not isinstance(block, dict):
                continue
            poi_id = block.get("poi_id")
            if isinstance(poi_id, str) and poi_id and poi_id not in known:
                known.add(poi_id)
                seen.append(poi_id)
    return seen


def _name_list(names: list[str]) -> str:
    """"A, B e altri 3" — mai un elenco di venti nomi in una riga sola."""
    if not names:
        return ""
    if len(names) <= _MAX_NAMED_PLACES:
        if len(names) == 1:
            return names[0]
        return ", ".join(names[:-1]) + " e " + names[-1]
    extra = len(names) - _MAX_NAMED_PLACES
    return ", ".join(names[:_MAX_NAMED_PLACES]) + f" e altri {extra}"


def build_country_card(trip) -> dict | None:
    """La scheda pratica del paese, presa TALE E QUALE da `local_info`.

    `None` quando il paese non è in tabella: l'omissione è l'esito voluto —
    vedi il docstring di `local_info.py`. Meglio nessuna riga che un numero di
    emergenza plausibile.
    """
    destination = _attr(trip, "destination")
    if not destination:
        return None
    return local_info.country_practical_info(destination)


def build_checklist(trip, itinerary: dict | None, hotels=None, pois=None) -> list[dict]:
    """La lista di controllo della sera prima.

    Ritorna `[{"title", "detail"}]` nell'ordine in cui ha senso spuntarla:
    prima ciò che, se manca, ti blocca in aeroporto; poi ciò che ti fa perdere
    soldi; poi ciò che ti fa perdere tempo sul posto.

    Non solleva mai: un ingrediente mancante toglie la sua riga, non il resto
    della lista.
    """
    items: list[dict] = []
    country = build_country_card(trip)
    currency = (country or {}).get("currency") or ""
    is_euro = "euro" in currency.lower()

    items.append({
        "title": "Documento d'identità valido per tutta la durata del viaggio",
        "detail": (
            "Controlla la data di scadenza, non solo che il documento ci sia: "
            "è l'unica voce di questa lista che non si può rimediare all'ultimo."
        ),
    })

    # --- Alloggio: indirizzo e telefono, scritti qui e non in una mail -----
    hotel = None
    for candidate in hotels or []:
        if candidate is not None:
            hotel = candidate
            break
    if hotel is not None:
        name = _attr(hotel, "name")
        address = _attr(hotel, "address")
        phone = _attr(hotel, "phone")
        bits = [b for b in (name, address) if b]
        if bits:
            detail = (
                "Salvalo sul telefono in un posto che si apre SENZA rete: "
                + " · ".join(bits)
            )
            if phone:
                detail += f" · tel. {phone}"
            detail += (
                ". Serve al controllo passaporti, al tassista e a te, la sera "
                "in cui il telefono è al 4%."
            )
            items.append({
                "title": "Indirizzo e telefono dell'alloggio, offline",
                "detail": detail,
            })

    # --- Prenotazioni: solo luoghi REALMENTE in programma -------------------
    poi_by_id = {}
    for poi in pois or []:
        poi_id = _attr(poi, "id")
        if poi_id:
            poi_by_id[poi_id] = poi
    bookable = []
    for poi_id in _used_poi_ids(itinerary):
        poi = poi_by_id.get(poi_id)
        if poi is None:
            continue
        if _attr(poi, "type") in _BOOKABLE_TYPES:
            name = _attr(poi, "name")
            if name:
                bookable.append(name)
    if bookable:
        items.append({
            "title": "Biglietti a orario per i luoghi che li richiedono",
            "detail": (
                f"In programma ci sono {_name_list(bookable)}. Per i musei più "
                "visitati la fascia oraria si esaurisce con giorni di anticipo, "
                "e la coda senza prenotazione è la voce che fa saltare il resto "
                "della giornata. Il link al sito ufficiale è accanto a ciascun "
                "luogo nel programma: comprare lì evita il sovrapprezzo dei "
                "rivenditori."
            ),
        })

    # --- Pagamenti: la riga cambia davvero in base alla valuta reale --------
    if country:
        if is_euro:
            payment_detail = (
                "Avvisa la banca che sarai all'estero e porta una seconda carta "
                "di un circuito diverso, tenuta separata dalla prima: una carta "
                "bloccata di sabato non si sblocca prima di lunedì."
            )
        else:
            payment_detail = (
                f"La valuta locale è {currency}: agli sportelli e nei negozi "
                "rifiuta sempre l'offerta di pagare \"in euro\" (conversione "
                "dinamica) — il tasso applicato è peggiore, ogni volta. Avvisa "
                "la banca del viaggio e porta una seconda carta di un circuito "
                "diverso, tenuta separata dalla prima."
            )
        items.append({
            "title": "Carte abilitate all'estero, e una di riserva",
            "detail": payment_detail,
        })

    items.append({
        "title": "Mappa della città scaricata offline",
        "detail": (
            "Su Google Maps: cerca la città, poi \"Scarica mappa offline\". "
            "Tutti i link di questo documento aprono comunque la posizione "
            "giusta, ma il percorso si calcola anche senza rete solo se la "
            "mappa è già sul telefono."
        ),
    })

    if country and country.get("plug"):
        items.append({
            "title": "Adattatore per le prese e una batteria esterna",
            "detail": (
                f"Prese {country['plug']}. La batteria esterna non è un lusso: "
                "questo itinerario si legge dal telefono, e lo schermo acceso "
                "tutto il giorno con la mappa aperta consuma più di quanto "
                "chiunque preveda."
            ),
        })

    items.append({
        "title": "Una copia di questo PDF anche offline",
        "detail": (
            "Salvalo nei file del telefono, non solo nella mail: la mail ha "
            "bisogno di rete, il file no."
        ),
    })

    return items


def _attr(obj, name):
    """Legge un campo sia da un oggetto (`POI`, `Hotel`) sia da un dizionario.

    Serve perché in questo prodotto gli hotel viaggiano in ENTRAMBE le forme a
    seconda di chi li passa (`cost_estimator` li legge come oggetti,
    `pdf_renderer` come dizionari): una funzione che ne accetta una sola
    funzionerebbe in metà del codice e fallirebbe in silenzio nell'altra metà.
    """
    if isinstance(obj, dict):
        value = obj.get(name)
    else:
        value = getattr(obj, name, None)
    return value.strip() if isinstance(value, str) and value.strip() else None


def build_predeparture(trip, itinerary: dict | None, hotels=None, pois=None) -> dict:
    """`{"country": dict|None, "checklist": [...]}` — mai un'eccezione."""
    try:
        return {
            "country": build_country_card(trip),
            "checklist": build_checklist(trip, itinerary, hotels=hotels, pois=pois),
        }
    except Exception as e:  # pragma: no cover - rete di sicurezza
        print(f"⚠️  Sezione 'Prima di partire' saltata: {type(e).__name__}: {e}")
        return {"country": None, "checklist": []}
