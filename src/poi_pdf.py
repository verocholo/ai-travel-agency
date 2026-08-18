"""
Guide per attrazione, come documenti a sé — src/poi_pdf.py.

[AGGIUNTO 2026-08-03 — richiesta di Lorenzo: «migliorare la guida turistica
linkando un pdf per attrazione da te generato ad hoc per la guida con ogni
attrazione con immagini e tutto con bottone di torna all'itinerario alla
parte giusta», e più avanti la frase che tiene insieme tutto il giro:
«come se fosse uno zoom out dal macro al micro». Fra le due strade possibili
(un capitolo "micro" in fondo allo stesso PDF, oppure file separati) Lorenzo
ha scelto esplicitamente: «PDF separati, ospitati su Render».]

Che problema risolve, detto con le sue parole. Il documento principale era
diventato «noioso»: dentro c'era il programma della giornata e, subito
sotto, tutto quello che si poteva dire di ogni singola attrazione. Chi
voleva sapere a che ora si esce doveva sfogliare tre pagine di storia del
Duomo. Separando i due livelli, il principale torna a rispondere alla
domanda macro («che faccio oggi?») e ogni guida risponde alla domanda micro
(«cos'è questo posto, quanto costa, come ci arrivo?») a chi la fa davvero.

Il prezzo di questa scelta, scritto qui perché non venga dimenticato:

  1. **le guide separate NON funzionano senza rete.** Il documento
     principale sì (è un file che il cliente ha scaricato), le guide no:
     sono URL. In aereo, in metropolitana o all'estero senza dati il
     cliente ha l'itinerario e non ha le guide. Per questo il rimando
     INTERNO non viene buttato: quando l'ospitalità non è configurata —
     o quando anche una sola guida non riesce a essere pubblicata — quel
     luogo torna ad avere il suo capitolo dentro il documento principale
     (vedi `pdf_renderer._costruisci_pin_targets`, che sceglie fra le due
     strade una per volta e per singola attrazione);
  2. **sono documenti raggiungibili da chiunque abbia la URL.** Il modello
     di sicurezza è quello di `src/hosting.py` e va letto lì per intero.
     Le guide, a differenza del documento principale, non contengono dati
     personali: non c'è il nome del cliente, non ci sono le sue date, non
     c'è il suo albergo. È deliberato ed è il motivo per cui il
     `consiglio_personalizzato` — l'unico campo della guida che parla del
     cliente in seconda persona — resta dentro il PDF principale e non
     viene stampato qui.

Interfaccia pubblica:

    render_guide_pdf(...) -> bytes | None
    publish_guides(...)   -> dict[poi_id, url]

Nessuna delle due solleva mai. Quando qualcosa non va tornano `None` o un
dizionario vuoto, e il chiamante semplicemente non stampa il link: la
regola di tutto il progetto è che un collegamento morto stampato su un
documento pagato è peggio di un collegamento assente.
"""
from __future__ import annotations

import base64
import os
import subprocess
import tempfile
from pathlib import Path

from src import fascicolo
from src import foto
from src import hosting
from src import scheduling_criteria
from src.pdf_links import LINK_PREFIX, PROBE_PREFIX
from src.pdf_renderer import (
    _esc, _paragraphs, _slug, _tieni_uniti_i_paragrafi,
)

# Quante guide al massimo si pubblicano per una consegna. Non è una paura
# astratta: ogni guida è una stampa di wkhtmltopdf da qualche centinaio di
# millisecondi, e l'esecuzione completa su Make ha un tetto duro di 300
# secondi che una misura reale ha già sfiorato (356 s). Meglio dieci guide
# pubblicate e le altre dentro il documento principale, che un itinerario
# che non arriva.
MAX_GUIDE = 12

# Tetto di sicurezza sulla singola stampa.
TIMEOUT_S = 30


# ---------------------------------------------------------------------------
# Il foglio di stile. È una copia RIDOTTA di quello del documento
# principale, non un import: le guide sono documenti brevi (2-3 pagine) e
# la maggior parte di quelle regole — copertina, indice, cartine, tabelle
# dei costi — qui non serve. Copiare 40 righe è più onesto che trascinarsi
# dietro 900 righe di regole morte dentro ogni singolo file pubblicato,
# moltiplicate per il numero di attrazioni.
#
# I limiti del motore restano gli stessi del documento principale (Qt
# WebKit di wkhtmltopdf): niente sfumature, niente trasparenze, niente
# scatole flessibili. Le due colonne, dove servono, si fanno con le
# tabelle.
# ---------------------------------------------------------------------------
_CSS_MODELLO = """
    /* Le due colonne del corpo della scheda. Tabella e non CSS: il motore di
       stampa le colonne non le conosce. */
    .guida-colonne { width: 100%; border-collapse: separate;
                     border-spacing: 14px 0; margin: 0 -14px; }
    .guida-colonne td { vertical-align: top; width: 50%; }

    .guida-fila { width: 100%; border-collapse: separate; border-spacing: 6px;
                  margin: 14px -6px 0 -6px; page-break-inside: avoid; }
    .guida-fila td { vertical-align: top; }
    .guida-fila img { width: 100%; display: block; }

    /* [AGGIUNTA 2026-08-15] La banda di apertura: la fotografia del luogo,
       grande, e due immagini piccole di altre tappe accanto. Le proporzioni
       non sono un vezzo — la grande deve restare chiaramente la protagonista,
       altrimenti la scheda sembra parlare di tre posti invece che di uno. */
    /* [AGGIUNTA 2026-08-15] La fascia di tre fotografie, in cima e in fondo
       alla scheda.
       [CORRETTO 2026-08-17 — pagine 15/18/21/26, «due foto piccole e tutto
       lo spazio vuoto».] La larghezza della cella ORA la dichiara ogni
       singola cella (`style='width:...'`, scritta da `_banda_di_foto()` in
       base a quante fotografie ci sono DAVVERO): un `width` fisso qui nel
       foglio di stile vincerebbe sempre su quello scritto in linea per la
       stessa identica proprieta', e due o una fotografia resterebbero
       strette a un terzo di pagina come se fossero sempre tre. */
    .keep { width: 100%; border-collapse: collapse;
            page-break-inside: avoid; }
    .keep td { padding: 0; border: none; }
    .guida-banda { width: 100%; border-collapse: separate; border-spacing: 6px;
                   margin: 0 -6px 6px -6px; page-break-inside: avoid; }
    .guida-banda td { vertical-align: top; padding: 0; }
    .guida-banda img { width: 100%; display: block; }

    @page { size: A4; margin: 1.6cm 1.6cm; }
    * { box-sizing: border-box; }
    body {
      font-family: 'Helvetica Neue', Arial, sans-serif;
      color: #22303f; line-height: 1.55; margin: 0; font-size: 13px;
    }
    /* [RIFATTO 2026-08-05 — task #195] Stessa identita' del documento
       principale (`src/identita.py`). Prima il capitolo si apriva con un
       pannello blu dagli angoli tondi e il principale con una pagina di
       carta: due documenti dentro lo stesso file con due facce diverse
       sono due documenti, non uno. Adesso si riconoscono come parenti. */
    .testata {
      background-color: #ffffff; color: #16212f;
      border-top: 3px solid {{accento}};
      padding: 18px 0 16px 0; margin-bottom: 4px;
    }
    .testata .occhiello {
      font-size: 9px; letter-spacing: .20em; color: {{accento_testo}};
      text-transform: uppercase; margin-bottom: 14px; font-weight: bold;
    }
    .testata h1 {
      font-family: Georgia, 'Times New Roman', serif;
      margin: 0; font-size: 34px; line-height: 1.1; font-weight: normal;
    }
    .testata .dove {
      font-family: Georgia, 'Times New Roman', serif;
      font-size: 13px; font-style: italic; color: #6c7683; margin-top: 8px;
    }
    .foto { text-align: center; margin: 12px 0 4px 0; }
    .foto img { max-width: 100%; border-radius: 0; }
    /* [CORRETTO 2026-08-17 — pagina 13: «i crediti delle foto sono scritti
       troppo in grande».]
       La regola valeva SOLO `.foto .credito`, cioe' solo per la fotografia
       singola in testa alla scheda. La fascia di tre fotografie
       (`_banda_di_foto`, quella di pagina 13) scrive lo stesso
       `<div class='credito'>` ma DENTRO una `<td>`, non dentro `.foto`: la
       regola non lo trovava, e il credito ereditava la dimensione del
       corpo del testo — tredici punti, quasi quanto il testo della scheda.
       La regola ora vale OVUNQUE compaia un credito, indipendentemente da
       cosa lo contiene: un font chiaro e piccolo, che non compete con la
       lettura, come chiesto. */
    .credito { font-size: 8px; color: #98a4b0; margin-top: 3px;
               font-weight: normal; line-height: 1.3; }
    .sottotitolo {
      font-family: Georgia, 'Times New Roman', serif;
      font-size: 17px; font-weight: normal; color: #16212f;
      border-bottom: 1px solid {{bordo_caldo}}; padding-bottom: 6px;
      margin: 22px 0 10px 0;
    }
    .corpo { margin: 0 0 9px 0; }
    .riga-luogo { padding: 4px 0; border-bottom: 1px solid {{bordo_caldo}}; }
    .nome-luogo { font-weight: bold; color: #16212f; }
    .riquadro {
      background: {{sfondo_caldo}}; border-left: 2px solid {{accento}};
      padding: 11px 16px; margin: 12px 0;
    }
    .riquadro ul { margin: 6px 0 0 0; padding-left: 18px; }
    .avviso {
      background: #ffffff; border-left: 2px solid #a3423a;
      padding: 11px 16px; margin: 12px 0;
    }
    .fatti { font-size: 12.5px; margin: 8px 0; }
    .pratico { width: 100%; border-collapse: collapse; margin: 6px 0; }
    .pratico td { padding: 5px 10px 5px 0; vertical-align: top; }
    .pratico .voce { color: #6b7a89; width: 34%; font-size: 12px; }
    .bottone-torna { margin: 0 0 9px 0; }
    /* `inline-block` non e' cosmesi: un `<a>` in linea con del padding
       verticale NON alza la riga che lo contiene, quindi due bottoni uno
       sotto l'altro si sovrappongono — visto sul campione del 2026-08-05,
       il secondo mangiava il bordo del primo. Da quando i bottoni di
       ritorno sono piu' d'uno (uno per punto di partenza) la cosa si nota
       ogni volta. */
    .bottone-torna a {
      display: inline-block;
      background-color: {{scuro}}; color: #ffffff; text-decoration: none;
      padding: 10px 18px; border-radius: 0; font-weight: bold;
      font-size: 13px;
    }

    /* [AGGIUNTO 2026-08-05 — task #190] La sonda. Stesse identiche regole
       del documento principale, e per la stessa ragione: wkhtmltopdf assegna
       un'annotazione solo a un elemento che occupa dello spazio, quindi la
       sonda deve essere quasi invisibile ma NON di dimensione zero. Se
       sparisse del tutto, la riparazione dei collegamenti resterebbe cieca e
       tutti i rimandi del fascicolo morirebbero in silenzio. */
    .anchor-probe { font-size: 2px; line-height: 2px; color: #ffffff; }
    .anchor-probe a { color: #ffffff; text-decoration: none; }
    .nota { font-size: 10.5px; color: #6b7a89; margin-top: 12px; }
    a { color: {{primario}}; }
    /* Il motore non sa tenere insieme una scatola alta, ma sa tenere
       insieme una riga di tabella: dove serve davvero si usa quella. */
    tr, img { page-break-inside: avoid; }

    /* [AGGIUNTO 2026-08-03 — task #183] Il guscio che la passata finale di
       impaginazione mette attorno a ogni paragrafo corto, perché non si
       spezzi fra due pagine. Il nome e la regola sono gli stessi del
       documento principale: è lo stesso codice a metterlo, e due fogli di
       stile che lo chiamano in due modi diversi sarebbero solo un modo per
       scoprire fra sei mesi che in uno dei due non ha mai funzionato. */
    .keep-prosa {
      width: 100%; border-collapse: collapse; page-break-inside: avoid;
      margin: 0; border: none;
    }
    .keep-prosa td { padding: 0; border: none; }
"""


