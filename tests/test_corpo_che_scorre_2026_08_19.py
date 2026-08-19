"""Il corpo della scheda scorre fra le pagine invece di cascare tutto insieme.

PERCHE' QUESTO FILE ESISTE

Primo fascicolo VENDUTO a un cliente vero, 19 agosto, Singapore. Il giudizio,
testuale: «l'impaginazione e' ancora terribile, troppi spazi bianchi e pagine
con solo due righe o tasti di collegamento».

Misurato sul suo documento — ventitre pagine — otto difetti:

    pagina  2: 69.9%      pagina 16: COMPLETAMENTE BIANCA
    pagina 11: 59.4%      pagina 17: 59.4%
    pagina 13: 15.5%      pagina 19: 51.4%
    pagina 14: 56.4%      pagina 21: 62.1%

E la cosa piu' istruttiva: la mia anteprima, lo stesso giorno, diceva
«PROBLEMI: nessuno». Il campione era la META' di una scheda vera — meno
paragrafi di storia, meno sezioni, meno bottoni di ritorno — quindi il
difetto non poteva presentarsi. Un controllo che gira su un campione piu'
piccolo del vero non e' un controllo, e' una rassicurazione. Il campione di
questo file e' ricostruito misurando le schede del fascicolo venduto.

## I tre difetti, e la causa di ognuno

**1. Il corpo che casca (pagine 11, 14, 17, 19, 21).** Le sezioni sotto la
storia — cosa cercare, da sapere, consigli, informazioni pratiche — stavano
in una tabella a DUE CELLE, cioe' una riga sola. Una riga di tabella non si
spezza mai fra due pagine: o entrava tutta nello spazio rimasto sotto la
storia, o scendeva TUTTA sulla pagina dopo, lasciando quattro decimi di
foglio bianchi. Con schede vere non entrava mai. Adesso le sezioni vanno a
coppie, una riga per coppia: si vede uguale, ma la tabella puo' spezzarsi fra
due righe e il testo scorre.

**2. La pagina completamente bianca (pagina 16).** Il salto di pagina fra una
scheda e l'altra era un `<div>` vuoto messo prima della scheda. Un div vuoto
e' comunque un blocco: quando la scheda precedente finiva a filo di pagina,
il div si prendeva un foglio tutto suo. Adesso il salto e' una proprieta'
della scheda, non un elemento in piu'.

**3. La pagina con solo i bottoni (pagine 13 e 23).** Il blocco «Torna dove
eri» non si spezza mai — e deve restare cosi', perche' titolo e bottoni
separati erano il difetto di pagina 18 del fascicolo di Bologna. Quando non
entrava scendeva da solo su un foglio nuovo. Adesso si misura quanto occupa
la CODA di ogni scheda sulla facciata dove atterra: se e' troppo magra, si
stringe la fotografia di apertura per tirarla su.
"""

import re
import unittest

from src import poi_pdf


def _fotografia(seme):
    """Un'immagine vera (non due byte finti): il ritaglio panoramico che fa
    rientrare le schede lavora sui PIXEL, e su un finto non farebbe niente."""
    import io

    from PIL import Image, ImageDraw

    larghezza, altezza = 1400, 900
    immagine = Image.new("RGB", (larghezza, altezza))
    disegno = ImageDraw.Draw(immagine)
    tinta = [(150, 180, 215), (210, 200, 170), (120, 170, 200)][seme % 3]
    disegno.rectangle([0, 0, larghezza, altezza], fill=tinta)
    disegno.rectangle([0, int(altezza * 0.62), larghezza, altezza],
                      fill=(120, 110, 95))
    dentro = io.BytesIO()
    immagine.save(dentro, format="JPEG", quality=80)
    return dentro.getvalue()


