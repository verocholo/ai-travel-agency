"""
NUOVO 2026-08-03 — task #181. Le IMMAGINI del documento.

RICHIESTA DI LORENZO
--------------------
«inserisci alcune immagini con senso» e, poco piu' avanti, «meno testo piu'
immagini, non deve essere noioso». Piu' la sua scelta esplicita, messa per
iscritto: "Foto vere ovunque + grafica interna", accettando un costo in piu'
per itinerario.

TRE SORGENTI, NELL'ORDINE
-------------------------
0. **La foto libera di Wikimedia Commons** [AGGIUNTO 2026-08-03, task #189].
   Prima di tutte, per una ragione che non e' estetica: e' l'unica sorgente
   che possiamo mettere dentro un PDF venduto, scaricato e conservato per
   sempre senza dipendere dalle condizioni d'uso di un fornitore. Costa zero
   euro e costa secondi, quindi non ha un tetto di spesa ma un cronometro
   (`SECONDI_MASSIMI_LIBERE`). La sua didascalia — autore, Commons, licenza —
   e' obbligatoria: e' la condizione a cui la foto si puo' usare, non un
   commento. Vedi `src/wikimedia.py`.
1. **La foto vera del luogo**, da Google Places, come RISERVA. E' quella che
   il cliente riconosce: se in copertina della guida del Duomo c'e' il Duomo,
   la guida sembra una guida. Su Commons ci sono milioni di monumenti e quasi
   nessuna trattoria: Google copre esattamente quel buco. Costa una chiamata
   a pagamento per foto (SKU "Place Photo", vedi `cost_telemetry`), e per
   questo c'e' un tetto: `MAX_FOTO`. Il tetto conta SOLO queste.
2. **La grafica disegnata in casa**, quando nessuna foto vera c'e'. Non e' un
   ripiego estetico ed e' bene essere chiari sul perche' esiste: la foto vera
   dipende da una chiave, da una quota e da una rete, cioe' da tre cose che
   possono non esserci, e una funzione di prodotto che dipende da una
   chiamata di rete non e' una funzione di prodotto — e' una speranza. E' la
   stessa decisione gia' presa per le cartine in `src/map_render.py`, per le
   stesse ragioni.

ONESTA' SU COSA SI STA GUARDANDO
--------------------------------
La grafica interna NON assomiglia a una fotografia e non ci prova: e' una
fascia di colore con il nome del luogo, la sua categoria e un motivo
geometrico. E il suo credito lo dice a lettere: «Grafica AI Travel Agency —
non e' una fotografia del luogo». Un'immagine generica spacciata per la foto
del posto sarebbe la bugia piu' facile da raccontare in un documento di
viaggio, e il cliente la scoprirebbe esattamente nel momento peggiore:
davanti al posto.

Per questo la grafica interna sta SOLO nelle guide della singola attrazione,
mai nel documento principale: nel documento principale un'immagine vale se
mostra un luogo vero, altrimenti e' rumore colorato. Chi legge il documento
principale lo sta sfogliando; chi apre la guida di un'attrazione ha gia'
scelto quel posto, e li' la fascia colorata fa il suo lavoro — separa,
intitola, rende la pagina non-noiosa — senza fingere niente.

DIMENSIONI E PESO
-----------------
Tutte le immagini escono da qui come PNG di al massimo `LARGHEZZA_MAX` pixel.
Il PDF le porta dentro in base64, cioe' un terzo piu' pesanti dei loro byte,
moltiplicato per il numero di attrazioni: senza questo taglio un itinerario
con venti guide diventerebbe un allegato che non passa da una casella di
posta. A 800 pixel una foto riempie la larghezza della pagina stampata senza
sgranare.
"""
from __future__ import annotations

import hashlib
import io
import time

from . import places_client
from . import wikimedia

# Quante foto VERE (a pagamento) al massimo per itinerario. Non e' un limite
# tecnico: e' una decisione di costo. A 7 $ ogni mille foto, dodici foto
# costano circa 0,077 € — dentro la forchetta che Lorenzo ha accettato
# ("0,07-0,10 € in piu' per itinerario"). Alzarlo e' una riga; farlo senza
# rimisurare il margine no.
MAX_FOTO = 12

