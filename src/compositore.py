"""Pagine sempre diverse, mai brutte (task #213).

PERCHE' QUESTO FILE ESISTE

Lorenzo, 13 agosto 2026: «non bastano 3 layout devi essere tu in grado di
diversificare ogni volta».

Ha ragione, e la differenza fra le due cose e' architetturale, non di
quantita'. Tre layout scritti a mano restano tre: al quarto giorno di viaggio
il cliente rivede la pagina del primo. Anche trenta layout scritti a mano
resterebbero trenta, e costerebbero trenta volte la fatica di uno.

## Come si ottiene la varieta' vera

Non disegnando piu' pagine: disegnando i **pezzi** e le **regole** con cui si
montano.

- **IMPIANTI** — come e' divisa la pagina.
- **ORNAMENTI** — cosa la caratterizza.
- **REGOLE** — quali combinazioni sono vietate.

Sette impianti per sei ornamenti, con i vincoli, fanno centinaia di pagine
distinte, tutte fatte di pezzi gia' guardati uno per uno. **Il numero di
pagine possibili cresce moltiplicando; la fatica di disegnarle cresce
sommando.** E' tutto qui.

## Perche' non si tira a sorte

La scelta esce da un numero ricavato dal viaggio stesso, non da `random`.
Quindi due giornate dello stesso viaggio prendono impianti diversi, due viaggi
diversi prendono sequenze diverse, e **lo stesso viaggio rigenerato da' lo
stesso identico documento**.

L'ultimo punto non e' un vezzo: un documento che cambia a ogni esecuzione e'
impossibile da collaudare, e un difetto che compare una volta su sei non si
ripara mai perche' nessuno riesce a riprodurlo. In questo progetto la
ripetibilita' e' gia' costata giorni una volta — la differenza fra il motore
di stampa di sviluppo e quello di produzione — e non si rinuncia a cuor
leggero.

## Il vero problema di un sistema cosi'

Con centinaia di combinazioni **non le si puo' guardare tutte**. Quindi la
qualita' non puo' dipendere dall'averle viste: deve dipendere dalle regole.
Per questo gli ornamenti sono pochi, i vincoli sono scritti qui in chiaro, e
le prove verificano le PROPRIETA' (mai due pagine gemelle di fila, mai piu' di
due ornamenti, mai un impianto senza le foto che chiede) invece di elencare i
casi buoni.

## Cosa NON sta qui

Il disegno delle pagine — cioe' l'HTML. Qui si decide **cosa** montare, non
**come** stamparlo: questo modulo non conosce il CSS, non produce HTML e non
sa niente di wkhtmltopdf. Serve a poterlo provare tutto senza stampare niente,
che e' la ragione per cui esiste separato.
"""

from __future__ import annotations

import hashlib

# --------------------------------------------------------------------------
# GLI IMPIANTI: come e' divisa la pagina.
#
# `foto` dice quante fotografie servono perche' l'impianto abbia senso — non
# quante ne stara' a guardare: un impianto costruito attorno a un mosaico di
# tre immagini, con una sola, e' una pagina sbagliata, non una piu' povera.
# --------------------------------------------------------------------------
IMPIANTI = (
    {"nome": "eroe-alto", "foto": 1,
     "descrizione": "fotografia a tutta larghezza in testa, titolo dentro l'immagine"},
    {"nome": "colonna-sinistra", "foto": 1,
     "descrizione": "colonna stretta a sinistra col numero, contenuto a destra"},
    {"nome": "colonna-destra", "foto": 1,
     "descrizione": "specchiata: contenuto a sinistra, colonna stretta a destra"},
    {"nome": "eroe-laterale", "foto": 1,
     "descrizione": "fotografia alta di lato, che esce dal margine"},
    {"nome": "mosaico-alto", "foto": 3,
     "descrizione": "tre fotografie in fila in cima, poi il programma"},
    {"nome": "banda-media", "foto": 1,
     "descrizione": "il programma si apre, una banda fotografica lo taglia a meta'"},
    {"nome": "numero-gigante", "foto": 0,
     "descrizione": "nessuna fotografia disponibile: comanda la tipografia"},
)

