"""Dove cade ogni capitolo sulla carta, e quali vanno mandati a capo.

PERCHE' QUESTO FILE ESISTE

Lorenzo, 15 agosto 2026: «ti sei perso l'impaginazione pero', non e' come
avevamo concordato si spezzano i capitoli. cerca di fare terminare i capitoli
a fine pagina».

Ha ragione su cio' che vede, e il rimedio ovvio sarebbe sbagliato. Mandare
**ogni** capitolo a inizio pagina e' gia' stato provato su questo prodotto, ed
e' costato sette pagine con il quaranta per cento di bianco: sta scritto nello
standard di qualita', misurato. Un documento fatto di pagine mezze vuote non
e' impaginato meglio, e' impaginato peggio — e Lorenzo stesso, l'11 agosto,
aveva segnalato l'altro lato della stessa medaglia: «non voglio una pagina
iniziata per due righe e poi lasciata bianca».

## Il difetto vero, detto con precisione

Non e' che un capitolo occupi due pagine — un capitolo lungo lo fa in
qualunque libro. E' che un capitolo **cominci in fondo a una pagina**: la
testata colorata, magari una riga di presentazione, e poi il foglio finisce.
Chi sfoglia vede un titolo appiccicato al bordo e il contenuto altrove: si
legge come un errore di stampa, ed e' esattamente quello che si nota.

## Come si fa a saperlo, visto che il motore di stampa non lo dice

Non si indovina: si stampa e si guarda dove sono finite le cose.

Ogni capitolo semina gia' una **sonda** — un collegamento invisibile che il
motore di stampa trasforma in un'annotazione con le sue coordinate. Serviva a
riparare i rimandi interni (vedi `src/pdf_links.py`); dice pero' anche, senza
costi aggiuntivi, **su quale pagina e a che altezza** e' finita la testata di
ogni capitolo.

Quindi: si stampa una volta, si guarda quali testate sono cadute troppo in
basso, si rimanda a capo **solo quelle**, e si ristampa. Una passata sola in
piu', su un documento gia' generato — nessuna chiamata a nessun modello,
nessun dato in piu' da nessuna parte.

## Perche' «solo quelle» e' il punto

Un capitolo che comincia a meta' pagina e prosegue sulla successiva sta bene
com'e': mandarlo a capo aggiungerebbe mezza pagina bianca per riparare un
difetto che non c'era. La regola qui dentro tocca **una minoranza** di
capitoli a ogni documento, ed e' cio' che la rende un miglioramento invece di
uno scambio.
"""

from __future__ import annotations

# L'altezza di un foglio A4 in punti tipografici. Il documento e' A4 in tutte
# le sue parti (lo dice il foglio di stile, e c'e' un controllo che lo
# verifica): non serve leggerla dal file, e leggerla male sarebbe peggio.
ALTEZZA_A4_PT = 842.0

# Quanta parte di pagina deve restare SOTTO la testata perche' il capitolo
# possa cominciare li'. Un quarto di pagina sono cinque o sei righe piu' la
# testata: abbastanza perche' si veda che il capitolo e' cominciato.
#
# Il numero e' misurato, non scelto: sotto il 20% la testata resta comunque
# appiccicata al bordo; sopra il 30% si cominciano a mandare a capo capitoli
# che stavano benissimo, e ricompare il bianco.
QUOTA_MINIMA_SOTTO = 0.25


