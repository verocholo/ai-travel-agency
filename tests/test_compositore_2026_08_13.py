"""Il compositore non puo' produrre una pagina brutta (task #213).

PERCHE' QUESTO FILE ESISTE

Lorenzo: «non bastano 3 layout devi essere tu in grado di diversificare ogni
volta». Da qui nasce `src/compositore.py`: non piu' N pagine disegnate a mano,
ma pezzi e regole con cui montarle.

Il guaio di un sistema cosi' e' preciso: **con centinaia di combinazioni non
le si puo' guardare tutte.** Quindi la qualita' non puo' dipendere dall'averle
viste. Deve dipendere dalle regole — e le regole vanno verificate come
PROPRIETA', non elencando i casi buoni.

Per questo qui sotto non c'e' quasi nessun «con questi ingressi esce questo».
Ci sono affermazioni del tipo «per QUALUNQUE viaggio, per QUALUNQUE giornata,
non succede mai che...». Un controllo scritto sui casi buoni sarebbe verde e
non direbbe niente sui casi che nessuno ha immaginato, che in un sistema
combinatorio sono la maggioranza.

## I due difetti che questi controlli bloccano, e che erano gia' usciti

**Pagine gemelle.** Sui primi provini le giornate 4 e 5 erano identiche,
ornamenti compresi: quando una giornata non ha fotografie resta un impianto
solo, e la regola «mai due volte di fila» cede in silenzio. Non si e' visto
ragionando — si e' visto stampandone dodici e guardandole.

**Testate gemelle.** «A colpo d'occhio» e «Piani B» pretendevano sempre
l'apertura piu' forte, e quando capitavano vicine si ripetevano.
"""

import unittest

from src import compositore


VIAGGI = ("Siena", "Santorini", "Marrakech", "Reykjavik", "Tokyo",
          "Bologna", "Lisbona", "Isole Lofoten")


class TestNonEsceMaiUnaPaginaChePromettePiuDiQuelloCheHa(unittest.TestCase):
    """La regola che protegge dalla pagina sbagliata, non da quella povera."""

    def test_nessun_impianto_chiede_piu_fotografie_di_quante_ce_ne_sono(self):
        for viaggio in VIAGGI:
            for disponibili in range(0, 6):
                for indice in range(1, 15):
                    ricetta = compositore.componi(viaggio, indice, disponibili)
                    with self.subTest(viaggio=viaggio, foto=disponibili, g=indice):
                        self.assertLessEqual(
                            ricetta["impianto"]["foto"], disponibili,
                            "un impianto costruito attorno a fotografie che non "
                            "ci sono non e' una pagina piu' povera: e' una "
                            "pagina sbagliata")

    def test_senza_fotografie_resta_solo_l_impianto_tipografico(self):
        for viaggio in VIAGGI:
            with self.subTest(viaggio=viaggio):
                self.assertEqual(
                    "numero-gigante",
                    compositore.componi(viaggio, 1, 0)["impianto"]["nome"])

    def test_con_le_fotografie_l_impianto_tipografico_non_esce_mai(self):
        """Il ripiego deve restare un ripiego.

        `numero-gigante` non chiede fotografie, quindi senza un taglio
        esplicito risulterebbe sempre fra i possibili e uscirebbe anche
        quando le immagini ci sono: una pagina spoglia al posto di una
        illustrata, per niente.
        """
        for viaggio in VIAGGI:
            for indice in range(1, 20):
                nome = compositore.componi(viaggio, indice, 4)["impianto"]["nome"]
                with self.subTest(viaggio=viaggio, g=indice):
                    self.assertNotEqual("numero-gigante", nome)


