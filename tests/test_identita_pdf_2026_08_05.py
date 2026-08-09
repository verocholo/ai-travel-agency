"""L'identità applicata al PDF (task #195).

PERCHÉ QUESTO FILE ESISTE
Lorenzo: «migliora in maniera professionale, accattivante e definitiva il
design e lo stile di tutto il pdf, deve essere facilmente riconoscibile, e si
deve distinguere dal resto del mercato per la sua qualità grafica», e poi
«standardizza tutto il progetto una volta finito».

Standardizzare un design vuol dire una cosa sola: che le decisioni che lo
rendono riconoscibile non possano tornare indietro da sole. Nessuno di questi
controlli giudica il gusto — non saprebbe farlo. Tengono ferme le poche
scelte che, se si perdono, riportano il documento a somigliare a tutti gli
altri: gli angoli vivi, le grazie sui titoli, un accento solo, e il colore
acceso usato con avarizia.

Sono controlli sull'HTML PRODOTTO e non sul foglio di stile scritto a mano: è
la stessa lezione già imparata due volte in questo progetto — un controllo
che legge il sorgente vede anche i commenti, e passa a vuoto per sempre.
"""

import re
import unittest

from src import identita
from src.pdf_renderer import _CSS, render_html


TRIP = {"destination": "Siena", "date_start": "2026-09-14",
        "date_end": "2026-09-16", "duration_days": 2, "budget_eur": 800}
ITINERARIO = {
    "destination": "Siena",
    "executive_summary": "Due giorni dentro le mura.",
    "days": [{"day": 1, "title": "Centro", "blocks": [
        {"time": "10:00", "activity": "Piazza del Campo", "location": "Siena",
         "poi_id": "POI1"}]}],
}


def _documento() -> str:
    return render_html(ITINERARIO, TRIP,
                       hotels=[{"name": "Hotel", "price_night_eur": 100}])


class TestLaCartaNonSembraUnCruscotto(unittest.TestCase):
    """Le due cose che, da sole, dicono «software» invece che «documento»."""

    def test_nessun_angolo_arrotondato_in_tutto_il_documento(self):
        """L'angolo tondo è il segnale numero uno di «interfaccia».

        Una guida di città stampata non ha angoli tondi da nessuna parte; un
        cruscotto ce li ha ovunque. È la modifica più piccola con l'effetto
        più grande, ed è anche quella che rientrerebbe per prima al primo
        pezzo di stile copiato da un'altra parte.
        """
        arrotondati = re.findall(r"border-radius:\s*([^;]+);", _documento())
        cattivi = [v.strip() for v in arrotondati
                   if v.strip() not in ("0", "0px")]
        self.assertEqual(cattivi, [],
                         f"angoli arrotondati rimasti: {cattivi}")

    def test_i_titoli_hanno_le_grazie(self):
        # Il carattere con le grazie è quello dei libri. È metà del
        # riconoscimento visivo del documento: senza, resta un rapporto.
        html = _documento()
        for regola in (".cover-title", ".section-title", ".day-title"):
            with self.subTest(regola=regola):
                blocco = html.split(regola + " {", 1)
                if len(blocco) == 1:
                    blocco = html.split(regola + " {", 1)
                self.assertIn("serif", html.split(regola, 1)[1][:400],
                              f"{regola} ha perso il carattere con le grazie")

    def test_le_grazie_sono_una_famiglia_che_esiste_di_sicuro(self):
        # Il PDF si stampa dentro un contenitore Docker minimo: un carattere
        # assente non dà errore, viene sostituito in silenzio e il documento
        # esce con una faccia che non è la sua.
        self.assertIn("Georgia", identita.SERIF)
        self.assertIn("serif", identita.SERIF)
        self.assertIn("Georgia", _CSS)


class TestUnAccentoSolo(unittest.TestCase):
    """«Poco colore» è una regola, non un'impressione."""

    def test_l_oro_dell_identita_e_quello_che_finisce_nel_documento(self):
        # Se qualcuno cambiasse l'oro in `identita.py` e non qui, i tre
        # documenti divergerebbero senza che nessuno se ne accorga.
        self.assertIn(identita.ORO.lower(), _CSS.lower())

    def test_il_vecchio_arancio_non_torna(self):
        # [REGRESSIONE 2026-08-05] Prima l'accento era un arancio da
        # segnaletica (#c9762f), usato in sedici punti. È il colore che
        # tornerebbe per primo copiando una regola vecchia.
        self.assertNotIn("#c9762f", _documento().lower())

    def test_i_colori_accesi_restano_dove_significano_qualcosa(self):
        """Il semaforo può esistere solo dove dice una cosa vera.

        Le etichette del ritmo («energia alta/media/bassa») dicono qualcosa
        di reale, quindi il colore resta — ma sul testo e su un filetto, non
        su una pastiglia piena. Tre pastiglie colorate erano le uniche
        macchie accese del documento e gridavano più del nome del luogo.
        """
        css = _CSS
        pezzo = css.split(".energy-chip.energy-high", 1)[1][:200]
        self.assertNotIn("background: #", pezzo,
                         "le etichette del ritmo sono tornate pastiglie piene")


