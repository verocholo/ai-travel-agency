"""
Il CRITERIO con cui e' costruita una giornata: prove.

[AGGIUNTO 2026-08-03 — task #180, richiesta di Lorenzo: «dare un criterio alla
programmazione delle cose da vedere (minimizzare gli spostamenti, tenendo
conto degli orari di apertura delle strutture e le varie pause durante la
giornata)»]

Queste prove sorvegliano tre cose diverse, e vale la pena tenerle distinte
perche' si rompono per ragioni diverse:

1. che gli ORARI arrivino fin qui (`places_client._open_hours`). Fino a ieri
   Google ce li mandava, li pagavamo, e li buttavamo via tenendo solo i
   giorni: la regola «tieni conto degli orari» non era disattesa, era
   impossibile da formulare;
2. che il CONTROLLO sia giusto (`scheduling_criteria`), compreso il caso in
   cui gli orari non ci sono — "non lo so" non deve mai diventare "chiuso";
3. che il criterio DICHIARATO al cliente e quello CHIESTO al modello siano lo
   stesso testo. E' la prova piu' importante del file e la meno ovvia: senza,
   fra sei mesi il documento promettera' una cosa e il prompt ne chiedera'
   un'altra, e nessuno se ne accorgera' perche' entrambi continueranno a
   funzionare benissimo, ciascuno per conto suo.
"""
import unittest
from pathlib import Path

from src import scheduling_criteria as sc
from src.places_client import _open_hours, _orario


RADICE = Path(__file__).resolve().parent.parent


# --- Gli orari arrivano dal fornitore ------------------------------------

class TestOrariDaGoogle(unittest.TestCase):
    """`regularOpeningHours` -> `{"Mon": [["09:00","19:00"]]}`."""

    def test_una_giornata_normale(self):
        risposta = {"periods": [
            {"open": {"day": 1, "hour": 9, "minute": 0},
             "close": {"day": 1, "hour": 19, "minute": 30}},
        ]}
        self.assertEqual(_open_hours(risposta), {"Mon": [["09:00", "19:30"]]})

    def test_il_giorno_zero_di_google_e_domenica_non_lunedi(self):
        # Il trabocchetto piu' pericoloso di tutto il modulo: Google numera i
        # giorni da domenica, Python da lunedi'. Sbagliarlo sposta ogni orario
        # di apertura di 24 ore, e un martedi' scambiato per un lunedi' e'
        # perfettamente plausibile a occhio — nessuno lo troverebbe rileggendo.
        risposta = {"periods": [
            {"open": {"day": 0, "hour": 10, "minute": 0},
             "close": {"day": 0, "hour": 13, "minute": 0}},
        ]}
        self.assertEqual(_open_hours(risposta), {"Sun": [["10:00", "13:00"]]})

    def test_due_fasce_nello_stesso_giorno_restano_due(self):
        # La chiusura a pranzo esiste, e schiacciarla in 09:00-19:00 farebbe
        # trovare il portone chiuso a chi ci arriva alle 14.
        risposta = {"periods": [
            {"open": {"day": 2, "hour": 15, "minute": 0},
             "close": {"day": 2, "hour": 19, "minute": 0}},
            {"open": {"day": 2, "hour": 9, "minute": 0},
             "close": {"day": 2, "hour": 13, "minute": 0}},
        ]}
        self.assertEqual(
            _open_hours(risposta),
            {"Tue": [["09:00", "13:00"], ["15:00", "19:00"]]},
        )

    def test_risposte_malformate_non_fanno_saltare_niente(self):
        for grezza in (None, {}, {"periods": None}, {"periods": []},
                       {"periods": [None]}, {"periods": [{"open": None}]},
                       {"periods": [{"open": {"day": 9, "hour": 9, "minute": 0},
                                     "close": {"day": 9, "hour": 10, "minute": 0}}]},
                       {"periods": [{"open": {"day": 1, "hour": 99, "minute": 0},
                                     "close": {"day": 1, "hour": 10, "minute": 0}}]}):
            with self.subTest(grezza=grezza):
                self.assertIsNone(_open_hours(grezza))

    def test_un_locale_aperto_oltre_la_mezzanotte_non_diventa_una_fascia_negativa(self):
        # Apre lunedi' alle 19 e chiude martedi' alle 2. Se lo scrivessimo
        # come 19:00-02:00 la fascia sarebbe "vuota" per qualunque conto e il
        # locale risulterebbe chiuso tutta la sera, cioe' proprio quando e'
        # aperto. Viene troncato alla fine del giorno di apertura.
        risposta = {"periods": [
            {"open": {"day": 1, "hour": 19, "minute": 0},
             "close": {"day": 2, "hour": 2, "minute": 0}},
        ]}
        self.assertEqual(_open_hours(risposta), {"Mon": [["19:00", "23:59"]]})

    def test_orario_singolo(self):
        self.assertEqual(_orario({"hour": 9, "minute": 5}), "09:05")
        self.assertIsNone(_orario({"hour": 25, "minute": 0}))
        self.assertIsNone(_orario(None))


