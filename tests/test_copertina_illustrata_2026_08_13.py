"""La copertina ha una fotografia e resta di UNA pagina (task #209).

PERCHE' QUESTO FILE ESISTE

Lorenzo, 13 agosto 2026: «per l'estetica vorrei un qualcosa di piu' colorato e
accattivante [...] e poi mi piacerebbe che l'estetica si adattasse al posto in
cui il cliente vuole andare».

La copertina era l'unica pagina del documento senza una sola immagine: il
cliente pagava, apriva, e trovava del testo.

## Il difetto che questa aggiunta ha subito prodotto

Appena la fascia fotografica e' comparsa in cima, la copertina del campione ha
sfondato sulla seconda pagina, lasciandola bianca per nove decimi. Cioe'
esattamente la cosa che Lorenzo aveva segnalato l'11 agosto:

    «non voglio che ci sia una pagina iniziata per due righe e poi lasciata
    bianca»

riparata allora, e ricomparsa oggi da un'altra porta.

## Perche' nessun controllo se n'era accorto

C'era gia' `test_nessuna_pagina_si_ferma_a_meta_foglio`, che e' proprio il
controllo giusto — ma gira sul campione **senza fotografie**, perche' in
questo ambiente non c'e' rete e le immagini vere non arrivano. Con la
copertina spoglia il difetto non esisteva.

E' la solita forma: il controllo era corretto, e cieco sul caso che conta. Qui
si toglie la cecita' costruendo le fotografie in casa, con Pillow, invece di
aspettarle dalla rete.

## Cosa difende

Che la copertina illustrata stia in UNA pagina, e che il documento non perda
il colore del posto per strada.
"""

import io
import unittest


def _foto(rgb, larghezza=900, altezza=600) -> bytes:
    """Una fotografia finta ma vera come byte: nessuna rete, nessun costo."""
    from PIL import Image, ImageDraw

    immagine = Image.new("RGB", (larghezza, altezza), rgb)
    disegno = ImageDraw.Draw(immagine)
    # Qualche banda piu' scura: senza, l'immagine e' una tinta piatta e la
    # scelta della tavolozza risulterebbe piu' facile di quanto sia davvero.
    for x in range(0, larghezza, 60):
        disegno.rectangle([x, 0, x + 30, altezza],
                          fill=tuple(max(0, c - 28) for c in rgb))
    fuori = io.BytesIO()
    immagine.save(fuori, format="JPEG", quality=85)
    return fuori.getvalue()


def _campione_illustrato(rgb=(168, 74, 38)):
    import scripts_sample_pdf

    itinerary, trip, kwargs, errori = scripts_sample_pdf.build_sample_render_kwargs()
    assert not errori, f"il campione monta con sezioni cadute: {errori}"
    identificativi = [
        b.get("poi_id")
        for g in itinerary["days"] for b in (g.get("blocks") or [])
        if isinstance(b, dict) and b.get("poi_id")
    ]
    kwargs = dict(kwargs)
    kwargs["photos"] = {
        i: {"png": _foto(rgb), "credito": "Prova / Test", "reale": True}
        for i in identificativi
    }
    return itinerary, trip, kwargs


class TestLaCopertinaHaUnaFotografia(unittest.TestCase):

    def setUp(self):
        from src.pdf_renderer import render_html

        itinerary, trip, kwargs = _campione_illustrato()
        completo = render_html(itinerary, trip, **kwargs)
        # SOLO il corpo. Cercare «cover-foto» nel documento intero trova
        # prima la REGOLA nel foglio di stile, e i confronti di posizione
        # finiscono per misurare l'ordine delle regole CSS invece
        # dell'ordine degli elementi in pagina. Ci sono cascato scrivendo
        # questo file: il rosso sembrava dire che la fotografia stava sotto
        # al titolo, e invece stava sopra da sempre.
        self.html = completo.split("<body>", 1)[1]

    def test_la_fascia_c_e(self):
        self.assertIn("<div class='cover-foto'>", self.html,
                      "la copertina e' tornata senza immagini")

    def test_la_fotografia_sta_prima_del_titolo(self):
        # Sotto il titolo sarebbe un'illustrazione qualunque; sopra e'
        # un'apertura. La differenza si vede in mezzo secondo.
        self.assertLess(self.html.find("cover-foto"), self.html.find("cover-title"))

    def test_porta_il_suo_credito(self):
        # Regola di tutto il progetto: nessuna immagine senza chi l'ha fatta.
        fascia = self.html.split("<div class='cover-foto'>", 1)[1].split("</div>", 1)[0]
        self.assertIn("<img", fascia)
        self.assertIn("Foto: Prova / Test", self.html[:self.html.find("cover-hero")])

    def test_senza_fotografie_la_copertina_resta_quella_di_ieri(self):
        """Il ripiego non deve essere una cosa nuova.

        Un documento senza immagini (nessuna chiave Google, o rete assente in
        generazione) deve uscire ESATTAMENTE come usciva prima, non peggio.
        """
        import scripts_sample_pdf
        from src.pdf_renderer import render_html

        itinerary, trip, kwargs, _ = scripts_sample_pdf.build_sample_render_kwargs()
        self.assertNotIn("<div class='cover-foto'>",
                         render_html(itinerary, trip, **kwargs))


