"""Piu' fotografie, negli spazi che restavano bianchi (task #203).

PERCHE' QUESTO FILE ESISTE

Lorenzo, sul documento vero: «ora non sono piu' storte ma inseriscine di piu',
soprattutto negli spazi bianchi; ad esempio a pagina 5 e 7 ce ne stanno almeno
3 in quello spazio».

C'era una fotografia per giornata, in apertura. Sotto il programma restava
mezza pagina bianca, e di sei luoghi visitati il cliente ne vedeva uno.

Adesso in chiusura di giornata c'e' una fila di due o tre fotografie. Le tre
scelte che la governano esistono tutte per lo stesso motivo — **che il
documento non peggiori quando i dati sono pochi**, che e' la condizione in cui
si trova piu' spesso:

  - **almeno due, mai una sola.** Una fotografia larga un terzo di pagina,
    sola in una riga da tre, non sembra una scelta: sembra un errore;
  - **niente doppioni.** La fotografia gia' usata in apertura non torna in
    fondo alla stessa pagina, e un luogo visitato due volte compare una volta;
  - **solo fotografie vere.** La grafica disegnata in casa resta fuori dal
    documento principale: li' un'immagine vale se mostra un posto che il
    cliente riconoscera', altrimenti e' un rettangolo colorato che occupa lo
    spazio del programma.

E il credito e' obbligatorio come ovunque: senza il nome di chi ha scattato la
foto, la foto non si stampa.
"""

import unittest

from src.pdf_renderer import _CSS, _render_striscia_foto


def _scatto(nome: str, reale: bool = True) -> dict:
    return {"png": b"\xff\xd8finto-jpeg-" + nome.encode(),
            "credito": f"Foto: {nome} / Prova", "reale": reale}


def _blocchi(*poi_ids) -> list:
    return [{"time": "10:00", "activity": f"Tappa {i}", "location": f"Luogo {i}",
             "poi_id": pid} for i, pid in enumerate(poi_ids, start=1)]


class TestLaFilaSiStampaQuandoServe(unittest.TestCase):

    def test_tre_luoghi_con_foto_danno_una_fila_da_tre(self):
        html = _render_striscia_foto(
            _blocchi("A", "B", "C"),
            {"A": _scatto("a"), "B": _scatto("b"), "C": _scatto("c")})
        self.assertIn("day-striscia", html)
        self.assertEqual(html.count("<img"), 3)

    def test_non_si_stampa_una_fila_di_una_foto_sola(self):
        """Il confine che tiene il documento credibile.

        Una fotografia sola in una riga pensata per tre non sembra una
        scelta: sembra che manchi qualcosa.
        """
        html = _render_striscia_foto(_blocchi("A", "B"), {"A": _scatto("a")})
        self.assertEqual(html, "")

    def test_la_foto_gia_usata_in_apertura_non_si_ripete(self):
        # Stampare due volte la stessa immagine nella stessa pagina e' il modo
        # piu' rapido di far sembrare automatico un documento fatto su misura.
        html = _render_striscia_foto(
            _blocchi("A", "B", "C"),
            {"A": _scatto("a"), "B": _scatto("b"), "C": _scatto("c")},
            gia_usata="A")
        self.assertEqual(html.count("<img"), 2)
        self.assertNotIn("Foto: a /", html)

    def test_un_luogo_visitato_due_volte_compare_una_volta(self):
        html = _render_striscia_foto(
            _blocchi("A", "B", "A", "C"),
            {"A": _scatto("a"), "B": _scatto("b"), "C": _scatto("c")})
        self.assertEqual(html.count("<img"), 3)

    def test_mai_piu_di_tre(self):
        # Oltre tre la riga diventa una galleria e il programma sparisce.
        html = _render_striscia_foto(
            _blocchi("A", "B", "C", "D", "E"),
            {k: _scatto(k.lower()) for k in "ABCDE"})
        self.assertEqual(html.count("<img"), 3)


