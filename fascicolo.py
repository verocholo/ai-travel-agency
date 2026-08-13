"""Il fascicolo: documenti diversi, un file solo.

[NUOVO 2026-08-05 — richiesta di Lorenzo, parola per parola: «altrettanto
fondamentale è che questi documenti seppur diversi stiano in un unico file,
non so come farai ma trova il modo»]

## Il problema, detto in italiano

Il cliente compra un itinerario. Dentro ci sono cose molto diverse fra loro:
il programma dei giorni, una guida per ogni attrazione, il foglio della
valigia. Fino a ieri le guide erano PDF separati ospitati su Render: per
aprirle serviva internet, e chi è in aereo o all'estero senza dati si trovava
con dei collegamenti morti. Peggio: erano *file* diversi, e Lorenzo ha chiesto
esplicitamente il contrario.

## Come si risolve

Ogni pezzo viene stampato per conto suo — così ognuno può avere la sua
impaginazione, la sua copertina, la sua identità — e poi i pezzi vengono
CUCITI in un unico PDF. Il foglio di calcolo, che non è un PDF e non si può
cucire, entra come allegato vero dentro il file (la graffetta che Anteprima,
Acrobat e Foxit sanno aprire).

## Perché i collegamenti sopravvivono alla cucitura

Questo è il punto delicato, ed è già risolto altrove: `src/pdf_links.py`.
wkhtmltopdf non sa scrivere un rimando interno, quindi ogni documento semina
delle *sonde* — collegamenti finti `ancora-interna:<nome>` — e alla fine una
passata di riparazione le trasforma in veri salti di pagina.

La cosa che rende possibile il fascicolo è che quella passata lavora sul file
GIÀ CUCITO. A quel punto le sonde di tutti i documenti stanno nella stessa
tabella, quindi un rimando può attraversare il confine fra un documento e
l'altro — in tutte e due le direzioni:

    documento principale  --#capitolo-duomo-->        capitolo staccato
    capitolo staccato     --#ritorno-duomo-...-->     documento principale

Misurato sul banco di prova prima di scrivere questo modulo: `riscritti: 2,
sonde: 2, non_risolte: [], goto: 2`.

## Perché i nomi delle ancore si calcolano e non si accumulano

Il bottone «torna indietro» sta nel capitolo, ma il punto in cui deve tornare
sta nel documento principale: due file stampati da due funzioni diverse, in
momenti diversi. Se il nome dell'ancora venisse messo da parte in una
variabile condivisa, basterebbe cambiare l'ordine di stampa per rompere
tutto, in silenzio.

Qui invece il nome si RICAVA dall'itinerario (giorno + posizione del blocco).
Le due parti lo calcolano ognuna per conto suo e ottengono lo stesso
risultato — e un controllo può verificare che siano d'accordo, cosa
impossibile se il nome fosse un effetto collaterale.

Nessuna funzione di questo modulo solleva eccezioni verso l'alto: se la
cucitura fallisce il cliente riceve comunque il documento principale, che è
la parte che ha pagato.
"""

from __future__ import annotations

import io
import re

# La stessa identica regola di `pdf_renderer._slug`. È ricopiata invece che
# importata perché `pdf_renderer` importerà questo modulo, e un import
# circolare farebbe fallire l'avvio del servizio. Il duplicato non è lasciato
# all'onore: `test_fascicolo` verifica che le due versioni diano la stessa
# risposta su una batteria di casi storti.
_SLUG_UNSAFE = re.compile(r"[^a-zA-Z0-9_-]+")

# Prefissi dei nomi. Sono costanti perché compaiono in due moduli diversi
# (qui e in `poi_pdf`) e un refuso non deve poter passare inosservato.
PREFISSO_CAPITOLO = "capitolo"
PREFISSO_RITORNO = "ritorno"

# Etichette viste dal cliente.
ETICHETTA_GIORNO = "Torna al Giorno"
ETICHETTA_CARTINA = "Torna alla cartina del Giorno"


def _slug(value) -> str:
    """Id sicuro per un'ancora. Copia esatta di `pdf_renderer._slug`."""
    return _SLUG_UNSAFE.sub("-", str(value or "")).strip("-").lower()


def ancora_capitolo(chiave) -> str:
    """Il punto di atterraggio, in cima al capitolo staccato di un'attrazione.

    `chiave` è di norma il `poi_id`. Se è vuota il nome resta comunque
    utilizzabile (`capitolo`), perché un'ancora brutta è un problema
    estetico mentre un'ancora vuota è un collegamento rotto.
    """
    coda = _slug(chiave)
    return f"{PREFISSO_CAPITOLO}-{coda}" if coda else PREFISSO_CAPITOLO