# --- Il controllo ---------------------------------------------------------

class TestStatoApertura(unittest.TestCase):
    ORARI = {"Mon": [["09:00", "13:00"], ["15:00", "19:00"]]}

    def test_dentro_una_fascia_e_aperto(self):
        self.assertEqual(sc.stato_apertura(self.ORARI, "Mon", "10:00"), "aperto")
        self.assertEqual(sc.stato_apertura(self.ORARI, "Mon", "16:30"), "aperto")

    def test_nel_buco_del_pranzo_e_chiuso(self):
        self.assertEqual(sc.stato_apertura(self.ORARI, "Mon", "14:00"), "chiuso")

    def test_un_giorno_non_elencato_e_chiuso(self):
        self.assertEqual(sc.stato_apertura(self.ORARI, "Tue", "10:00"), "ignoto")

    def test_senza_orari_e_ignoto_mai_chiuso(self):
        # La distinzione che regge tutto il resto. Dire "chiuso" di un luogo
        # di cui non sappiamo gli orari manda il cliente a saltare una tappa
        # aperta; dire "aperto" e' la bugia che questo prodotto esiste per non
        # dire. Resta "ignoto", e il documento lo scrive.
        self.assertEqual(sc.stato_apertura(None, "Mon", "10:00"), "ignoto")
        self.assertEqual(sc.stato_apertura({}, "Mon", "10:00"), "ignoto")
        self.assertEqual(sc.stato_apertura({"Mon": []}, "Mon", "10:00"), "ignoto")

    def test_un_orario_illeggibile_non_produce_una_segnalazione(self):
        for orario in (None, "", "mattina", "25:00", 9):
            with self.subTest(orario=orario):
                self.assertEqual(sc.stato_apertura(self.ORARI, "Mon", orario), "ignoto")

    def test_gli_estremi_contano_come_aperto(self):
        self.assertEqual(sc.stato_apertura(self.ORARI, "Mon", "09:00"), "aperto")
        self.assertEqual(sc.stato_apertura(self.ORARI, "Mon", "19:00"), "aperto")


class TestGiornoDellaSettimana(unittest.TestCase):
    def test_il_giorno_uno_e_la_data_di_partenza(self):
        # Stessa convenzione senza "+1" di `_day_calendar_label()` e di
        # `_date_difference_days()`. Un modulo che contasse diversamente
        # sposterebbe TUTTI gli orari di 24 ore in silenzio.
        self.assertEqual(sc.giorno_settimana("2026-09-14", 1), "Mon")
        self.assertEqual(sc.giorno_settimana("2026-09-14", 3), "Wed")
        self.assertEqual(sc.giorno_settimana("2026-09-14", 7), "Sun")

    def test_date_assurde_non_producono_un_giorno_inventato(self):
        for data, numero in (("", 1), (None, 1), ("2026-09-14", None),
                             ("non-una-data", 1), ("2026-09-14", 0),
                             ("2026-09-14", 9999)):
            with self.subTest(data=data, numero=numero):
                self.assertIsNone(sc.giorno_settimana(data, numero))


