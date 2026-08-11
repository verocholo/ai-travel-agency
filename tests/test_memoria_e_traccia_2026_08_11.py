"""La traccia che un processo morto lascia dietro di se' (task #197).

PERCHE' QUESTO FILE ESISTE

Il 10 e l'11 agosto 2026 due esecuzioni di produzione sono morte allo stesso
identico punto — 368,9 e 372,9 secondi, stesse quattro operazioni, stessi
4.185 byte scambiati — con un `502 Bad Gateway`. Un 502 non lo scrive il
nostro servizio: e' il portone che dice «dietro di me non risponde nessuno».
Il contenitore si era spento mentre lavorava.

E un processo morto non scrive niente, per definizione. Nei log non c'era
niente da leggere, nella risposta nemmeno, e la diagnosi si era ridotta a
chiedere a Lorenzo di aprire cruscotti e mandare fotografie dello schermo —
cioe' a farlo lavorare per un guasto nostro.

Da qui in poi il lavoro lascia una traccia MENTRE e' vivo: ogni cinque secondi
scrive su disco da quanto sta lavorando e quanta memoria occupa. Quando muore,
l'ultima riga resta. La domanda che decide se spendere venticinque dollari al
mese e' una sola — **con quanta memoria stava girando quando e' morto?** — e
adesso ha una risposta scritta invece che una supposizione.

La traccia non contiene niente di nessuno: secondi e megabyte.
"""

import json
import os
import tempfile
import unittest

from src import lavori


class TestLaTracciaEsisteEDiceIlNecessario(unittest.TestCase):

    def setUp(self):
        self._cartella = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        os.environ["LAVORI_DIR"] = self._cartella.name

    def tearDown(self):
        self._cartella.cleanup()
        os.environ.pop("LAVORI_DIR", None)

    def test_la_memoria_si_misura_davvero(self):
        # Se questo tornasse None su Linux, tutta la traccia sarebbe una
        # colonna di caselle vuote proprio nel momento in cui serve.
        valore = lavori.memoria_mb()
        self.assertIsNotNone(valore, "la misura della memoria non funziona")
        self.assertGreater(valore, 1)

    def test_il_battito_scrive_secondi_e_megabyte(self):
        identificativo = lavori.nuovo()
        lavori.batti(identificativo)
        dati = lavori.leggi(identificativo)
        self.assertEqual(dati["stato"], "in_corso")
        for campo in ("da_secondi", "memoria_mb", "memoria_massima_mb"):
            with self.subTest(campo=campo):
                self.assertIn(campo, dati)

    def test_il_massimo_non_scende_mai(self):
        # Il numero che conta e' il PICCO: al momento della morte la memoria
        # e' gia' stata restituita, e leggere l'ultimo valore invece del piu'
        # alto racconterebbe una bugia rassicurante.
        identificativo = lavori.nuovo()
        lavori.batti(identificativo)
        percorso = lavori.cartella() / f"{identificativo}.json"
        dati = json.loads(percorso.read_text(encoding="utf-8"))
        dati["memoria_massima_mb"] = 999999.0
        percorso.write_text(json.dumps(dati), encoding="utf-8")
        lavori.batti(identificativo)
        self.assertEqual(lavori.leggi(identificativo)["memoria_massima_mb"], 999999.0)

    def test_il_battito_non_tocca_un_lavoro_gia_finito(self):
        # Sarebbe il modo piu' sciocco di perdere un documento gia' pronto:
        # un filone in ritardo che riscrive sopra l'esito.
        identificativo = lavori.nuovo()
        lavori.salva_esito(identificativo, {"pdf_base64": "eccolo"}, 200)
        lavori.batti(identificativo)
        dati = lavori.leggi(identificativo)
        self.assertEqual(dati["stato"], "pronto")
        self.assertEqual(dati["corpo"]["pdf_base64"], "eccolo")

    def test_il_battito_su_un_numero_inventato_non_solleva(self):
        for storto in ("../../etc/passwd", "", None, "mai-esistito-1234"):
            with self.subTest(storto=storto):
                lavori.batti(storto)


