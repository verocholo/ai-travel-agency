"""Test del fascicolo: documenti diversi, un file solo (`src/fascicolo.py`).

PERCHÉ QUESTO FILE ESISTE
Lorenzo, parola per parola: «altrettanto fondamentale è che questi documenti
seppur diversi stiano in un unico file, non so come farai ma trova il modo» e
«è importantissimo però che ogni collegamento esterno abbia un pulsante per
ritornare al documento principale, nel punto esatto di dove si era arrivati
originariamente».

Sono due promesse che si rompono in silenzio. Un collegamento morto dentro un
PDF non dà errore: si clicca e non succede niente. Il cliente non scrive per
lamentarsi, semplicemente non ricompra. Quindi qui non si controlla l'HTML —
l'HTML era già giusto la volta che i collegamenti non funzionavano — si
stampano PDF veri, si cuciono, e si legge il file cucito.

I test che stampano davvero stanno in fondo. Se `wkhtmltopdf` non c'è, si
saltano: non si fingono verdi.
"""

import io
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from src import fascicolo, pdf_links


HA_WKHTMLTOPDF = shutil.which("wkhtmltopdf") is not None


def _pagina(titolo: str, corpo: str) -> str:
    """Una paginetta con lo stesso stile di sonda del documento vero.

    La regola `.anchor-probe` è ricopiata da `pdf_renderer`: la sonda deve
    essere quasi invisibile ma NON di dimensione zero, altrimenti wkhtmltopdf
    non le assegna nessuna annotazione e la riparazione resta cieca.
    """
    return (
        "<!doctype html><html><head><meta charset='utf-8'><style>"
        "body { font-family: sans-serif; }"
        ".anchor-probe { font-size: 2px; line-height: 2px; color: #ffffff; }"
        ".anchor-probe a { color: #ffffff; text-decoration: none; }"
        ".alto { height: 900px; }"
        f"</style><title>{titolo}</title></head><body>{corpo}</body></html>"
    )


def _sonda(nome: str) -> str:
    return (
        f"<span id='{nome}' class='anchor-probe'>"
        f"<a href='{pdf_links.PROBE_PREFIX}{nome}'>&#160;</a></span>"
    )


def _stampa(html: str, cartella: Path, nome: str) -> bytes:
    percorso_html = cartella / f"{nome}.html"
    percorso_pdf = cartella / f"{nome}.pdf"
    percorso_html.write_text(html, encoding="utf-8")
    subprocess.run(
        ["wkhtmltopdf", "--quiet", "--enable-internal-links",
         str(percorso_html), str(percorso_pdf)],
        capture_output=True, timeout=120,
    )
    return percorso_pdf.read_bytes()


class TestINomiDelleAncoreSiCalcolano(unittest.TestCase):
    """I nomi devono venire fuori dai dati, non da una variabile condivisa.

    Il bottone «torna indietro» lo scrive il capitolo; il punto in cui deve
    atterrare lo scrive il documento principale. Sono due stampe separate. Se
    le due parti non calcolassero lo stesso nome partendo dagli stessi dati,
    il collegamento sarebbe rotto senza che nessuno se ne accorga.
    """

    def test_lo_slug_e_lo_stesso_del_generatore_del_documento(self):
        # `fascicolo._slug` è una copia di `pdf_renderer._slug` (l'import
        # diretto sarebbe circolare). Una copia che diverge produrrebbe
        # ancore che non si incontrano mai: qui si accende il rosso.
        from src import pdf_renderer

        casi = [
            "POI1", "Piazza del Campo", "Café de l'Opéra", "duomo/siena",
            "  spazi  ", "ACCENTÌ", "", None, 12, "già-fatto",
        ]
        for caso in casi:
            with self.subTest(caso=caso):
                self.assertEqual(
                    fascicolo._slug(caso), pdf_renderer._slug(caso),
                    "la copia dello slug è divergente: le ancore del "
                    "capitolo e quelle dell'itinerario non si incontrerebbero",
                )

    def test_due_origini_diverse_danno_due_ancore_diverse(self):
        # È il cuore della richiesta: «nel punto esatto di dove si era
        # arrivati originariamente». La stessa attrazione si raggiunge dalla
        # cartina del Giorno 2 e dal programma del Giorno 2: se le due ancore
        # coincidessero, uno dei due ritorni porterebbe nel posto sbagliato.
        da_cartina = fascicolo.ancora_ritorno("POI1", ("cartina", 2))
        da_blocco = fascicolo.ancora_ritorno("POI1", ("blocco", 2, 0))
        self.assertNotEqual(da_cartina, da_blocco)

    def test_lo_stesso_blocco_in_due_giorni_diversi_non_si_confonde(self):
        primo = fascicolo.ancora_ritorno("POI1", ("blocco", 1, 0))
        secondo = fascicolo.ancora_ritorno("POI1", ("blocco", 2, 0))
        self.assertNotEqual(primo, secondo)

    def test_la_prima_attivita_del_giorno_non_sparisce(self):
        """[REGRESSIONE 2026-08-05] Lo zero è falso in Python.

        `_slug` scrive `str(value or "")`: la posizione 0 — cioè la PRIMA
        attività della giornata, il caso più frequente che esista — usciva
        come stringa vuota e l'ancora diventava `ritorno-poi1-blocco-1`,
        indistinguibile da altre. Trovato provando il codice a mano, non
        leggendolo.
        """
        self.assertIn("-0", fascicolo.ancora_ritorno("POI1", ("blocco", 1, 0)))
        self.assertNotEqual(
            fascicolo.ancora_ritorno("POI1", ("blocco", 1, 0)),
            fascicolo.ancora_ritorno("POI1", ("blocco", 1)),
        )

    def test_ogni_posizione_del_giorno_ha_la_sua_ancora(self):
        # Una giornata piena sono otto o dieci blocchi: se due qualsiasi
        # collidessero, uno dei due bottoni porterebbe nel posto sbagliato.
        nomi = [fascicolo.ancora_ritorno("POI1", ("blocco", g, p))
                for g in range(1, 8) for p in range(0, 12)]
        self.assertEqual(len(set(nomi)), len(nomi))

    def test_l_ancora_non_e_mai_vuota_ne_storta(self):
        # Un `poi_id` con apostrofi o spazi produrrebbe un `href='#...'`
        # spezzato, cioè un altro collegamento morto silenzioso.
        for chiave in ["Café de l'Opéra", "", None, "a/b c"]:
            with self.subTest(chiave=chiave):
                nome = fascicolo.ancora_capitolo(chiave)
                self.assertTrue(nome)
                self.assertRegex(nome, r"^[a-z0-9_-]+$")
                ritorno = fascicolo.ancora_ritorno(chiave, ("blocco", 1, 0))
                self.assertRegex(ritorno, r"^[a-z0-9_-]+$")

    def test_capitolo_e_ritorno_non_si_somigliano(self):
        # Se i due prefissi collidessero, la riparazione risolverebbe un
        # rimando sull'ancora sbagliata.
        self.assertNotEqual(
            fascicolo.ancora_capitolo("POI1"),
            fascicolo.ancora_ritorno("POI1", ("blocco", 1, 0)),
        )