# Larghezza massima in pixel dell'immagine che finisce nel documento.
# [ALZATO 2026-08-11 — segnalazione di Lorenzo: «le foto sono stretchate o in
# bassa risoluzione».] Erano 800 pixel di larghezza. Su schermo bastano; sulla
# pagina stampata quella stessa immagine si allarga su diciotto centimetri,
# cioe' circa 110 punti per pollice — la soglia sotto la quale una fotografia
# comincia a sembrare sgranata, e il documento con lei. A 1600 si sta intorno
# ai 220, che e' qualita' da stampa.
#
# Il peso non aumenta, DIMINUISCE: vedi `normalizza_png()` qui sotto, che da
# oggi salva in JPEG invece che in PNG. Una fotografia in PNG pesa dieci volte
# tanto, perche' il PNG e' fatto per i disegni a tinte piatte e non per le
# sfumature di un cielo.
LARGHEZZA_MAX = 1600

# --- Il tempo che si puo' spendere cercando fotografie gratuite ------------
#
# Wikimedia non costa soldi, quindi non ha senso metterle un tetto di spesa.
# Ma costa SECONDI, e i secondi in questo progetto sono la risorsa piu' scarsa
# che abbiamo: lo scenario Make ha un tetto di esecuzione di 300 secondi e due
# esecuzioni vere misurate sono durate 239 e 356 secondi. La seconda ha gia'
# sforato. Venti attrazioni x due chiamate x dodici secondi di attesa
# basterebbero da sole a superare il tetto, e il cliente che ha pagato 4,90 €
# non riceverebbe niente — per colpa di fotografie che erano un di piu'.
#
# Quindi il tetto qui e' un cronometro: quando il tempo speso a cercare foto
# libere supera SECONDI_MASSIMI_LIBERE si smette di cercarle e si passa a
# Google o alla grafica disegnata. Il documento esce sempre; esce con meno
# fotografie vere quando la rete e' lenta. E' l'unico ordine di priorita'
# accettabile fra "bello" e "consegnato".
SECONDI_MASSIMI_LIBERE = 45

# Attesa massima per singola chiamata a Commons. Piu' bassa del predefinito
# del modulo (12 s) di proposito: qui dentro ci sono decine di chiamate in
# fila, e una sola risposta lenta non deve mangiarsi un quarto del budget.
TIMEOUT_LIBERA = 6

# Altezza della grafica interna, in proporzione da cartolina larga: deve
# occupare una fascia, non mezza pagina.
_GRAFICA_W, _GRAFICA_H = 800, 300

CREDITO_GRAFICA_INTERNA = "Grafica AI Travel Agency — non è una fotografia del luogo"

# Un colore per categoria, cosi' che sfogliando le guide si riconosca a colpo
# d'occhio se si sta guardando un museo o un ristorante. Sono gli stessi toni
# della cartina disegnata in casa (`map_render._MARKER_RGB`): due tavolozze
# diverse nello stesso documento si notano e sembrano un errore.
_COLORI = {
    "museum": ((37, 71, 108), (72, 122, 168)),
    "restaurant": ((140, 60, 44), (186, 104, 76)),
    "shopping": ((96, 62, 120), (139, 104, 162)),
    "activity": ((32, 96, 92), (68, 143, 134)),
}
_COLORE_DEFAULT = ((47, 102, 144), (94, 148, 188))

_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
)
_FONT_BOLD_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
)

_ETICHETTA_TIPO = {
    "museum": "MUSEO E CULTURA",
    "restaurant": "DOVE MANGIARE",
    "shopping": "SHOPPING",
    "activity": "DA VEDERE",
}


def _load_font(size: int, bold: bool = False):
    from PIL import ImageFont
    for path in (_FONT_BOLD_CANDIDATES if bold else _FONT_CANDIDATES):
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    try:
        return ImageFont.load_default()
    except Exception:
        return None