def _guida(indice, storia=4, sezioni=True):
    """Una scheda della stessa taglia di quelle del fascicolo venduto."""
    paragrafo = ("Questo luogo ha una storia lunga che vale la pena "
                 "raccontare per esteso, perche' spiega perche' oggi si "
                 "presenta cosi' e non in un altro modo. ") * 3
    guida = {
        "poi_id": f"luogo_{indice}",
        "poi_name": f"Luogo numero {indice}",
        "title": f"Luogo numero {indice}: un titolo lungo come quelli veri",
        "history_summary": "\n\n".join(paragrafo for _ in range(storia)),
    }
    if sezioni:
        guida.update({
            "highlights": [{"name": f"Cosa guardare {k}",
                            "why": "Una spiegazione di un paio di righe sul "
                                   "perche' vale la pena fermarsi qui."}
                           for k in range(4)],
            "curiosita": ["Una curiosita' storica lunga quanto basta per "
                          "occupare due o tre righe di elenco." for _ in range(3)],
            "practical_tips": ["Un consiglio pratico scritto per esteso, con "
                               "la ragione dietro." for _ in range(6)],
            "errore_da_evitare": "Arrivare senza avere verificato gli orari.",
            "dintorni": [{"name": f"Posto vicino {k}",
                          "why": "A pochi minuti a piedi."} for k in range(3)],
            "best_time_to_visit": "Primo mattino",
            "estimated_visit_duration": "2-3 ore",
        })
    return guida


class TestILCORPOSISPEZZAFRALERIGHE(unittest.TestCase):
    """Il difetto numero uno: una riga sola che non puo' spezzarsi."""

    def test_le_sezioni_stanno_su_piu_righe(self):
        """La proprieta' che permette al corpo di scorrere.

        Con una riga sola il motore di stampa non ha nessun punto in cui
        interrompere: e' quello, e non una soglia sbagliata, che lasciava
        quattro decimi di foglio bianchi sotto la storia.
        """
        html = poi_pdf.build_guide_html(_guida(0), destination="Singapore")
        tabella = html.split("<table class='guida-colonne'>", 1)[1]
        tabella = tabella.split("</table>", 1)[0]
        self.assertGreater(tabella.count("<tr>"), 1,
                           "il corpo e' tornato a essere una riga sola: "
                           "non puo' spezzarsi fra due pagine")

    def test_le_colonne_restano_due(self):
        """Il difetto si ripara senza perdere l'impaginazione a colonne: una
        riga larga quanto un A4 e' faticosa, ed e' il motivo per cui guide e
        riviste sono in colonne da un secolo e mezzo."""
        html = poi_pdf.build_guide_html(_guida(0), destination="Singapore")
        tabella = html.split("<table class='guida-colonne'>", 1)[1]
        prima_riga = tabella.split("</tr>", 1)[0]
        self.assertEqual(2, prima_riga.count("<td>"))

    def test_la_tabella_del_corpo_non_e_incollata(self):
        """`page-break-inside: avoid` sul corpo annullerebbe tutta la
        riparazione: la tabella tornerebbe a cascare intera."""
        foglio = poi_pdf._css()
        regola = foglio.split(".guida-colonne", 1)[1].split("}", 1)[0]
        self.assertNotIn("page-break-inside", regola)

    def test_una_sezione_non_si_spezza_fra_due_celle(self):
        """Le parti di una sezione non sono spostabili una per una.

        L'elenco «Da sapere» era costruito in tre pezzi — apertura, voci,
        chiusura — e finche' finivano nella stessa colonna funzionava per
        fortuna, non per costruzione. Con le coppie di celle il taglio puo'
        cadere in mezzo, e l'elenco uscirebbe spezzato a meta'.
        """
        html = poi_pdf.build_guide_html(_guida(0), destination="Singapore")
        self.assertTrue(re.search(r"<ul>(?:<li>[^<]*</li>)+</ul>", html),
                        "un elenco e' finito spezzato fra due celle")
        riquadro = html.split("class='riquadro'", 1)[1].split("</div>", 1)[0]
        self.assertIn("<li>", riquadro,
                      "i consigli pratici sono usciti dal loro riquadro")


