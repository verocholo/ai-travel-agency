"""
LE GUIDE PER ATTRAZIONE — i controlli su `src/poi_pdf.py`.

[CREATO 2026-08-03 — richiesta di Lorenzo: "migliorare la guida turistica
linkando un pdf per attrazione da te generato ad hoc per la guida con ogni
attrazioni con immagini e tutto con bottone di torna all'itinerario alla
parte giusta", e sua scelta esplicita fra le due strade proposte: "PDF
separati, ospitati su Render"]

Che cosa sorveglia questo file
-----------------------------------------------------------------------------
Da oggi una parte del prodotto smette di essere un allegato di posta e
diventa un documento pubblicato su internet, raggiungibile da chiunque
conosca la URL. Cambiano quindi le cose che possono andare storte, e non
sono cose estetiche:

  * un testo che si rivolge al cliente per nome finisce su una pagina
    pubblica (`consiglio_personalizzato`);
  * una foto di qualcun altro viene stampata su un documento venduto senza
    la riga di attribuzione;
  * due attrazioni omonime si sovrascrivono a vicenda e il cliente trova la
    guida sbagliata dietro il link giusto;
  * la stampa di una guida fallisce e il capitolo sparisce da tutte e due i
    posti — dal documento principale (perché "tanto c'è la guida separata")
    e da internet (perché non è mai stata pubblicata);
  * l'ospitalità non è configurata su Render e il prodotto, invece di
    tornare tranquillamente al PDF unico di ieri, si rompe.

Ognuno di questi ha il suo test qui sotto. Il criterio di fondo è sempre lo
stesso: **una guida in meno è un peccato, un itinerario non consegnato è un
rimborso**. Nessun percorso di errore, in questo modulo, ha il diritto di
sollevare un'eccezione.
"""
import os
import pathlib
import shutil
import tempfile
import unittest

from src import hosting, pdf_extras, pdf_links, poi_pdf
from src.pdf_renderer import render_html


# ---------------------------------------------------------------------------
# Materiale di prova
# ---------------------------------------------------------------------------
# L'HTML esce con gli apostrofi gia' convertiti in `&#x27;` — e' `_esc()` che
# lo fa, ed e' giusto cosi': un apostrofo crudo dentro un attributo `href='...'`
# lo spezzerebbe. La trappola e' nei controlli NEGATIVI: cercare
# "Torna all'itinerario" nella forma con l'apostrofo non lo trova mai, quindi
# un `assertNotIn` scritto cosi' passerebbe sempre e non direbbe niente. Per
# questo l'etichetta sta qui una volta sola, nella forma vera.
ETICHETTA_RITORNO = "Torna all&#x27;itinerario"



def _guida(poi_id="PLACE_1", nome="Duomo di Siena", **extra) -> dict:
    """Una guida con tutti i campi che il modello compila davvero.

    I nomi dei campi seguono `prompts/system_prompt_guide.txt`: dentro
    `highlights` e `dintorni` la spiegazione si chiama `why`, non
    `description`. Sbagliare quel nome non fa fallire niente — semplicemente
    la spiegazione non viene stampata — ed è esattamente il tipo di errore
    silenzioso per cui vale la pena avere una prova fedele allo schema.
    """
    base = {
        "poi_id": poi_id,
        "poi_name": nome,
        "title": f"Il {nome}",
        "history_summary": "Due frasi di storia.\n\nE un secondo paragrafo.",
        "highlights": [{"name": "Il pavimento", "why": "Scoperto poche settimane l'anno."}],
        "curiosita": ["Il campanile ha sei ordini di finestre."],
        "practical_tips": ["Compra il biglietto cumulativo."],
        "errore_da_evitare": "Arrivare alle 11: e' l'ora dei gruppi.",
        "dintorni": [{"name": "Battistero", "why": "A due minuti, sotto l'abside."}],
        "best_time_to_visit": "Prima mattina",
        "estimated_visit_duration": "1 ora e 30",
        "consiglio_personalizzato": "Lorenzo, cerca il pulpito di Nicola Pisano.",
        "disclaimer": "Orari e prezzi possono cambiare.",
    }
    base.update(extra)
    return base


class _ConArchivio(unittest.TestCase):
    """Un archivio vero su disco in una cartella temporanea, come in
    `tests/test_hosting_2026_08_03.py`. Nessun finto filesystem: quello che
    ci preoccupa qui è proprio che i file finiscano dove devono, con il nome
    che devono avere."""

    BASE = "https://esempio-servizio.onrender.com"

    def setUp(self):
        self.radice = tempfile.mkdtemp(prefix="guide-test-")
        self._ambiente = {
            k: os.environ.get(k)
            for k in ("PUBLIC_FILES_DIR", "PUBLIC_BASE_URL")
        }
        os.environ["PUBLIC_FILES_DIR"] = self.radice
        os.environ["PUBLIC_BASE_URL"] = self.BASE
        self.consegna = hosting.new_delivery_id()

    def tearDown(self):
        shutil.rmtree(self.radice, ignore_errors=True)
        for chiave, valore in self._ambiente.items():
            if valore is None:
                os.environ.pop(chiave, None)
            else:
                os.environ[chiave] = valore


