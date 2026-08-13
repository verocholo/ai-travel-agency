"""La prova che chiede la verita' al motore di stampa vero (task #207).

PERCHE' QUESTO FILE ESISTE

`src/prova_stampa.py` esiste per rispondere all'unica domanda di questo
progetto a cui in sviluppo non si puo' rispondere: **il motore di stampa di
PRODUZIONE cancella i rimandi interni?** In sviluppa il binario non ha le
patch, il difetto non si riproduce, e ogni prova scritta qui e' verde per
costruzione.

Quindi i controlli in questo file non provano che i collegamenti
funzionino — non possono. Provano una cosa piu' piccola e altrettanto
necessaria: **che quella misura sia onesta.**

Una diagnostica che sbaglia e' peggio di una diagnostica che manca, perche'
la si crede. Le tre bugie che potrebbe raccontare sono:

1. **Misurare un comando che nessuno esegue.** Se la prova stampasse con
   opzioni sue, darebbe una risposta precisa alla domanda sbagliata.
2. **Chiedere una cosa piu' facile di quella vera.** Se il bersaglio fosse
   nella stessa pagina del rimando, il motore lo troverebbe e non
   cancellerebbe niente: verde sempre, ovunque, e senza significato. Il
   guasto vero nasce da un bersaglio che al momento della stampa NON C'E'.
3. **Contare i gusci vuoti come collegamenti.** Sul documento venduto le 26
   annotazioni dei rimandi interni C'ERANO: larghe zero, senza nessuna
   azione dentro. Chi si limita a contarle le trova tutte e dice che va bene.

E ce n'e' una quarta, che vale quanto le altre tre messe insieme: la prova
deve **sapere di non poter dimostrare niente da qui**. Su questa macchina
sopravvivono tutti e due i rimandi, il nuovo e il vecchio, e il verdetto lo
dice a chiare lettere invece di spacciare quel verde per una conferma.
"""

import re
import unittest

from src import pdf_links, pdf_renderer, prova_stampa


class TestLaProvaMisuraIlProdottoVero(unittest.TestCase):
    """La bugia numero 1: misurare un comando che nessuno esegue."""

    def test_stampa_con_le_stesse_parole_con_cui_si_stampa_il_documento(self):
        sorgente = (
            __import__("pathlib").Path(prova_stampa.__file__).read_text(encoding="utf-8"))
        self.assertIn("pdf_renderer.COMANDO_STAMPA", sorgente)
        self.assertNotIn('"wkhtmltopdf", "--quiet"', sorgente,
                         "la prova si e' costruita un comando suo: misurerebbe "
                         "il comportamento di qualcosa che nessuno esegue")

    def test_il_prodotto_usa_davvero_quella_costante(self):
        """Il verso opposto, ed e' quello che si dimentica.

        Se `render_pdf` tornasse a scriversi le opzioni in casa, la costante
        resterebbe li' — usata solo dalla prova — e i due si allontanerebbero
        in silenzio: la diagnosi continuerebbe a dire «tutto bene» misurando
        un comando che il prodotto ha smesso di eseguire.
        """
        sorgente = (
            __import__("pathlib").Path(pdf_renderer.__file__).read_text(encoding="utf-8"))
        chiamata = sorgente.split("subprocess.run(", 1)[1][:200]
        self.assertIn("COMANDO_STAMPA", chiamata)

    def test_le_opzioni_che_contano_ci_sono_ancora(self):
        self.assertIn("--enable-internal-links", pdf_renderer.COMANDO_STAMPA)
        self.assertEqual("wkhtmltopdf", pdf_renderer.COMANDO_STAMPA[0])