def normalizza_png(grezzi: bytes, larghezza_max: int = LARGHEZZA_MAX) -> bytes | None:
    """Byte di un'immagine qualunque -> PNG ridimensionato. None se illeggibile.

    Google restituisce quasi sempre un JPEG. Il documento la scrive dentro un
    `data:image/png;base64`, e dichiarare PNG un JPEG e' il genere di bugia
    che funziona in un browser e non funziona in wkhtmltopdf — cioe' che si
    scopre solo guardando il PDF finito, che e' tardi. Qui la conversione e'
    vera.

    Il ridimensionamento e' l'altra meta': vedi la nota sul peso in cima al
    modulo.
    """
    if not grezzi:
        return None
    try:
        from PIL import Image
        immagine = Image.open(io.BytesIO(grezzi))
        immagine.load()
        if immagine.mode not in ("RGB", "L"):
            immagine = immagine.convert("RGB")
        larghezza, altezza = immagine.size
        if larghezza <= 0 or altezza <= 0:
            return None
        if larghezza > larghezza_max:
            nuova_altezza = max(1, round(altezza * larghezza_max / larghezza))
            immagine = immagine.resize((larghezza_max, nuova_altezza), Image.LANCZOS)
        uscita = io.BytesIO()
        # [CAMBIATO 2026-08-11] JPEG, non PNG. Il PNG conserva ogni pixel
        # esattamente com'e': perfetto per un disegno a tinte piatte, sbagliato
        # per una fotografia, dove costa dieci volte tanto per una differenza
        # che nessun occhio vede. Con lo stesso peso di prima si porta il
        # doppio della risoluzione.
        #
        # `quality=85` e' il punto dove si smette di vedere la differenza;
        # `progressive` non serve alla stampa ma non costa niente.
        immagine.save(uscita, format="JPEG", quality=85, optimize=True,
                      progressive=True)
        return uscita.getvalue()
    except Exception as e:  # noqa: BLE001 — un'immagine rotta non e' un guasto
        print(f"⚠️  foto.normalizza_png: immagine illeggibile — {type(e).__name__}: {e}")
        return None


def mime_immagine(dati: bytes) -> str:
    """`image/jpeg` o `image/png`, guardando i byte veri.

    [AGGIUNTO 2026-08-11] Da quando le fotografie escono in JPEG e le cartine
    restano PNG, il documento non puo' piu' dichiarare un formato a memoria.
    Scrivere `data:image/png` davanti a un JPEG e' la bugia che il browser
    perdona e il motore di stampa no: l'immagine sparisce dal PDF e ce ne si
    accorge guardando la pagina finita, cioe' tardi.

    Si guardano i primi due byte, che sono la firma del formato. Il PNG resta
    la risposta prudente per tutto il resto: e' cio' che il documento ha
    sempre usato.
    """
    if isinstance(dati, (bytes, bytearray)) and dati[:2] == b"\xff\xd8":
        return "image/jpeg"
    return "image/png"


def _sfumatura_verticale(disegno, larghezza: int, altezza: int, alto, basso) -> None:
    """Il fondo della grafica interna, riga per riga.

    Pillow non ha un gradiente: si disegna a mano, una riga di pixel alla
    volta. Costa qualche millisecondo e vale la pena — una fascia di colore
    piatto sembra un errore di stampa, una sfumata sembra una copertina.
    """
    for y in range(altezza):
        quota = y / max(1, altezza - 1)
        colore = tuple(
            round(alto[i] + (basso[i] - alto[i]) * quota) for i in range(3)
        )
        disegno.line([(0, y), (larghezza, y)], fill=colore)


def _testo_a_capo(disegno, testo: str, font, larghezza_max: int) -> list[str]:
    """Il nome spezzato in righe che stanno dentro la fascia."""
    parole = [p for p in str(testo).split() if p]
    if not parole:
        return []
    righe, corrente = [], parole[0]
    for parola in parole[1:]:
        prova = f"{corrente} {parola}"
        larghezza = disegno.textbbox((0, 0), prova, font=font)[2]
        if larghezza <= larghezza_max:
            corrente = prova
        else:
            righe.append(corrente)
            corrente = parola
    righe.append(corrente)
    return righe[:3]