# Gli ornamenti: cosa caratterizza la pagina oltre alla sua ossatura.
ORNAMENTI = ("bollo", "nastro", "capolettera", "tonda", "fascia-dati", "citazione")

# Al massimo due per pagina. Tre fanno volantino, e questo documento si vende
# a 4,90: deve sembrare un prodotto, non una promozione.
MASSIMO_ORNAMENTI = 2

# Le coppie vietate. Sono le uniche regole che impediscono al sistema di
# produrre una pagina brutta, e vanno lette come tali: con centinaia di
# combinazioni possibili, quello che non e' vietato qui prima o poi esce.
INCOMPATIBILI = (
    {"capolettera", "bollo"},   # due numeroni giganti si contendono l'occhio
    {"nastro", "citazione"},    # due blocchi pieni attaccati, nessuno dei due vince
    {"tonda", "fascia-dati"},   # su una colonna stretta non ci stanno insieme
)


def numero_stabile(*pezzi) -> int:
    """Un numero ricavato dagli ingressi, non tirato a sorte.

    Lo stesso ingresso da' sempre la stessa uscita; ingressi vicini
    ("Siena|1" e "Siena|2") danno uscite lontane, che e' cio' che serve
    perche' due giornate consecutive non si somiglino.
    """
    grezzo = "|".join(str(p) for p in pezzi).encode("utf-8")
    return int.from_bytes(hashlib.sha256(grezzo).digest()[:6], "big")


def _ornamenti(dado: int, quanti: int, foto_disponibili: int, giro: int) -> list:
    scelti: list[str] = []
    for passo in range(len(ORNAMENTI)):
        candidato = ORNAMENTI[((dado >> 16) + giro + passo * 3) % len(ORNAMENTI)]
        if candidato in scelti:
            continue
        if any(vietata <= set(scelti + [candidato]) for vietata in INCOMPATIBILI):
            continue
        # La fotografia tonda e' un ornamento IN PIU', non l'unica immagine
        # della pagina: con una sola fotografia disponibile si prenderebbe
        # quella dell'impianto e la pagina resterebbe senza la sua apertura.
        if candidato == "tonda" and foto_disponibili < 2:
            continue
        scelti.append(candidato)
        if len(scelti) == quanti:
            break
    return scelti


def componi(chiave: str, indice: int, foto_disponibili: int,
            precedente: dict | None = None) -> dict:
    """La ricetta di UNA pagina: quale impianto, quali ornamenti.

    `chiave` e' qualcosa che identifica il viaggio (la destinazione va bene) e
    `indice` la posizione della pagina. Insieme fanno il numero che decide
    tutto — quindi due viaggi diversi non prendono la stessa sequenza, e lo
    stesso viaggio rigenerato prende sempre la sua.

    `precedente` e' la ricetta della pagina prima, e serve a non ripetersi.
    """
    dado = numero_stabile(chiave, indice)

    # `numero-gigante` non chiede fotografie, quindi senza questo taglio
    # risulterebbe sempre fra i possibili e uscirebbe anche nelle giornate che
    # le foto ce l'hanno: una pagina spoglia al posto di una illustrata, per
    # niente. E' il RIPIEGO delle pagine senza immagini, ed e' l'unico lavoro
    # per cui e' stato disegnato.
    if foto_disponibili >= 1:
        possibili = [i for i in IMPIANTI if 1 <= i["foto"] <= foto_disponibili]
    else:
        possibili = [i for i in IMPIANTI if i["foto"] == 0]

    nome_precedente = (precedente or {}).get("impianto", {}).get("nome")
    diversi = [i for i in possibili if i["nome"] != nome_precedente] or possibili
    impianto = diversi[dado % len(diversi)]

    quanti = 1 + ((dado >> 8) % MASSIMO_ORNAMENTI)
    scelti = _ornamenti(dado, quanti, foto_disponibili, 0)

    # [DIFETTO VISTO SUI PROVINI, 2026-08-13.] Quando una giornata non ha
    # fotografie resta un impianto solo, e la regola «mai due volte di fila»
    # non ha piu' niente fra cui scegliere: cede in silenzio. Sui primi dodici
    # provini le pagine 4 e 5 erano IDENTICHE, ornamenti compresi.
    #
    # Non si e' visto ragionando: si e' visto stampandone dodici di fila e
    # guardandole. Se l'ossatura e' costretta a ripetersi, cambiano almeno gli
    # ornamenti — due pagine con la stessa ossatura ma decorate in modo
    # diverso non si leggono come un doppione.
    if nome_precedente and impianto["nome"] == nome_precedente:
        vecchi = tuple((precedente or {}).get("ornamenti") or ())
        for giro in range(1, len(ORNAMENTI) + 1):
            alternativi = _ornamenti(dado, quanti, foto_disponibili, giro)
            if tuple(alternativi) != vecchi:
                scelti = alternativi
                break

    return {"impianto": impianto, "ornamenti": scelti}


