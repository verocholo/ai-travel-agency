"""I colori del documento vengono dal posto, e non possono uscire brutti (task #209).

PERCHE' QUESTO FILE ESISTE

Lorenzo, 13 agosto 2026: «mi piacerebbe che l'estetica si adattasse al posto in
cui il cliente vuole andare».

Il rischio di questa idea e' tutto in una frase: **un colore scelto da un
programma finisce nel documento venduto senza che nessuno lo guardi.** Non c'e'
una persona fra la scelta e la casella di posta del cliente. Quindi la
domanda vera non e' «funziona?» ma «puo' produrre qualcosa di illeggibile o di
brutto?».

La risposta e' costruita in due pezzi, e i controlli qui sotto difendono
tutti e due:

**Le tavolozze sono disegnate a mano.** La fotografia non sceglie un colore:
sceglie fra otto tavolozze che qualcuno ha gia' guardato. Il peggio che possa
succedere e' una tavolozza poco azzeccata — non una brutta.

**Il contrasto e' verificato, non stimato.** Per ognuna delle otto, per ogni
ruolo, con la formula vera (WCAG). A occhio un blu chiaro su blu scuro sembra
sempre leggibile finche' non lo si guarda stampato su un telefono al sole.

## La parte che non e' ovvia: la stabilita'

Lo stesso viaggio, rigenerato, deve dare lo stesso documento. Un colore che
cambia fra due esecuzioni identiche e' un difetto che nessuno riesce a
riprodurre — e quindi non si ripara mai. Per questo la scelta e' deterministica
e c'e' un controllo che la ripete.
"""

import io
import unittest

from src import tavolozza


def _foto(rgb, righe_scure=True) -> bytes:
    from PIL import Image, ImageDraw

    immagine = Image.new("RGB", (240, 160), rgb)
    if righe_scure:
        disegno = ImageDraw.Draw(immagine)
        for x in range(0, 240, 40):
            disegno.rectangle([x, 0, x + 18, 160],
                              fill=tuple(max(0, c - 30) for c in rgb))
    fuori = io.BytesIO()
    immagine.save(fuori, format="JPEG", quality=85)
    return fuori.getvalue()


def _scatti(rgb, quanti=3, reale=True) -> dict:
    return {f"P{i}": {"png": _foto(rgb), "credito": "Prova", "reale": reale}
            for i in range(quanti)}