class TestVerificaGiornata(unittest.TestCase):
    POI = {
        "P1": {"name": "Museo Civico", "open_hours": {"Mon": [["09:00", "13:00"]]}},
        "P2": {"name": "Trattoria", "open_hours": None},
    }

    def test_segnala_solo_la_tappa_a_porta_chiusa(self):
        blocchi = [
            {"time": "10:00", "poi_id": "P1"},
            {"time": "15:00", "poi_id": "P1"},
            {"time": "20:00", "poi_id": "P2"},
            {"time": "21:00", "poi_id": None},
        ]
        fuori = sc.verifica_giornata(blocchi, self.POI, "Mon")
        self.assertEqual(list(fuori), [1])
        self.assertEqual(fuori[1]["orario"], "15:00")
        self.assertEqual(fuori[1]["finestre"], "09:00–13:00")
        self.assertEqual(fuori[1]["nome"], "Museo Civico")

    def test_senza_giorno_della_settimana_non_segnala_niente(self):
        # Meglio nessuna segnalazione che una segnalazione basata su un giorno
        # indovinato: la seconda e' peggio di niente, perche' viene creduta.
        blocchi = [{"time": "15:00", "poi_id": "P1"}]
        self.assertEqual(sc.verifica_giornata(blocchi, self.POI, None), {})

    def test_un_poi_id_non_stringa_non_fa_saltare_il_documento(self):
        # Difetto vero, trovato dal test di robustezza del renderer: il JSON
        # del modello passa di qui PRIMA della validazione, e un `poi_id`
        # uguale a una lista faceva alzare TypeError a `dict.get()`, cioe'
        # faceva perdere al cliente il documento intero per un campo storto.
        blocchi = [{"time": "15:00", "poi_id": ["P1"]},
                   {"time": "15:00", "poi_id": {"a": 1}},
                   {"time": "15:00", "poi_id": 7}]
        self.assertEqual(sc.verifica_giornata(blocchi, self.POI, "Mon"), {})

    def test_forme_inattese_non_sollevano(self):
        self.assertEqual(sc.verifica_giornata(None, self.POI, "Mon"), {})
        self.assertEqual(sc.verifica_giornata([None, 3, "x"], self.POI, "Mon"), {})
        self.assertEqual(sc.verifica_giornata([{"poi_id": "P1"}], None, "Mon"), {})


class TestDescriviFinestre(unittest.TestCase):
    def test_una_fascia(self):
        self.assertEqual(
            sc.descrivi_finestre({"Mon": [["09:00", "19:00"]]}, "Mon"),
            "09:00–19:00",
        )

    def test_due_fasce(self):
        self.assertEqual(
            sc.descrivi_finestre(
                {"Mon": [["09:00", "13:00"], ["15:00", "19:00"]]}, "Mon"),
            "09:00–13:00 e 15:00–19:00",
        )

    def test_senza_orari_stringa_vuota(self):
        self.assertEqual(sc.descrivi_finestre(None, "Mon"), "")


# --- Il criterio nel documento -------------------------------------------

