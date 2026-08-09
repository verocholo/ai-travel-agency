"""
L'ARCHIVIO PUBBLICO — i controlli su `src/hosting.py`.

[CREATO 2026-08-03 — richiesta di Lorenzo: "migliorare la guida turistica
linkando un pdf per attrazione da te generato ad hoc ... con bottone di
torna all'itinerario alla parte giusta", e sua scelta esplicita fra le
opzioni proposte: "PDF separati, ospitati su Render"]

Perché questo file è tutto sulla sicurezza e quasi niente sulle funzionalità
-----------------------------------------------------------------------------
Che `store()` salvi un file e `resolve()` lo rilegga è la parte facile, e si
esaurisce in tre test. Tutto il resto di questo modulo esiste per una ragione
sola: da oggi il prodotto pubblica su internet, senza password, documenti che
contengono i dati di viaggio di una persona che ha pagato. La credenziale è
la URL stessa — un token casuale — e questo significa che ogni difetto qui
non è un difetto di comodità ma una fuga di dati.

I modi in cui una cosa così si rompe sono noti e sempre gli stessi:
  * il token confrontato con `==` (perde informazione sul tempo);
  * un `../` che scappa dalla cartella e legge mezzo filesystem;
  * la scadenza che non scade;
  * la risposta che dice "consegna inesistente" invece di "no", e così
    risponde alla domanda "questo codice è mai esistito?" a chiunque;
  * la rotta pubblica che finisce sotto l'autenticazione di Make (e allora
    il cliente non apre più niente) o, molto peggio, la rotta di
    manutenzione che ne esce.

Ognuno di questi ha il suo test qui sotto. Se uno fallisce, non è "un test
rotto": è un documento di un cliente che sta per diventare leggibile da
qualcun altro.
"""
import importlib
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from src import hosting


class _ConArchivio(unittest.TestCase):
    """Base comune: un archivio vero su disco, in una cartella temporanea,
    smontato alla fine. Niente mock: questo modulo parla col filesystem, e
    un test che finge il filesystem non direbbe niente sulla cosa che ci
    preoccupa."""

    BASE = "https://esempio-servizio.onrender.com"

    def setUp(self):
        self.radice = tempfile.mkdtemp(prefix="hosting-test-")
        self._ambiente_precedente = {
            k: os.environ.get(k)
            for k in ("PUBLIC_FILES_DIR", "PUBLIC_BASE_URL",
                      "PUBLIC_FILES_RETENTION_DAYS")
        }
        os.environ["PUBLIC_FILES_DIR"] = self.radice
        os.environ["PUBLIC_BASE_URL"] = self.BASE
        os.environ.pop("PUBLIC_FILES_RETENTION_DAYS", None)

    def tearDown(self):
        shutil.rmtree(self.radice, ignore_errors=True)
        for chiave, valore in self._ambiente_precedente.items():
            if valore is None:
                os.environ.pop(chiave, None)
            else:
                os.environ[chiave] = valore

    def _consegna(self, nome="itinerario", blob=b"%PDF-1.4 finto"):
        consegna = hosting.new_delivery_id()
        token = hosting.reserve(consegna)
        url = hosting.store(consegna, nome, blob)
        return consegna, token, url