def _css(tavolozza: dict | None = None) -> str:
    """Il foglio di stile del capitolo, coi colori del posto (task #209).

    [AGGIUNTO 2026-08-13] I capitoli staccati vengono cuciti dentro lo stesso
    file del documento principale: se restassero blu navy mentre il principale
    e' color cotto, il fascicolo sembrerebbe due documenti incollati per
    sbaglio — un difetto piu' evidente del grigiore da cui siamo partiti.

    La tavolozza si sceglie dalle stesse fotografie che vede il documento
    principale, quindi le due meta' arrivano allo stesso colore da sole. Che
    ci arrivino DAVVERO non e' una cosa da dare per buona: c'e' una prova
    apposta che stampa tutte e due e confronta.
    """
    from src import tavolozza as _tav

    piena = _tav.completa(tavolozza) if tavolozza else _tav.completa(_tav.PREDEFINITA)
    foglio = _CSS_MODELLO
    for ruolo, colore in piena.items():
        if isinstance(colore, str) and colore.startswith("#"):
            foglio = foglio.replace("{{" + ruolo + "}}", colore)
    return foglio


_CSS = _css()


def _righe_nominate(voci, titolo: str) -> str:
    """«Cosa cercare, una volta dentro» e «A due passi da qui»: nome in
    evidenza e, quando c'è, il perché di fianco."""
    righe = []
    for voce in voci or []:
        if isinstance(voce, dict):
            nome, perche = voce.get("name") or "", voce.get("why") or ""
        else:
            nome, perche = str(voce), ""
        if not nome:
            continue
        righe.append(
            f"<div class='riga-luogo'><span class='nome-luogo'>{_esc(nome)}</span>"
            + (f" — {_esc(perche)}" if perche else "")
            + "</div>"
        )
    if not righe:
        return ""
    return f"<div class='sottotitolo'>{_esc(titolo)}</div>" + "".join(righe)


def _riga_pratica(voce: str, contenuto: str) -> str:
    if not contenuto:
        return ""
    return f"<tr><td class='voce'>{_esc(voce)}</td><td>{contenuto}</td></tr>"


def _link(url, etichetta: str) -> str:
    """Un collegamento, ma solo se è cifrato.

    Un `http://` dentro un PDF che viaggia per posta elettronica è una
    segnalazione che i lettori moderni mostrano al cliente, ed è anche
    vietato da un test di regressione del progetto. Meglio niente riga.
    """
    testo = str(url or "").strip()
    if not testo.startswith("https://"):
        return ""
    return f"<a href='{_esc(testo)}'>{_esc(etichetta)}</a>"


_GIORNI_IT = (
    ("Mon", "Lun"), ("Tue", "Mar"), ("Wed", "Mer"), ("Thu", "Gio"),
    ("Fri", "Ven"), ("Sat", "Sab"), ("Sun", "Dom"),
)


def _orari_settimana(open_hours) -> str:
    """La settimana di apertura, in una riga per giorno.

    [AGGIUNTO 2026-08-03 — task #180, richiesta di Lorenzo: «tenendo conto
    degli orari di apertura delle strutture»]

    Questo e' il posto giusto per il dettaglio, ed e' la ragione per cui
    esiste lo "zoom out dal macro al micro": sette righe di orari nel
    documento principale, moltiplicate per venti attrazioni, sono
    centoquaranta righe che nessuno legge; qui dentro sono la prima cosa che
    serve a chi sta decidendo se uscire adesso.

    Un giorno assente dalle chiavi significa CHIUSO, e viene stampato come
    tale: lasciarlo fuori dall'elenco farebbe leggere "non lo sappiamo" a chi
    invece sta guardando l'unica informazione che gli evita un viaggio a
    vuoto. Se `open_hours` manca del tutto la riga non compare affatto — il
    silenzio e' meglio di sette "chiuso" inventati.
    """
    if not isinstance(open_hours, dict) or not open_hours:
        return ""
    righe = []
    for chiave, etichetta in _GIORNI_IT:
        finestre = scheduling_criteria.finestre_del_giorno(open_hours, chiave)
        if finestre:
            testo = " e ".join(f"{inizio}\u2013{fine}" for inizio, fine in finestre)
        else:
            testo = "chiuso"
        righe.append(f"{etichetta} {testo}")
    return "<br>".join(_esc(r) for r in righe)


def _sonda(nome: str) -> str:
    """Il punto di atterraggio di un rimando, dentro una guida.

    [AGGIUNTO 2026-08-05 — task #190] Identico a `pdf_renderer._anchor`: è
    lo stesso meccanismo, e deve restare lo stesso. Il carattere dentro il
    collegamento è uno spazio unificatore, non uno spazio normale: uno spazio
    normale verrebbe collassato dal motore e l'elemento resterebbe largo zero
    pixel — cioè senza annotazione, cioè invisibile alla riparazione.
    """
    sicuro = _esc(str(nome or "").strip())
    if not sicuro:
        return ""
    return (
        f"<span id='{sicuro}' class='anchor-probe'>"
        f"<a href='{PROBE_PREFIX}{sicuro}'>&#160;</a></span>"
    )