class TestNonEsceMaiUnaPaginaSovraccarica(unittest.TestCase):

    def test_mai_piu_di_due_ornamenti(self):
        # Tre fanno volantino, e questo documento si vende a 4,90: deve
        # sembrare un prodotto, non una promozione.
        for viaggio in VIAGGI:
            for disponibili in (0, 1, 3, 5):
                for indice in range(1, 15):
                    quanti = len(compositore.componi(
                        viaggio, indice, disponibili)["ornamenti"])
                    with self.subTest(viaggio=viaggio, foto=disponibili, g=indice):
                        self.assertLessEqual(quanti, compositore.MASSIMO_ORNAMENTI)

    def test_c_e_sempre_almeno_un_ornamento(self):
        # Una pagina senza nessun carattere e' la pagina di prima: corretta e
        # anonima, cioe' il punto da cui siamo partiti.
        for viaggio in VIAGGI:
            for indice in range(1, 15):
                with self.subTest(viaggio=viaggio, g=indice):
                    self.assertTrue(compositore.componi(viaggio, indice, 4)["ornamenti"])

    def test_nessuna_coppia_vietata_esce_mai(self):
        for viaggio in VIAGGI:
            for disponibili in (0, 1, 2, 3, 5):
                for indice in range(1, 20):
                    scelti = set(compositore.componi(
                        viaggio, indice, disponibili)["ornamenti"])
                    for vietata in compositore.INCOMPATIBILI:
                        with self.subTest(viaggio=viaggio, g=indice,
                                          vietata=sorted(vietata)):
                            self.assertFalse(
                                vietata <= scelti,
                                f"la coppia vietata {sorted(vietata)} e' finita "
                                "insieme sulla stessa pagina")

    def test_la_foto_tonda_non_esce_quando_ce_n_e_una_sola(self):
        """E' un ornamento IN PIU', non l'unica immagine della pagina.

        Con una fotografia sola se la prenderebbe l'ornamento e l'impianto
        resterebbe senza la sua apertura.
        """
        for viaggio in VIAGGI:
            for indice in range(1, 20):
                for disponibili in (0, 1):
                    with self.subTest(viaggio=viaggio, g=indice, foto=disponibili):
                        self.assertNotIn("tonda", compositore.componi(
                            viaggio, indice, disponibili)["ornamenti"])


class TestNonEsconoMaiDuePAGINEGEMELLEDIFILA(unittest.TestCase):
    """[DIFETTO VERO, VISTO SUI PROVINI 2026-08-13.]

    Le giornate 4 e 5 erano identiche, ornamenti compresi. Quando una giornata
    non ha fotografie resta un impianto solo e la regola «mai due volte di
    fila» non ha piu' niente fra cui scegliere: cede in silenzio.

    Due pagine gemelle attaccate si vedono anche sfogliando in fretta, ed e'
    esattamente cio' che questo sistema esiste per evitare.
    """

    def _sequenza(self, viaggio, quante=14, scoperte=(5, 10)):
        fuori, precedente = [], None
        for indice in range(1, quante + 1):
            disponibili = 0 if indice in scoperte else 4
            ricetta = compositore.componi(viaggio, indice, disponibili, precedente)
            fuori.append((ricetta["impianto"]["nome"], tuple(ricetta["ornamenti"])))
            precedente = ricetta
        return fuori

    def test_mai_due_ricette_identiche_di_fila(self):
        for viaggio in VIAGGI:
            sequenza = self._sequenza(viaggio)
            gemelle = [i for i, (a, b) in enumerate(zip(sequenza, sequenza[1:]))
                       if a == b]
            with self.subTest(viaggio=viaggio):
                self.assertEqual([], gemelle,
                                 f"pagine gemelle attaccate in posizione {gemelle}: "
                                 f"{[sequenza[i] for i in gemelle]}")

    def test_mai_due_ricette_identiche_di_fila_nemmeno_tutte_scoperte(self):
        # Il caso estremo: NESSUNA giornata ha fotografie, quindi l'impianto
        # e' obbligato per tutte. E' la situazione in cui la regola aveva
        # ceduto.
        for viaggio in VIAGGI:
            sequenza = self._sequenza(viaggio, scoperte=tuple(range(1, 15)))
            gemelle = [i for i, (a, b) in enumerate(zip(sequenza, sequenza[1:]))
                       if a == b]
            with self.subTest(viaggio=viaggio):
                self.assertEqual([], gemelle)

    def test_un_viaggio_lungo_usa_piu_di_un_paio_di_impianti(self):
        # Senza questo, «mai due di fila» si potrebbe soddisfare alternando
        # sempre gli stessi due: formalmente a posto, e identico a prima.
        for viaggio in VIAGGI:
            impianti = {n for n, _ in self._sequenza(viaggio, quante=14, scoperte=())}
            with self.subTest(viaggio=viaggio):
                self.assertGreaterEqual(len(impianti), 4, sorted(impianti))