def posizioni(dati: bytes) -> dict:
    """`{nome_ancora: (pagina, altezza_dal_basso_in_punti)}`.

    Si legge dalle sonde, cioe' dal documento STAMPATO: e' l'unica fonte che
    sappia dove sono finite le cose davvero. Non solleva mai — senza sonde
    torna vuoto, e chi chiama non fa niente.
    """
    try:
        from . import pdf_links

        pdf = pdf_links._Pdf(dati)
        pagine = pdf_links._page_order(pdf)
        pagina_di = {}
        for indice, numero_pagina in enumerate(pagine):
            for annotazione in pdf_links._annots_of_page(pdf, numero_pagina):
                pagina_di[annotazione] = indice

        trovate: dict[str, tuple[int, float]] = {}
        for numero in pdf.objects:
            corpo = pdf.body(numero)
            if b"/Subtype /Link" not in corpo and b"/Subtype/Link" not in corpo:
                continue
            uri = pdf_links._uri_di(corpo)
            if not uri or not uri.startswith(pdf_links.PROBE_PREFIX):
                continue
            from urllib.parse import unquote

            nome = unquote(uri[len(pdf_links.PROBE_PREFIX):]).strip("/")
            riquadro = pdf_links._rect(corpo)
            if nome and riquadro and numero in pagina_di and nome not in trovate:
                trovate[nome] = (pagina_di[numero], riquadro[3])
        return trovate
    except Exception:
        return {}


# Quanto deve restare, come minimo, sotto l'ultima fotografia di una
# giornata perche' quella giornata si consideri "finita con spazio bianco".
#
# [AGGIUNTO 2026-08-16 — l'ultimo dei nove difetti segnalati da Lorenzo sul
# fascicolo di Bologna: pagine 15, 18, 21, 26, «due foto piccole e spazio
# vuoto».] Trenta per cento e' la stessa soglia, vista dal lato opposto, di
# `ARRIVO_MINIMO` in `scripts_qualita_pagina.py` (70% di riempimento minimo
# = 30% di margine massimo tollerato): le due misurano la stessa cosa con
# strumenti diversi — quella sui pixel della pagina stampata, questa sui
# punti di una sonda — e usare lo stesso numero evita due definizioni
# diverse dello stesso difetto che un domani potrebbero disallinearsi.
QUOTA_BIANCO_GIORNATA = 0.30


def giornate_con_bianco_finale(dati: bytes, numeri_giorni,
                               ancore_successive=(),
                               quota: float = QUOTA_BIANCO_GIORNATA) -> set:
    """Quali giornate finiscono con troppo spazio bianco sotto l'ultima foto.

    [AGGIUNTO 2026-08-16 — l'ultimo dei nove difetti segnalati da Lorenzo sul
    fascicolo di Bologna: pagine 15, 18, 21, 26, «due foto piccole e spazio
    vuoto». La strada scelta e' ingrandire le fotografie di chiusura
    giornata, non allargare i margini — vedi
    `src/pdf_renderer._render_striscia_foto`.]

    Stesso metodo di `capitoli_da_mandare_a_capo`, applicato a un problema
    diverso: non si indovina, si stampa, si guarda dove sono cadute le sonde,
    si ripara SOLO quello che serve. La sonda qui non e' la testata di un
    capitolo ma la chiusura di ogni giornata (`giorno-{N}-fine`, seminata da
    `src/pdf_renderer.py` subito dopo l'ultima cosa che quella giornata
    stampa): dice a che altezza dal fondo pagina si e' fermato il contenuto,
    fila di foto compresa.

    Una giornata entra nel risultato SOLO se tutte e tre le condizioni sono
    vere — le prime due esistono per non riparare un difetto che non c'e':

    - **non e' l'ultima pagina del documento intero.** Quella e' la
      chiusura, finisce dove finisce, e allungarla per riempirla e' il
      difetto opposto — stessa regola che usa
      `scripts_qualita_pagina.problemi()` saltando l'ultima pagina.
    - **quello che viene dopo comincia su una pagina SUCCESSIVA.** Se la
      giornata dopo (o, per l'ultima giornata, il primo capitolo dopo)
      comincia sulla STESSA pagina, lo spazio lo riempie gia' lei:
      ingrandire qui sposterebbe soltanto il problema, non lo toglierebbe.
      `ancore_successive` e' l'elenco dei nomi da controllare per l'ultima
      giornata, nell'ordine in cui possono comparire nel documento — di
      solito `CAPITOLI_DEL_DOCUMENTO` di `src/pdf_renderer.py`, filtrato ai
      capitoli che vengono dopo il programma.
    - **la sonda di chiusura si e' fermata alta sulla pagina**, sopra la
      soglia `quota` dell'altezza del foglio: e' la misura diretta dello
      spazio bianco rimasto sotto.

    Torna un insieme di NUMERI di giornata (non di nomi di sonda): e' quello
    che `_render_striscia_foto` chiede per decidere, giornata per giornata,
    se ingrandire la propria fila di chiusura.
    """
    dove = posizioni(dati)
    if not dove:
        return set()
    pagine_note = [pagina for pagina, _altezza in dove.values()]
    if not pagine_note:
        return set()
    ultima_pagina = max(pagine_note)

    try:
        ordinati = sorted({int(n) for n in (numeri_giorni or [])})
    except (TypeError, ValueError):
        return set()

    trovate = set()
    for indice, numero in enumerate(ordinati):
        fine = dove.get(f"giorno-{numero}-fine")
        if not fine:
            continue
        pagina, altezza = fine
        if pagina >= ultima_pagina:
            continue

        prossima_pagina = None
        if indice + 1 < len(ordinati):
            prossima = dove.get(f"giorno-{ordinati[indice + 1]}")
            if prossima:
                prossima_pagina = prossima[0]
        else:
            for nome in (ancore_successive or ()):
                trovata = dove.get(nome)
                if trovata:
                    prossima_pagina = trovata[0]
                    break

        if prossima_pagina is None or prossima_pagina <= pagina:
            continue

        if altezza >= ALTEZZA_A4_PT * quota:
            trovate.add(numero)
    return trovate