class TestLaCopertinaIllustrataStaInUNAPagina(unittest.TestCase):
    """Il difetto vero di questo giro, e l'unico modo di vederlo: stampare.

    [VISTO FALLIRE, 2026-08-13.] Con la fascia a 2,6 di rapporto e le soglie
    di respiro di prima, questo controllo era rosso: la copertina finiva a
    pagina 2 e la seconda pagina restava bianca per nove decimi.
    """

    @classmethod
    def setUpClass(cls):
        import shutil
        import tempfile
        from pathlib import Path

        if shutil.which("wkhtmltopdf") is None:
            raise unittest.SkipTest("serve wkhtmltopdf per guardare le pagine")
        from src.pdf_renderer import render_pdf

        itinerary, trip, kwargs = _campione_illustrato()
        percorso = Path(tempfile.mkdtemp(prefix="copertina-")) / "campione.pdf"
        render_pdf(itinerary, trip, output_path=str(percorso), **kwargs)
        cls.pdf = percorso.read_bytes()

    def _testo_pagina(self, indice: int) -> str:
        """Il testo di una pagina, con gli spazi normali.

        `extract_text()` restituisce TABULAZIONI al posto degli spazi fra le
        parole: cercare «Itinerario Ottimizzato» non trova niente anche
        quando c'e', scritto a caratteri di scatola. Ci sono cascato
        scrivendo questo file, e il rosso sembrava un difetto del prodotto.
        """
        import re

        try:
            import pypdf
        except ImportError:
            self.skipTest("serve pypdf per leggere le pagine")
        grezzo = pypdf.PdfReader(io.BytesIO(self.pdf)).pages[indice].extract_text() or ""
        return re.sub(r"\s+", " ", grezzo)

    def test_la_copertina_non_sborda_sul_foglio_dopo(self):
        """La seconda pagina deve essere il DOCUMENTO, non la coda della
        copertina.

        Si riconosce dalla fascia di testata, che apre il contenuto vero. Se
        a pagina 2 c'e' ancora roba di copertina, vuol dire che la prima ha
        sfondato — e il cliente si trova un foglio quasi bianco al posto
        numero due, che e' la posizione peggiore possibile.
        """
        seconda = self._testo_pagina(1)
        self.assertIn(
            "Itinerario Ottimizzato", seconda,
            "la seconda pagina non comincia col documento: la copertina ha "
            "sfondato e ha lasciato un foglio quasi bianco")

    def test_la_copertina_dice_gia_tutto_quello_che_deve(self):
        # Se per farla stare in una pagina qualcuno domani togliesse
        # l'indice, il controllo qui sopra resterebbe verde e la copertina
        # avrebbe perso il suo lavoro.
        prima = self._testo_pagina(0)
        for atteso in ("Itinerario su misura", "Cosa troverai dentro",
                       "Budget indicato", "Come si legge"):
            with self.subTest(atteso=atteso):
                self.assertIn(atteso.lower(), prima.lower())


class TestIlColoreDelPostoArrivaFinoAlDocumento(unittest.TestCase):
    """Le prove di `test_tavolozza` verificano che la SCELTA sia giusta.

    Questa verifica una cosa diversa e piu' fragile: che il colore scelto
    arrivi davvero nel foglio di stile del documento stampato. E' la
    differenza fra una funzione corretta e una funzione chiamata — e in
    questo progetto e' gia' costata una fila di fotografie scritta e mai
    attaccata alla pagina.
    """

    def _foglio(self, rgb) -> str:
        from src.pdf_renderer import render_html

        itinerary, trip, kwargs = _campione_illustrato(rgb)
        html = render_html(itinerary, trip, **kwargs)
        return html.split("<style>", 1)[1].split("</style>", 1)[0]

    def test_un_posto_di_mattoni_produce_un_documento_di_mattoni(self):
        from src import tavolozza

        cotto = tavolozza.per_nome("cotto")
        foglio = self._foglio((168, 74, 38))
        self.assertIn(cotto["scuro"], foglio)
        self.assertNotIn(tavolozza.per_nome("pietra")["scuro"], foglio)

    def test_un_posto_di_mare_produce_un_documento_di_mare(self):
        from src import tavolozza

        foglio = self._foglio((32, 132, 178))
        self.assertIn(tavolozza.per_nome("mare")["scuro"], foglio)

    def test_due_posti_diversi_non_danno_lo_stesso_documento(self):
        # E' tutta la richiesta di Lorenzo in una riga.
        self.assertNotEqual(self._foglio((168, 74, 38)), self._foglio((32, 132, 178)))

    def test_nessun_segnaposto_arriva_al_cliente(self):
        """Un `{{scuro}}` rimasto nel foglio non da' errore: il motore lo
        ignora e stampa un documento senza quel colore. Silenzioso, e a valle.
        """
        self.assertNotIn("{{", self._foglio((32, 132, 178)))


if __name__ == "__main__":
    unittest.main()
