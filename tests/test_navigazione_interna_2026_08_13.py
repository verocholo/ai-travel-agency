"""La navigazione interna del fascicolo non muore piu' in silenzio (task #202).

PERCHE' QUESTO FILE ESISTE

Nel documento consegnato l'11 agosto 2026 — 28 pagine, nove capitoli staccati
— non c'era **nemmeno una** destinazione interna. Letto con `pdf_links`:

    pagine: 28 | sonde: 0 | esterni: 42 | goto: 0

Tutti i collegamenti verso l'esterno funzionavano (Google Maps, i siti dei
luoghi, i numeri di telefono). Tutti quelli interni — i pulsanti «Apri la
guida», le zone cliccabili sulle cartine — erano morti. Meta' del contenuto
comprato era raggiungibile solo scorrendo ventotto pagine a mano.

## La cosa peggiore non e' il difetto

E' che il numero **c'era gia'**. `repair_internal_links_bytes()` restituisce
da sempre un resoconto con `riscritti`, `sonde`, `non_risolte`, e
`render_pdf()` lo stampava perfino — nei log di Render, cioe' in un posto che
non guarda nessuno. E' la stessa lezione del 10 agosto, quando un `502`
nascondeva a Make la frase che spiegava tutto: **un'informazione che arriva
dove nessuno guarda non e' un'informazione.**

Da qui in poi quel numero risale fino alla risposta di `/v1/pdf`, quindi fino
a Make, dove si legge senza aprire niente. E se e' zero mentre i capitoli ci
sono, la consegna si ferma.

## Perche' NON si controlla «guides_generated»

Un documento puo' avere le guide dentro le pagine invece che in capitoli
staccati: in quel caso i collegamenti interni non servono e pretenderli
bloccherebbe consegne perfettamente buone. Il segnale giusto e' quanti
capitoli sono stati DAVVERO staccati e cuciti in fondo.
"""

import unittest

import service


class TestLaRegolaDaSola(unittest.TestCase):

    def _motivo(self, **contatori):
        return service._fascicolo_troppo_incompleto(contatori)

    def test_capitoli_senza_collegamenti_fermano_la_consegna(self):
        """Il caso vero dell'11 agosto: nove capitoli, zero salti."""
        motivo = self._motivo(capitoli_staccati=9, collegamenti_interni=0,
                              guides_requested=9, guides_generated=9)
        self.assertTrue(motivo)
        self.assertIn("9", motivo)
        self.assertIn("collegamento", motivo)

    def test_con_i_collegamenti_al_loro_posto_si_consegna(self):
        # Il controllo gemello: senza questo, bloccare TUTTO passerebbe.
        self.assertFalse(self._motivo(capitoli_staccati=9,
                                      collegamenti_interni=65,
                                      guides_requested=9, guides_generated=9))

    def test_un_documento_senza_capitoli_staccati_non_deve_niente(self):
        """Il confine, ed e' la parte che tiene viva la regola.

        Le guide possono stare dentro le pagine invece che in capitoli a se'.
        Li' i collegamenti interni non servono, e pretenderli bloccherebbe
        consegne buone — cioe' farebbe spegnere la regola entro una settimana.
        """
        self.assertFalse(self._motivo(capitoli_staccati=0,
                                      collegamenti_interni=0,
                                      guides_requested=5, guides_generated=5))

    def test_non_lo_so_non_e_zero(self):
        # Quando la stampa non riferisce (prove con la stampa finta), il
        # contatore e' `None`. Trattarlo come zero bloccherebbe consegne per
        # una misura mai fatta — che e' il modo piu' rapido di rendere una
        # regola insopportabile e quindi cancellata.
        self.assertFalse(self._motivo(capitoli_staccati=9,
                                      collegamenti_interni=None,
                                      guides_requested=9, guides_generated=9))


class TestIlNumeroRisaleFinoAMake(unittest.TestCase):
    """Non basta che la regola sia giusta: il numero deve arrivarci.

    Il difetto dell'11 agosto non e' stato non calcolare, e' stato calcolare
    e non far vedere.
    """

    def test_la_stampa_sa_riferire_il_resoconto_a_chi_la_chiama(self):
        import inspect

        from src import pdf_renderer

        firma = inspect.signature(pdf_renderer.render_pdf)
        self.assertIn("resoconto_collegamenti", firma.parameters,
                      "la stampa non ha piu' modo di riferire quanti "
                      "collegamenti interni ha scritto")

    def test_il_servizio_chiede_il_resoconto_e_lo_mette_nei_contatori(self):
        import inspect

        sorgente = inspect.getsource(service._esegui_pdf)
        self.assertIn("resoconto_collegamenti=", sorgente,
                      "il servizio non chiede piu' il resoconto")
        self.assertIn("collegamenti_interni", sorgente,
                      "il numero non arriva nei contatori, quindi non arriva "
                      "a Make: torneremmo a scoprirlo aprendo il PDF")


if __name__ == "__main__":
    unittest.main()
