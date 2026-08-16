"""Le due aperture a colonne (task #219).

PERCHE' QUESTO FILE ESISTE

Erano l'ultimo pezzo del prototipo approvato che il documento venduto non
aveva: le pagine in cui l'apertura si divide in colonne invece di impilarsi.

## Cosa e' entrato e cosa no, e perche' non e' una rinuncia

E' entrata la meta' prudente: a colonne va l'APERTURA della giornata, non la
giornata. Titolo, cartina, programma e legenda restano impilati esattamente
come prima — e con loro i sette controlli di impaginazione che li difendono.

La seconda meta' (il programma affiancato alla cartina) resta fuori di
proposito. Non perche' non si sappia fare: perche' ridisegna il pezzo che
tiene in piedi tutto il resto, e questa settimana ha gia' mostrato due volte
cosa succede a rimettere in gioco piu' garanzie insieme — una singola immagine
in piu' ha fatto sfondare una pagina.

## Cosa difendono i controlli qui sotto

Che le due aperture nuove arrivino DAVVERO nel documento (la trappola gia'
presa una volta: una funzione corretta e mai chiamata), e che quando le
fotografie non bastano ripieghino su un'apertura che esiste invece di
stampare una tabella mezza vuota.
"""

import re
import unittest

from tests.test_aperture_giornata_2026_08_13 import _documento


def _classi(html: str) -> list:
    return re.findall(r"class='(day-eroe|day-numerone|day-banda|day-larga)'", html)


class TestLeColonneArrivanoDAVVERONELDOCUMENTO(unittest.TestCase):

    def test_su_qualche_viaggio_compaiono_entrambe(self):
        viste = set()
        for destinazione in ("Siena", "Tokyo", "Oslo", "Lisbona", "Bergen",
                             "Palermo"):
            viste.update(_classi(_documento(giorni=6,
                                            destinazione=destinazione)))
        for attesa in ("day-eroe", "day-numerone"):
            with self.subTest(apertura=attesa):
                self.assertIn(attesa, viste,
                              "l'apertura e' stata scritta ma non arriva mai "
                              "sulla pagina")

    def test_le_colonne_sono_tabelle_e_non_riquadri_affiancati(self):
        # Con questo motore di stampa `float` e `flex` vengono ignorati in
        # silenzio: due riquadri affiancati escono uno SOTTO l'altro, e non lo
        # dice nessun errore. Le colonne si fanno con le tabelle.
        html = _documento(giorni=6, destinazione="Oslo")
        for classe in ("day-eroe", "day-numerone"):
            if f"class='{classe}'" not in html:
                continue
            with self.subTest(classe=classe):
                self.assertIn(f"<table class='{classe}'>", html)

    def test_con_una_sola_fotografia_non_esce_una_tabella_mezza_vuota(self):
        # `eroe-laterale` ne vuole due. Con una sola deve ripiegare su
        # un'apertura che esiste, non stampare una colonna vuota accanto a
        # una piena — che si legge come una figura che non e' stata stampata.
        from src import compositore

        for indice in range(1, 8):
            scelta = compositore.scegli_apertura("Prova", indice, 1)
            with self.subTest(indice=indice):
                self.assertNotEqual("eroe-laterale", scelta)
                self.assertNotEqual("mosaico", scelta)


class TestLaGIORNATASOTTONONECAMBIATA(unittest.TestCase):
    """[LA PROVA PIU' IMPORTANTE DI QUESTO FILE.]

    Il valore di queste due aperture sta tutto nel fatto che si fermano
    all'apertura. Se un domani qualcuno le estendesse alla giornata intera,
    questo diventerebbe rosso prima che il documento arrivi a un cliente.
    """

    def test_la_cartina_e_il_programma_restano_dove_erano(self):
        html = _documento(giorni=6, destinazione="Oslo")
        for pezzo in ("class='day-title'", "class='block'"):
            with self.subTest(pezzo=pezzo):
                self.assertIn(pezzo, html)
        # Nessuna apertura a colonne deve INGLOBARE il programma: se il
        # blocco orario finisse dentro la tabella dell'apertura, la giornata
        # sarebbe stata ridisegnata.
        for apertura in re.finditer(r"<table class='day-(?:eroe|numerone)'>(.*?)</table>",
                                    html, re.S):
            self.assertNotIn("class='block'", apertura.group(1))


if __name__ == "__main__":
    unittest.main()