class TestILSALTODIPAGINANONSIPRENDEUNFOGLIO(unittest.TestCase):
    """Il difetto numero due: la pagina completamente bianca."""

    def test_il_salto_e_una_proprieta_della_scheda(self):
        unito = poi_pdf.unisci_le_schede(
            [("capitolo-uno", "<html><body><div>prima</div></body></html>"),
             ("capitolo-due", "<html><body><div>seconda</div></body></html>")],
            a_capo=["capitolo-due"])
        self.assertNotIn("<div style='page-break-before: always'></div>", unito,
                         "il salto e' di nuovo un elemento vuoto: quando la "
                         "scheda prima finisce a filo di pagina si prende un "
                         "foglio tutto suo e resta bianco")
        self.assertIn("page-break-before: always", unito,
                      "il salto e' sparito del tutto")

    def test_la_scheda_e_dentro_il_guscio_che_salta(self):
        unito = poi_pdf.unisci_le_schede(
            [("capitolo-uno", "<html><body><div>prima</div></body></html>"),
             ("capitolo-due", "<html><body><div>seconda</div></body></html>")],
            a_capo=["capitolo-due"])
        dopo_il_salto = unito.split("page-break-before: always'>", 1)[1]
        self.assertTrue(dopo_il_salto.lstrip().startswith("<div>seconda"),
                        "il guscio del salto non contiene la scheda")

    def test_la_prima_scheda_non_salta_mai(self):
        """Un salto prima della prima vorrebbe dire aprire il blocco delle
        guide con un foglio bianco: lo stesso difetto, in cima."""
        unito = poi_pdf.unisci_le_schede(
            [("capitolo-uno", "<html><body><div>prima</div></body></html>")],
            a_capo=["capitolo-uno"])
        self.assertNotIn("page-break-before", unito)


class TestLACODAMAGRASITIRASU(unittest.TestCase):
    """Il difetto numero tre: la facciata con sopra solo i bottoni."""

    def test_la_misura_dice_quanto_occupa_la_coda(self):
        from unittest import mock

        from src import impaginazione

        alto = impaginazione.ALTEZZA_A4_PT
        margine = impaginazione.MARGINE_VERTICALE_GUIDA_PT
        utile = alto - 2 * margine
        finte = {
            # Scheda magra: comincia in cima alla pagina 0 e finisce a un
            # dito dalla cima della pagina 1 — la coda occupa il 10%.
            "capitolo-magra": (0, margine + utile * 0.95),
            "capitolo-magra-fine": (1, (alto - margine) - utile * 0.10),
            # Scheda sana: la coda riempie quasi tutta la facciata, come le
            # schede vere del cliente (misurate: 85-89%).
            "capitolo-sana": (2, margine + utile * 0.95),
            "capitolo-sana-fine": (3, (alto - margine) - utile * 0.88),
        }
        with mock.patch.object(impaginazione, "posizioni", lambda _d: finte):
            misure = poi_pdf._misura_le_schede(
                b"finto", ["capitolo-magra", "capitolo-sana"])
        self.assertAlmostEqual(0.10, misure["capitolo-magra"][2], places=2)
        self.assertAlmostEqual(0.88, misure["capitolo-sana"][2], places=2)
        self.assertGreater(misure["capitolo-sana"][2], poi_pdf.QUOTA_CODA_MAGRA)
        self.assertLess(misure["capitolo-magra"][2], poi_pdf.QUOTA_CODA_MAGRA)

    def test_la_soglia_e_quella_del_misuratore_di_pagina(self):
        """La soglia non e' scelta a occhio: e' quella del misuratore,
        convertita.

        Il misuratore ragiona in quota di FOGLIO (70% minimo), questa misura
        in quota di altezza UTILE, cioe' foglio meno margini. Le due non
        coincidono, e la differenza non e' accademica: 0.70 di utile fa
        68,8% di foglio, un soffio SOTTO la soglia — sarebbe l'unico valore
        che non ripara proprio le facciate che il misuratore segnala.
        """
        import scripts_qualita_pagina as qualita

        alto = 842.0
        margine = 1.6 * 28.3465
        utile = alto - 2 * margine
        in_foglio = (margine + poi_pdf.QUOTA_CODA_MAGRA * utile) / alto * 100.0
        self.assertGreaterEqual(in_foglio, qualita.ARRIVO_MINIMO,
                                "la soglia di riparazione sta sotto quella "
                                "del misuratore: si riparerebbe meno di "
                                "quello che il misuratore segnala")
        self.assertLess(in_foglio, qualita.ARRIVO_MINIMO + 3.0,
                        "la soglia e' molto piu' severa del misuratore: si "
                        "stringerebbero fotografie senza che nessuno lo chieda")

    def test_una_scheda_lunga_ma_con_la_coda_piena_non_si_tocca(self):
        """[MISURATO, ed e' la ragione per cui questa soglia esiste.]

        La regola di ieri stringeva la fotografia di OGNI scheda che
        sbordasse. Sul fascicolo vero — dove le schede sono lunghe una
        facciata e mezzo e sbordano tutte — ha ritagliato tutte le fotografie
        fino all'ultimo gradino senza guadagnare una sola pagina: immagini
        ridotte a strisce per niente. Una scheda che sborda con la coda piena
        e' un capitolo che continua, non un difetto.
        """
        import inspect

        sorgente = inspect.getsource(poi_pdf.costruisci_capitoli)
        self.assertIn("coda < QUOTA_CODA_MAGRA", sorgente,
                      "il ciclo stringe di nuovo qualunque scheda sbordi")


