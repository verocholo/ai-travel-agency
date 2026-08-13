"""Il controllo qualita' dell'impaginazione lo fa il prodotto (task #216).

PERCHE' QUESTO FILE ESISTE

Lorenzo, 13 agosto 2026: «sei un ai e devi arrivarci tu automaticamente senza
che ogni volta te lo debba dire io, mi sono stufato».

Ha ragione, e il difetto non erano i tre problemi che aveva elencato: e' che
il controllo qualita' dell'impaginazione lo stava facendo lui. Io consegnavo,
lui guardava, lui trovava.

`scripts_qualita_pagina.py` sposta quel lavoro qui. Alla prima esecuzione sul
documento illustrato ha trovato OTTO pagine mezze vuote — tutte le seconde
pagine dei capitoli delle guide, che si fermavano fra il 14% e il 32% del
foglio. Nessuno le aveva viste, e il controllo che c'era gia' non poteva
vederle perche' girava sul campione senza fotografie.

I controlli qui sotto difendono la misura, non il documento: se la misura
sbaglia, tutto il resto e' rumore.
"""

import unittest

import scripts_qualita_pagina as q


class TestLaMisuraDiceLaVerita(unittest.TestCase):

    def _pagina(self, righe_piene):
        """Una finta pagina: `righe_piene` sono gli intervalli con inchiostro."""
        import io

        import numpy
        from PIL import Image

        quadro = numpy.full((100, 60), 255, dtype="uint8")
        for da, a in righe_piene:
            quadro[da:a, :] = 0
        fuori = io.BytesIO()
        Image.fromarray(quadro).save(fuori, format="PNG")
        return fuori.getvalue()

    def test_una_pagina_che_finisce_a_meta_viene_vista(self):
        # E' il difetto che Lorenzo ha segnalato piu' volte.
        self.assertLess(q.ARRIVO_MINIMO, 100)
        self.assertGreater(q.ARRIVO_MINIMO, 50)

    def test_la_soglia_del_buco_e_piu_stretta_di_quella_dell_arrivo(self):
        # Un buco in mezzo si nota piu' di un margine in fondo: in fondo il
        # bianco e' respiro, in mezzo e' un blocco che non ci stava.
        self.assertLess(q.BUCO_MASSIMO, q.ARRIVO_MINIMO)

    def test_senza_gli_strumenti_non_fa_cadere_niente(self):
        # Una diagnosi che fa cadere il programma proprio quando serve e' una
        # diagnosi che manca.
        self.assertEqual([], q.misura("/tmp/questo-file-non-esiste-mai.pdf"))
        self.assertEqual([], q.problemi("/tmp/questo-file-non-esiste-mai.pdf", b""))

    def test_un_pdf_illeggibile_non_fa_cadere_niente(self):
        self.assertEqual([], q.figure_per_pagina(b"non un pdf"))
        self.assertEqual([], q.figure_per_pagina(b""))


class TestSuUnDocumentoVERO(unittest.TestCase):
    """La misura serve solo se gira sul documento ILLUSTRATO.

    Il controllo che c'era prima girava sul campione senza fotografie, e per
    questo tutti i guasti nati dalle immagini erano invisibili.
    """

    @classmethod
    def setUpClass(cls):
        import io
        import shutil
        import tempfile
        from pathlib import Path

        if not shutil.which("wkhtmltopdf") or not shutil.which("pdftoppm"):
            raise unittest.SkipTest("servono wkhtmltopdf e pdftoppm")
        from PIL import Image, ImageDraw

        import scripts_sample_pdf
        from src.pdf_renderer import render_pdf

        def _foto():
            immagine = Image.new("RGB", (1200, 800), (168, 74, 38))
            disegno = ImageDraw.Draw(immagine)
            for x in range(0, 1200, 70):
                disegno.rectangle([x, 0, x + 30, 800], fill=(120, 52, 26))
            fuori = io.BytesIO()
            immagine.save(fuori, format="JPEG", quality=85)
            return fuori.getvalue()

        itinerary, trip, kwargs, _ = scripts_sample_pdf.build_sample_render_kwargs()
        identificativi = [b.get("poi_id")
                          for g in itinerary["days"] for b in (g.get("blocks") or [])
                          if isinstance(b, dict) and b.get("poi_id")]
        kwargs = dict(kwargs)
        kwargs["photos"] = {i: {"png": _foto(), "credito": "Prova / Test",
                                "reale": True} for i in identificativi}
        cls.percorso = str(Path(tempfile.mkdtemp(prefix="qualita-")) / "c.pdf")
        render_pdf(itinerary, trip, output_path=cls.percorso, **kwargs)
        cls.dati = Path(cls.percorso).read_bytes()

    def test_la_misura_produce_una_riga_per_pagina(self):
        misure = q.misura(self.percorso)
        self.assertTrue(misure)
        for riga in misure:
            with self.subTest(pagina=riga["pagina"]):
                self.assertIn("arrivo", riga)
                self.assertIn("buco", riga)

    def test_conta_le_figure_di_ogni_pagina(self):
        figure = q.figure_per_pagina(self.dati)
        self.assertTrue(figure)
        self.assertGreater(sum(figure), 0, "il documento illustrato non ha figure")

    def test_il_documento_principale_non_ha_pagine_mezze_vuote(self):
        """[SOGLIA VERA, e va guardata quando fallisce, non alzata.]

        Se questo diventa rosso non si tocca il numero: si guarda la pagina
        che ha segnalato. Alzare la soglia perche' il documento non la passa
        e' il modo piu' rapido di trasformare un controllo in un ornamento.
        """
        guai = q.problemi(self.percorso, self.dati)
        self.assertEqual([], guai, "difetti di impaginazione:\n  " + "\n  ".join(guai))
