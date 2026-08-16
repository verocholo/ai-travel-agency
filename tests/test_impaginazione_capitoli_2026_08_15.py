"""Nessun capitolo comincia in fondo al foglio (task #221).

PERCHE' QUESTO FILE ESISTE

Lorenzo, 15 agosto 2026: «ti sei perso l'impaginazione pero', non e' come
avevamo concordato si spezzano i capitoli. cerca di fare terminare i capitoli
a fine pagina».

Misurando il documento vero, due capitoli su undici cominciavano a **trenta** e
a **settantasette punti** dal bordo inferiore: la testata colorata appiccicata
al fondo pagina e il contenuto sul foglio dopo. Non e' un capitolo lungo che
occupa due pagine — quello lo fa qualunque libro — e' un titolo che sembra un
errore di stampa.

## Perche' NON si mandano a capo tutti i capitoli

Perche' e' gia' stato provato su questo prodotto ed e' costato sette pagine
con il quaranta per cento di bianco (sta nello standard di qualita',
misurato). E perche' lo stesso Lorenzo, l'11 agosto, aveva segnalato l'altra
faccia della stessa medaglia: «non voglio una pagina iniziata per due righe e
poi lasciata bianca».

Quindi si stampa, si guarda dove sono cadute le testate, si mandano a capo
**solo quelle** cadute in fondo, e si ristampa. Le prove qui sotto difendono
tutte e due i lati: che le testate basse spariscano, e che il documento non
diventi piu' lungo per ripararle.
"""

import io
import subprocess
import tempfile
import shutil
import unittest
from pathlib import Path


def _pezzi():
    import scripts_sample_pdf
    from PIL import Image, ImageDraw

    def _foto():
        immagine = Image.new("RGB", (1400, 900), (150, 90, 60))
        disegno = ImageDraw.Draw(immagine)
        for x in range(0, 1400, 70):
            disegno.rectangle([x, 0, x + 30, 900], fill=(90, 50, 35))
        fuori = io.BytesIO()
        immagine.save(fuori, format="JPEG", quality=85)
        return fuori.getvalue()

    itinerario, viaggio, kwargs, _ = scripts_sample_pdf.build_sample_render_kwargs()
    identificativi = [b.get("poi_id")
                      for g in itinerario["days"] for b in (g.get("blocks") or [])
                      if isinstance(b, dict) and b.get("poi_id")]
    kwargs = dict(kwargs)
    kwargs.pop("output_path", None)
    kwargs["photos"] = {i: {"png": _foto(), "credito": "Prova / Test",
                            "reale": True} for i in identificativi}
    return itinerario, viaggio, kwargs


def _stampa(a_capo=()):
    from src.pdf_renderer import COMANDO_STAMPA, render_html

    itinerario, viaggio, kwargs = _pezzi()
    html = render_html(itinerario, viaggio, capitoli_a_capo=a_capo, **kwargs)
    percorso_html = tempfile.mktemp(suffix=".html")
    Path(percorso_html).write_text(html, encoding="utf-8")
    percorso_pdf = tempfile.mktemp(suffix=".pdf")
    subprocess.run([*COMANDO_STAMPA, percorso_html, percorso_pdf],
                   check=True, capture_output=True, timeout=120)
    return Path(percorso_pdf)