class TestNessunaTavolozzaPuoUscireIlleggibile(unittest.TestCase):
    """Il controllo che rende accettabile l'idea di far scegliere i colori a
    un programma. Senza, questa funzione non si potrebbe spedire."""

    # 4.5 e' la soglia sotto la quale un testo comincia a costare fatica.
    # Non e' un numero preso da un manuale a caso: e' quello su cui e'
    # tarata l'accessibilita' del web, e un PDF letto su un telefono in
    # viaggio e' piu' difficile di una pagina web, non meno.
    SOGLIA_TESTO = 4.5
    # Per il testo corrente su fondo chiaro si chiede molto di piu': e' la
    # parte che il cliente legge per trenta pagine di fila.
    SOGLIA_LETTURA = 7.0

    def test_ogni_tavolozza_regge_il_testo_bianco_sulla_fascia_scura(self):
        for t in tavolozza.TAVOLOZZE:
            with self.subTest(tavolozza=t["nome"]):
                self.assertGreaterEqual(
                    tavolozza.contrasto("#ffffff", t["scuro"]), self.SOGLIA_LETTURA,
                    f"'{t['nome']}': il titolo della fascia di testata non si legge")

    def test_ogni_colore_di_testo_si_legge_sul_bianco(self):
        for t in tavolozza.TAVOLOZZE:
            for ruolo in ("scuro", "primario", "accento_testo"):
                with self.subTest(tavolozza=t["nome"], ruolo=ruolo):
                    self.assertGreaterEqual(
                        tavolozza.contrasto(t[ruolo], "#ffffff"), self.SOGLIA_TESTO,
                        f"'{t['nome']}': il colore '{ruolo}' non si legge sulla pagina")

    def test_il_testo_corrente_si_legge_su_ogni_fondo_tenue(self):
        # I riquadri (avvisi, note, blocchi) hanno un fondo colorato chiaro e
        # dentro ci va il testo nero di sempre.
        for t in tavolozza.TAVOLOZZE:
            for ruolo in ("sfondo_tenue", "sfondo_caldo"):
                with self.subTest(tavolozza=t["nome"], ruolo=ruolo):
                    self.assertGreaterEqual(
                        tavolozza.contrasto(tavolozza.NEUTRI["inchiostro"], t[ruolo]),
                        self.SOGLIA_LETTURA,
                        f"'{t['nome']}': il testo dentro i riquadri '{ruolo}' e' faticoso")

    def test_i_due_ruoli_calcolati_si_leggono_sulla_propria_fascia(self):
        # Sono gli unici colori non scritti a mano: si ricavano schiarendo.
        # Proprio perche' nessuno li ha guardati uno per uno, vanno misurati.
        for t in tavolozza.TAVOLOZZE:
            piena = tavolozza.completa(t)
            for ruolo in ("chiaro_su_scuro", "accento_su_scuro"):
                with self.subTest(tavolozza=t["nome"], ruolo=ruolo):
                    self.assertGreaterEqual(
                        tavolozza.contrasto(piena[ruolo], piena["scuro"]),
                        self.SOGLIA_TESTO,
                        f"'{t['nome']}': '{ruolo}' sparisce sulla propria fascia")

    def test_ogni_tavolozza_ha_tutti_i_ruoli(self):
        """Un ruolo mancante non da' errore: lascia un `{{segnaposto}}` nel
        foglio di stile, che il motore di stampa ignora in silenzio. Il
        documento esce con un colore in meno e nessuno lo sa."""
        richiesti = {"nome", "descrizione", "tinta", "fredda", "scuro", "primario",
                     "accento", "accento_testo", "sfondo_tenue", "sfondo_caldo",
                     "bordo", "bordo_caldo"}
        for t in tavolozza.TAVOLOZZE:
            with self.subTest(tavolozza=t["nome"]):
                self.assertEqual(set(), richiesti - set(t))

    def test_i_nomi_non_si_ripetono(self):
        nomi = [t["nome"] for t in tavolozza.TAVOLOZZE]
        self.assertEqual(len(nomi), len(set(nomi)))

    def test_le_tinte_sono_sparse_e_non_ammucchiate(self):
        # Due tavolozze quasi sullo stesso angolo di colore vorrebbero dire
        # che una delle due non vince mai: peso morto che sembra scelta.
        tinte = sorted(float(t["tinta"]) for t in tavolozza.TAVOLOZZE)
        for prima, dopo in zip(tinte, tinte[1:]):
            with self.subTest(fra=(prima, dopo)):
                self.assertGreater(dopo - prima, 10.0)


class TestIlPostoSceglieDavveroIColori(unittest.TestCase):

    def test_un_posto_di_mattoni_prende_la_tavolozza_del_cotto(self):
        self.assertEqual("cotto", tavolozza.scegli(_scatti((168, 74, 38)))["nome"])

    def test_un_posto_di_mare_prende_quella_del_mare(self):
        self.assertEqual("mare", tavolozza.scegli(_scatti((32, 132, 178)))["nome"])

    def test_un_posto_di_verde_prende_quella_del_verde(self):
        self.assertEqual("verde", tavolozza.scegli(_scatti((46, 138, 92)))["nome"])

    def test_due_posti_diversi_non_danno_la_stessa_tavolozza(self):
        # E' la richiesta di Lorenzo ridotta all'osso.
        self.assertNotEqual(tavolozza.scegli(_scatti((168, 74, 38)))["nome"],
                            tavolozza.scegli(_scatti((32, 132, 178)))["nome"])

    def test_un_posto_senza_colore_non_finisce_fra_le_spezie(self):
        """Pietra, cemento, nebbia, neve.

        E' il caso in cui l'idea si rompe piu' facilmente: su una fotografia
        quasi grigia il vincitore lo decide il rumore, e un lampione giallo
        basterebbe a stabilire che Reykjavik e' una citta' di spezie. Sotto
        una certa saturazione si sceglie solo fra le tavolozze fredde.
        """
        scelta = tavolozza.scegli(_scatti((150, 152, 155)))
        self.assertTrue(
            scelta["fredda"],
            f"una fotografia senza colore ha scelto '{scelta['nome']}', che e' "
            "una tavolozza calda: il colore lo sta decidendo il rumore")