class TestLoStessoViaggioDaSempreLoStessoDocumento(unittest.TestCase):
    """Un documento che cambia a ogni esecuzione e' impossibile da collaudare,
    e un difetto che compare una volta su sei non si ripara mai perche'
    nessuno riesce a riprodurlo."""

    def test_ripetendo_esce_sempre_uguale(self):
        for viaggio in VIAGGI:
            uno = compositore.componi(viaggio, 3, 4)
            for _ in range(5):
                with self.subTest(viaggio=viaggio):
                    self.assertEqual(uno, compositore.componi(viaggio, 3, 4))

    def test_due_viaggi_diversi_non_prendono_la_stessa_sequenza(self):
        def seq(v):
            fuori, prec = [], None
            for i in range(1, 9):
                r = compositore.componi(v, i, 4, prec)
                fuori.append(r["impianto"]["nome"])
                prec = r
            return tuple(fuori)

        sequenze = {v: seq(v) for v in VIAGGI}
        self.assertGreaterEqual(
            len(set(sequenze.values())), len(VIAGGI) - 1,
            f"viaggi diversi ricevono la stessa sequenza di pagine: {sequenze}")

    def test_nessuna_traccia_di_casualita_nel_codice(self):
        """La scorciatoia che toglierebbe la ripetibilita' in una riga.

        `random` darebbe varieta' subito e costerebbe il collaudo. Questo
        controllo esiste perche' quella riga non venga scritta la prossima
        volta che qualcuno ha fretta.
        """
        import pathlib
        import re

        sorgente = pathlib.Path(compositore.__file__).read_text(encoding="utf-8")
        codice = re.sub(r'""".*?"""', "", sorgente, flags=re.S)
        codice = re.sub(r"(?m)^\s*#.*$", "", codice)
        for vietato in ("import random", "random.", "shuffle", "time.time"):
            with self.subTest(vietato=vietato):
                self.assertNotIn(vietato, codice)


class TestLeTestateDeiCapitoli(unittest.TestCase):

    def test_mai_la_stessa_testata_due_capitoli_di_fila(self):
        capitoli = ("colpo-docchio", "alloggio", "selezione", "costi", "consigli",
                    "piani-b", "prima-di-partire", "vademecum", "recensione")
        forti = {"colpo-docchio", "piani-b"}
        for viaggio in VIAGGI:
            precedente, sequenza = None, []
            for nome in capitoli:
                modo = compositore.testata(viaggio, nome, precedente,
                                           forte=nome in forti)
                sequenza.append(modo)
                precedente = modo
            gemelle = [i for i, (a, b) in enumerate(zip(sequenza, sequenza[1:]))
                       if a == b]
            with self.subTest(viaggio=viaggio):
                self.assertEqual([], gemelle, sequenza)

    def test_i_capitoli_di_racconto_prendono_l_apertura_forte(self):
        self.assertEqual(compositore.TESTATA_FORTE,
                         compositore.testata("Siena", "piani-b", None, forte=True))

    def test_ma_non_se_il_capitolo_prima_aveva_gia_quella(self):
        # [DIFETTO VISTO SUI PROVINI.] Due testate gemelle attaccate si vedono
        # sfogliando.
        self.assertEqual(
            compositore.TESTATA_FORTE_ALTERNATIVA,
            compositore.testata("Siena", "piani-b", compositore.TESTATA_FORTE,
                                forte=True))

    def test_le_testate_usate_sono_piu_di_due(self):
        modi = {compositore.testata("Siena", f"capitolo-{i}") for i in range(30)}
        self.assertGreaterEqual(len(modi), 3, sorted(modi))