# Quanto deve restare SOTTO la fine del documento perche' l'ultima pagina
# del corpo si consideri "una coda orfana".
#
# [AGGIUNTO 2026-08-18 — l'ultimo difetto rimasto sul campione misurato:
# «pagina 11: il contenuto si ferma al 6.0% del foglio».]
#
# Sessanta per cento vuol dire: la pagina finale del corpo e' piena per meno
# di due quinti. Sotto quella soglia non e' piu' «un capitolo che finisce
# dove finisce» — e' tre righe e poi mezzo foglio bianco, con dietro le
# schede delle guide che ricominciano. Nel fascicolo cucito quella pagina
# sta in MEZZO al documento, non in fondo: e' li' la differenza con
# `scripts_qualita_pagina.problemi()`, che l'ultima pagina la salta.
# [ALZATA A 0.55 il 2026-08-18 — richiesta di Lorenzo: «evita di spezzare
# troppo le pagine» e, prima, «le foto devono occupare lo spazio bianco».]
#
# Era 0.60, cioe' si interveniva solo quando l'ultima pagina del corpo era
# piena per meno di due quinti. Da quando i capitoli scorrono invece di
# prendersi una pagina a testa, quella pagina finale capita spesso intorno
# alla meta' — misurato: 49.6% — e restava fuori dalla riparazione per un
# soffio. Sotto il 55% la pagina si riempie con una fotografia mai usata,
# ed e' esattamente cio' che Lorenzo ha chiesto di fare con lo spazio
# bianco.
QUOTA_CODA_ORFANA = 0.48


def quante_pagine(dati: bytes) -> int:
    """Quante pagine ha questo PDF. Zero se non si riesce a leggerlo.

    Serve al cancello della ristampa: una ristampa che compatta la coda ha
    senso SOLO se toglie una pagina. Se non la toglie si tiene la prima, che
    ha il testo per esteso.
    """
    try:
        from . import pdf_links

        return len(pdf_links._page_order(pdf_links._Pdf(dati)))
    except Exception:
        return 0