class TestSULCAMPIONEDELLASTESSATAGLIADELVERO(unittest.TestCase):
    """La prova che il campione di ieri non poteva fare.

    Sei schede delle dimensioni di quelle vendute, stampate e misurate con lo
    stesso strumento con cui e' stato misurato il documento del cliente.
    """

    @classmethod
    def setUpClass(cls):
        import tempfile

        orari = {g: "10:00-22:00" for g in
                 ("monday", "tuesday", "wednesday", "thursday", "friday",
                  "saturday", "sunday")}
        scheda = {"address": "301 Upper Thomson Rd, Singapore 574408",
                  "phone": "6454 9133"}
        guide = [_guida(i) for i in range(6)]
        # Con le fotografie, come nel documento vero: senza, la riparazione
        # della coda magra non ha nessuna leva — non c'e' niente da
        # stringere e niente con cui riempire. E' un limite dichiarato, non
        # un caso da nascondere: vedi il ciclo in `costruisci_capitoli`.
        scatti = {f"luogo_{i}": {"png": _fotografia(i),
                                 "credito": f"Foto: Autore {i} / Prova",
                                 "reale": True,
                                 "png_alt": _fotografia(i + 40),
                                 "credito_alt": f"Foto: Autore {i}b / Prova"}
                  for i in range(6)}
        ritorni = {f"luogo_{i}": [
            {"ancora": "cartina-giorno-1",
             "etichetta": "Torna alla cartina del Giorno 1"},
            {"ancora": "giorno-1-1005", "etichetta": "Torna al Giorno 1 · 10:05"},
        ] for i in range(6)}
        capitoli = poi_pdf.costruisci_capitoli(
            guide, ritorni, destination="Singapore",
            place_cards={f"luogo_{i}": scheda for i in range(6)},
            photos=scatti,
            open_hours_by_poi={f"luogo_{i}": orari for i in range(6)})
        cls.blob = next((c["pdf"] for c in capitoli if c["pdf"]), b"")
        cls.ancore = [c["ancora"] for c in capitoli]
        file_pdf = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        file_pdf.write(cls.blob)
        file_pdf.close()
        cls.percorso = file_pdf.name

    def test_il_blocco_si_stampa(self):
        self.assertTrue(self.blob)

    def test_nessuna_facciata_resta_quasi_vuota(self):
        """La misura dei tre difetti, sul documento stampato.

        La soglia qui e' il 50%, non il 70% del misuratore, e la differenza
        va spiegata invece che nascosta. Questo campione e' un caso peggiore
        costruito apposta: sei schede IDENTICHE, lunghe una facciata e
        mezzo, ognuna con una fotografia sola. Quando a una scheda cosi'
        avanza soltanto il blocco «Torna dove eri», gli unici centimetri che
        si possono mettere su quella facciata sono quelli della fila di
        chiusura — e con una fotografia sola si arriva al 56%, non al 92%.

        Misurato: senza le riparazioni quelle facciate stavano al 14,2%.
        Il salto da 14 a 56 e' il difetto che il cliente ha visto («pagine
        con solo due righe o tasti di collegamento»); l'ultimo tratto fino
        al 70% si vince con piu' fotografie disponibili, non con
        l'impaginazione — e su un fascicolo vero le fotografie ci sono, dove
        infatti il misuratore non segnala piu' niente.
        """
        import scripts_qualita_pagina as qualita

        misure = qualita.misura(self.percorso)
        if not misure:
            self.skipTest("misuratore non disponibile qui (numpy/pdftoppm)")
        magre = [m for m in misure[:-1] if m["arrivo"] < 50.0]
        self.assertEqual([], magre,
                         f"facciate quasi vuote: {[(m['pagina'], m['arrivo']) for m in magre]}")

    def test_nessuna_facciata_e_completamente_bianca(self):
        import scripts_qualita_pagina as qualita

        misure = qualita.misura(self.percorso)
        if not misure:
            self.skipTest("misuratore non disponibile qui (numpy/pdftoppm)")
        bianche = [m["pagina"] for m in misure if m["arrivo"] <= 0.0]
        self.assertEqual([], bianche, f"facciate bianche: {bianche}")

    def test_nessuna_facciata_contiene_due_schede(self):
        from src import impaginazione

        dove = impaginazione.posizioni(self.blob)
        partenze = [dove[a][0] for a in self.ancore if a in dove]
        self.assertTrue(partenze)
        self.assertEqual(len(partenze), len(set(partenze)))


