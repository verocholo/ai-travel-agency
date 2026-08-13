"""Sapere quali file in produzione sono vecchi (task #208).

PERCHE' QUESTO FILE ESISTE

La pagina `/prova-collegamenti`, il giorno stesso in cui e' stata accesa, ha
risposto:

    {"errore": "TypeError: cuci() got an unexpected keyword argument 'ancore'"}

`pdf_renderer.py` in produzione era quello nuovo, `fascicolo.py` era rimasto
quello vecchio. Il servizio rispondeva normalmente a tutto il resto e sarebbe
morto **solo** al momento di cucire il fascicolo, cioe' dopo dodici minuti di
generazione gia' pagata.

Il file dimenticato e' l'incidente. Il difetto e' che non c'era **nessun modo**
di sapere quali file fossero vecchi: il codice arriva in produzione a mano, un
caricamento alla volta, da un telefono, su cinquantacinque moduli, seguendo un
elenco che scrivo io a ogni giro. Prima o poi ne salta uno — ed e' successo.

`/impronte` chiude questa classe di guasti: dice l'impronta di ogni file, si
confronta con quella dei file che ho in mano, e l'elenco di cosa ricaricare
esce da solo.

I controlli qui sotto difendono le tre cose che rendono quell'elenco
affidabile: che copra i file giusti, che sappia davvero distinguere due
versioni, e che nel confronto non annacqui la differenza fra «diverso» e
«mancante» — che da telefono sono due gesti diversi.
"""

import hashlib
import unittest
from pathlib import Path

from src import impronte


class TestLImprontaDistingueDavveroDueVersioni(unittest.TestCase):

    def test_due_file_diversi_hanno_impronte_diverse(self):
        import tempfile

        cartella = Path(tempfile.mkdtemp())
        a, b = cartella / "a.py", cartella / "b.py"
        a.write_text("ancore=None", encoding="utf-8")
        b.write_text("ancore=None ", encoding="utf-8")  # uno spazio in piu'
        self.assertNotEqual(impronte._impronta(a), impronte._impronta(b),
                            "due versioni diverse risultano uguali: l'elenco "
                            "di cosa ricaricare sarebbe inutile")

    def test_lo_stesso_contenuto_da_la_stessa_impronta(self):
        import tempfile

        cartella = Path(tempfile.mkdtemp())
        a, b = cartella / "a.py", cartella / "b.py"
        for f in (a, b):
            f.write_text("uguale", encoding="utf-8")
        self.assertEqual(impronte._impronta(a), impronte._impronta(b))

    def test_e_la_stessa_impronta_che_calcolo_io_da_qui(self):
        """Il pezzo che rende il confronto una prova e non un'opinione.

        Se il servizio calcolasse l'impronta in un modo e io in un altro,
        risulterebbe TUTTO diverso, ogni volta, e l'unico consiglio possibile
        tornerebbe a essere «ricarica tutto» — cioe' il problema di partenza.
        """
        percorso = Path(impronte.__file__)
        atteso = hashlib.sha256(percorso.read_bytes()).hexdigest()[:impronte.CIFRE]
        self.assertEqual(atteso, impronte._impronta(percorso))

    def test_si_legge_in_binario_e_gli_a_capo_contano(self):
        # Un file arrivato con gli a-capo di Windows E' un file diverso, e in
        # un `Procfile` la differenza cambia il comportamento. Meglio una
        # differenza segnalata in piu' che una vera taciuta.
        import tempfile

        cartella = Path(tempfile.mkdtemp())
        unix, windows = cartella / "u.txt", cartella / "w.txt"
        unix.write_bytes(b"riga\n")
        windows.write_bytes(b"riga\r\n")
        self.assertNotEqual(impronte._impronta(unix), impronte._impronta(windows))