def coda_orfana(dati: bytes, sonda: str = "documento-fine",
                quota: float = QUOTA_CODA_ORFANA) -> bool:
    """Vero se il corpo del documento finisce con una pagina quasi vuota.

    Si legge dalla sonda che il documento semina nell'ultima cosa che stampa
    (la nota di chiusura): la sua altezza dal fondo del foglio E' lo spazio
    bianco rimasto sotto. Alta sulla pagina = poco contenuto sopra di lei.

    Due condizioni, e la prima non e' una formalita':

    - **la sonda non e' sulla prima pagina.** Un documento di una pagina
      sola finisce dove finisce, e non c'e' niente da compattare;
    - **e' rimasta alta**, sopra `quota` dell'altezza del foglio.

    Non solleva mai: senza sonde torna falso e chi chiama non fa niente —
    il documento esce come sempre.
    """
    dove = posizioni(dati)
    trovata = dove.get(sonda) if dove else None
    if not trovata:
        return False
    pagina, altezza = trovata
    if pagina <= 0:
        return False
    return altezza >= ALTEZZA_A4_PT * quota


# Quanto foglio deve restare SOTTO l'inizio di una scheda perche' la sua
# fotografia di apertura ci stia.
#
# [AGGIUNTO 2026-08-18 — Lorenzo su pagina 16 dell'anteprima: «non mi piace
# come e' impaginata, togli lo spazio bianco».] La fotografia di una scheda
# e' alta circa dodici centimetri fra figura e didascalia: su un foglio A4
# sono quattro decimi di pagina. Sotto quella soglia la figura non entra,
# scende alla pagina dopo e si porta dietro tutto il testo — mezzo foglio
# bianco sotto un titolo solo.
#
# Il numero e' piu' alto di `QUOTA_MINIMA_SOTTO` di proposito: quello dice
# «la testata e' appiccicata al bordo, manda a capo il capitolo», questo dice
# «c'e' posto per il testo ma non per la figura, sposta la figura». Sono due
# riparazioni diverse per due difetti diversi, e la prima ha la precedenza.
QUOTA_PER_LA_FOTOGRAFIA = 0.55


def capitoli_con_foto_in_coda(dati: bytes, nomi,
                              quota: float = QUOTA_PER_LA_FOTOGRAFIA) -> set:
    """Quali schede cominciano troppo in basso perche' la loro fotografia
    ci stia sotto.

    Restituisce i nomi delle ancore. Chi chiama ristampa QUELLE schede con la
    fotografia dopo la storia invece che prima: il testo comincia subito
    sotto il titolo e riempie il foglio.

    Non comprende le schede che vanno gia' mandate a capo: per quelle il
    problema e' un altro e la riparazione pure — cominciano su una pagina
    nuova, dove di posto ce n'e' tutto.
    """
    dove = posizioni(dati)
    if not dove:
        return set()
    interessanti = [n for n in (nomi or []) if n in dove]
    if not interessanti:
        return set()
    gia_a_capo = capitoli_da_mandare_a_capo(dati, nomi)
    soglia = ALTEZZA_A4_PT * quota
    return {
        nome for nome in interessanti
        if nome not in gia_a_capo and dove[nome][1] < soglia
    }


def capitoli_da_mandare_a_capo(dati: bytes, nomi,
                               quota: float = QUOTA_MINIMA_SOTTO) -> set:
    """Quali capitoli cominciano troppo in fondo alla loro pagina.

    Il PRIMO capitolo non si manda mai a capo: sta subito sotto la copertina,
    e spostarlo vorrebbe dire aprire il documento con una pagina bianca.
    """
    dove = posizioni(dati)
    if not dove:
        return set()
    interessanti = [n for n in (nomi or []) if n in dove]
    if not interessanti:
        return set()
    # Il capitolo che sta piu' in alto nel documento e' il primo: si esclude.
    primo = min(interessanti, key=lambda n: (dove[n][0], -dove[n][1]))
    soglia = ALTEZZA_A4_PT * quota
    return {
        nome for nome in interessanti
        if nome != primo and dove[nome][1] < soglia
    }


