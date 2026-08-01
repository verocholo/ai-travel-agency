"""
Avvisi legali destinati al cliente — src/legal_notices.py.

[AGGIUNTO 2026-08-01 — punto 6 del feedback "da investitore" del 2026-08-01:
"la parte legale è ancora bozza... sono due frasi da mettere a posto, ma vanno
messe a posto prima di vendere".]

Le due frasi in questione esistevano già, ma esistevano SOLO nelle bozze in
`claude/legal/`, cioè in documenti che il cliente non vede mai. Un termine di
servizio che dice la cosa giusta non serve a niente se la cosa giusta non
compare in nessuno dei tre posti dove il cliente guarda davvero: il modulo
d'ordine, l'email di consegna e il PDF. Questo modulo tiene quei testi in UN
solo posto, versionato insieme al codice, e li mette nel PDF; gli altri due
punti di contatto (modulo Tally e email di Make.com) li leggono da qui perché
`claude/legal/02-testi-consenso-e-form-BOZZA.md` rimanda a questo file invece
di ricopiare le frasi a mano — se si ricopiassero, prima o poi divergerebbero,
ed è esattamente la divergenza fra quello che prometti e quello che scrivi che
un'autorità o un cliente arrabbiato va a cercare.

I due buchi che chiude, entrambi bloccanti prima della prima vendita:

1. **Rinuncia al recesso sui contenuti digitali.** L'art. 59 lett. a) e o) del
   Codice del Consumo fa perdere il recesso di 14 giorni solo se il cliente
   chiede espressamente l'esecuzione immediata E dà atto di perdere il recesso.
   Due conseguenze pratiche che mancavano: la richiesta va RACCOLTA al momento
   dell'acquisto (spunta separata, non pre-spuntata), e va CONFERMATA su
   supporto durevole — in pratica, una riga nell'email di consegna. Senza la
   conferma, la rinuncia raccolta è fragile: chi contesta dirà di non averla
   mai vista.

2. **Informazione, non pacchetto turistico.** Vendere un documento informativo
   e vendere un pacchetto turistico sono due attività con obblighi
   incomparabili (fondo di garanzia, assicurazione, responsabilità per
   l'esecuzione dei servizi). La differenza va detta al cliente in modo
   esplicito e va detta VICINO ai link verso le piattaforme di prenotazione,
   che sono il punto in cui un lettore — o un giudice — potrebbe leggere il
   documento come un'offerta combinata.

NB: nessuno di questi testi è stato rivisto da un avvocato. Sono la versione
"pronta da far vedere", non la versione approvata. `claude/legal/05-brief-per-avvocato.md`
li segnala entrambi come domande da chiudere.
"""
from __future__ import annotations

# Versione dei testi. Serve a una cosa sola ma importante: l'evidenza della
# rinuncia raccolta al checkout va archiviata INSIEME alla versione del testo
# che il cliente ha effettivamente letto. Sapere che "il cliente ha spuntato la
# casella" non prova niente se non si sa più che cosa diceva la casella quel
# giorno. Ogni modifica sostanziale ai testi qui sotto incrementa questo numero.
NOTICES_VERSION = "2026-08-01.1"


# ---------------------------------------------------------------------------
# 1. Natura del servizio — informazione, non pacchetto turistico.
# ---------------------------------------------------------------------------

# Versione breve, per il piede del PDF e per l'intestazione del modulo: deve
# entrare in una riga e deve dire la cosa in modo che non serva rileggerla.
NATURE_SHORT = (
    "Questo è un documento informativo personalizzato: non è un pacchetto "
    "turistico e non comprende prenotazioni, voli, alloggi o assicurazioni."
)

# Versione estesa, per la pagina d'ordine e per l'email di consegna.
NATURE_LONG = (
    "Quello che ricevi è un documento informativo costruito su misura: "
    "consigli, orari, percorsi e stime di spesa. Non siamo un'agenzia di "
    "viaggi né un tour operator, non vendiamo pacchetti turistici e non "
    "prenotiamo nulla al posto tuo. Ogni prenotazione la fai tu, "
    "direttamente con la struttura o con la piattaforma che preferisci, "
    "alle loro condizioni e ai loro prezzi."
)