def _paragraphi_separati(testo) -> list:
    """Il testo diviso nei suoi paragrafi, ognuno gia' vestito da paragrafo.

    [AGGIUNTO 2026-08-18.] `_paragraphs` li restituisce gia' incollati in
    una stringa sola, che va benissimo per una colonna e non serve a niente
    per due: per bilanciare due colonne bisogna poterli contare e pesare uno
    per uno. Stessa divisione, stesse regole — si riusa `_paragraphs` su ogni
    pezzo invece di riscrivere la spaccatura, cosi' le due strade non
    possono divergere.
    """
    import re as _re

    grezzo = str(testo or "").replace("\r\n", "\n").replace("\r", "\n")
    blocchi = [b.strip() for b in _re.split(r"\n\s*\n", grezzo) if b.strip()]
    if len(blocchi) <= 1:
        singoli = [b.strip() for b in grezzo.split("\n") if b.strip()]
        blocchi = singoli if len(singoli) > 1 else blocchi
    return [_paragraphs(b, "corpo") for b in blocchi if b]


def _due_colonne(pezzi) -> str:
    """Il corpo della scheda su due colonne, bilanciate per altezza.

    [AGGIUNTO 2026-08-13 — task #223.] Ogni guida era lunga circa una pagina e
    mezza, quindi ne occupava due e la seconda restava al 44-62%: otto guide,
    otto mezze pagine bianche. Misurato, e segnalato da Lorenzo.

    Le due strade ovvie erano peggiori. Accorciare la scheda voleva dire
    togliere un terzo del contenuto pagato. Attaccare le guide una dopo
    l'altra faceva sparire il bianco ma anche la reperibilita': una scheda che
    comincia a meta' foglio non si trova piu' sfogliando, e queste guide si
    usano sul posto, col telefono in mano davanti al luogo.

    Due colonne risolvono senza togliere niente: lo stesso testo si dimezza in
    altezza e la scheda sta in una pagina. E si legge meglio — una riga larga
    quanto un A4 e' faticosa, l'occhio si perde tornando a capo. E' il motivo
    per cui guide e riviste sono impaginate in colonne da un secolo e mezzo.

    Si usa una TABELLA perche' il motore di stampa non conosce le colonne CSS:
    vincolo noto di questo progetto, gia' aggirato cosi' per la lista della
    valigia nel vademecum.

    Il bilanciamento e' sulla LUNGHEZZA del testo, non sul numero di blocchi:
    i pezzi hanno altezze molto diverse (una riga di orario contro tre
    paragrafi di storia), e dividerli a meta' per conteggio produrrebbe una
    colonna piena e una vuota — lo stesso difetto, spostato di dieci
    centimetri.
    """
    pieni = [x for x in (pezzi or []) if isinstance(x, str) and x.strip()]
    if not pieni:
        return ""
    if len(pieni) == 1:
        return pieni[0]
    meta = sum(len(x) for x in pieni) / 2.0
    corrente, taglio = 0.0, len(pieni)
    for indice, pezzo in enumerate(pieni):
        corrente += len(pezzo)
        if corrente >= meta:
            # Si taglia DOPO il pezzo che supera la meta', non prima: cosi' la
            # colonna di sinistra e' la piu' piena e il bianco eventuale cade
            # in fondo a destra, dove si legge come margine invece che come
            # buco.
            taglio = indice + 1
            break
    taglio = max(1, min(taglio, len(pieni) - 1))
    return ("<table class='guida-colonne'><tr>"
            f"<td>{''.join(pieni[:taglio])}</td>"
            f"<td>{''.join(pieni[taglio:])}</td></tr></table>")


# Quanto sono larghe, al massimo, le fotografie di contorno della scheda.
# Sulla pagina sono larghe cinque centimetri scarsi: oltre questa misura si
# aggiunge peso al file — che viaggia per posta — senza aggiungere niente che
# un occhio possa vedere.
LARGHEZZA_FOTO_DI_CONTORNO = 560


def _immagine(scatto, larghezza_max: int | None = None, alt: str = "",
              rapporto: float | None = None) -> str:
    """Una fotografia con il suo credito, o "" se non si puo' stampare.

    Senza credito non si stampa: pubblicare la fotografia di qualcun altro
    senza dire di chi e' su un documento venduto non e' un dettaglio
    estetico. E' la stessa regola di tutto il resto del prodotto.
    """
    if not isinstance(scatto, dict):
        return ""
    grezzi = scatto.get("png")
    credito = str(scatto.get("credito") or "").strip()
    if not grezzi or not credito:
        return ""
    if rapporto:
        grezzi = foto.ritaglia_panoramica(grezzi, rapporto) or grezzi
        # [ANGOLI MORBIDI 2026-08-18] Sui pixel, non col foglio di stile:
        # qui `border-radius` su un'immagine arrotonda in alto e taglia netto
        # in basso. Stessa scelta del documento principale, cosi' le due
        # meta' del fascicolo hanno la stessa faccia.
        grezzi = foto.angoli_arrotondati(grezzi) or grezzi
    if larghezza_max:
        grezzi = foto.normalizza_png(grezzi, larghezza_max) or grezzi
    try:
        b64 = base64.b64encode(grezzi).decode("ascii")
    except (TypeError, ValueError):
        return ""
    return (f"<img src='data:{foto.mime_immagine(grezzi)};base64,{b64}' "
            f"alt='{_esc(alt)}'>"
            f"<div class='credito'>{_esc(credito)}</div>")


# Il rapporto fra larghezza e altezza delle fotografie in banda. Tutte
# uguali, e piu' larghe che alte: tre immagini della stessa forma fanno una
# fascia, tre immagini di forme diverse fanno disordine. E il ritaglio non e'
# solo estetica — e' quello che rende l'altezza della banda PREVEDIBILE, e
# quindi la lunghezza della scheda.
#
# [ABBASSATO 2026-08-17, poi RIMISURATO — task #226/224.] Provato ad
# abbassarlo da 1.55 a 1.2 sperando di alzare la banda quando cade da sola su
# una pagina quasi vuota (pagine 13/15/17/19/21/23/25/27 del fascicolo di
# Bologna). Misurato: NESSUN effetto sulle fotografie orizzontali, che sono
# la maggioranza. Il motivo e' nel ritaglio stesso: `foto.ritaglia_panoramica`
# non alza mai il rapporto di una foto GIA' piu' panoramica di quello
# richiesto (non puo' aggiungere pixel che non esistono), quindi abbassare
# il numero qui non allunga una foto orizzontale che era gia' oltre quella
# soglia — cambia solo le foto con un rapporto nativo fra 1.2 e 1.55, una
# minoranza. Resta a 1.2 perche' non fa danno e aiuta quel caso minore, ma
# NON e' la riparazione del difetto vero.
#
# La riparazione vera e' un'altra: la banda cade sola su una pagina quasi
# vuota perche' il resto della scheda (testata + corpo) riempie quasi tutta
# la prima pagina, e non le resta spazio. Serve lo stesso metodo gia' usato
# per il bianco a fine giornata (misura la prima stampa, decide, ristampa) —
# qui pero' non ancora costruito: la scheda di ogni guida e' un documento a
# se', stampato una volta sola, senza la seconda passata che il documento
# principale ha gia'. E' il prossimo pezzo, non ancora fatto.
RAPPORTO_DELLA_BANDA = 1.2


