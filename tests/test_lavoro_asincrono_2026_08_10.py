"""La generazione presa in carico, non più attesa — task del 2026-08-10.

PERCHÉ QUESTO FILE ESISTE

Otto esecuzioni di produzione morte di fila, tutte allo stesso modo:
`ModuleTimeoutError` sul modulo HTTP che chiama `/v1/itinerary`, durata
**300,3 / 300,4 / 300,5 secondi**. È il tetto rigido di 300 secondi del modulo
HTTP di Make, che non si alza su nessun piano a pagamento.

Ogni fallimento è costato davvero: Make chiude la connessione, ma il server
continua a lavorare fino in fondo. Otto generazioni complete pagate, zero
documenti consegnati, e il cliente che aveva pagato non ha ricevuto niente.

La correzione non tocca né il prompt né il modello: si smette di tenere il
chiamante appeso. Chi chiede riceve subito un numero d'ordine e ripassa a
ritirare.

## Cosa proteggono davvero questi controlli

Il modo in cui questa cosa si romperebbe in silenzio è uno solo, ed è sottile:
**che la strada nuova e quella di sempre comincino a comportarsi in modo
diverso**. Basta che qualcuno, un domani, aggiunga una validazione alla rotta
sincrona e si dimentichi di quella presa in carico, e il prodotto avrà due
comportamenti — con il cliente a fare da collaudatore. Per questo la maggior
parte dei controlli qui sotto non guarda la funzione nuova: guarda che le due
strade restino **la stessa strada**.
"""

import json
import os
import tempfile
import unittest
from unittest import mock


class _BaseServizio(unittest.TestCase):
    """Ogni prova ha la sua cartella dei lavori, buttata alla fine."""

    def setUp(self):
        os.environ["SERVICE_API_KEY"] = "chiave-di-prova-non-vera"
        # `ignore_cleanup_errors` non e' pigrizia: queste prove lasciano
        # dietro filoni di lavoro veri che continuano a scrivere il loro
        # esito. Ogni tanto uno di loro riscriveva il file un istante dopo
        # la pulizia e la cartella risultava «non vuota»: la prova diventava
        # rossa a caso, senza che il prodotto avesse niente che non va. Un
        # controllo che fallisce a caso e' un controllo che, dopo la terza
        # volta, nessuno guarda piu'.
        self._cartella = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        os.environ["LAVORI_DIR"] = self._cartella.name
        import service as _servizio

        self.servizio = _servizio
        self.client = _servizio.app.test_client()

    def tearDown(self):
        self._cartella.cleanup()
        os.environ.pop("LAVORI_DIR", None)

    @property
    def intestazioni(self):
        return {"X-Service-Key": os.environ["SERVICE_API_KEY"]}

    def _corpo_valido(self):
        return {"mode": "mock", "scenario_key": "happy_path", "trip": {
            "email": "cliente@esempio.it", "scopo": "Relax",
            "destinazione": "Siena", "arrivo": "2026-09-12",
            "partenza": "2026-09-14", "budget": 500, "note": "",
        }}


