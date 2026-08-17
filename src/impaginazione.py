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