def _banda_di_foto(scatti, alt: str = "") -> str:
    """Fino a tre fotografie in fila, larghe quanto serve. "" se non ce n'è.

    [CORRETTA 2026-08-17 — segnalazione di Lorenzo sulle pagine 15, 18, 21 e
    26 del fascicolo di Bologna: «due foto piccole e tutto lo spazio vuoto».]

    Prima la tabella aveva SEMPRE tre colonne, anche con una o due
    fotografie vere: le celle mancanti restavano vuote (`<td></td>`), e le
    fotografie presenti restavano strette a un terzo della pagina —
    esattamente la larghezza che sarebbe toccata a tre, anche quando erano
    due o una sola. Con un itinerario piccolo (5-6 luoghi illustrati in
    tutto) la fila in fondo alla scheda, che esclude il luogo di cui la
    scheda gia' parla, quasi non arriva mai a tre: due e' la norma, non
    l'eccezione.

    La riparazione e' la stessa gia' usata per la fila di chiusura giornata
    (`src/pdf_renderer._render_striscia_foto`): le colonne si dividono per
    le fotografie DAVVERO disponibili, non per un numero fisso. Con due
    fotografie le celle diventano larghe il 50% invece del 33%, e la
    fotografia — il cui ritaglio resta lo stesso, vedi `RAPPORTO_DELLA_BANDA`
    — viene di conseguenza piu' ALTA: niente margini toccati, solo meno
    colonne piu' larghe.
    """
    pezzi: list[str] = []
    for scatto in (scatti or []):
        if len(pezzi) >= 3:
            break
        pezzo = _immagine(scatto, LARGHEZZA_FOTO_DI_CONTORNO, alt=alt,
                          rapporto=RAPPORTO_DELLA_BANDA)
        if pezzo:
            pezzi.append(pezzo)
    if not pezzi:
        return ""
    larghezza = 100 // len(pezzi)
    celle = [f"<td style='width:{larghezza}%'>{pezzo}</td>" for pezzo in pezzi]
    return "<table class='guida-banda'><tr>" + "".join(celle) + "</tr></table>"


def _testa_illustrata(photo, compagne, nome: str) -> str:
    """La fascia di fotografie in cima alla scheda.

    [RIFATTA 2026-08-15 — richiesta di Lorenzo: «nelle guide turistiche
    metterei tre foto per pagina».]

    Prima c'era UNA fotografia larga quanto la pagina, alta sette centimetri.
    Adesso sono tre in fila: la prima e' il luogo di cui parla la scheda, le
    altre due sono altre tappe dello stesso viaggio. Le didascalie dicono
    sempre di che cosa si tratta, quindi nessuna puo' essere scambiata per il
    luogo — la regola di questo prodotto e' che non si inventa niente.

    La fascia e' anche piu' BASSA della fotografia sola che sostituisce, e
    questo non e' un effetto collaterale: tre centimetri e mezzo recuperati
    qui sono tre centimetri e mezzo che la scheda non deve chiedere a una
    seconda pagina.

    Con una sola fotografia si torna esattamente alla fotografia grande di
    prima. Con nessuna, niente: una scheda senza immagini e' meno bella, una
    scheda con un riquadro vuoto e' rotta.
    """
    utili = [c for c in ([photo] + list(compagne or [])) if isinstance(c, dict)]
    if len(utili) >= 3:
        return _banda_di_foto(utili, nome)
    grande = _immagine(photo, alt=nome)
    return f"<div class='foto'>{grande}</div>" if grande else ""