class TestSulDocumentoVEROSTAMPATO(unittest.TestCase):
    """La prova che conta: dove cadono le testate lo dice solo la carta."""

    @classmethod
    def setUpClass(cls):
        if not shutil.which("wkhtmltopdf"):
            raise unittest.SkipTest("serve wkhtmltopdf")

    def _basse(self, dati):
        from src import impaginazione
        from src.pdf_renderer import CAPITOLI_DEL_DOCUMENTO

        soglia = impaginazione.ALTEZZA_A4_PT * impaginazione.QUOTA_MINIMA_SOTTO
        return {nome: round(altezza)
                for nome, (_pagina, altezza) in impaginazione.posizioni(dati).items()
                if nome in CAPITOLI_DEL_DOCUMENTO and altezza < soglia}

    def test_la_seconda_stampa_toglie_le_testate_dal_fondo_pagina(self):
        from src import impaginazione
        from src.pdf_renderer import CAPITOLI_DEL_DOCUMENTO

        prima = _stampa().read_bytes()
        # Se la prima stampa fosse gia' perfetta questa prova non misurerebbe
        # niente e diventerebbe verde per il motivo sbagliato.
        self.assertTrue(self._basse(prima),
                        "la prova non misura niente: nessuna testata cade in "
                        "fondo nemmeno alla prima stampa")
        da_spostare = impaginazione.capitoli_da_mandare_a_capo(
            prima, CAPITOLI_DEL_DOCUMENTO)
        dopo = _stampa(da_spostare).read_bytes()
        self.assertEqual({}, self._basse(dopo))

    def test_ripararle_non_allunga_il_documento(self):
        """[L'ALTRA META', E VALE QUANTO LA PRIMA.]

        Mandare a capo i capitoli e' facile; farlo senza riempire il documento
        di pagine mezze vuote e' il punto. Se un domani qualcuno allargasse la
        regola a tutti i capitoli, questo diventerebbe rosso.
        """
        import scripts_qualita_pagina as q
        from src import impaginazione
        from src.pdf_renderer import CAPITOLI_DEL_DOCUMENTO

        prima = _stampa()
        da_spostare = impaginazione.capitoli_da_mandare_a_capo(
            prima.read_bytes(), CAPITOLI_DEL_DOCUMENTO)
        dopo = _stampa(da_spostare)
        self.assertLessEqual(len(q.misura(str(dopo))),
                             len(q.misura(str(prima))) + 1)
        self.assertEqual([], q.problemi(str(dopo), dopo.read_bytes()))


class TestLaREGOLAEUNAMINORANZA(unittest.TestCase):

    def _con_posizioni(self, finte):
        """Sostituisce la lettura del PDF, e la RIMETTE a posto.

        [SCRITTO DOPO AVERCI SBATTUTO LA TESTA.] La prima versione faceva
        `del` sulla funzione sostituita: cosi' non si torna all'originale, la
        si CANCELLA dal modulo — e le quattro prove successive sono morte con
        un errore che non c'entrava niente con quello che stavano provando.
        """
        from unittest.mock import patch

        from src import impaginazione

        return patch.object(impaginazione, "posizioni",
                            lambda _dati: finte)

    def test_il_primo_capitolo_non_si_manda_mai_a_capo(self):
        # Sta subito sotto la copertina: spostarlo vorrebbe dire aprire il
        # documento con una pagina bianca.
        from src import impaginazione

        with self._con_posizioni({"colpo-docchio": (1, 10.0),
                                  "costi": (3, 10.0)}):
            self.assertEqual({"costi"}, impaginazione.capitoli_da_mandare_a_capo(
                b"finto", ["colpo-docchio", "costi"]))

    def test_un_capitolo_a_meta_pagina_resta_dov_e(self):
        from src import impaginazione

        with self._con_posizioni({"a": (1, 800.0), "b": (2, 500.0)}):
            self.assertEqual(set(), impaginazione.capitoli_da_mandare_a_capo(
                b"finto", ["a", "b"]))


class TestNONFACADERENIENTE(unittest.TestCase):
    """Una diagnosi che fa cadere il programma proprio quando serve e' una
    diagnosi che manca."""

    def test_byte_che_non_sono_un_pdf(self):
        from src import impaginazione

        self.assertEqual({}, impaginazione.posizioni(b"non un pdf"))
        self.assertEqual(set(), impaginazione.capitoli_da_mandare_a_capo(
            b"non un pdf", ["costi"]))

    def test_senza_sonde_non_si_sposta_niente(self):
        from src import impaginazione

        self.assertEqual(set(),
                         impaginazione.capitoli_da_mandare_a_capo(b"", []))


if __name__ == "__main__":
    unittest.main()