# Avviso da mettere ACCANTO ai link verso le piattaforme di prenotazione. È il
# punto più delicato del documento: un elenco di link a Booking/Airbnb/Vrbo
# subito sotto un itinerario è esattamente ciò che potrebbe far leggere il
# tutto come un'offerta combinata. La frase chiarisce che sono ricerche
# pubbliche, che non c'è nessun accordo dietro e che noi non entriamo nel
# contratto.
BOOKING_LINKS_NOTICE = (
    "Sono normali ricerche pubbliche, come quelle che faresti tu: non sono "
    "prenotazioni predisposte da noi, non abbiamo accordi con queste "
    "piattaforme e non siamo parte del contratto fra te e loro."
)


# ---------------------------------------------------------------------------
# 2. Esecuzione immediata e rinuncia al recesso.
# ---------------------------------------------------------------------------

# Testo della spunta AL CHECKOUT. Va presentato da solo, non pre-spuntato e
# non accorpato all'accettazione dei Termini: un consenso impacchettato con
# altro non vale, ed è il difetto più comune in questo tipo di form.
WITHDRAWAL_CHECKBOX = (
    "Chiedo che l'itinerario mi sia fornito subito e prendo atto che, "
    "trattandosi di un contenuto digitale eseguito immediatamente, perderò "
    "il diritto di recesso di 14 giorni una volta che la generazione è "
    "iniziata (art. 59 Codice del Consumo). Resta ferma la garanzia legale "
    "di conformità: se il documento è difettoso o non conforme a quanto "
    "promesso, ho diritto ai rimedi di legge."
)

# Conferma su supporto durevole, da inserire nell'email di consegna. È la metà
# che mancava: la spunta al checkout senza questa conferma è una prova debole.
WITHDRAWAL_CONFIRMATION = (
    "Come da tua richiesta espressa al momento dell'acquisto, abbiamo "
    "iniziato subito la generazione dell'itinerario. Per questo motivo, "
    "come avevi confermato, il diritto di recesso di 14 giorni previsto per "
    "gli acquisti a distanza non si applica a questo contenuto digitale "
    "(art. 59 Codice del Consumo). Resta ferma la garanzia legale di "
    "conformità: se il documento è difettoso o non corrisponde a quanto "
    "promesso, scrivici e lo sistemiamo."
)


def consent_record(
    accepted: bool,
    timestamp: str | None = None,
    source: str = "checkout",
) -> dict:
    """Traccia dell'evidenza da archiviare insieme all'ordine.

    Serve a rispondere, mesi dopo, alla sola domanda che conta in una
    contestazione: *questo* cliente, *quel* giorno, ha visto e accettato
    *quale* testo. Per questo la versione dei testi è parte del record: senza,
    l'evidenza dice che una casella è stata spuntata ma non che cosa
    dichiarava.

    Non contiene dati personali: si archivia accanto all'ordine, che ha già la
    sua chiave. Il campo `source` distingue la spunta al checkout dalle altre
    strade possibili (ordine telefonico, riemissione manuale) perché hanno
    valore probatorio diverso.
    """
    return {
        "recesso_rinuncia_accettata": bool(accepted),
        "recesso_testo_versione": NOTICES_VERSION,
        "recesso_raccolta_il": timestamp or "",
        "recesso_raccolta_da": source,
    }


def delivery_email_footer() -> str:
    """Blocco legale dell'email di consegna, in testo semplice.

    Lo consuma il modulo Gmail dello scenario Make.com. È qui e non incollato
    dentro Make per la stessa ragione per cui i prezzi non sono incollati nei
    prompt: un testo duplicato in due sistemi diversi diverge sempre, e qui
    divergere significa promettere per email una cosa diversa da quella
    scritta nei Termini.
    """
    return (
        f"{NATURE_LONG}\n\n"
        f"{WITHDRAWAL_CONFIRMATION}\n\n"
        "Verifica sempre orari di apertura, prezzi e disponibilità prima di "
        "partire o di prenotare: cambiano, e noi fotografiamo la situazione al "
        "momento in cui generiamo il documento."
    )
