"""Il numero di pagina dice la verita' (task #217).

PERCHE' QUESTO FILE ESISTE

Il piede del fascicolo diceva **«1 / 12» su un documento di ventisei pagine**,
e le pagine delle guide non avevano nessun numero.

Non era una svista: il numero lo scriveva il motore di stampa, e il motore di
stampa vede un file per volta. Quando stampa l'itinerario le guide non
esistono ancora — sono altri file, che verranno cuciti dietro — quindi «12»
era il totale vero di quello che aveva in mano, e diventava falso dieci
secondi dopo.

## Le due strade sbagliate, tenute scritte apposta

1. **Chiedere il numero al motore di stampa.** Il motore del banco di lavoro
   risponde: «--footer-center is not support using unpatched qt, and will be
   ignored». Di qua il piede non esiste, di la' (produzione, con le patch)
   esiste. E' la stessa differenza fra i due motori che a questo progetto e'
   gia' costata una settimana.
2. **Sovrapporre una seconda pagina con `merge_page()`.** Funziona su un
   documento semplice e **rovina questo**: il fascicolo si apre bianco. Il
   testo si estrae ancora — quindi una prova che cerca stringhe passa lo
   stesso — e il guasto si vede solo guardando le pagine.

Il punto 2 e' la ragione per cui qui sotto c'e' un controllo che GUARDA
davvero l'inchiostro sulla carta, e non solo il testo.
"""

import io
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


def _stampa(html: str) -> bytes:
    percorso_html = tempfile.mktemp(suffix=".html")
    percorso_pdf = tempfile.mktemp(suffix=".pdf")
    Path(percorso_html).write_text(html, encoding="utf-8")
    subprocess.run(["wkhtmltopdf", "--quiet", percorso_html, percorso_pdf],
                   capture_output=True, timeout=60, check=True)
    return Path(percorso_pdf).read_bytes()


def _documento(pagine: int, testo: str = "Contenuto") -> bytes:
    pezzi = []
    for n in range(1, pagine + 1):
        pezzi.append(f"<h1>{testo} {n}</h1><p>{'riga di testo. ' * 40}</p>")
        if n < pagine:
            pezzi.append("<div style='page-break-after: always'></div>")
    return _stampa("<html><body>" + "".join(pezzi) + "</body></html>")


def _numeri_stampati(dati: bytes) -> list:
    """Cosa dice il numero di ogni pagina, letto dal disegno stesso.

    Si legge dal disegno e non dall'estrazione del testo di proposito: e'
    l'unica lettura che non puo' essere ingannata da un lettore indulgente.
    """
    from pypdf import PdfReader

    trovati = []
    for pagina in PdfReader(io.BytesIO(dati)).pages:
        risorse = pagina.get("/Resources")
        disegni = (risorse.get_object().get("/XObject") if risorse else None)
        if not disegni:
            trovati.append(None)
            continue
        modulo = disegni.get_object().get("/Numero")
        if modulo is None:
            trovati.append(None)
            continue
        scritta = re.search(r"\((\d+) / (\d+)\)",
                            modulo.get_object().get_data().decode("latin-1"))
        trovati.append(scritta.groups() if scritta else None)
    return trovati


