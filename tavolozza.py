"""Il documento prende i colori dal posto dove sta andando il cliente (task #209).

PERCHE' QUESTO FILE ESISTE

Lorenzo, 13 agosto 2026, guardando il primo fascicolo con la navigazione
riparata: «per l'estetica vorrei un qualcosa di piu' colorato e accattivante
[...] e poi mi piacerebbe che l'estetica si adattasse al posto in cui il
cliente vuole andare».

Il documento di prima era corretto, leggibile e **freddo**: stessa fascia blu
navy e stesso filetto oro per Bologna, per Santorini e per Marrakech. Sembrava
un rapporto di consulenza, non l'inizio di una vacanza. E soprattutto: non
diceva niente del posto prima ancora che si leggesse una parola.

## Le due strade sbagliate, e perche' sono state scartate

**Chiedere il colore al modello.** Costa token a ogni vendita e, soprattutto,
il modello puo' rispondere qualunque cosa: un giorno un accostamento
illeggibile, e il difetto arriva al cliente perche' nessuno rilegge il CSS di
un documento generato.

**Prendere il colore dominante della foto e usarlo cosi' com'e'.** E'
l'errore classico. Le fotografie vere sono piene di grigi fangosi, cieli
slavati e insegne fluorescenti: un colore estratto e usato tale e quale
produce, prima o poi, un documento illeggibile o brutto — e non c'e' modo di
accorgersene prima che sia partito.

## La strada presa

Le tavolozze sono **disegnate a mano**, poche e tutte belle. La fotografia non
sceglie il colore: sceglie **quale tavolozza**. E' il luogo a votare, ma fra
opzioni che qualcuno ha gia' guardato.

Cosi' si ottengono tutte e due le cose: un documento che a Santorini e' blu e
bianco e a Bologna e' cotto e ocra, e la garanzia che non possa uscire brutto
nemmeno per una destinazione a cui nessuno ha pensato.

Il colore si legge dalle fotografie che **scarichiamo gia'**: nessuna
chiamata in piu', nessun costo in piu', e nessun dato inventato — e' il posto
che si racconta con le proprie immagini.

## Cosa NON cambia mai

I grigi del testo. Il nero dell'inchiostro. Le distanze fra le righe. Cambia
la parte cromatica, non la leggibilita': un documento di trenta pagine si
legge con il contrasto, e quello e' verificato per ogni tavolozza dalle prove
(vedi `tests/test_tavolozza_2026_08_13.py`), non a occhio.
"""

from __future__ import annotations

import colorsys

# --------------------------------------------------------------------------
# I colori che non cambiano mai.
#
# Sono i grigi del testo e il nero dell'inchiostro. Restano identici in ogni
# tavolozza di proposito: un documento di trenta pagine lo si legge grazie ai
# neutri, e farli girare insieme al colore vorrebbe dire rimettere in gioco la
# leggibilita' a ogni destinazione. Cambia la parte cromatica, non quella che
# tiene in piedi la lettura.
# --------------------------------------------------------------------------
NEUTRI = {
    "inchiostro": "#16212f",   # il nero del testo corrente
    "grigio": "#4a5b6b",       # testo secondario
    "grigio_tenue": "#6b7a89",  # didascalie
    "grigio_chiaro": "#8a97a3",  # etichette minute
    "bianco": "#ffffff",
}