class TestLElencoDeiRitorni(unittest.TestCase):
    """Da dove si arriva a un capitolo. È la lista che le due parti leggono."""

    def _itinerario(self):
        return {
            "days": [
                {"day": 1, "blocks": [
                    {"time": "09:30", "activity": "Duomo", "poi_id": "POI1"},
                    {"time": "12:00", "activity": "Pranzo"},
                ]},
                {"day": 2, "blocks": [
                    {"time": "10:00", "activity": "Torre", "poi_id": "POI2"},
                    {"time": "16:00", "activity": "Duomo di nuovo",
                     "poi_id": "POI1"},
                ]},
            ]
        }

    def _guide(self):
        return [{"poi_id": "POI1", "poi_name": "Duomo"},
                {"poi_id": "POI2", "poi_name": "Torre"}]

    def test_un_attrazione_vista_due_volte_ha_due_ritorni_distinti(self):
        # Lorenzo l'ha chiesto esplicitamente. Il Duomo compare il Giorno 1 e
        # il Giorno 2: dal capitolo devono partire due bottoni diversi.
        ritorni = fascicolo.elenca_ritorni(
            self._itinerario(), self._guide())
        blocchi = [v for v in ritorni["POI1"] if v["origine"][0] == "blocco"]
        self.assertEqual(len(blocchi), 2)
        self.assertEqual(
            len({v["ancora"] for v in blocchi}), 2,
            "due passaggi diversi hanno prodotto la stessa ancora: uno dei "
            "due bottoni «torna indietro» porterebbe nel punto sbagliato",
        )

    def test_anche_la_cartina_e_un_punto_di_partenza(self):
        # I pallini cliccabili della cartina portano al capitolo tanto quanto
        # il collegamento nel programma: anche da lì si deve poter tornare.
        ritorni = fascicolo.elenca_ritorni(
            self._itinerario(), self._guide(), giorni_con_cartina=[1, 2])
        origini = [v["origine"] for v in ritorni["POI1"]]
        self.assertIn(("cartina", 1), origini)
        self.assertIn(("cartina", 2), origini)

    def test_senza_cartina_non_si_promette_un_ritorno_alla_cartina(self):
        """[REGRESSIONE 2026-08-05] Il difetto che ha trovato il controllo
        di insieme, non la lettura del codice.

        La prima versione dava per scontato che ogni giorno avesse la sua
        cartina. Su un documento senza cartine il capitolo stampava lo stesso
        due bottoni «torna alla cartina del Giorno N» che puntavano a un
        punto inesistente. La chiamata a Google Static Maps che va male è il
        guasto più frequente di questo progetto: non è un caso di scuola.
        """
        ritorni = fascicolo.elenca_ritorni(self._itinerario(), self._guide())
        origini = [v["origine"][0] for v in ritorni["POI1"]]
        self.assertNotIn("cartina", origini)
        self.assertIn("blocco", origini)

    def test_la_cartina_di_un_giorno_solo_non_ne_promette_due(self):
        ritorni = fascicolo.elenca_ritorni(
            self._itinerario(), self._guide(), giorni_con_cartina=[2])
        cartine = [v["origine"] for v in ritorni["POI1"]
                   if v["origine"][0] == "cartina"]
        self.assertEqual(cartine, [("cartina", 2)])

    def test_chi_non_ha_capitolo_non_ha_ritorni(self):
        # Seminare ancore per attrazioni senza guida sporcherebbe il
        # documento con bersagli che nessuno raggiunge mai.
        ritorni = fascicolo.elenca_ritorni(
            self._itinerario(), [{"poi_id": "POI2"}])
        self.assertNotIn("POI1", ritorni)

    def test_le_etichette_dicono_al_cliente_dove_sta_tornando(self):
        # «Torna all'itinerario» non basta quando i punti di partenza sono
        # due: il cliente deve capire quale bottone lo riporta dove stava.
        ritorni = fascicolo.elenca_ritorni(
            self._itinerario(), self._guide(), giorni_con_cartina=[1, 2])
        etichette = [v["etichetta"] for v in ritorni["POI1"]]
        self.assertEqual(len(set(etichette)), len(etichette),
                         "due bottoni con la stessa scritta sono indistinguibili")
        self.assertTrue(any("09:30" in e for e in etichette))

    def test_l_ordine_e_quello_di_lettura(self):
        ritorni = fascicolo.elenca_ritorni(
            self._itinerario(), self._guide(), giorni_con_cartina=[1, 2])
        giorni = [v["origine"][1] for v in ritorni["POI1"]]
        self.assertEqual(giorni, sorted(giorni))

    def test_dati_storti_non_fanno_esplodere_niente(self):
        # I giorni arrivano da un modello linguistico: prima o poi qualcosa
        # sarà `None` o una stringa dove ci si aspetta un dizionario.
        for storto in [None, {}, {"days": None}, {"days": [None, "x"]},
                       {"days": [{"blocks": [None, 3]}]}]:
            with self.subTest(storto=storto):
                fascicolo.elenca_ritorni(storto, self._guide())


