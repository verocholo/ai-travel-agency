"""
NODO 10A (estensione) — Link di ricerca esterni multi-piattaforma.

[AGGIUNTO 2026-07-11 — richiesta di prodotto di Lorenzo: "questa integrazione
multi-piattaforma la facciamo"] Segue la ricerca su Airbnb/Vrbo/Booking (vedi
CHANGELOG.md item 82): Airbnb non ha un'API self-service per terze parti ed è
contrattualmente vietato costruirci un prodotto come il nostro; Vrbo/Expedia
Rapid API ha lo stesso gate di Booking Affiliate (niente self-service, serve
approvazione business). Nessuno dei tre è quindi integrabile come FONTE DATI
live (prezzi/disponibilità reali) senza una partnership formale.

Quello che invece è sempre stato legittimo e già previsto — PROGETTO.md
§5.3 lo descriveva così fin dall'inizio del progetto, ma non era mai stato
implementato: "per affiliate_url costruiamo a valle un link di ricerca
Booking/GetYourGuide (best-effort da nome+città) finché non siamo approvati
come partner Booking" — è generare un link alla pagina di RICERCA PUBBLICA
di ciascuna piattaforma (non un'API, non dati scrapati: lo stesso link che
un utente costruirebbe a mano digitando l'indirizzo nel browser). Questo non
richiede nessuna autorizzazione: è esattamente ciò che fa qualunque sito che
linka "cerca su Booking.com" senza essere un partner ufficiale.

Formati verificati via ricerca web il 2026-07-11 (fonti in CHANGELOG.md):
- Booking.com: `ss` (query libera), `checkin`/`checkout` (YYYY-MM-DD),
  `group_adults`.
- Airbnb: location nel PATH (non query string), `checkin`/`checkout`.
- Vrbo: `destination`, `startDate`/`endDate`, `adults`.

[CORRETTO 2026-07-12 — tre round di bug reali trovati ED ESEGUITI da
Lorenzo col click-test dal vivo nel browser sul suo PC]

Round 1: la scelta originale era di cercare su Booking NOME HOTEL +
destinazione combinati in un'unica stringa `ss=` libera, ipotizzando che
Booking (che lista davvero hotel/catene con brand) avrebbe risolto una
ricerca specifica. Verificato invece che NON è così: cliccando il link
reale generato per "Relais Borgo Val d'Orcia, Val d'Orcia, Toscana",
Booking non riconosce la stringa combinata come destinazione valida e
reindirizza alla propria homepage (`index.it.html`) con il parametro
`errorc_searchstring_not_found=ss`.

Round 2: rimosso il nome hotel, provata la SOLA destinazione ("Val
d'Orcia, Toscana") — stesso identico errore. Isolato con un test mirato
di Lorenzo: la sola regione ("Toscana") risolve correttamente, "Val
d'Orcia" no — perché è il nome di una valle/area turistica (comprende
più comuni: Pienza, Montalcino, San Quirico d'Orcia...), non una singola
città/regione amministrativa indicizzata nel database di destinazioni di
Booking. Usare solo la regione avrebbe risolto l'affidabilità ma
sacrificato la precisione (Lorenzo: "ho bisogno della precisione sennò
il servizio non è pronto come desidero").

Round 3, soluzione adottata: cercare il NOME HOTEL DA SOLO (senza
destinazione). Testato dal vivo da Lorenzo: nessun redirect di errore,
ricerca eseguita con risultati reali (Booking ha fatto fuzzy-match del
nome fittizio della fixture di test con una struttura reale
dall'aspetto/nome simile) — con nomi hotel reali (dati LiteAPI live, non
fixture) questo dovrebbe risolvere in modo affidabile E preciso, perché
Booking indicizza hotel reali con il loro nome esatto, a differenza di
nomi di aree/valli generiche. `hotel_name`, se fornito, è quindi ora
usato DA SOLO per la query Booking (mai combinato con la destinazione);
se assente, fallback sulla sola destinazione (comportamento del round 2).

Airbnb/Vrbo cercano SOLO la destinazione, MAI il nome dell'hotel-ancora
scelto da LiteAPI: sono marketplace di alloggi indipendenti/affitti
brevi, l'hotel scelto (spesso una catena) tipicamente non è lì — cercarlo per
nome sarebbe fuorviante. L'intento qui è "confronta anche altre opzioni per
la stessa destinazione/date", non "trova questo stesso hotel altrove".
Entrambi confermati funzionanti dal vivo da Lorenzo il 2026-07-12 (aprono
una pagina di risultati reale per destinazione/date), nessuna modifica
necessaria.

[AGGIORNATO 2026-07-11 — audit mirato post-implementazione, richiesto da
Lorenzo ("facciamo il massimo, la qualità migliore")] Un audit indipendente
mirato SOLO su questa feature (non il solito audit a 6 agenti sull'intero
codebase, già fatto due volte) ha trovato ed eseguito 6 bug reali (ognuno
confermato lanciando davvero `build_search_links()`/`render_markdown()` con
l'input incriminato, non solo ipotizzato): `destination=None` che crashava
con `TypeError` mai catturato a monte; una destinazione vuota/whitespace
che produceva un URL Airbnb con doppio slash (`/s//homes`); date non nel
formato `YYYY-MM-DD` (incluso `None`) che finivano come stringa letterale
"None" nell'URL invece di essere omesse; una destinazione contenente "/"
(es. "Bosnia/Herzegovina") che spezzava il path Airbnb in due segmenti
diversi da quello inteso; un hotel con `name=None` esplicito (a differenza
di `name` assente, già gestito) che bypassava il fallback "[Da Verificare]"
nel renderer; e una destinazione contenente `]`/`(`/`)` che rompeva la
sintassi Markdown stessa del link `[testo](url)`, iniettando una parentesi/
bracket falsi accanto all'URL reale. Tutti e 6 corretti qui sotto (vedi i
tag `[CORRETTO 2026-07-11 — audit mirato]` inline) e coperti da nuovi test
in `tests/test_affiliate_links.py`. Dettaglio completo in CHANGELOG.md.
"""
from __future__ import annotations
import re
from urllib.parse import quote, quote_plus, urlencode

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _clean_date(value) -> str | None:
    """
    [AGGIUNTO 2026-07-11 — audit mirato] Ritorna la data solo se è
    davvero una stringa nel formato atteso `YYYY-MM-DD`, altrimenti
    `None` — così il parametro viene OMESSO dall'URL invece di comparire
    come stringa letterale "None" (bug reale trovato con
    `build_search_links(destination, None, None)`) o come valore
    spazzatura non validato.
    """
    return value if isinstance(value, str) and _DATE_RE.match(value) else None


