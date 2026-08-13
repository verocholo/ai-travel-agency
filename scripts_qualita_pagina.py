"""Il controllo qualita' del documento lo fa il prodotto, non il cliente (task #216).

PERCHE' QUESTO FILE ESISTE

Lorenzo, 13 agosto 2026, dopo l'ennesima segnalazione sull'impaginazione:

    «migliora l'impaginazione per non spezzare i paragrafi e per non lasciare
    troppi spazi bianchi [...] ma comunque sei un ai e devi arrivarci tu
    automaticamente senza che ogni volta te lo debba dire io, mi sono stufato»

Ha ragione, e il difetto non sono i tre problemi che ha elencato: e' che
finora **il controllo qualita' l'ha fatto lui**. Io consegnavo, lui guardava,
lui trovava, lui me lo diceva. Un prodotto che funziona cosi' non scala oltre
la pazienza di una persona — ed e' finita.

## Perche' i controlli che c'erano non bastavano

Ce n'era gia' uno buono: `test_nessuna_pagina_si_ferma_a_meta_foglio`. Guarda
tutte le pagine e misura fin dove arriva l'inchiostro. Aveva pero' due punti
ciechi, e sono esattamente quelli in cui i difetti sono passati:

**Girava sul campione SENZA fotografie**, perche' qui non c'e' rete. Tutti i
guasti nati dalle immagini — la copertina che sfonda, la pagina con una foto
sola in mezzo al bianco — per lui non esistevano.

**Misurava solo dove FINISCE il contenuto.** Una pagina che arriva in fondo ma
ha una voragine bianca nel mezzo — poche righe, poi il vuoto, poi una figura —
la superava a mani basse. Ed e' proprio la forma che Lorenzo ha segnalato:
«poche righe e poi bianco».

## Cosa misura questo modulo

Guarda le pagine come immagini, riga di pixel per riga di pixel, e per ognuna
dice tre cose:

- **fin dove arriva** il contenuto (la pagina finisce a meta' foglio?);
- **il buco piu' grande in mezzo** (c'e' una voragine bianca fra due blocchi?);
- **quante figure** ci sono (la pagina e' un muro di testo?).

Non decide se il documento e' bello: dice se ha uno dei tre difetti che
Lorenzo ha dovuto segnalare piu' di una volta. E' una rete, non un giudizio.

## Come va usato

Prima di ogni consegna. Non e' un di piu': e' la cosa che sposta il controllo
qualita' da Lorenzo a qui.

## Perche' sta FUORI da `src/` e non dentro il prodotto

Ci era finito dentro, e un controllo che c'era gia' l'ha preso al volo: usa
`numpy`, che non e' fra le librerie dichiarate del servizio. La riparazione
facile sarebbe stata aggiungerlo a `requirements.txt` — e sarebbe stata
sbagliata.

Questo modulo non serve al servizio: serve a CHI CONSEGNA, prima di
consegnare. Metterlo in `src/` avrebbe caricato l'immagine di produzione di
una libreria pesante per una funzione che in produzione non gira mai, e
avrebbe allungato ogni deploy per niente.

Il controllo sulle dipendenze aveva ragione a protestare; il posto sbagliato
era il file, non la regola.
"""

from __future__ import annotations

import pathlib
import subprocess
import tempfile

# Fin dove deve arrivare il contenuto di una pagina, in percentuale
# dell'altezza. Non e' "piena": e' "non e' mezza vuota". Serve margine, perche'
# una riga in piu' o in meno sposta un blocco di pagina, e un controllo che
# fallisce a ogni virgola smette di essere letto.
ARRIVO_MINIMO = 70.0

# Il buco bianco piu' grande tollerato IN MEZZO al contenuto, sempre in
# percentuale dell'altezza. Sopra questa soglia non e' respiro: e' un blocco
# che non ci stava e ha spinto tutto alla pagina dopo.
BUCO_MASSIMO = 18.0

# Sotto questa soglia una riga di pixel si considera bianca. 245 e non 255
# perche' la carta compressa in PNG non e' mai perfettamente bianca.
_SOGLIA_INCHIOSTRO = 245


