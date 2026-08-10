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
        self._cartella = tempfile.TemporaryDirectory()
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


if __name__ == "__main__":
    unittest.main()