# ---------------------------------------------------------------------------
# 1. Il giro normale
# ---------------------------------------------------------------------------
class TestQuelloCheDeveSemplicementeFunzionare(_ConArchivio):

    def test_un_file_salvato_si_rilegge_identico(self):
        blob = b"%PDF-1.4 contenuto di prova\x00\xff binario"
        consegna, token, url = self._consegna(blob=blob)
        letto = hosting.resolve(consegna, token, "itinerario.pdf")
        self.assertIsNotNone(letto)
        self.assertEqual(letto[0], blob)
        self.assertEqual(letto[1], "application/pdf")

    def test_la_url_ha_la_forma_promessa(self):
        consegna, token, url = self._consegna()
        self.assertEqual(url, f"{self.BASE}/f/{consegna}/{token}/itinerario.pdf")
        self.assertTrue(url.startswith("https://"))

    def test_la_url_si_puo_calcolare_prima_che_il_file_esista(self):
        """È il motivo per cui `reserve()` esiste separata da `store()`: la
        guida di un'attrazione deve stampare il bottone "torna
        all'itinerario" mentre l'itinerario non è ancora stato scritto."""
        consegna = hosting.new_delivery_id()
        token = hosting.reserve(consegna)
        prevista = hosting.public_url(consegna, token, "itinerario")
        effettiva = hosting.store(consegna, "itinerario", b"%PDF-1.4 x")
        self.assertEqual(prevista, effettiva)

    def test_riservare_due_volte_da_lo_stesso_token(self):
        consegna = hosting.new_delivery_id()
        self.assertEqual(hosting.reserve(consegna), hosting.reserve(consegna))

    def test_piu_file_nella_stessa_consegna_convivono(self):
        consegna = hosting.new_delivery_id()
        token = hosting.reserve(consegna)
        hosting.store(consegna, "itinerario", b"%PDF-1.4 principale")
        hosting.store(consegna, "guida-duomo", b"%PDF-1.4 duomo")
        self.assertEqual(hosting.resolve(consegna, token, "itinerario.pdf")[0],
                         b"%PDF-1.4 principale")
        self.assertEqual(hosting.resolve(consegna, token, "guida-duomo.pdf")[0],
                         b"%PDF-1.4 duomo")

    def test_lestensione_la_decide_il_tipo_non_il_chiamante(self):
        """Un chiamante non deve poter far comparire un `.html` nella URL:
        un HTML servito dal nostro dominio è una pagina che può eseguire
        codice nel contesto del nostro sito."""
        consegna = hosting.new_delivery_id()
        hosting.reserve(consegna)
        url = hosting.store(consegna, "foglio", b"xlsx finto",
                            content_type="application/vnd.openxmlformats-"
                                         "officedocument.spreadsheetml.sheet")
        self.assertIsNotNone(url)
        self.assertTrue(url.endswith(".xlsx"), url)

    def test_un_tipo_non_ammesso_non_entra(self):
        consegna = hosting.new_delivery_id()
        hosting.reserve(consegna)
        for tipo in ("text/html", "application/javascript", "image/svg+xml",
                     "application/octet-stream", "", None, 42):
            self.assertIsNone(
                hosting.store(consegna, "brutto", b"contenuto", content_type=tipo),
                f"tipo accettato e non doveva: {tipo!r}",
            )


# ---------------------------------------------------------------------------
# 2. Il token è la credenziale
# ---------------------------------------------------------------------------
class TestIlTokenEUnaCredenziale(_ConArchivio):

    def test_un_token_sbagliato_non_apre_niente(self):
        consegna, token, _ = self._consegna()
        finto = "A" * len(token)
        self.assertIsNone(hosting.resolve(consegna, finto, "itinerario.pdf"))

    def test_il_token_e_lungo_abbastanza_da_non_essere_indovinato(self):
        """128 bit di entropia è la soglia sotto la quale una URL a
        capacità smette di essere una credenziale e diventa un ostacolo."""
        _, token, _ = self._consegna()
        self.assertGreaterEqual(len(token), 22, f"token troppo corto: {len(token)}")

    def test_due_consegne_non_condividono_il_token(self):
        c1, t1, _ = self._consegna()
        c2, t2, _ = self._consegna()
        self.assertNotEqual(t1, t2)
        self.assertIsNone(hosting.resolve(c1, t2, "itinerario.pdf"))
        self.assertIsNone(hosting.resolve(c2, t1, "itinerario.pdf"))

    def test_il_confronto_del_token_e_a_tempo_costante(self):
        """Il controllo sta sul SORGENTE e non sul comportamento, perché la
        differenza di tempo fra `==` e `compare_digest` non è misurabile in
        modo affidabile dentro un test unitario. Qui si verifica che il
        modulo usi lo strumento giusto: è l'unica forma di controllo che
        non produce falsi verdi su una macchina scarica."""
        with open(hosting.__file__, encoding="utf-8") as f:
            sorgente = f.read()
        self.assertIn("compare_digest", sorgente)
        righe_sospette = [
            r.strip() for r in sorgente.splitlines()
            if "token" in r and "==" in r and not r.strip().startswith("#")
        ]
        self.assertEqual([], righe_sospette,
                         f"token confrontato con ==: {righe_sospette}")


