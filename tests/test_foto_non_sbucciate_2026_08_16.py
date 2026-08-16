"""Una fotografia non si sbuccia per farla stare in una fascia (task #222).

PERCHE' QUESTO FILE ESISTE

Lorenzo, 16 agosto, guardando pagina 6 del fascicolo di Bologna: «le foto sono
stretchate».

Non erano stirate — nessun pixel era stato deformato — erano **sbucciate**. Le
due torri di Bologna sono una fotografia verticale, alta e stretta; il
programma le chiedeva un rapporto da fascia panoramica e il ritaglio le
toglieva l'ottanta per cento dell'altezza. Quello che restava era una striscia
di mattoni in cui non si riconosceva piu' niente, e sulla pagina si legge
esattamente come un'immagine deformata.

E' la stessa regola di tutto il prodotto applicata alle immagini: meglio una
cosa vera e meno bella di una bella e falsa.
"""

import io
import unittest


def _foto(larghezza, altezza):
    from PIL import Image

    fuori = io.BytesIO()
    Image.new("RGB", (larghezza, altezza), (150, 90, 60)).save(
        fuori, format="JPEG", quality=85)
    return fuori.getvalue()


def _misura(dati):
    from PIL import Image

    with Image.open(io.BytesIO(dati)) as immagine:
        return immagine.size


class TestIlTagliaHaUnTetto(unittest.TestCase):

    def test_una_foto_verticale_non_diventa_una_striscia(self):
        from src import foto

        # Le due torri: 600 x 1400. Chiedendo una fascia da 3.1 servirebbe
        # un'altezza di 193 pixel, cioe' il 14% dell'originale.
        _larghezza, altezza = _misura(
            foto.ritaglia_panoramica(_foto(600, 1400), 3.1))
        self.assertGreaterEqual(
            altezza / 1400, 1.0 - foto.TAGLIO_MASSIMO - 0.01,
            "la fotografia verticale e' stata sbucciata: e' il difetto che "
            "Lorenzo ha chiamato «stretchate»")

    def test_una_foto_orizzontale_si_ritaglia_come_sempre(self):
        """[CORREZIONE DELLA PRIMA VERSIONE, presa da una prova gia' scritta.]

        Il tetto vale solo per le fotografie VERTICALI. Applicato a tutte
        cambiava la fascia della copertina e le bande delle giornate, tarate
        su fotografie orizzontali che quel taglio lo reggono: 1200x900 ridotta
        a 1200x400 resta una fascia leggibile, 600x1400 ridotta a 600x193 e'
        una striscia di mattoni. Non conta quanto si toglie, conta cosa resta.
        """
        from src import foto

        larghezza, altezza = _misura(
            foto.ritaglia_panoramica(_foto(1200, 900), 3.0))
        self.assertEqual(1200, larghezza)
        self.assertAlmostEqual(400, altezza, delta=4)

    def test_non_si_aggiungono_pixel_che_non_esistono(self):
        # Una foto gia' piu' panoramica del rapporto chiesto resta com'e':
        # allargarla vorrebbe dire inventare quello che non c'e'.
        from src import foto

        self.assertEqual((1600, 400),
                         _misura(foto.ritaglia_panoramica(_foto(1600, 400), 2.6)))

    def test_il_tetto_e_un_numero_scritto_e_ragionevole(self):
        # Se un domani qualcuno lo alzasse a 0.9 per «far stare meglio una
        # fascia», il difetto tornerebbe identico e senza errori.
        from src import foto

        self.assertLessEqual(foto.TAGLIO_MASSIMO, 0.5)
        self.assertGreater(foto.TAGLIO_MASSIMO, 0.2)


if __name__ == "__main__":
    unittest.main()