# ---------------------------------------------------------------------------
# 1. Che cosa finisce, e che cosa NON finisce, dentro una pagina pubblica
# ---------------------------------------------------------------------------
class TestCosaFinisceSuUnaPaginaPubblica(unittest.TestCase):

    def test_il_consiglio_personale_non_esce_mai_dalla_busta(self):
        """`consiglio_personalizzato` è l'unico campo della guida che si
        rivolge al cliente in seconda persona, spesso per nome. Nel PDF
        principale — che arriva per posta al solo destinatario — è il tocco
        che fa sentire il prodotto cucito addosso. Su una pagina raggiungibile
        da chiunque abbia la URL è un dato personale pubblicato.

        Se un giorno qualcuno lo aggiunge "per uniformità" con il documento
        principale, questo test glielo impedisce."""
        html = poi_pdf.build_guide_html(_guida())
        self.assertNotIn("Nicola Pisano", html)
        self.assertNotIn("Lorenzo", html)

    def test_tutto_il_resto_della_guida_invece_c_e(self):
        """Il controspecchio del test qui sopra: tolto il consiglio
        personale, la guida separata non deve essere una versione mutilata
        di quella interna, altrimenti il cliente ci perde."""
        html = poi_pdf.build_guide_html(_guida(), destination="Siena")
        for atteso in (
            "Duomo di Siena", "Due frasi di storia", "Il pavimento",
            "Scoperto poche settimane", "sei ordini di finestre",
            "biglietto cumulativo", "l&#x27;ora dei gruppi", "Battistero",
            "Prima mattina", "1 ora e 30", "Siena",
        ):
            self.assertIn(atteso, html, f"manca dalla guida: {atteso}")

    def test_niente_indirizzi_non_cifrati(self):
        """Stessa regola del documento principale: un `http://` dentro un
        PDF viene segnalato al lettore. Qui la sorgente del rischio è la
        scheda del luogo, che arriva da Google e non è sotto il nostro
        controllo."""
        scheda = {
            "address": "Piazza del Duomo 8",
            "tickets_link": {"url": "http://operaduomo.siena.it/", "label": "Biglietti"},
        }
        html = poi_pdf.build_guide_html(_guida(), place_card=scheda)
        self.assertNotIn("http://", html)
        # E il link scartato non deve nemmeno lasciare una riga vuota con
        # l'etichetta: o è cliccabile, o non c'è.
        self.assertNotIn("Biglietti e orari", html)

    def test_un_link_cifrato_invece_passa(self):
        scheda = {
            "tickets_link": {"url": "https://operaduomo.siena.it/", "label": "Sito ufficiale"},
        }
        html = poi_pdf.build_guide_html(_guida(), place_card=scheda)
        self.assertIn("https://operaduomo.siena.it/", html)
        self.assertIn("Sito ufficiale", html)

    def test_anche_il_bottone_di_ritorno_deve_essere_cifrato(self):
        html = poi_pdf.build_guide_html(
            _guida(), itinerary_url="http://esempio.it/itinerario.pdf"
        )
        self.assertNotIn("http://", html)
        self.assertNotIn(ETICHETTA_RITORNO, html)


# ---------------------------------------------------------------------------
# 2. Le foto
# ---------------------------------------------------------------------------
class TestLeFotoENonSoloLeFoto(unittest.TestCase):

    def test_niente_credito_niente_foto(self):
        """Una foto di Google Places si può ripubblicare, ma con la riga di
        attribuzione. Su un documento che il cliente ha pagato, stampare
        l'immagine di qualcun altro senza dire di chi è non è un dettaglio
        estetico: è il tipo di cosa che si paga cara una volta sola.

        La scelta scritta nel modulo è netta — se manca il credito la foto
        non si stampa affatto — e questo test la tiene ferma."""
        html = poi_pdf.build_guide_html(
            _guida(), photo={"png": b"\x89PNG\r\n\x1a\nfinta"}
        )
        self.assertNotIn("data:image/png;base64", html)

    def test_con_il_credito_la_foto_si_stampa_e_il_credito_si_vede(self):
        html = poi_pdf.build_guide_html(
            _guida(),
            photo={"png": b"\x89PNG\r\n\x1a\nfinta", "credito": "Foto: M. Rossi / Google"},
        )
        self.assertIn("data:image/png;base64", html)
        self.assertIn("Foto: M. Rossi / Google", html)

    def test_una_foto_vuota_non_stampa_un_riquadro_vuoto(self):
        html = poi_pdf.build_guide_html(
            _guida(), photo={"png": b"", "credito": "Foto: qualcuno"}
        )
        self.assertNotIn("data:image/png;base64", html)