class TestLaProvaChiedeLaCosaDifficile(unittest.TestCase):
    """La bugia numero 2: un bersaglio che il motore trova senza fatica."""

    def test_la_pagina_che_parte_non_contiene_il_suo_bersaglio(self):
        principale = prova_stampa._html_principale()
        self.assertIn(prova_stampa.ANCORA, principale,
                      "la pagina deve contenere il RIMANDO")
        self.assertNotIn(
            f"id='{prova_stampa.ANCORA}'", principale,
            "il bersaglio non deve stare nella stessa pagina del rimando: se "
            "il motore lo trova non cancella niente, e la prova sarebbe verde "
            "ovunque senza dire nulla")

    def test_il_bersaglio_sta_nel_capitolo_cucito_dopo(self):
        # E' la condizione esatta di produzione: il capitolo e' un altro file,
        # stampato a parte e attaccato in fondo dopo.
        self.assertIn(f"id='{prova_stampa.ANCORA}'", prova_stampa._html_capitolo())

    def test_si_provano_tutte_e_tre_le_forme(self):
        principale = prova_stampa._html_principale()
        self.assertIn(f"href='{pdf_links.href_interno(prova_stampa.ANCORA)}'",
                      principale, "manca la forma nuova: e' quella da verificare")
        self.assertIn(f"href='#{prova_stampa.ANCORA}'", principale,
                      "manca la forma vecchia: senza, non si vede se questa "
                      "macchina riproduce il guasto o no")
        self.assertIn(f"href='{prova_stampa.ESTERNO}'", principale,
                      "manca il collegamento esterno: e' il controllo del "
                      "controllo, senza si legge «tutto morto» come una "
                      "risposta invece che come uno strumento rotto")

    def test_nessun_indirizzo_della_prova_puo_finire_a_qualcuno(self):
        # `.invalid` e' riservato dallo standard: nessuno lo puo' comprare, e
        # nessuna richiesta parte davvero verso un sito di qualcun altro.
        for indirizzo in (prova_stampa.ESTERNO, pdf_links.HOST_INTERNO):
            with self.subTest(indirizzo=indirizzo):
                self.assertRegex(indirizzo, r"^https://[^/]+\.invalid(/|$)")


class TestUnGuscioVuotoNonVieneContatoComeCollegamento(unittest.TestCase):
    """La bugia numero 3, ed e' quella che ha nascosto il guasto per giorni."""

    def test_un_rettangolo_di_area_nulla_non_conta(self):
        # `[0 0 0 0]`: e' esattamente cio' che c'era, ventisei volte, nel
        # documento venduto senza navigazione.
        esito = prova_stampa._verdetto_su(
            "https://x.invalid/a", [("https://x.invalid/a", (0.0, 0.0, 0.0, 0.0))])
        self.assertEqual(1, esito["annotazioni"])
        self.assertEqual(0, esito["cliccabili"])
        self.assertFalse(esito["sopravvive"])

    def test_un_rettangolo_vero_conta(self):
        esito = prova_stampa._verdetto_su(
            "https://x.invalid/a", [("https://x.invalid/a", (20.0, 300.0, 90.0, 314.0))])
        self.assertTrue(esito["sopravvive"])

    def test_un_annotazione_senza_rettangolo_non_conta(self):
        esito = prova_stampa._verdetto_su(
            "https://x.invalid/a", [("https://x.invalid/a", None)])
        self.assertFalse(esito["sopravvive"])

    def test_un_altro_indirizzo_non_viene_scambiato_per_il_nostro(self):
        esito = prova_stampa._verdetto_su(
            "https://x.invalid/a", [("https://x.invalid/b", (0.0, 0.0, 9.0, 9.0))])
        self.assertEqual(0, esito["annotazioni"])


class TestIlVerdettoNonSiSpacciaPerUnaConfermaCheNonE(unittest.TestCase):
    """La bugia numero 4: credere a un verde che non significa niente.

    Su questa macchina il binario non ha le patch, quindi sopravvivono TUTTI
    E DUE i rimandi. Un verdetto ingenuo direbbe «funziona» — e sarebbe la
    stessa identica falsa sicurezza che ci e' costata la settimana.
    """

    def _verdetto(self, nuovo, vecchio, esterno, goto=5, sentinella=b""):
        vivo = lambda s: {"sopravvive": s, "annotazioni": 1, "cliccabili": int(s)}
        return prova_stampa._verdetto(
            vivo(nuovo), vivo(vecchio), vivo(esterno), {"goto": goto}, sentinella)

    def test_se_il_collegamento_esterno_muore_la_misura_si_dichiara_rotta(self):
        # Prima di ogni altra lettura: se non sopravvive nemmeno un normale
        # link a un sito, non e' il prodotto ad avere un problema.
        detto = self._verdetto(nuovo=False, vecchio=False, esterno=False)
        self.assertIn("MISURA NON VALIDA", detto)

    def test_se_la_forma_nuova_muore_lo_dice_senza_giri_di_parole(self):
        detto = self._verdetto(nuovo=False, vecchio=False, esterno=True)
        self.assertTrue(detto.startswith("NO:"), detto)
        self.assertIn("NON basta", detto)

    def test_sulla_macchina_di_sviluppo_avverte_che_non_dimostra_niente(self):
        # Il caso vero della sandbox: tutto verde, e proprio per questo il
        # verdetto deve dire che qui il guasto non si riproduce.
        detto = self._verdetto(nuovo=True, vecchio=True, esterno=True)
        self.assertTrue(detto.startswith("SI:"), detto)
        self.assertIn("NON riproduce il guasto", detto)

    def test_solo_in_produzione_la_conferma_e_piena(self):
        # Forma nuova viva, forma vecchia cancellata: e' la firma del binario
        # patchato, ed e' l'unica lettura che conferma la diagnosi.
        detto = self._verdetto(nuovo=True, vecchio=False, esterno=True)
        self.assertTrue(detto.startswith("SI:"), detto)
        self.assertIn("conferma la diagnosi", detto)
        self.assertNotIn("NON riproduce", detto)

    def test_un_sentinella_dimenticato_nel_file_non_passa_per_successo(self):
        detto = self._verdetto(nuovo=True, vecchio=False, esterno=True,
                               sentinella=b"ancora-interna")
        self.assertTrue(detto.startswith("QUASI:"), detto)

    def test_senza_salti_veri_il_verdetto_accusa_la_riparazione(self):
        detto = self._verdetto(nuovo=True, vecchio=False, esterno=True, goto=0)
        self.assertTrue(detto.startswith("A META':"), detto)