class TestIlSegnapostoRestaInvisibile(unittest.TestCase):
    """[REGRESSIONE 2026-08-05 — difetto visto sulla pagina, non nel codice]

    Da quando il segnaposto del ritorno si semina DENTRO il pulsante «Apri
    la guida» (task #191), il suo `<a>` ereditava lo stile del pulsante:
    fondo blu, riempimento, blocco in linea. Nel PDF vero, accanto a ognuno
    dei nove pulsanti, compariva un mozzicone blu largo mezzo centimetro.

    Nessun controllo poteva vederlo: l'HTML era corretto e tutti i
    collegamenti funzionavano. Si vedeva solo guardando la pagina stampata.
    Questo controlla la cosa che lo rende invisibile — l'ordine delle regole
    nel foglio di stile — che è l'unica parte verificabile senza occhi.
    """

    def test_la_regola_del_segnaposto_viene_dopo_quella_dei_pulsanti(self):
        # Nel CSS, a parità di specificità, vince l'ultima. Se la regola del
        # segnaposto risalisse sopra quella del pulsante, il mozzicone
        # tornerebbe — e tornerebbe in silenzio.
        pulsante = _CSS.find(".guide-link a {")
        segnaposto = _CSS.find(".anchor-probe a {")
        self.assertGreater(pulsante, 0, "regola del pulsante non trovata")
        self.assertGreater(segnaposto, 0, "regola del segnaposto non trovata")
        self.assertGreater(segnaposto, pulsante,
                           "il segnaposto verrebbe ridipinto come un pulsante")

    def test_il_segnaposto_annulla_tutto_quello_che_potrebbe_ereditare(self):
        regola = _CSS.split(".anchor-probe a {", 1)[1].split("}", 1)[0]
        for annullato in ("background: none", "padding: 0", "display: inline"):
            with self.subTest(annullato=annullato):
                self.assertIn(annullato, regola)

    def test_resta_comunque_di_dimensione_non_nulla(self):
        # Invisibile sì, inesistente no: un elemento largo zero pixel non
        # riceve annotazione da wkhtmltopdf, e la riparazione dei
        # collegamenti resterebbe cieca. È il difetto opposto, e sarebbe
        # peggio.
        regola = _CSS.split(".anchor-probe a {", 1)[1].split("}", 1)[0]
        self.assertIn("font-size: 2px", regola)
        self.assertNotIn("display: none", regola)
        self.assertIn("&#160;", _documento())


class TestLeDateSonoScritteDaUnaPersona(unittest.TestCase):
    """[REGRESSIONE 2026-08-05] «2026-09-14» in copertina.

    Era, su tutta la copertina, l'unico punto in cui si vedeva che il
    documento l'ha scritto un programma. Quella forma esiste per gli
    ordinamenti; a un cliente dice solo che nessuno ha guardato la pagina
    prima di venderla.
    """

    def test_in_copertina_il_periodo_e_in_italiano(self):
        html = _documento()
        self.assertIn("settembre 2026", html)
        self.assertNotIn("2026-09-14 &#8594; 2026-09-16", html)
        self.assertNotIn("2026-09-14 → 2026-09-16", html)

    def test_il_mese_non_si_ripete_quando_e_lo_stesso(self):
        from src.pdf_renderer import _periodo_leggibile

        self.assertEqual(_periodo_leggibile("2026-09-14", "2026-09-16"),
                         "14 → 16 settembre 2026")

    def test_a_cavallo_di_mese_e_di_anno_si_capisce_lo_stesso(self):
        from src.pdf_renderer import _periodo_leggibile

        self.assertEqual(_periodo_leggibile("2026-09-28", "2026-10-03"),
                         "28 settembre → 3 ottobre 2026")
        self.assertEqual(_periodo_leggibile("2026-12-30", "2027-01-02"),
                         "30 dicembre 2026 → 2 gennaio 2027")

    def test_una_data_illeggibile_non_toglie_la_copertina(self):
        # Le date arrivano dal modulo di richiesta e passano per Make: prima
        # o poi ne arriverà una storta. Meglio brutto che assente.
        from src.pdf_renderer import _periodo_leggibile

        for coppia in [("", ""), (None, None), ("ieri", "domani"), (1, 2)]:
            with self.subTest(coppia=coppia):
                self.assertTrue(_periodo_leggibile(*coppia))


if __name__ == "__main__":
    unittest.main()