class TestIlCapitoloStaccato(unittest.TestCase):
    """L'HTML della guida quando è un capitolo cucito, non un file ospitato."""

    def _guida(self):
        return {"poi_id": "POI1", "poi_name": "Duomo", "title": "Duomo",
                "history_summary": "Storia.", "practical_tips": ["Vai presto."]}

    def _ritorni(self):
        return [
            {"origine": ("cartina", 2), "etichetta": "Torna alla cartina del Giorno 2",
             "ancora": fascicolo.ancora_ritorno("POI1", ("cartina", 2))},
            {"origine": ("blocco", 2, 0), "etichetta": "Torna al Giorno 2 &#183; 09:30",
             "ancora": fascicolo.ancora_ritorno("POI1", ("blocco", 2, 0))},
        ]

    def test_il_capitolo_semina_la_sua_ancora_in_cima(self):
        from src import poi_pdf

        html = poi_pdf.build_guide_html(
            self._guida(), ancora_capitolo="capitolo-poi1")
        # Con la tag e l'apice di chiusura: `capitolo-poi1` da solo
        # comparirebbe anche dentro un commento e il controllo passerebbe a
        # vuoto per sempre.
        self.assertIn("id='capitolo-poi1' class='anchor-probe'", html)
        self.assertIn(f"{pdf_links.PROBE_PREFIX}capitolo-poi1", html)

    def test_un_bottone_per_ogni_punto_di_partenza(self):
        from src import poi_pdf

        html = poi_pdf.build_guide_html(
            self._guida(), ancora_capitolo="capitolo-poi1",
            ritorni=self._ritorni())
        for voce in self._ritorni():
            # [AGGIORNATO 2026-08-13] Era `href='#{ancora}'`. Il pulsante
            # "torna al programma" e' proprio uno di quelli che in produzione
            # sparivano: punta indietro, verso il documento principale, cioe'
            # verso un bersaglio che al momento della stampa del capitolo non
            # esiste ancora. Il motore lo cancellava.
            self.assertIn(f"href='{pdf_links.href_interno(voce['ancora'])}'", html)

    def test_nel_fascicolo_il_ritorno_non_passa_da_internet(self):
        # Il documento principale è a due pagine di distanza. Mandare il
        # cliente su una URL per raggiungerlo sarebbe peggio in ogni caso, e
        # in aereo sarebbe un vicolo cieco.
        from src import poi_pdf

        html = poi_pdf.build_guide_html(
            self._guida(), ancora_capitolo="capitolo-poi1",
            ritorni=self._ritorni(),
            itinerary_url="https://esempio.it/f/a/b/itinerario.pdf")
        self.assertNotIn("https://esempio.it", html)

    def test_senza_fascicolo_la_guida_resta_quella_di_prima(self):
        # `publish_guides` continua a esistere: chi ha l'ospitalità
        # configurata non deve accorgersi di questo giro.
        from src import poi_pdf

        html = poi_pdf.build_guide_html(
            self._guida(),
            itinerary_url="https://esempio.it/f/a/b/itinerario.pdf")
        self.assertIn("https://esempio.it/f/a/b/itinerario.pdf", html)
        self.assertNotIn("class='anchor-probe'", html)

    def test_i_capitoli_escono_con_ancora_e_byte(self):
        if not HA_WKHTMLTOPDF:
            self.skipTest("wkhtmltopdf non installato")
        from src import poi_pdf

        capitoli = poi_pdf.costruisci_capitoli(
            [self._guida()], {"POI1": self._ritorni()}, destination="Siena")
        self.assertEqual(len(capitoli), 1)
        self.assertEqual(capitoli[0]["ancora"],
                         fascicolo.ancora_capitolo("POI1"))
        self.assertTrue(capitoli[0]["pdf"].startswith(b"%PDF"))

    def test_una_guida_senza_poi_id_non_diventa_un_capitolo_fantasma(self):
        # Senza `poi_id` nessun collegamento potrebbe puntarci: sarebbero
        # pagine in più che il cliente non raggiunge da nessuna parte.
        from src import poi_pdf

        self.assertEqual(
            poi_pdf.costruisci_capitoli([{"poi_name": "Senza id"}]), [])