# ---------------------------------------------------------------------------
# 3. Nessuna via d'uscita dalla cartella
# ---------------------------------------------------------------------------
class TestNonSiEsceDallaCartella(_ConArchivio):

    CATTIVI = [
        "../fuori", "..", ".", "../../etc/passwd", "/etc/passwd",
        "..%2ffuori", "..%252ffuori", "%2e%2e%2f", "....//fuori",
        "cartella/dentro", "cartella\\dentro", "file\x00.pdf",
        "a" * 500, "", "   ", "nome con spazi", "nome;rm -rf /",
        "café", "‮ftp.pdf", "_consegna", None, 42, [], {},
    ]

    def test_nessun_nome_cattivo_scrive_da_qualche_parte(self):
        consegna = hosting.new_delivery_id()
        hosting.reserve(consegna)
        for cattivo in self.CATTIVI:
            self.assertIsNone(
                hosting.store(consegna, cattivo, b"%PDF-1.4 x"),
                f"nome accettato e non doveva: {cattivo!r}",
            )

    def test_nessuna_consegna_cattiva_legge_da_qualche_parte(self):
        _, token, _ = self._consegna()
        for cattivo in self.CATTIVI:
            self.assertIsNone(hosting.resolve(cattivo, token, "itinerario.pdf"))
            self.assertIsNone(hosting.reserve(cattivo))

    def test_nessun_nome_cattivo_legge_da_qualche_parte(self):
        consegna, token, _ = self._consegna()
        for cattivo in self.CATTIVI:
            self.assertIsNone(hosting.resolve(consegna, token, cattivo))

    def test_niente_e_stato_scritto_fuori_dalla_radice(self):
        """La prova materiale: dopo aver bombardato l'archivio con ogni
        nome malformato, la cartella temporanea contiene solo le consegne
        legittime e il filesystem attorno è intatto."""
        consegna = hosting.new_delivery_id()
        hosting.reserve(consegna)
        for cattivo in self.CATTIVI:
            hosting.store(consegna, cattivo, b"%PDF-1.4 x")
        presenti = sorted(os.listdir(self.radice))
        self.assertEqual(presenti, [consegna], f"comparso altro: {presenti}")

    def test_un_file_vero_fuori_dalla_radice_resta_illeggibile(self):
        """Il controllo che conta davvero: si crea un file ACCANTO alla
        radice e si prova a raggiungerlo in tutti i modi. Se una sola
        combinazione lo restituisce, il prodotto legge il filesystem del
        server per conto di chiunque abbia una URL."""
        vicino = os.path.join(os.path.dirname(self.radice), "segreto-fuori.pdf")
        with open(vicino, "wb") as f:
            f.write(b"NON DEVE USCIRE")
        try:
            consegna, token, _ = self._consegna()
            tentativi = [
                (consegna, token, "../segreto-fuori.pdf"),
                ("..", token, "segreto-fuori.pdf"),
                (consegna, token, "..%2fsegreto-fuori.pdf"),
                ("../" + os.path.basename(self.radice), token, "segreto-fuori.pdf"),
                (consegna, "../" + token, "segreto-fuori.pdf"),
            ]
            for c, t, n in tentativi:
                esito = hosting.resolve(c, t, n)
                if esito is not None:
                    self.assertNotIn(b"NON DEVE USCIRE", esito[0],
                                     f"fuga dalla cartella con {(c, t, n)!r}")
                self.assertIsNone(esito, f"fuga dalla cartella con {(c, t, n)!r}")
        finally:
            os.unlink(vicino)


