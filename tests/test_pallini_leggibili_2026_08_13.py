"""I pallini della cartina si vedono (task #204).

PERCHE' QUESTO FILE ESISTE

Lorenzo, sul documento vero: «la cartina dovrebbe essere ancora migliorata,
soprattutto i pallini sono poco chiari».

Il problema non era la dimensione: era il **contrasto**. Questi pallini si
appoggiano su una cartina stradale vera, gia' fitta di nomi di vie, insegne e
numeri civici. Un cerchietto piccolo con dentro una cifra piccola si perde nel
rumore di fondo, e il numero — che e' l'unica cosa che collega la cartina al
programma della giornata — diventa illeggibile proprio dove serve.

Tre cose insieme: il pallino piu' grande, l'anello bianco piu' largo, e un
filo scuro fra i due. L'anello bianco da solo non basta: su una cartina chiara
il bianco contro il bianco sparisce, e il pallino torna a sembrare una macchia
di colore appoggiata li'. Il filo scuro gli da' un bordo con qualunque sfondo.

## Perche' si MISURANO i pixel

Le costanti si possono controllare leggendo il codice, ed e' quello che fanno
le prime prove. Ma «si vede bene» non e' una costante: e' una proprieta'
dell'immagine disegnata. Le prove in fondo disegnano un pallino vero su tre
sfondi diversi — chiaro, scuro, verde come un parco — e contano i pixel
attorno: se un giorno l'anello o il filo sparissero, nessun numero nel codice
cambierebbe, ma quelle prove diventerebbero rosse.

Effetto collaterale voluto: le zone cliccabili sulla cartina si calcolano da
questo stesso raggio, quindi sono diventate anche piu' facili da centrare con
un dito.
"""

import unittest

from src import map_render


class TestLeMisureNonTornanoIndietro(unittest.TestCase):

    def test_il_pallino_e_piu_grande_di_com_era(self):
        # Era 9 * _SCALE e si perdeva sul fondo.
        self.assertGreaterEqual(map_render._PIN_RADIUS, 11 * map_render._SCALE)

    def test_l_alone_bianco_e_abbastanza_largo_da_staccarlo(self):
        # Era 1,5 punti: un filo di bianco che a stampa spariva.
        self.assertGreaterEqual(map_render._ALONE_PIN, 3 * map_render._SCALE)

    def test_il_numero_dentro_non_e_piu_piccolo_del_pallino(self):
        """Il numero e' l'unica cosa che lega la cartina al programma.

        Un pallino grande con dentro una cifra minuscola risolve meta'
        problema e lascia intatta quella che conta.
        """
        import inspect

        sorgente = inspect.getsource(map_render)
        self.assertIn("font_pin = _load_font(11 * _SCALE, bold=True)", sorgente)


class TestIlPallinoSiStaccaDAVVERODALLOSFONDO(unittest.TestCase):
    """Non si controlla una costante: si guarda l'immagine disegnata."""

    SFONDI = {
        "chiaro (strade)": (245, 243, 238),
        "scuro": (40, 40, 40),
        "verde (parco)": (200, 224, 190),
    }

    def _disegna(self, sfondo):
        from PIL import Image, ImageDraw

        lato = 120
        immagine = Image.new("RGB", (lato, lato), sfondo)
        disegno = ImageDraw.Draw(immagine)
        map_render._pin(disegno, lato / 2, lato / 2, (26, 59, 92), "1", None)
        return immagine

    def test_attorno_al_pallino_c_e_sempre_un_anello_bianco(self):
        centro = 60
        for nome, sfondo in self.SFONDI.items():
            with self.subTest(sfondo=nome):
                immagine = self._disegna(sfondo)
                raggio = map_render._PIN_RADIUS
                # Un punto poco fuori dal colore, dentro l'alone.
                px = immagine.getpixel((centro + raggio + 3, centro))
                self.assertEqual(
                    px, (255, 255, 255),
                    f"su fondo {nome} l'anello bianco non c'e': il pallino si "
                    "confonde con la cartina")

    def test_fra_l_anello_e_il_colore_c_e_un_filo_scuro(self):
        # E' la parte che salva il pallino sui fondi chiari, dove il bianco
        # contro il bianco non stacca niente.
        immagine = self._disegna(self.SFONDI["chiaro (strade)"])
        centro, raggio = 60, map_render._PIN_RADIUS
        colonna = [immagine.getpixel((centro + d, centro))
                   for d in range(raggio - 2, raggio + 3)]
        scuri = [p for p in colonna if sum(p) < 250]
        self.assertTrue(scuri, "nessun filo scuro attorno al colore del pallino")

    def test_il_centro_resta_del_colore_della_giornata(self):
        # Il contorno non deve mangiarsi il pallino: il colore dice a quale
        # giornata appartiene la tappa, ed e' informazione.
        immagine = self._disegna(self.SFONDI["chiaro (strade)"])
        self.assertEqual(immagine.getpixel((60, 60)), (26, 59, 92))


if __name__ == "__main__":
    unittest.main()
