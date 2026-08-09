"""
Genera il PDF di ESEMPIO da ispezionare in sandbox. NON fa parte del servizio:
non chiama l'API di Anthropic, non chiama Google, non spende una sola
operazione Make.

[RISCRITTO 2026-08-02 — verifica finale]
La versione precedente passava `poi=[]` e blocchi senza `poi_id`. Conseguenza:
il campione mostrava copertina, indice, giorno-per-giorno, costi, "Prima di
partire", consigli e recensione — e NON mostrava nessuna delle sezioni chieste
esplicitamente da Lorenzo il 2026-08-01: guide tascabili con il link interno,
schede ristorante con menù/telefono, biglietti dei musei, "come arrivare"
spostamento per spostamento, legenda delle cartine, piani B se piove,
Architect's Tips per direttrici. Il documento che serviva a controllare il
lavoro era esattamente quello che non lo mostrava.

Da qui in poi il campione è un payload COMPLETO: dieci POI reali di Siena con
coordinate vere, itinerario denso (quattro-cinque tappe al giorno, durate
differenziate), guide tascabili, consigli per direttrici e piani B scritti a
mano nella forma ESATTA che producono `guide_generator.py` e
`tips_generator.py`.

Due avvertenze, perché un campione che finge di essere produzione è peggio di
nessun campione:
  1. gli `id` dei POI NON sono veri `place_id` di Google. I link cliccabili
     restano corretti perché ogni POI porta un `google_maps_uri` reale, che ha
     la precedenza (vedi `place_links.build_place_page_url`).
  2. guide, consigli e piani B qui sono scritti a mano. In produzione li
     genera Claude a partire dagli stessi dati; qui servono solo a mostrare
     l'IMPAGINAZIONE di quelle sezioni senza spendere una chiamata.
"""
import os
from types import SimpleNamespace

from src import pdf_renderer
from src import pdf_extras
from src import foto as _foto
from src.schemas import Trip

# [CORRETTO 2026-08-03 — segnalazione del cliente: «il link di tally non
# funziona ancora»] Qui c'era `os.environ.setdefault("FEEDBACK_FORM_URL",
# "https://tally.so/r/ESEMPIO")`, ed era l'UNICA URL di modulo configurata in
# tutto il repo: ogni campione mai consegnato conteneva quindi un link al 404
# di Tally, che è il difetto peggiore possibile — sembra funzionare fino al
# clic, e chi lo clicca è appena tornato da un viaggio pagato.
#
# La variabile ora non viene impostata affatto, e la scelta è deliberata fra
# le due possibili. Tenere un segnaposto e affidarsi alla validazione di
# `feedback_link.validate_form_url()` per scartarlo avrebbe lasciato una URL
# finta scritta nel repo: il giorno in cui quella regola viene allentata (o
# il segnaposto cambiato in qualcosa che la regola non riconosce) il link
# morto tornerebbe a uscire da solo, senza che nessuno abbia toccato questo
# file. Non impostarla toglie il difetto alla radice e in più rende il
# campione ONESTO: mostra esattamente il documento che il prodotto emette
# oggi in produzione, dove la variabile non è impostata.
#
# Chi vuole vedere impaginato il riquadro "Rispondi qui" esporta la URL vera
# prima di lanciare lo script:
#     FEEDBACK_FORM_URL=https://tally.so/r/<id-vero> python3 scripts_sample_pdf.py
#
# Il segreto qui sotto resta: non è un segreto di produzione (serve solo a
# rendere stabile il codice del viaggio fra due generazioni del campione) e
# `setdefault` fa comunque vincere quello vero, se c'è.
os.environ.setdefault("FEEDBACK_REF_SECRET", "segreto-di-esempio-solo-sandbox")

TRIP = {
    "email": "cliente@example.com",
    "destination": "Siena",
    "objective_function": "ENERGY_PACING",
    "date_start": "2026-09-14",
    # [CORRETTO 2026-08-02 (ter)] Erano 3 giorni con due sole giornate
    # progettate: la copertina scriveva "3 giorni" e il programma ne elencava
    # due. In produzione quella forma non passa (validator.py rifiuta un
    # `days[]` di lunghezza diversa da `trip.duration_days`), quindi
    # l'esempio mostrava un documento che il prodotto vero non emette —
    # e per giunta si contraddiceva sotto gli occhi di chi lo giudica.
    "date_end": "2026-09-16",
    "duration_days": 2,
    "budget_mode": "LIMITED",
    "budget_eur": 800,
    # [AGGIUNTO 2026-08-03 - task #184] Il campione viaggia in TRE. Non e' un
    # dettaglio di scenografia: il foglio della valigia mette una colonna di
    # spunte PER VIAGGIATORE, e con un viaggiatore solo la colonna e' una e la
    # cosa chiesta da Lorenzo - "se sono tre, 3 caselle di checklist" - non si
    # vedrebbe nel documento su cui la si giudica. Tre e' anche il numero che
    # rompe la vecchia impaginazione a due colonne, quindi il campione mostra
    # il caso difficile invece di quello comodo.
    "travelers": 3,
}


def _maps(query: str) -> str:
    from urllib.parse import quote_plus
    return f"https://www.google.com/maps/search/?api=1&query={quote_plus(query)}"


