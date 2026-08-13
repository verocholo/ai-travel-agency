"""Quali file, in produzione, non sono quelli che ho in mano (task #208).

PERCHE' QUESTO FILE ESISTE

13 agosto 2026. La pagina `/prova-collegamenti`, appena accesa, ha risposto:

    {"errore": "TypeError: cuci() got an unexpected keyword argument 'ancore'"}

Cioe': in produzione `src/pdf_renderer.py` era quello nuovo e chiamava
`fascicolo.cuci(..., ancore=...)`, ma `src/fascicolo.py` era rimasto quello
vecchio, che quel parametro non lo conosce. Il servizio rispondeva
normalmente a tutto il resto; sarebbe morto **solo** al momento di cucire il
fascicolo, cioe' dopo dodici minuti di generazione gia' pagata.

## Il difetto vero, che non e' il file mancante

Il file dimenticato e' l'incidente. Il difetto e' che **non c'era modo di
sapere quali file in produzione fossero vecchi.**

Il codice arriva qui a mano, un caricamento alla volta, da un telefono. Con
cinquantacinque moduli e un elenco scritto a mano da me a ogni giro, prima o
poi ne salta uno — ed e' successo. Quando succede, non se ne accorge nessuno:
i moduli disallineati non danno nessun errore finche' non si incontrano, e si
incontrano nel punto piu' caro possibile.

Fino a oggi l'unica risposta era «ricarica tutto», che da telefono e' mezz'ora
e che sposta il problema invece di risolverlo: alla decima volta si salta di
nuovo un file.

## Cosa fa questa pagina

Dice l'impronta di ogni file che compone il servizio: un numero corto,
calcolato dal suo contenuto. Due file identici hanno la stessa impronta, due
file diversi no — e non c'e' modo di sbagliarsi.

Confrontandola con quella dei file che ho in mano, si sa in due secondi
**esattamente quali ricaricare**, e nessun altro. Niente elenchi scritti a
mano, niente «mi pare di averlo mandato».

## Perche' si puo' lasciare pubblica

Un'impronta non si puo' riaprire: e' un numero ricavato dal contenuto, non il
contenuto. Non dice cosa c'e' scritto dentro un file, dice solo se e' uguale o
diverso da un altro. Non escono nomi di persone, indirizzi, chiavi, e nemmeno
una riga di codice.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

# La radice del progetto: questo file sta in `src/`, quindi si sale di uno.
RADICE = Path(__file__).resolve().parent.parent

# I file che compongono il servizio. Non tutto il repository: le prove non
# girano in produzione e i documenti non cambiano il comportamento di niente.
# Qui c'e' cio' che, se e' vecchio, produce un guasto.
FILE_DI_RADICE = ("service.py", "main.py", "requirements.txt",
                  "Dockerfile", "Procfile", "scripts_sample_pdf.py")

# Lunghezza dell'impronta. Dodici cifre esadecimali bastano largamente a
# distinguere due versioni di uno stesso file, e stanno su una riga di
# telefono senza andare a capo — cosa che conta davvero, perche' questa
# pagina si legge da li'.
CIFRE = 12


def _impronta(percorso: Path) -> str:
    """Il numero che identifica il contenuto di un file.

    Si legge in binario e NON si normalizzano gli a-capo di proposito: un
    file arrivato con gli a-capo di Windows e' un file diverso, e ci sono
    modi in cui questo cambia il comportamento (un `.sh`, un `Procfile`).
    Meglio una differenza segnalata in piu' che una vera taciuta.
    """
    return hashlib.sha256(percorso.read_bytes()).hexdigest()[:CIFRE]


def impronte() -> dict:
    """Ogni file del servizio con la sua impronta, in ordine alfabetico."""
    trovate: dict[str, str] = {}
    for percorso in sorted((RADICE / "src").glob("*.py")):
        trovate[f"src/{percorso.name}"] = _impronta(percorso)
    for nome in FILE_DI_RADICE:
        percorso = RADICE / nome
        if percorso.exists():
            trovate[nome] = _impronta(percorso)
    return trovate


def confronta(attese: dict) -> dict:
    """Che cosa non torna, detto in italiano e senza far contare a nessuno.

    `attese` sono le impronte dei file che ho in mano io. Il risultato e'
    l'elenco dei file da ricaricare — e SOLO quelli.

    La distinzione fra «diverso» e «mancante» non e' un dettaglio: un file
    diverso si ricarica sopra, uno mancante va creato, e da telefono sono due
    gesti diversi. Un elenco unico costringerebbe a scoprirlo file per file.
    """
    qui = impronte()
    diversi = sorted(n for n, v in attese.items() if n in qui and qui[n] != v)
    mancanti = sorted(n for n in attese if n not in qui)
    in_piu = sorted(n for n in qui if n not in attese)
    return {
        "da_ricaricare": diversi,
        "mancanti": mancanti,
        "non_previsti": in_piu,
        "tutto_allineato": not diversi and not mancanti,
    }