# --------------------------------------------------------------------------
# DUE DIFETTI CHE NON SI MISURANO CON UNA SOGLIA (2026-08-18, sesto giro)
#
# Richiesta di Lorenzo, alla lettera: «non spezzare la pagina su due facciate
# nella guida turistica non mi piace, ed evita di mettere i titoli come ultima
# cosa della pagina, piuttosto vai alla pagina successiva ma solo in quel
# caso».
#
# Sono due difetti, e nessuno dei due e' una questione di quanti centimetri
# restano sotto il titolo — che e' l'unica cosa che sanno dire
# `capitoli_da_mandare_a_capo` e `capitoli_con_foto_in_coda`.
#
# La soglia sbaglia in tutte e due le direzioni:
#
#  - un titolo che comincia al 40% dell'altezza sembra stare comodo, ma se
#    subito sotto c'e' una fotografia alta dodici centimetri — che non si
#    spezza mai — la fotografia scende e il titolo resta l'ultima cosa della
#    pagina. Nessuna soglia sull'altezza del titolo lo vede;
#  - un titolo al 12% con quattro righe di testo sotto non e' orfano, e
#    mandarlo a capo regalerebbe un ottavo di pagina bianca.
#
# Quindi non si misura il titolo: si misura **dove e' finita la prima riga di
# testo** rispetto al titolo. Se e' su una pagina diversa, allora il titolo e'
# davvero l'ultima cosa che si vede — non per stima, per constatazione. Ogni
# scheda semina due sonde in piu' (`{ancora}-testo` all'inizio del primo
# paragrafo, `{ancora}-fine` in fondo a tutto) e le due funzioni qui sotto le
# leggono.
#
# I margini verticali del foglio, in punti tipografici. Servono a una cosa
# sola: sapere quanta carta c'e' davvero fra il primo rigo e l'ultimo, perche'
# «questa scheda ci starebbe in una facciata» dev'essere una sottrazione e non
# un parere. Un centimetro e sei sono i margini della guida — regola `@page`
# in `poi_pdf._css()`. Chi stampa con margini diversi li passa come parametro:
# meglio un numero esplicito qui che una misura sbagliata di nascosto.
MARGINE_VERTICALE_GUIDA_PT = 1.6 * 28.3465


def titoli_orfani(dati: bytes, coppie) -> set:
    """Quali schede stampano il titolo come ULTIMA cosa della pagina.

    `coppie` sono `(ancora_del_titolo, sonda_del_primo_testo)`. Il difetto
    c'e' quando le due sonde cadono su pagine diverse: il titolo sta sul
    foglio di prima, tutto il resto della scheda sul foglio dopo.

    Non e' una stima. E' il difetto stesso, letto sul documento stampato.

    Torna i nomi delle ANCORE, cioe' cio' che `poi_pdf.unisci_le_schede()`
    chiede per mandare quelle schede — e solo quelle — a inizio pagina.

    La prima scheda non puo' comparire nel risultato per costruzione: chi
    chiama non la mette fra le coppie, perche' mandarla a capo vorrebbe dire
    aprire il blocco delle guide con un foglio bianco.
    """
    dove = posizioni(dati)
    if not dove:
        return set()
    orfani = set()
    for ancora, sonda in (coppie or ()):
        titolo = dove.get(ancora)
        testo = dove.get(sonda)
        if not titolo or not testo:
            continue
        if testo[0] > titolo[0]:
            orfani.add(ancora)
    return orfani