class TestSoloFotografieVereEConIlCredito(unittest.TestCase):

    def test_la_grafica_disegnata_in_casa_resta_fuori(self):
        html = _render_striscia_foto(
            _blocchi("A", "B", "C"),
            {"A": _scatto("a", reale=False), "B": _scatto("b", reale=False),
             "C": _scatto("c")})
        self.assertEqual(html, "", "un rettangolo colorato si e' preso lo "
                                   "spazio del programma")

    def test_senza_credito_la_foto_non_si_stampa(self):
        senza = {"png": b"\xff\xd8x", "credito": "  ", "reale": True}
        html = _render_striscia_foto(
            _blocchi("A", "B", "C"),
            {"A": senza, "B": senza, "C": _scatto("c")})
        self.assertEqual(html, "")

    def test_niente_immagini_niente_fila(self):
        for immagini in (None, {}, {"A": {}}, {"A": None}):
            with self.subTest(immagini=immagini):
                self.assertEqual(
                    _render_striscia_foto(_blocchi("A", "B"), immagini), "")

    def test_il_formato_dichiarato_segue_i_byte(self):
        # Stessa regola di tutte le altre immagini: il tipo si legge, non si
        # ricorda. Qui i finti sono JPEG e devono essere dichiarati tali.
        html = _render_striscia_foto(
            _blocchi("A", "B"), {"A": _scatto("a"), "B": _scatto("b")})
        self.assertIn("data:image/jpeg;base64", html)
        self.assertNotIn("data:image/png;base64", html)


class TestLaFilaNonRovinaLImpaginazione(unittest.TestCase):
    """Il rischio vero di questa aggiunta: riempire i vuoti creandone altri."""

    def test_la_fila_non_si_spezza_fra_due_pagine(self):
        regola = _CSS.split(".day-striscia {", 1)[1].split("}", 1)[0]
        self.assertIn("page-break-inside: avoid", regola,
                      "una fila spezzata a meta' lascia una riga di "
                      "didascalie orfane in cima alla pagina dopo")

    def test_le_colonne_si_fanno_con_una_tabella(self):
        # In questo motore di stampa le colonne vere si ottengono solo con le
        # tabelle: `float` e `display: flex` vengono ignorati in silenzio.
        html = _render_striscia_foto(
            _blocchi("A", "B"), {"A": _scatto("a"), "B": _scatto("b")})
        self.assertIn("<table class='day-striscia'>", html)
        self.assertNotIn("display: flex", html)

    def test_le_immagini_della_fila_hanno_un_tetto_d_altezza(self):
        # Senza, una fotografia verticale si prende mezza pagina e la fila
        # diventa il contrario di cio' per cui e' nata.
        regola = _CSS.split(".day-striscia img {", 1)[1].split("}", 1)[0]
        self.assertIn("max-height", regola)
        self.assertIn("max-width", regola)


class TestLaFilaArrivaDAVVERONELDOCUMENTO(unittest.TestCase):
    """La trappola che questo progetto ha gia' preso piu' volte.

    Una funzione corretta e mai chiamata e' il modo piu' elegante di non
    risolvere un problema. Tutte le prove qui sopra passano anche se la fila
    non viene mai attaccata alla pagina: l'ho verificato staccandola, e sono
    rimaste verdi tutte e dodici. Questa e' l'unica che se ne accorge.
    """

    def _documento(self):
        from src.pdf_renderer import render_html

        itinerario = {
            "destination": "Bologna",
            "executive_summary": "Due giorni.",
            "days": [{"day": 1, "title": "Centro", "blocks": _blocchi("A", "B", "C")}],
        }
        return render_html(
            itinerario,
            {"destination": "Bologna", "date_start": "2026-09-12",
             "date_end": "2026-09-14", "duration_days": 1, "budget_eur": 600},
            hotels=[{"name": "Hotel", "price_night_eur": 100}],
            photos={"A": _scatto("a"), "B": _scatto("b"), "C": _scatto("c")},
        )

    def test_la_fila_compare_nella_pagina_costruita(self):
        self.assertIn("<table class='day-striscia'>", self._documento(),
                      "la fila esiste come funzione ma non arriva al "
                      "documento: e' come non averla scritta")

    def test_la_foto_di_apertura_non_e_anche_nella_fila(self):
        # Il giro completo del non-doppione, misurato sul documento vero e non
        # sulla funzione isolata: e' li' che il difetto si vedrebbe.
        documento = self._documento()
        self.assertEqual(documento.count("Foto: a / Prova"), 1)


if __name__ == "__main__":
    unittest.main()