def build_guide_html(
    guide: dict,
    *,
    destination: str = "",
    place_card: dict | None = None,
    photo: dict | None = None,
    itinerary_url: str | None = None,
    come_arrivare: str = "",
    open_hours: dict | None = None,
    ancora_capitolo: str = "",
    ritorni=None,
    # [AGGIUNTO 2026-08-13 — task #209] I colori del posto. `None` = quelli
    # di sempre, cioe' il capitolo esattamente com'era ieri.
    tavolozza: dict | None = None,
    # [AGGIUNTO 2026-08-13 — task #217] Altre fotografie del viaggio, per la
    # fila in fondo alla scheda. Lista di `{"png", "credito"}`.
    foto_extra=None,
    # [AGGIUNTO 2026-08-17 — task #227, ultimo dei nove difetti del
    # fascicolo di Bologna: pagine 13/15/17/19/21/23/25/27, «due foto
    # piccole e tutto lo spazio vuoto».]
    #
    # Quando la fila di fotografie in fondo cade da sola su una pagina
    # quasi vuota — perche' il resto della scheda ha gia' riempito la
    # pagina prima — questa fila deve ingrandirsi per occupare quello
    # spazio, con lo stesso principio gia' usato per la fila di chiusura
    # giornata del documento principale: meno fotografie, piu' grandi.
    # Lo decide `costruisci_capitoli()`, misurando la prima stampa di
    # QUESTA guida — vedi la sonda `guida-banda-inizio` piu' sotto.
    banda_ingrandita: bool = False,
    # La sonda serve SOLO alla modalita' fascicolo (`costruisci_capitoli`):
    # e' li' che la seconda stampa la legge per decidere. Nella modalita'
    # pubblicata (`publish_guides`) la guida esce com'era prima — nessuna
    # sonda orfana in un documento pubblico che nessuno ripara mai. Falso
    # di default apposta: aggiungere una sonda va CHIESTO, non presunto.
    sonda_banda: bool = False,
) -> str:
    """L'HTML di UNA guida, completo e autonomo.

    `photo` è `{"png": bytes, "credito": str}` — la foto vera del luogo
    quando c'è; il credito è obbligatorio quando la foto arriva da Google
    Places, e infatti se manca il credito la foto NON viene stampata:
    pubblicare una foto altrui senza attribuzione su un documento venduto
    è un problema serio, non un dettaglio estetico.

    `itinerary_url` è la URL del documento principale: è il bottone «torna
    all'itinerario». Se manca, il bottone non c'è — e la guida lo dice, con
    una riga di spiegazione, invece di lasciare il cliente in un vicolo
    cieco senza capire perché.

    `ancora_capitolo` e `ritorni` servono alla modalità FASCICOLO, cioè
    quando questa guida non è un file ospitato ma un capitolo cucito dentro
    lo stesso PDF dell'itinerario (task #190-#191). In quel caso:

      - `ancora_capitolo` è il nome del punto di atterraggio stampato in
        cima, quello che il documento principale raggiunge da `#...`;
      - `ritorni` è l'elenco prodotto da `fascicolo.elenca_ritorni()` per
        QUESTA attrazione: un bottone per ogni punto da cui ci si arriva.

    Il secondo è il motivo per cui la lista non è una stringa sola. Lorenzo:
    «ogni collegamento esterno abbia un pulsante per ritornare al documento
    principale, NEL PUNTO ESATTO di dove si era arrivati originariamente».
    La stessa attrazione può comparire nel programma del Giorno 2 e sulla
    cartina del Giorno 2, e i due bottoni devono riportare in due posti
    diversi: un bottone solo, per forza di cose, ne sbaglierebbe uno.

    Quando `ritorni` c'è, il bottone verso la URL ospitata non viene
    stampato: nel fascicolo il documento principale è a due pagine di
    distanza, e mandare il cliente su internet per raggiungerlo sarebbe
    peggio in ogni situazione — soprattutto in aereo, che è esattamente il
    momento in cui questi documenti si leggono.
    """
    guide = guide if isinstance(guide, dict) else {}
    nome = str(guide.get("poi_name") or "").strip()
    titolo = str(guide.get("title") or nome).strip()
    card = place_card if isinstance(place_card, dict) else {}

    parti = [
        "<!DOCTYPE html><html lang='it'><head><meta charset='utf-8'>",
        f"<title>{_esc(titolo or 'Guida')}</title><style>{_css(tavolozza)}</style></head><body>",
        # La sonda del capitolo sta PRIMA di tutto: è il punto in cui deve
        # atterrare chi arriva dall'itinerario, e deve essere la testata —
        # non il primo paragrafo — la prima cosa che vede.
        _sonda(ancora_capitolo),
        "<div class='testata'>",
        "<div class='occhiello'>Guida turistica tascabile</div>",
        f"<h1>{_esc(titolo)}</h1>",
    ]
    sottotesto = " · ".join(x for x in (nome if nome != titolo else "", destination) if x)
    if sottotesto:
        parti.append(f"<div class='dove'>{_esc(sottotesto)}</div>")
    parti.append("</div>")

    # La foto sta subito sotto la testata: è la risposta immediata a «meno
    # testo più immagini, non deve essere noioso». Prima del testo, non
    # dopo — una foto in fondo alla pagina l'ha già persa chi si è annoiato.
    # [RIFATTA 2026-08-15 — richiesta di Lorenzo: «nelle guide turistiche
    # metterei tre foto per pagina».] Prima qui c'era UNA fotografia larga
    # quanto la pagina. Adesso la fotografia del luogo resta la grande — e'
    # di questo che parla la scheda — e accanto le stanno due immagini
    # piccole di altre tappe dello stesso viaggio: tre su questa pagina, tre
    # nella fila in fondo, che di solito cade sulla pagina dopo.
    #
    # Perche' una tabella e non tre riquadri affiancati: affiancare, con
    # questo motore di stampa, si fa solo con le tabelle. `float` e `flex`
    # li ignora in silenzio, e il risultato sarebbero tre fotografie una
    # sotto l'altra — cioe' mezza pagina di immagini invece di una banda.
    compagne = [c for c in (foto_extra or [])[:2] if isinstance(c, dict)]
    parti.append(_testa_illustrata(photo, compagne, nome or titolo))

    storia = guide.get("history_summary") or ""
    if storia:
        # [SU DUE COLONNE 2026-08-18 — Lorenzo, con quattro brochure di
        # viaggio in mano: «renderla luxury ma simile a queste».]
        #
        # Erano tutte e quattro impaginate a colonne, e non per moda: una
        # riga larga quanto un A4 e' faticosa, l'occhio si perde tornando a
        # capo. E' il motivo per cui riviste e guide sono in colonne da un
        # secolo e mezzo — la stessa ragione gia' scritta in `_due_colonne`,
        # applicata al pezzo di testo piu' lungo della scheda invece che
        # solo agli elenchi sotto.
        #
        # Con UN paragrafo solo non si divide niente: mezza colonna di
        # testo e mezza vuota sarebbe peggio di una riga larga.
        _pezzi_storia = _paragraphi_separati(storia)
        _dentro = (_due_colonne(_pezzi_storia) if len(_pezzi_storia) > 1
                   else _paragraphs(storia, "corpo"))
        parti.append(f"<div class='corpo'>{_dentro}</div>")

    # [AGGIUNTO 2026-08-13 — task #223] Il corpo della scheda si
    # raccoglie qui e si stampa su DUE COLONNE (vedi `_due_colonne`).
    corpo: list[str] = []
    corpo.append(_righe_nominate(guide.get("highlights"), "Cosa cercare, una volta dentro"))

    curiosita = [str(c).strip() for c in (guide.get("curiosita") or []) if str(c).strip()]
    if curiosita:
        # [CORRETTO 2026-08-18] Le voci finivano in `parti` mentre l'elenco
        # che le contiene finiva in `corpo`: i pallini uscivano FUORI dal
        # loro `<ul>` e fuori dalle due colonne, stampati a tutta larghezza
        # in fondo alla scheda, staccati dal titolo «Da sapere» che li
        # annunciava. Si vede benissimo sul fascicolo vero, ed e' un refuso
        # di una lettera: `parti` invece di `corpo`.
        corpo.append("<div class='sottotitolo'>Da sapere</div><ul>")
        corpo.extend(f"<li>{_esc(c)}</li>" for c in curiosita)
        corpo.append("</ul>")

    consigli = [str(t).strip() for t in (guide.get("practical_tips") or []) if str(t).strip()]
    if consigli:
        # Stesso refuso, stesso effetto: i consigli pratici uscivano dal
        # loro riquadro colorato e finivano a tutta pagina in fondo.
        corpo.append("<div class='riquadro'><strong>Consigli pratici</strong><ul>")
        corpo.extend(f"<li>{_esc(t)}</li>" for t in consigli)
        corpo.append("</ul></div>")

    errore = str(guide.get("errore_da_evitare") or "").strip()
    if errore:
        corpo.append(
            f"<div class='avviso'><strong>L'errore che fanno quasi tutti:</strong> "
            f"{_esc(errore)}</div>"
        )

    corpo.append(_righe_nominate(guide.get("dintorni"), "A due passi da qui"))

    # --- Il blocco "micro": orari, biglietti, contatti, come arrivare ----
    # È la parte che Lorenzo ha elencato per nome («orari, biglietti, info,
    # guida turistica, come arrivare») e la ragione per cui il documento
    # principale può permettersi di diventare più scarno: qui c'è tutto
    # quello che serve DAVANTI al cancello, e solo a chi ci sta andando.
    righe = [
        # [AGGIUNTO 2026-08-03 — task #180] Gli orari stanno in cima e non in
        # fondo: e' l'unica riga di questa tabella che puo' far tornare
        # indietro il cliente davanti a un portone chiuso.
        _riga_pratica("Orari di apertura", _orari_settimana(open_hours)),
        _riga_pratica("Quando visitare", _esc(guide.get("best_time_to_visit") or "")),
        _riga_pratica("Durata della visita", _esc(guide.get("estimated_visit_duration") or "")),
        _riga_pratica("Indirizzo", _esc(card.get("address") or "")),
        _riga_pratica("Telefono", _esc(card.get("phone") or "")),
    ]
    for chiave, etichetta in (
        ("tickets_link", "Biglietti e orari"),
        ("info_link", "Scheda del luogo"),
        ("menu_link", "Menù e sito"),
    ):
        voce = card.get(chiave)
        if isinstance(voce, dict) and voce.get("url"):
            righe.append(_riga_pratica(etichetta, _link(voce["url"], voce.get("label") or etichetta)))
    if come_arrivare:
        righe.append(_riga_pratica("Come arrivare", come_arrivare))
    righe = [r for r in righe if r]
    if righe:
        corpo.append("<div class='sottotitolo'>Informazioni pratiche</div>")
        corpo.append("<table class='pratico'>" + "".join(righe) + "</table>")

    if guide.get("disclaimer"):
        corpo.append(f"<div class='nota'>{_esc(guide['disclaimer'])}</div>")

    # --- I bottoni di ritorno --------------------------------------------
    # [RIFATTO 2026-08-05 — task #191] Prima ce n'era uno solo e portava
    # "all'itinerario", genericamente. Ora, in modalità fascicolo, ce n'è uno
    # per ogni punto da cui si arriva qui, e ognuno riporta esattamente lì.
    voci_ritorno = [
        v for v in (ritorni or [])
        if isinstance(v, dict) and v.get("ancora")
    ]
    parti.append(_due_colonne(corpo))

    if voci_ritorno:
        # [TENUTO INSIEME 2026-08-18 — pagina 18 del fascicolo di Bologna
        # vero: una riga grigia in cima e poi un foglio bianco intero.]
        #
        # Il titolino, i bottoni e la nota che li spiega sono UNA cosa sola.
        # Stampati come pezzi separati, il motore di stampa e' liberissimo di
        # lasciare i bottoni in fondo a una pagina e mandare la nota su
        # quella dopo — dove resta da sola, perche' dopo di lei non c'e'
        # piu' niente. Il risultato e' la pagina peggiore dell'intero
        # documento: quella che fa pensare «e' rotto».
        #
        # Il guscio e' una tabella con `page-break-inside: avoid`, l'unico
        # modo che questo motore rispetta davvero.
        blocco = ["<div class='sottotitolo'>Torna dove eri</div>"]
        for voce in voci_ritorno:
            etichetta = str(voce.get("etichetta") or "Torna all'itinerario")
            blocco.append(
                f"<div class='bottone-torna'>"
                f"<a href='{LINK_PREFIX}{_esc(str(voce['ancora']))}'>&#8617; {etichetta}</a>"
                f"</div>"
            )
        if len(voci_ritorno) > 1:
            blocco.append(
                "<div class='nota'>Questo luogo compare pi&#249; volte nel "
                "tuo programma: ogni bottone ti riporta al punto preciso da "
                "cui sei arrivato.</div>"
            )
        parti.append("<table class='keep'><tr><td>" + "".join(blocco)
                     + "</td></tr></table>")
    elif _link(itinerary_url, "Torna all'itinerario"):
        parti.append(
            "<div class='bottone-torna'>"
            + _link(itinerary_url, "Torna all'itinerario")
            + "</div>"
        )
        parti.append(
            "<div class='nota'>Il collegamento riapre il tuo itinerario "
            "completo, al capitolo del programma giorno per giorno.</div>"
        )
    else:
        parti.append(
            "<div class='nota'>Questa guida fa parte del tuo itinerario: "
            "per il programma della giornata, gli orari e gli spostamenti "
            "torna al documento principale che hai ricevuto per email.</div>"
        )

    # [AGGIUNTO 2026-08-17 — task #227] La sonda che dice se la fila di
    # fotografie in fondo sta per cadere da sola su una pagina quasi vuota.
    #
    # Stessa lezione gia' imparata (e corretta due volte) per la sonda di
    # fine giornata del documento principale: la sonda va DENTRO l'ultimo
    # elemento gia' presente, non accanto — un elemento a se' stante, anche
    # minuscolo, puo' spostare l'impaginazione di quello che segue in modi
    # imprevedibili. Qui l'ultimo elemento e' sempre un `<div>` (la nota, o
    # l'ultimo bottone di ritorno): la sonda entra prima della sua chiusura.
    #
    # [CORRETTO 2026-08-17, stesso giorno — trovato da un test gia'
    # scritto.] La prima versione la seminava SEMPRE, incondizionatamente:
    # rompeva `test_senza_fascicolo_la_guida_resta_quella_di_prima`, che
    # protegge le guide PUBBLICATE singolarmente (`publish_guides`) dal
    # portare sonde che li' nessuno ripara mai. Ora la sonda si semina solo
    # se esplicitamente chiesta — `costruisci_capitoli()` la chiede,
    # `publish_guides()` no.
    if sonda_banda and parti and parti[-1].endswith("</div>"):
        parti[-1] = parti[-1][: -len("</div>")] + _sonda("guida-banda-inizio") + "</div>"

    # [AGGIUNTO 2026-08-13 — task #217] La fila di fotografie in fondo.
    #
    # Nasce da DUE cose che si sono rivelate la stessa. Lorenzo: «vorrei che
    # incastrassi nella guida turistica alcune foto». E il misuratore
    # dell'impaginazione, alla prima esecuzione: otto pagine mezze vuote,
    # tutte le SECONDE pagine dei capitoli delle guide, ferme fra il 14% e il
    # 32% del foglio.
    #
    # Erano lo stesso difetto visto da due parti: la scheda sbordava di poco
    # e lasciava la pagina dopo quasi bianca. Riempirla di parole sarebbe
    # stato peggio del bianco; riempirla di fotografie del posto e' cio' che
    # era gia' stato chiesto.
    #
    # Servono almeno DUE fotografie: una sola in mezzo a una pagina vuota e'
    # esattamente il difetto segnalato («una sola foto centrale che non mi
    # piace»), non la sua riparazione.
    # [UNIFICATA 2026-08-15] La fila in fondo e' la stessa fascia di quella
    # in cima — stesse tre colonne, stessa forma, stessa altezza. Prima erano
    # due disegni diversi che facevano la stessa cosa in due modi, e la
    # seconda pagina della scheda ne usciva sbilanciata.
    #
    # Le prime due fotografie di contorno sono gia' in cima: ristamparle qui
    # vorrebbe dire la stessa immagine due volte nella stessa scheda, che e'
    # il difetto piu' rapido da notare sfogliando.
    # [LEGATA AL TESTO 2026-08-16 — «se la pagina inizia con una foto non
    # mettere la foto».] La fascia viaggia dentro `page-break-inside: avoid`:
    # o entra, o scende INTERA sulla pagina dopo, dove arriva da sola. Legata
    # all'ultimo pezzo di testo che la precede, o scendono insieme — e allora
    # la pagina nuova ha anche del testo — o restano dove sono.
    #
    # [ESTESA 2026-08-17 — task #227, pagine 13/15/17/19/21/23/25/27: «due
    # foto piccole e tutto lo spazio vuoto».] Quando `banda_ingrandita` e'
    # vero — deciso da `costruisci_capitoli()` misurando la prima stampa —
    # la fila usa al MASSIMO due fotografie invece di tre: colonne piu'
    # larghe, e a parita' di ritaglio, figure piu' alte. Riempie di piu' la
    # pagina isolata senza toccare un solo margine, la stessa idea gia'
    # applicata alla fila di chiusura giornata del documento principale.
    candidate_finali = (foto_extra or [])[2:5]
    if banda_ingrandita:
        candidate_finali = candidate_finali[:2]
    in_fondo = _banda_di_foto(candidate_finali)
    if in_fondo:
        coda = parti.pop() if parti else ""
        parti.append("<table class='keep'><tr><td>"
                     + coda + in_fondo + "</td></tr></table>")

    parti.append("</body></html>")

    # [AGGIUNTO 2026-08-03 - task #183] La stessa passata di impaginazione del
    # documento principale: anche qui un paragrafo non si spezza fra due
    # pagine. Le guide per attrazione sono quasi solo prosa, quindi e' il
    # documento in cui il difetto si vedeva di piu' - ed e' anche quello che
    # il cliente apre dal telefono, dove una pagina mezza vuota si nota
    # subito. La regola sta in un posto solo per tutti e due i documenti: se
    # cambia la soglia, cambia per entrambi.
    return _tieni_uniti_i_paragrafi("".join(parti))