class TestSiRispondeSubito(_BaseServizio):
    """Il punto di tutto: la risposta non deve dipendere dalla generazione."""

    def test_la_presa_in_carico_non_aspetta_la_generazione(self):
        """Il controllo che descrive il guasto — e che ha dovuto essere
        riscritto.

        [SCRITTO DUE VOLTE, 2026-08-10] La prima versione fingeva una
        generazione che solleva un'eccezione e verificava che la risposta
        fosse comunque 202. Messa alla prova rendendo la rotta di nuovo
        SINCRONA, restava verde: la rete di sicurezza attorno al lavoro
        cattura l'eccezione e la risposta esce 202 in tutti e due i casi.
        Un controllo sull'asincronia che non sapeva distinguere il sincrono
        dall'asincrono.

        L'unica cosa che distingue davvero le due versioni è il TEMPO. Qui la
        generazione finta resta bloccata tre secondi: se la rotta aspettasse,
        la risposta arriverebbe dopo tre secondi invece che subito.
        """
        import threading
        import time

        libera = threading.Event()

        def _lentissima(_body):
            libera.wait(10)
            return {"itinerary": "tardi"}, 200

        with mock.patch.object(self.servizio, "_esegui_itinerario",
                               side_effect=_lentissima):
            inizio = time.monotonic()
            risposta = self.client.post("/v1/itinerary/avvia",
                                        json=self._corpo_valido(),
                                        headers=self.intestazioni)
            trascorso = time.monotonic() - inizio
            libera.set()

        self.assertEqual(risposta.status_code, 202)
        self.assertIn("job_id", risposta.get_json())
        self.assertLess(
            trascorso, 1.0,
            f"la risposta ha impiegato {trascorso:.1f}s: la rotta sta ancora "
            "aspettando la generazione, ed è esattamente il difetto che ha "
            "fatto morire otto esecuzioni di produzione a 300 secondi",
        )

    def test_il_numero_d_ordine_serve_a_ritirare(self):
        with mock.patch.object(self.servizio, "_esegui_itinerario",
                               return_value=({"itinerary": {"giorni": 2}}, 200)):
            avvio = self.client.post("/v1/itinerary/avvia",
                                     json=self._corpo_valido(),
                                     headers=self.intestazioni)
            numero = avvio.get_json()["job_id"]
            self._attendi(numero)
            ritiro = self.client.get(f"/v1/itinerary/esito/{numero}",
                                     headers=self.intestazioni)
        self.assertEqual(ritiro.status_code, 200)
        self.assertEqual(ritiro.get_json()["itinerary"], {"giorni": 2})

    def _attendi(self, numero, tentativi=100):
        import time

        from src import lavori

        for _ in range(tentativi):
            dati = lavori.leggi(numero)
            if dati and dati.get("stato") != "in_corso":
                return dati
            time.sleep(0.02)
        self.fail("il lavoro non è mai finito")

    def test_finche_non_e_pronto_si_risponde_202_e_non_200(self):
        # Se rispondesse 200 con un corpo vuoto, Make proseguirebbe verso la
        # stampa del PDF con un itinerario inesistente, e il cliente
        # riceverebbe un documento vuoto invece di niente.
        from src import lavori

        numero = lavori.nuovo()
        risposta = self.client.get(f"/v1/itinerary/esito/{numero}",
                                   headers=self.intestazioni)
        self.assertEqual(risposta.status_code, 202)
        self.assertEqual(risposta.get_json()["stato"], "in_corso")


class TestLeDueStradeSonoLaStessaStrada(_BaseServizio):
    """Il difetto che verrebbe dopo: due comportamenti invece di uno."""

    def test_la_rotta_di_sempre_usa_la_stessa_funzione(self):
        # Se un domani `create_itinerary` tornasse a contenere la sua logica,
        # ogni correzione andrebbe fatta due volte — e la seconda volta si
        # dimentica.
        with mock.patch.object(self.servizio, "_esegui_itinerario",
                               return_value=({"segno": "unico"}, 200)) as usata:
            risposta = self.client.post("/v1/itinerary",
                                        json=self._corpo_valido(),
                                        headers=self.intestazioni)
        usata.assert_called_once()
        self.assertEqual(risposta.get_json()["segno"], "unico")

    def test_un_errore_del_cliente_esce_uguale_dalle_due_strade(self):
        """Un `trip` sbagliato deve dare lo stesso 400, in tutti e due i modi.

        È la promessa che rende la strada nuova sostituibile a quella vecchia:
        se il preso-in-carico inghiottisse gli errori, un wiring sbagliato di
        Make sembrerebbe funzionare fino al cliente.
        """
        storto = {"mode": "mock", "trip": {"destinazione": "Siena"}}

        sincrona = self.client.post("/v1/itinerary", json=storto,
                                    headers=self.intestazioni)
        avvio = self.client.post("/v1/itinerary/avvia", json=storto,
                                 headers=self.intestazioni)
        numero = avvio.get_json()["job_id"]
        TestSiRispondeSubito._attendi(self, numero)
        ritiro = self.client.get(f"/v1/itinerary/esito/{numero}",
                                 headers=self.intestazioni)

        self.assertEqual(sincrona.status_code, 400)
        self.assertEqual(ritiro.status_code, 400)
        self.assertEqual(sincrona.get_json()["error"], ritiro.get_json()["error"])

    def test_anche_un_guasto_del_server_esce_uguale(self):
        with mock.patch.object(self.servizio, "_esegui_itinerario",
                               side_effect=RuntimeError("il fornitore è caduto")):
            avvio = self.client.post("/v1/itinerary/avvia",
                                     json=self._corpo_valido(),
                                     headers=self.intestazioni)
            numero = avvio.get_json()["job_id"]
            TestSiRispondeSubito._attendi(self, numero)
            ritiro = self.client.get(f"/v1/itinerary/esito/{numero}",
                                     headers=self.intestazioni)
        self.assertEqual(ritiro.status_code, 500)
        self.assertIn("RuntimeError", ritiro.get_json()["error"])