class TestIlTotaleEQuelloDelDocumentoCONSEGNATO(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not shutil.which("wkhtmltopdf"):
            raise unittest.SkipTest("serve wkhtmltopdf")

    def test_ogni_pagina_porta_il_suo_numero(self):
        from src import fascicolo

        numerato = fascicolo.numera(_documento(4))
        self.assertEqual([("1", "4"), ("2", "4"), ("3", "4"), ("4", "4")],
                         _numeri_stampati(numerato))

    def test_dopo_la_cucitura_il_totale_comprende_le_guide(self):
        """E' il difetto vero: «1 / 12» su un fascicolo di ventisei pagine.

        Il totale va calcolato quando il fascicolo e' cucito, non prima: un
        numero scritto in stampa parla di un documento che non e' quello che
        il cliente riceve.
        """
        from src import fascicolo

        principale = _documento(3, "Itinerario")
        capitolo = _documento(2, "Guida")
        cucito, resoconto = fascicolo.cuci(principale, [capitolo])
        self.assertTrue(resoconto.get("numerazione_riuscita"))
        numeri = _numeri_stampati(cucito)
        self.assertEqual(5, len(numeri), numeri)
        self.assertTrue(all(n and n[1] == "5" for n in numeri),
                        f"il totale non e' quello del fascicolo: {numeri}")
        self.assertEqual(["1", "2", "3", "4", "5"], [n[0] for n in numeri])


class TestLaPaginaNONVIENERISCRITTA(unittest.TestCase):
    """[SCRITTO DOPO AVER ROVINATO IL DOCUMENTO UNA VOLTA.]

    La prima versione sovrapponeva le pagine con `merge_page()`. Il fascicolo
    usciva **bianco**, e il testo si estraeva ancora: una prova che cerca
    stringhe sarebbe passata. Qui si controlla la cosa che quella prova non
    guardava.
    """

    @classmethod
    def setUpClass(cls):
        if not shutil.which("wkhtmltopdf") or not shutil.which("pdftoppm"):
            raise unittest.SkipTest("servono wkhtmltopdf e pdftoppm")

    def _inchiostro(self, dati: bytes, pagina: int) -> int:
        try:
            import numpy
            from PIL import Image
        except ImportError:  # pragma: no cover
            self.skipTest("servono numpy e Pillow")
        cartella = Path(tempfile.mkdtemp(prefix="inchiostro-"))
        percorso = cartella / "d.pdf"
        percorso.write_bytes(dati)
        subprocess.run(["pdftoppm", "-f", str(pagina), "-l", str(pagina),
                        "-r", "50", "-png", str(percorso), str(cartella / "p")],
                       capture_output=True, timeout=120)
        immagini = sorted(cartella.glob("p-*.png"))
        self.assertTrue(immagini, "la pagina non si e' nemmeno disegnata")
        quadro = numpy.array(Image.open(immagini[0]).convert("L"))
        return int((quadro < 200).sum())

    def test_la_pagina_numerata_ha_ancora_tutto_quello_che_aveva(self):
        from src import fascicolo

        prima = _documento(2)
        dopo = fascicolo.numera(prima)
        # Un filo in piu' per il numero, non un ordine di grandezza in meno.
        self.assertGreater(self._inchiostro(dopo, 1),
                           self._inchiostro(prima, 1) * 0.95,
                           "la pagina ha perso contenuto: e' il difetto di "
                           "`merge_page()`, che si vede solo sulla carta")

    def test_i_comandi_di_disegno_sono_gli_stessi_byte(self):
        # La prova piu' stretta: il corpo della pagina non viene riscritto, si
        # riusa. Se un domani qualcuno tornasse a ricostruirlo, questo
        # diventerebbe rosso prima che il documento arrivi a un cliente.
        from pypdf import PdfReader

        from src import fascicolo

        prima = _documento(2)
        originale = (PdfReader(io.BytesIO(prima)).pages[0]["/Contents"]
                     .get_object().get_data())
        dopo = fascicolo.numera(prima)
        corpo = (PdfReader(io.BytesIO(dopo)).pages[0]["/Resources"]
                 .get_object()["/XObject"].get_object()["/Corpo"]
                 .get_object().get_data())
        self.assertEqual(originale, corpo)


class TestINumeriNONCOSTANOICOLLEGAMENTI(unittest.TestCase):
    """I salti interni sono la cosa piu' fragile del prodotto: sono gia'
    spariti una volta per una differenza fra due motori di stampa, e nessuno
    se n'e' accorto per una settimana."""

    @classmethod
    def setUpClass(cls):
        if not shutil.which("wkhtmltopdf"):
            raise unittest.SkipTest("serve wkhtmltopdf")

    def test_le_annotazioni_restano_tutte(self):
        from pypdf import PdfReader

        from src import fascicolo

        html = ("<html><body><a href='https://esempio.invalid/a'>uno</a>"
                "<div style='page-break-after: always'></div>"
                "<a href='https://esempio.invalid/b'>due</a></body></html>")
        prima = _stampa(html)

        def quanti(dati):
            totale = 0
            for pagina in PdfReader(io.BytesIO(dati)).pages:
                elenco = pagina.get("/Annots")
                totale += len(elenco.get_object()) if elenco is not None else 0
            return totale

        self.assertGreater(quanti(prima), 0, "la prova non misura niente")
        self.assertEqual(quanti(prima), quanti(fascicolo.numera(prima)))


class TestQuandoNONSIPUOFARENIENTE(unittest.TestCase):
    """Un documento senza numeri e' un fastidio; un documento con i numeri
    sbagliati, o rovinato, e' un danno. Nel dubbio si torna indietro."""

    def test_dei_byte_che_non_sono_un_pdf_tornano_indietro_uguali(self):
        from src import fascicolo

        self.assertEqual(b"non un pdf", fascicolo.numera(b"non un pdf"))
        self.assertEqual(b"", fascicolo.numera(b""))
        self.assertIsNone(fascicolo.numera(None))

    def test_il_numero_e_centrato_sul_foglio(self):
        # Le pagine a una cifra e quelle a due hanno larghezze diverse: senza
        # le misure delle lettere il numero si potrebbe solo centrare a
        # occhio, cioe' storto su meta' delle pagine.
        from src import fascicolo

        stretto = fascicolo._disegno_del_numero("1 / 9", 595.0)
        largo = fascicolo._disegno_del_numero("10 / 100", 595.0)
        da_sinistra = [float(re.search(rb"1 0 0 1 ([\d.]+) ", d).group(1))
                       for d in (stretto, largo)]
        self.assertGreater(da_sinistra[0], da_sinistra[1])
        for posizione, testo in zip(da_sinistra, ("1 / 9", "10 / 100")):
            larghezza = fascicolo._larghezza(
                testo, fascicolo.CORPO_DEL_NUMERO_PT)
            # Un centesimo di punto di tolleranza: il comando di disegno
            # porta due decimali, non di piu'.
            self.assertAlmostEqual(595.0 - posizione - larghezza, posizione,
                                   places=1)


if __name__ == "__main__":
    unittest.main()
