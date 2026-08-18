"""La copertina del prototipo, quella approvata (task #218).

PERCHE' QUESTO FILE ESISTE

La prima pagina era l'ultima rimasta lontana dal prototipo che Lorenzo aveva
approvato: mancavano il blocco di colore, il bollo con la durata e la
fotografia tonda. E' la pagina che il cliente vede per prima.

## Cosa difendono i controlli qui sotto

**Che la copertina resti di UNA pagina.** Non e' una preoccupazione teorica:
in questo progetto la copertina e' sbordata sulla seconda pagina due volte, e
la seconda volta e' successo proprio aggiungendo un'immagine. Lorenzo
l'11 agosto: «non voglio una pagina iniziata per due righe e poi lasciata
bianca».

**Che la figura tonda sia tonda per davvero.** Con questo motore di stampa gli
angoli arrotondati applicati a un'immagine danno una figura mezza tonda e
mezza quadrata — un difetto che non solleva nessun errore e si vede solo sulla
carta. Il ritaglio si fa sui pixel prima di stampare, e qui si verifica che
sia quella la strada presa.

**Che la durata non sia scritta due volte.** La stessa informazione ripetuta a
sei centimetri di distanza non rassicura: fa venire il dubbio che siano due
cose diverse lette male.
"""

import io
import re
import shutil
import tempfile
import unittest
from pathlib import Path


def _foto(colore=(168, 74, 38)) -> bytes:
    from PIL import Image, ImageDraw

    immagine = Image.new("RGB", (1400, 900), colore)
    disegno = ImageDraw.Draw(immagine)
    for x in range(0, 1400, 80):
        disegno.rectangle([x, 0, x + 35, 900],
                          fill=tuple(max(0, c - 45) for c in colore))
    fuori = io.BytesIO()
    immagine.save(fuori, format="JPEG", quality=85)
    return fuori.getvalue()


def _pezzi(giorni=2, colore=(168, 74, 38)):
    import scripts_sample_pdf

    itinerario, viaggio, kwargs, _ = scripts_sample_pdf.build_sample_render_kwargs()
    identificativi = [b.get("poi_id")
                      for g in itinerario["days"] for b in (g.get("blocks") or [])
                      if isinstance(b, dict) and b.get("poi_id")]
    kwargs = dict(kwargs)
    kwargs.pop("output_path", None)
    kwargs["photos"] = {i: {"png": _foto(colore), "credito": "Prova / Test",
                            "reale": True} for i in identificativi}
    viaggio = dict(viaggio, duration_days=giorni)
    return itinerario, viaggio, kwargs


def _documento(giorni=2, colore=(168, 74, 38)) -> str:
    from src.pdf_renderer import render_html

    itinerario, viaggio, kwargs = _pezzi(giorni, colore)
    return render_html(itinerario, viaggio, **kwargs)


class TestIlBloccoDellaCopertinaCEDAVVERO(unittest.TestCase):

    def test_ci_sono_blocco_bollo_e_figura_tonda(self):
        html = _documento()
        # Si cerca l'ATTRIBUTO e non il nome della classe: il nome compare
        # anche nel foglio di stile, quindi cercarlo li' direbbe di si' anche
        # su una copertina che non ha disegnato niente. Ci sono cascato.
        # [AGGIORNATO 2026-08-18] `cover-blocco` porta ora anche
        # `cover-al-vivo`: il blocco del titolo arriva ai bordi del foglio
        # come nelle brochure che Lorenzo ha portato. Si cerca quindi
        # l'inizio dell'attributo e non la stringa chiusa — altrimenti la
        # prova diventa rossa a ogni classe aggiunta, che e' il modo piu'
        # rapido di far ignorare una prova.
        for pezzo in ("class='cover-blocco", "class='cover-bollo'",
                      "class='cover-tonda'"):
            with self.subTest(pezzo=pezzo):
                self.assertIn(pezzo, html)

    def test_il_bollo_dice_i_giorni_veri(self):
        html = _documento(giorni=7)
        blocco = html.split("class='cover-bollo'>", 1)[1][:300]
        self.assertIn("7", blocco)
        self.assertIn("giorni", blocco)

    def test_senza_durata_il_bollo_non_esce_vuoto(self):
        # Un cerchio di colore con dentro il nulla e' peggio di nessun cerchio.
        from src.pdf_renderer import render_html

        itinerario, viaggio, kwargs = _pezzi()
        viaggio = dict(viaggio)
        viaggio.pop("duration_days", None)
        self.assertNotIn("class='cover-bollo'",
                         render_html(itinerario, viaggio, **kwargs))

    def test_la_durata_non_e_scritta_due_volte(self):
        html = _documento(giorni=5)
        copertina = html.split("class='cover-facts'", 1)[0]
        self.assertNotIn("Quanto dura", copertina)