class TestNessunoRitiraLaRobaDiUnAltro(_BaseServizio):
    """Le rotte nuove nascono pubbliche: qui si verifica che non lo siano."""

    def test_avviare_senza_chiave_non_si_puo(self):
        # In questo servizio l'autenticazione NON è globale: si chiama dentro
        # ogni funzione. Una rotta nuova che se ne dimentica è un rubinetto
        # aperto sulla strada, e ogni chiamata spende soldi veri.
        risposta = self.client.post("/v1/itinerary/avvia",
                                    json=self._corpo_valido())
        self.assertEqual(risposta.status_code, 401)

    def test_ritirare_senza_chiave_non_si_puo(self):
        risposta = self.client.get("/v1/itinerary/esito/qualunquecosa123")
        self.assertEqual(risposta.status_code, 401)

    def test_un_numero_d_ordine_inventato_non_dice_niente(self):
        risposta = self.client.get("/v1/itinerary/esito/inventato123456",
                                   headers=self.intestazioni)
        self.assertEqual(risposta.status_code, 404)


class TestIlNumeroDOrdineNonApreAltriFile(_BaseServizio):
    """[SICUREZZA] Il numero finisce dentro un nome di file.

    Senza filtro, un numero come `../../etc/passwd` farebbe leggere al
    servizio un file qualunque del disco. È la vulnerabilità più banale che
    esista e anche una delle più frequenti.
    """

    def test_i_percorsi_travestiti_da_numero_vengono_rifiutati(self):
        from src import lavori

        for cattivo in ["../segreto", "..%2Fsegreto", "a/b", "", "x",
                        "." * 300, "con spazio", "punto.punto"]:
            with self.subTest(cattivo=cattivo):
                self.assertIsNone(lavori._file(cattivo))
                self.assertIsNone(lavori.leggi(cattivo))

    def test_il_numero_generato_e_sempre_accettabile(self):
        from src import lavori

        for _ in range(50):
            numero = lavori.nuovo()
            self.assertIsNotNone(lavori._file(numero))
            self.assertRegex(numero, r"^[A-Za-z0-9_-]{8,64}$")

    def test_due_lavori_non_hanno_mai_lo_stesso_numero(self):
        from src import lavori

        numeri = {lavori.nuovo() for _ in range(200)}
        self.assertEqual(len(numeri), 200)


class TestUnLavoroMortoNonRestaInCorsoPerSempre(_BaseServizio):
    """Se il processo cade, Make ripasserebbe all'infinito."""

    def test_dopo_la_scadenza_diventa_un_errore_leggibile(self):
        import time

        from src import lavori

        numero = lavori.nuovo()
        percorso = lavori._file(numero)
        dati = json.loads(percorso.read_text())
        dati["creato"] = time.time() - lavori.SCADENZA_SECONDI - 10
        percorso.write_text(json.dumps(dati))

        letto = lavori.leggi(numero)
        self.assertEqual(letto["stato"], "errore")
        self.assertEqual(letto["codice"], 504)

    def test_la_scadenza_e_piu_lunga_della_generazione_piu_lenta_mai_vista(self):
        # La più lenta misurata è stata 356 secondi. Una scadenza più corta
        # dichiarerebbe morti dei lavori ancora vivi.
        from src import lavori

        self.assertGreater(lavori.SCADENZA_SECONDI, 356 * 2)

    def test_i_lavori_vecchi_si_buttano(self):
        import time

        from src import lavori

        numero = lavori.nuovo()
        percorso = lavori._file(numero)
        vecchio = time.time() - lavori.ETA_MASSIMA_SECONDI - 10
        os.utime(percorso, (vecchio, vecchio))
        self.assertEqual(lavori.pulisci(), 1)
        self.assertIsNone(lavori.leggi(numero))