def render_guide_pdf(html: str) -> bytes | None:
    """Da HTML a byte di PDF. `None` se la stampa non riesce, mai
    un'eccezione: una guida in meno è un peccato, un itinerario non
    consegnato è un rimborso."""
    if not isinstance(html, str) or not html.strip():
        return None
    percorso_html = percorso_pdf = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", suffix=".html", delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(html)
            percorso_html = tmp.name
        fd, percorso_pdf = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        esito = subprocess.run(
            ["wkhtmltopdf", "--quiet", "--enable-internal-links",
             percorso_html, percorso_pdf],
            capture_output=True, text=True, timeout=TIMEOUT_S,
        )
        if esito.returncode != 0:
            return None
        dati = Path(percorso_pdf).read_bytes()
        return dati or None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    finally:
        for p in (percorso_html, percorso_pdf):
            if p:
                Path(p).unlink(missing_ok=True)


def nome_file_guida(guide: dict, indice: int) -> str:
    """Il nome con cui la guida vive nella URL.

    Descrive il CONTENUTO e mai il cliente — è la stessa regola scritta in
    cima a `src/hosting.py`: nella URL non deve comparire niente che
    identifichi una persona. `guida-duomo-di-siena`, non `guida-lorenzo`.
    """
    grezzo = guide.get("poi_name") or guide.get("title") or ""
    pulito = _slug(grezzo) if grezzo else ""
    # `_slug()` può restituire vuoto (nome tutto di caratteri non latini) e
    # la lista bianca di hosting.py taglia a 64 caratteri: entrambi i casi
    # vanno chiusi qui, non scoperti da un `None` di `store()`.
    if not pulito:
        return f"guida-{indice + 1}"
    return f"guida-{pulito}"[:60]


def _altre_foto(tutte, escluso: str, giro: int) -> list:
    """Le fotografie IN PIU' del luogo di cui parla la scheda. Quasi sempre
    nessuna, ed e' giusto cosi'.

    [SVUOTATA 2026-08-16 — annullamento di una decisione mia, non correzione
    di un difetto.]

    Prima questa funzione restituiva fotografie di ALTRE tappe del viaggio,
    per riempire la scheda. Lorenzo, guardando il fascicolo vero: «le foto
    sono messe a caso senza alcun ordine (cosa c'entra il tortellino) e si
    ripetono ancora».

    Aveva ragione, e la difesa che avevo scritto — «la didascalia dice di chi
    e' la fotografia, quindi non si promette niente di falso» — e' vera e non
    basta: chi sfoglia non legge la didascalia, vede un tortellino nella
    scheda delle Due Torri e conclude che il documento mette immagini a caso.

    LA REGOLA: una fotografia sta nella pagina di cui parla, o non c'e'.

    La funzione resta al suo posto, e non e' un residuo: il giorno in cui
    Google restituira' piu' di una fotografia per luogo, le altre di QUEL
    luogo entreranno da qui senza toccare nient'altro.

    [UNITE LE DUE STRADE — 2026-08-18.] Due sessioni avevano riparato lo
    stesso difetto in due modi diversi, e la fusione tiene il meglio di
    tutti e due:

      - la REGOLA e' quella qui sopra: solo fotografie del luogo di cui
        parla la scheda. E' cio' che Lorenzo ha chiesto — «foto inerenti
        ai testi» — e nessuna rotazione di immagini altrui la soddisfa;
      - il MECCANISMO e' il loro: `png_alt`/`credito_alt`, la seconda
        fotografia dello stesso luogo raccolta da `foto.raccogli_foto`.
        Serviva a non ripetere lo stesso scatto, e serve ancora — ma
        applicato al luogo giusto invece che a un altro.

    Risultato: la scheda chiude con una SECONDA fotografia del suo stesso
    luogo, quando c'e'. Quando non c'e', non chiude con niente.
    """
    if not isinstance(tutte, dict) or not escluso:
        return []
    proprie = tutte.get(escluso)
    if not isinstance(proprie, dict):
        return []
    if not proprie.get("png") or not proprie.get("credito"):
        return []
    # La seconda fotografia dello stesso luogo, se `foto.raccogli_foto` e'
    # riuscita a prenderla: e' quella che chiude la scheda senza ripetere
    # l'immagine gia' vista in apertura.
    alt_png = proprie.get("png_alt")
    alt_credito = proprie.get("credito_alt")
    if not alt_png or not alt_credito:
        return []
    return [{"png": alt_png, "credito": alt_credito}]