# --------------------------------------------------------------------------
# LE TESTATE dei capitoli.
#
# Le pagine di consultazione (costi, vademecum, prima di partire, selezione)
# hanno un mestiere diverso da quelle di racconto: il cliente confronta i
# numeri col proprio budget e spunta la valigia la sera prima. Li' un impianto
# spettacolare non aggiunge, TOGLIE.
#
# Ma «piu' calme» non vuol dire «tutte uguali» — e' la correzione di Lorenzo:
# «aggiungiamo un po di dinamismo anche li, tutto deve essere accattivante».
# Quindi cambia l'APERTURA, mentre la tabella sotto resta ferma e leggibile.
# Cambia il ritmo, non il vestito.
# --------------------------------------------------------------------------
TESTATE = ("fascia", "laterale", "blocco", "numero")

# L'apertura piu' forte, e quella a cui si ripiega quando la pagina prima
# aveva gia' quella: sono le due che reggono un capitolo importante.
TESTATA_FORTE = "fascia"
TESTATA_FORTE_ALTERNATIVA = "blocco"


def testata(chiave: str, capitolo: str, precedente: str | None = None,
            forte: bool = False) -> str:
    """Come si apre un capitolo. Mai due volte di fila nello stesso modo.

    `forte=True` per i capitoli di racconto, che vogliono l'apertura piu'
    decisa. [DIFETTO VISTO SUI PROVINI, 2026-08-13.] Nemmeno loro pero'
    possono averla se il capitolo prima aveva gia' quella: due testate gemelle
    attaccate si vedono sfogliando, ed e' proprio il difetto che questo
    sistema esiste per evitare.
    """
    if forte:
        return (TESTATA_FORTE_ALTERNATIVA if precedente == TESTATA_FORTE
                else TESTATA_FORTE)
    possibili = [m for m in TESTATE if m != precedente] or list(TESTATE)
    return possibili[numero_stabile(chiave, capitolo) % len(possibili)]


# --------------------------------------------------------------------------
# LE FOTOGRAFIE DI OGNI GIORNATA
# --------------------------------------------------------------------------
def foto_della_giornata(proprie, riserva_viaggio, riserva_destinazione,
                        indice: int, quante: int = 3) -> tuple[list, str]:
    """Le fotografie di UNA giornata, e da dove arrivano.

    [Richiesta di Lorenzo, 13 agosto 2026: «ogni giornata deve avere le
    foto».] Aveva ragione: la giornata spoglia era l'unica pagina brutta del
    mazzo, e usciva per un motivo che al cliente non interessa — che per
    quelle tappe Google non aveva restituito niente.

    Ma la garanzia non si dichiara, si costruisce, e va costruita **senza dire
    una cosa falsa**. La regola di questo prodotto e' che non si inventa
    niente: quindi non si mette una fotografia generica facendola passare per
    la tappa di quel giorno. Si scende per gradi, e ogni gradino resta vero
    perche' la didascalia dice sempre CHE COSA si sta guardando:

      1. le fotografie delle tappe di quella giornata;
      2. quelle di altre tappe dello stesso viaggio — stessa citta', luogo
         dichiarato nella didascalia, nessuno ci legge una promessa;
      3. una fotografia della destinazione in se'.

    Resta scoperto un solo caso, ed e' dichiarato: un viaggio con ZERO
    immagini. Succede se manca la chiave di Google o se la rete cade in
    generazione — cioe' un guasto di configurazione, non una giornata
    sfortunata. Li' la pagina deve reggere lo stesso: un fascicolo che non
    parte e' peggio di uno senza fotografie.

    Torna anche la PROVENIENZA, e non e' un di piu': chi stampa deve poter
    scrivere una didascalia onesta, e chi legge una diagnosi deve poter
    vedere quante giornate hanno dovuto prendere in prestito.
    """
    if proprie:
        return list(proprie)[:quante], "proprie"
    if riserva_viaggio:
        # Si ruota sull'indice della giornata invece di prendere sempre la
        # prima: altrimenti tutte le giornate scoperte dello stesso viaggio
        # mostrerebbero la stessa identica immagine, che si nota subito.
        riserva = list(riserva_viaggio)
        taglio = (max(1, indice) - 1) % len(riserva)
        return (riserva[taglio:] + riserva[:taglio])[:quante], "dal viaggio"
    if riserva_destinazione:
        return [riserva_destinazione], "della destinazione"
    return [], "nessuna"


