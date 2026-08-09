"""
[AGGIUNTO 2026-08-03 — segnalazione del cliente: «il link di tally non
funziona ancora».]

Il capitolo "Facci sapere com'è andata" può fallire in quattro modi
diversi, e tutti e quattro finiscono nello stesso posto: una persona che
ha appena finito il viaggio prova a rispondere e non ci riesce. I quattro
modi sono:

  1. la URL configurata è un SEGNAPOSTO mai sostituito
     (`https://tally.so/r/ESEMPIO`): il link si apre e mostra il 404 di
     Tally. È la forma peggiore, perché sembra funzionare fino al clic;
  2. la URL non ha lo schema (`tally.so/r/xyz`): wkhtmltopdf la risolve
     contro il file HTML temporaneo e produce un `file:///tmp/...` che
     `src/pdf_links.py` scarta — un link morto, silenzioso, invisibile a
     chi rilegge il PDF sul proprio computer;
  3. la URL ha un'ancora (`...#inizio`): il vecchio codice attaccava
     `?ref=` DOPO l'ancora, quindi il modulo si apriva ma la risposta
     arrivava senza il codice del viaggio, cioè inutilizzabile;
  4. la variabile non è impostata affatto in produzione: il capitolo fa
     le domande e non offre nessun posto dove rispondere.

Questi test descrivono le promesse corrispondenti. Non verificano che il
codice faccia quello che fa: verificano che nessuna di queste quattro
forme possa arrivare a un cliente pagante.
"""
import os
import unittest
from unittest.mock import patch
from urllib.parse import parse_qsl, urlsplit

from src import feedback_link
from src import pdf_renderer
from src.schemas import Trip


_TRIP = Trip(
    email="cliente@example.com",
    destination="Siena",
    date_start="2026-09-14",
    date_end="2026-09-17",
    duration_days=3,
    objective_function="ENERGY_PACING",
    budget_eur=800,
    budget_mode="LIMITED",
)


def _costruisci(base, ref="abc1234567", param=None):
    """URL finale con `FEEDBACK_FORM_URL` impostata a `base`.

    L'ambiente viene ripulito da `FEEDBACK_REF_PARAM`: altri moduli della
    suite lo impostano, e un test che dipende da chi ha girato prima non
    dice niente su niente.
    """
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("FEEDBACK_REF_PARAM", None)
        os.environ["FEEDBACK_FORM_URL"] = base
        if param is not None:
            os.environ["FEEDBACK_REF_PARAM"] = param
        return feedback_link.build_feedback_url(ref)