class TestOgniGiornataHaLeFotografie(unittest.TestCase):
    """Richiesta secca di Lorenzo. La garanzia e' costruita a gradini, e ogni
    gradino resta VERO: non si spaccia una foto generica per la tappa del
    giorno, perche' la regola di questo prodotto e' che non si inventa
    niente."""

    def test_se_la_giornata_ha_le_sue_si_usano_le_sue(self):
        avute, da_dove = compositore.foto_della_giornata(
            ["a", "b"], ["x", "y"], "z", 1)
        self.assertEqual(["a", "b"], avute)
        self.assertEqual("proprie", da_dove)

    def test_senza_le_proprie_si_prendono_in_prestito_dal_viaggio(self):
        avute, da_dove = compositore.foto_della_giornata([], ["x", "y"], "z", 1)
        self.assertTrue(avute)
        self.assertEqual("dal viaggio", da_dove)

    def test_le_foto_prestate_ruotano_col_giorno(self):
        """Prendendo sempre la prima disponibile, tutte le giornate scoperte
        dello stesso viaggio mostrerebbero la stessa identica immagine — e
        quello si nota subito."""
        prime = [compositore.foto_della_giornata([], ["x", "y", "z"], None, g)[0][0]
                 for g in (1, 2, 3)]
        self.assertEqual(3, len(set(prime)), prime)

    def test_all_ultimo_gradino_resta_la_destinazione(self):
        avute, da_dove = compositore.foto_della_giornata([], [], "citta", 1)
        self.assertEqual(["citta"], avute)
        self.assertEqual("della destinazione", da_dove)

    def test_senza_nessuna_immagine_lo_dice_invece_di_fingere(self):
        # Succede solo se manca la chiave di Google o se la rete cade: un
        # guasto di configurazione, non una giornata sfortunata. La pagina
        # deve reggere lo stesso — un fascicolo che non parte e' peggio di uno
        # senza fotografie.
        avute, da_dove = compositore.foto_della_giornata([], [], None, 1)
        self.assertEqual([], avute)
        self.assertEqual("nessuna", da_dove)

    def test_la_provenienza_torna_sempre_indietro(self):
        """Non e' un di piu': chi stampa deve poter scrivere una didascalia
        onesta, e chi legge una diagnosi deve poter vedere quante giornate
        hanno dovuto prendere in prestito."""
        for proprie, viaggio, destinazione in (
                (["a"], [], None), ([], ["b"], None), ([], [], "c"), ([], [], None)):
            with self.subTest(caso=str((proprie, viaggio, destinazione))):
                self.assertIn(
                    compositore.foto_della_giornata(
                        proprie, viaggio, destinazione, 1)[1],
                    ("proprie", "dal viaggio", "della destinazione", "nessuna"))

    def test_dati_strampalati_non_fanno_cadere_niente(self):
        for caso in ((None, None, None), ((), (), ""), ([], None, None)):
            with self.subTest(caso=str(caso)):
                avute, _ = compositore.foto_della_giornata(*caso, 1)
                self.assertEqual([], avute)


class TestLIntegritaDelCatalogo(unittest.TestCase):
    """Se un pezzo del catalogo si rompe, il difetto non da' errore: produce
    una pagina che manca di qualcosa, in silenzio."""

    def test_ogni_impianto_ha_nome_descrizione_e_quante_foto_vuole(self):
        for impianto in compositore.IMPIANTI:
            with self.subTest(impianto=impianto.get("nome")):
                self.assertTrue(impianto.get("nome"))
                self.assertTrue(impianto.get("descrizione"))
                self.assertIsInstance(impianto.get("foto"), int)

    def test_i_nomi_degli_impianti_non_si_ripetono(self):
        nomi = [i["nome"] for i in compositore.IMPIANTI]
        self.assertEqual(len(nomi), len(set(nomi)))

    def test_c_e_esattamente_un_ripiego_senza_fotografie(self):
        # Zero: le giornate senza immagini non avrebbero nessun impianto e la
        # pagina non uscirebbe. Due o piu': il ripiego smetterebbe di essere
        # l'ultima spiaggia e comincerebbe a vincere anche altrove.
        self.assertEqual(1, sum(1 for i in compositore.IMPIANTI if i["foto"] == 0))

    def test_le_coppie_vietate_parlano_di_ornamenti_che_esistono(self):
        # Una regola scritta su un ornamento rinominato non vieta piu' niente
        # e non lo dice: e' il modo piu' silenzioso di perdere un vincolo.
        for vietata in compositore.INCOMPATIBILI:
            for nome in vietata:
                with self.subTest(ornamento=nome):
                    self.assertIn(nome, compositore.ORNAMENTI)