# ---------------------------------------------------------------------------
# 4. La scadenza scade
# ---------------------------------------------------------------------------
class TestLaScadenzaScadeDavvero(_ConArchivio):

    def _invecchia(self, consegna, giorni):
        """Riscrive la data di nascita nel manifesto. Si tocca il manifesto
        e non l'orologio perché è il manifesto la fonte di verità: un test
        che sposta l'orologio verificherebbe una cosa che in produzione non
        succede mai."""
        import json
        percorso = os.path.join(self.radice, consegna, "_consegna.json")
        with open(percorso, encoding="utf-8") as f:
            manifest = json.load(f)
        nascita = datetime.now(timezone.utc) - timedelta(days=giorni)
        manifest["creato"] = nascita.isoformat()
        with open(percorso, "w", encoding="utf-8") as f:
            json.dump(manifest, f)

    def test_una_consegna_scaduta_non_si_apre_piu(self):
        consegna, token, _ = self._consegna()
        self._invecchia(consegna, hosting.RETENTION_DEFAULT_DAYS + 1)
        self.assertIsNone(hosting.resolve(consegna, token, "itinerario.pdf"))

    def test_un_giorno_prima_della_scadenza_si_apre_ancora(self):
        """Il controllo di segno opposto: senza questo, una scadenza
        impostata a zero passerebbe il test qui sopra ed romperebbe ogni
        link il giorno stesso della consegna."""
        consegna, token, _ = self._consegna()
        self._invecchia(consegna, hosting.RETENTION_DEFAULT_DAYS - 1)
        self.assertIsNotNone(hosting.resolve(consegna, token, "itinerario.pdf"))

    def test_lo_spazzino_cancella_solo_le_scadute(self):
        viva, token_viva, _ = self._consegna()
        morta, _, _ = self._consegna()
        self._invecchia(morta, hosting.RETENTION_DEFAULT_DAYS + 5)
        self.assertEqual(hosting.sweep(), 1)
        self.assertFalse(os.path.exists(os.path.join(self.radice, morta)))
        self.assertIsNotNone(hosting.resolve(viva, token_viva, "itinerario.pdf"))

    def test_lo_spazzino_non_tocca_roba_che_non_e_nostra(self):
        """Su un disco Render appena montato c'è `lost+found`. Uno spazzino
        che cancella tutto quello che trova è un incidente che aspetta."""
        estranea = os.path.join(self.radice, "lost+found")
        os.makedirs(estranea, exist_ok=True)
        with open(os.path.join(estranea, "roba"), "wb") as f:
            f.write(b"x")
        hosting.sweep()
        self.assertTrue(os.path.exists(estranea))

    def test_rigenerare_un_viaggio_scaduto_continua_a_funzionare(self):
        """Un affinamento o una correzione su un viaggio vecchio non deve
        fallire: la consegna rinasce con un token nuovo. I vecchi link
        muoiono, ma erano già scaduti."""
        consegna, vecchio, _ = self._consegna()
        self._invecchia(consegna, hosting.RETENTION_DEFAULT_DAYS + 10)
        nuovo = hosting.reserve(consegna)
        self.assertIsNotNone(nuovo)
        self.assertNotEqual(nuovo, vecchio)
        hosting.store(consegna, "itinerario", b"%PDF-1.4 rifatto")
        self.assertIsNotNone(hosting.resolve(consegna, nuovo, "itinerario.pdf"))
        self.assertIsNone(hosting.resolve(consegna, vecchio, "itinerario.pdf"))


