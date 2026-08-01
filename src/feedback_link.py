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

Variabili d'ambiente (tutte opzionali):

    FEEDBACK_FORM_URL     URL del modulo di risposta. Assente → nessun
                          link nel PDF, comportamento di oggi.
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
from urllib.parse import quote

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


def form_url() -> str | None:
    """URL del modulo di risposta, o None se non configurato."""
    url = (os.getenv("FEEDBACK_FORM_URL") or "").strip()
    return url or None


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
    """URL completa da mettere nel PDF, o None se il modulo non è configurato."""
    base = form_url()
    if not base:
        return None
    if not ref:
        return base
    separator = "&" if "?" in base else "?"
    return f"{base}{separator}{_ref_param()}={quote(str(ref), safe='')}"


def build_feedback_link(trip: object = None) -> tuple[str | None, str | None]:
    """Comodità per il chiamante: ritorna `(ref, url)` in un colpo solo.

    `ref` esiste sempre (serve comunque a Make per archiviare la consegna in
    Airtable); `url` è None finché FEEDBACK_FORM_URL non è impostata.
    """
    ref = build_reference(trip)
    return ref, build_feedback_url(ref)