class TestIlMagazzinoSopravviveAiProcessiSeparati(_BaseServizio):
    """`gunicorn --workers 2`: chi ritira può non essere chi ha preso in carico."""

    def test_l_esito_si_legge_da_un_processo_che_non_ha_generato_niente(self):
        # Si simula l'altro processo ricaricando il modulo da zero: se lo
        # stato vivesse in memoria, qui non ci sarebbe più niente.
        import importlib

        from src import lavori

        numero = lavori.nuovo()
        lavori.salva_esito(numero, {"itinerary": "fatto"}, 200)

        altro = importlib.reload(lavori)
        letto = altro.leggi(numero)
        self.assertEqual(letto["corpo"]["itinerary"], "fatto")

    def test_una_scrittura_a_meta_non_si_puo_leggere(self):
        # La scrittura è atomica: prima un temporaneo, poi lo spostamento.
        # Senza, chi ritira nel millisecondo sbagliato legge un JSON tagliato.
        import inspect

        from src import lavori

        sorgente = inspect.getsource(lavori._scrivi)
        self.assertIn("os.replace", sorgente)




class TestChiRitiraNonDeveIndovinareIlTempo(_BaseServizio):
    """[REGRESSIONE 2026-08-10 — da un guasto vero, in produzione, costato
    otto minuti di generazione pagata e buttata.]

    Il primo giro faceva aspettare Make a tempo fisso: 300 secondi di sonno,
    una domanda, altri 180 di sonno, l'ultima domanda. Sembrava prudente.
    Non lo era, e sbagliava in tutti e due i versi:

      - **se la generazione finiva prima**, ogni cliente pagava 480 secondi
        di attesa inutile;
      - **se finiva dopo**, l'ultima domanda arrivava a vuoto, il documento
        non veniva mai costruito, e la generazione — gia' fatta e gia'
        pagata — finiva nel cestino.

    Un'attesa indovinata e' la cosa che non puo' funzionare: chi chiede e'
    l'unico che non sa quanto ci vuole. Adesso la domanda resta aperta e la
    risposta arriva quando e' pronta.
    """

    def test_l_attesa_finisce_nell_istante_in_cui_il_lavoro_e_pronto(self):
        """Il punto di tutto: non un secondo prima, non un secondo dopo.

        Si chiede di aspettare fino a dieci secondi un lavoro che diventa
        pronto dopo mezzo. Se la risposta arrivasse dopo dieci secondi
        vorrebbe dire che stiamo ancora dormendo a tempo fisso.
        """
        import threading
        import time

        from src import lavori

        identificativo = lavori.nuovo()

        def _finisci_fra_mezzo_secondo():
            time.sleep(0.5)
            lavori.salva_esito(identificativo, {"ok": True}, 200)

        threading.Thread(target=_finisci_fra_mezzo_secondo, daemon=True).start()
        inizio = time.monotonic()
        dati = lavori.attendi(identificativo, 10)
        passato = time.monotonic() - inizio

        self.assertEqual(dati.get("stato"), "pronto")
        self.assertLess(
            passato, 4.0,
            f"la risposta ha impiegato {passato:.1f}s per un lavoro pronto "
            "dopo 0,5s: si sta ancora aspettando a tempo fisso",
        )

    def test_se_non_e_pronto_si_torna_indietro_prima_del_tetto_di_make(self):
        # Una risposta che arriva a 300,1 secondi e' una risposta persa: il
        # modulo HTTP di Make ha gia' staccato. Il margine e' la differenza
        # fra aspettare il massimo possibile e aspettare invano.
        from src import lavori

        self.assertLess(lavori.ATTESA_MASSIMA_SECONDI, 300)
        self.assertGreater(lavori.ATTESA_MASSIMA_SECONDI, 240)

    def test_nessuno_puo_tenere_il_servizio_appeso_dall_indirizzo(self):
        """`?attendi=` arriva da fuori: deve reggere qualunque cosa.

        Senza il tetto, un `?attendi=99999999` occuperebbe per giorni uno
        degli otto filoni di lavoro del servizio. Con due o tre chiamate cosi'
        il prodotto sarebbe spento senza che nessuno abbia fatto niente di
        illegale.
        """
        from src import lavori

        for valore in ("99999999", 99999999, "1e9", float("inf")):
            with self.subTest(valore=valore):
                self.assertLessEqual(lavori._secondi_validi(valore),
                                     lavori.ATTESA_MASSIMA_SECONDI)

    def test_un_attesa_scritta_male_non_fa_cadere_niente(self):
        from src import lavori

        for valore in (None, "", "subito", "-5", float("nan"), {}, []):
            with self.subTest(valore=valore):
                self.assertEqual(lavori._secondi_validi(valore), 0.0)

    def test_senza_attendi_il_comportamento_e_quello_di_sempre(self):
        # La rotta esisteva gia' e qualcuno potrebbe usarla senza il
        # parametro: deve rispondere subito, come prima, senza aspettare.
        import time

        from src import lavori

        identificativo = lavori.nuovo()
        inizio = time.monotonic()
        risposta = self.client.get(f"/v1/itinerary/esito/{identificativo}",
                                   headers=self.intestazioni)
        passato = time.monotonic() - inizio
        self.assertEqual(risposta.status_code, 202)
        self.assertLess(passato, 2.0)

    def test_dall_indirizzo_si_puo_chiedere_di_aspettare(self):
        """Il giro completo, dalla rotta: si chiede, si aspetta, si riceve."""
        import threading
        import time

        from src import lavori

        identificativo = lavori.nuovo()

        def _finisci_fra_poco():
            time.sleep(0.5)
            lavori.salva_esito(identificativo, {"itinerary": {"days": []}}, 200)

        threading.Thread(target=_finisci_fra_poco, daemon=True).start()
        inizio = time.monotonic()
        risposta = self.client.get(
            f"/v1/itinerary/esito/{identificativo}?attendi=10",
            headers=self.intestazioni)
        passato = time.monotonic() - inizio

        self.assertEqual(risposta.status_code, 200)
        self.assertIn("itinerary", risposta.get_json())
        self.assertLess(passato, 4.0, "l'attesa non si e' interrotta da sola")

    def test_un_lavoro_gia_pronto_torna_indietro_immediatamente(self):
        # Le domande sono piu' d'una in fila: la seconda e la terza trovano
        # il lavoro gia' fatto e non devono aggiungere un solo secondo.
        import time

        from src import lavori

        identificativo = lavori.nuovo()
        lavori.salva_esito(identificativo, {"ok": True}, 200)
        inizio = time.monotonic()
        lavori.attendi(identificativo, 30)
        self.assertLess(time.monotonic() - inizio, 1.0)

    def test_un_numero_inventato_non_tiene_nessuno_in_attesa(self):
        # Aspettare 290 secondi un lavoro che non esiste sarebbe il modo piu'
        # sciocco di regalare il servizio a chi lo chiama a caso.
        import time

        from src import lavori

        inizio = time.monotonic()
        self.assertIsNone(lavori.attendi("numero-inventato-1234", 30))
        self.assertLess(time.monotonic() - inizio, 1.0)


