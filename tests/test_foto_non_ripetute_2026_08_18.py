"""La stessa fotografia non esce due volte (task #230).

PERCHE' QUESTO FILE ESISTE

Lorenzo, sul fascicolo di Bologna vero, guardandolo da cliente: «la scelta
delle foto e' troppo limitata hai ripetuto le stesse 3 foto».

Misurato su quel PDF, contando le impronte dei byte: **quattordici immagini
stampate, dieci diverse**. La fotografia delle Due Torri usciva TRE volte
identica — la fascia di copertina, la striscia del Giorno 1, e a tutta pagina
in apertura di scheda — e quella di Piazza Maggiore due.

## La causa, che non era dove sembrava

Non era la scelta di un singolo punto del documento: era che **nessun punto
sapeva cosa avessero gia' stampato gli altri**. Copertina, aperture di
giornata, file di chiusura e schede ripartivano tutte da `photos` grezzo e
riprendevano, ognuna per conto suo, la prima fotografia di ogni luogo.

Due riparazioni, e servono tutte e due:

  1. **la scorta** — `wikimedia.cerca_immagini` tiene fino a tre delle
     ventiquattro candidate che gia' arrivavano (prima se ne teneva una e se
     ne buttavano ventitre'), e `foto.raccogli_foto` le mette in `scatti`;
  2. **il registro** — un insieme di impronte, uno per documento, che ogni
     punto consulta prima di stampare.

## La riga che tiene in piedi il tutto

Quando la scorta finisce, si ripete invece di lasciare la pagina vuota. Non
e' una resa: la regola presa alla lettera, su un viaggio con quattro luoghi e
una fotografia a testa, non produce un documento senza ripetizioni — produce
giornate senza fotografie, che e' peggio e che Lorenzo aveva gia' bocciato il
13 agosto («ogni giornata deve avere le foto»).
"""

import unittest

from src import pdf_renderer as R


def _scatto(nome, quante=1, reale=True):
    """Una voce di `photos` con una scorta di `quante` fotografie."""
    scatti = [{"png": f"jpeg-{nome}-{i}".encode(),
               "credito": f"Foto: {nome} / Prova"} for i in range(quante)]
    return {"png": scatti[0]["png"], "credito": scatti[0]["credito"],
            "reale": reale, "scatti": scatti if reale else []}


def _blocchi(*poi_ids):
    return [{"time": "10:00", "activity": f"Tappa {i}", "location": f"Luogo {i}",
             "poi_id": p} for i, p in enumerate(poi_ids, start=1)]


class TestLIMPRONTADIUNIMMAGINE(unittest.TestCase):
    """Si guarda l'immagine, non il luogo da cui viene."""

    def test_due_byte_uguali_hanno_la_stessa_impronta(self):
        self.assertEqual(R._impronta(b"identici"), R._impronta(b"identici"))

    def test_due_immagini_diverse_hanno_impronte_diverse(self):
        self.assertNotEqual(R._impronta(b"una"), R._impronta(b"altra"))

    def test_il_vuoto_non_ha_impronta(self):
        # Cosi' un'immagine mancante non "occupa" un posto nel registro
        # impedendo a quella vera di uscire.
        for niente in (b"", None, "non byte", 0):
            with self.subTest(valore=niente):
                self.assertEqual("", R._impronta(niente))

    def test_lo_stesso_file_da_due_luoghi_diversi_e_la_stessa_immagine(self):
        """Succede: Commons restituisce lo stesso scatto per due ricerche
        vicine. Contarlo per `poi_id` lo lascerebbe passare due volte, ed e'
        il motivo per cui il registro guarda i byte."""
        uno = {"png": b"stessa-foto", "credito": "c", "reale": True,
               "scatti": [{"png": b"stessa-foto", "credito": "c"}]}
        due = {"png": b"stessa-foto", "credito": "c", "reale": True,
               "scatti": [{"png": b"stessa-foto", "credito": "c"}]}
        usate = set()
        self.assertIsNotNone(R._scatto_non_ancora_usato(uno, usate))
        self.assertIsNone(R._scatto_non_ancora_usato(due, usate))


class TestLASCELTACONTROILREGISTRO(unittest.TestCase):

    def test_senza_registro_si_comporta_come_sempre(self):
        """La compatibilita' non e' un dettaglio: mezza dozzina di collaudi
        e tutto il codice piu' vecchio chiamano queste funzioni senza
        registro, e devono continuare a vedere lo stesso documento."""
        scatto = _scatto("a", quante=3)
        for _ in range(5):
            scelto = R._scatto_non_ancora_usato(scatto, None)
            self.assertEqual(b"jpeg-a-0", scelto["png"])

    def test_col_registro_ogni_chiamata_da_una_fotografia_nuova(self):
        scatto = _scatto("a", quante=3)
        usate = set()
        prese = [R._scatto_non_ancora_usato(scatto, usate) for _ in range(3)]
        self.assertEqual([b"jpeg-a-0", b"jpeg-a-1", b"jpeg-a-2"],
                         [p["png"] for p in prese])

    def test_finita_la_scorta_torna_niente(self):
        scatto = _scatto("a", quante=2)
        usate = set()
        R._scatto_non_ancora_usato(scatto, usate)
        R._scatto_non_ancora_usato(scatto, usate)
        self.assertIsNone(R._scatto_non_ancora_usato(scatto, usate))

    def test_una_fotografia_senza_credito_non_si_stampa(self):
        """Regola di licenza, non di estetica: Wikimedia e Google permettono
        di ridistribuire l'immagine dentro un documento venduto a una
        condizione sola, che autore e licenza siano scritti accanto."""
        scatto = {"png": b"x", "credito": "", "reale": True,
                  "scatti": [{"png": b"x", "credito": "   "},
                             {"png": b"y", "credito": "Foto: vera / Prova"}]}
        scelto = R._scatto_non_ancora_usato(scatto, set())
        self.assertEqual(b"y", scelto["png"])

    def test_una_voce_vecchia_senza_scorta_funziona_lo_stesso(self):
        # `photos` costruiti a mano nei collaudi non hanno `scatti`.
        vecchia = {"png": b"z", "credito": "Foto: z / Prova", "reale": True}
        self.assertEqual(b"z", R._scatto_non_ancora_usato(vecchia, set())["png"])