# ---------------------------------------------------------------------------
# 3. Il bottone «torna all'itinerario»
# ---------------------------------------------------------------------------
class TestIlBottoneDiRitorno(unittest.TestCase):

    URL = "https://esempio.onrender.com/f/abc/def/itinerario.pdf"

    def test_c_e_il_bottone_quando_c_e_la_url(self):
        html = poi_pdf.build_guide_html(_guida(), itinerary_url=self.URL)
        self.assertIn(self.URL, html)
        self.assertIn(ETICHETTA_RITORNO, html)

    def test_senza_url_niente_vicolo_cieco_ma_una_spiegazione(self):
        """Il caso peggiore non è "manca il bottone": è una guida che finisce
        senza dire al cliente come tornare indietro. Quando la URL non c'è —
        ospitalità non configurata, o guida stampata prima dell'itinerario —
        al suo posto deve esserci una frase che spiega dove guardare."""
        html = poi_pdf.build_guide_html(_guida())
        self.assertNotIn(ETICHETTA_RITORNO, html)
        self.assertIn("documento principale", html)

    def test_il_bottone_diventa_un_link_vero_nel_pdf(self):
        """Non basta che l'HTML contenga un `<a>`: wkhtmltopdf deve
        trasformarlo in un'annotazione cliccabile. È il controllo che
        distingue "abbiamo scritto il codice" da "il cliente ci può
        cliccare sopra"."""
        try:
            from pypdf import PdfReader
        except ImportError:  # pragma: no cover - ambiente senza pypdf
            self.skipTest("pypdf non disponibile")
        import io

        blob = poi_pdf.render_guide_pdf(
            poi_pdf.build_guide_html(_guida(), itinerary_url=self.URL)
        )
        if not blob:  # pragma: no cover - ambiente senza wkhtmltopdf
            self.skipTest("wkhtmltopdf non disponibile")
        indirizzi = []
        for pagina in PdfReader(io.BytesIO(blob)).pages:
            annotazioni = pagina.get("/Annots")
            if annotazioni is None:
                continue
            for voce in annotazioni.get_object():
                azione = voce.get_object().get("/A")
                if azione is not None:
                    indirizzi.append(azione.get_object().get("/URI"))
        self.assertIn(self.URL, indirizzi)


# ---------------------------------------------------------------------------
# 4. La stampa
# ---------------------------------------------------------------------------
class TestLaStampaNonDeveMaiEsplodere(unittest.TestCase):

    def test_html_vuoto_ritorna_niente_senza_sollevare(self):
        self.assertIsNone(poi_pdf.render_guide_pdf(""))
        self.assertIsNone(poi_pdf.render_guide_pdf(None))
        self.assertIsNone(poi_pdf.render_guide_pdf("   "))

    def test_una_guida_completamente_vuota_produce_comunque_un_documento(self):
        """Il modello può restituire una guida quasi vuota. Non è un motivo
        per far saltare la consegna: deve uscire una pagina povera, non
        un'eccezione."""
        html = poi_pdf.build_guide_html({})
        self.assertIn("<html", html)
        self.assertIn("</html>", html)

    def test_i_caratteri_speciali_non_rompono_la_pagina(self):
        html = poi_pdf.build_guide_html(
            _guida(nome="Chiesa <b>di</b> Sant'Agostino & C.")
        )
        self.assertNotIn("<b>di</b>", html)
        self.assertIn("&amp;", html)


# ---------------------------------------------------------------------------
# 5. I nomi dei file: quello che finisce dentro la URL
# ---------------------------------------------------------------------------
class TestIlNomeDentroLaUrl(unittest.TestCase):

    def test_il_nome_descrive_il_luogo_non_il_cliente(self):
        """La regola è la stessa scritta in cima a `src/hosting.py`: nella
        URL non deve comparire niente che identifichi una persona."""
        nome = poi_pdf.nome_file_guida(_guida(), 0)
        self.assertEqual(nome, "guida-duomo-di-siena")

    def test_un_nome_impronunciabile_non_produce_un_file_senza_nome(self):
        """Un POI con nome tutto in caratteri non latini svuota lo `slug`.
        Senza questa rete si otterrebbe `guida-` per tutti, e le attrazioni
        si sovrascriverebbero a vicenda."""
        self.assertEqual(poi_pdf.nome_file_guida({"poi_name": "東京"}, 3), "guida-4")
        self.assertEqual(poi_pdf.nome_file_guida({}, 0), "guida-1")

    def test_il_nome_non_supera_il_limite_dell_archivio(self):
        """`hosting.store()` taglia a 64 caratteri; qui si sta sotto, così
        il taglio non avviene mai a valle dove nessuno lo vedrebbe."""
        lungo = poi_pdf.nome_file_guida({"poi_name": "Basilica " * 30}, 0)
        self.assertLessEqual(len(lungo), 60)


