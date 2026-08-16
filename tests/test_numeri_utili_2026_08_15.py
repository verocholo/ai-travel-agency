"""Il capitolo che si cerca quando qualcosa va storto (task #220).

PERCHE' QUESTO FILE ESISTE

Lorenzo, 15 agosto: «mancano ancora dei capitoli». Il numero di emergenza, la
valuta e le prese erano gia' nel documento — ma in coda a «Prima di partire»,
cioe' dentro il capitolo che si legge la sera prima. Queste righe servono
DURANTE il viaggio, e nessuno apre la lista della valigia mentre e' in giro
con un problema. Un dato messo dove non lo si cerca e' un dato che non c'e'.

## Cosa difendono i controlli qui sotto

1. che il capitolo esista davvero nel documento e nell'indice;
2. che non ci sia il DOPPIONE — le stesse righe erano in «Prima di partire» e
   lasciarle in tutti e due i posti sarebbe stato il modo piu' rapido di
   peggiorare invece di migliorare;
3. che il numero di emergenza esca dalla tabella scritta a mano e non da un
   modello, e che su un paese sconosciuto NON esca affatto: e' il dato in cui
   un errore fa il danno piu' grave e piu' veloce;
4. che il capitolo non prometta cose che non sappiamo — i prezzi dei
   biglietti dei mezzi restano fuori finche' non c'e' una fonte vera.
"""

import unittest


def _documento(destinazione="Siena"):
    import scripts_sample_pdf
    from src.pdf_renderer import render_html

    itinerario, viaggio, kwargs, _ = scripts_sample_pdf.build_sample_render_kwargs()
    kwargs = dict(kwargs)
    kwargs.pop("output_path", None)
    itinerario = dict(itinerario, destination=destinazione)
    viaggio = dict(viaggio, destination=destinazione)
    return render_html(itinerario, viaggio, **kwargs)


class TestIlCapitoloCEDAVVERO(unittest.TestCase):

    def test_esce_nel_documento_e_nellindice(self):
        html = _documento()
        self.assertIn("data-capitolo='numeri-utili'", html)
        self.assertIn("Numeri utili e quanto si cammina", html)

    def test_il_numero_di_emergenza_arriva_dalla_tabella_scritta_a_mano(self):
        from src import local_info

        atteso = local_info.country_practical_info("Siena")["emergency"]
        self.assertIn(atteso, _documento())

    def test_su_un_paese_che_non_conosciamo_niente_numero_inventato(self):
        # L'omissione e' l'esito voluto: meglio nessuna riga che un numero
        # di emergenza plausibile.
        from src import local_info

        self.assertIsNone(local_info.country_practical_info("Wakanda"))


class TestNONCEILDOPPIONE(unittest.TestCase):
    """Spostare una cosa e lasciarla anche dov'era e' il modo piu' rapido di
    peggiorare un documento credendo di migliorarlo."""

    def test_la_scheda_del_paese_non_e_piu_in_prima_di_partire(self):
        from src.pdf_renderer import _render_predeparture

        stampato = _render_predeparture({
            "country": {"country": "Italia", "emergency": "112",
                        "currency": "Euro (€)"},
            "checklist": [{"title": "Documenti", "detail": "carta d'identità"}],
        })
        self.assertNotIn("112", stampato)
        self.assertIn("Documenti", stampato)

    def test_il_numero_di_emergenza_compare_una_volta_sola(self):
        html = _documento()
        self.assertEqual(1, html.count(">Numero di emergenza<"))


class TestNONSIPROMETTEQUELLOCHENONSISA(unittest.TestCase):
    """La regola del prodotto vale anche quando rende un capitolo piu' corto:
    i prezzi dei mezzi cambiano, non abbiamo una fonte, e un cliente che
    arriva al tornello col prezzo sbagliato non si fida piu' nemmeno delle
    parti giuste."""

    def test_non_si_parla_di_biglietti_e_abbonamenti(self):
        from src.pdf_renderer import _render_numeri_utili

        stampato = _render_numeri_utili(
            {"country": {"country": "Italia", "emergency": "112"}},
            hotels=[{"name": "Hotel", "address": "Via Roma 1"}])
        for parola in ("abbonamento", "biglietto giornaliero", "metro"):
            with self.subTest(parola=parola):
                self.assertNotIn(parola, stampato.lower())

    def test_senza_niente_da_dire_il_capitolo_non_esce(self):
        from src.pdf_renderer import _render_numeri_utili

        self.assertEqual("", _render_numeri_utili(None))
        self.assertEqual("", _render_numeri_utili({"country": None}))


if __name__ == "__main__":
    unittest.main()