class TestLAGIORNATANONSISVUOTA(unittest.TestCase):
    """[LA PROVA PIU' IMPORTANTE DI QUESTO FILE.]

    La regola «mai due volte la stessa immagine» presa alla lettera fa
    sparire le fotografie invece delle ripetizioni. Qui si verifica che il
    ripiego ci sia, e che valga SOLO quando serve davvero.
    """

    def test_con_la_scorta_nessuna_giornata_ripete_niente(self):
        photos = {"A": _scatto("a", quante=2), "B": _scatto("b", quante=2)}
        usate = set()
        prima = R._foto_vere_della_giornata(_blocchi("A", "B"), photos, usate)
        dopo = R._foto_vere_della_giornata(_blocchi("A", "B"), photos, usate)
        tutte = [s["png"] for _p, s, _n in prima + dopo]
        self.assertEqual(len(tutte), len(set(tutte)), f"immagini ripetute: {tutte}")

    def test_senza_scorta_la_giornata_ha_comunque_le_sue_fotografie(self):
        photos = {"A": _scatto("a"), "B": _scatto("b")}
        usate = {R._impronta(b"jpeg-a-0"), R._impronta(b"jpeg-b-0")}
        lista = R._foto_vere_della_giornata(_blocchi("A", "B"), photos, usate)
        self.assertEqual(2, len(lista),
                         "con la scorta finita la giornata resta senza "
                         "fotografie: e' peggio di una ripetizione")

    def test_la_riserva_e_una_seconda_fotografia_dello_stesso_luogo(self):
        photos = {"A": _scatto("a", quante=2)}
        usate = set()
        R._foto_vere_della_giornata(_blocchi("A"), photos, usate)
        riserva = R._scorta_della_giornata(_blocchi("A"), photos, usate)
        self.assertEqual([b"jpeg-a-1"], [s["png"] for _p, s, _n in riserva])

    def test_senza_registro_non_esiste_nessuna_riserva(self):
        # Senza sapere cosa e' gia' uscito, la riserva ristamperebbe le
        # stesse immagini: e' il difetto da cui nasce tutta questa storia.
        photos = {"A": _scatto("a", quante=3)}
        self.assertEqual([], R._scorta_della_giornata(_blocchi("A"), photos, None))


class TestSULDOCUMENTOINTERO(unittest.TestCase):
    """[SOGLIA VERA.] Le prove qui sopra difendono i pezzi. Questa conta le
    immagini stampate nel documento, che e' cio' che Lorenzo ha contato."""

    def _documento(self, quante_per_luogo):
        itinerario = {
            "destination": "Bologna",
            "executive_summary": "Due giorni.",
            "days": [
                {"day": 1, "title": "Centro", "blocks": _blocchi("A", "B", "C")},
                {"day": 2, "title": "Fuori", "blocks": _blocchi("D", "E")},
            ],
        }
        photos = {k: _scatto(k.lower(), quante=quante_per_luogo)
                  for k in "ABCDE"}
        return R.render_html(
            itinerario,
            {"destination": "Bologna", "date_start": "2026-09-12",
             "date_end": "2026-09-14", "duration_days": 2, "budget_eur": 600},
            hotels=[{"name": "Hotel", "price_night_eur": 100}],
            photos=photos)

    def _impronte_stampate(self, html):
        import re

        # Il contenuto INTERO, non i primi caratteri: due immagini diverse
        # possono cominciare uguali, e una prova sulle ripetizioni che
        # confronta prefissi troverebbe doppioni che non esistono.
        return re.findall(r"<img src='data:[^;]+;base64,([^']+)'", html)

    def test_con_la_scorta_ogni_immagine_esce_una_volta_sola(self):
        stampate = self._impronte_stampate(self._documento(3))
        self.assertGreaterEqual(len(stampate), 4,
                                "il documento non stampa abbastanza immagini "
                                "perche' questa prova significhi qualcosa")
        doppie = len(stampate) - len(set(stampate))
        self.assertEqual(0, doppie,
                         f"{doppie} immagini stampate due volte: e' il "
                         "difetto «hai ripetuto le stesse 3 foto»")

    def test_la_scorta_larga_porta_piu_immagini_diverse(self):
        """Il punto della raccolta plurale: non «piu' foto», **piu' foto
        DIVERSE**. Con una sola per luogo il documento e' costretto a
        ripetersi; con tre non lo e' piu'."""
        magro = set(self._impronte_stampate(self._documento(1)))
        ricco = set(self._impronte_stampate(self._documento(3)))
        self.assertGreater(len(ricco), len(magro))


if __name__ == "__main__":
    unittest.main()