# [AGGIUNTO 2026-08-03 — task #180] Gli orari di apertura, nella stessa forma
# in cui `places_client._open_hours()` li ricava da `regularOpeningHours` di
# Google. Nel campione sono ILLUSTRATIVI e non verificati uno per uno (come
# gli `id`, e per la stessa ragione dichiarata sopra): servono a far vedere
# che cosa il documento fa con gli orari, non a dire a nessuno a che ora apre
# il Duomo. In produzione arrivano dal fornitore, non da qui.
_ORARI_MUSEO = {g: [["10:00", "19:00"]] for g in
                ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat")}
_ORARI_MUSEO["Sun"] = [["13:30", "18:00"]]
_ORARI_CHIESA = {g: [["10:30", "19:00"]] for g in
                 ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat")}
_ORARI_CHIESA["Sun"] = [["13:30", "18:00"]]
_ORARI_RISTORANTE = {g: [["12:00", "14:30"], ["19:00", "22:30"]] for g in
                     ("Tue", "Wed", "Thu", "Fri", "Sat", "Sun")}

# I POI: coordinate reali, tipi normalizzati come li produce places_client
# (restaurant | museum | shopping | activity), `primary_type` grezzo conservato
# perché è quello su cui si decide se una tappa è all'aperto (piani B).
POIS = [
    dict(id="SAMPLE_campo", type="activity", primary_type="tourist_attraction",
         name="Piazza del Campo", lat=43.31822, lng=11.33160,
         energy_tag="LOW", rating=4.8, user_rating_count=41200,
         address="Piazza del Campo, 53100 Siena SI",
         google_maps_uri=_maps("Piazza del Campo Siena")),
    dict(id="SAMPLE_torre", type="museum", primary_type="observation_deck",
         name="Torre del Mangia", lat=43.31812, lng=11.33145,
         energy_tag="HIGH", rating=4.7, user_rating_count=9800,
         address="Piazza del Campo 1, 53100 Siena SI",
         website="https://www.comune.siena.it/musei-civici",
         open_hours=_ORARI_MUSEO,
         google_maps_uri=_maps("Torre del Mangia Siena")),
    dict(id="SAMPLE_taverna", type="restaurant", primary_type="italian_restaurant",
         name="Taverna di San Giuseppe", lat=43.31600, lng=11.33080,
         energy_tag="LOW", price_level="MODERATE", rating=4.6,
         user_rating_count=4300, phone="+39 0577 42286",
         address="Via Giovanni Duprè 132, 53100 Siena SI",
         website="https://www.tavernasangiuseppe.it",
         open_hours=_ORARI_RISTORANTE,
         google_maps_uri=_maps("Taverna di San Giuseppe Siena")),
    dict(id="SAMPLE_duomo", type="museum", primary_type="church",
         name="Duomo di Siena", lat=43.31757, lng=11.32884,
         energy_tag="MEDIUM", rating=4.8, user_rating_count=28600,
         address="Piazza del Duomo 8, 53100 Siena SI",
         website="https://operaduomo.siena.it",
         open_hours=_ORARI_CHIESA,
         google_maps_uri=_maps("Duomo di Siena")),
    dict(id="SAMPLE_scala", type="museum", primary_type="museum",
         name="Santa Maria della Scala", lat=43.31740, lng=11.32830,
         energy_tag="MEDIUM", rating=4.6, user_rating_count=6100,
         address="Piazza del Duomo 1, 53100 Siena SI",
         website="https://www.santamariadellascala.com",
         open_hours=_ORARI_MUSEO,
         google_maps_uri=_maps("Santa Maria della Scala Siena")),
    dict(id="SAMPLE_terzi", type="restaurant", primary_type="wine_bar",
         name="Enoteca I Terzi", lat=43.31895, lng=11.33095,
         energy_tag="LOW", price_level="MODERATE", rating=4.5,
         user_rating_count=2900, phone="+39 0577 44329",
         address="Via dei Termini 7, 53100 Siena SI",
         website="https://www.enotecaiterzi.it",
         google_maps_uri=_maps("Enoteca I Terzi Siena")),
    dict(id="SAMPLE_domenico", type="museum", primary_type="church",
         name="Basilica di San Domenico", lat=43.32040, lng=11.32550,
         energy_tag="LOW", rating=4.5, user_rating_count=7400,
         address="Piazza San Domenico 1, 53100 Siena SI",
         google_maps_uri=_maps("Basilica di San Domenico Siena")),
    dict(id="SAMPLE_pinacoteca", type="museum", primary_type="art_gallery",
         name="Pinacoteca Nazionale di Siena", lat=43.31480, lng=11.32860,
         energy_tag="LOW", rating=4.4, user_rating_count=1800,
         address="Via San Pietro 29, 53100 Siena SI",
         website="https://www.pinacotecanazionale.siena.it",
         google_maps_uri=_maps("Pinacoteca Nazionale Siena")),
    dict(id="SAMPLE_fortezza", type="activity", primary_type="park",
         name="Fortezza Medicea", lat=43.32220, lng=11.32310,
         energy_tag="LOW", rating=4.5, user_rating_count=5200,
         address="Piazza della Libertà, 53100 Siena SI",
         google_maps_uri=_maps("Fortezza Medicea Siena")),
    dict(id="SAMPLE_consorzio", type="shopping", primary_type="gift_shop",
         name="Consorzio Agrario di Siena", lat=43.31960, lng=11.32760,
         energy_tag="LOW", price_level="INEXPENSIVE", rating=4.4,
         user_rating_count=2100,
         address="Via Pianigiani 9, 53100 Siena SI",
         website="https://www.capsi.it",
         google_maps_uri=_maps("Consorzio Agrario Siena")),
]

# Giornate dense e con durate DIFFERENZIATE (punto di Lorenzo: "attività che
# richiedono poco tempo le fai di lunghezze enormi, lasciando il cliente ad
# annoiarsi"). Una piazza è 40 minuti, una torre 45, un museo grande 2 ore.
ITINERARY = {
    "destination": "Siena",
    "executive_summary": (
        "Due giorni costruiti attorno a un ritmo lento ma pieno: le salite e i "
        "musei concentrati al mattino quando le gambe sono fresche, il primo "
        "pomeriggio protetto dal caldo di settembre, e ogni sera una tappa "
        "corta che non chiede nulla."
    ),
    "architect_tips": [
        "Il Duomo si visita meglio subito dopo l'apertura: mezz'ora dopo la fila raddoppia.",
        "Piazza del Campo la sera cambia completamente: vale una seconda passata.",
    ],
    "days": [
        {
            "day": 1,
            "title": "Arrivo e centro storico",
            "blocks": [
                {"time": "10:30", "duration_min": 40, "activity": "Piazza del Campo",
                 "location": "Siena", "poi_id": "SAMPLE_campo",
                 "logistics": "8 minuti a piedi dal parcheggio Santa Caterina"},
                {"time": "11:20", "duration_min": 45, "activity": "Salita alla Torre del Mangia",
                 "location": "Piazza del Campo 1", "poi_id": "SAMPLE_torre",
                 "logistics": "400 scalini, ingresso dal cortile del Podestà"},
                {"time": "12:30", "duration_min": 90, "activity": "Pranzo alla Taverna di San Giuseppe",
                 "location": "Via Giovanni Duprè 132", "poi_id": "SAMPLE_taverna"},
                {"time": "16:00", "duration_min": 75, "activity": "Duomo di Siena",
                 "location": "Piazza del Duomo", "poi_id": "SAMPLE_duomo",
                 "logistics": "10 minuti a piedi, in salita"},
                {"time": "19:30", "duration_min": 90, "activity": "Cena all'Enoteca I Terzi",
                 "location": "Via dei Termini 7", "poi_id": "SAMPLE_terzi"},
            ],
        },
        {
            "day": 2,
            "title": "Fuori le mura",
            "blocks": [
                {"time": "09:30", "duration_min": 45, "activity": "Basilica di San Domenico",
                 "location": "Siena", "poi_id": "SAMPLE_domenico"},
                {"time": "10:45", "duration_min": 120, "activity": "Santa Maria della Scala",
                 "location": "Piazza del Duomo 1", "poi_id": "SAMPLE_scala",
                 "logistics": "7 minuti a piedi, in discesa"},
                {"time": "15:00", "duration_min": 60, "activity": "Passeggiata alla Fortezza Medicea",
                 "location": "Siena", "poi_id": "SAMPLE_fortezza",
                 "logistics": "12 minuti a piedi, in piano"},
                {"time": "17:00", "duration_min": 40, "activity": "Spesa al Consorzio Agrario",
                 "location": "Via Pianigiani 9", "poi_id": "SAMPLE_consorzio"},
            ],
        },
    ],
}

HOTELS = [
    # [2026-08-02] `lat`/`lng` aggiunte: in produzione arrivano da LiteAPI e ci
    # sono sempre, qui mancavano — e senza di esse la cartina non disegnava il
    # perno della giornata mentre la legenda continuava a nominarlo. Un esempio
    # con dati più poveri della produzione nasconde difetti invece di mostrarli.
    {"name": "Palazzo Ravizza", "property_type": "hotel", "price_night_eur": 140,
     "address": "Pian dei Mantellini 34, 53100 Siena SI", "phone": "+39 0577 280462",
     "lat": 43.3155, "lng": 11.3243},
    {"name": "Hotel Athena", "property_type": "hotel", "price_night_eur": 118,
     "lat": 43.3161, "lng": 11.3226},
]

# --- Sezioni che in produzione genera Claude -----------------------------
# Scritte a mano SOLO per mostrare l'impaginazione: stessa forma esatta che
# producono guide_generator.normalize_guide() e tips_generator.normalize_tips().
#
# [ESTESE 2026-08-02 (quater) — task #169, richiesta di Lorenzo: «deve esserci
# una guida per ogni cosa che lo richieda, non aver paura di sembrare prolisso
# è una cosa molto interessante»]
#
# Erano DUE guide su nove tappe che le meritano. In produzione la selezione la
# fa `guide_generator.select_guide_targets()` e ne sceglie nove: il campione
# mostrava quindi un capitolo largo un quinto di quello che il prodotto emette
# davvero, e il documento che Lorenzo apre per giudicare il lavoro faceva
# sembrare povera una sezione che povera non è. Ora ce n'è una per ogni
# bersaglio, nell'ORDINE DI VISITA — lo stesso ordine in cui `pdf_extras` le
# genera, così l'esempio e la produzione impaginano identico.
#
# `tests/test_standard_qualita.py` lega questa lista alla selezione vera:
# se domani qualcuno aggiunge una tappa al programma senza scriverne la guida,
# il controllo cade. È il modo per non dover ripetere la richiesta.
GUIDES = [
    {
        "poi_id": "SAMPLE_campo",
        "poi_name": "Piazza del Campo",
        "title": "Piazza del Campo",
        "history_summary": (
            "Nata nel Duecento sul punto in cui convergevano i tre colli della "
            "città, la piazza è l'unico spazio che nessuna delle tre parti "
            "poteva rivendicare: per questo ci si costruì sopra il governo. La "
            "pavimentazione è divisa in nove spicchi, uno per ciascun membro "
            "del Governo dei Nove che resse Siena fino al 1355 — non è un "
            "motivo decorativo, è un organigramma inciso nel mattone."
        ),
        "highlights": [
            {"name": "I nove spicchi", "why": "contali dal centro: sono la firma del governo che costruì la piazza"},
            {"name": "Fonte Gaia", "why": "quella che vedi è la copia ottocentesca; gli originali di Jacopo della Quercia sono a Santa Maria della Scala"},
            {"name": "La pendenza", "why": "la conca non è un difetto del terreno: convoglia l'acqua piovana verso un unico scarico centrale"},
        ],
        "curiosita": [
            "Il Palio non si corre sul mattonato: pochi giorni prima si stende sopra l'anello esterno uno strato di tufo, che viene rimosso a corsa finita. Per undici mesi l'anno la pista non esiste.",
            "La piazza non appartiene a nessuna delle diciassette contrade. È terreno neutro, ed è esattamente la ragione per cui il governo cittadino si insediò qui e non in un quartiere di parte.",
            "Il selciato è in mattoni posati a spina di pesce con costoloni di travertino: la stessa tecnica usata per le strade in salita, dove serviva presa per gli zoccoli.",
        ],
        "errore_da_evitare": "Sedersi a un tavolino del lato assolato per \"godersi la piazza\" e pagare il servizio: la vista migliore è dal mattonato, in basso al centro della conca, dove ci si siede gratis e si vede tutta la curva del Palazzo Pubblico.",
        "dintorni": [
            {"name": "Palazzo Pubblico e Museo Civico", "why": "si entra dalla piazza stessa: dentro c'è il ciclo del Buon Governo di Ambrogio Lorenzetti"},
            {"name": "Loggia della Mercanzia", "why": "due minuti in salita, all'incrocio dei tre colli: è il punto in cui le tre parti storiche della città si toccano"},
            {"name": "Via di Città", "why": "la strada curva che parte dall'angolo alto della piazza, la più bella spina di palazzi medievali della città"},
        ],
        "practical_tips": [
            "Sedersi sul mattonato è consentito e non costa nulla: è il posto migliore per la prima mezz'ora.",
            "I bar sotto il Palazzo Pubblico applicano il servizio al tavolo: il caffè al banco costa un terzo.",
        ],
        "best_time_to_visit": "presto al mattino o dopo le 19: a mezzogiorno la conca non ha ombra",
        "estimated_visit_duration": "40 minuti",
        "consiglio_personalizzato": (
            "Il tuo ritmo prevede la Torre subito dopo: entra in piazza dal lato "
            "opposto al Palazzo Pubblico, così la vedi tutta prima di salirci."
        ),
        "disclaimer": "Orari, biglietti e aperture del Palazzo Pubblico cambiano con la stagione: verifica sul sito ufficiale dei Musei Civici prima di andare.",
    },
    {
        "poi_id": "SAMPLE_torre",
        "poi_name": "Torre del Mangia",
        "title": "Torre del Mangia",
        "history_summary": (
            "Costruita fra il 1338 e il 1348, la torre fu alzata di proposito "
            "fino a pareggiare la quota del Duomo, che sta più in alto sulla "
            "collina: il potere civile non doveva risultare più basso di quello "
            "religioso, e l'unico modo per dirlo senza parole era l'altezza. Il "
            "nome viene dal primo campanaro, Giovanni di Balduccio, soprannominato "
            "Mangiaguadagni per come spendeva la paga. Ai piedi della torre la "
            "Cappella di Piazza fu costruita come voto dopo la peste nera del "
            "1348, la stessa che fermò per sempre i lavori del Duomo Nuovo."
        ),
        "highlights": [
            {"name": "La cella campanaria", "why": "l'ultima rampa è una scala a chiocciola strettissima: è il punto in cui la salita smette di essere una scalinata"},
            {"name": "Il panorama sul Campo", "why": "dall'alto i nove spicchi si leggono come una pianta: è l'unico posto da cui si capisce la forma della piazza"},
            {"name": "La Cappella di Piazza", "why": "alla base, si guarda da fuori e senza biglietto: è un ex voto contro la peste"},
        ],
        "curiosita": [
            "La tradizione racconta che agli angoli delle fondamenta furono murate pietre con lettere latine ed ebraiche e alcune monete, come scaramanzia contro i fulmini: la torre è la cosa più alta della città e prende tutti i temporali.",
            "La campana grande in cima, che i senesi chiamano Sunto, dà il nome all'Assunta a cui la città si consacrò prima della battaglia di Montaperti.",
            "La Cappella di Piazza ai piedi della torre fu costruita come voto per la fine della peste: è un edificio nato da un ringraziamento, non da una committenza.",
        ],
        "errore_da_evitare": "Salire e poi scoprire di non avere più tempo per il Museo Civico, che sta nello stesso edificio ed è la parte che quasi tutti sacrificano: i due ingressi si prendono insieme, e vanno messi in programma insieme.",
        "dintorni": [
            {"name": "Cortile del Podestà", "why": "è il cortile da cui si sale, e da solo vale lo sguardo: pozzo, stemmi e loggia trecentesca"},
            {"name": "Cappella di Piazza", "why": "alla base della torre, si guarda da fuori e non costa nulla"},
            {"name": "Fonte Gaia", "why": "sul lato opposto della conca, tre minuti in piano"},
        ],
        "practical_tips": [
            "L'ingresso è dal cortile del Podestà, non dalla piazza: la biglietteria è la stessa del Museo Civico.",
            "Gli accessi sono contingentati a piccoli gruppi e in alta stagione si esaurisce la fascia oraria: verifica sul sito dei Musei Civici prima di salire fin lì.",
            "Non ci sono ascensori né deposito: zaini grandi e passeggini restano fuori.",
            "Circa quattrocento scalini senza punti di sosta reali: se il fiato è un tema, la Torre è la tappa da sacrificare, non da rimandare a fine giornata.",
        ],
        "best_time_to_visit": "prima fascia del mattino: la pietra è ancora fresca e la luce arriva radente sui tetti",
        "estimated_visit_duration": "45 minuti compresa la fila",
        "consiglio_personalizzato": (
            "Nel tuo programma la Torre arriva subito dopo la piazza e prima del "
            "pranzo: è l'ordine giusto, perché sali con le gambe fresche e scendi "
            "esattamente all'ora in cui il Campo comincia a non avere più ombra."
        ),
        "disclaimer": "Gli accessi alla torre sono contingentati e sospesi in caso di maltempo: controlla disponibilità, orari e prezzi sul sito dei Musei Civici lo stesso giorno.",
    },
    {
        "poi_id": "SAMPLE_taverna",
        "poi_name": "Taverna di San Giuseppe",
        "title": "Taverna di San Giuseppe",
        "history_summary": (
            "La sala che si vede entrando è la parte meno antica del locale: le "
            "cantine scavate sotto Via Duprè affondano nel tufo della collina e "
            "sono le stesse gallerie che i senesi usavano per l'acqua e per il "
            "vino secoli prima che qui ci fosse un ristorante. È una cucina "
            "senese dichiarata, non toscana generica: la differenza si sente sui "
            "primi fatti a mano e sulla carne, non sui piatti da cartolina."
        ),
        "highlights": [
            {"name": "Le cantine sotterranee", "why": "chiedi di dare un'occhiata prima o dopo il pasto: è il pezzo di locale che nessuno si aspetta"},
            {"name": "I pici", "why": "spaghettone senese fatto a mano, tirato uno per uno: il piatto su cui si giudica una cucina qui"},
            {"name": "La carne alla brace", "why": "la Chianina è il motivo per cui questo indirizzo compare in ogni elenco: si ordina al peso, non a porzione"},
        ],
        "curiosita": [
            "La strada porta il nome di Giovanni Duprè, scultore senese dell'Ottocento nato in questo stesso rione: uno dei pochi artisti cittadini a cui Siena abbia intitolato la via in cui è cresciuto.",
            "Siamo nel territorio della contrada dell'Onda, il cui museo sta a pochi numeri civici di distanza: nei giorni intorno al Palio questa strada è di parte, non di città.",
            "Le cantine sotto la sala sono scavate nel tufo della collina, la stessa roccia friabile in cui i senesi hanno ricavato per secoli i cunicoli dell'acqua.",
        ],
        "errore_da_evitare": "Presentarsi senza prenotazione in una sera di alta stagione e ripiegare sul primo tavolo libero sotto il Campo: è il modo più comune di trasformare la cena migliore del viaggio in quella che non si ricorda.",
        "dintorni": [
            {"name": "Museo della Contrada dell'Onda", "why": "pochi numeri civici più avanti: si visita su richiesta ed è il modo più diretto di capire cos'è una contrada"},
            {"name": "Piazza del Campo", "why": "tre minuti in salita: dopo pranzo è il rientro naturale"},
            {"name": "Orto de' Pecci", "why": "sotto le mura, dieci minuti a piedi in discesa: campi coltivati dentro la città medievale"},
        ],
        "practical_tips": [
            "Si prenota, e con anticipo: nelle sere di alta stagione i tavoli finiscono giorni prima.",
            "La bistecca si ordina al peso e per due persone: se siete in due e volete anche il primo, mezzo chilo è già molto.",
            "Il conto sta nella fascia media-alta della città: se il budget della giornata è stretto, è qui che conviene tenerlo largo e alleggerire la cena.",
        ],
        "best_time_to_visit": "a pranzo si mangia con più calma e la sala sotterranea è meno affollata",
        "estimated_visit_duration": "1 ora e 30",
        "consiglio_personalizzato": (
            "Nel tuo programma il pranzo qui dura novanta minuti e sotto ha il "
            "buco più lungo della giornata: è voluto. Alle 14 il centro è nel suo "
            "momento peggiore per luce e caldo, e questa è la sala giusta in cui "
            "lasciarlo passare invece di camminarci dentro."
        ),
        "disclaimer": "Giorni di chiusura, orari e prezzi dei ristoranti cambiano di stagione in stagione: telefona o controlla il sito prima di contarci.",
    },
    {
        "poi_id": "SAMPLE_duomo",
        "poi_name": "Duomo di Siena",
        "title": "Duomo di Siena",
        "history_summary": (
            "Il Duomo doveva essere solo il transetto di una cattedrale enorme, "
            "il \"Duomo Nuovo\", che avrebbe superato San Pietro. I lavori si "
            "fermarono nel 1348 con la peste nera e non ripresero mai: il muro "
            "incompiuto che si vede accanto alla facciata è quello che resta "
            "dell'ambizione di Siena prima che perdesse un terzo dei suoi "
            "abitanti in sei mesi."
        ),
        "highlights": [
            {"name": "Il pavimento a tarsie", "why": "56 riquadri, scoperti solo alcune settimane l'anno: verifica sul sito se il tuo periodo è uno di quelli"},
            {"name": "Il pulpito di Nicola Pisano", "why": "1268, sette pannelli: è il punto in cui la scultura italiana smette di essere romanica"},
            {"name": "La Libreria Piccolomini", "why": "gli affreschi del Pinturicchio, colori originali mai ridipinti"},
        ],
        "curiosita": [
            "Le fasce bianche e nere non sono una scelta decorativa: sono i colori della Balzana, lo stemma di Siena, ripetuti su tutta la cattedrale.",
            "Il muro incompiuto del Duomo Nuovo si può salire: dall'alto del \"facciatone\" si guarda il vuoto dove sarebbe dovuta stare la navata mai costruita.",
            "Il pavimento a tarsie fu lavorato nell'arco di quasi due secoli da decine di artisti diversi: non è un'opera, è un cantiere durato generazioni.",
        ],
        "errore_da_evitare": "Programmare la visita per il pavimento senza verificare il periodo di scopertura: per gran parte dell'anno i riquadri sono protetti e coperti, ed è proprio la cosa per cui la maggior parte delle persone entra.",
        "dintorni": [
            {"name": "Battistero di San Giovanni", "why": "sotto l'abside, si scende per una scalinata: la fonte battesimale ha pannelli di Donatello e Ghiberti"},
            {"name": "Santa Maria della Scala", "why": "esattamente di fronte, dall'altra parte della piazza"},
            {"name": "Museo dell'Opera e Facciatone", "why": "sul fianco destro: ci sta la Maestà di Duccio, e da lì si sale sul muro incompiuto"},
        ],
        "practical_tips": [
            "Spalle e ginocchia coperte: è una chiesa officiante e il controllo è reale.",
            "Il biglietto cumulativo (OPA SI Pass) conviene già dal secondo ingresso.",
        ],
        "best_time_to_visit": "all'apertura: la luce sul pavimento è migliore e la fila non esiste ancora",
        "estimated_visit_duration": "1 ora e 15",
        "consiglio_personalizzato": (
            "Hai Santa Maria della Scala il giorno dopo, a cento metri: comprare "
            "il pass cumulativo oggi ti fa risparmiare e ti evita la seconda coda."
        ),
        "disclaimer": "Periodi di scopertura del pavimento, orari e biglietti cumulativi cambiano ogni anno: verifica sul sito dell'Opera del Duomo prima della visita.",
    },
    {
        "poi_id": "SAMPLE_terzi",
        "poi_name": "Enoteca I Terzi",
        "title": "Enoteca I Terzi",
        "history_summary": (
            "Il nome dice dove sei: i Terzi sono le tre parti storiche in cui "
            "Siena è divisa da prima che esistessero le contrade, e questa strada "
            "sta esattamente sulla linea in cui due di esse si toccano. È "
            "un'enoteca con cucina, non un ristorante con carta dei vini: si "
            "ordina prima il calice e poi il piatto che gli sta bene, che è "
            "l'ordine inverso a quello a cui si è abituati."
        ),
        "highlights": [
            {"name": "I calici al bicchiere", "why": "la lista al bicchiere è larga: è il modo per assaggiare tre denominazioni diverse senza tre bottiglie"},
            {"name": "Il banco", "why": "mangiare al bancone è accettato e si aspetta molto meno del tavolo"},
            {"name": "I salumi e i pecorini", "why": "la selezione locale è il tagliere su cui si capisce la differenza fra un pecorino di Pienza giovane e uno stagionato"},
        ],
        "curiosita": [
            "I Terzi — di Città, di San Martino e di Camollia — sono la divisione amministrativa di Siena precedente alle diciassette contrade, e sopravvivono ancora nei nomi delle strade e nell'ordine delle cerimonie.",
            "A due passi c'è Palazzo Salimbeni, sede storica di quella che viene considerata la banca più antica del mondo ancora in attività.",
            "In una città che vive di Sangiovese, la carta di un'enoteca senese si giudica da quanto spazio dà ai produttori piccoli della provincia rispetto alle etichette famose.",
        ],
        "errore_da_evitare": "Ordinare il piatto e poi cercare il vino che ci sta: qui si lavora nell'ordine inverso, si parte dal calice, e chi non lo sa si perde metà del motivo per cui questo indirizzo esiste.",
        "dintorni": [
            {"name": "Piazza Salimbeni", "why": "un minuto a piedi: tre palazzi di tre epoche diverse su un solo lato"},
            {"name": "Piazza Tolomei", "why": "due minuti: la lupa senese su colonna e uno dei palazzi privati più antichi della città"},
            {"name": "Piazza del Campo", "why": "cinque minuti in discesa: il rientro naturale dopo cena"},
        ],
        "practical_tips": [
            "Prenotare la sera è la regola, non l'eccezione: è piccola.",
            "Se non sai cosa scegliere, dì il piatto e lasciagli scegliere il vino: qui è il verso in cui funziona.",
            "Chiude fra pranzo e cena: non è un indirizzo da pomeriggio.",
        ],
        "best_time_to_visit": "primo turno di cena, verso le 19:30, quando la sala è ancora tranquilla",
        "estimated_visit_duration": "1 ora e 30",
        "consiglio_personalizzato": (
            "È l'ultima tappa della tua prima giornata, dopo una salita e un "
            "museo: per questo la cena è qui e non in un indirizzo che chiede di "
            "attraversare la città. Dall'Enoteca al tuo alloggio si torna a piedi "
            "in piano, ed è la ragione per cui questa sera finisce così."
        ),
        "disclaimer": "Turni di cena, giorni di chiusura e prezzi cambiano di stagione: prenota e verifica direttamente prima di contarci.",
    },
    {
        "poi_id": "SAMPLE_domenico",
        "poi_name": "Basilica di San Domenico",
        "title": "Basilica di San Domenico",
        "history_summary": (
            "Un enorme parallelepipedo di mattoni senza facciata, cominciato nel "
            "Duecento: la spoglia è voluta, perché i domenicani predicavano a una "
            "folla e avevano bisogno di un capannone, non di una scenografia. È "
            "la chiesa di Caterina Benincasa, la santa che scrisse ai papi e che "
            "Siena considera sua molto prima che l'Italia la facesse patrona: "
            "nella cappella a lei dedicata sono conservate le sue reliquie, e gli "
            "affreschi intorno sono del Sodoma."
        ),
        "highlights": [
            {"name": "La Cappella di Santa Caterina", "why": "gli affreschi del Sodoma raccontano l'estasi e lo svenimento: è il punto in cui la chiesa smette di essere spoglia"},
            {"name": "Il ritratto di Andrea Vanni", "why": "dipinto da chi la conobbe di persona: è l'immagine più vicina al vero che esista di lei"},
            {"name": "La terrazza sul retro", "why": "affacciandosi si ha il profilo del Duomo e della Torre nello stesso sguardo, gratis"},
        ],
        "curiosita": [
            "La facciata non è mai stata rivestita: il mattone a vista che si vede oggi era destinato a sparire sotto il marmo, e nessuno ci ha più messo mano.",
            "Caterina Benincasa non sapeva scrivere all'inizio e dettava le sue lettere — compresi i richiami ai papi — a chi le stava intorno.",
            "Il 29 aprile Siena la celebra e le contrade portano i ceri in basilica: è una delle poche occasioni in cui la città si raduna fuori dal Palio.",
        ],
        "errore_da_evitare": "Entrare, guardare la navata enorme e uscire dopo cinque minuti: la Cappella di Santa Caterina è sul fianco destro e non si vede dall'ingresso, che è esattamente il motivo per cui quasi tutti la saltano.",
        "dintorni": [
            {"name": "Santuario e Casa di Santa Caterina", "why": "tre minuti in discesa: la casa di famiglia trasformata in oratorio"},
            {"name": "Fonte Branda", "why": "cinque minuti più sotto: la fonte medievale con le arcate, ancora piena d'acqua"},
            {"name": "Fortezza Medicea", "why": "dieci minuti in piano verso nord, per chi vuole il panorama al tramonto"},
        ],
        "practical_tips": [
            "L'ingresso alla basilica è libero: è una delle poche cose importanti di Siena che non costa nulla.",
            "È una chiesa officiante e durante le funzioni la cappella non si visita: le mattine dei giorni festivi sono le meno adatte.",
            "Dentro fa fresco anche a settembre: è la sosta giusta se la giornata parte già calda.",
        ],
        "best_time_to_visit": "prima mattina, appena aperta, quando la luce entra bassa dalle finestre alte",
        "estimated_visit_duration": "45 minuti",
        "consiglio_personalizzato": (
            "Apre la tua seconda giornata perché è a pochi minuti dall'alloggio e "
            "in discesa: si comincia con una cosa grande senza spendere gambe, e "
            "si arriva a Santa Maria della Scala già entrati nell'atmosfera."
        ),
        "disclaimer": "La basilica è officiante: orari di visita e accesso alla cappella variano con le funzioni. Verifica prima di andare, soprattutto nei giorni festivi.",
    },
    {
        "poi_id": "SAMPLE_scala",
        "poi_name": "Santa Maria della Scala",
        "title": "Santa Maria della Scala",
        "history_summary": (
            "Per quasi mille anni questo palazzo davanti al Duomo non è stato un "
            "museo: era l'ospedale della città, uno dei più antichi d'Europa, "
            "nato per accogliere i pellegrini della via Francigena e diventato "
            "poi brefotrofio, ricovero e ospizio. Ha smesso di curare persone "
            "solo alla fine del Novecento. Visitarlo significa scendere per "
            "livelli dentro la collina: sopra le corsie affrescate, sotto le "
            "cantine, i cunicoli e la Siena etrusca."
        ),
        "highlights": [
            {"name": "Il Pellegrinaio", "why": "gli affreschi quattrocenteschi mostrano l'ospedale al lavoro: medici, trovatelli, malati. Non è una scena sacra, è un reportage"},
            {"name": "Le formelle originali di Fonte Gaia", "why": "gli originali di Jacopo della Quercia stanno qui: in piazza del Campo c'è la copia"},
            {"name": "I livelli sotterranei", "why": "si scende di piano in piano fino alla roccia: è la parte che i bambini ricordano"},
        ],
        "curiosita": [
            "Per secoli chi moriva senza eredi lasciava i propri beni alla Scala: è così che un ospedale è diventato uno dei maggiori proprietari terrieri della Toscana.",
            "Nel Pellegrinaio i pittori del Quattrocento hanno dipinto medici al lavoro, trovatelli e malati a letto: una committenza laica che racconta un servizio pubblico, cosa rarissima per l'epoca.",
            "Sotto Siena corre la rete dei bottini, chilometri di cunicoli medievali scavati a mano per portare l'acqua alle fonti: i livelli inferiori della Scala scendono verso quello stesso mondo sotterraneo.",
        ],
        "errore_da_evitare": "Entrare un'ora prima della chiusura convinti che sia un museo piccolo: si arriva sì e no a metà, e la metà che si perde è quella sotterranea, cioè quella che nessun altro museo della città può offrire.",
        "dintorni": [
            {"name": "Duomo di Siena", "why": "esattamente di fronte, dall'altra parte della piazza"},
            {"name": "Battistero di San Giovanni", "why": "due minuti, dietro l'abside della cattedrale"},
            {"name": "Pinacoteca Nazionale", "why": "cinque minuti in discesa lungo via San Pietro: la pittura senese dal Duecento al Cinquecento, quasi sempre semivuota"},
        ],
        "practical_tips": [
            "È molto più grande di quanto sembri dall'ingresso: due ore sono il minimo, non la media.",
            "I livelli inferiori sono freschi e in parte a scale: scarpe chiuse e una maglia leggera anche d'estate.",
            "Se hai già preso il pass cumulativo del Duomo, verifica cosa include: le combinazioni cambiano di stagione in stagione.",
        ],
        "best_time_to_visit": "metà mattina: si esce per pranzo senza aver preso il caldo delle ore centrali",
        "estimated_visit_duration": "2 ore",
        "consiglio_personalizzato": (
            "Nel tuo programma è la tappa più lunga della vacanza, ed è l'unica a "
            "cui sono state date due ore piene: è la scelta di non correre in "
            "nessun altro punto delle due giornate. Il pomeriggio, di conseguenza, "
            "resta leggero apposta."
        ),
        "disclaimer": "Percorsi aperti, mostre temporanee, orari e biglietti cumulativi cambiano spesso: verifica sul sito ufficiale il giorno prima.",
    },
    {
        "poi_id": "SAMPLE_fortezza",
        "poi_name": "Fortezza Medicea",
        "title": "Fortezza Medicea",
        "history_summary": (
            "Non è una fortezza senese: è la fortezza che i vincitori costruirono "
            "sopra Siena. Dopo la caduta della Repubblica, a metà Cinquecento, "
            "Cosimo I de' Medici la fece alzare su progetto di Baldassarre Lanci "
            "per tenere la città sotto controllo, e i senesi non l'hanno mai "
            "chiamata in altro modo. Oggi i bastioni sono un parco pubblico: il "
            "posto meno turistico e più frequentato dai residenti che ci sia in "
            "città."
        ),
        "highlights": [
            {"name": "Il camminamento sui bastioni", "why": "si fa il giro completo in piano, sopra le mura: è la passeggiata che nessuna guida mette in programma"},
            {"name": "Il profilo della città al tramonto", "why": "da qui Duomo e Torre si vedono insieme, controluce, alla stessa distanza"},
            {"name": "Il prato interno", "why": "è dove si siedono i senesi: se vuoi vedere la città che non lavora sul turismo, è qui"},
        ],
        "curiosita": [
            "Una prima fortezza, costruita dagli spagnoli, sorgeva quasi nello stesso punto: i senesi la rasero al suolo nel 1552 appena cacciata la guarnigione. Quella medicea è la seconda, ed è quella che nessuno è più riuscito ad abbattere.",
            "I bastioni sono a pianta quadrata con quattro punte angolari: è architettura militare da artiglieria, pensata per resistere alle palle di cannone invece che alle scale d'assalto.",
            "Il grande spiazzo accanto, la Lizza, ospita da generazioni il mercato settimanale: è il posto in cui si vede la Siena che fa la spesa, non quella che vende souvenir.",
        ],
        "errore_da_evitare": "Salirci nelle ore centrali di una giornata di sole: sui bastioni non c'è un metro d'ombra, e il panorama alle 18 è lo stesso di mezzogiorno con metà del caldo e una luce migliore.",
        "dintorni": [
            {"name": "La Lizza", "why": "adiacente: giardini pubblici e, nel giorno di mercato, il mercato più grande della città"},
            {"name": "Basilica di San Domenico", "why": "dieci minuti in piano verso il centro"},
            {"name": "Stadio Artemio Franchi", "why": "letteralmente sotto le mura della fortezza: lo si guarda dall'alto dei bastioni"},
        ],
        "practical_tips": [
            "L'ingresso è libero e non ci sono orari: è uno spazio pubblico all'aperto.",
            "Non c'è ombra sui bastioni: nelle ore centrali di una giornata di sole è la tappa sbagliata.",
            "I servizi interni (locali, eventi) aprono a intermittenza e cambiano di anno in anno: dai per buono il parco, non il resto.",
        ],
        "best_time_to_visit": "tardo pomeriggio, l'ultima ora e mezza di luce",
        "estimated_visit_duration": "1 ora",
        "consiglio_personalizzato": (
            "Arriva dopo due ore di museo, ed è esattamente per questo che sta "
            "lì: è all'aperto, è in piano, non chiede biglietti né attenzione. "
            "Dopo Santa Maria della Scala una terza sala chiusa sarebbe stata una "
            "tappa di troppo."
        ),
        "disclaimer": "Il parco sui bastioni è pubblico e liberamente accessibile, ma le attività ospitate all'interno aprono e chiudono di anno in anno: non darle per scontate.",
    },
    {
        "poi_id": "SAMPLE_consorzio",
        "poi_name": "Consorzio Agrario di Siena",
        "title": "Consorzio Agrario di Siena",
        "history_summary": (
            "Nasce all'inizio del Novecento come cooperativa dei produttori della "
            "provincia, e questa origine spiega perché non somigli a un negozio "
            "di souvenir: qui la filiera corta non è un'etichetta di marketing ma "
            "il motivo per cui l'insegna esiste. È il posto in cui i senesi "
            "comprano la farina e il vino, e da cui il visitatore esce con le "
            "stesse cose invece che con una scatola decorata."
        ),
        "highlights": [
            {"name": "Il banco del pane e dei dolci", "why": "panforte, ricciarelli e cavallucci fatti sul posto: la differenza con la scatola sigillata del centro si sente al primo morso"},
            {"name": "Gli scaffali del vino", "why": "le denominazioni della provincia a prezzo di negozio, non di enoteca turistica"},
            {"name": "Gli oli e i legumi locali", "why": "è la parte che entra in valigia senza rompersi e che dura fino a casa"},
        ],
        "curiosita": [
            "Il panforte nasce come pane speziato da mercanti, fatto per non guastarsi nei viaggi lunghi: la consistenza compatta non è un vezzo, è una tecnica di conservazione.",
            "La tradizione vuole che i cavallucci prendano il nome dai cavallari, i postiglioni che li mangiavano alle stazioni di cambio dei cavalli.",
            "I ricciarelli si fanno con pasta di mandorle e si cuociono poco: se sono duri, non sono freschi. È il modo più rapido per giudicare un banco di dolci senese.",
        ],
        "errore_da_evitare": "Comprare i dolci nelle scatole illustrate dei negozi del centro pensando siano gli stessi: la differenza non è il prezzo, è la data di produzione, e sul panforte si sente al primo morso.",
        "dintorni": [
            {"name": "Piazza Salimbeni", "why": "due minuti: si passa di lì tornando verso il centro"},
            {"name": "La Lizza", "why": "cinque minuti: nel giorno di mercato è la versione all'aperto della stessa spesa"},
            {"name": "Piazza del Campo", "why": "cinque minuti in discesa, per chiudere il viaggio dove è cominciato"},
        ],
        "practical_tips": [
            "Chiedi il sottovuoto per salumi e formaggi: lo fanno, ed è la differenza fra portarli a casa e buttarli.",
            "Se voli con solo bagaglio a mano, ricorda che oli, mieli e creme spalmabili non passano il controllo: vanno in stiva o non vanno.",
            "Il panforte pesa molto più di quanto sembri: due confezioni sono già mezzo chilo di bagaglio.",
        ],
        "best_time_to_visit": "tardo pomeriggio, come ultima tappa prima di rientrare",
        "estimated_visit_duration": "40 minuti",
        "consiglio_personalizzato": (
            "È l'ultima tappa del viaggio ed è voluto: si compra alla fine, non "
            "all'inizio, così non ci si porta dietro il peso per due giorni. "
            "Guarda il vademecum in questo stesso documento prima di riempire il "
            "carrello — la sezione sul bagaglio dice cosa può salire in cabina."
        ),
        "disclaimer": "Giorni e orari di apertura cambiano nei festivi. Se torni in aereo, verifica prima le regole sui liquidi in cabina e, per l'estero, le norme doganali sui prodotti alimentari.",
    },
]
TIPS = {
    "sections": [
        {"id": "biglietti_prenotazioni", "title": "Biglietti e prenotazioni", "tips": [
            "Torre del Mangia: ingressi contingentati a 50 persone ogni 30 minuti. Prenota lo slot delle 11:20 online il giorno prima, altrimenti l'attesa in piazza è di 40-60 minuti a settembre.",
            "Duomo: l'OPA SI Pass copre Duomo, Libreria Piccolomini, Cripta e Museo dell'Opera. Con le due visite che hai in programma si ripaga già il primo giorno.",
            "Taverna di San Giuseppe: prenotazione praticamente obbligatoria anche a pranzo. Il numero è cliccabile nella scheda del ristorante qui sotto.",
        ]},
        {"id": "bagagli_logistica", "title": "Bagagli e logistica", "tips": [
            "Il centro storico è chiuso al traffico: se arrivi in auto, il parcheggio Santa Caterina ha la risalita meccanizzata che ti porta a 8 minuti dal Campo.",
            "Scarpe con suola scolpita, non da ginnastica liscia: il lastricato in pietra serena di Siena è scivoloso, soprattutto in discesa verso San Domenico.",
            "Il check-in a Palazzo Ravizza è dalle 14: il primo giorno arrivi in piazza alle 10:30, quindi lascia i bagagli in hotel prima — lo fanno anche prima dell'orario.",
        ]},
        {"id": "risparmio_pagamenti", "title": "Risparmio e pagamenti", "tips": [
            "Al bancomat rifiuta sempre la conversione nella tua valuta: la commissione nascosta è tra il 3 e il 12%.",
            "Il pranzo alla Taverna con il menù del giorno costa circa 25-30 € contro i 45-55 € della carta: chiedilo, non è esposto.",
            # [AGGIORNATO 2026-08-02] Diceva "774 € su 800 €, margine 26 €":
            # era la cifra prodotta dal doppio conteggio dell'alloggio, corretto
            # in `cost_estimator`. Un consiglio che contraddice la tabella dei
            # costi stampata due pagine sopra è peggio di un consiglio assente.
            "Il totale stimato di questo viaggio è 465–512 € su un budget di 800 €: il margine copre una cena fuori programma o un museo in più senza rifare i conti.",
        ]},
        {"id": "meteo_luce_stagione", "title": "Meteo, luce e stagione", "tips": [
            "Metà settembre a Siena: 26-28 °C di giorno, 14-16 °C la sera. Serve uno strato leggero per la cena all'aperto, non un cappotto.",
            "Il tramonto è verso le 19:40: la luce migliore su Piazza del Campo è tra le 18:30 e le 19:15.",
            "Un temporale pomeridiano è possibile: i piani B nella sezione dedicata sono già scelti tra i luoghi del tuo itinerario.",
        ]},
        {"id": "pratico_sicurezza", "title": "Pratico e sicurezza", "tips": [
            "Siena è una delle città più sicure d'Italia: l'unico rischio reale è il borseggio in Piazza del Campo nelle ore di punta.",
            "Le fontanelle pubbliche del centro sono potabili e segnalate: riempi la borraccia, l'acqua in bottiglia in piazza costa 3 €.",
            "Il numero unico di emergenza è il 112, lo trovi anche nella scheda \"Prima di partire\".",
        ]},
        {"id": "vita_notturna", "title": "Vita notturna", "tips": [
            "Siena non è una città da locali fino a tardi: la sera si concentra tra Via di Città e Piazza del Campo, e alle 24 è finita.",
            "Enoteca I Terzi resta aperta oltre le 23 ed è uno dei pochi posti dove si mangia tardi davvero.",
        ]},
    ],
    "rain_plans": [
        {
            "day": 1,
            "summary": "Se piove, la Torre chiude per sicurezza: l'alternativa è a 300 metri e resta dentro il tuo biglietto cumulativo.",
            "swaps": [
                {"replaces": "Salita alla Torre del Mangia", "name": "Santa Maria della Scala",
                 "why": "coperto, enorme, e sposta il museo del giorno 2 lasciandoti il giorno 2 più libero"},
            ],
        },
        {
            "day": 2,
            "summary": "La Fortezza è un parco all'aperto: con la pioggia non ha senso.",
            "swaps": [
                {"replaces": "Passeggiata alla Fortezza Medicea", "name": "Pinacoteca Nazionale di Siena",
                 "why": "a 10 minuti a piedi, quasi sempre vuota, e la collezione di fondi oro è la più importante d'Italia"},
            ],
        },
    ],
}

FEEDBACK = {
    "message": (
        "Se sei tornato da Siena, ci farebbe davvero comodo sapere com'è andata: "
        "serve a rendere il prossimo itinerario migliore di questo."
    ),
    "questions": [
        "La Taverna di San Giuseppe è stata all'altezza?",
        "Il secondo giorno ti è sembrato troppo vuoto?",
    ],
}

# --- Montaggio ------------------------------------------------------------
# [RIFATTO 2026-08-02 (ter) — task #169 "rendere questo lo standard"]
# Il montaggio era codice a modulo: importare questo file scriveva un PDF su
# disco. Ora e' una funzione, e il PDF si scrive solo se il file viene
# eseguito. Il motivo non e' estetico: `tests/test_standard_qualita.py`
# controlla lo standard di qualita' PROPRIO SU QUESTO campione, e deve poterlo
# montare senza produrre file. Cosi' l'esempio che Lorenzo guarda e il
# documento su cui girano i controlli sono lo stesso documento — se qualcuno
# domani impoverisce il campione per far passare un test, i controlli sullo
# standard cadono con lui invece di continuare a dire "verde" su un campione
# svuotato.
def build_sample_render_kwargs(con_fascicolo: bool = False):
    """Monta il campione completo e restituisce
    `(itinerary, trip, kwargs_di_render, sezioni_cadute)`."""
    _trip_obj = Trip(
        email=TRIP["email"], destination=TRIP["destination"],
        date_start=TRIP["date_start"], date_end=TRIP["date_end"],
        duration_days=TRIP["duration_days"], budget_eur=TRIP["budget_eur"],
        budget_mode=TRIP["budget_mode"], objective_function=TRIP["objective_function"],
    )
    # Attenzione: il renderer legge gli hotel come dizionari, ma cost_estimator
    # li legge come oggetti (getattr). In produzione arrivano dal payload
    # LiteAPI, che e' fatto di oggetti; qui vanno passati in entrambe le forme,
    # altrimenti la tabella dei costi mostra "prezzo non fornito" e il campione
    # sembra rotto quando invece e' solo il finto payload a essere della forma
    # sbagliata.
    _payload = SimpleNamespace(
        poi=[SimpleNamespace(**p) for p in POIS],
        hotels=[SimpleNamespace(**h) for h in HOTELS],
    )
    # [CORRETTO 2026-08-03 — segnalazione del cliente: «risolvi il problema
    # delle cartine che non si vedono»]
    # Qui la chiave di Google non veniva passata AFFATTO: non "era assente",
    # proprio non c'era il parametro. Conseguenza: il campione percorreva
    # sempre e comunque il ramo senza rete e disegnava lo schema fatto in
    # casa — anche su una macchina con la chiave configurata e con internet.
    # Il documento che serve a controllare il prodotto era l'unico che non
    # poteva mostrare la cartina vera del prodotto. Ora la chiave, se c'e',
    # si usa; se non c'e' il campione lo DICE (vedi l'avviso in fondo al
    # file) invece di far sembrare lo schema il comportamento normale.
    _google = (os.getenv("GOOGLE_MAPS_KEY") or "").strip() or None
    sections = pdf_extras.build_pdf_sections(
        ITINERARY, _trip_obj, _payload, api_key=None, google_maps_key=_google,
    )
    # [AGGIUNTO 2026-08-05 — task #190/#192] Il foglio della valigia vive
    # dentro `sections` con una chiave che la lista bianca del renderer NON
    # accetta: va letto adesso, prima del filtro, altrimenti sparisce.
    _sezioni_intere = sections
    sections, section_errors = pdf_extras.split_render_kwargs(sections)

    # I consigli e i piani B in produzione arrivano da Claude (`api_key`), che
    # qui non c'e': si sostituisce il testo scritto a mano, non la logica.
    sections["tips"] = TIPS

    # [2026-08-02] Qui c'era un rattoppo: senza chiave Google le cartine
    # sparivano, e l'esempio se le ricostruiva da solo con `png=None` per non
    # perdere almeno la legenda. Tolto. Ora la pipeline vera disegna lo schema
    # in locale (`src/map_render.py`) e questo esempio percorre ESATTAMENTE la
    # stessa strada del prodotto. Un esempio che si aggiusta da se' non e' un
    # esempio, e' una vetrina: non avrebbe mai potuto mostrare il difetto che
    # il cliente ha visto.
    used = {b.get("poi_id") for d in ITINERARY["days"] for b in d["blocks"]}
    _poi_usati = [p for p in POIS if p["id"] in used]

    # [AGGIUNTO 2026-08-03 — task #181] Le immagini. Questa riga mancava, e la
    # sua assenza era un difetto piu' grave di quanto sembri: il campione e'
    # il documento su cui si decide se il prodotto va bene, e sarebbe uscito
    # senza NESSUNA immagine il giorno stesso in cui le immagini erano la
    # modifica principale. Chi lo avesse guardato avrebbe concluso che il
    # lavoro non era stato fatto.
    #
    # `raccogli_foto` percorre la stessa strada del prodotto: prova la
    # fotografia vera di Google e, quando non la ottiene, disegna la
    # copertina in casa. Senza chiave o senza rete resta la seconda — e il
    # campione lo DICE in fondo, invece di far passare il ripiego per il
    # risultato normale (stessa regola gia' applicata alle cartine).
    sections["photos"] = _foto.raccogli_foto(
        GUIDES, _poi_usati, api_key=_google,
        citta=TRIP.get("destination") or "",
    )

    # [AGGIUNTO 2026-08-05 — task #190] Il fascicolo: le guide diventano
    # capitoli staccati cuciti dentro lo stesso file, e il foglio della
    # valigia entra come allegato.
    #
    # Perche' e' un interruttore e non il comportamento fisso: stampare i
    # capitoli vuol dire nove chiamate a wkhtmltopdf, che sul campione sono
    # oltre tre minuti. La suite dei controlli monta questo documento decine
    # di volte, e tre minuti moltiplicati per decine sono una suite che
    # nessuno esegue piu' — cioe' il modo piu' sicuro di perdere tutti i
    # controlli insieme. I controlli che guardano l'HTML del documento
    # principale montano quindi la versione senza fascicolo, che NON e' una
    # finzione: e' la strada di riserva vera, quella che il cliente riceve
    # ogni volta che la stampa di un capitolo non riesce.
    #
    # Il campione CONSEGNATO — quello che si guarda per decidere se il
    # prodotto va bene — si monta invece con il fascicolo (vedi in fondo al
    # file), e il suo controllo di insieme sta in
    # `tests/test_fascicolo_2026_08_05.py`.
    if con_fascicolo:
        pdf_extras.prepara_fascicolo(
            GUIDES, sections, itinerary=ITINERARY, trip=_trip_obj,
            poi=_poi_usati, photos=sections.get("photos"),
        )
        _sezioni_intere["capitoli_pdf"] = sections.get("capitoli_pdf")
        if pdf_extras.allega_foglio_valigia(_sezioni_intere):
            sections["allegati"] = _sezioni_intere["allegati"]

    kwargs = dict(
        hotels=HOTELS, guides=GUIDES, feedback=FEEDBACK,
        poi=_poi_usati,
        **sections,
    )
    return ITINERARY, TRIP, kwargs, section_errors


if __name__ == "__main__":
    _itinerary, _trip, _kwargs, _section_errors = build_sample_render_kwargs(
        con_fascicolo=True)
    pdf_renderer.render_pdf(
        _itinerary, _trip, output_path="/tmp/esempio-2026-08-02.pdf", **_kwargs
    )
    print("OK \u2192 /tmp/esempio-2026-08-02.pdf")
    print("sezioni cadute:", _section_errors or "nessuna")

    # [AGGIUNTO 2026-08-03] Il capitolo della recensione esce senza riquadro
    # "Rispondi qui" ogni volta che la URL manca o non \u00e8 valida. Senza questa
    # riga la differenza fra "il modulo non \u00e8 configurato" e "il modulo \u00e8
    # configurato male" non si vede: si vede solo un capitolo pi\u00f9 corto.
    # [AGGIUNTO 2026-08-03] Stessa logica dell'avviso qui sotto, applicata
    # alle cartine. Senza questa riga un campione con lo schema disegnato in
    # casa e un campione con la cartina stradale vera si distinguono solo
    # guardandoli: e chi li guarda, guardando lo schema, conclude che il
    # prodotto non ha la cartina. Non e' vero, ma e' quello che si vede.
    _fonti = {d.get("map_source") for d in (_kwargs.get("day_maps") or [])}
    if "schema" in _fonti:
        print("\u26a0\ufe0f  Cartine disegnate in casa (schema), non stradali. "
              "Nel campione questo succede quando GOOGLE_MAPS_KEY non e' "
              "impostata oppure quando la macchina non raggiunge "
              "maps.googleapis.com. In produzione la chiave c'e' e la base "
              "stradale viene scaricata: quello che vedi qui e' la RETE DI "
              "SICUREZZA, non il risultato normale.")

    # [AGGIUNTO 2026-08-03 — task #181] Stesso avviso delle cartine, applicato
    # alle immagini: un campione illustrato con le copertine disegnate in casa
    # e uno illustrato con le fotografie vere si somigliano abbastanza da far
    # credere che le fotografie non ci siano mai state.
    _immagini = _kwargs.get("photos") or {}
    _vere = sum(1 for v in _immagini.values() if isinstance(v, dict) and v.get("reale"))
    print(f"immagini: {len(_immagini)} guide illustrate, {_vere} con foto vera")
    if _immagini and not _vere:
        print("\u26a0\ufe0f  Nessuna FOTOGRAFIA vera: quelle che vedi sono le "
              "copertine disegnate in casa, il ripiego. Succede quando "
              "GOOGLE_MAPS_KEY non e' impostata oppure quando la macchina non "
              "raggiunge places.googleapis.com. In produzione la chiave c'e' e "
              "la fotografia del luogo viene scaricata.")

    if not (_kwargs.get("feedback_link") or {}).get("url"):
        print("\u26a0\ufe0f  Modulo recensione assente dal campione: imposta "
              "FEEDBACK_FORM_URL con la URL https:// del modulo Tally vero "
              "(e FEEDBACK_REF_SECRET) prima di rigenerarlo.")

    print("schede locale:", len(_kwargs.get("place_cards") or {}))
    print("tratte 'come arrivare':",
          sum(len(d.get("legs") or []) for d in _kwargs.get("directions") or []))
    print("voci 'prima di partire':",
          len((_kwargs.get("predeparture") or {}).get("checklist") or []))

    # [AGGIUNTO 2026-08-02 — task #172] Il foglio della valigia esce accanto al
    # PDF, come esce accanto al PDF nella mail del cliente. Viene ricostruito
    # qui e non restituito da `build_sample_render_kwargs()` perche' quella
    # funzione ha una firma su cui girano i controlli dello standard: e' un
    # allegato, non un argomento del renderer.
    from src import checklist_xlsx as _checklist_xlsx

    # [AGGIUNTO 2026-08-03 - task #184] Il numero di viaggiatori si passa
    # DAVVERO: prima non si passava e restava il valore per difetto, uno, per
    # cui il campione usciva con una sola colonna di spunte anche quando il
    # viaggio era per tre. Il difetto stava solo nel campione - il servizio
    # vero il numero lo passa da sempre - ma il campione e' il documento su
    # cui si decide se il prodotto va bene, e mostrava la funzione rotta.
    _blob = _checklist_xlsx.build_checklist_xlsx(
        _trip, _kwargs.get("vademecum"), _kwargs.get("predeparture"), _itinerary,
        travellers=int(_trip.get("travelers") or 1),
    )
    if _blob:
        _nome = "/tmp/" + _checklist_xlsx.build_checklist_filename(_trip)
        with open(_nome, "wb") as _f:
            _f.write(_blob)
        print("foglio della valigia:", _nome,
              f"({(_kwargs.get('checklist_sheet') or {}).get('rows', 0)} voci, "
              f"{int(_trip.get('travelers') or 1)} colonne di spunte)")
        print("\u26a0\ufe0f  Il foglio del campione NON ha il bottone «torna "
              "all'itinerario»: quel bottone porta all'indirizzo pubblico del "
              "PDF, che esiste solo quando l'itinerario viene ospitato "
              "(PUBLIC_BASE_URL su Render). Qui il PDF e' un file locale e un "
              "bottone che non apre niente e' peggio di nessun bottone.")
    else:
        print("foglio della valigia: non generato")