class TestAncheIlFascicoloSiPuoPrendereInCarico(_BaseServizio):
    """[AGGIUNTO 2026-08-10] La seconda fase ha lo stesso tetto della prima.

    Il tetto dei 300 secondi del modulo HTTP di Make vale per OGNI chiamata,
    non solo per la prima. La costruzione del fascicolo — cinque guide
    generate dal modello, le fotografie scaricate, sei documenti stampati e
    cuciti insieme — e' la fase piu' lenta delle due. Aspettare di vederla
    morire in produzione, sapendo gia' fare il conto, sarebbe stato un
    difetto scelto invece che subito.
    """

    def test_la_rotta_di_sempre_e_quella_presa_in_carico_fanno_lo_stesso_lavoro(self):
        """La cosa che conta davvero: una sola implementazione.

        Se il fascicolo venisse costruito da due funzioni diverse, fra sei
        mesi il documento comprato dal cliente sarebbe diverso da quello
        provato in prova, e nessuno saprebbe dire da quando.
        """
        import inspect

        sorgente = inspect.getsource(self.servizio.generate_pdf)
        self.assertIn("_esegui_pdf", sorgente,
                      "la rotta di sempre non usa piu' la funzione condivisa")
        sorgente_avvio = inspect.getsource(self.servizio.avvia_pdf)
        self.assertIn("_esegui_pdf", sorgente_avvio)

    def test_la_presa_in_carico_del_fascicolo_risponde_subito(self):
        """Il controllo che descrive il guasto: si misura il TEMPO.

        Un controllo che guarda solo il codice 202 resterebbe verde anche se
        qualcuno rimettesse la costruzione dentro la risposta — che e'
        esattamente il guasto da impedire.
        """
        import time

        def _lentissimo(body):
            time.sleep(10)
            return {"pdf_base64": "x"}, 200

        with mock.patch.object(self.servizio, "_esegui_pdf", _lentissimo):
            inizio = time.monotonic()
            risposta = self.client.post("/v1/pdf/avvia", json={"trip": {}},
                                        headers=self.intestazioni)
            passato = time.monotonic() - inizio

        self.assertEqual(risposta.status_code, 202)
        self.assertLess(passato, 3.0,
                        f"la risposta ha impiegato {passato:.1f}s: la "
                        "costruzione e' ancora dentro la risposta")

    def test_il_fascicolo_si_ritira_con_lo_stesso_numero(self):
        import time

        with mock.patch.object(self.servizio, "_esegui_pdf",
                               lambda body: ({"pdf_base64": "eccolo"}, 200)):
            avvio = self.client.post("/v1/pdf/avvia", json={"trip": {}},
                                     headers=self.intestazioni)
            numero = avvio.get_json()["job_id"]
            for _ in range(50):
                ritiro = self.client.get(f"/v1/pdf/esito/{numero}",
                                         headers=self.intestazioni)
                if ritiro.status_code != 202:
                    break
                time.sleep(0.1)

        self.assertEqual(ritiro.status_code, 200)
        self.assertEqual(ritiro.get_json().get("pdf_base64"), "eccolo")

    def test_un_body_che_non_e_un_oggetto_non_produce_un_numero_a_vuoto(self):
        risposta = self.client.post("/v1/pdf/avvia", data="non sono JSON",
                                    content_type="application/json",
                                    headers=self.intestazioni)
        self.assertEqual(risposta.status_code, 400)

    def test_prendere_in_carico_un_fascicolo_senza_chiave_non_si_puo(self):
        risposta = self.client.post("/v1/pdf/avvia", json={"trip": {}})
        self.assertEqual(risposta.status_code, 401)


