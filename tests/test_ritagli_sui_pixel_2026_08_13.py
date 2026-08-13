"""Cio' che il CSS non sa fare si fa sui pixel (task #213).

PERCHE' QUESTO FILE ESISTE

Il motore di stampa di questo progetto e' un Qt WebKit del 2014. Tre cose che
in un browser sono una riga di CSS, qui non funzionano — e non funzionano **in
silenzio**, che e' la parte pericolosa: l'anteprima e' perfetta e il PDF
venduto e' sbagliato.

    ritaglio tondo      `border-radius` + `overflow: hidden`
                        → esce mezzo tondo e mezzo quadrato (MISURATO)
    sfumatura scura     `linear-gradient`  → ignorata
    trasparenza         `rgba()`, `opacity` → ignorate, e su una build hanno
                        pure fatto SPARIRE il testo (11 luglio, PC di Lorenzo)

Servono tutte e tre per il disegno nuovo: la fotografia tonda e' un ornamento
di pagina, e la sfumatura e' cio' che tiene leggibile un titolo bianco stampato
sopra una fotografia.

Quindi si fanno sui PIXEL, con Pillow, dove funzionano sempre e allo stesso
modo su qualunque binario. E' la stessa lezione gia' pagata con
`object-fit: cover` l'11 agosto: **la scorciatoia che sembra la soluzione non
esiste in questo motore.**

## Che cosa difendono i controlli qui sotto

Non che le immagini siano belle — quello si guarda. Difendono le due cose che
si romperebbero in silenzio: che il ritaglio non deformi (la lezione delle
foto stirate) e che un'immagine illeggibile non faccia cadere il documento.
"""

import io
import unittest

from src import foto


def _immagine(larghezza, altezza, colore=(30, 110, 150), formato="JPEG") -> bytes:
    from PIL import Image

    fuori = io.BytesIO()
    Image.new("RGB", (larghezza, altezza), colore).save(fuori, format=formato)
    return fuori.getvalue()


def _misura(dati):
    from PIL import Image

    with Image.open(io.BytesIO(dati)) as immagine:
        return immagine.size


class TestIlRitaglioTondo(unittest.TestCase):

    def test_esce_quadrato_perche_un_cerchio_sta_in_un_quadrato(self):
        letto = foto.ritaglia_tondo(_immagine(1200, 800), lato=300)
        self.assertEqual((300, 300), _misura(letto))

    def test_non_deforma_l_immagine_di_partenza(self):
        """La lezione dell'11 agosto, in un altro punto.

        Ridimensionare 1200x800 in un quadrato SENZA ritagliare prima
        schiaccerebbe la fotografia — una torre diventerebbe tozza. Qui si
        prende il quadrato centrale e poi si scala: le proporzioni di cio' che
        resta sono intatte.
        """
        from PIL import Image

        # Un'immagine con una banda verticale netta: se venisse schiacciata in
        # orizzontale, la banda cambierebbe larghezza in modo misurabile.
        base = Image.new("RGB", (800, 800), (255, 255, 255))
        for x in range(400, 500):
            for y in range(800):
                base.putpixel((x, y), (0, 0, 0))
        grezzo = io.BytesIO()
        base.save(grezzo, format="PNG")

        letto = foto.ritaglia_tondo(grezzo.getvalue(), lato=800)
        with Image.open(io.BytesIO(letto)) as uscita:
            riga = [uscita.getpixel((x, 400))[0] < 128 for x in range(800)]
        larghezza_banda = sum(riga)
        self.assertGreater(larghezza_banda, 80)
        self.assertLess(larghezza_banda, 120)

    def test_gli_angoli_sono_bianchi_e_il_centro_no(self):
        # E' il controllo che dice se il cerchio c'e' davvero. Senza, un
        # ritaglio quadrato passerebbe tutti gli altri.
        from PIL import Image

        letto = foto.ritaglia_tondo(_immagine(600, 600, (20, 90, 140)), lato=200)
        with Image.open(io.BytesIO(letto)) as uscita:
            self.assertEqual((255, 255, 255), uscita.getpixel((2, 2)))
            self.assertEqual((255, 255, 255), uscita.getpixel((197, 197)))
            self.assertNotEqual((255, 255, 255), uscita.getpixel((100, 100)))

    def test_prende_il_centro_e_non_l_angolo(self):
        """Nelle fotografie di viaggio il soggetto sta quasi sempre al centro:
        ritagliando dall'angolo si taglia via mezza torre."""
        from PIL import Image

        base = Image.new("RGB", (900, 300), (255, 255, 255))
        for x in range(430, 470):
            for y in range(300):
                base.putpixel((x, y), (200, 0, 0))
        grezzo = io.BytesIO()
        base.save(grezzo, format="PNG")

        letto = foto.ritaglia_tondo(grezzo.getvalue(), lato=200)
        with Image.open(io.BytesIO(letto)) as uscita:
            centro = uscita.getpixel((100, 100))
        self.assertGreater(centro[0], centro[1] + 40,
                           "il ritaglio non e' centrato: il soggetto e' sparito")

    def test_un_immagine_illeggibile_non_fa_cadere_niente(self):
        # Una fotografia rotta puo' costare la fotografia, mai il documento.
        for spazzatura in (b"non una immagine", b"", None, "stringa", 42):
            with self.subTest(caso=str(spazzatura)[:14]):
                self.assertIsNone(foto.ritaglia_tondo(spazzatura))