# ---------------------------------------------------------------------------
# 6. La pubblicazione
# ---------------------------------------------------------------------------
class TestLaPubblicazione(_ConArchivio):

    def test_senza_ospitalita_configurata_non_succede_niente_di_male(self):
        """È il caso normale finché `PUBLIC_BASE_URL` non è impostata su
        Render. Il prodotto deve tornare esattamente a quello di ieri — un
        unico PDF con le guide dentro — non rompersi."""
        os.environ.pop("PUBLIC_BASE_URL", None)
        self.assertEqual(
            poi_pdf.publish_guides([_guida()], consegna=self.consegna), {}
        )

    def test_senza_guide_non_si_pubblica_niente(self):
        self.assertEqual(poi_pdf.publish_guides([], consegna=self.consegna), {})
        self.assertEqual(poi_pdf.publish_guides(None, consegna=self.consegna), {})

    def test_una_guida_pubblicata_torna_come_url_cifrata(self):
        urls = poi_pdf.publish_guides(
            [_guida(poi_id="PLACE_1")], consegna=self.consegna, destination="Siena"
        )
        if not urls:  # pragma: no cover - ambiente senza wkhtmltopdf
            self.skipTest("wkhtmltopdf non disponibile")
        self.assertIn("PLACE_1", urls)
        self.assertTrue(urls["PLACE_1"].startswith("https://"))
        self.assertIn("guida-duomo-di-siena.pdf", urls["PLACE_1"])

    def test_il_file_pubblicato_si_rilegge_ed_e_un_pdf(self):
        urls = poi_pdf.publish_guides([_guida()], consegna=self.consegna)
        if not urls:  # pragma: no cover
            self.skipTest("wkhtmltopdf non disponibile")
        token = hosting.reserve(self.consegna)
        letto = hosting.resolve(self.consegna, token, "guida-duomo-di-siena.pdf")
        self.assertIsNotNone(letto)
        self.assertTrue(letto[0].startswith(b"%PDF"))

    def test_due_attrazioni_omonime_non_si_sovrascrivono(self):
        """Due chiese con lo stesso nome esistono davvero, e in silenzio la
        seconda cancellerebbe la prima: il cliente troverebbe la guida
        sbagliata dietro il link giusto, che è peggio di un link rotto
        perché non se ne accorgerebbe."""
        urls = poi_pdf.publish_guides(
            [_guida(poi_id="A", nome="San Giovanni"),
             _guida(poi_id="B", nome="San Giovanni")],
            consegna=self.consegna,
        )
        if not urls:  # pragma: no cover
            self.skipTest("wkhtmltopdf non disponibile")
        self.assertEqual(len(urls), 2)
        self.assertNotEqual(urls["A"], urls["B"])

    def test_una_guida_senza_identificativo_viene_saltata_non_pubblicata_a_caso(self):
        """Senza `poi_id` non c'è modo di collegare la guida al pallino
        della cartina: pubblicarla creerebbe un file che nessuno raggiunge
        mai e che resta comunque leggibile da chi indovina la URL."""
        urls = poi_pdf.publish_guides(
            [_guida(poi_id=None), _guida(poi_id="BUONO")], consegna=self.consegna
        )
        if not urls:  # pragma: no cover
            self.skipTest("wkhtmltopdf non disponibile")
        self.assertEqual(list(urls), ["BUONO"])

    def test_una_stampa_fallita_toglie_solo_quella_guida(self):
        """La degradazione parziale è tutto il punto del disegno: il
        documento principale continuerà a stampare il capitolo interno per
        l'attrazione che non è stata pubblicata. Se invece un fallimento
        facesse saltare l'intera pubblicazione, un timeout su una guida
        toglierebbe i link a tutte."""
        originale = poi_pdf.render_guide_pdf
        chiamate = {"n": 0}

        def _stampa_capricciosa(html):
            chiamate["n"] += 1
            if chiamate["n"] == 1:
                return None
            return b"%PDF-1.4 finto"

        poi_pdf.render_guide_pdf = _stampa_capricciosa
        try:
            urls = poi_pdf.publish_guides(
                [_guida(poi_id="ROTTA", nome="Prima"),
                 _guida(poi_id="SANA", nome="Seconda")],
                consegna=self.consegna,
            )
        finally:
            poi_pdf.render_guide_pdf = originale
        self.assertEqual(list(urls), ["SANA"])

    def test_non_si_stampano_piu_guide_del_tetto(self):
        """Ogni guida è una stampa `wkhtmltopdf` da qualche secondo, e Make
        chiude l'esecuzione a 300 secondi. Il tetto non è una raffinatezza:
        senza, un itinerario di sette giorni con trenta tappe non verrebbe
        consegnato affatto.

        Chi resta fuori non perde niente: per quelle attrazioni il documento
        principale continua a stampare il capitolo interno."""
        originale = poi_pdf.render_guide_pdf
        poi_pdf.render_guide_pdf = lambda html: b"%PDF-1.4 finto"
        try:
            urls = poi_pdf.publish_guides(
                [_guida(poi_id=f"P{i}", nome=f"Luogo {i}") for i in range(40)],
                consegna=self.consegna,
            )
        finally:
            poi_pdf.render_guide_pdf = originale
        self.assertEqual(len(urls), poi_pdf.MAX_GUIDE)
        self.assertLessEqual(poi_pdf.MAX_GUIDE, 12)

    def test_la_url_dell_itinerario_arriva_dentro_ogni_guida(self):
        """Il giro completo che Lorenzo ha chiesto — "bottone di torna
        all'itinerario alla parte giusta" — funziona solo se la URL del
        documento principale, calcolata PRIMA che il documento esista,
        arriva davvero dentro il PDF di ogni attrazione."""
        vista = {}
        originale = poi_pdf.render_guide_pdf
        poi_pdf.render_guide_pdf = lambda html: vista.setdefault("html", html) and None or b"%PDF-1.4 x"
        try:
            poi_pdf.publish_guides(
                [_guida()], consegna=self.consegna,
                itinerary_url="https://esempio.it/f/a/b/itinerario.pdf",
            )
        finally:
            poi_pdf.render_guide_pdf = originale
        self.assertIn("https://esempio.it/f/a/b/itinerario.pdf", vista.get("html", ""))

    def test_la_scheda_del_luogo_e_il_come_arrivare_finiscono_nella_guida(self):
        """È la meta' "micro" dello zoom out: orari, biglietti, contatti e
        come arrivare devono stare QUI, perché è per questo che il documento
        principale può permettersi di diventare più scarno."""
        vista = {}
        originale = poi_pdf.render_guide_pdf
        poi_pdf.render_guide_pdf = lambda html: vista.setdefault("html", html) and None or b"%PDF-1.4 x"
        try:
            poi_pdf.publish_guides(
                [_guida(poi_id="P1")], consegna=self.consegna,
                place_cards={"P1": {"address": "Piazza del Duomo 8", "phone": "+39 0577 286300"}},
                directions_by_poi={"P1": "7 minuti a piedi da Piazza del Campo (550 m)."},
            )
        finally:
            poi_pdf.render_guide_pdf = originale
        html = vista.get("html", "")
        self.assertIn("Piazza del Duomo 8", html)
        self.assertIn("+39 0577 286300", html)
        self.assertIn("550 m", html)

    def test_argomenti_sbagliati_non_fanno_saltare_la_consegna(self):
        """Chi chiama passa quello che ha: dizionari `None`, liste con
        dentro stringhe, chiavi che non esistono. Niente di tutto questo
        deve arrivare al cliente come una consegna mancata."""
        originale = poi_pdf.render_guide_pdf
        poi_pdf.render_guide_pdf = lambda html: b"%PDF-1.4 x"
        try:
            urls = poi_pdf.publish_guides(
                [_guida(poi_id="P1"), "non una guida", None, 42],
                consegna=self.consegna,
                place_cards="non un dizionario",
                photos=None,
                directions_by_poi=["nemmeno questo"],
            )
        finally:
            poi_pdf.render_guide_pdf = originale
        self.assertEqual(list(urls), ["P1"])


