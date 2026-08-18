"""La fotografia deve c'entrare con il luogo (task #224).

PERCHE' QUESTO FILE ESISTE

Lorenzo, 16 agosto, guardando il fascicolo di Bologna: «le foto sono messe a
caso senza alcun ordine (cosa c'entra il tortellino)».

Commons, cercando «Mercato delle Erbe Bologna», restituisce anche un piatto di
tortellini: la ricerca e' testuale e il nome della citta' basta a farli
comparire. Fino a oggi si prendeva **la prima immagine utilizzabile**, cioe' si
tirava a sorte fra i risultati.

Contare le parole in comune fra il titolo della fotografia e il nome del luogo
non e' intelligenza artificiale, ed e' esattamente quello che serve. Con zero
parole in comune non si stampa: meglio una scheda senza fotografia che una
scheda con la fotografia di un'altra cosa.
"""

import unittest


def _pagina(titolo, licenza="CC BY-SA 4.0"):
    return {
        "title": titolo,
        "imageinfo": [{
            "thumburl": "https://esempio.invalid/" + titolo,
            "extmetadata": {"LicenseShortName": {"value": licenza},
                            "Artist": {"value": "Autore"}},
        }],
    }


class TestIlTortellinoNONPASSA(unittest.TestCase):

    def test_zero_parole_in_comune_zero_fotografia(self):
        from src.wikimedia import _prima_utilizzabile

        scelta = _prima_utilizzabile(
            [_pagina("File:Tortellini bolognesi.jpg")], "Mercato delle Erbe")
        self.assertIsNone(scelta)

    def test_fra_due_candidati_vince_quello_che_nomina_il_luogo(self):
        from src.wikimedia import _prima_utilizzabile

        scelta = _prima_utilizzabile(
            [_pagina("File:Tortellini bolognesi.jpg"),
             _pagina("File:Mercato delle Erbe Bologna 01.jpg")],
            "Mercato delle Erbe")
        self.assertIn("Mercato", scelta["titolo"])

    def test_le_parole_di_servizio_non_fanno_attinenza(self):
        # «di», «della», «Italia», «photo» compaiono in mezza Commons: se
        # contassero, qualunque immagine risulterebbe attinente e il filtro
        # non filtrerebbe niente.
        from src.wikimedia import attinenza

        self.assertEqual(0, attinenza("File:Photo of Italy.jpg",
                                      "Basilica di San Domenico"))

    def test_senza_nome_si_comporta_come_prima(self):
        # Il filtro non deve rompere i punti che non passano un nome.
        from src.wikimedia import _prima_utilizzabile

        scelta = _prima_utilizzabile([_pagina("File:Qualunque cosa.jpg")])
        self.assertIsNotNone(scelta)

    def test_la_licenza_resta_la_regola_piu_forte(self):
        # Attinente ma non ridistribuibile: non si stampa lo stesso. La
        # licenza viene prima di tutto, anche dell'estetica.
        from src.wikimedia import _prima_utilizzabile

        scelta = _prima_utilizzabile(
            [_pagina("File:Mercato delle Erbe Bologna.jpg", "Tutti i diritti riservati")],
            "Mercato delle Erbe")
        self.assertIsNone(scelta)


class TestLaSceltaEPIUAMPIA(unittest.TestCase):

    def test_si_chiedono_piu_candidati_di_prima(self):
        # Con la scelta per attinenza, piu' candidati vuol dire piu'
        # probabilita' che ce ne sia uno che nomina davvero il luogo. Costa
        # zero: e' la stessa singola richiesta.
        import inspect

        from src import wikimedia

        # [SPOSTATA 2026-08-18] La richiesta a Commons sta in
        # `cerca_immagini` (plurale): `cerca_immagine` e' diventata la
        # scorciatoia che ne chiede una sola. Il numero di candidati e'
        # sempre lo stesso — e' la stessa singola richiesta — ma va letto
        # dove la richiesta si scrive davvero.
        sorgente = inspect.getsource(wikimedia.cerca_immagini)
        numero = int(sorgente.split('"gsrlimit": "', 1)[1].split('"', 1)[0])
        self.assertGreaterEqual(numero, 20)


if __name__ == "__main__":
    unittest.main()