# --------------------------------------------------------------------------
# LE APERTURE DI GIORNATA
#
# [AGGIUNTO 2026-08-13 — primo pezzo del compositore che entra davvero nel
# documento.] Sono un sottoinsieme degli impianti: quelli che si IMPILANO,
# cioe' che non ridisegnano la pagina in colonne.
#
# La scelta e' voluta e va spiegata, perche' sembra una rinuncia e non lo e'.
# Gli impianti a colonne cambiano la struttura dell'intera giornata — titolo,
# cartina, programma, legenda — e quella struttura oggi regge sette controlli
# di impaginazione, fra cui quello che impedisce a una pagina di restare mezza
# vuota. Cambiarla tutta in una volta vorrebbe dire rimettere in gioco sette
# garanzie insieme, e questa settimana ha gia' mostrato cosa succede: due
# volte una singola immagine in piu' ha fatto sfondare una pagina.
#
# Le aperture impilate danno la varieta' visibile — nessuna giornata uguale
# alla precedente — al prezzo di UN pezzo di HTML che cambia, nello stesso
# punto in cui prima ce n'era uno solo. Le colonne arrivano dopo, quando
# questa parte e' in produzione e collaudata.
# --------------------------------------------------------------------------
APERTURE = (
    {"nome": "foto-sola", "foto": 1,
     "descrizione": "una fotografia centrata, com'era prima"},
    {"nome": "banda", "foto": 1,
     "descrizione": "fotografia panoramica a tutta larghezza, fino al bordo"},
    {"nome": "mosaico", "foto": 3,
     "descrizione": "tre fotografie in fila"},
    # [AGGIUNTE 2026-08-15 — task #219.] Le prime due aperture a COLONNE che
    # entrano nel documento venduto. Sono la meta' prudente degli impianti a
    # colonne: dividono in colonne l'APERTURA, non la giornata. Il titolo, la
    # cartina, il programma e la legenda restano impilati esattamente come
    # prima, e con loro i sette controlli di impaginazione che li difendono.
    #
    # E' la differenza fra aggiungere una pagina nuova e rifare quella che
    # gia' regge il documento. La seconda meta' — il programma affiancato
    # alla cartina — resta fuori di proposito: non e' che non si sappia fare,
    # e' che ridisegna il pezzo che tiene in piedi tutto il resto.
    {"nome": "eroe-laterale", "foto": 2,
     "descrizione": "fotografia grande a sinistra, una piccola accanto"},
    {"nome": "numero-gigante", "foto": 1,
     "descrizione": "il numero del giorno in grande, la fotografia accanto"},
)


def scegli_apertura(chiave: str, indice: int, foto_disponibili: int,
                    precedente: str | None = None) -> str:
    """Come si apre una giornata. Mai due volte di fila nello stesso modo.

    Torna "" quando non c'e' nemmeno una fotografia: in quel caso la giornata
    si apre come si apriva prima, col solo titolo. E' l'unico caso, ed e'
    dichiarato — succede se manca la chiave di Google, cioe' un guasto di
    configurazione, non una giornata sfortunata.
    """
    possibili = [a for a in APERTURE if a["foto"] <= foto_disponibili
                 and a["foto"] >= 1]
    if not possibili:
        return ""
    diverse = [a for a in possibili if a["nome"] != precedente] or possibili
    return diverse[numero_stabile(chiave, "apertura", indice) % len(diverse)]["nome"]