def ancora_ritorno(chiave, origine) -> str:
    """Il punto di atterraggio del bottone «torna indietro».

    `origine` dice DA DOVE si era partiti, ed è quello che permette di
    rispettare la richiesta di Lorenzo: «ogni collegamento esterno abbia un
    pulsante per ritornare al documento principale, nel punto esatto di dove
    si era arrivati originariamente».

    La stessa attrazione può essere raggiunta da due punti — dal programma
    del Giorno 2 e dalla cartina del Giorno 2 — e i due bottoni devono
    riportare in due posti diversi. Per questo il nome contiene l'origine e
    non solo l'attrazione.

    Forme previste per `origine`:
        ("blocco", numero_giorno, posizione_nel_giorno)
        ("cartina", numero_giorno)
    ma qualunque sequenza di pezzi semplici funziona: vengono messi in fila.
    """
    if isinstance(origine, (str, bytes)) or not hasattr(origine, "__iter__"):
        pezzi = [origine]
    else:
        pezzi = list(origine)
    # `str(p)` PRIMA di `_slug`, e non è un dettaglio: `_slug` scrive
    # `str(value or "")`, quindi lo zero — che è falso in Python — le
    # sparirebbe fra le dita. Lo zero qui è la PRIMA attività del giorno,
    # cioè il caso più frequente di tutti: senza questa riga il bottone
    # «torna» della prima tappa punterebbe a un'ancora che non esiste.
    # Trovato girando il codice, non a tavolino.
    coda = "-".join(x for x in (_slug(str(p)) for p in pezzi) if x)
    testa = _slug(chiave)
    parti = [PREFISSO_RITORNO]
    if testa:
        parti.append(testa)
    if coda:
        parti.append(coda)
    return "-".join(parti)


def ancora_cartina(numero_giorno) -> str:
    """Il punto di atterraggio del ritorno alla cartina di un giorno.

    [CORRETTO 2026-08-05, poche ore dopo la prima versione] All'inizio anche
    questa ancora portava dentro il nome dell'attrazione, come quelle dei
    blocchi. Era sbagliato per due motivi, e il secondo l'ha mostrato il
    campione vero:

      1. **non serve a niente.** Il posto in cui si torna è la cartina del
         Giorno 2, punto: è lo stesso identico posto per tutte e nove le
         tappe di quella cartina. Nove nomi diversi per un solo posto sono
         nove modi di dire la stessa cosa;
      2. **non funzionava.** Nove nomi vogliono nove segnaposti, tutti
         ammucchiati nello stesso millimetro sopra la figura, e il motore di
         stampa non ha assegnato un'annotazione a tutti: sul campione vero
         quattro rimandi su nove sono rimasti morti. Un segnaposto solo, in
         un punto solo, esce sempre.

    Meno nomi, meno segnaposti, meno modi di sbagliare.
    """
    return ancora_ritorno("", ("cartina", numero_giorno))


def _etichetta_blocco(numero_giorno, orario) -> str:
    """«Torna al Giorno 2 · 09:30» — o senza orario se non c'è."""
    testo = f"{ETICHETTA_GIORNO} {numero_giorno}"
    orario = (orario or "").strip()
    return f"{testo} &#183; {orario}" if orario else testo