# ---------------------------------------------------------------------------
# 1. Quello che non può funzionare non deve essere stampato
# ---------------------------------------------------------------------------
class TestUnaUrlCheNonPuoFunzionareNonArrivaAlCliente(unittest.TestCase):
    def test_variabile_assente_nessun_link(self):
        """Senza modulo configurato non si inventa un link: meglio un
        capitolo senza riquadro che un riquadro che porta al nulla."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("FEEDBACK_FORM_URL", None)
            self.assertIsNone(feedback_link.build_feedback_url("abc1234567"))

    def test_valore_vuoto_o_di_soli_spazi_nessun_link(self):
        """Una variabile impostata a "" nella dashboard di Render è il modo
        più comune di credere di aver configurato qualcosa senza averlo
        fatto."""
        for vuoto in ("", "   ", "\n\t "):
            with self.subTest(valore=repr(vuoto)):
                self.assertIsNone(_costruisci(vuoto))

    def test_valore_non_testuale_non_rompe_la_generazione(self):
        """Il PDF vale 200 €: nessuna forma di configurazione sbagliata può
        farlo fallire, al massimo può togliere il riquadro."""
        finto_getenv = lambda chiave, default=None: (  # noqa: E731
            123 if chiave == "FEEDBACK_FORM_URL" else default
        )
        with patch.object(feedback_link.os, "getenv", finto_getenv):
            self.assertIsNone(feedback_link.build_feedback_url("abc1234567"))

    def test_senza_schema_nessun_link(self):
        """`tally.so/r/xyz` diventa un `file:///tmp/...` dentro il PDF: il
        cliente clicca e non succede niente. È il difetto più difficile da
        vedere di tutti, perché il testo stampato sembra giusto."""
        for senza_schema in ("tally.so/r/xyz", "ESEMPIO", "/r/xyz", "www.tally.so/r/xyz"):
            with self.subTest(valore=senza_schema):
                self.assertIsNone(_costruisci(senza_schema))

    def test_http_in_chiaro_rifiutato(self):
        """Regola di tutto il repo: nessun `http://` in un documento che
        contiene il nome e le date di viaggio di una persona."""
        self.assertIsNone(_costruisci("http://tally.so/r/xyz"))

    def test_senza_host_nessun_link(self):
        for senza_host in ("https:///r/xyz", "https://", "https://?a=b"):
            with self.subTest(valore=senza_host):
                self.assertIsNone(_costruisci(senza_host))

    def test_segnaposto_mai_sostituito_nessun_link(self):
        """È la causa della segnalazione: il campione è sempre uscito con
        `https://tally.so/r/ESEMPIO`, che si apre sul 404 di Tally."""
        for segnaposto in (
            "https://tally.so/r/ESEMPIO",
            "https://tally.so/r/esempio",
            "https://tally.so/r/PLACEHOLDER",
            "https://tally.so/r/TUO-FORM-ID",
            "https://tally.so/r/form_id",
            "https://tally.so/r/TODO",
            "https://tally.so/r/xxxx",
            "https://tally.so/r/da-impostare",
            "https://example.com/r/wA5b2Q",
        ):
            with self.subTest(valore=segnaposto):
                self.assertIsNone(_costruisci(segnaposto))

    def test_un_id_che_potrebbe_essere_vero_non_viene_scartato(self):
        """Il controllo opposto, e il più importante dei due: un falso
        positivo qui toglie in silenzio un modulo che funziona, e nessuno
        se ne accorge finché non smettono di arrivare risposte."""
        for buona in (
            "https://tally.so/r/wA5b2Q",
            "https://tally.so/r/test",
            "https://tally.so/r/demo2026",
            "https://forms.gle/aBcDeF123",
        ):
            with self.subTest(valore=buona):
                self.assertIsNotNone(_costruisci(buona))


# ---------------------------------------------------------------------------
# 2. Il link buono deve portare con sé il codice del viaggio
# ---------------------------------------------------------------------------
class TestIlLinkBuonoPortaIlCodiceDelViaggio(unittest.TestCase):
    def test_url_pulita_riceve_il_ref(self):
        self.assertEqual(
            _costruisci("https://tally.so/r/wA5b2Q"),
            "https://tally.so/r/wA5b2Q?ref=abc1234567",
        )

    def test_url_con_query_riceve_il_ref_dopo_una_e_commerciale(self):
        """Se il modulo è già configurato in italiano (`?lang=it`), il
        parametro va aggiunto, non sostituito."""
        self.assertEqual(
            _costruisci("https://tally.so/r/wA5b2Q?lang=it"),
            "https://tally.so/r/wA5b2Q?lang=it&ref=abc1234567",
        )

    def test_url_con_ancora_mette_il_ref_nella_query_non_dopo_l_ancora(self):
        """`...#inizio?ref=abc` è una URL sintatticamente valida in cui
        `ref` fa parte dell'ancora: il modulo si apre e la risposta arriva
        senza sapere di quale viaggio parla. Con cento risposte all'anno,
        cento aneddoti anonimi."""
        url = _costruisci("https://tally.so/r/wA5b2Q#inizio")
        self.assertEqual(url, "https://tally.so/r/wA5b2Q?ref=abc1234567#inizio")
        pezzi = urlsplit(url)
        self.assertEqual(dict(parse_qsl(pezzi.query))["ref"], "abc1234567")
        self.assertEqual(pezzi.fragment, "inizio")

    def test_ancora_e_query_insieme_restano_nell_ordine_giusto(self):
        self.assertEqual(
            _costruisci("https://tally.so/r/wA5b2Q?lang=it#inizio"),
            "https://tally.so/r/wA5b2Q?lang=it&ref=abc1234567#inizio",
        )

    def test_nome_del_parametro_strano_non_spezza_la_url(self):
        """`FEEDBACK_REF_PARAM` la scrive una persona a mano nella
        dashboard: uno spazio o una `&` di troppo non deve produrre una URL
        che il modulo interpreta come due parametri diversi."""
        url = _costruisci("https://tally.so/r/wA5b2Q", param="re f&x=")
        self.assertNotIn(" ", url)
        pezzi = urlsplit(url)
        self.assertEqual(parse_qsl(pezzi.query), [("re f&x=", "abc1234567")])

    def test_senza_ref_resta_la_url_configurata(self):
        self.assertEqual(
            _costruisci("https://tally.so/r/wA5b2Q", ref=None),
            "https://tally.so/r/wA5b2Q",
        )

    def test_il_codice_del_viaggio_resta_deterministico(self):
        """Rigenerare il PDF non deve cambiare il codice: altrimenti la
        risposta già data non si riattacca più al viaggio giusto."""
        with patch.dict(os.environ, {"FEEDBACK_REF_SECRET": "segreto-di-test",
                                     "FEEDBACK_FORM_URL": "https://tally.so/r/wA5b2Q"}):
            os.environ.pop("FEEDBACK_REF_PARAM", None)
            primo = feedback_link.build_feedback_link(_TRIP)
            secondo = feedback_link.build_feedback_link(_TRIP)
        self.assertEqual(primo, secondo)
        self.assertIn("ref=" + primo[0], primo[1])


# ---------------------------------------------------------------------------
# 3. Il controllo che impedisce al difetto di tornare
# ---------------------------------------------------------------------------
class TestIlCampioneNonSpedisceUnLinkFinto(unittest.TestCase):
    """Il campione di `scripts_sample_pdf.py` è il documento che il cliente
    guarda per giudicare il lavoro. Per mesi ha contenuto
    `https://tally.so/r/ESEMPIO`, cioè un link al 404 di Tally, e nessun
    test lo diceva."""

    def _campione(self):
        import scripts_sample_pdf
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("FEEDBACK_FORM_URL", None)
            itinerary, trip, kwargs, _ = scripts_sample_pdf.build_sample_render_kwargs()
            return pdf_renderer.render_html(itinerary, trip, **kwargs), kwargs

    def test_il_campione_non_contiene_nessuna_url_segnaposto(self):
        html, _ = self._campione()
        for finto in ("tally.so", "/r/ESEMPIO", "ESEMPIO"):
            self.assertNotIn(finto, html)

    def test_senza_modulo_configurato_il_campione_non_ha_nessun_link(self):
        _, kwargs = self._campione()
        self.assertIsNone((kwargs.get("feedback_link") or {}).get("url"))

    def test_il_sorgente_del_campione_non_configura_nessuna_url(self):
        """Il controllo sta sul sorgente e non solo sul risultato: se
        domani qualcuno rimette un `setdefault` con una URL inventata, il
        campione tornerebbe a uscire con un link morto. Le righe di
        commento sono escluse apposta — spiegare come si esporta la
        variabile vera è utile, impostarla nel codice no."""
        import scripts_sample_pdf
        with open(scripts_sample_pdf.__file__, encoding="utf-8") as f:
            sorgente = f.read()
        attive = [r for r in sorgente.splitlines() if not r.lstrip().startswith("#")]
        impostazioni = [r for r in attive if "FEEDBACK_FORM_URL" in r
                        and ("environ" in r or "putenv" in r)]
        self.assertEqual(impostazioni, [])
        self.assertEqual([r for r in attive if "tally.so" in r], [])


# ---------------------------------------------------------------------------
# 4. Il buco che resta — non richiudibile da questo modulo
# ---------------------------------------------------------------------------
class TestIlCapitoloNonChiedeSeNonCEDoveRispondere(unittest.TestCase):
    """[CHIUSO 2026-08-03] Era un fallimento atteso: senza
    `FEEDBACK_FORM_URL` il capitolo "Facci sapere com'è andata" usciva
    lo stesso — intro, domande personalizzate rivolte al cliente, e
    nessun riquadro "Rispondi qui". Il questionario nella bottiglia
    descritto in cima a `src/feedback_link.py`, con l'aggravante di
    sembrare voluto. Ora la sezione, la sua voce d'indice e la sua
    àncora non vengono proprio emesse."""

    _ITINERARIO = {
        "destination": "Siena",
        "executive_summary": "Due giorni.",
        "days": [{"day": 1, "title": "Arrivo", "blocks": [
            {"time": "10:00", "activity": "Piazza del Campo", "location": "Siena"},
        ]}],
    }
    _FEEDBACK = {
        "intro_message": "Com'è andata?",
        "questions": ["Ti è piaciuta la Taverna di San Giuseppe?"],
    }

    def _html(self, link):
        return pdf_renderer.render_html(
            self._ITINERARIO, _TRIP.to_dict(),
            feedback=self._FEEDBACK, feedback_link=link,
        )

    def test_senza_un_posto_dove_rispondere_il_capitolo_non_fa_domande(self):
        html = self._html({"ref": "abc1234567", "url": None, "core_questions": []})
        self.assertNotIn("Facci sapere com'è andata", html)
        self.assertNotIn("Rispondi qui", html)
        # E nemmeno la domanda personalizzata deve sopravvivere da sola:
        # sarebbe la stessa promessa rotta senza nemmeno il titolo.
        self.assertNotIn("Taverna di San Giuseppe", html)

    def test_senza_feedback_link_del_tutto_il_capitolo_non_esce(self):
        # Il caso vero della produzione di oggi: la variabile non è
        # impostata, quindi `build_feedback_link()` restituisce None e il
        # kwarg non arriva proprio.
        self.assertNotIn("Facci sapere com'è andata", self._html(None))

    def test_lindice_non_promette_un_capitolo_che_non_ce(self):
        # Una voce d'indice che punta a un'àncora inesistente è un link
        # morto in copertina: peggio dell'assenza, perché è cliccabile.
        html = self._html(None)
        self.assertNotIn("recensione", html)

    def test_con_una_url_vera_il_capitolo_torna_intero(self):
        # Il controllo di segno opposto: la correzione non deve aver
        # spento la sezione anche quando il modulo c'è davvero.
        # La URL arriva qui GIA' completa: il codice della consegna lo
        # attacca `build_feedback_url()` a monte, il renderer la stampa
        # e basta. Un test che si aspettasse il renderer a comporla
        # duplicherebbe la logica in due posti.
        html = self._html({"ref": "abc1234567",
                           "url": "https://tally.so/r/wA5b2Q?ref=abc1234567",
                           "core_questions": []})
        self.assertIn("Facci sapere com'è andata", html)
        self.assertIn("Rispondi qui", html)
        self.assertIn("https://tally.so/r/wA5b2Q?ref=abc1234567", html)
        self.assertIn("abc1234567", html)


if __name__ == "__main__":
    unittest.main()