class TestLAFOTOGRAFIACHERIEMPIELAFACCIATA(unittest.TestCase):
    """L'ultimo rimedio: quando la coda non si puo' tirare su, si riempie.

    [MISURATO il 19 agosto, e le due scelte ovvie erano tutte e due
    sbagliate.] La facciata dove atterrava la coda di una scheda — spesso
    solo i bottoni «Torna dove eri» — stava al 17% del foglio. Mettendoci la
    fila di chiusura di sempre, tre fotografie affiancate, saliva al 60%: tre
    immagini in fila sono larghe un terzo e quindi alte un terzo, e riempiono
    meno di una sola. Con UNA fotografia sola, larga quanto la pagina e
    ritagliata quasi quadrata, la facciata arriva sopra la soglia.

    La regola di sempre non cambia: e' una fotografia DI QUEL luogo. Il
    ritaglio verticale toglie larghezza, non verita'.
    """

    def _con_scatti(self, quanti):
        return {"png": _fotografia(0), "credito": "Foto: Autore / Prova",
                "reale": True,
                "scatti": [{"png": _fotografia(k), "credito": f"Foto: {k}"}
                           for k in range(quanti)]}

    def test_la_scorta_del_luogo_alimenta_la_fila(self):
        """Le fotografie in piu' dello STESSO luogo, saltate le due gia'
        stampate (l'apertura e la chiusura)."""
        tutte = {"luogo": self._con_scatti(5)}
        libere = poi_pdf._altre_foto(tutte, "luogo", 0)
        self.assertEqual(3, len(libere))

    def test_senza_scorta_si_ricade_sulla_seconda_di_sempre(self):
        """Un luogo con una fotografia sola non deve perdere quella che
        aveva: meglio una fila corta che nessuna fila."""
        voce = {"png": _fotografia(0), "credito": "Foto: A",
                "png_alt": _fotografia(1), "credito_alt": "Foto: B"}
        libere = poi_pdf._altre_foto({"luogo": voce}, "luogo", 0)
        self.assertEqual(1, len(libere))

    def test_il_riempimento_usa_una_fotografia_sola_e_alta(self):
        html = poi_pdf.build_guide_html(
            _guida(0), destination="Singapore",
            photo={"png": _fotografia(0), "credito": "Foto: A"},
            foto_extra=[{"png": _fotografia(k), "credito": f"Foto: {k}"}
                        for k in range(3)],
            banda_di_riempimento=True)
        # La fila vera, non il foglio di stile: si prende l'ULTIMA tabella
        # con quella classe e la si taglia alla sua chiusura.
        coda = html.rsplit("<table class='guida-banda'>", 1)[1]
        coda = coda.split("</table>", 1)[0]
        self.assertEqual(1, coda.count("<td"),
                         "la fila di riempimento ha piu' di una cella: "
                         "affiancate, le fotografie diventano basse e "
                         "riempiono meno di una sola")

    def test_il_ritaglio_verticale_alza_davvero_la_figura(self):
        """Il controllo che impedisce alla riparazione di essere finta.

        `ritaglia_panoramica` non puo' rendere piu' alta un'immagine — non
        puo' aggiungere pixel — quindi chiedere un rapporto piu' basso non
        cambiava niente. Ci volle un ritaglio dall'altra parte, che toglie
        LARGHEZZA. Qui si verifica sui pixel.
        """
        import io

        from PIL import Image

        from src import foto

        grezzi = _fotografia(0)
        prima = Image.open(io.BytesIO(grezzi)).size
        dopo_bytes = foto.ritaglia_ritratto(grezzi, poi_pdf.RAPPORTO_DEL_RIEMPIMENTO)
        self.assertIsNotNone(dopo_bytes)
        dopo = Image.open(io.BytesIO(dopo_bytes)).size
        self.assertLess(dopo[0] / dopo[1], prima[0] / prima[1],
                        "la fotografia di riempimento non e' piu' alta di "
                        "quella di partenza: riempirebbe come prima")