def elenca_ritorni(itinerary, guides, *, giorni_con_cartina=None) -> dict:
    """Per ogni attrazione che ha un capitolo, tutti i punti da cui ci si
    arriva.

    Restituisce `{poi_id: [{"origine", "ancora", "etichetta"}, ...]}`.

    Il documento principale usa questo elenco per SEMINARE le ancore nei
    punti giusti; il capitolo staccato lo usa per DISEGNARE un bottone per
    ogni punto. Sono due letture della stessa lista, e questo è il motivo per
    cui il ritorno non può sbagliare bersaglio.

    L'ordine è quello di lettura del documento (giorno crescente, poi la
    cartina del giorno prima dei blocchi di quel giorno), così i bottoni nel
    capitolo compaiono nell'ordine in cui il cliente ha incontrato i rimandi.

    `giorni_con_cartina` sono i numeri dei giorni che una cartina ce l'hanno
    davvero, e va passato: senza, non si generano ritorni dalla cartina.

    [CORRETTO 2026-08-05, poche ore dopo averlo scritto] La prima versione
    dava per scontato che ogni giorno avesse la sua cartina, e il controllo
    di insieme l'ha smentita subito: sul documento senza cartine restavano
    due bottoni «torna alla cartina del Giorno N» che puntavano a un punto
    inesistente. Non è un caso di scuola — la chiamata a Google Static Maps
    che va male è il guasto più frequente di questo progetto — ed è
    esattamente il difetto che questo modulo esiste per non avere: un
    collegamento morto stampato su un documento pagato.
    """
    con_capitolo = set()
    for guida in guides or []:
        if not isinstance(guida, dict):
            continue
        poi_id = guida.get("poi_id")
        if isinstance(poi_id, str) and poi_id:
            con_capitolo.add(poi_id)
    if not con_capitolo:
        return {}

    giorni = []
    if isinstance(itinerary, dict):
        giorni = itinerary.get("days") or []

    con_cartina = set()
    for numero in (giorni_con_cartina or []):
        con_cartina.add(numero)

    ritorni: dict[str, list[dict]] = {}

    def aggiungi(poi_id, origine, etichetta, ancora=""):
        voce = {
            "origine": tuple(origine),
            "ancora": ancora or ancora_ritorno(poi_id, origine),
            "etichetta": etichetta,
        }
        ritorni.setdefault(poi_id, []).append(voce)

    for giorno in giorni:
        if not isinstance(giorno, dict):
            continue
        numero = giorno.get("day")
        blocchi = giorno.get("blocks") or []

        # La cartina viene prima nel documento, quindi prima anche qui.
        if numero in con_cartina:
            visti = []
            for blocco in blocchi:
                if not isinstance(blocco, dict):
                    continue
                poi_id = blocco.get("poi_id")
                if (isinstance(poi_id, str) and poi_id in con_capitolo
                        and poi_id not in visti):
                    visti.append(poi_id)
            for poi_id in visti:
                # Ancora CONDIVISA da tutte le tappe di questa cartina: il
                # posto in cui si torna è uno solo. Vedi `ancora_cartina()`.
                aggiungi(
                    poi_id, ("cartina", numero),
                    f"{ETICHETTA_CARTINA} {numero}",
                    ancora=ancora_cartina(numero),
                )

        for posizione, blocco in enumerate(blocchi):
            if not isinstance(blocco, dict):
                continue
            poi_id = blocco.get("poi_id")
            if not isinstance(poi_id, str) or poi_id not in con_capitolo:
                continue
            aggiungi(
                poi_id, ("blocco", numero, posizione),
                _etichetta_blocco(numero, blocco.get("time")),
            )

    return ritorni


def unisci(principale: bytes, capitoli) -> bytes:
    """Mette in fila più PDF in un file solo, conservando i collegamenti.

    `pypdf` copia le annotazioni di link insieme alle pagine: è la ragione
    per cui questo approccio funziona invece di stampare tutto due volte.

    Se qualcosa va storto — un capitolo illeggibile, `pypdf` assente —
    torna indietro il documento principale intatto. Il cliente perde le
    guide, non l'itinerario.
    """
    pezzi = [c for c in (capitoli or []) if isinstance(c, bytes) and c]
    if not pezzi:
        return principale
    try:
        from pypdf import PdfWriter

        scrittore = PdfWriter()
        scrittore.append(io.BytesIO(principale))
        for pezzo in pezzi:
            scrittore.append(io.BytesIO(pezzo))
        fuori = io.BytesIO()
        scrittore.write(fuori)
        return fuori.getvalue()
    except Exception:
        return principale


def allega(dati: bytes, allegati) -> bytes:
    """Infila dei file dentro il PDF come veri allegati (la «graffetta»).

    Serve al foglio della valigia: è un `.xlsx`, non si può cucire fra le
    pagine, ma può viaggiare DENTRO lo stesso file. Chi apre il PDF con
    Anteprima, Acrobat o Foxit lo trova nel pannello degli allegati.

    Attenzione all'onestà: non tutti i lettori mostrano quel pannello, e
    quelli dei telefoni quasi mai. Per questo il foglio esiste anche come
    capitolo stampabile dentro il PDF — la decisione «doppio binario» presa
    con Lorenzo. Questa funzione è solo uno dei due binari.

    `allegati` è `{nome_file: contenuto}`. Errori: si torna indietro con il
    file com'era.
    """
    voci = {
        nome: blob for nome, blob in (allegati or {}).items()
        if isinstance(nome, str) and nome and isinstance(blob, bytes) and blob
    }
    if not voci:
        return dati
    try:
        from pypdf import PdfReader, PdfWriter

        scrittore = PdfWriter()
        scrittore.append(PdfReader(io.BytesIO(dati)))
        for nome, blob in voci.items():
            scrittore.add_attachment(nome, blob)
        fuori = io.BytesIO()
        scrittore.write(fuori)
        return fuori.getvalue()
    except Exception:
        return dati