# ---------------------------------------------------------------------------
# 5. Il no è sempre lo stesso no
# ---------------------------------------------------------------------------
class TestIlNoNonRaccontaNiente(_ConArchivio):

    def test_ogni_fallimento_ha_la_stessa_faccia(self):
        """Se "consegna inesistente" e "token sbagliato" dessero risposte
        diverse, chiunque potrebbe chiedere al servizio "questo codice è
        mai esistito?" e ottenere risposta. È esattamente l'informazione
        che una URL a capacità non deve dare."""
        consegna, token, _ = self._consegna()
        esiti = {
            "consegna che non esiste": hosting.resolve("aaaaaaaaaaaaaaaa", token, "itinerario.pdf"),
            "token sbagliato": hosting.resolve(consegna, "B" * len(token), "itinerario.pdf"),
            "file che non esiste": hosting.resolve(consegna, token, "inesistente.pdf"),
            "nome malformato": hosting.resolve(consegna, token, "../x"),
        }
        self.assertEqual({None}, set(esiti.values()), esiti)


# ---------------------------------------------------------------------------
# 6. I tetti di spazio
# ---------------------------------------------------------------------------
class TestIlDiscoENonFinito(_ConArchivio):

    def test_oltre_il_tetto_di_byte_si_rifiuta(self):
        consegna = hosting.new_delivery_id()
        hosting.reserve(consegna)
        grosso = b"x" * (hosting.MAX_BYTES_PER_CONSEGNA + 1)
        self.assertIsNone(hosting.store(consegna, "enorme", grosso))

    def test_oltre_il_tetto_di_file_si_rifiuta(self):
        consegna = hosting.new_delivery_id()
        hosting.reserve(consegna)
        for i in range(hosting.MAX_FILE_PER_CONSEGNA):
            self.assertIsNotNone(hosting.store(consegna, f"g{i}", b"%PDF-1.4 x"),
                                 f"rifiutato troppo presto al file {i}")
        self.assertIsNone(hosting.store(consegna, "uno-di-troppo", b"%PDF-1.4 x"))

    def test_un_blob_vuoto_o_non_di_byte_non_entra(self):
        consegna = hosting.new_delivery_id()
        hosting.reserve(consegna)
        for brutto in (b"", "", None, 42, [], {"a": 1}):
            self.assertIsNone(hosting.store(consegna, "vuoto", brutto),
                              f"accettato: {brutto!r}")


# ---------------------------------------------------------------------------
# 7. Non configurato = silenzio, mai una URL finta
# ---------------------------------------------------------------------------
class TestSenzaConfigurazioneNonSiPromette(unittest.TestCase):
    """È la stessa disciplina del riquadro della valigia e del capitolo
    della recensione: un collegamento che non apre niente è peggio di
    nessun collegamento, perché il cliente lo scopre dopo aver cliccato."""

    def setUp(self):
        self._prima = {k: os.environ.get(k) for k in
                       ("PUBLIC_FILES_DIR", "PUBLIC_BASE_URL")}

    def tearDown(self):
        for k, v in self._prima.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def _spegni(self, **variabili):
        for chiave in ("PUBLIC_FILES_DIR", "PUBLIC_BASE_URL"):
            os.environ.pop(chiave, None)
        for chiave, valore in variabili.items():
            os.environ[chiave] = valore

    def test_senza_niente_configurato_tutto_tace(self):
        self._spegni()
        self.assertFalse(hosting.is_configured())
        self.assertIsNone(hosting.store("abc", "itinerario", b"%PDF-1.4 x"))
        self.assertIsNone(hosting.reserve("abc"))
        self.assertIsNone(hosting.public_url("abc", "t" * 30, "itinerario"))
        self.assertEqual(hosting.sweep(), 0)

    def test_una_base_url_non_https_vale_come_non_configurata(self):
        """Un indirizzo non cifrato dentro un documento che il cliente apre
        sul telefono è un difetto di sicurezza, non di stile — ed è già
        vietato da un controllo sul PDF (`assertNotIn("http://")`)."""
        with tempfile.TemporaryDirectory() as radice:
            for cattiva in ("http://esempio.it", "esempio.it", "//esempio.it",
                            "https://", "https://localhost", "ftp://esempio.it",
                            "", "   ", "https://example.com"):
                self._spegni(PUBLIC_FILES_DIR=radice, PUBLIC_BASE_URL=cattiva)
                self.assertFalse(hosting.is_configured(),
                                 f"accettata una base url cattiva: {cattiva!r}")
                self.assertIsNone(hosting.store("abc", "itinerario", b"%PDF-1.4 x"))

    def test_la_barra_finale_non_produce_una_doppia_barra(self):
        with tempfile.TemporaryDirectory() as radice:
            self._spegni(PUBLIC_FILES_DIR=radice,
                         PUBLIC_BASE_URL="https://esempio.onrender.com/")
            consegna = hosting.new_delivery_id()
            token = hosting.reserve(consegna)
            url = hosting.store(consegna, "itinerario", b"%PDF-1.4 x")
            self.assertIsNotNone(url)
            self.assertNotIn("//f/", url)
            self.assertEqual(url.count("://"), 1)