# ---------------------------------------------------------------------------
# 7. Il documento principale dimagrisce — ma solo dove puo' permetterselo
# ---------------------------------------------------------------------------
class TestIlDocumentoPrincipaleDimagrisce(unittest.TestCase):
    """Richiesta di Lorenzo: "cosi' il documento principale appare piu' pulito
    piu' scarno andando a toglierli dal documento principale, come se fosse
    uno zoom out dal macro al micro".

    Qui si sorveglia la meta' pericolosa di quella frase. Togliere un
    capitolo e' facile; il difetto che il cliente pagherebbe e' toglierlo
    quando la guida separata NON e' stata pubblicata — a quel punto la guida
    non esiste piu' da nessuna parte e nessuna prova automatica se ne
    accorge, perche' il documento esce lo stesso, solo piu' povero.
    """

    GUIDE = [
        {"poi_id": "P1", "poi_name": "Duomo", "title": "Il Duomo",
         "history_summary": "Storia del Duomo, riconoscibile."},
        {"poi_id": "P2", "poi_name": "Fortezza", "title": "La Fortezza",
         "history_summary": "Storia della Fortezza, riconoscibile."},
    ]

    def _documento(self, guide_urls=None):
        return render_html(
            {"days": []}, {"destination": "Siena"},
            guides=[dict(g) for g in self.GUIDE], guide_urls=guide_urls,
            poi=[{"id": "P1", "name": "Duomo"}, {"id": "P2", "name": "Fortezza"}],
        )

    def test_senza_pubblicazione_i_capitoli_restano_tutti(self):
        """Il comportamento di ieri, che deve restare quello di sempre finche'
        `PUBLIC_BASE_URL` non e' impostata su Render."""
        out = self._documento()
        self.assertIn("Storia del Duomo", out)
        self.assertIn("Storia della Fortezza", out)
        self.assertIn("Guide turistiche tascabili", out)

    def test_il_capitolo_sparisce_solo_per_chi_e_stato_pubblicato(self):
        out = self._documento(guide_urls={"P1": "https://esempio.it/f/a/b/guida-duomo.pdf"})
        self.assertNotIn("Storia del Duomo", out)
        self.assertIn("Storia della Fortezza", out)

    def test_una_url_non_cifrata_non_toglie_niente(self):
        """Il filtro guarda la URL, non l'intenzione. Un indirizzo che non
        sarebbe comunque stampato non ha il diritto di far sparire un
        capitolo: sarebbe una guida persa due volte."""
        out = self._documento(guide_urls={"P1": "http://esempio.it/guida.pdf"})
        self.assertIn("Storia del Duomo", out)

    def test_pubblicate_tutte_la_sezione_intera_se_ne_va(self):
        out = self._documento(guide_urls={
            "P1": "https://esempio.it/f/a/b/guida-duomo.pdf",
            "P2": "https://esempio.it/f/a/b/guida-fortezza.pdf",
        })
        self.assertNotIn("Storia del Duomo", out)
        self.assertNotIn("Storia della Fortezza", out)
        self.assertNotIn("Guide turistiche tascabili", out)

    def test_e_se_ne_va_anche_dall_indice(self):
        """Una voce d'indice che punta a un capitolo inesistente e' un link
        morto stampato in copertina — il primo che il cliente prova."""
        out = self._documento(guide_urls={
            "P1": "https://esempio.it/f/a/b/guida-duomo.pdf",
            "P2": "https://esempio.it/f/a/b/guida-fortezza.pdf",
        })
        self.assertNotIn("Guide turistiche tascabili", out)

    def test_il_conto_in_copertina_non_mente_sulle_guide_che_il_cliente_ha(self):
        """Le guide pubblicate non sono guide perse: sono altrove. La
        copertina deve continuare a contarle tutte, altrimenti il documento
        dichiara meno di quello che il cliente ha davvero comprato."""
        out = self._documento(guide_urls={"P1": "https://esempio.it/f/a/b/g.pdf"})
        self.assertIn("2", out)