# --------------------------------------------------------------------------
# Le tavolozze. Poche, disegnate a mano, tutte gia' guardate.
#
# `tinta` e' l'angolo di colore (0-360) attorno a cui ruota la tavolozza: e'
# il numero con cui la fotografia del posto la sceglie. `fredda` dice se la
# tavolozza sta bene su una destinazione dai colori spenti (pietra, nebbia,
# nord) — serve quando la foto non ha nessuna tinta dominante e votare per
# angolo non avrebbe senso.
#
# Ogni tavolozza ha gli stessi sette ruoli, e i ruoli sono descritti dal
# COMPITO, non dal colore: `scuro` e' «la fascia di testata», non «il blu».
# Chi ne aggiunge una domani non deve indovinare a cosa serve ciascuno.
# --------------------------------------------------------------------------
TAVOLOZZE = (
    {
        "nome": "pietra",
        "descrizione": "citta' d'arte e di calcare: Parigi, Praga, Vienna",
        "tinta": 212, "fredda": True,
        "scuro": "#1a3b5c", "primario": "#2f6690", "accento_testo": "#8a6a2f", "accento": "#b08d4f",
        "sfondo_tenue": "#eef2f6", "sfondo_caldo": "#faf7f1",
        "bordo": "#dbe3ec", "bordo_caldo": "#e2ded6",
    },
    {
        "nome": "mare",
        "descrizione": "coste e isole: Cicladi, Amalfi, Croazia",
        "tinta": 197, "fredda": False,
        "scuro": "#0c3a51", "primario": "#136a8a", "accento_testo": "#8f6414", "accento": "#c8912f",
        "sfondo_tenue": "#e8f2f6", "sfondo_caldo": "#fdf6e9",
        "bordo": "#cfe0e8", "bordo_caldo": "#ece2cf",
    },
    {
        "nome": "cotto",
        "descrizione": "citta' di mattone e portici: Bologna, Siena, Toscana",
        "tinta": 18, "fredda": False,
        "scuro": "#5c2a1b", "primario": "#9c4423", "accento_testo": "#6d5819", "accento": "#7a6320",
        "sfondo_tenue": "#f7ece5", "sfondo_caldo": "#faf5e8",
        "bordo": "#e8d5c8", "bordo_caldo": "#e4dcc6",
    },
    {
        "nome": "verde",
        "descrizione": "montagna, laghi e natura: Alpi, Irlanda, foreste",
        "tinta": 150, "fredda": False,
        "scuro": "#16402f", "primario": "#256b4f", "accento_testo": "#7f621f", "accento": "#94742a",
        "sfondo_tenue": "#e8f2ec", "sfondo_caldo": "#f8f6ea",
        "bordo": "#cfe2d7", "bordo_caldo": "#e3decb",
    },
    {
        "nome": "spezie",
        "descrizione": "sud e deserto: Marrakech, Siviglia, Petra",
        "tinta": 33, "fredda": False,
        "scuro": "#5b3411", "primario": "#a3591a", "accento_testo": "#7d5f10", "accento": "#8a6a12",
        "sfondo_tenue": "#f8efe1", "sfondo_caldo": "#fbf6e6",
        "bordo": "#ead9c0", "bordo_caldo": "#e6dfc4",
    },
    {
        "nome": "nord",
        "descrizione": "freddo e luce bassa: Scandinavia, Islanda, Baltico",
        "tinta": 232, "fredda": True,
        "scuro": "#1d2e45", "primario": "#3a6180", "accento_testo": "#8a6626", "accento": "#96702c",
        "sfondo_tenue": "#eaeff5", "sfondo_caldo": "#f7f5f0",
        "bordo": "#d6dfe9", "bordo_caldo": "#e0dcd2",
    },
    {
        "nome": "tropicale",
        "descrizione": "tropici e barriera: Caraibi, Thailandia, Bali",
        "tinta": 175, "fredda": False,
        "scuro": "#06403c", "primario": "#0d7168", "accento_testo": "#9c4d16", "accento": "#b35a1b",
        "sfondo_tenue": "#e4f2ef", "sfondo_caldo": "#fdf3e9",
        "bordo": "#c8e2dd", "bordo_caldo": "#efdccb",
    },
    {
        "nome": "notte",
        "descrizione": "metropoli e vita notturna: Tokyo, New York, Berlino",
        "tinta": 268, "fredda": False,
        "scuro": "#2a2450", "primario": "#524594", "accento_testo": "#87621a", "accento": "#a97c22",
        "sfondo_tenue": "#eeecf6", "sfondo_caldo": "#faf6ec",
        "bordo": "#dcd8ec", "bordo_caldo": "#e8e0cd",
    },
)

# Quella di sempre. E' anche il ripiego quando non c'e' nessuna fotografia:
# il documento che il prodotto ha venduto finora era esattamente questo, e un
# ripiego deve essere una cosa gia' vista funzionare, non una cosa nuova.
PREDEFINITA = TAVOLOZZE[0]

