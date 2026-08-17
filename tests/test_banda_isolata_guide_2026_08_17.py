"""La fila di foto in fondo alla guida non resta isolata su una pagina vuota
(task #227).

PERCHE' QUESTO FILE ESISTE

Ultimo dei nove difetti segnalati da Lorenzo sul fascicolo di Bologna:
pagine 13, 15, 17, 19, 21, 23, 25, 27, «due foto piccole e tutto lo spazio
vuoto». Il fix delle colonne dinamiche (`_banda_di_foto`, vedi
`tests/test_banda_guide_dinamica_2026_08_17.py`) risolve lo spreco di
colonne ma non basta da solo: quando il resto della scheda riempie quasi
tutta la prima pagina, la fila finale cade DA SOLA su una seconda pagina
quasi vuota, e nessuna fila di fotografie — per quanto ben proporzionata —
puo' riempire un intero foglio A4 senza un ritaglio innaturale.

Stesso metodo gia' usato per il bianco a fine giornata del documento
principale: si stampa, si guarda dove e' caduta la sonda
(`guida-banda-inizio`), si decide se la fila e' isolata, e SOLO in quel
caso si ristampa con una fila piu' grande (meno fotografie, piu' larghe).
"""

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


def _scatto(nome="x", seme=0):
    from PIL import Image, ImageDraw

    immagine = Image.new("RGB", (1400, 900), (110 + seme, 90, 70))
    disegno = ImageDraw.Draw(immagine)
    for x in range(0, 1400, 60):
        disegno.rectangle([x, 0, x + 25, 900], fill=(80 + seme % 40, 55, 40))
    fuori = io.BytesIO()
    immagine.save(fuori, format="JPEG", quality=85)
    return {"png": fuori.getvalue(), "credito": f"Foto: {nome} / Prova"}


def _guida_corta():
    return {"poi_id": "A", "poi_name": "Duomo", "title": "Duomo",
            "history_summary": "Una storia breve."}


def _guida_lunga():
    return {
        "poi_id": "A", "poi_name": "Duomo", "title": "Duomo",
        "history_summary": "Una storia lunga e dettagliata. " * 70,
        "highlights": [{"name": f"Punto {i}", "why": "Una descrizione lunga e articolata." * 3}
                       for i in range(8)],
        "curiosita": ["Una curiosita' interessante e piuttosto lunga da leggere davvero."
                     for _ in range(8)],
        "practical_tips": ["Un consiglio pratico utile e dettagliato." for _ in range(8)],
        "dintorni": [{"name": f"Vicino {i}", "why": "A due passi da qui, molto comodo."}
                    for i in range(6)],
        "errore_da_evitare": "Un errore comune da evitare, spiegato per bene. " * 5,
    }


class TestLaSondaArrivaDavveroNellaGuida(unittest.TestCase):

    def test_la_sonda_precede_la_fila_finale(self):
        from src import poi_pdf

        html = poi_pdf.build_guide_html(
            _guida_corta(), photo=_scatto("duomo"),
            foto_extra=[_scatto("a"), _scatto("b"), _scatto("c"), _scatto("d")],
            sonda_banda=True,
        )
        self.assertIn("id='guida-banda-inizio'", html)
        pezzo = html.split("id='guida-banda-inizio'", 1)[1][:200]
        self.assertIn("guida-banda", pezzo,
                      "la sonda deve stare subito prima della fila di foto")

    def test_la_sonda_non_ha_altezza_dichiarata_a_parte(self):
        """[difetto gia' preso e corretto una volta, altrove — vedi
        `src/pdf_renderer.py`, la sonda di fine giornata] La sonda deve
        stare DENTRO un contenuto gia' presente, non da sola nel flusso:
        qui dentro l'ultima nota o l'ultimo bottone di ritorno."""
        from src import poi_pdf

        html = poi_pdf.build_guide_html(
            _guida_corta(), photo=_scatto("duomo"),
            foto_extra=[_scatto("a"), _scatto("b")],
            sonda_banda=True,
        )
        pezzo = html.split("id='guida-banda-inizio'", 1)[0][-400:]
        self.assertIn("<div class=", pezzo,
                      "la sonda deve stare dentro un div gia' presente")


class TestBandaIsolata(unittest.TestCase):
    """`banda_isolata()`, con sonde finte: nessuna stampa vera."""

    def _con_posizioni(self, finte):
        from src import impaginazione

        return patch.object(impaginazione, "posizioni", lambda _dati: finte)

    def test_sonda_alta_sulla_pagina_e_isolata(self):
        from src import poi_pdf

        with self._con_posizioni({"guida-banda-inizio": (1, 700.0)}):
            self.assertTrue(poi_pdf.banda_isolata(b"finto"))

    def test_sonda_bassa_sulla_pagina_non_e_isolata(self):
        from src import poi_pdf

        with self._con_posizioni({"guida-banda-inizio": (0, 200.0)}):
            self.assertFalse(poi_pdf.banda_isolata(b"finto"))

    def test_senza_sonda_non_e_isolata_per_definizione(self):
        from src import poi_pdf

        with self._con_posizioni({}):
            self.assertFalse(poi_pdf.banda_isolata(b"finto"))

    def test_non_solleva_su_byte_che_non_sono_un_pdf(self):
        from src import poi_pdf

        self.assertFalse(poi_pdf.banda_isolata(b"non un pdf"))