# ---------------------------------------------------------------------------
# 8. Il collegamento dentro il programma della giornata
# ---------------------------------------------------------------------------
class TestIlCollegamentoDentroIlProgramma(unittest.TestCase):
    """Il link "guida turistica" stampato accanto a un blocco della giornata
    deve portare dove portano il pallino della cartina e la riga di legenda.
    Tre strade per lo stesso posto sono un'occasione perfetta per farne
    divergere una."""

    def _documento(self, guide_urls=None):
        return render_html(
            {"days": [{"day": 1, "title": "Centro", "blocks": [
                {"time": "09:00", "activity": "Visita al Duomo",
                 "poi_id": "P1", "location": "Piazza del Duomo"},
            ]}]},
            {"destination": "Siena"},
            guides=[{"poi_id": "P1", "poi_name": "Duomo", "title": "Il Duomo",
                     "history_summary": "Storia."}],
            guide_urls=guide_urls,
            poi=[{"id": "P1", "name": "Duomo"}],
        )

    def test_senza_pubblicazione_il_link_resta_interno(self):
        out = self._documento()
        # L'ancora nasce dal `poi_id`, NON dal nome: in `render_html` la chiave
        # e' `guide.get("poi_id") or guide.get("poi_name")`, quindi con
        # poi_id="P1" l'ancora vera e' `guida-p1` e non `guida-duomo`.
        # Scriverlo sbagliato qui non si vede (l'assertIn fallisce e lo scopri),
        # ma scriverlo sbagliato in un assertNotIn passa per sempre a vuoto.
        # [AGGIORNATO 2026-08-13] Era `href='#guida-p1'`. I rimandi interni
        # ora escono verso un indirizzo sentinella: e' l'unica forma che in
        # produzione arriva intatta fino al PDF venduto.
        self.assertIn(f"href='{pdf_links.href_interno('guida-p1')}'", out)
        self.assertIn("Guida turistica tascabile", out)

    def test_con_la_pubblicazione_il_link_porta_al_documento_vero(self):
        url = "https://esempio.it/f/a/b/guida-duomo.pdf"
        out = self._documento(guide_urls={"P1": url})
        self.assertIn(f"href='{url}'", out)
        # Stesso discorso al contrario: il capitolo interno non deve piu'
        # esistere, e l'unica ancora che potrebbe esistere e' `guida-p1`.
        # L'`assertNotIn` va aggiornato con ancora piu' cura dell'assertIn:
        # cercando la forma vecchia non fallirebbe mai piu', qualunque cosa
        # succeda al prodotto.
        self.assertNotIn(f"href='{pdf_links.href_interno('guida-p1')}'", out)

    def test_la_dicitura_dice_la_verita_su_dove_si_va(self):
        """"Tascabile" promette una cosa che un documento ospitato non
        mantiene: senza rete non si apre. La parola cambia perche' cambia la
        promessa, non per varieta' di stile."""
        out = self._documento(guide_urls={"P1": "https://esempio.it/f/a/b/g.pdf"})
        self.assertIn("Apri la guida turistica", out)