class TestSeQualcosaVaStortoIlClienteRicevePeroIlSuoItinerario(unittest.TestCase):
    """La cucitura è un di più. L'itinerario è quello che ha pagato."""

    def test_un_capitolo_illeggibile_non_porta_via_il_documento(self):
        principale = b"%PDF-1.4 finto ma sono i byte del cliente"
        fuori = fascicolo.unisci(principale, [b"non sono un pdf"])
        self.assertEqual(fuori, principale)

    def test_senza_capitoli_il_documento_torna_identico(self):
        principale = b"%PDF-1.4 identico"
        self.assertEqual(fascicolo.unisci(principale, []), principale)
        self.assertEqual(fascicolo.unisci(principale, None), principale)

    def test_cuci_non_solleva_mai_e_lo_dice_nel_resoconto(self):
        dati, resoconto = fascicolo.cuci(b"spazzatura", [b"altra spazzatura"])
        self.assertIsInstance(dati, bytes)
        self.assertIsInstance(resoconto, dict)
        self.assertFalse(resoconto["unione_riuscita"])

    def test_un_allegato_vuoto_non_tocca_il_file(self):
        dati = b"%PDF-1.4 intatto"
        self.assertEqual(fascicolo.allega(dati, {}), dati)
        self.assertEqual(fascicolo.allega(dati, {"a.xlsx": b""}), dati)