class TestLIndirizzoDiRitiroEsisteDavvero(_BaseServizio):
    """[REGRESSIONE 2026-08-10, difetto trovato mentre lo si scriveva.]

    La risposta della presa in carico contiene un campo `ritira_su` che dice
    dove ripassare. Componendolo dal nome del lavoro veniva fuori
    `/v1/itinerario/esito/...` — con la «o» finale, in italiano — mentre la
    rotta vera si chiama `/v1/itinerary/...`. Nessuno se ne sarebbe accorto:
    oggi Make non legge quel campo, si compone l'indirizzo da solo. Sarebbe
    stata una bugia scritta nel prodotto, in attesa del primo che ci crede.
    """

    def _ritira_su(self, rotta):
        with mock.patch.object(self.servizio, "_esegui_itinerario",
                               lambda body: ({"ok": True}, 200)), \
             mock.patch.object(self.servizio, "_esegui_pdf",
                               lambda body: ({"ok": True}, 200)):
            risposta = self.client.post(rotta, json={"trip": {}},
                                        headers=self.intestazioni)
        return risposta.get_json()["ritira_su"]

    def test_l_indirizzo_promesso_risponde_davvero(self):
        for rotta in ("/v1/itinerary/avvia", "/v1/pdf/avvia"):
            with self.subTest(rotta=rotta):
                indirizzo = self._ritira_su(rotta)
                risposta = self.client.get(indirizzo, headers=self.intestazioni)
                self.assertNotEqual(
                    risposta.status_code, 404,
                    f"{rotta} promette di ripassare su {indirizzo}, che non "
                    "e' una strada di questo servizio")