# Quanto deve restare, come minimo, sopra la sonda perche' una fila di
# fotografie si consideri "caduta sola su una pagina quasi vuota".
#
# [AGGIUNTO 2026-08-17 — task #227, ultimo dei nove difetti del fascicolo di
# Bologna: pagine 13/15/17/19/21/23/25/27, «due foto piccole e tutto lo
# spazio vuoto».] Stessa soglia, stesso ragionamento di
# `src/impaginazione.QUOTA_BIANCO_GIORNATA`: se la sonda che precede la fila
# si ferma alta sulla pagina — sopra il 70% dell'altezza del foglio — vuol
# dire che quasi niente la precede su QUELLA pagina, cioe' che la fila e'
# rimasta isolata. Il numero e' piu' alto della soglia gemella (0.30 contro
# 0.70, ma sono la stessa misura guardata da parti opposte: qui si guarda
# quanto resta SOPRA la sonda, li' quanto resta SOTTO l'ultima fotografia)
# perche' qui la sonda sta appena PRIMA della fila, non alla fine della
# giornata: se la pagina fosse gia' per meta' piena la fila non sarebbe
# affatto isolata.
QUOTA_BANDA_ISOLATA = 0.70


def banda_isolata(dati: bytes, quota: float = QUOTA_BANDA_ISOLATA) -> bool:
    """La fila di fotografie in fondo a QUESTA guida e' caduta da sola su
    una pagina quasi vuota?

    [DOVE SI USA, dal 18 agosto: `publish_guides()`, cioe' le guide
    PUBBLICATE — un documento per attrazione, ospitato su Render. Non piu'
    `costruisci_capitoli()`: li' le schede scorrono dentro un unico
    documento e dopo la fila comincia subito la scheda dopo, quindi la
    pagina non resta vuota e non c'e' niente da ingrandire. La riparazione
    non e' stata buttata: e' stata spostata dove il vincolo che l'ha resa
    necessaria — un PDF per guida — esiste ancora.]

    [AGGIUNTO 2026-08-17 — task #227.] Stesso metodo di
    `impaginazione.giornate_con_bianco_finale`, applicato a un documento
    piu' piccolo: si stampa, si guarda dove e' caduta la sonda
    `guida-banda-inizio` seminata da `build_guide_html()`, si decide.

    Non serve confrontare con "la pagina dopo", come per le giornate: qui
    non c'e' nessuna pagina dopo — la fila e' l'ultima cosa che la guida
    stampa. Basta guardare quanto resta SOPRA la sonda: se e' quasi tutta
    la pagina, quella pagina era vuota prima che la fila cominciasse.

    Torna `False` — mai solleva — se le sonde non si leggono: una guida
    senza questa riparazione resta comunque una guida.
    """
    try:
        from src import impaginazione

        dove = impaginazione.posizioni(dati)
        posizione = dove.get("guida-banda-inizio")
        if not posizione:
            return False
        _pagina, altezza = posizione
        return altezza >= impaginazione.ALTEZZA_A4_PT * quota
    except Exception:
        return False


def _frammento(html: str) -> str:
    """Il CORPO di una scheda, senza il guscio del documento.

    Serve a mettere piu' schede dentro un foglio solo. Il taglio si fa sui
    marcatori veri (`<body ...>` e `</body>`) perche' `build_guide_html`
    chiude sempre con `</body></html>`: se un domani cambiasse forma, qui si
    torna la stringa intera invece di tagliare a caso — una scheda con un
    guscio di troppo si stampa lo stesso, una scheda tagliata male no.
    """
    testo = str(html or "")
    apertura = testo.find("<body")
    if apertura < 0:
        return testo
    apertura = testo.find(">", apertura)
    chiusura = testo.rfind("</body>")
    if apertura < 0 or chiusura <= apertura:
        return testo
    return testo[apertura + 1:chiusura]


def unisci_le_schede(pezzi, a_capo=()) -> str:
    """Tutte le schede in UN documento solo, cosi' che condividano le pagine.

    [RIFATTO 2026-08-18 — decisione di Lorenzo, presa sui numeri.]

    ## Il difetto che questa funzione toglie alla radice

    Misurato sul campione con nove schede cucite: **dieci pagine su
    ventisette piene fra l'8% e il 26%**. Ogni scheda era un PDF a se',
    cucito dietro l'altro, e due PDF diversi non possono condividere un
    foglio: una scheda lunga una pagina e un quarto si portava dietro
    tre quarti di pagina bianca, sempre, per costruzione.

    Nessuna regola di impaginazione poteva ripararlo — non era una scelta
    sbagliata, era l'impianto. Le riparazioni provate prima (ingrandire la
    fila di fotografie quando resta isolata, stringere la coda) coprivano
    solo i casi in cui c'era qualcosa da ingrandire o da stringere.

    ## Cosa cambia per chi legge

    Le schede scorrono una dopo l'altra come i capitoli di un libro: la
    seconda comincia dove finisce la prima, sulla stessa pagina se c'e'
    posto. Chi sfoglia non vede piu' mezze pagine bianche fra una scheda e
    l'altra.

    ## E i collegamenti?

    Restano. Ogni scheda porta con se' la sua ancora, che il documento
    principale usa per il bottone «Apri la guida»: cambia dove atterra
    (una pagina condivisa invece di una pagina propria), non se atterra.
    Dove sia finita ogni ancora non si indovina — si misura sul PDF
    stampato, con le stesse sonde di tutto il resto.

    `a_capo` sono le ancore delle schede che devono comunque cominciare su
    una pagina nuova: quelle che, misurando, erano cadute troppo in fondo al
    foglio. E' la stessa regola del documento principale — una scheda che
    comincia due righe prima della fine della pagina si legge come un errore
    di stampa — e vale per una MINORANZA di schede, non per tutte: mandarle
    a capo tutte vorrebbe dire tornare al difetto di partenza.
    """
    pezzi = [(a, h) for a, h in (pezzi or []) if h]
    if not pezzi:
        return ""
    primo = str(pezzi[0][1])
    apertura = primo.find("<body")
    if apertura >= 0:
        apertura = primo.find(">", apertura)
    guscio = primo[:apertura + 1] if apertura > 0 else "<html><body>"

    da_mandare_a_capo = {n for n in (a_capo or []) if n}
    corpo = []
    for indice, (ancora, html) in enumerate(pezzi):
        dentro = _frammento(html)
        # La prima non si manda mai a capo: e' gia' la prima pagina del
        # blocco delle schede, e un salto qui vorrebbe dire aprire il
        # blocco con un foglio bianco.
        if indice and ancora in da_mandare_a_capo:
            dentro = ("<div style='page-break-before: always'></div>" + dentro)
        corpo.append(dentro)
    return guscio + "".join(corpo) + "</body></html>"