class TestCriterioNelDocumento(unittest.TestCase):
    TRIP = {"destination": "Siena", "date_start": "2026-09-14",
            "date_end": "2026-09-16", "duration_days": 3}

    def _itinerario(self, orario_museo="15:00"):
        return {
            "destination": "Siena",
            "executive_summary": "Tre giorni.",
            "days": [{"day": 1, "title": "Arrivo", "blocks": [
                {"time": "10:00", "activity": "Passeggiata", "location": "Centro",
                 "poi_id": "P2"},
                {"time": orario_museo, "activity": "Visita al museo",
                 "location": "Museo Civico", "poi_id": "P1"},
            ]}],
        }

    POI = [
        {"id": "P1", "name": "Museo Civico", "lat": 43.3, "lng": 11.3,
         "open_hours": {"Mon": [["09:00", "13:00"]]}},
        {"id": "P2", "name": "Piazza del Campo", "lat": 43.31, "lng": 11.33},
    ]

    def _html(self, **kwargs):
        from src.pdf_renderer import render_html
        return render_html(self._itinerario(**kwargs), self.TRIP, poi=self.POI)

    def test_il_documento_dichiara_il_criterio_una_volta_sola(self):
        out = self._html()
        for nome, _spiegazione in sc.CRITERIO:
            self.assertIn(nome, out)
        self.assertEqual(out.count("class='criterio-riga'"), len(sc.CRITERIO))

    def test_una_tappa_fuori_orario_viene_segnalata_accanto_alla_tappa(self):
        # Il 2026-09-14 e' un lunedi': il museo chiude alle 13:00, la visita
        # e' alle 15:00.
        out = self._html(orario_museo="15:00")
        self.assertIn("class='block-chiuso'", out)
        self.assertIn("alle 15:00 questo luogo risulta chiuso", out)
        self.assertIn("09:00&#8211;13:00", out.replace("–", "&#8211;"))

    def test_una_tappa_dentro_l_orario_non_produce_nessuna_segnalazione(self):
        out = self._html(orario_museo="10:30")
        self.assertNotIn("class='block-chiuso'", out)

    def test_senza_data_di_partenza_nessuna_segnalazione(self):
        from src.pdf_renderer import render_html
        trip = dict(self.TRIP)
        trip.pop("date_start")
        out = render_html(self._itinerario(), trip, poi=self.POI)
        self.assertNotIn("class='block-chiuso'", out)

    def test_la_segnalazione_non_e_gialla_come_il_margine_di_ritmo(self):
        # Se la segnalazione "porta chiusa" avesse lo stesso aspetto della
        # riga di ritmo, il cliente imparerebbe a saltarle entrambe — e quella
        # che conta e' questa.
        out = self._html()
        self.assertIn(".block-chiuso", out)
        self.assertNotIn("color: #7a6320;\n      background: #fbeeec", out)


class TestOrariNellaGuidaDellaAttrazione(unittest.TestCase):
    """Lo "zoom out dal macro al micro": il dettaglio sta nella guida."""

    ORARI = {"Mon": [["09:00", "13:00"], ["15:00", "19:00"]],
             "Tue": [["09:00", "19:00"]]}

    def test_la_guida_stampa_la_settimana_intera(self):
        from src.poi_pdf import build_guide_html
        html = build_guide_html(
            {"poi_name": "Museo Civico", "title": "Museo Civico"},
            destination="Siena", open_hours=self.ORARI,
        )
        self.assertIn("Orari di apertura", html)
        self.assertIn("Lun 09:00–13:00 e 15:00–19:00", html)
        self.assertIn("Mar 09:00–19:00", html)

    def test_un_giorno_assente_viene_scritto_chiuso_non_omesso(self):
        # Omettere il mercoledi' farebbe leggere "non lo sappiamo" a chi sta
        # guardando l'unica informazione che gli evita un viaggio a vuoto.
        from src.poi_pdf import build_guide_html
        html = build_guide_html(
            {"poi_name": "Museo Civico"}, open_hours=self.ORARI,
        )
        self.assertIn("Mer chiuso", html)
        self.assertIn("Dom chiuso", html)

    def test_senza_orari_la_riga_non_compare_affatto(self):
        # Sette "chiuso" inventati sono peggio del silenzio.
        from src.poi_pdf import build_guide_html
        html = build_guide_html({"poi_name": "Museo Civico"}, open_hours=None)
        self.assertNotIn("Orari di apertura", html)

    def test_gli_orari_arrivano_fin_qui_dalla_lista_dei_poi(self):
        # La catena intera, non il singolo anello: POI -> pdf_extras -> guida.
        from src.pdf_extras import _orari_per_poi

        class FintoPoi:
            id = "P1"
            open_hours = {"Mon": [["09:00", "19:00"]]}

        self.assertEqual(
            _orari_per_poi([{"id": "P1", "open_hours": {"Mon": [["09:00", "19:00"]]}}]),
            {"P1": {"Mon": [["09:00", "19:00"]]}},
        )
        self.assertEqual(_orari_per_poi([FintoPoi()]), {"P1": FintoPoi.open_hours})
        self.assertEqual(_orari_per_poi([{"id": "P1"}, None, {"open_hours": {}}]), {})
        self.assertEqual(_orari_per_poi(None), {})