class TestLElencoCopreCioCheContaDavvero(unittest.TestCase):

    def setUp(self):
        self.trovate = impronte.impronte()

    def test_ci_sono_tutti_i_moduli_del_prodotto(self):
        quanti = len(list((impronte.RADICE / "src").glob("*.py")))
        presenti = [n for n in self.trovate if n.startswith("src/")]
        self.assertEqual(quanti, len(presenti))
        self.assertGreater(quanti, 40, "mancano moduli: l'elenco non copre il "
                                       "prodotto e un file vecchio potrebbe "
                                       "restare invisibile")

    def test_ci_sono_i_file_di_radice_che_fanno_partire_il_servizio(self):
        # `service.py` e' proprio quello che oggi e' arrivato per ultimo, e
        # `Dockerfile` decide quale motore di stampa viene installato: sono i
        # due file il cui ritardo si paga di piu'.
        for nome in ("service.py", "requirements.txt", "Dockerfile"):
            with self.subTest(nome=nome):
                self.assertIn(nome, self.trovate)

    def test_i_file_di_prova_non_entrano(self):
        # Le prove non girano in produzione: metterle qui vorrebbe dire
        # chiedere a Lorenzo di ricaricare file che non cambiano niente.
        self.assertEqual([], [n for n in self.trovate if n.startswith("tests")])

    def test_fascicolo_e_pdf_renderer_ci_sono_tutti_e_due(self):
        """I due protagonisti del guasto del 13 agosto.

        Erano disallineati fra loro, e nessuna pagina di questo servizio
        poteva dirlo.
        """
        self.assertIn("src/fascicolo.py", self.trovate)
        self.assertIn("src/pdf_renderer.py", self.trovate)

    def test_ogni_impronta_e_corta_e_leggibile_da_telefono(self):
        for nome, valore in self.trovate.items():
            with self.subTest(nome=nome):
                self.assertEqual(impronte.CIFRE, len(valore))


class TestIlConfrontoDiceCosaFareSenzaFarLoCapireANessuno(unittest.TestCase):

    def test_quando_tutto_torna_lo_dice_e_basta(self):
        esito = impronte.confronta(impronte.impronte())
        self.assertTrue(esito["tutto_allineato"])
        self.assertEqual([], esito["da_ricaricare"])
        self.assertEqual([], esito["mancanti"])

    def test_un_file_vecchio_finisce_fra_quelli_da_ricaricare(self):
        attese = dict(impronte.impronte())
        attese["src/fascicolo.py"] = "000000000000"
        esito = impronte.confronta(attese)
        self.assertEqual(["src/fascicolo.py"], esito["da_ricaricare"])
        self.assertFalse(esito["tutto_allineato"])

    def test_un_file_mai_arrivato_non_viene_confuso_con_uno_vecchio(self):
        """Da telefono sono due gesti diversi: uno si carica sopra, l'altro va
        creato. Un elenco unico costringerebbe a scoprirlo file per file."""
        attese = dict(impronte.impronte())
        attese["src/mai_caricato.py"] = "000000000000"
        esito = impronte.confronta(attese)
        self.assertEqual(["src/mai_caricato.py"], esito["mancanti"])
        self.assertEqual([], esito["da_ricaricare"])

    def test_un_file_di_troppo_si_vede_ma_non_allarma(self):
        # Un file rimasto li' da una prova vecchia non e' un guasto e non
        # deve comparire nell'elenco di cosa ricaricare.
        attese = {n: v for n, v in impronte.impronte().items()
                  if n != "src/impronte.py"}
        esito = impronte.confronta(attese)
        self.assertIn("src/impronte.py", esito["non_previsti"])
        self.assertTrue(esito["tutto_allineato"])


class TestLaRottaPubblica(unittest.TestCase):

    def setUp(self):
        import service

        service.app.config["TESTING"] = True
        self.client = service.app.test_client()

    def test_risponde_senza_chiave(self):
        risposta = self.client.get("/impronte")
        self.assertEqual(200, risposta.status_code)
        self.assertIn("src/fascicolo.py", risposta.get_json()["file"])

    def test_non_esce_una_riga_di_codice(self):
        """E' l'unico motivo per cui questa pagina puo' restare pubblica.

        Un'impronta non si riapre: e' un numero ricavato dal contenuto, non
        il contenuto. Se un giorno qualcuno ci aggiungesse un'anteprima «per
        comodita'», questa pagina diventerebbe una lettura del codice
        sorgente aperta a chiunque.
        """
        testo = self.client.get("/impronte").get_data(as_text=True)
        for spia in ("def ", "import ", "@app.route", "SERVICE_API_KEY", "sk-"):
            with self.subTest(spia=spia):
                self.assertNotIn(spia, testo)


if __name__ == "__main__":
    unittest.main()