class TestLaPaginaDiStatoNonDiceNientaDiNessuno(unittest.TestCase):
    """Non ha chiave, quindi deve poter essere letta da chiunque senza danno."""

    def setUp(self):
        self._cartella = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        os.environ["LAVORI_DIR"] = self._cartella.name
        import service

        self.servizio = service
        self.client = service.app.test_client()

    def tearDown(self):
        self._cartella.cleanup()
        os.environ.pop("LAVORI_DIR", None)

    def test_si_apre_senza_chiave(self):
        # Il punto di tutta la pagina: si guarda dal telefono, con un tocco,
        # senza incollare una chiave dentro un browser.
        self.assertEqual(self.client.get("/salute-lavori").status_code, 200)

    def test_dice_la_memoria_e_da_quanto_e_acceso(self):
        dati = self.client.get("/salute-lavori").get_json()
        self.assertIsNotNone(dati["memoria_adesso_mb"])
        self.assertIn("acceso_da_secondi", dati)

    def test_non_esce_niente_del_cliente(self):
        identificativo = lavori.nuovo()
        lavori.salva_esito(identificativo, {
            "pdf_base64": "SEGRETISSIMO",
            "trip": {"email": "cliente@esempio.it", "destination": "Siena"},
        }, 200)
        testo = self.client.get("/salute-lavori").get_data(as_text=True)
        for vietato in ("SEGRETISSIMO", "cliente@esempio.it", "Siena"):
            with self.subTest(vietato=vietato):
                self.assertNotIn(vietato, testo)

    def test_il_numero_d_ordine_non_esce_per_intero(self):
        # Con il numero intero e la chiave si ritira il documento di un altro.
        # La chiave qui non c'e', ma meta' di un segreto non si regala.
        identificativo = lavori.nuovo()
        testo = self.client.get("/salute-lavori").get_data(as_text=True)
        self.assertNotIn(identificativo, testo)

    def test_dice_com_e_finito_l_ultimo_lavoro(self):
        identificativo = lavori.nuovo()
        lavori.batti(identificativo)
        ultimo = self.client.get("/salute-lavori").get_json()["ultimo_lavoro"]
        self.assertEqual(ultimo["stato"], "in_corso")
        self.assertIsNotNone(ultimo["memoria_massima_mb"])


class TestIlServizioNonSiPortaDietroLaPropriaSuiteDiTest(unittest.TestCase):
    """[REGRESSIONE 2026-08-11] L'etichetta su /health costava un import di tutto.

    `/health` mostra quanti test ha la suite, e il numero e' calcolato invece
    che scritto a mano — giusto, ed e' nato da una costante gia' disallineata.
    Il MODO pero' era `unittest.discover()`, che per contare i test **importa
    ogni file di prova del progetto**. Un modulo importato non si scarica: il
    contenitore che serve i clienti si teneva in memoria, per sempre, tutte le
    prove con le loro finte e i loro dati di esempio.

    E il costo cresceva da solo: 404 test quando la riga fu scritta, piu' di
    1600 oggi. Nessuno l'aveva toccata; era peggiorata quattro volte in
    silenzio.
    """

    def test_il_conteggio_e_ancora_quello_vero(self):
        """La cosa che rende sicura la riscrittura.

        Contare leggendo i file e' piu' economico ma deve dare lo STESSO
        numero di `unittest`, altrimenti abbiamo risparmiato memoria in cambio
        di una bugia sulla pagina di stato. La differenza non e' teorica: una
        prima versione ne perdeva dieci, quelli ereditati da una classe di
        prova che ne estende un'altra.
        """
        import unittest as _u

        import service

        radice = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        vero = _u.TestLoader().discover(
            start_dir=os.path.join(radice, "tests"), top_level_dir=radice
        ).countTestCases()
        self.assertEqual(service._conta_i_test_senza_eseguirli(), vero)

    def test_contare_non_importa_nessun_file_di_prova(self):
        """Il punto della riscrittura, verificato invece che sperato."""
        import subprocess
        import sys

        radice = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        programma = (
            "import sys, os; sys.path.insert(0, %r); "
            "os.environ['SERVICE_API_KEY']='x'; "
            "import service; service._conta_i_test_senza_eseguirli(); "
            "print(len([m for m in sys.modules if m.startswith('tests')]))"
        ) % radice
        uscita = subprocess.run([sys.executable, "-c", programma],
                                capture_output=True, text=True, cwd=radice)
        self.assertEqual(
            uscita.stdout.strip().splitlines()[-1], "0",
            "contare i test importa ancora i file di prova dentro il "
            "processo che serve i clienti")


class TestLeImpostazioniDiMemoriaRestanoAccese(unittest.TestCase):
    """[AGGIUNTO 2026-08-11] Due righe che valgono centinaia di megabyte.

    La libreria C di sistema, con piu' filoni, apre fino a otto aree di
    memoria per ogni processore e non le restituisce piu'. Su un contenitore
    da 512 MB e' un modo raffinato di sprecare memoria senza che nessuna riga
    di Python risulti colpevole. Sono due righe che nessuno guarderebbe mai
    piu': se sparissero, sparirebbero in silenzio.
    """

    def _dockerfile(self):
        import pathlib

        radice = pathlib.Path(__file__).resolve().parent.parent
        return (radice / "Dockerfile").read_text(encoding="utf-8")

    def test_le_aree_di_memoria_restano_poche(self):
        self.assertIn("MALLOC_ARENA_MAX=2", self._dockerfile())

    def test_la_memoria_liberata_torna_al_sistema(self):
        self.assertIn("MALLOC_TRIM_THRESHOLD_", self._dockerfile())


if __name__ == "__main__":
    unittest.main()