# --- La prova che tiene insieme il prompt e il documento ------------------

class TestIlCriterioDichiaratoEQuelloChiestoAlModello(unittest.TestCase):
    """La prova piu' importante del file.

    Il criterio vive in due posti che nessun compilatore mette in relazione:
    la costante `scheduling_criteria.CRITERIO`, che il PDF stampa al cliente,
    e `prompts/system_prompt_master.txt`, che dice al modello come costruire
    la giornata. Se si separano, il documento promette una cosa e la giornata
    ne applica un'altra — e non se ne accorge nessuno, perche' entrambi
    continuano a funzionare benissimo ciascuno per conto suo. E' il tipo di
    difetto che si scopre da un cliente che ha fatto due volte lo stesso
    tragitto.
    """

    def _prompt(self):
        return (RADICE / "prompts" / "system_prompt_master.txt").read_text(encoding="utf-8")

    def test_le_tre_voci_del_criterio_sono_scritte_nel_prompt(self):
        prompt = self._prompt()
        for nome, _spiegazione in sc.CRITERIO:
            with self.subTest(nome=nome):
                self.assertIn(nome, prompt)

    def test_il_prompt_non_dichiara_voci_di_criterio_che_il_documento_non_stampa(self):
        # La direzione opposta della stessa prova: se qualcuno aggiungesse
        # una quarta voce al prompt senza aggiungerla alla costante, il
        # cliente riceverebbe una giornata costruita con una regola che il suo
        # documento non gli ha mai dichiarato.
        prompt = self._prompt()
        blocco = prompt.split("10. [AGGIUNTO 2026-08-03")[1].split("[FALLBACK_STRATEGIES]")[0]
        lettere = [r for r in blocco.splitlines() if r.strip()[:3] in ("a) ", "b) ", "c) ", "d) ")]
        self.assertEqual(len(lettere), len(sc.CRITERIO))

    def test_il_criterio_stampato_e_scritto_in_italiano_vero(self):
        # Difetto vero, visto rigenerando il campione: le tre righe erano
        # uscite come "ogni tappa e' collocata", con l'apostrofo al posto
        # dell'accento. E' la convenzione con cui in questo progetto si
        # scrivono i COMMENTI, ed era finita per inerzia dentro una stringa
        # che il cliente legge su un documento che ha pagato. La prova esiste
        # perche' l'inerzia non si corregge da sola: la prossima riga di testo
        # cliente scritta in questo file nascerebbe con lo stesso errore.
        troncate = ("e'", "perche'", "piu'", "puo'", "pero'", "gia'",
                    "cosi'", "citta'", "meta'", "verra'", "sara'")
        for nome, spiegazione in sc.CRITERIO:
            for parola in (nome + " " + spiegazione).split():
                with self.subTest(parola=parola):
                    self.assertNotIn(
                        parola.strip(".,;:").lower(), troncate,
                        "accento scritto con l'apostrofo in un testo che legge il cliente",
                    )

    def test_il_prompt_documenta_il_campo_degli_orari(self):
        # Senza questa riga in [INPUT_DATA] il modello riceve `open_hours` nel
        # JSON e non sa che cosa sia: il dato arriverebbe e resterebbe
        # inutilizzato, che e' esattamente la situazione da cui siamo partiti.
        prompt = self._prompt()
        self.assertIn("open_hours", prompt)
        self.assertIn("Controllo aperture", prompt)


if __name__ == "__main__":
    unittest.main()