@unittest.skipUnless(HA_WKHTMLTOPDF, "wkhtmltopdf non installato")
class TestSulFascicoloVero(unittest.TestCase):
    """Si stampa, si cuce, si legge. L'unico test che può dire la verità."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="fascicolo-")
        cartella = Path(cls.tmp)
        cls.nome_capitolo = fascicolo.ancora_capitolo("POI1")
        cls.nome_ritorno = fascicolo.ancora_ritorno("POI1", ("blocco", 2, 0))

        principale = _pagina("Itinerario", (
            "<h1>Itinerario</h1>"
            "<p>Giorno 2, mattina.</p>"
            f"{_sonda(cls.nome_ritorno)}"
            f"<p><a href='#{cls.nome_capitolo}'>Apri la guida</a></p>"
            "<div class='alto'></div>"
        ))
        capitolo = _pagina("Duomo", (
            f"{_sonda(cls.nome_capitolo)}"
            "<h1>Duomo</h1><p>Storia.</p>"
            f"<p><a href='#{cls.nome_ritorno}'>Torna al Giorno 2</a></p>"
        ))
        cls.pdf_principale = _stampa(principale, cartella, "principale")
        cls.pdf_capitolo = _stampa(capitolo, cartella, "capitolo")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_dopo_la_cucitura_le_sonde_si_leggono_ancora(self):
        """Il controllo che ha fatto scoprire il difetto.

        `pypdf`, quando riscrive il file, protegge in ottale ogni carattere
        non alfanumerico dentro le stringhe: `(ancora-interna:capitolo-duomo)`
        diventa `(ancora\\055interna\\072capitolo\\055duomo)`. Prima che
        `pdf_links._uri_di` sapesse scioglierle, sul file cucito la
        riparazione contava ZERO sonde e quattro «collegamenti esterni»: cioè
        ogni rimando del fascicolo sarebbe rimasto rotto, in silenzio.
        """
        unito = fascicolo.unisci(self.pdf_principale, [self.pdf_capitolo])
        letto = pdf_links.analyse(unito)
        self.assertIn(self.nome_capitolo, letto["sonde"],
                      "sul file cucito le sonde non si leggono più: tutti i "
                      "rimandi del fascicolo resterebbero morti")
        self.assertIn(self.nome_ritorno, letto["sonde"])

    def test_il_rimando_attraversa_il_confine_fra_i_due_documenti(self):
        # Andata e ritorno: dall'itinerario al capitolo e dal capitolo al
        # punto esatto dell'itinerario. È tutta la richiesta di Lorenzo in un
        # solo controllo.
        dati, resoconto = fascicolo.cuci(
            self.pdf_principale, [self.pdf_capitolo])
        self.assertEqual(resoconto["capitoli"], 1)
        self.assertEqual(resoconto["collegamenti"].get("non_risolte"), [])
        letto = pdf_links.analyse(dati)
        self.assertEqual(letto["rotti"], {},
                         "è rimasto un collegamento morto nel fascicolo")
        self.assertGreaterEqual(letto["goto"], 2)

    def test_il_ritorno_atterra_su_una_pagina_del_documento_principale(self):
        # Non basta che il salto esista: deve puntare INDIETRO. Se atterrasse
        # dentro il capitolo, il bottone «torna» girerebbe a vuoto.
        unito = fascicolo.unisci(self.pdf_principale, [self.pdf_capitolo])
        letto = pdf_links.analyse(unito)
        pagine_principale = _pagine_di(self.pdf_principale)
        pagina_ritorno = letto["sonde"][self.nome_ritorno][0]
        pagina_capitolo = letto["sonde"][self.nome_capitolo][0]
        self.assertLess(pagina_ritorno, pagine_principale)
        self.assertGreaterEqual(pagina_capitolo, pagine_principale)

    def test_il_fascicolo_resta_leggibile_da_un_lettore_vero(self):
        if not shutil.which("pdfinfo"):
            self.skipTest("poppler-utils non installato")
        dati, _ = fascicolo.cuci(self.pdf_principale, [self.pdf_capitolo])
        fuori = Path(self.tmp) / "fascicolo.pdf"
        fuori.write_bytes(dati)
        res = subprocess.run(["pdfinfo", str(fuori)],
                             capture_output=True, text=True, timeout=60)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertNotIn("Syntax Error", res.stderr)

    def test_il_foglio_di_calcolo_viaggia_dentro_lo_stesso_file(self):
        """Il primo dei due binari della valigia.

        Il foglio non è un PDF e non si può cucire fra le pagine, ma può
        stare DENTRO il file come allegato. Qui si verifica che ci sia
        davvero e che i byte tornino fuori identici — un allegato corrotto
        sarebbe peggio di nessun allegato.
        """
        from pypdf import PdfReader

        finto_xlsx = b"PK\x03\x04finto foglio di calcolo"
        dati, resoconto = fascicolo.cuci(
            self.pdf_principale, [self.pdf_capitolo],
            {"Valigia.xlsx": finto_xlsx})
        self.assertEqual(resoconto["allegati"], 1)
        lettore = PdfReader(io.BytesIO(dati))
        self.assertIn("Valigia.xlsx", lettore.attachments)
        self.assertEqual(lettore.attachments["Valigia.xlsx"][0], finto_xlsx)

    def test_l_allegato_non_scuce_i_collegamenti(self):
        # L'ordine dentro `cuci` non è negoziabile: unione, allegati e SOLO
        # ALLA FINE la riparazione. Se si invertisse, il passaggio di `pypdf`
        # riscriverebbe il file da capo e cancellerebbe i salti di pagina.
        dati, _ = fascicolo.cuci(
            self.pdf_principale, [self.pdf_capitolo],
            {"Valigia.xlsx": b"PK\x03\x04qualcosa"})
        letto = pdf_links.analyse(dati)
        self.assertEqual(letto["rotti"], {})
        self.assertGreaterEqual(letto["goto"], 2)


class TestIlFascicoloELaStradaNORMALE(unittest.TestCase):
    """Non un argomento in più da ricordarsi: il modo standard di stampare.

    Lorenzo, alla fine della richiesta: «standardizza tutto il progetto una
    volta finito». Un pezzo di prodotto che funziona solo se il chiamante si
    ricorda di chiederlo non è standardizzato — è una trappola con sei mesi
    di ritardo.
    """

    def test_i_capitoli_arrivano_al_renderer_da_soli(self):
        # `split_render_kwargs` filtra per lista bianca: una chiave non
        # elencata viene buttata via IN SILENZIO. È già successo con
        # `checklist_xlsx`.
        from src import pdf_extras

        sezioni = {"capitoli_pdf": [{"poi_id": "P1", "ancora": "capitolo-p1",
                                     "pdf": b"%PDF"}],
                   "allegati": {"Valigia.xlsx": b"PK"}}
        kwargs, _ = pdf_extras.split_render_kwargs(sezioni)
        self.assertIn("capitoli_pdf", kwargs)
        self.assertIn("allegati", kwargs)

    def test_render_pdf_accetta_davvero_quelle_due_chiavi(self):
        # La lista bianca e la firma del renderer possono divergere: qui si
        # verifica che la chiave passata esista dall'altra parte.
        import inspect

        from src import pdf_renderer

        firma = inspect.signature(pdf_renderer.render_pdf).parameters
        self.assertIn("capitoli_pdf", firma)
        self.assertIn("allegati", firma)

    def test_il_foglio_diventa_allegato_col_suo_nome(self):
        from src import pdf_extras

        sezioni = {"checklist_xlsx": {"filename": "Valigia-Siena.xlsx",
                                      "content": b"PK\x03\x04"}}
        self.assertTrue(pdf_extras.allega_foglio_valigia(sezioni))
        self.assertEqual(sezioni["allegati"],
                         {"Valigia-Siena.xlsx": b"PK\x03\x04"})

    def test_senza_foglio_non_si_allega_un_file_vuoto(self):
        from src import pdf_extras

        for sezioni in [{}, {"checklist_xlsx": None},
                        {"checklist_xlsx": {"content": b""}}]:
            with self.subTest(sezioni=sezioni):
                self.assertFalse(pdf_extras.allega_foglio_valigia(sezioni))
                self.assertNotIn("allegati", sezioni)

    def test_una_guida_gia_capitolo_non_viene_anche_pubblicata(self):
        # Stamparla due volte costa mezzo secondo su un'esecuzione che ha
        # gia' sfiorato il tetto duro dei 300 secondi di Make.
        from unittest import mock

        from src import pdf_extras

        sezioni = {"capitoli_pdf": [{"poi_id": "P1", "ancora": "capitolo-p1",
                                     "pdf": b"%PDF"}]}
        with mock.patch.object(pdf_extras.hosting, "is_configured",
                               return_value=True), \
             mock.patch.object(pdf_extras.poi_pdf, "publish_guides") as pubblica:
            pdf_extras.publish_hosted_guides(
                [{"poi_id": "P1", "poi_name": "Duomo"}], sezioni)
        pubblica.assert_not_called()

    def test_l_allegato_si_prende_dopo_il_bottone_di_ritorno(self):
        """[REGRESSIONE — lo stesso inciampo del 2026-08-03]

        `aggiungi_ritorno_al_foglio_valigia()` RIFÀ il foglio da capo per
        metterci dentro il bottone. Allegarlo prima significa infilare nel
        PDF la versione senza bottone: lo stesso file, e proprio senza la
        cosa che era stata chiesta. L'ordine si controlla nel sorgente
        perché non lascia nessuna traccia visibile nel prodotto.
        """
        for nome in ("service.py", "main.py"):
            with self.subTest(file=nome):
                testo = Path(nome).read_text(encoding="utf-8")
                # Con la parentesi: il nome nudo compare nei commenti molto
                # prima della chiamata vera, e il controllo passerebbe a
                # vuoto per sempre.
                bottone = testo.find("aggiungi_ritorno_al_foglio_valigia(\n")
                allegato = testo.find("allega_foglio_valigia(sections)")
                self.assertGreater(bottone, 0, "chiamata al bottone non trovata")
                self.assertGreater(allegato, 0, "chiamata all'allegato non trovata")
                self.assertLess(bottone, allegato)

    def test_i_capitoli_si_preparano_prima_della_pubblicazione(self):
        # `publish_hosted_guides` si fa da parte guardando `capitoli_pdf`:
        # se girasse per prima quella chiave sarebbe ancora vuota e ogni
        # guida verrebbe stampata due volte.
        for nome in ("service.py", "main.py"):
            with self.subTest(file=nome):
                testo = Path(nome).read_text(encoding="utf-8")
                capitoli = testo.find("prepara_fascicolo(\n")
                pubblica = testo.find("publish_hosted_guides(\n")
                self.assertGreater(capitoli, 0, "chiamata al fascicolo non trovata")
                self.assertGreater(pubblica, 0, "chiamata alla pubblicazione non trovata")
                self.assertLess(capitoli, pubblica)


@unittest.skipUnless(HA_WKHTMLTOPDF, "wkhtmltopdf non installato")
class TestIlDocumentoVeroDalPrincipioAllaFine(unittest.TestCase):
    """Il giro completo: `render_pdf` con i capitoli, letto sul file finito.

    I test qui sopra provano i pezzi. Questo prova il prodotto: è l'unico che
    fallirebbe se qualcuno, fra sei mesi, dimenticasse di passare i capitoli
    a `render_pdf` — cioè il modo più probabile in cui questa funzione
    smetterà di funzionare.
    """

    ITINERARIO = {
        "destination": "Siena",
        "executive_summary": "Un bel viaggio.",
        "days": [
            {"day": 1, "title": "Centro", "blocks": [
                {"time": "09:30", "activity": "Duomo", "location": "Siena",
                 "poi_id": "POI1"},
                {"time": "12:30", "activity": "Pranzo", "location": "Siena"},
            ]},
            {"day": 2, "title": "Ancora centro", "blocks": [
                {"time": "10:00", "activity": "Duomo di nuovo",
                 "location": "Siena", "poi_id": "POI1"},
            ]},
        ],
    }
    VIAGGIO = {"destination": "Siena", "date_start": "2026-09-01",
               "date_end": "2026-09-03", "duration_days": 2,
               "budget_eur": 500}
    GUIDE = [{"poi_id": "POI1", "poi_name": "Duomo", "title": "Duomo",
              "history_summary": "Una storia lunga.",
              "practical_tips": ["Vai presto."]}]

    @classmethod
    def setUpClass(cls):
        from src import pdf_renderer, poi_pdf

        cls.tmp = tempfile.mkdtemp(prefix="fascicolo-vero-")
        ritorni = fascicolo.elenca_ritorni(cls.ITINERARIO, cls.GUIDE)
        cls.capitoli = poi_pdf.costruisci_capitoli(
            cls.GUIDE, ritorni, destination="Siena")
        percorso = str(Path(cls.tmp) / "itinerario.pdf")
        pdf_renderer.render_pdf(
            cls.ITINERARIO, cls.VIAGGIO, guides=cls.GUIDE,
            capitoli_pdf=cls.capitoli, output_path=percorso,
            allegati={"Valigia.xlsx": b"PK\x03\x04finto foglio"},
        )
        cls.dati = Path(percorso).read_bytes()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_nel_documento_finito_non_resta_un_collegamento_morto(self):
        letto = pdf_links.analyse(self.dati)
        self.assertEqual(letto["rotti"], {})
        self.assertEqual(letto["sonde"], {})
        self.assertGreater(letto["goto"], 0)

    def test_il_capitolo_e_dentro_lo_stesso_file(self):
        # «questi documenti seppur diversi stiano in un unico file». Il
        # capitolo esiste: il documento è più lungo delle sole pagine
        # dell'itinerario, e il testo della guida si legge qui dentro.
        self.assertTrue(self.capitoli, "nessun capitolo stampato")
        self.assertGreater(_pagine_di(self.dati),
                           _pagine_di_soli_itinerario())

    def test_la_guida_non_e_stampata_due_volte(self):
        # Se il capitolo interno restasse anche nel principale, il cliente si
        # ritroverebbe la stessa guida due volte — esattamente il peso che
        # Lorenzo ha chiesto di togliere.
        from src import pdf_renderer

        html = pdf_renderer.render_html(
            self.ITINERARIO, self.VIAGGIO, guides=self.GUIDE,
            capitoli={"POI1": fascicolo.ancora_capitolo("POI1")},
        )
        self.assertNotIn("Una storia lunga.", html)
        self.assertIn(
            f"href='{pdf_links.href_interno(fascicolo.ancora_capitolo('POI1'))}'",
            html)

    def test_ogni_passaggio_semina_il_suo_ritorno_nel_punto_giusto(self):
        # Due passaggi al Duomo, due segnaposti distinti, ognuno accanto al
        # collegamento che porta via da quel punto.
        from src import pdf_renderer

        html = pdf_renderer.render_html(
            self.ITINERARIO, self.VIAGGIO, guides=self.GUIDE,
            capitoli={"POI1": fascicolo.ancora_capitolo("POI1")},
        )
        primo = fascicolo.ancora_ritorno("POI1", ("blocco", 1, 0))
        secondo = fascicolo.ancora_ritorno("POI1", ("blocco", 2, 0))
        self.assertIn(f"id='{primo}' class='anchor-probe'", html)
        self.assertIn(f"id='{secondo}' class='anchor-probe'", html)

    def test_dal_capitolo_si_torna_alla_cartina_con_un_bersaglio_solo(self):
        # Tutte le tappe di una cartina tornano nello stesso punto, quindi
        # condividono lo stesso nome: nove nomi per un posto solo erano nove
        # segnaposti ammucchiati, e quattro non uscivano affatto.
        voci = fascicolo.elenca_ritorni(
            self.ITINERARIO, self.GUIDE, giorni_con_cartina=[2])["POI1"]
        da_cartina = [v for v in voci if v["origine"][0] == "cartina"]
        self.assertEqual([v["ancora"] for v in da_cartina],
                         [fascicolo.ancora_cartina(2)])

    def test_se_la_cartina_non_esce_il_ritorno_atterra_lo_stesso(self):
        """La seconda cintura sulla stessa caduta.

        Un giorno può avere la sua cartina PREVISTA e non riuscire a
        stamparla — succede quando Google Static Maps non risponde. Il
        capitolo è già stato stampato con il suo bottone «torna alla
        cartina»: se il segnaposto sparisse insieme all'immagine, quel
        bottone diventerebbe un collegamento morto. Deve atterrare all'inizio
        della giornata, cioè dove la cartina sarebbe stata.
        """
        from unittest import mock

        from src import pdf_renderer

        piani = [{"day": 1, "url": "https://esempio.it/x", "pins": []},
                 {"day": 2, "url": "https://esempio.it/y", "pins": []}]
        with mock.patch.object(pdf_renderer, "_render_day_map",
                               return_value=""):
            html = pdf_renderer.render_html(
                self.ITINERARIO, self.VIAGGIO, guides=self.GUIDE,
                capitoli={"POI1": fascicolo.ancora_capitolo("POI1")},
                day_maps=piani,
            )
        for giorno in (1, 2):
            nome = fascicolo.ancora_cartina(giorno)
            self.assertIn(f"id='{nome}' class='anchor-probe'", html)

    def test_senza_capitoli_il_documento_resta_quello_di_ieri(self):
        # La regressione che conta di più: chi non usa il fascicolo non deve
        # accorgersi di niente.
        from src import pdf_renderer

        html = pdf_renderer.render_html(
            self.ITINERARIO, self.VIAGGIO, guides=self.GUIDE)
        self.assertIn("Una storia lunga.", html)
        self.assertNotIn(fascicolo.ancora_capitolo("POI1"), html)

    def test_il_foglio_della_valigia_viaggia_col_documento(self):
        from pypdf import PdfReader

        lettore = PdfReader(io.BytesIO(self.dati))
        self.assertIn("Valigia.xlsx", lettore.attachments)


@unittest.skipUnless(HA_WKHTMLTOPDF, "wkhtmltopdf non installato")
class TestIlCampioneConsegnatoNonHaCollegamentiMorti(unittest.TestCase):
    """Il controllo che ha trovato il difetto che nessun altro vedeva.

    I controlli sui pezzi guardano un itinerario finto con una tappa sola.
    Il campione vero ne ha nove su due giornate, e proprio quel numero ha
    fatto emergere due difetti che con una tappa sola erano invisibili:

      1. tutte le tappe di una cartina condividevano la stessa posizione di
         partenza, e la tabella delle ancore ne teneva UNA sola: otto
         bottoni su nove restavano senza bersaglio;
      2. due segnaposti attaccati producevano una sola annotazione.

    Nessuno dei due si vedeva guardando il documento: si vedeva solo
    contando i collegamenti sul file finito. È questo che conta il controllo.

    Costa qualche minuto perché stampa davvero nove capitoli. Vale il prezzo:
    è l'unico che guarda il documento che il cliente riceve.
    """

    @classmethod
    def setUpClass(cls):
        import scripts_sample_pdf
        from src import pdf_renderer

        itinerary, trip, kwargs, errori = \
            scripts_sample_pdf.build_sample_render_kwargs(con_fascicolo=True)
        assert not errori, f"il campione monta con sezioni cadute: {errori}"
        cls.capitoli = kwargs.get("capitoli_pdf") or []
        cls.tmp = tempfile.mkdtemp(prefix="campione-fascicolo-")
        percorso = str(Path(cls.tmp) / "campione.pdf")
        pdf_renderer.render_pdf(itinerary, trip, output_path=percorso, **kwargs)
        cls.dati = Path(percorso).read_bytes()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_il_campione_ha_davvero_i_capitoli_staccati(self):
        # Senza questa riga tutto il resto passerebbe a vuoto: zero capitoli
        # vuol dire zero rimandi da controllare.
        self.assertGreaterEqual(len(self.capitoli), 5)

    def test_non_resta_un_solo_collegamento_morto(self):
        letto = pdf_links.analyse(self.dati)
        self.assertEqual(
            letto["rotti"], {},
            "ci sono rimandi senza bersaglio: nel documento non si vede "
            "niente, il cliente ci clicca sopra e non succede nulla",
        )
        self.assertEqual(letto["sonde"], {})

    def test_ogni_capitolo_e_raggiungibile_e_riporta_indietro(self):
        # Andata e ritorno per ognuna delle nove guide.
        letto = pdf_links.analyse(self.dati)
        self.assertGreaterEqual(letto["goto"], 2 * len(self.capitoli))


def _pagine_di_soli_itinerario() -> int:
    from src import pdf_renderer

    cartella = tempfile.mkdtemp(prefix="solo-itinerario-")
    try:
        percorso = str(Path(cartella) / "solo.pdf")
        pdf_renderer.render_pdf(
            TestIlDocumentoVeroDalPrincipioAllaFine.ITINERARIO,
            TestIlDocumentoVeroDalPrincipioAllaFine.VIAGGIO,
            guides=TestIlDocumentoVeroDalPrincipioAllaFine.GUIDE,
            capitoli_pdf=[{"poi_id": "POI1", "ancora": "capitolo-poi1",
                           "pdf": None}],
            output_path=percorso,
        )
        return _pagine_di(Path(percorso).read_bytes())
    finally:
        shutil.rmtree(cartella, ignore_errors=True)


def _pagine_di(dati: bytes) -> int:
    from pypdf import PdfReader

    return len(PdfReader(io.BytesIO(dati)).pages)


if __name__ == "__main__":
    unittest.main()