class TestLaProvaGiraDavveroENonCostaNiente(unittest.TestCase):

    def test_su_questa_macchina_da_una_risposta_leggibile(self):
        esito = prova_stampa.prova_collegamenti()
        self.assertNotIn("errore", esito, esito)
        self.assertTrue(esito["rimando_esterno"]["sopravvive"],
                        "lo strumento di misura non funziona su questa macchina")
        self.assertTrue(esito["rimando_nuovo"]["sopravvive"], esito)
        self.assertGreater(esito["dopo_la_riparazione"]["salti_veri"], 0, esito)
        self.assertEqual(
            0, esito["dopo_la_riparazione"]["sentinella_rimasto_nel_file"], esito)
        self.assertTrue(esito["verdetto"])

    def test_non_chiama_nessuno_e_non_costa_niente(self):
        """Questa rotta e' pubblica: deve restare gratis anche se qualcuno la
        apre cento volte. Nessuna chiamata a Claude, a Google o a Wikimedia."""
        sorgente = (
            __import__("pathlib").Path(prova_stampa.__file__).read_text(encoding="utf-8"))
        codice = re.sub(r'""".*?"""', "", sorgente, flags=re.S)
        codice = re.sub(r"(?m)^\s*#.*$", "", codice)
        for costoso in ("anthropic", "claude", "requests", "googleapis",
                        "wikimedia", "urlopen"):
            with self.subTest(costoso=costoso):
                self.assertNotIn(costoso, codice.lower())

    def test_un_guasto_qualunque_non_butta_giu_il_servizio(self):
        # Una diagnostica che solleva e' una diagnostica che manca proprio
        # quando serve. Qui si rompe la stampa di proposito.
        vero = prova_stampa._stampa
        prova_stampa._stampa = lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError("motore esploso"))
        try:
            esito = prova_stampa.prova_collegamenti()
        finally:
            prova_stampa._stampa = vero
        self.assertIn("errore", esito)
        self.assertIn("motore esploso", esito["errore"])


class TestLaRottaPubblica(unittest.TestCase):

    def setUp(self):
        import service

        service.app.config["TESTING"] = True
        self.client = service.app.test_client()

    def test_si_apre_senza_chiave(self):
        # Deve funzionare da telefono, con un tocco, senza incollare niente:
        # e' l'unico modo perche' venga davvero usata.
        risposta = self.client.get("/prova-collegamenti")
        self.assertEqual(200, risposta.status_code)
        self.assertIn("verdetto", risposta.get_json())

    def test_non_racconta_niente_di_nessuno(self):
        """Pubblica si puo' essere solo se non c'e' niente da proteggere."""
        testo = self.client.get("/prova-collegamenti").get_data(as_text=True)
        for riservato in ("@", "sk-", "SERVICE_API_KEY", "Bearer"):
            with self.subTest(riservato=riservato):
                self.assertNotIn(riservato, testo)

    def test_si_puo_spegnere_senza_rifare_un_deploy(self):
        import os
        from unittest import mock

        with mock.patch.dict(os.environ, {"PROVA_STAMPA_SPENTA": "si"}):
            self.assertEqual(403, self.client.get("/prova-collegamenti").status_code)


if __name__ == "__main__":
    unittest.main()