class TestLaSfumaturaCheTieneLeggibileIlTitolo(unittest.TestCase):
    """Un titolo bianco sopra una fotografia e' la mossa che fa sembrare il
    documento una rivista. Se la fotografia ha il fondo chiaro — un cielo, un
    muro, la neve — il titolo sparisce. E sparisce al cliente, non a noi: noi
    la proviamo su tre foto, lui ne riceve trenta."""

    def _luminosita_media(self, dati, dalla_riga, alla_riga):
        from PIL import Image

        with Image.open(io.BytesIO(dati)) as immagine:
            piena = immagine.convert("L")
            larghezza, _ = piena.size
            valori = [piena.getpixel((x, y))
                      for y in range(dalla_riga, alla_riga)
                      for x in range(0, larghezza, 20)]
        return sum(valori) / len(valori)

    def test_il_fondo_si_scurisce_davvero(self):
        chiara = _immagine(600, 400, (240, 240, 240))
        letto = foto.sfuma_in_basso(chiara)
        self.assertLess(self._luminosita_media(letto, 380, 400), 90,
                        "il fondo non si e' scurito: un titolo bianco qui sopra "
                        "sarebbe illeggibile")

    def test_la_cima_resta_intatta(self):
        # Scurire tutta l'immagine sarebbe piu' facile e sbagliato: la
        # fotografia serve a mostrare il posto, non a fare da sfondo.
        chiara = _immagine(600, 400, (240, 240, 240))
        letto = foto.sfuma_in_basso(chiara)
        self.assertGreater(self._luminosita_media(letto, 0, 20), 200)

    def test_e_una_sfumatura_non_una_fascia(self):
        """Una fascia scurita di colpo si riconosce come un rettangolo
        appoggiato sopra la foto: e' il contrario di premium."""
        chiara = _immagine(600, 400, (240, 240, 240))
        letto = foto.sfuma_in_basso(chiara)
        alto = self._luminosita_media(letto, 170, 190)
        mezzo = self._luminosita_media(letto, 290, 310)
        basso = self._luminosita_media(letto, 380, 400)
        self.assertGreater(alto, mezzo + 8, "non degrada: e' un gradino")
        self.assertGreater(mezzo, basso + 8, "non degrada: e' un gradino")

    def test_le_dimensioni_non_cambiano(self):
        self.assertEqual((600, 400), _misura(foto.sfuma_in_basso(_immagine(600, 400))))

    def test_un_immagine_illeggibile_non_fa_cadere_niente(self):
        for spazzatura in (b"non una immagine", b"", None, 42):
            with self.subTest(caso=str(spazzatura)[:14]):
                self.assertIsNone(foto.sfuma_in_basso(spazzatura))

    def test_valori_assurdi_non_fanno_cadere_niente(self):
        # Chi chiama passa numeri, e prima o poi ne passa uno sbagliato.
        for quota, forza in ((0, 0), (5, 5), (-1, -1), (1, 1)):
            with self.subTest(quota=quota, forza=forza):
                self.assertIsNotNone(
                    foto.sfuma_in_basso(_immagine(200, 200), quota, forza))


class TestIlPanoramaRestaQuelloDiPrima(unittest.TestCase):
    """`ritaglia_panoramica` e' gia' in produzione dalla copertina. Qui si
    verifica solo che i due ritagli nuovi non l'abbiano disturbata."""

    def test_taglia_in_altezza_e_lascia_la_larghezza(self):
        larghezza, altezza = _misura(foto.ritaglia_panoramica(_immagine(1200, 900), 3.0))
        self.assertEqual(1200, larghezza)
        self.assertAlmostEqual(400, altezza, delta=4)

    def test_una_foto_gia_panoramica_non_viene_allargata(self):
        # Allargarla vorrebbe dire aggiungere pixel che non esistono.
        _, altezza = _misura(foto.ritaglia_panoramica(_immagine(1200, 200), 3.0))
        self.assertEqual(200, altezza)


if __name__ == "__main__":
    unittest.main()