def schede_spezzate(dati: bytes, coppie,
                    margine_pt: float = MARGINE_VERTICALE_GUIDA_PT) -> set:
    """Quali schede sono tagliate a meta' fra due facciate PUR STANDOCI in una.

    `coppie` sono `(ancora_del_titolo, sonda_di_fine_scheda)`.

    ## Perche' «pur standoci» non e' un dettaglio

    Una scheda lunga due pagine e mezzo si spezza per forza, in questo come in
    qualunque libro, e mandarla a capo non toglierebbe niente: sposterebbe il
    taglio di qualche riga e lascerebbe indietro mezzo foglio bianco. E' la
    lezione gia' pagata due volte su questo prodotto — un salto di pagina non
    toglie il bianco, lo sposta indietro.

    Il difetto vero e' un altro: una scheda che **starebbe tutta in una
    facciata** e invece comincia a meta' foglio, cosi' che il lettore ne vede
    un pezzo qui e un pezzo voltando pagina. Quella si ripara davvero, e la
    riparazione non costa niente di nuovo: la carta che si lascia indietro e'
    la stessa che la scheda avrebbe comunque sprecato.

    ## Come si sa se ci starebbe

    Con una sottrazione, sulle sonde del documento stampato:

        altezza usata = (quanto scende sulla prima facciata)
                      + (facciate intere in mezzo)
                      + (quanto scende sull'ultima facciata)

    e la si confronta con l'altezza utile del foglio, cioe' l'A4 meno i due
    margini. Se ci sta, e' una scheda spezzata inutilmente; se non ci sta, si
    lascia stare — e il conto la esclude da solo, senza bisogno di un caso a
    parte: una facciata intera in mezzo basta gia' a sforare.

    Non solleva mai: senza sonde torna un insieme vuoto e il documento esce
    come sempre.
    """
    dove = posizioni(dati)
    if not dove:
        return set()
    try:
        margine = float(margine_pt)
    except (TypeError, ValueError):
        return set()
    utile = ALTEZZA_A4_PT - 2 * margine
    if utile <= 0:
        return set()

    spezzate = set()
    for ancora, sonda in (coppie or ()):
        inizio = dove.get(ancora)
        fine = dove.get(sonda)
        if not inizio or not fine:
            continue
        facciate = fine[0] - inizio[0]
        if facciate <= 0:
            continue  # sta tutta su una facciata: e' gia' come la vuole Lorenzo
        sulla_prima = inizio[1] - margine
        sull_ultima = (ALTEZZA_A4_PT - margine) - fine[1]
        usata = sulla_prima + sull_ultima + (facciate - 1) * utile
        if usata <= utile:
            spezzate.add(ancora)
    return spezzate


# --------------------------------------------------------------------------
# LE SONDE CHE NON SONO ANCORE (2026-08-18)
#
# Dal 17 agosto il documento semina anche sonde che NON sono punti di
# atterraggio: servono solo a misurare dove finiscono le cose sulla carta —
# `giorno-N-fine` per sapere quanto bianco resta in fondo a una giornata,
# `guida-banda-inizio` per sapere se la fila di fotografie di una scheda e'
# rimasta isolata in cima a una pagina.
#
# La differenza va dichiarata QUI e non indovinata da chi controlla: il
# controllo che pretende «ogni ancora ha un rimando che ci porta» resta
# giusto per le ancore di navigazione, e diventerebbe un falso allarme se
# contasse anche queste. Un controllo che grida senza motivo si impara a
# ignorarlo, ed e' il modo in cui i controlli veri smettono di funzionare.
# `documento-fine` non e' elencata qui: la regola sul suffisso `-fine` la
# copre gia'. Elencarla due volte darebbe l'idea che le due strade siano
# alternative, e il giorno in cui qualcuno togliesse il suffisso resterebbe
# un elenco che sembra completo e non lo e'.
# [ESTESO 2026-08-18, sesto giro] `-testo` e' la sonda che ogni scheda semina
# all'inizio del suo primo paragrafo: serve a sapere se il titolo e' rimasto
# l'ultima cosa della pagina. Come `-fine`, non e' un posto dove atterrare —
# nessun bottone ci porta, e il controllo dei rimandi non deve aspettarselo.
SONDE_DI_MISURA = ("guida-banda-inizio",)
SUFFISSI_DI_MISURA = ("-fine", "-testo")


def e_sonda_di_misura(nome: str) -> bool:
    """Vero se questa sonda serve a MISURARE, non a farci atterrare qualcuno."""
    testo = str(nome or "")
    return (testo in SONDE_DI_MISURA
            or testo.endswith(SUFFISSI_DI_MISURA))