# ---------------------------------------------------------------------------
# 9. Il montaggio: `pdf_extras` mette insieme i pezzi
# ---------------------------------------------------------------------------
class TestIlMontaggio(_ConArchivio):

    def test_il_come_arrivare_si_gira_dal_punto_di_vista_dell_attrazione(self):
        tratte = [{"day": 1, "legs": [
            {"from_name": "Albergo", "to_poi_id": "P1", "duration_text": "circa 8 min a piedi"},
            {"from_name": "Duomo", "to_poi_id": "P2", "duration_text": "circa 5 min a piedi"},
        ]}]
        fuori = pdf_extras.build_directions_by_poi(tratte)
        self.assertEqual(fuori["P1"], "Da Albergo, circa 8 min a piedi.")
        self.assertEqual(fuori["P2"], "Da Duomo, circa 5 min a piedi.")

    def test_quando_un_posto_torna_piu_volte_vince_la_prima_volta(self):
        """E' l'unica volta in cui la domanda "come ci arrivo?" e' davvero
        aperta: le successive il cliente c'e' gia' stato."""
        tratte = [
            {"day": 1, "legs": [{"from_name": "Albergo", "to_poi_id": "P1",
                                 "duration_text": "circa 8 min a piedi"}]},
            {"day": 2, "legs": [{"from_name": "Stazione", "to_poi_id": "P1",
                                 "duration_text": "circa 20 min in autobus"}]},
        ]
        self.assertEqual(
            pdf_extras.build_directions_by_poi(tratte)["P1"],
            "Da Albergo, circa 8 min a piedi.",
        )

    def test_tratte_malformate_non_producono_righe_finte(self):
        self.assertEqual(pdf_extras.build_directions_by_poi(None), {})
        self.assertEqual(pdf_extras.build_directions_by_poi(["non un dizionario"]), {})
        self.assertEqual(
            pdf_extras.build_directions_by_poi(
                [{"legs": [{"to_poi_id": "P1"}, {"from_name": "X"}]}]
            ),
            {},
        )

    def test_senza_ospitalita_il_montaggio_non_tocca_le_sezioni(self):
        os.environ.pop("PUBLIC_BASE_URL", None)
        sezioni = {"feedback_link": {"ref": "abc123"}}
        esito = pdf_extras.publish_hosted_guides([_guida()], sezioni)
        self.assertEqual(esito["guide_urls"], {})
        self.assertIsNone(esito["itinerary_url"])
        self.assertNotIn("guide_urls", sezioni)

    def test_la_consegna_e_lo_stesso_codice_della_recensione(self):
        """Due identificativi diversi per la stessa vendita significano non
        riuscire piu' a collegare un documento pubblicato a chi l'ha
        comprato. Il `ref` della recensione e' gia' quello che Make archivia
        in Airtable: si riusa quello."""
        originale = poi_pdf.render_guide_pdf
        poi_pdf.render_guide_pdf = lambda html: b"%PDF-1.4 x"
        try:
            esito = pdf_extras.publish_hosted_guides(
                [_guida()], {"feedback_link": {"ref": "rif-di-prova"}},
            )
        finally:
            poi_pdf.render_guide_pdf = originale
        self.assertEqual(esito["consegna"], "rif-di-prova")
        self.assertIn("rif-di-prova", esito["itinerary_url"])

    def test_senza_recensione_si_genera_comunque_una_consegna(self):
        originale = poi_pdf.render_guide_pdf
        poi_pdf.render_guide_pdf = lambda html: b"%PDF-1.4 x"
        try:
            esito = pdf_extras.publish_hosted_guides([_guida()], {})
        finally:
            poi_pdf.render_guide_pdf = originale
        self.assertTrue(esito["consegna"])
        self.assertTrue(esito["itinerary_url"].startswith("https://"))

    def test_le_url_finiscono_dentro_le_sezioni_pronte_per_il_renderer(self):
        originale = poi_pdf.render_guide_pdf
        poi_pdf.render_guide_pdf = lambda html: b"%PDF-1.4 x"
        sezioni = {"feedback_link": {"ref": "abc123"}}
        try:
            pdf_extras.publish_hosted_guides([_guida(poi_id="P1")], sezioni)
        finally:
            poi_pdf.render_guide_pdf = originale
        self.assertIn("P1", sezioni["guide_urls"])
        # E la chiave deve passare il filtro a lista bianca, altrimenti il
        # renderer non la vedrebbe mai e tutto questo lavoro sarebbe muto.
        argomenti, _ = pdf_extras.split_render_kwargs(sezioni)
        self.assertIn("guide_urls", argomenti)

    def test_la_url_dell_itinerario_si_calcola_prima_che_il_documento_esista(self):
        """E' il nodo dell'intero disegno: la guida contiene il bottone
        "torna all'itinerario", ma l'itinerario non e' ancora stato stampato
        quando la guida viene costruita. Il token si riserva prima."""
        originale = poi_pdf.render_guide_pdf
        poi_pdf.render_guide_pdf = lambda html: b"%PDF-1.4 x"
        try:
            esito = pdf_extras.publish_hosted_guides(
                [_guida()], {"feedback_link": {"ref": "abc123"}},
            )
        finally:
            poi_pdf.render_guide_pdf = originale
        # Ora il documento principale viene scritto DOPO, sotto la stessa
        # URL che le guide hanno gia' stampato.
        effettiva = hosting.store(esito["consegna"], "itinerario", b"%PDF-1.4 principale")
        self.assertEqual(effettiva, esito["itinerary_url"])

    def test_un_guasto_nel_montaggio_non_porta_giu_la_consegna(self):
        originale = poi_pdf.publish_guides
        poi_pdf.publish_guides = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("disco pieno"))
        try:
            esito = pdf_extras.publish_hosted_guides(
                [_guida()], {"feedback_link": {"ref": "abc123"}},
            )
        finally:
            poi_pdf.publish_guides = originale
        self.assertEqual(esito["guide_urls"], {})


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