# Sotto questa saturazione media, la fotografia non ha un colore dominante:
# e' pietra, cemento, nebbia, neve. Votare per angolo di tinta su pixel quasi
# grigi vuol dire lasciar decidere il rumore — un lampione giallo deciderebbe
# che Reykjavik e' una citta' di spezie.
SATURAZIONE_MINIMA = 0.18

# Un pixel entra nel voto solo se ha un colore vero. Fuori il bianco slavato
# del cielo, il nero delle ombre e i grigi: sono la maggioranza di quasi ogni
# fotografia e, se votassero, vincerebbero sempre loro.
_LUMINOSITA_MIN = 0.12
_LUMINOSITA_MAX = 0.94
_SATURAZIONE_PIXEL_MIN = 0.22


def _schiarisci(colore: str, quanto: float) -> str:
    """Lo stesso colore, spostato verso il bianco. `quanto` da 0 a 1.

    Serve per i due ruoli che vivono SOPRA la fascia scura, dove il colore
    pieno sparirebbe. Sono calcolati invece che scritti a mano di proposito:
    restano dentro la famiglia della tavolozza qualunque sia, e chi domani ne
    aggiunge una nona non deve ricordarsi di inventare anche questi due.
    """
    grezzo = colore.lstrip("#")
    canali = [int(grezzo[i:i + 2], 16) for i in (0, 2, 4)]
    misti = [round(c + (255 - c) * quanto) for c in canali]
    return "#" + "".join(f"{c:02x}" for c in misti)


def completa(tavolozza: dict) -> dict:
    """La tavolozza con dentro anche i ruoli che si ricavano dagli altri."""
    piena = dict(tavolozza)
    # Testo e occhiello sopra la fascia scura di testata. I due numeri sono
    # scelti perche' il contrasto sul proprio `scuro` resti sopra la soglia di
    # leggibilita' in TUTTE le tavolozze: e' verificato dalle prove, non a
    # occhio, perche' a occhio un blu chiaro su blu scuro sembra sempre
    # leggibile finche' non lo si guarda stampato.
    piena["chiaro_su_scuro"] = _schiarisci(tavolozza["primario"], 0.78)
    piena["accento_su_scuro"] = _schiarisci(tavolozza["accento"], 0.42)
    return piena


def per_nome(nome: str) -> dict:
    """La tavolozza che si chiama cosi', o quella predefinita."""
    for t in TAVOLOZZE:
        if t["nome"] == nome:
            return completa(t)
    return completa(PREDEFINITA)


def _distanza_di_tinta(a: float, b: float) -> float:
    """Quanto distano due angoli di colore, sapendo che 350 e 10 sono vicini.

    Senza il giro completo, il rosso a 355 gradi risulterebbe lontanissimo
    dall'arancione a 5 — e ogni destinazione dai toni caldi finirebbe nella
    tavolozza sbagliata.
    """
    scarto = abs(a - b) % 360.0
    return min(scarto, 360.0 - scarto)