class TestQuandoNonSiSaSiRestaSuQuellaDiSempre(unittest.TestCase):
    """Il ripiego dev'essere una cosa gia' vista funzionare, non una nuova."""

    def test_senza_fotografie_si_usa_la_predefinita(self):
        for vuoto in (None, {}, "non un dizionario", []):
            with self.subTest(vuoto=str(vuoto)[:12]):
                self.assertEqual(tavolozza.PREDEFINITA["nome"],
                                 tavolozza.scegli(vuoto)["nome"])

    def test_le_copertine_disegnate_in_casa_non_votano(self):
        """Sono immagini fatte da noi: direbbero soltanto di che colore le
        disegniamo noi. La tavolozza si sceglierebbe guardandosi allo
        specchio invece di guardare il posto."""
        self.assertEqual(tavolozza.PREDEFINITA["nome"],
                         tavolozza.scegli(_scatti((168, 74, 38), reale=False))["nome"])

    def test_un_immagine_illeggibile_non_fa_cadere_niente(self):
        # Una fotografia rotta puo' costare la fotografia, mai il documento.
        rotte = {"P0": {"png": b"non una immagine", "credito": "x", "reale": True}}
        self.assertEqual(tavolozza.PREDEFINITA["nome"], tavolozza.scegli(rotte)["nome"])

    def test_dati_strampalati_non_fanno_cadere_niente(self):
        strani = {"A": None, "B": {"png": None, "reale": True}, "C": {"reale": True},
                  "D": {"png": b"", "reale": True}, "E": "boh"}
        self.assertTrue(tavolozza.scegli(strani)["nome"])


class TestLoStessoViaggioDaSempreLoStessoDocumento(unittest.TestCase):
    """Un colore che cambia fra due esecuzioni identiche e' un difetto che
    nessuno riesce a riprodurre — e quindi non si ripara mai."""

    def test_ripetendo_la_scelta_esce_sempre_uguale(self):
        scatti = _scatti((168, 74, 38), quanti=5)
        primi = [tavolozza.scegli(scatti)["nome"] for _ in range(5)]
        self.assertEqual(1, len(set(primi)), primi)

    def test_l_ordine_delle_fotografie_non_cambia_il_risultato(self):
        # I dizionari conservano l'ordine di inserimento: se la scelta
        # dipendesse da quale foto arriva prima, due generazioni dello stesso
        # viaggio potrebbero dare due colori diversi.
        scatti = _scatti((32, 132, 178), quanti=4)
        rovesciati = dict(reversed(list(scatti.items())))
        self.assertEqual(tavolozza.scegli(scatti)["nome"],
                         tavolozza.scegli(rovesciati)["nome"])


class TestLaMisuraDelContrastoEQuellaVera(unittest.TestCase):
    """Se questa formula fosse sbagliata, tutti i controlli qui sopra
    sarebbero verdi e non direbbero niente."""

    def test_bianco_su_nero_da_il_massimo(self):
        self.assertAlmostEqual(21.0, tavolozza.contrasto("#ffffff", "#000000"), places=1)

    def test_un_colore_con_se_stesso_da_il_minimo(self):
        self.assertAlmostEqual(1.0, tavolozza.contrasto("#2f6690", "#2f6690"), places=3)

    def test_non_conta_l_ordine(self):
        self.assertAlmostEqual(tavolozza.contrasto("#ffffff", "#1a3b5c"),
                               tavolozza.contrasto("#1a3b5c", "#ffffff"), places=6)

    def test_un_grigio_medio_sul_bianco_sta_sotto_soglia(self):
        # Un valore noto: #949494 su bianco sta appena sotto 4.5. Se questa
        # riga passasse, la formula sarebbe troppo generosa e lascerebbe
        # passare accostamenti faticosi.
        self.assertLess(tavolozza.contrasto("#949494", "#ffffff"), 4.5)


if __name__ == "__main__":
    unittest.main()