class TestLaFiguraTondaETONDA(unittest.TestCase):
    """Il difetto misurato il 13 agosto: gli angoli arrotondati applicati a
    un'immagine, con questo motore, danno mezza tonda e mezza quadrata."""

    def test_il_ritaglio_si_fa_sui_pixel_non_col_foglio_di_stile(self):
        from src.pdf_renderer import _CSS

        pezzo = _CSS.split(".cover-tonda img {", 1)[1].split("}", 1)[0]
        self.assertNotIn("border-radius", pezzo,
                         "la figura tonda non si ottiene arrotondando "
                         "l'immagine: viene mezza tonda e mezza quadrata")

    def test_il_bollo_invece_e_un_cerchio_vero(self):
        # Un riquadro di colore vuoto SI' che diventa tondo: quadrato, e
        # raggio pari a meta' del lato. E' l'unica forma tonda che questo
        # motore disegna davvero.
        from src.pdf_renderer import _CSS

        pezzo = _CSS.split(".cover-bollo {", 1)[1].split("}", 1)[0]
        misure = {nome: float(re.search(nome + r":\s*([\d.]+)px", pezzo).group(1))
                  for nome in ("width", "height", "border-radius")}
        self.assertEqual(misure["width"], misure["height"])
        self.assertAlmostEqual(misure["width"] / 2, misure["border-radius"],
                               places=1)


class TestLaCopertinaSTAINUNAPAGINA(unittest.TestCase):
    """[SOGLIA VERA, gia' sfondata due volte.]

    Si stampa e si conta. Un controllo sull'HTML non potrebbe vederlo: quante
    pagine occupi la copertina lo decide il motore di stampa, non il codice.
    """

    @classmethod
    def setUpClass(cls):
        if not shutil.which("wkhtmltopdf") or not shutil.which("pdftoppm"):
            raise unittest.SkipTest("servono wkhtmltopdf e pdftoppm")

    def _prima_pagina_dopo_la_copertina(self, giorni):
        from src.pdf_renderer import render_pdf

        itinerario, viaggio, kwargs = _pezzi(giorni)
        percorso = str(Path(tempfile.mkdtemp(prefix="copertina-")) / "c.pdf")
        render_pdf(itinerario, viaggio, output_path=percorso, **kwargs)
        try:
            import pypdf
        except ImportError:  # pragma: no cover
            self.skipTest("serve pypdf")
        lettore = pypdf.PdfReader(percorso)
        return (lettore.pages[1].extract_text() or "")

    def test_la_seconda_pagina_non_e_la_coda_della_copertina(self):
        # Il difetto vero non e' «la copertina e' lunga»: e' che la seconda
        # pagina comincia con due righe di copertina e poi resta bianca.
        for giorni in (2, 5, 9):
            with self.subTest(giorni=giorni):
                seconda = self._prima_pagina_dopo_la_copertina(giorni)
                self.assertNotIn("Cosa troverai dentro", seconda,
                                 "l'indice della copertina e' finito sulla "
                                 "seconda pagina")


if __name__ == "__main__":
    unittest.main()