class TestIlServizioRegeIlTempoCheGliChiediamo(unittest.TestCase):
    """[REGRESSIONE 2026-08-10 — da un `502 Bad Gateway` vero.]

    Il 10 agosto, alle 16:19, un'esecuzione e' morta dopo 369 secondi con un
    `502 Bad Gateway`. Quel codice non lo scrive il nostro servizio — quando
    e' lui a rifiutare qualcosa risponde con una frase in italiano. Un 502
    secco e' il portone che dice «dietro di me non risponde nessuno»: il
    processo si era spento mentre lavorava.

    Due numeri devono restare d'accordo fra loro, e vivono in file diversi:
    quanto a lungo una richiesta puo' restare aperta ad aspettare
    (`lavori.ATTESA_MASSIMA_SECONDI`) e dopo quanto gunicorn considera un
    processo bloccato e lo uccide (`--timeout`). Se il secondo scende sotto il
    primo, il servizio ammazza da solo le proprie richieste — e il cliente
    riceve un 502 che non spiega niente.
    """

    def _riga_di_avvio(self, nome):
        import pathlib

        radice = pathlib.Path(__file__).resolve().parent.parent
        for riga in (radice / nome).read_text(encoding="utf-8").splitlines():
            pulita = riga.split("#", 1)[0].strip()
            if "gunicorn" in pulita:
                return pulita
        return ""

    def _valore(self, riga, opzione):
        pezzi = riga.split()
        return int(pezzi[pezzi.index(opzione) + 1])

    def test_il_tetto_di_gunicorn_sta_sopra_all_attesa_piu_lunga(self):
        from src import lavori

        for nome in ("Dockerfile", "Procfile"):
            with self.subTest(nome=nome):
                riga = self._riga_di_avvio(nome)
                self.assertTrue(riga, f"{nome}: riga di avvio non trovata")
                self.assertGreater(
                    self._valore(riga, "--timeout"), lavori.ATTESA_MASSIMA_SECONDI,
                    f"{nome}: gunicorn uccide la richiesta prima che l'attesa "
                    "finisca — il cliente riceve un 502 senza spiegazione")

    def test_i_due_file_dicono_la_stessa_cosa(self):
        # Render usa il Dockerfile, il Procfile serve altrove: due righe
        # diverse vorrebbero dire due comportamenti diversi a seconda di dove
        # gira, e nessuno se ne accorgerebbe finche' non conta.
        self.assertEqual(
            self._riga_di_avvio("Dockerfile").replace("CMD ", ""),
            self._riga_di_avvio("Procfile").replace("web: ", ""))

    def test_un_processo_solo(self):
        """512 MB non bastano per due copie di una generazione.

        Non e' una regola di stile: e' la lettura del guasto del 10 agosto.
        Se un giorno il piano di Render cresce si puo' tornare indietro — ma
        allora questo controllo va riscritto guardando la memoria vera, non
        cancellato perche' da' fastidio.
        """
        self.assertEqual(self._valore(self._riga_di_avvio("Dockerfile"),
                                      "--workers"), 1)


if __name__ == "__main__":
    unittest.main()
