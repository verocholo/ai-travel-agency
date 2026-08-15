"""
Ciclo di dati sulle recensioni — src/feedback_link.py.

[AGGIUNTO 2026-08-01 — punto 6 del feedback "da investitore" del
2026-08-01: la sezione "Facci sapere com'è andata" oggi genera domande
bellissime, personalizzate sul viaggio vero... e poi non c'è nessun posto
dove il cliente possa rispondere. Non un link, non un modulo, niente. È
un questionario stampato su carta e infilato in una bottiglia.]

Il problema che risolve è che, senza risposte che tornano indietro, non
esiste nessun modo di sapere se il prodotto funziona. L'unico segnale
disponibile oggi è l'assenza di rimborsi richiesti, che è un segnale
pessimo: misura la pigrizia del cliente, non la qualità dell'itinerario.

Tre cose servono perché quel ciclo si chiuda, e sono le tre che questo
modulo fornisce:

1. **Un posto dove rispondere.** `FEEDBACK_FORM_URL` (un modulo Tally,
   lo stesso strumento già usato per l'ordine). Se la variabile non è
   impostata il modulo è inerte e il PDF esce esattamente come oggi:
   nessuna sezione rotta, nessun link morto.

2. **Un modo di ricollegare la risposta al viaggio giusto** senza
   chiedere al cliente di ricordarsi niente e senza mettere dati
   personali in una URL. È il `ref`: una stringa corta e opaca, derivata
   con HMAC-SHA256 dai dati del viaggio quando `FEEDBACK_REF_SECRET` è
   impostata (così lo stesso viaggio dà sempre lo stesso codice, anche
   se il PDF viene rigenerato), casuale altrimenti. Dal codice non si
   torna indietro all'email di nessuno.

3. **Domande CONFRONTABILI fra clienti diversi.** Questo è il punto
   meno ovvio e il più importante. Le domande generate dal modello sono
   personalizzate sul viaggio — ottime per far parlare una persona,
   inutilizzabili per rispondere a "il ritmo delle giornate è giusto?"
   su cento clienti, perché ogni cliente ha ricevuto una domanda diversa.
   `CORE_QUESTIONS` è il set fisso che invece si può contare: stesse
   domande per tutti, stesse opzioni di risposta, quindi una tabella
   invece di cento aneddoti. Le due cose convivono: le personalizzate
   fanno aprire la persona, queste producono il dato.

[AGGIUNTO 2026-08-03 — segnalazione del cliente: «il link di tally non
funziona ancora»] Le tre cose sopra erano scritte, ma nessuna di esse
controllava che la URL configurata potesse davvero funzionare. Con
`FEEDBACK_FORM_URL` a `https://tally.so/r/ESEMPIO` (il valore lasciato nel
generatore del campione) il PDF usciva con un link al 404 di Tally; con un
valore senza schema (`tally.so/r/xyz`) wkhtmltopdf lo risolveva contro il
file HTML temporaneo e ne faceva un `file:///tmp/...` che `pdf_links.py`
scarta — un link morto e invisibile. Da qui la regola di `validate_form_url()`:
una URL che non può funzionare NON viene stampata affatto. Meglio un
capitolo senza riquadro che un riquadro che porta al nulla: il primo si
nota e si sistema, il secondo sembra funzionare fino al clic del cliente.

Variabili d'ambiente (tutte opzionali):

    FEEDBACK_FORM_URL     URL del modulo di risposta, `https://` assoluta.
                          Assente o non valida → nessun link nel PDF.
    FEEDBACK_REF_SECRET   segreto per derivare il `ref` in modo stabile.
                          Assente → `ref` casuale (funziona lo stesso, ma
                          rigenerare il PDF produce un codice diverso).
    FEEDBACK_REF_PARAM    nome del parametro nella URL, default "ref".
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

# Lunghezza del codice mostrato al cliente. 10 caratteri esadecimali sono
# ~40 bit: abbastanza da non collidere su qualunque volume questo progetto
# possa realisticamente raggiungere, abbastanza pochi da poterli ricopiare a
# mano in un modulo senza sbagliare.
REF_LENGTH = 10

DEFAULT_REF_PARAM = "ref"


# ---------------------------------------------------------------------------
# Le domande confrontabili.
#
# Volutamente POCHE. Ogni domanda in più abbassa il tasso di risposta, e un
# questionario da quindici domande a cui risponde il 3% dei clienti produce
# meno informazione di sei domande a cui risponde il 30%. Ognuna di queste è
# qui perché la sua risposta cambierebbe una decisione concreta:
#
#   voto           — la metrica di riferimento nel tempo, l'unica che dice se
#                    le modifiche al prodotto lo stanno migliorando.
#   seguito        — se il piano non viene seguito, tutto il lavoro di
#                    ottimizzazione logistica è sprecato per definizione.
#   ritmo          — il difetto più probabile di un itinerario generato da un
#                    modello: troppe cose in un giorno. Senza questa domanda
#                    resta un'opinione (vedi la regola anti-noia e
#                    `validator.check_day_density`, che oggi tira a indovinare).
#   saltato        — dice QUALI raccomandazioni non reggono alla realtà.
#   mancato        — l'unica domanda che può far scoprire una sezione che
#                    manca del tutto al prodotto.
#   consiglio      — il Net Promoter classico: prossimo alla verità sulla
#                    disponibilità a pagare e a portare altri clienti.
#   testimonianza  — consenso ESPLICITO, mai presunto (stessa regola già
#                    scritta in prompts/system_prompt_feedback.txt).
# ---------------------------------------------------------------------------
CORE_QUESTIONS = [
    {
        "id": "voto",
        "text": "Da 1 a 10, quanto è stato utile l'itinerario che ti abbiamo mandato?",
        "type": "scala_1_10",
    },
    {
        "id": "seguito",
        "text": "Quanto hai seguito il programma giorno per giorno?",
        "type": "scelta",
        "options": ["Quasi tutto", "Circa metà", "Poco", "Per niente"],
    },
    {
        "id": "ritmo",
        "text": "Il ritmo delle giornate com'era?",
        "type": "scelta",
        "options": ["Troppo pieno", "Giusto", "Troppo vuoto"],
    },
    {
        "id": "saltato",
        "text": "C'è qualcosa che avevamo consigliato e che hai saltato? Cosa, e perché?",
        "type": "testo",
    },
    {
        "id": "mancato",
        "text": "Cosa avresti voluto trovare nel documento e non c'era?",
        "type": "testo",
    },
    {
        "id": "consiglio",
        "text": "Da 0 a 10, quanto consiglieresti questo servizio a un amico?",
        "type": "scala_0_10",
    },
    {
        "id": "testimonianza",
        "text": "Possiamo usare pubblicamente una tua frase su questo viaggio, "
                "con il tuo nome di battesimo?",
        "type": "scelta",
        "options": ["Sì", "Sì ma senza nome", "No"],
    },
]


# ---------------------------------------------------------------------------
# Validazione della URL configurata.
#
# La regola è asimmetrica di proposito, perché i due errori non costano
# uguale: stampare una URL rotta manda il cliente su un 404 (e quello che
# perdiamo è la sua fiducia, non solo la sua risposta), mentre scartare per
# sbaglio una URL buona toglie il riquadro in silenzio e nessuno se ne
# accorge finché non smettono di arrivare risposte. Quindi si scarta solo
# quello che NON PUÒ funzionare, mai quello che "sembra strano".
# ---------------------------------------------------------------------------

# Nomi che nessun generatore di moduli assegnerebbe mai a un form vero: sono
# parole che una persona scrive quando ancora non ha l'id definitivo. Gli id
# di Tally sono stringhe casuali (`wA5b2Q`), quindi il rischio di falso
# positivo è nullo su questi e alto su qualunque parola di senso compiuto in
# più — per questo NON ci sono qui dentro "test", "demo" o "sample", che un
# modulo vero può legittimamente chiamarsi (un form di prova usato davvero
# resta un form che risponde).
_ID_SEGNAPOSTO = frozenset({
    "esempio", "esempi", "example", "placeholder", "segnaposto",
    "changeme", "cambiami", "todo", "tbd", "fixme",
    "none", "null", "undefined", "xxx", "xxxx", "xxxxx",
    "formid", "idform", "yourformid", "tuoformid", "iddelmodulo",
    "daimpostare", "dainserire", "inseriscilaurl", "urldelmodulo",
})

# Domini che per definizione non ospitano niente (RFC 2606 e RFC 6761): una
# URL che punta lì non è "probabilmente" sbagliata, è sbagliata e basta.
_HOST_RISERVATI = frozenset({"localhost", "example.com", "example.net", "example.org"})
_SUFFISSI_RISERVATI = (".localhost", ".invalid", ".test", ".example",
                       ".example.com", ".example.net", ".example.org")


def _normalizza_id(testo: str) -> str:
    """`TUO-FORM-ID`, `tuo_form_id` e `TuoFormId` sono lo stesso segnaposto:
    il confronto va fatto sulle sole lettere e cifre, minuscole."""
    return "".join(c for c in testo.lower() if c.isalnum())


def validate_form_url(raw: object) -> str | None:
    """La URL configurata se può funzionare, None altrimenti. Non solleva mai.

    Scarta, in quest'ordine: quello che non è testo (una variabile
    d'ambiente è sempre una stringa, ma questa funzione la chiamano anche
    altri), il vuoto e i soli spazi (il modo più comune di credere di aver
    configurato qualcosa senza averlo fatto), tutto ciò che non è una URL
    assoluta `https` (`http://` è vietato in tutto il repo: questo documento
    contiene nome e date di viaggio di una persona; senza schema il PDF
    produce un `file:///` morto), le URL senza host, i domini riservati e gli
    id di modulo che sono chiaramente un segnaposto mai sostituito.
    """
    if not isinstance(raw, str):
        return None
    base = raw.strip()
    if not base:
        return None
    try:
        pezzi = urlsplit(base)
        host = (pezzi.hostname or "").lower()
    except ValueError:
        # URL sintatticamente indecifrabile (parentesi IPv6 sbilanciate, ecc.).
        return None
    if pezzi.scheme.lower() != "https" or not host:
        return None
    if host in _HOST_RISERVATI or host.endswith(_SUFFISSI_RISERVATI):
        return None
    segmenti = [s for s in pezzi.path.split("/") if s]
    if segmenti and _normalizza_id(segmenti[-1]) in _ID_SEGNAPOSTO:
        return None
    return base


def form_url() -> str | None:
    """URL del modulo di risposta, o None se non configurata o non valida."""
    try:
        return validate_form_url(os.getenv("FEEDBACK_FORM_URL"))
    except Exception:  # noqa: BLE001 — il PDF non fallisce per una variabile
        return None


def _ref_param() -> str:
    raw = (os.getenv("FEEDBACK_REF_PARAM") or "").strip()
    return raw or DEFAULT_REF_PARAM


def build_reference(trip: object = None) -> str:
    """Codice opaco che identifica QUESTA consegna.

    Con `FEEDBACK_REF_SECRET` impostata è deterministico: lo stesso viaggio
    produce sempre lo stesso codice, quindi rigenerare il PDF (per un errore,
    per un affinamento) non spezza il collegamento con la risposta già data.
    Senza segreto ricade su un valore casuale — funziona, ma quel legame si
    perde a ogni rigenerazione.

    Il codice NON è reversibile e non contiene dati personali: è l'HMAC
    troncato di destinazione+date+email, non l'email cifrata. Chi intercetta
    la URL vede un codice, non un cliente. `email` entra nel calcolo solo per
    distinguere due viaggiatori con lo stesso viaggio nelle stesse date, mai
    nell'output.
    """
    secret = (os.getenv("FEEDBACK_REF_SECRET") or "").strip()
    if not secret:
        return secrets.token_hex((REF_LENGTH + 1) // 2)[:REF_LENGTH]

    getter = trip.get if isinstance(trip, dict) else lambda k, d=None: getattr(trip, k, d)
    parts = []
    for field in ("email", "destination", "date_start", "date_end"):
        try:
            value = getter(field, None)
        except Exception:  # noqa: BLE001 — un Trip esotico non deve rompere il PDF
            value = None
        parts.append("" if value is None else str(value))
    material = "|".join(parts).encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), material, hashlib.sha256).hexdigest()
    return digest[:REF_LENGTH]


def build_feedback_url(ref: str | None = None) -> str | None:
    """URL completa da mettere nel PDF, o None se il modulo non è configurato
    o se la URL configurata non può funzionare (vedi `validate_form_url`).

    [CORRETTO 2026-08-03] Il parametro veniva attaccato in coda con una
    `f`-string. Su una URL con un'ancora (`https://.../wA5b2Q#inizio`) il
    risultato era `...#inizio?ref=abc`: sintatticamente valido, ma `ref`
    finisce DENTRO l'ancora e il modulo non lo riceve mai — il cliente
    risponde e la risposta arriva senza sapere di quale viaggio parli, che è
    esattamente il caso in cui non serve a niente. Ora la query si ricostruisce
    con `urllib.parse`, quindi il parametro entra dove deve (prima
    dell'ancora, che resta in fondo) e il vecchio comportamento sul
    separatore `?`/`&` si ottiene di conseguenza invece che a mano. Anche il
    NOME del parametro viene ora codificato: `FEEDBACK_REF_PARAM` la scrive
    una persona a mano nella dashboard, e uno spazio o una `&` di troppo
    spezzerebbero la URL in due parametri diversi.
    """
    base = form_url()
    if not base:
        return None
    if not ref:
        return base
    try:
        pezzi = urlsplit(base)
        parametri = parse_qsl(pezzi.query, keep_blank_values=True)
        parametri.append((_ref_param(), str(ref)))
        # `quote_via=quote` e non il `quote_plus` di default: uno spazio
        # diventa `%20` e non `+`, che è la forma che tutti i moduli
        # interpretano allo stesso modo.
        return urlunsplit(pezzi._replace(query=urlencode(parametri, quote_via=quote)))
    except Exception:  # noqa: BLE001 — nessun PDF fallisce per un link
        return None


def build_feedback_link(trip: object = None) -> tuple[str | None, str | None]:
    """Comodità per il chiamante: ritorna `(ref, url)` in un colpo solo.

    `ref` esiste sempre (serve comunque a Make per archiviare la consegna in
    Airtable); `url` è None finché FEEDBACK_FORM_URL non è impostata.
    """
    ref = build_reference(trip)
    return ref, build_feedback_url(ref)