def build_search_links(destination: str, date_start: str, date_end: str, hotel_name: str | None = None) -> dict[str, str]:
    """
    Funzione pura (nessuna chiamata di rete) — costruisce 3 link di ricerca
    pubblica, uno per piattaforma. [CORRETTO 2026-07-12 — terzo round di
    bug reali trovati dal vivo da Lorenzo, vedi nota di modulo] `hotel_name`,
    se fornito, viene usato DA SOLO per la query Booking (mai combinato con
    la destinazione: la combinazione, e anche la sola destinazione quando è
    un nome di area/valle come "Val d'Orcia", mandavano in errore la ricerca
    reale di Booking). Se `hotel_name` è assente, Booking usa la sola
    destinazione. Airbnb/Vrbo restano invariati: solo destinazione, mai il
    nome hotel (marketplace di alloggi indipendenti, vedi nota di modulo).
    """
    # [CORRETTO 2026-07-11 — audit mirato] `destination=None` crashava con
    # `TypeError: quote_from_bytes() expected bytes` propagato fino al
    # chiamante (mai catturato in pipeline.py). Normalizzato a stringa
    # vuota, stesso trattamento già riservato a `destination=""`.
    destination = destination or ""
    hotel_name = hotel_name or None
    date_start = _clean_date(date_start)
    date_end = _clean_date(date_end)

    # [CORRETTO 2026-07-12 — terzo round, bug reale trovato dal vivo da
    # Lorenzo] Booking cerca il nome hotel DA SOLO quando disponibile (mai
    # combinato con la destinazione — vedi nota di modulo): un hotel reale
    # è quasi sempre indicizzato con il suo nome esatto, a differenza di
    # nomi di aree/valli generiche che il motore di ricerca di Booking non
    # sempre riconosce come destinazione valida.
    booking_query = hotel_name if hotel_name else destination
    booking_params: dict[str, str] = {"ss": booking_query}
    if date_start:
        booking_params["checkin"] = date_start
    if date_end:
        booking_params["checkout"] = date_end
    booking_params["group_adults"] = "2"
    booking_url = (
        "https://www.booking.com/searchresults.html?"
        + urlencode(booking_params, quote_via=quote_plus)
    )

    # Airbnb vuole la località nel path, non in query string, con spazi
    # sostituiti da trattini (non %20/+) — es. "Rio-de-Janeiro". Rimuoviamo
    # anche le virgole (es. "Lisbona, Portogallo" -> "Lisbona Portogallo")
    # prima di sostituire gli spazi, altrimenti resterebbe un trattino
    # "orfano" al posto della virgola. [CORRETTO 2026-07-11 — audit
    # mirato] Rimuoviamo anche "/": senza questo, una destinazione come
    # "Bosnia/Herzegovina" produceva `/s/Bosnia/Herzegovina/homes` — DUE
    # segmenti di path invece di uno, perché `quote()` di default lascia
    # "/" non codificato (safe="/"). Usiamo `safe=""` per sicurezza anche
    # se in teoria non dovrebbe più arrivare nessuna "/" residua.
    airbnb_location = destination.replace(",", "").replace("/", " ").strip()
    airbnb_location_path = quote(airbnb_location.replace(" ", "-"), safe="") if airbnb_location else ""
    # [CORRETTO 2026-07-11 — audit mirato] destinazione vuota/whitespace
    # produceva `/s//homes` (doppio slash, path malformato) invece di
    # omettere il segmento di località.
    airbnb_path = f"{airbnb_location_path}/homes" if airbnb_location_path else "homes"
    airbnb_params: dict[str, str] = {}
    if date_start:
        airbnb_params["checkin"] = date_start
    if date_end:
        airbnb_params["checkout"] = date_end
    airbnb_url = f"https://www.airbnb.com/s/{airbnb_path}"
    if airbnb_params:
        airbnb_url += "?" + urlencode(airbnb_params)

    vrbo_params: dict[str, str] = {"destination": destination}
    if date_start:
        vrbo_params["startDate"] = date_start
    if date_end:
        vrbo_params["endDate"] = date_end
    vrbo_params["adults"] = "2"
    vrbo_url = (
        "https://www.vrbo.com/search?"
        + urlencode(vrbo_params, quote_via=quote_plus)
    )

    return {"booking": booking_url, "airbnb": airbnb_url, "vrbo": vrbo_url}