def pagine_di_partenza(principale: bytes, capitoli, ancore) -> dict:
    """`{nome_ancora: indice della prima pagina del suo capitolo}`.

    [AGGIUNTO 2026-08-13] Serve a non dipendere piu' dai segnaposto per sapere
    dove atterra un collegamento. Il conto e' banale — le pagine del documento
    principale, poi quelle di ogni capitolo in fila — ed e' un'informazione
    che abbiamo per COSTRUZIONE: siamo noi a decidere l'ordine in cui i
    capitoli vengono cuciti.

    Fino a oggi la stessa informazione veniva dedotta guardando il PDF finito,
    cercando un'ancora invisibile larga due pixel. Funzionava in sviluppo e in
    produzione no, perche' il motore di stampa la' non la disegnava affatto:
    sette capitoli, zero collegamenti, e nessuno se ne accorgeva.

    Non solleva mai: se il conto non riesce, si torna una mappa vuota e il
    meccanismo dei segnaposto resta l'unico, esattamente come prima.
    """
    try:
        from pypdf import PdfReader

        mappa = {}
        pagina = len(PdfReader(io.BytesIO(principale)).pages)
        for pezzo, ancora in zip(capitoli or [], ancore or []):
            quante = len(PdfReader(io.BytesIO(pezzo)).pages)
            if isinstance(ancora, str) and ancora:
                mappa[ancora] = pagina
            pagina += quante
        return mappa
    except Exception:  # noqa: BLE001 — una mappa mancante non e' un guasto
        return {}


def cuci(principale: bytes, capitoli=None, allegati=None, ancore=None) -> tuple[bytes, dict]:
    """Il fascicolo completo: cuci le pagine, infila gli allegati, ripara i
    rimandi.

    L'ordine non è negoziabile ed è il cuore di questo modulo:

      1. UNIONE — `pypdf` riscrive tutto il file da capo;
      2. ALLEGATI — `pypdf` lo riscrive ancora;
      3. RIPARAZIONE — la nostra passata, che aggiunge in fondo senza
         toccare il resto.

    Se la riparazione venisse prima, i passaggi di `pypdf` la
    cancellerebbero: riscrivendo il file da zero, le sonde già trasformate in
    salti di pagina tornerebbero collegamenti finti o sparirebbero. Fatta per
    ultima, l'ultimo a scrivere siamo noi, e nessuno può disfare il lavoro.

    Torna `(byte, resoconto)`. Il resoconto serve alla diagnostica: dice
    quanti capitoli sono entrati, quanti allegati, e cosa ha trovato la
    riparazione. Non solleva mai.
    """
    resoconto = {
        "capitoli": 0,
        "allegati": 0,
        "unione_riuscita": False,
        "allegati_riusciti": False,
        "collegamenti": {},
        "errore": "",
    }
    dati = principale
    try:
        pezzi = [c for c in (capitoli or []) if isinstance(c, bytes) and c]
        if pezzi:
            unito = unisci(dati, pezzi)
            if unito is not dati and len(unito) > len(dati):
                resoconto["capitoli"] = len(pezzi)
                resoconto["unione_riuscita"] = True
                dati = unito

        voci = {
            nome: blob for nome, blob in (allegati or {}).items()
            if isinstance(nome, str) and nome
            and isinstance(blob, bytes) and blob
        }
        if voci:
            con_allegati = allega(dati, voci)
            if con_allegati is not dati:
                resoconto["allegati"] = len(voci)
                resoconto["allegati_riusciti"] = True
                dati = con_allegati

        from src import pdf_links

        note = pagine_di_partenza(principale, pezzi, ancore) if pezzi else {}
        riparato, rapporto = pdf_links.repair_internal_links_bytes(
            dati, ancore_note=note)
        resoconto["collegamenti"] = rapporto
        dati = riparato
    except Exception as exc:  # pragma: no cover - rete di sicurezza
        resoconto["errore"] = type(exc).__name__
    return dati, resoconto