# ---------------------------------------------------------------------------
# 10. Il giro completo: la URL stampata dentro le guide e il posto dove
#     l'itinerario finisce davvero devono essere lo STESSO posto
# ---------------------------------------------------------------------------
class TestIlRitornoPortaAUnFileCheEsiste(_ConArchivio):
    """È l'unico punto del meccanismo dove un errore non si vede da nessuna
    parte: le guide stampano il bottone "Torna all'itinerario" PRIMA che
    l'itinerario esista, quindi la stampa riesce comunque, il PDF è valido,
    il bottone è cliccabile — e porta a una pagina che non c'è.

    Nessun test del renderer può accorgersene, perché dal punto di vista del
    renderer è tutto a posto. Se ne accorgerebbe solo il cliente, dopo aver
    pagato. Per questo la prova sta qui e guarda le due estremità insieme:
    l'indirizzo prenotato e l'indirizzo dove il file viene poi salvato.
    """

    def _sezioni(self, ref="RIF123"):
        return {"feedback_link": {"ref": ref}, "directions": [], "place_cards": []}

    def test_lindirizzo_prenotato_e_quello_dove_il_file_finisce(self):
        sezioni = self._sezioni()
        esito = pdf_extras.publish_hosted_guides(
            [_guida()], sezioni, destination="Siena"
        )
        if not esito.get("itinerary_url"):  # pragma: no cover
            self.skipTest("wkhtmltopdf non disponibile")
        # Questa è la riga che `service.py` esegue appena il PDF esiste.
        salvato = hosting.store(esito["consegna"], "itinerario", b"%PDF-finto")
        self.assertEqual(salvato, esito["itinerary_url"])

    def test_il_file_salvato_si_rilegge_dallindirizzo_del_bottone(self):
        sezioni = self._sezioni()
        esito = pdf_extras.publish_hosted_guides([_guida()], sezioni)
        if not esito.get("itinerary_url"):  # pragma: no cover
            self.skipTest("wkhtmltopdf non disponibile")
        hosting.store(esito["consegna"], "itinerario", b"%PDF-finto")
        letto = hosting.resolve(
            esito["consegna"], esito["token"], "itinerario.pdf"
        )
        self.assertIsNotNone(letto)
        self.assertEqual(letto[0], b"%PDF-finto")

    def test_la_consegna_e_la_stessa_del_collegamento_recensione(self):
        """Un solo identificativo per vendita: è quello che Make archivia in
        Airtable. Se qui ne nascesse un secondo, un documento pubblicato non
        sarebbe più ricollegabile all'acquisto — e quindi nemmeno
        cancellabile su richiesta del cliente."""
        esito = pdf_extras.publish_hosted_guides(
            [_guida()], self._sezioni(ref="ABC999")
        )
        if not esito.get("consegna"):  # pragma: no cover
            self.skipTest("wkhtmltopdf non disponibile")
        self.assertEqual(esito["consegna"], "ABC999")

    def test_le_url_delle_guide_finiscono_dentro_le_sezioni(self):
        sezioni = self._sezioni()
        esito = pdf_extras.publish_hosted_guides([_guida()], sezioni)
        if not esito.get("guide_urls"):  # pragma: no cover
            self.skipTest("wkhtmltopdf non disponibile")
        self.assertEqual(sezioni.get("guide_urls"), esito["guide_urls"])

    def test_senza_ospitalita_le_sezioni_restano_intatte(self):
        os.environ.pop("PUBLIC_BASE_URL", None)
        sezioni = self._sezioni()
        esito = pdf_extras.publish_hosted_guides([_guida()], sezioni)
        self.assertEqual(esito["guide_urls"], {})
        self.assertIsNone(esito["itinerary_url"])
        self.assertNotIn("guide_urls", sezioni)


# ---------------------------------------------------------------------------
# 11. Che il meccanismo sia davvero ACCESO
# ---------------------------------------------------------------------------
class TestIlMeccanismoEAcceso(unittest.TestCase):
    """Tutto quello che sta sopra prova che il meccanismo funziona. Nessuna di
    quelle prove si accorgerebbe però se nessuno lo chiamasse: le funzioni
    resterebbero corrette, i test verdi, e il documento tornerebbe in silenzio
    quello di ieri.

    È già successo in questo progetto (una sezione scritta, provata e mai
    collegata), quindi qui si guarda il codice sorgente vero di `service.py` e
    `main.py`. È una prova grezza, ma è l'unica che fallisce se qualcuno
    riordina quei file e si porta via la chiamata.
    """

    RADICE = pathlib.Path(__file__).resolve().parent.parent

    def _sorgente(self, nome):
        return (self.RADICE / nome).read_text(encoding="utf-8")

    def test_il_servizio_pubblica_le_guide(self):
        self.assertIn("publish_hosted_guides(", self._sorgente("service.py"))

    def test_il_servizio_salva_anche_litinerario(self):
        """La metà che si dimentica: senza questa riga i bottoni di ritorno
        stampati dentro le guide portano tutti a una pagina inesistente."""
        sorgente = self._sorgente("service.py")
        self.assertIn('hosting.store(', sorgente)
        self.assertIn('"itinerario", pdf_bytes', sorgente)

    def test_la_pubblicazione_avviene_prima_del_filtro_delle_sezioni(self):
        """`split_render_kwargs()` tiene solo le chiavi che il renderer
        accetta: se la pubblicazione avvenisse dopo, `guide_urls` nascerebbe
        già scartata e il documento principale non dimagrirebbe mai."""
        sorgente = self._sorgente("service.py")
        self.assertLess(
            sorgente.index("publish_hosted_guides("),
            sorgente.index("sections, section_errors = split_render_kwargs("),
        )

    def test_anche_la_riga_di_comando_fa_la_stessa_cosa(self):
        """Se il PDF di prova fosse diverso da quello del cliente, provarlo in
        locale non direbbe più niente su cosa riceve chi paga."""
        self.assertIn("publish_hosted_guides(", self._sorgente("main.py"))
