"""L'identità visiva del prodotto, in un posto solo — src/identita.py.

[NUOVO 2026-08-05 — task #194. Richiesta di Lorenzo: «migliora in maniera
professionale, accattivante e definitiva il design e lo stile di tutto il pdf,
deve essere facilmente riconoscibile, e si deve distinguere dal resto del
mercato per la sua qualità grafica», e sua scelta esplicita fra le tre
proposte: «Progettala tu, stile "editoriale di lusso"».]

## Che cosa vuol dire «editoriale di lusso», in pratica

Il riferimento non è un sito di viaggi: sono le guide di città di Louis
Vuitton e le riviste tipo Monocle. Quel modo di fare le pagine si riconosce
da cinque cose, e sono tutte scelte di sottrazione:

  1. **Bianco**. Il fondo è carta, e il vuoto è un elemento del progetto, non
     spazio sprecato. Un documento che riempie ogni centimetro sembra un
     volantino;
  2. **Poco colore**. Due colori e mezzo in tutto il documento: l'inchiostro,
     l'oro per accento, il grigio per il secondario. I colori a semaforo
     esistono solo dove significano qualcosa (una scadenza);
  3. **Grazie per i titoli**. Il carattere con le grazie è quello dei libri:
     dice «questo si legge», non «questo si consuma». Il senza grazie resta
     per le tabelle e i dati, dove serve chiarezza e non voce;
  4. **Maiuscoletto spaziato per le etichette**. Le sopralinee («ITINERARIO
     SU MISURA», «GUIDA TURISTICA») in maiuscolo, piccole, con le lettere
     distanziate. È il segnale più economico di cura che esista in tipografia;
  5. **Filetti sottili, mai riquadri pesanti**. Una linea da un pixel al
     posto di un bordo: separa senza gridare.

## Perché sta in un modulo e non nei due fogli di stile

Perché i documenti sono diventati tre — l'itinerario, i capitoli staccati e
il foglio di calcolo — e un'identità che vive in tre posti smette di essere
un'identità al primo colore cambiato in due su tre. Qui i valori si scrivono
una volta; chi disegna li importa.

I nomi sono in italiano di proposito: Lorenzo non è uno sviluppatore e questo
è il modulo che ha più probabilità di volere aperto per cambiare un colore.

## Il vincolo che decide tutto

Il motore di stampa (wkhtmltopdf con Qt WebKit) non sa disegnare sfumature,
trasparenze, `rgba()`, scatole flessibili né SVG. Un'identità che ne avesse
bisogno sarebbe bellissima nel browser e rotta nel PDF venduto. Per questo
qui ci sono solo tinte piatte: sono l'unica cosa che si vede identica nel
browser, nel PDF e dentro un foglio di calcolo.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# I colori. Forma `#rrggbb` per il web e per il PDF.
# ---------------------------------------------------------------------------

# L'inchiostro. Non nero pieno: il nero assoluto su carta bianca vibra e
# stanca: tutti i libri stampati bene usano un nero caldo o bluastro.
INCHIOSTRO = "#16212F"

# Il blu profondo dell'identità. È il colore delle testate e delle copertine.
NOTTE = "#1A3B5C"

# L'oro. È l'UNICO accento del documento, e va usato con avarizia: un filetto,
# una sopralinea, il numero di un giorno. Se comincia a comparire ovunque
# smette di significare «guarda qui» e diventa decorazione.
ORO = "#B08D4F"

# I grigi. Uno per il testo secondario, uno per i filetti. Sono due e non
# cinque: una scala di grigi lunga è il modo più rapido per far sembrare un
# documento una schermata di impostazioni.
GRIGIO_TESTO = "#6C7683"
FILETTO = "#E2DED6"

# Le carte. Il bianco pieno per le pagine, l'avorio per i riquadri che devono
# staccarsi appena dal fondo senza diventare scatole.
CARTA = "#FFFFFF"
AVORIO = "#FAF7F1"


# ---------------------------------------------------------------------------
# I caratteri
# ---------------------------------------------------------------------------
# Nomi di famiglie sempre presenti: il PDF si stampa dentro un contenitore
# Docker minimo, e un carattere che non c'è non dà errore — viene sostituito,
# in silenzio, e il documento esce con una faccia che non è la sua.
SERIF = "Georgia, 'Times New Roman', serif"
SENZA_GRAZIE = "'Helvetica Neue', Helvetica, Arial, sans-serif"

# Il maiuscoletto spaziato delle sopralinee.
SPAZIATURA_OCCHIELLO = "0.18em"


# ---------------------------------------------------------------------------
# Il nome
# ---------------------------------------------------------------------------
MARCHIO = "AI TRAVEL AGENCY"
# Cosa c'è scritto sotto il marchio. Una riga sola: se ne servissero due, il
# prodotto non sarebbe chiaro nemmeno a chi lo vende.
SOTTOTITOLO_MARCHIO = "Itinerari su misura"


# ---------------------------------------------------------------------------
# La stessa tavolozza per il foglio di calcolo
# ---------------------------------------------------------------------------
# `openpyxl` vuole `AARRGGBB` — otto cifre, con l'opacità davanti — e non
# accetta il cancelletto. Convertire a mano ogni volta è il modo con cui, fra
# sei mesi, il foglio avrà colori leggermente diversi dal PDF senza che
# nessuno sappia dire quando è successo.
def excel(colore: str) -> str:
    """Da `#rrggbb` a `FFRRGGBB`, la forma che vuole `openpyxl`."""
    testo = str(colore or "").strip().lstrip("#")
    return f"FF{testo.upper()}"


# Le fasce temporali del foglio della valigia. I colori dicono una cosa vera
# — quanto manca alla scadenza — quindi qui il semaforo ha senso e resta. Ma
# sono tinte SMORZATE, non i colori pieni di un foglio di calcolo qualsiasi:
# devono leggersi come carta colorata, non come un allarme.
FASCE = {
    "subito": "#EFD9D2",          # terracotta chiara
    "due_settimane": "#F3E4D0",   # sabbia
    "settimana": "#F5EFD8",       # avorio caldo
    "vigilia": "#E1E9DE",         # salvia
    "viaggio": "#DBE5EE",         # azzurro polvere
}