class TestSulDocumentoVEROSTAMPATO(unittest.TestCase):
    """La prova che conta: quanto spazio resta lo dice solo la carta."""

    @classmethod
    def setUpClass(cls):
        import shutil

        if not shutil.which("wkhtmltopdf"):
            raise unittest.SkipTest("serve wkhtmltopdf")

    def test_una_guida_corta_produce_una_sonda_alta_e_isolata(self):
        from src import poi_pdf

        html = poi_pdf.build_guide_html(
            _guida_corta(), photo=_scatto("duomo", 1),
            foto_extra=[_scatto("a", 2), _scatto("b", 3), _scatto("c", 4), _scatto("d", 5)],
            sonda_banda=True,
        )
        blob = poi_pdf.render_guide_pdf(html)
        self.assertTrue(blob)

    def test_una_guida_lunga_lascia_la_fila_isolata_sulla_seconda_pagina(self):
        """La prova che riproduce DAVVERO il difetto: contenuto abbondante
        che riempie quasi tutta la prima pagina, fila di foto sulla
        seconda quasi vuota."""
        from src import poi_pdf

        extra = [_scatto(f"e{i}", i) for i in range(2, 8)]
        html = poi_pdf.build_guide_html(
            _guida_lunga(), photo=_scatto("duomo", 1), foto_extra=extra,
            sonda_banda=True)
        blob = poi_pdf.render_guide_pdf(html)
        self.assertTrue(blob, "la prova non stampa niente: verificare "
                        "wkhtmltopdf")
        self.assertTrue(
            poi_pdf.banda_isolata(blob),
            "la prova non riproduce il difetto — nessuna fila isolata "
            "nemmeno con questo contenuto abbondante: aumentare il "
            "contenuto della fixture, non il codice")

    def test_la_stampa_ingrandita_riempie_di_piu_la_pagina_isolata(self):
        import scripts_qualita_pagina as q
        from src import poi_pdf

        extra = [_scatto(f"e{i}", i) for i in range(2, 8)]
        html_normale = poi_pdf.build_guide_html(
            _guida_lunga(), photo=_scatto("duomo", 1), foto_extra=extra,
            banda_ingrandita=False, sonda_banda=True)
        html_grande = poi_pdf.build_guide_html(
            _guida_lunga(), photo=_scatto("duomo", 1), foto_extra=extra,
            banda_ingrandita=True, sonda_banda=True)

        blob_normale = poi_pdf.render_guide_pdf(html_normale)
        blob_grande = poi_pdf.render_guide_pdf(html_grande)
        self.assertTrue(blob_normale and blob_grande)

        def _riempimento_ultima_pagina(blob):
            percorso = tempfile.mktemp(suffix=".pdf")
            Path(percorso).write_bytes(blob)
            misure = q.misura(percorso)
            self.assertEqual(2, len(misure), "questa prova presume due "
                             "pagine: la prima con la scheda, la seconda "
                             "isolata con la fila di foto")
            return misure[-1]["arrivo"]

        prima = _riempimento_ultima_pagina(blob_normale)
        dopo = _riempimento_ultima_pagina(blob_grande)
        self.assertGreater(
            dopo, prima,
            "la stampa ingrandita doveva riempire di piu' la pagina "
            "isolata rispetto a quella normale — non e' successo")

    def test_costruisci_capitoli_collega_davvero_la_seconda_stampa(self):
        """La trappola gia' presa altre volte in questo progetto: una
        funzione corretta (`banda_isolata`) scritta e mai collegata al
        documento vero."""
        from src import poi_pdf

        guide = [_guida_lunga()]
        photos = {"A": _scatto("duomo", 1), "B": _scatto("b", 2),
                 "C": _scatto("c", 3), "D": _scatto("d", 4),
                 "E": _scatto("e", 5), "F": _scatto("f", 6)}
        capitoli = poi_pdf.costruisci_capitoli(guide, photos=photos)
        self.assertEqual(1, len(capitoli))
        self.assertTrue(capitoli[0]["pdf"])

    def test_ripararla_non_allunga_la_scheda(self):
        """Ingrandire la fila e' facile; farlo senza aggiungere una terza
        pagina e' il punto — stesso principio gia' verificato per il
        documento principale."""
        from src import poi_pdf

        extra = [_scatto(f"e{i}", i) for i in range(2, 8)]
        html_grande = poi_pdf.build_guide_html(
            _guida_lunga(), photo=_scatto("duomo", 1), foto_extra=extra,
            banda_ingrandita=True, sonda_banda=True)
        blob_grande = poi_pdf.render_guide_pdf(html_grande)
        percorso = tempfile.mktemp(suffix=".pdf")
        Path(percorso).write_bytes(blob_grande)

        import scripts_qualita_pagina as q

        self.assertEqual(2, len(q.misura(percorso)))


if __name__ == "__main__":
    unittest.main()