# ---------------------------------------------------------------------------
# 8. Le due rotte, e il verso giusto dell'autenticazione
# ---------------------------------------------------------------------------
class TestLeRotteDelServizio(_ConArchivio):
    """In `service.py` l'autenticazione è per-rotta: `_check_auth()` viene
    chiamata DENTRO ogni handler, non da un `before_request`. Significa che
    una rotta nuova nasce pubblica, e che l'errore possibile è in tutti e
    due i versi:

      * mettere l'autenticazione sulla rotta di lettura → il cliente non
        apre più niente, e l'unico modo di rimediare sarebbe scrivere la
        chiave del servizio dentro un PDF che gira per posta;
      * dimenticarla sulla rotta di manutenzione → chiunque può cancellare
        i documenti di tutti.

    Entrambi i versi hanno il loro test. È il tipo di cosa che si rompe in
    silenzio durante un refactoring e che nessuno nota finché non scrive
    un cliente.
    """

    def setUp(self):
        super().setUp()
        self._chiave_prima = os.environ.get("SERVICE_API_KEY")
        os.environ["SERVICE_API_KEY"] = "chiave-di-prova-solo-per-i-test"
        import service
        self.service = service
        service.app.config["TESTING"] = True
        self.client = service.app.test_client()

    def tearDown(self):
        if self._chiave_prima is None:
            os.environ.pop("SERVICE_API_KEY", None)
        else:
            os.environ["SERVICE_API_KEY"] = self._chiave_prima
        super().tearDown()

    def test_il_cliente_apre_il_documento_senza_nessuna_chiave(self):
        consegna, token, _ = self._consegna(blob=b"%PDF-1.4 vero")
        r = self.client.get(f"/f/{consegna}/{token}/itinerario.pdf")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data, b"%PDF-1.4 vero")
        self.assertEqual(r.headers["Content-Type"], "application/pdf")

    def test_il_documento_non_finisce_nei_motori_di_ricerca(self):
        consegna, token, _ = self._consegna()
        r = self.client.get(f"/f/{consegna}/{token}/itinerario.pdf")
        self.assertIn("noindex", r.headers.get("X-Robots-Tag", ""))
        self.assertIn("private", r.headers.get("Cache-Control", ""))
        self.assertEqual(r.headers.get("X-Content-Type-Options"), "nosniff")

    def test_ogni_fallimento_e_lo_stesso_404(self):
        consegna, token, _ = self._consegna()
        risposte = [
            self.client.get(f"/f/aaaaaaaaaaaa/{token}/itinerario.pdf"),
            self.client.get(f"/f/{consegna}/{'B' * len(token)}/itinerario.pdf"),
            self.client.get(f"/f/{consegna}/{token}/inesistente.pdf"),
        ]
        for r in risposte:
            self.assertEqual(r.status_code, 404)
        corpi = {r.get_data() for r in risposte}
        self.assertEqual(len(corpi), 1, f"404 distinguibili fra loro: {corpi}")

    def test_la_rotta_di_manutenzione_vuole_la_chiave(self):
        r = self.client.post("/v1/manutenzione/pulizia")
        self.assertEqual(r.status_code, 401)
        r = self.client.post("/v1/manutenzione/pulizia",
                             headers={"X-Service-Key": "chiave-sbagliata"})
        self.assertEqual(r.status_code, 401)

    def test_la_rotta_di_manutenzione_funziona_con_la_chiave(self):
        r = self.client.post(
            "/v1/manutenzione/pulizia",
            headers={"X-Service-Key": "chiave-di-prova-solo-per-i-test"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("consegne_cancellate", r.get_json())

    def test_nessun_percorso_del_server_trapela_nella_risposta(self):
        """Un 404 che stampa il percorso su disco racconta com'è fatto il
        server a chiunque provi una URL a caso."""
        r = self.client.get("/f/aaaaaaaaaaaa/" + "T" * 40 + "/x.pdf")
        corpo = r.get_data(as_text=True)
        self.assertNotIn(self.radice, corpo)
        self.assertNotIn("/opt/", corpo)
        self.assertNotIn("Traceback", corpo)


class TestIlDeployDichiaraQuelloCheServe(unittest.TestCase):
    """Il codice funziona solo se Render gli dà un disco vero.

    Questa classe non prova il codice: prova il file di configurazione. È
    l'unico posto dove un errore non si vede provando il programma — il
    programma qui funziona benissimo, è la macchina su cui gira che riparte
    ogni volta con la cartella vuota, e i link stampati sui PDF già spediti
    diventano 404 giorni dopo, quando ormai non si possono più correggere.
    """

    @classmethod
    def setUpClass(cls):
        import yaml  # PyYAML arriva con le dipendenze del progetto
        radice = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(radice, "render.yaml"), encoding="utf-8") as f:
            cls.servizio = yaml.safe_load(f)["services"][0]
        with open(os.path.join(radice, "DEPLOY.md"), encoding="utf-8") as f:
            cls.deploy = f.read()

    def _variabili(self):
        return {v["key"]: v for v in self.servizio.get("envVars") or []}

    def test_le_tre_variabili_dellarchivio_sono_dichiarate(self):
        chiavi = self._variabili()
        for nome in ("PUBLIC_FILES_DIR", "PUBLIC_BASE_URL",
                     "PUBLIC_FILES_RETENTION_DAYS"):
            self.assertIn(nome, chiavi, f"{nome} non è dichiarata in render.yaml")

    def test_il_disco_esiste_ed_e_montato_dove_il_codice_scrive(self):
        disco = self.servizio.get("disk")
        self.assertIsNotNone(
            disco, "senza disco persistente i documenti spariscono al riavvio")
        percorso = self._variabili()["PUBLIC_FILES_DIR"].get("value")
        self.assertEqual(
            disco.get("mountPath"), percorso,
            "il disco è montato in un punto diverso da dove il codice scrive: "
            "il servizio parte, non dà errore, e perde tutto a ogni riavvio")

    def test_il_disco_richiede_un_piano_a_pagamento(self):
        """Su Render il disco non esiste sul piano gratuito. Se qualcuno
        riporta il servizio su `free` per risparmiare, questo test glielo
        dice subito invece di farglielo scoprire dai clienti."""
        self.assertNotEqual(self.servizio.get("plan"), "free")

    def test_il_deploy_spiega_a_lorenzo_cosa_deve_fare_a_mano(self):
        for pezzo in ("PUBLIC_BASE_URL", "/var/dati/pubblici",
                      "/v1/manutenzione/pulizia"):
            self.assertIn(pezzo, self.deploy)

    def test_il_deploy_non_millanta_conformita(self):
        """Il compromesso (link non indovinabile ma non autenticato) va
        dichiarato, non venduto come risolto: non siamo avvocati."""
        self.assertIn("avvocato", self.deploy.lower())
        brutte = ("conforme al gdpr", "gdpr compliant", "a norma di gdpr",
                  "pienamente conforme")
        basso = self.deploy.lower()
        for frase in brutte:
            self.assertNotIn(frase, basso)


if __name__ == "__main__":
    unittest.main()