if __name__ == "__main__":
    unittest.main()


class TestLeApertureDiGiornata(unittest.TestCase):
    """Il primo pezzo del compositore che entra davvero nel documento.

    Sono le aperture che si IMPILANO — non ridisegnano la pagina in colonne —
    perche' cambiare tutta la struttura della giornata in una volta vorrebbe
    dire rimettere in gioco insieme sette controlli di impaginazione. Questa
    settimana ha gia' mostrato due volte cosa succede: una singola immagine in
    piu' fa sfondare una pagina.
    """

    def test_mai_la_stessa_apertura_due_giornate_di_fila(self):
        for viaggio in VIAGGI:
            precedente, sequenza = None, []
            for giorno in range(1, 13):
                modo = compositore.scegli_apertura(viaggio, giorno, 4, precedente)
                sequenza.append(modo)
                precedente = modo
            gemelle = [i for i, (a, b) in enumerate(zip(sequenza, sequenza[1:]))
                       if a == b]
            with self.subTest(viaggio=viaggio):
                self.assertEqual([], gemelle, sequenza)

    def test_il_mosaico_non_esce_se_non_ci_sono_tre_fotografie(self):
        # Tre riquadri di cui due vuoti non sono un mosaico piu' povero: sono
        # una pagina rotta.
        for viaggio in VIAGGI:
            for disponibili in (1, 2):
                for giorno in range(1, 12):
                    with self.subTest(viaggio=viaggio, foto=disponibili, g=giorno):
                        self.assertNotEqual("mosaico", compositore.scegli_apertura(
                            viaggio, giorno, disponibili))

    def test_senza_fotografie_non_si_apre_niente(self):
        # La giornata torna a com'era prima: solo il titolo. E' il ripiego, ed
        # e' una cosa gia' vista funzionare.
        for viaggio in VIAGGI:
            with self.subTest(viaggio=viaggio):
                self.assertEqual("", compositore.scegli_apertura(viaggio, 1, 0))

    def test_con_le_fotografie_un_apertura_c_e_sempre(self):
        for viaggio in VIAGGI:
            for disponibili in (1, 2, 3, 8):
                for giorno in range(1, 12):
                    with self.subTest(viaggio=viaggio, foto=disponibili, g=giorno):
                        self.assertTrue(compositore.scegli_apertura(
                            viaggio, giorno, disponibili))

    def test_un_viaggio_lungo_le_usa_tutte(self):
        # Senza questo, «mai due di fila» si soddisfa alternandone sempre due.
        usate = set()
        precedente = None
        for giorno in range(1, 16):
            modo = compositore.scegli_apertura("Siena", giorno, 4, precedente)
            usate.add(modo)
            precedente = modo
        self.assertEqual({a["nome"] for a in compositore.APERTURE}, usate)

    def test_e_ripetibile(self):
        uno = [compositore.scegli_apertura("Siena", g, 4) for g in range(1, 9)]
        due = [compositore.scegli_apertura("Siena", g, 4) for g in range(1, 9)]
        self.assertEqual(uno, due)

    def test_ogni_apertura_dichiara_quante_foto_vuole(self):
        for apertura in compositore.APERTURE:
            with self.subTest(apertura=apertura.get("nome")):
                self.assertTrue(apertura.get("nome"))
                self.assertTrue(apertura.get("descrizione"))
                self.assertGreaterEqual(apertura.get("foto"), 1)