def _tinta_dominante(dati: bytes) -> tuple[float, float] | None:
    """Angolo di colore prevalente di una fotografia, e quanto e' saturo.

    Torna `None` se l'immagine non si legge: una fotografia illeggibile non
    deve impedire di stampare il documento, al massimo di colorarlo.
    """
    try:
        import io

        from PIL import Image
    except ImportError:
        return None
    try:
        with Image.open(io.BytesIO(dati)) as immagine:
            piccola = immagine.convert("RGB").resize((48, 48))
            pixel = list(piccola.getdata())
    except Exception:
        return None
    if not pixel:
        return None

    # Il voto e' pesato sulla saturazione: un rosso deciso conta piu' di un
    # beige incerto. Senza il peso, mille pixel di intonaco slavato battono
    # cento pixel di mare.
    urna: dict[int, float] = {}
    saturazioni = []
    for r, g, b in pixel:
        h, l, s = colorsys.rgb_to_hls(r / 255.0, g / 255.0, b / 255.0)
        saturazioni.append(s if _LUMINOSITA_MIN < l < _LUMINOSITA_MAX else 0.0)
        if not (_LUMINOSITA_MIN < l < _LUMINOSITA_MAX):
            continue
        if s < _SATURAZIONE_PIXEL_MIN:
            continue
        # Spicchi da 10 gradi: piu' stretti inseguirebbero il rumore del
        # sensore, piu' larghi confonderebbero l'arancione col giallo.
        spicchio = int((h * 360.0) // 10) * 10
        urna[spicchio] = urna.get(spicchio, 0.0) + s
    if not urna:
        return None
    vincitore = max(urna, key=lambda k: urna[k])
    media = sum(saturazioni) / len(saturazioni)
    return float(vincitore + 5), media


def scegli(foto: dict | None) -> dict:
    """La tavolozza del viaggio, decisa dalle fotografie vere del posto.

    `foto` e' la stessa struttura che il resto del prodotto gia' maneggia:
    `poi_id -> {"png": bytes, "reale": True, ...}`. Contano solo gli scatti
    REALI: una copertina disegnata da noi direbbe soltanto di che colore la
    disegniamo noi, e la tavolozza si sceglierebbe da sola guardandosi allo
    specchio.

    Senza fotografie si torna alla tavolozza di sempre. E' voluto: un
    documento senza immagini non ha nessuna informazione sul posto, e
    inventargli un colore sarebbe la stessa cosa che inventargli un prezzo.
    """
    if not isinstance(foto, dict):
        return completa(PREDEFINITA)
    voti: dict[str, float] = {}
    saturazioni = []
    for scatto in foto.values():
        if not isinstance(scatto, dict) or not scatto.get("reale"):
            continue
        dati = scatto.get("png")
        if not isinstance(dati, (bytes, bytearray)) or not dati:
            continue
        letto = _tinta_dominante(bytes(dati))
        if letto is None:
            continue
        tinta, saturazione = letto
        saturazioni.append(saturazione)
        vicina = min(
            (t for t in TAVOLOZZE),
            key=lambda t: _distanza_di_tinta(tinta, float(t["tinta"])),
        )
        voti[vicina["nome"]] = voti.get(vicina["nome"], 0.0) + 1.0

    if not voti or not saturazioni:
        return completa(PREDEFINITA)

    # Posto senza colore dominante (pietra, nebbia, neve): si sceglie fra le
    # tavolozze fredde, che sono disegnate per reggere una luce spenta.
    if sum(saturazioni) / len(saturazioni) < SATURAZIONE_MINIMA:
        fredde = {n: v for n, v in voti.items() if per_nome(n)["fredda"]}
        return per_nome(max(fredde, key=lambda n: fredde[n])) if fredde else completa(PREDEFINITA)

    # A parita' di voti vince la prima in elenco, non «una qualsiasi»: lo
    # stesso viaggio, rigenerato, deve dare lo stesso documento. Un colore che
    # cambia fra due esecuzioni identiche e' un difetto che nessuno riesce a
    # riprodurre e che quindi non si ripara mai.
    massimo = max(voti.values())
    for tavolozza in TAVOLOZZE:
        if voti.get(tavolozza["nome"], 0.0) == massimo:
            return completa(tavolozza)
    return completa(PREDEFINITA)


# --------------------------------------------------------------------------
# Contrasto. Non e' un vezzo da manuale: e' la differenza fra un documento
# che si legge sul telefono al sole e uno che il cliente chiude.
# --------------------------------------------------------------------------
def _canale(valore: float) -> float:
    return valore / 12.92 if valore <= 0.03928 else ((valore + 0.055) / 1.055) ** 2.4


def luminosita(colore: str) -> float:
    """Quanta luce emette un colore (0 nero, 1 bianco), formula WCAG."""
    grezzo = colore.lstrip("#")
    r, g, b = (int(grezzo[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    return (0.2126 * _canale(r) + 0.7152 * _canale(g) + 0.0722 * _canale(b))


def contrasto(primo: str, secondo: str) -> float:
    """Il rapporto di contrasto fra due colori: da 1 (uguali) a 21."""
    a, b = luminosita(primo), luminosita(secondo)
    chiaro, scuro = max(a, b), min(a, b)
    return (chiaro + 0.05) / (scuro + 0.05)