def copertina_interna(nome: str, tipo: str = "") -> bytes | None:
    """La fascia disegnata in casa per un'attrazione. PNG, oppure None.

    Deterministica: lo stesso nome produce sempre la stessa figura. Serve
    perche' il campione rigenerato due volte dev'essere identico due volte,
    altrimenti nessuno sa piu' dire se una differenza vista a schermo e' una
    modifica o il caso.
    """
    testo = str(nome or "").strip()
    if not testo:
        return None
    try:
        from PIL import Image, ImageDraw
        chiave = str(tipo or "").strip().lower()
        alto, basso = _COLORI.get(chiave, _COLORE_DEFAULT)
        immagine = Image.new("RGB", (_GRAFICA_W, _GRAFICA_H), alto)
        disegno = ImageDraw.Draw(immagine)
        _sfumatura_verticale(disegno, _GRAFICA_W, _GRAFICA_H, alto, basso)

        # Il motivo geometrico: cerchi concentrici deboli, spostati in modo
        # deterministico a partire dal nome. Due guide vicine non si somigliano,
        # e nessuna delle due sembra una fotografia.
        seme = int(hashlib.sha1(testo.encode("utf-8")).hexdigest()[:8], 16)
        cx = _GRAFICA_W - 130 - (seme % 90)
        cy = 60 + ((seme // 90) % 70)
        velo = tuple(min(255, c + 26) for c in basso)
        for raggio in range(40, 240, 32):
            disegno.ellipse(
                [cx - raggio, cy - raggio, cx + raggio, cy + raggio],
                outline=velo, width=2,
            )

        etichetta = _ETICHETTA_TIPO.get(chiave, "DA VEDERE")
        font_etichetta = _load_font(20, bold=True)
        font_nome = _load_font(46, bold=True)
        if font_etichetta is None or font_nome is None:
            return None

        disegno.text((44, 44), etichetta, font=font_etichetta,
                     fill=tuple(min(255, c + 90) for c in alto))
        righe = _testo_a_capo(disegno, testo, font_nome, _GRAFICA_W - 88)
        y = 110
        for riga in righe:
            disegno.text((44, y), riga, font=font_nome, fill=(255, 255, 255))
            y += 56

        uscita = io.BytesIO()
        # Qui il PNG resta, e non e' una dimenticanza: questa immagine e' un
        # DISEGNO a tinte piatte — sfondo, righe, lettere. E' esattamente il
        # caso per cui il PNG esiste, e in JPEG le lettere si sfrangerebbero.
        # Le fotografie vere, che sono l'altro caso, escono in JPEG da
        # `normalizza_png()`.
        immagine.save(uscita, format="PNG", optimize=True)
        return uscita.getvalue()
    except Exception as e:  # noqa: BLE001
        print(f"⚠️  foto.copertina_interna: non disegnata — {type(e).__name__}: {e}")
        return None


def _indice_poi(poi) -> dict:
    """`{poi_id: {"nome", "tipo", "ref", "credito"}}` da POI dict oppure oggetti.

    Accetta entrambe le forme di proposito, come `pdf_extras._orari_per_poi`:
    `service.py` ha in mano i POI gia' convertiti in dizionari dal payload di
    Make, `main.py` ha l'`ApiPayload` con le dataclass. Una funzione che
    accettasse una sola delle due costringerebbe uno dei due chiamanti a
    convertire, e quella conversione sarebbe il punto in cui prima o poi le
    due strade si separano.
    """
    indice: dict = {}
    for elemento in (poi or []):
        if isinstance(elemento, dict):
            leggi = elemento.get
        elif elemento is not None:
            leggi = lambda campo, _e=elemento: getattr(_e, campo, None)  # noqa: E731
        else:
            continue
        identificativo = leggi("id")
        if not isinstance(identificativo, str) or not identificativo:
            continue
        indice[identificativo] = {
            "nome": leggi("name") if isinstance(leggi("name"), str) else "",
            "tipo": leggi("type") if isinstance(leggi("type"), str) else "",
            "ref": leggi("photo_ref") if isinstance(leggi("photo_ref"), str) else "",
            "credito": (leggi("photo_credit")
                        if isinstance(leggi("photo_credit"), str) else ""),
        }
    return indice


def _id_delle_guide(guides) -> list[str]:
    """Gli id delle attrazioni che avranno una guida, in ordine e senza doppioni.

    L'ordine conta: e' l'ordine in cui il tetto `MAX_FOTO` viene speso. Le
    guide arrivano gia' ordinate per importanza dal generatore, quindi
    spendere in ordine significa comprare le foto dei posti che il cliente
    guardera' per primi.
    """
    visti: list[str] = []
    for guida in (guides or []):
        if not isinstance(guida, dict):
            continue
        identificativo = guida.get("poi_id")
        if isinstance(identificativo, str) and identificativo and identificativo not in visti:
            visti.append(identificativo)
    return visti


def _foto_libera(nome: str, citta: str, scaduto) -> tuple[bytes | None, str]:
    """La fotografia gratuita di Commons, se c'e' e se c'e' ancora tempo.

    Torna `(png, didascalia)` oppure `(None, "")`. La didascalia NON e' un
    commento sulla foto: e' la licenza. Wikimedia permette di ridistribuire
    l'immagine dentro un documento venduto a una condizione sola — che
    l'autore e la licenza siano scritti accanto. Per questo escono insieme
    dalla stessa funzione: separarli renderebbe possibile stampare l'una
    senza l'altra, cioe' violare la licenza per distrazione.
    """
    if not nome or scaduto():
        return None, ""
    trovata = wikimedia.cerca_immagine(nome, citta, timeout=TIMEOUT_LIBERA)
    if trovata is None:
        return None, ""
    png = normalizza_png(trovata.byte)
    if not png:
        return None, ""
    return png, trovata.didascalia()


def raccogli_foto(guides, poi, api_key: str | None = None,
                  massimo: int = MAX_FOTO, citta: str = "") -> dict:
    """`{poi_id: {"png", "credito", "reale", "fonte"}}` per le attrazioni con una guida.

    TRE SORGENTI, IN QUEST'ORDINE — E L'ORDINE NON E' ESTETICO
    ----------------------------------------------------------
    1. **Wikimedia Commons**, gratuita e con licenza libera. Prima di tutto il
       resto non perche' sia piu' bella, ma perche' e' l'unica che possiamo
       mettere dentro un PDF che il cliente paga, scarica e tiene per sempre
       senza dipendere dalle condizioni d'uso di qualcun altro. Costa zero
       euro e costa secondi: per questo ha un cronometro, non un tetto di
       spesa (vedi `SECONDI_MASSIMI_LIBERE`).
    2. **Google Places**, a pagamento e con tetto `massimo`. E' la riserva:
       copre i posti che su Commons non esistono — le trattorie, i negozi, i
       locali di quartiere — dove Wikimedia trova milioni di monumenti e
       nessun ristorante.
    3. **La grafica disegnata in casa**, che non finge di essere una
       fotografia e lo dichiara nel proprio credito.

    Il tetto `massimo` conta SOLO le foto di Google, perche' e' un tetto di
    spesa e Wikimedia non si paga. Una foto libera trovata al posto di una a
    pagamento e' un risparmio, non un consumo: contarla sarebbe l'errore
    esattamente contrario a quello che il tetto serve a evitare.
    
    `reale` distingue la fotografia dal disegno, ed e' la chiave che permette
    al documento principale di stampare solo le prime: vedi la nota
    sull'onesta' in cima al modulo.

    Non alza mai un'eccezione e non lascia mai una guida senza immagine finche'
    Pillow risponde: senza chiave, senza rete o a tetto esaurito ogni
    attrazione riceve comunque la sua fascia disegnata in casa. E' il motivo
    per cui il campione generato in questo ambiente — dove `maps.googleapis.com`
    non e' raggiungibile affatto — mostra lo stesso un documento illustrato, e
    il motivo per cui va detto a chiare lettere che quelle non sono le foto
    vere: qui non ci arriveranno mai, in produzione si.
    """
    risultato: dict = {}
    indice = _indice_poi(poi)
    try:
        tetto = max(0, int(massimo))
    except (TypeError, ValueError):
        tetto = MAX_FOTO
    spese = 0

    # Il cronometro parte qui e non dentro `_foto_libera`: deve misurare il
    # tempo speso in TUTTE le ricerche messe insieme, non in una sola. Un
    # budget per chiamata non proteggerebbe da venti chiamate lente.
    inizio = time.monotonic()

    def scaduto() -> bool:
        return (time.monotonic() - inizio) > SECONDI_MASSIMI_LIBERE

    for identificativo in _id_delle_guide(guides):
        scheda = indice.get(identificativo) or {}
        nome = scheda.get("nome") or ""
        immagine = None
        credito = ""
        fonte = ""

        # 1. La fotografia libera, gratis.
        immagine, credito = _foto_libera(nome, citta, scaduto)
        if immagine:
            fonte = "wikimedia"

        # 2. La riserva a pagamento, solo se la prima non ha trovato niente.
        ref, credito_vero = scheda.get("ref") or "", scheda.get("credito") or ""
        # Il credito si controlla PRIMA di spendere, non dopo: una foto senza
        # attribuzione non verrebbe stampata comunque (vedi
        # `poi_pdf.build_guide_html`), quindi comprarla sarebbe soldi buttati
        # in cambio di niente.
        if not immagine and api_key and ref and credito_vero and spese < tetto:
            spese += 1
            grezzi = places_client.fetch_place_photo(ref, api_key, LARGHEZZA_MAX)
            immagine = normalizza_png(grezzi) if grezzi else None
            if immagine:
                credito = credito_vero
                fonte = "google"

        # 3. La grafica disegnata in casa, che dichiara di non essere una foto.
        reale = bool(immagine)
        if not immagine:
            immagine = copertina_interna(nome, scheda.get("tipo") or "")
            credito = CREDITO_GRAFICA_INTERNA
            fonte = "grafica"
        if not immagine:
            continue

        risultato[identificativo] = {
            "png": immagine, "credito": credito, "reale": reale, "fonte": fonte,
        }

    return risultato


def solo_reali(foto: dict | None) -> dict:
    """Le sole immagini che sono davvero fotografie del luogo.

    Il filtro che tiene la grafica interna fuori dal documento principale.
    Esiste come funzione, e non come una riga scritta due volte nei due
    chiamanti, perche' e' esattamente il genere di riga che si dimentica di
    aggiornare nel secondo posto.
    """
    if not isinstance(foto, dict):
        return {}
    return {
        chiave: valore for chiave, valore in foto.items()
        if isinstance(valore, dict) and valore.get("reale") and valore.get("png")
    }


# Quanta altezza si puo' togliere a una fotografia, al massimo, per farla
# diventare piu' larga che alta. Oltre questo, l'immagine non e' piu'
# riconoscibile: e' il difetto che Lorenzo ha chiamato «stretchate» guardando
# le due torri ridotte a una striscia di mattoni.
#
# Quaranta per cento e' misurato: una foto orizzontale non ci arriva mai
# (le serve poco o niente), una verticale ci sbatte contro subito — che e'
# esattamente il caso da proteggere.
TAGLIO_MASSIMO = 0.40


def ritaglia_panoramica(grezzi: bytes, rapporto: float = 2.6) -> bytes | None:
    """La stessa fotografia, ritagliata a fascia larga. `None` se non si legge.

    [AGGIUNTO 2026-08-13 — task #209] Serve alla fascia in cima alla
    copertina, e nasce da un vincolo che in questo progetto ha gia' fatto
    danni una volta.

    In un browser questa cosa si fa con una riga: `object-fit: cover`, e
    l'immagine riempie il riquadro tagliando quello che avanza. Il motore di
    stampa di questo progetto quella proprieta' la ignora **in silenzio**: si
    vedrebbe l'anteprima perfetta e il PDF venduto sbagliato.

    L'alternativa dentro il foglio di stile sarebbe `width: 100%` insieme a
    `max-height`, ed e' esattamente la coppia che l'11 agosto ha prodotto le
    fotografie schiacciate che Lorenzo ha segnalato: il motore obbedisce a
    tutte e due gli ordini e deforma l'immagine.

    Quindi il ritaglio si fa QUI, sui pixel, dove funziona davvero. Dopo, il
    foglio di stile puo' dire soltanto `width: 100%`: le proporzioni sono gia'
    giuste e non c'e' piu' niente da schiacciare.

    Si taglia al CENTRO in altezza, non in alto: nelle fotografie di viaggio
    la meta' superiore e' quasi sempre cielo, e una fascia di solo cielo non
    racconta nessun posto.

    ## QUANTO SI PUO' TAGLIARE, e perche' c'e' un limite

    [AGGIUNTO 2026-08-16 — difetto segnalato da Lorenzo a pagina 6 del
    fascicolo di Bologna: «le foto sono stretchate».]

    Non erano stirate: erano **sbucciate**. Una fotografia verticale — le due
    torri di Bologna, alte e strette — a cui si chiede un rapporto da fascia
    perde l'ottanta per cento dell'altezza, e quello che resta e' una striscia
    di mattoni in cui non si riconosce piu' niente. Sulla pagina si legge
    esattamente come un'immagine deformata, anche se nessun pixel e' stato
    stirato.

    Da qui il tetto: **non si toglie mai piu' di `TAGLIO_MASSIMO` dell'altezza
    originale.** Se il rapporto chiesto costerebbe di piu', si ritaglia fino
    al tetto e ci si ferma. La figura esce un po' meno panoramica di quanto
    chiesto — e questo il foglio di stile lo regge senza deformare niente,
    perche' la larghezza resta l'unica misura dichiarata — invece di uscire
    irriconoscibile.

    E' la stessa regola di tutto il prodotto applicata alle immagini: meglio
    una cosa vera e meno bella che una bella e falsa.
    """
    try:
        import io

        from PIL import Image
    except ImportError:
        return None
    if not isinstance(grezzi, (bytes, bytearray)) or not grezzi:
        return None
    try:
        with Image.open(io.BytesIO(grezzi)) as immagine:
            piena = immagine.convert("RGB")
            larghezza, altezza = piena.size
            if not larghezza or not altezza or rapporto <= 0:
                return None
            voluta = int(larghezza / rapporto)
            # Il tetto al taglio vale SOLO per le fotografie verticali, ed e'
            # una correzione della prima versione di questa regola.
            #
            # Applicandolo a tutte, cambiava anche il comportamento su cui il
            # documento e' gia' tarato: la fascia della copertina, le bande
            # delle giornate, tutte tagliate da fotografie orizzontali che
            # quel taglio lo reggono benissimo — una foto 1200x900 ridotta a
            # 1200x400 resta una fascia leggibile, mentre 600x1400 ridotta a
            # 600x193 e' una striscia di mattoni. La differenza non e' quanto
            # si toglie: e' cosa resta.
            #
            # Una prova gia' scritta l'ha preso subito, ed era nel giusto.
            if altezza > larghezza:
                minima = int(altezza * (1.0 - TAGLIO_MASSIMO))
                if voluta < minima:
                    voluta = minima
            if voluta >= altezza:
                # Gia' piu' panoramica di cosi': si lascia com'e'. Allargarla
                # vorrebbe dire aggiungere pixel che non esistono.
                ritagliata = piena
            else:
                alto = (altezza - voluta) // 2
                ritagliata = piena.crop((0, alto, larghezza, alto + voluta))
            fuori = io.BytesIO()
            ritagliata.save(fuori, format="JPEG", quality=85, optimize=True,
                            progressive=True)
            return fuori.getvalue()
    except Exception:
        return None


def sfuma_in_basso(grezzi: bytes, quota: float = 0.62,
                   forza: float = 0.86) -> bytes | None:
    """La stessa foto con la luce che cala verso il fondo. `None` se non si legge.

    [AGGIUNTO 2026-08-13 — task #213] Serve dove un titolo bianco viene
    stampato SOPRA una fotografia. E' la mossa che fa sembrare il documento
    una rivista invece di una relazione, e ha un difetto che non si vede
    provandola: se capita una foto col fondo chiaro — un cielo, un muro
    d'intonaco, la neve — il titolo sparisce. E capita al cliente, non a noi,
    perche' noi la proviamo su tre foto e lui ne riceve trenta.

    In un browser si risolve con una sfumatura nera semitrasparente. Il motore
    di stampa di questo progetto non sa fare ne' le sfumature (`linear-
    gradient`) ne' la trasparenza (`rgba`, `opacity`): le ignora in silenzio,
    e in silenzio e' la parola che conta. Quindi la sfumatura si disegna sui
    PIXEL, riga per riga, dove funziona sempre.

    Sfumata e non a fascia piena di proposito: una fascia scurita di colpo si
    riconosce come un rettangolo appoggiato sopra la foto, ed e' il contrario
    di premium. L'esponente 1,4 fa partire il buio piano e stringere in fondo,
    che e' come si comporta la luce vera.
    """
    try:
        from PIL import Image
    except ImportError:
        return None
    if not isinstance(grezzi, (bytes, bytearray)) or not grezzi:
        return None
    try:
        with Image.open(io.BytesIO(grezzi)) as immagine:
            piena = immagine.convert("RGB")
            larghezza, altezza = piena.size
            if not larghezza or not altezza:
                return None
            quota = min(max(float(quota), 0.05), 1.0)
            forza = min(max(float(forza), 0.0), 1.0)
            inizio = int(altezza * (1.0 - quota))
            corsa = max(1, altezza - inizio)
            velo = Image.new("L", (1, corsa))
            for riga in range(corsa):
                peso = (riga / (corsa - 1)) ** 1.4 if corsa > 1 else 1.0
                velo.putpixel((0, riga), int(255 * forza * peso))
            velo = velo.resize((larghezza, corsa))
            nero = Image.new("RGB", (larghezza, corsa), (0, 0, 0))
            fascia = piena.crop((0, inizio, larghezza, altezza))
            piena.paste(Image.composite(nero, fascia, velo), (0, inizio))
            fuori = io.BytesIO()
            piena.save(fuori, format="JPEG", quality=88, optimize=True,
                       progressive=True)
            return fuori.getvalue()
    except Exception:
        return None


def ritaglia_tondo(grezzi: bytes, lato: int = 460,
                   sfondo_rgb=(255, 255, 255)) -> bytes | None:
    """La stessa foto dentro un cerchio. `None` se non si legge.

    [AGGIUNTO 2026-08-13 — task #213] Misurato sul motore di stampa: il
    ritaglio tondo via CSS (`border-radius` piu' `overflow: hidden` sul
    contenitore) esce **mezzo tondo e mezzo quadrato** — arrotonda in alto e
    taglia netto in basso. E' una di quelle cose che nell'anteprima del
    browser sono perfette e nel PDF venduto sono un difetto.

    Quindi si ritaglia sui pixel. Si prende il quadrato CENTRALE dell'immagine
    prima di renderla tonda: partendo dall'angolo si taglierebbe via meta' del
    soggetto, che nelle fotografie di viaggio sta quasi sempre al centro.

    IL COLORE DEL FONDO VA DETTO DA CHI CHIAMA.

    [CORRETTO 2026-08-15 — difetto visto da Lorenzo sul documento vero: «in
    copertina se fai il cerchio togli la forma del quadrato bianco dietro che
    e' molto brutto».]

    Aveva ragione e il difetto era mio: il fondo era bianco fisso, e in
    copertina il cerchio sta **sopra un blocco di colore pieno**. Risultato:
    un quadrato bianco attorno alla foto tonda, cioe' esattamente la cosa che
    il ritaglio tondo doveva evitare.

    Non si usa la trasparenza — un PNG con canale alfa pesa di piu' e su certi
    lettori si annerisce, e questo documento e' gia' stato morso da una
    differenza fra motori. Si passa invece il colore su cui la figura andra' a
    finire: cosi' gli angoli scompaiono davvero, su qualunque fondo, e senza
    chiedere niente al motore di stampa.
    """
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None
    if not isinstance(grezzi, (bytes, bytearray)) or not grezzi:
        return None
    try:
        lato = max(16, int(lato))
        with Image.open(io.BytesIO(grezzi)) as immagine:
            piena = immagine.convert("RGB")
            larghezza, altezza = piena.size
            minimo = min(larghezza, altezza)
            if not minimo:
                return None
            sinistra = (larghezza - minimo) // 2
            alto = (altezza - minimo) // 2
            quadrata = piena.crop(
                (sinistra, alto, sinistra + minimo, alto + minimo)
            ).resize((lato, lato))
            maschera = Image.new("L", (lato, lato), 0)
            ImageDraw.Draw(maschera).ellipse((0, 0, lato - 1, lato - 1), fill=255)
            try:
                colore = tuple(int(c) for c in (sfondo_rgb or (255, 255, 255)))[:3]
                if len(colore) != 3:
                    colore = (255, 255, 255)
            except (TypeError, ValueError):
                colore = (255, 255, 255)
            sfondo = Image.new("RGB", (lato, lato), colore)
            sfondo.paste(quadrata, (0, 0), maschera)
            fuori = io.BytesIO()
            sfondo.save(fuori, format="PNG", optimize=True)
            return fuori.getvalue()
    except Exception:
        return None
