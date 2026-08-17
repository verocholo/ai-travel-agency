"""Il riepilogo del viaggio non si spezza fra due pagine (task #225).

PERCHE' QUESTO FILE ESISTE

Direttiva di Lorenzo: «non devono spezzarsi non solo i vari capitoli, ma
anche i vari paragrafi». Sul fascicolo di Bologna il riquadro «Il viaggio
in breve» — l'`executive_summary`, un paragrafo vero scritto in prosa — si
spezzava fra le pagine 2 e 3.

La macchina che protegge i paragrafi dallo spezzarsi (`_tieni_uniti_i_paragrafi`,
task #183) già esisteva: mancava solo `summary-box` nell'elenco delle classi
che riconosce. Non era una dimenticanza di disegno — quando la regola fu
scritta, quel riquadro conteneva solo brevi frasi di sistema; da quando ci
entra anche l'`executive_summary` è un blocco di prosa a tutti gli effetti.
"""

import unittest


class TestIlRiepilogoDelViaggioERiconosciutoComeProsa(unittest.TestCase):

    def test_summary_box_e_nell_elenco_delle_classi_protette(self):
        from src.pdf_renderer import _CLASSI_PROSA

        self.assertIn("summary-box", _CLASSI_PROSA)

    def test_un_riepilogo_corto_viene_avvolto_nel_guscio(self):
        from src.pdf_renderer import _tieni_uniti_i_paragrafi

        testo = (
            "Il tuo weekend bolognese è costruito interamente a piedi "
            "attorno al Grand Hotel Majestic già Baglioni, baricentro "
            "perfetto a 6-7 minuti da Piazza Maggiore, dalle Due Torri, "
            "dal Mercato delle Erbe e dall'unico ristorante verificato "
            "per esigenze vegetariane."
        )
        html = f"<div class='summary-box'>{testo}</div>"
        risultato = _tieni_uniti_i_paragrafi(html)
        self.assertIn("<table class='keep-prosa'>", risultato,
                      "il riepilogo del viaggio deve essere avvolto nel "
                      "guscio che gli impedisce di spezzarsi")
        self.assertIn("summary-box", risultato)

    def test_un_riepilogo_lunghissimo_resta_libero_di_scorrere(self):
        """[LA STESSA TENSIONE GIA' RISOLTA PER GLI ALTRI PARAGRAFI.]
        Un riepilogo enorme, spinto tutto insieme alla pagina dopo,
        lascerebbe bianca la pagina prima — esattamente il difetto
        opposto, gia' visto e gia' risolto per le altre classi di prosa.
        Sopra la soglia si lascia scorrere, come tutti gli altri."""
        from src.pdf_renderer import LIMITE_PROSA_UNITA, _tieni_uniti_i_paragrafi

        testo = "Frase molto lunga ripetuta molte volte. " * 40
        self.assertGreater(len(testo), LIMITE_PROSA_UNITA)
        html = f"<div class='summary-box'>{testo}</div>"
        risultato = _tieni_uniti_i_paragrafi(html)
        self.assertNotIn("keep-prosa", risultato)

    def test_arriva_davvero_nel_documento_renderizzato(self):
        """La trappola gia' presa altre volte in questo progetto: una
        regola corretta che nessuno collega al documento vero."""
        from src.pdf_renderer import render_html

        itinerario = {
            "destination": "Bologna",
            "executive_summary": (
                "Il tuo weekend bolognese è costruito interamente a piedi "
                "attorno al Grand Hotel Majestic già Baglioni, baricentro "
                "perfetto a poche minuti da Piazza Maggiore e dalle Due "
                "Torri, con entrambe le cene fissate all'Osteria dell'Orsa "
                "per la sicurezza alimentare di tua sorella."
            ),
            "days": [{"day": 1, "title": "Centro", "blocks": []}],
        }
        html = render_html(
            itinerario,
            {"destination": "Bologna", "date_start": "2026-09-12",
             "date_end": "2026-09-13", "duration_days": 1, "budget_eur": 300},
            hotels=[{"name": "Hotel", "price_night_eur": 100}],
        )
        pezzo = html.split("<div class='summary-box'>", 1)[0][-40:]
        self.assertIn("keep-prosa", pezzo)


if __name__ == "__main__":
    unittest.main()