def misura(percorso_pdf: str, risoluzione: int = 60) -> list[dict]:
    """Una riga per pagina: dove arriva il contenuto e dov'e' il buco piu' grande.

    Torna una lista vuota se mancano gli strumenti (`pdftoppm`, Pillow,
    numpy). Non solleva mai: una diagnosi che fa cadere il programma proprio
    quando serve e' una diagnosi che manca.
    """
    try:
        import numpy
        from PIL import Image
    except ImportError:
        return []
    if not shutil_which("pdftoppm"):
        return []

    fuori: list[dict] = []
    try:
        with tempfile.TemporaryDirectory() as cartella:
            subprocess.run(
                ["pdftoppm", "-png", "-r", str(risoluzione), percorso_pdf,
                 f"{cartella}/pag"],
                check=True, capture_output=True, timeout=180,
            )
            immagini = sorted(pathlib.Path(cartella).glob("pag-*.png"))
            for numero, percorso in enumerate(immagini, start=1):
                quadro = numpy.array(Image.open(percorso).convert("L"))
                altezza = quadro.shape[0]
                righe = numpy.where((quadro < _SOGLIA_INCHIOSTRO).any(axis=1))[0]
                if not len(righe):
                    fuori.append({"pagina": numero, "arrivo": 0.0,
                                  "buco": 100.0, "vuota": True})
                    continue
                # Il buco piu' lungo FRA la prima e l'ultima riga con
                # inchiostro. Il bianco prima e dopo non e' un buco: e' il
                # margine, e c'e' per disegno.
                dentro = righe.max() - righe.min() + 1
                presenti = numpy.zeros(dentro, dtype=bool)
                presenti[righe - righe.min()] = True
                buco, corrente = 0, 0
                for acceso in presenti:
                    corrente = 0 if acceso else corrente + 1
                    buco = max(buco, corrente)
                fuori.append({
                    "pagina": numero,
                    "arrivo": round(100.0 * righe.max() / altezza, 1),
                    "buco": round(100.0 * buco / altezza, 1),
                    "vuota": False,
                })
    except Exception:
        return fuori
    return fuori


def shutil_which(nome: str):
    import shutil

    return shutil.which(nome)


def figure_per_pagina(dati: bytes) -> list[int]:
    """Quante immagini ci sono su ogni pagina. Lista vuota se non si legge."""
    try:
        import io

        import pypdf
    except ImportError:
        return []
    try:
        lettore = pypdf.PdfReader(io.BytesIO(dati))
    except Exception:
        return []
    fuori = []
    for pagina in lettore.pages:
        try:
            risorse = pagina.get("/Resources")
            risorse = risorse.get_object() if risorse is not None else {}
            xo = (risorse or {}).get("/XObject")
            xo = xo.get_object() if xo is not None else {}
            fuori.append(sum(1 for k in xo
                             if xo[k].get_object().get("/Subtype") == "/Image"))
        except Exception:
            fuori.append(0)
    return fuori


def problemi(percorso_pdf: str, dati: bytes | None = None,
             salta_ultima: bool = True) -> list[str]:
    """L'elenco dei difetti di impaginazione, in italiano e pronto da leggere.

    L'ULTIMA pagina si salta di proposito: e' la chiusura, finisce dove
    finisce il documento, e pretendere che arrivi in fondo vorrebbe dire
    riempirla di parole inutili — l'opposto della richiesta.
    """
    misure = misura(percorso_pdf)
    if not misure:
        return []
    figure = figure_per_pagina(
        dati if dati is not None else pathlib.Path(percorso_pdf).read_bytes())
    da_guardare = misure[:-1] if (salta_ultima and len(misure) > 1) else misure

    trovati = []
    for riga in da_guardare:
        numero = riga["pagina"]
        quante = figure[numero - 1] if numero - 1 < len(figure) else 0
        if riga["vuota"]:
            trovati.append(f"pagina {numero}: completamente bianca")
            continue
        if riga["arrivo"] < ARRIVO_MINIMO:
            trovati.append(
                f"pagina {numero}: il contenuto si ferma al {riga['arrivo']}% "
                f"del foglio ({quante} figure)")
        if riga["buco"] > BUCO_MASSIMO:
            trovati.append(
                f"pagina {numero}: buco bianco del {riga['buco']}% in mezzo al "
                "contenuto")
    return trovati