def costruisci_capitoli(
    guides,
    ritorni_per_poi=None,
    *,
    destination: str = "",
    place_cards: dict | None = None,
    photos: dict | None = None,
    directions_by_poi: dict | None = None,
    open_hours_by_poi: dict | None = None,
) -> list[dict]:
    """Le guide come CAPITOLI da cucire, non come file da pubblicare.

    [AGGIUNTO 2026-08-05 — task #190. Richiesta di Lorenzo: «questi documenti
    seppur diversi stiano in un unico file, non so come farai ma trova il
    modo»]

    È la sorella di `publish_guides()` e fa quasi lo stesso lavoro, con una
    differenza che cambia tutto: invece di caricare il PDF su Render e
    tornare una URL, tiene i byte e li consegna a chi dovrà cucirli.

    Perché sono due funzioni e non una con un interruttore: quella pubblicata
    e quella cucita non hanno lo stesso contenuto. La versione ospitata è un
    documento pubblico raggiungibile da chiunque abbia la URL, e per questo
    non contiene niente del cliente; quella cucita vive dentro il file del
    cliente e può permettersi i bottoni «torna al Giorno 2, ore 09:30», che
    su un documento pubblico non avrebbero senso. Un interruttore dentro una
    funzione sola avrebbe fatto sembrare le due cose intercambiabili.

    Ritorna una lista di `{"poi_id", "ancora", "pdf"}` nell'ordine in cui i
    capitoli andranno cuciti. Le guide che non riescono a essere stampate
    non compaiono: per quelle il documento principale continua a stampare il
    capitolo interno di sempre. Non solleva mai.
    """
    elenco = [g for g in (guides or []) if isinstance(g, dict)]
    if not elenco:
        return []

    ritorni = ritorni_per_poi if isinstance(ritorni_per_poi, dict) else {}
    schede = place_cards if isinstance(place_cards, dict) else {}
    foto = photos if isinstance(photos, dict) else {}
    tragitti = directions_by_poi if isinstance(directions_by_poi, dict) else {}
    orari = open_hours_by_poi if isinstance(open_hours_by_poi, dict) else {}

    # Stesse fotografie del documento principale, quindi stessa tavolozza:
    # le due meta' del fascicolo ci arrivano da sole. Che ci arrivino
    # DAVVERO lo verifica `test_copertina_illustrata`, stampandole entrambe.
    from src import tavolozza as _tav

    tinte = _tav.scegli(foto if isinstance(foto, dict) else None)

    # --- 1. le schede, una per una, ma solo come TESTO ---------------------
    # Non si stampa ancora niente: si stampa una volta sola, tutte insieme,
    # ed e' il punto dell'intera modifica. Stampare qui vorrebbe dire N
    # documenti che non possono condividere una pagina.
    pezzi: list[tuple] = []
    for guide in elenco[:MAX_GUIDE]:
        poi_id = guide.get("poi_id")
        if not isinstance(poi_id, str) or not poi_id:
            continue
        ancora = fascicolo.ancora_capitolo(poi_id)
        try:
            html = build_guide_html(
                guide,
                destination=destination,
                place_card=schede.get(poi_id),
                photo=foto.get(poi_id),
                come_arrivare=str(tragitti.get(poi_id) or ""),
                open_hours=orari.get(poi_id),
                ancora_capitolo=ancora,
                ritorni=ritorni.get(poi_id),
                tavolozza=tinte,
                foto_extra=_altre_foto(foto, poi_id, len(pezzi)),
                # [SPENTA NELLA MODALITA' UNITA' — 2026-08-18] La sonda
                # serviva a scoprire se la fila di fotografie in fondo a
                # QUESTA scheda fosse caduta da sola su una pagina quasi
                # vuota, per ristamparla ingrandita. Con le schede che
                # scorrono una nell'altra il caso quasi non esiste piu':
                # dopo quella fila comincia subito la scheda successiva,
                # quindi la pagina non resta vuota. E con un documento solo
                # una sonda con lo stesso nome per ogni scheda si
                # pesterebbe i piedi da sola.
                sonda_banda=False,
            )
        except Exception:
            html = ""
        if html:
            pezzi.append((poi_id, ancora, html))

    if not pezzi:
        return []

    # --- 2. una stampa sola, tutte le schede dentro ------------------------
    blob = render_guide_pdf(unisci_le_schede([(a, h) for _p, a, h in pezzi]))
    if not blob:
        # Nessun capitolo cucito: il documento principale torna a stampare
        # le schede al suo interno, che e' il comportamento di sempre
        # quando la stampa delle guide non riesce. Meglio un fascicolo
        # senza capitoli staccati che un fascicolo con i collegamenti morti.
        return []

    # --- 3. LA SECONDA STAMPA: solo le schede cadute in fondo al foglio ----
    # Stesso metodo del documento principale (`src/impaginazione.py`): si
    # guarda dove sono atterrate le ancore, si mandano a capo SOLO quelle
    # che cominciano a due dita dal fondo — una scheda che comincia li' si
    # legge come un errore di stampa — e si ristampa.
    #
    # Solo quelle: mandarle a capo tutte vorrebbe dire tornare esattamente
    # al difetto che questa modifica toglie.
    try:
        from src import impaginazione

        a_capo = impaginazione.capitoli_da_mandare_a_capo(
            blob, [a for _p, a, _h in pezzi])
        if a_capo:
            rifatto = render_guide_pdf(
                unisci_le_schede([(a, h) for _p, a, h in pezzi], a_capo))
            if rifatto:
                blob = rifatto
    except Exception:
        pass  # una scheda impaginata meno bene e' meglio di nessuna scheda

    # --- 4. dove e' finita ogni ancora ------------------------------------
    # Il conto per costruzione non si puo' piu' fare — le schede non hanno
    # piu' una pagina propria da contare — quindi la posizione si MISURA
    # sulle sonde del PDF appena stampato. Se le sonde non si leggono, tutte
    # le ancore atterrano sulla prima pagina del blocco: un collegamento
    # impreciso e' molto meglio di un collegamento morto.
    try:
        from src import impaginazione

        dove = impaginazione.posizioni(blob)
    except Exception:
        dove = {}

    capitoli = []
    for poi_id, ancora, _html in pezzi:
        posizione = dove.get(ancora)
        capitoli.append({
            "poi_id": poi_id,
            "ancora": ancora,
            # I byte stanno su UNA voce sola: e' un documento solo. Le altre
            # voci servono a dire al documento principale quali bottoni puo'
            # stampare, e su quale pagina atterrano.
            "pdf": blob if not capitoli else b"",
            "pagina": int(posizione[0]) if posizione else 0,
        })
    return capitoli


def publish_guides(
    guides,
    *,
    consegna: str,
    destination: str = "",
    place_cards: dict | None = None,
    photos: dict | None = None,
    itinerary_url: str | None = None,
    directions_by_poi: dict | None = None,
    open_hours_by_poi: dict | None = None,
) -> dict:
    """Pubblica una guida per attrazione e ritorna `{poi_id: url}`.

    Ritorna un dizionario VUOTO — non solleva, non stampa niente — quando
    l'ospitalità non è configurata. È il caso normale finché
    `PUBLIC_BASE_URL` non è impostata su Render, e in quel caso il prodotto
    resta esattamente quello di ieri: un unico PDF con le guide dentro.

    Le attrazioni che non riescono a essere pubblicate semplicemente non
    compaiono nel risultato, e per quelle il documento principale continua
    a stampare il capitolo interno. Non è una degradazione teorica: la
    stampa di una guida può fallire per un timeout, e il cliente non deve
    accorgersene.
    """
    elenco = [g for g in (guides or []) if isinstance(g, dict)]
    if not elenco or not hosting.is_configured():
        return {}

    schede = place_cards if isinstance(place_cards, dict) else {}
    foto = photos if isinstance(photos, dict) else {}
    tragitti = directions_by_poi if isinstance(directions_by_poi, dict) else {}
    orari = open_hours_by_poi if isinstance(open_hours_by_poi, dict) else {}

    urls: dict = {}
    nomi_usati: set = set()
    for indice, guide in enumerate(elenco[:MAX_GUIDE]):
        poi_id = guide.get("poi_id")
        if not isinstance(poi_id, str) or not poi_id:
            continue
        nome = nome_file_guida(guide, indice)
        # Due attrazioni con lo stesso nome (succede: due chiese omonime)
        # si sovrascriverebbero a vicenda in silenzio, e il cliente
        # troverebbe la guida sbagliata dietro il link giusto.
        if nome in nomi_usati:
            nome = f"{nome}-{indice + 1}"[:60]
        nomi_usati.add(nome)

        def _stampa(**extra):
            return render_guide_pdf(build_guide_html(
                guide,
                destination=destination,
                place_card=schede.get(poi_id),
                photo=foto.get(poi_id),
                itinerary_url=itinerary_url,
                come_arrivare=str(tragitti.get(poi_id) or ""),
                open_hours=orari.get(poi_id),
                **extra,
            ))

        blob = _stampa(sonda_banda=True)
        if not blob:
            continue

        # [SPOSTATA QUI 2026-08-18 — non e' una riparazione nuova, e' quella
        # del 17 agosto rimessa dove serve ancora.]
        #
        # La seconda stampa con la fila di fotografie ingrandita nasceva per
        # i capitoli cuciti. Da oggi i capitoli scorrono dentro un documento
        # solo (`unisci_le_schede`) e quel problema li' non esiste piu':
        # dopo la fila comincia subito la scheda successiva.
        #
        # Qui invece il vincolo e' rimasto identico — una guida pubblicata E'
        # un documento a se', e la sua fila di fotografie puo' ancora cadere
        # da sola su una pagina quasi vuota. Buttare la riparazione perche'
        # e' cambiato l'altro documento sarebbe stato uno spreco.
        if banda_isolata(blob):
            ingrandito = _stampa(sonda_banda=True, banda_ingrandita=True)
            if ingrandito:
                blob = ingrandito
        url = hosting.store(consegna, nome, blob)
        if url:
            urls[poi_id] = url
    return urls
