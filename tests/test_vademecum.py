"""
[AGGIUNTO 2026-08-02 — task #167] Copre src/vademecum.py e la sua resa nel PDF.

Richiesta di Lorenzo, alla lettera: "aggiungi una parte di «vademecum di
viaggio» e di suggerimenti di cosa portare in valigia su come strutturarla, in
base a dove si va e alla stagione (in base al clima e alle previsioni
metereologiche) + per eventuali aerei low cost o quando venga richiesto quale
tipologia di bagaglio conviene prendere (stiva o cabina) e il costo di
quest'ultimo".

I test di principio, quelli che valgono più degli altri messi insieme:

  * `test_nessuna_previsione_meteo_spacciata_per_dato` — il documento nasce
    settimane prima della partenza. Stampare "il 14 settembre ci saranno 24°"
    non è un servizio, è una bugia con l'aria di un dato. Si stampa il clima
    tipico (vero, storico, verificabile) e si dà il link alla previsione vera
    con scritto QUANDO aprirlo.
  * `test_nessun_orario_di_tramonto_stimato` — `sun_times` senza il fuso vero
    ripiega sulla longitudine e su Lisbona sbaglia di due ore. La durata della
    luce, invece, è una differenza fra istanti: il fuso si semplifica e sparisce.
    Stampiamo solo quella.
  * `test_destinazione_sconosciuta_non_inventa_un_clima` — stessa regola del
    numero di emergenza in `predeparture`: l'omissione, mai il plausibile.
  * `test_niente_tariffe_bagaglio_a_chi_parte_in_auto` — stampare il listino
    Ryanair a chi va in macchina è il tipo di rumore che fa perdere fiducia in
    tutto il resto del documento.
"""
import unittest

from src import vademecum
from src.pdf_renderer import _render_vademecum, render_html
from src.schemas import POI


class FakeTrip:
    """Il `Trip` reale ha sei campi obbligatori che qui non servono a niente.
    `vademecum` legge i suoi ingredienti con `_get()`, che funziona sia sugli
    oggetti sia sui dizionari: questo è il minimo che serve."""

    def __init__(self, destination=None, date_start=None, date_end=None,
                 duration_days=None, raw_notes=None, dest_lat=None, dest_lng=None):
        self.destination = destination
        self.date_start = date_start
        self.date_end = date_end
        self.duration_days = duration_days
        self.raw_notes = raw_notes
        self.dest_lat = dest_lat
        self.dest_lng = dest_lng


LISBONA = FakeTrip("Lisbona, Portogallo", "2026-09-14", "2026-09-18",
                   raw_notes="voliamo low cost da Milano",
                   dest_lat=38.72, dest_lng=-9.14)
BERLINO_INVERNO = FakeTrip("Berlino, Germania", "2027-01-10", "2027-01-18",
                           raw_notes="voliamo con Ryanair")
CORTINA = FakeTrip("Cortina d'Ampezzo, Italia", "2027-02-01", "2027-02-04")

MUSEO = POI(id="M1", type="museum", name="Museu Nacional", lat=38.7, lng=-9.1)
MUSEO_2 = POI(id="M2", type="museum", name="Museu do Azulejo", lat=38.72, lng=-9.11)
CHIESA = POI(id="C1", type="activity", name="Cattedrale di Lisbona",
             lat=38.71, lng=-9.13)
CHIESA_2 = POI(id="C2", type="activity", name="Chiesa di São Roque",
               lat=38.715, lng=-9.14)
PARCO = POI(id="P1", type="activity", name="Miradouro da Senhora do Monte",
            lat=38.72, lng=-9.13, primary_type="park")
RISTORANTE_CARO = POI(id="R1", type="restaurant", name="Belcanto",
                      lat=38.71, lng=-9.14, price_level="VERY_EXPENSIVE")

ITINERARIO = {
    "days": [
        {"day": 1, "blocks": [{"poi_id": "M1"}, {"poi_id": "C1"}]},
        {"day": 2, "blocks": [{"poi_id": "M2"}, {"poi_id": "P1"}, {"poi_id": "R1"}]},
    ]
}
POIS = [MUSEO, MUSEO_2, CHIESA, CHIESA_2, PARCO, RISTORANTE_CARO]


# --- Il clima -------------------------------------------------------------
class TestClima(unittest.TestCase):
    def test_lisbona_a_settembre_ha_un_clima_mediterraneo_e_caldo(self):
        c = vademecum.build_climate(LISBONA)
        self.assertEqual(c["month"], 9)
        self.assertEqual(c["month_label"], "settembre")
        self.assertGreaterEqual(c["temp_max"], 22)
        self.assertLess(c["temp_min"], c["temp_max"])

    def test_berlino_a_gennaio_e_freddo_e_lisbona_no(self):
        """Il test che giustifica l'esistenza delle zone climatiche: se
        gennaio a Berlino e settembre a Lisbona producessero la stessa
        valigia, la sezione non servirebbe a niente."""
        berlino = vademecum.build_climate(BERLINO_INVERNO)
        lisbona = vademecum.build_climate(LISBONA)
        self.assertLess(berlino["temp_max"], 10)
        self.assertGreater(lisbona["temp_max"], 20)

    def test_una_localita_alpina_non_prende_il_clima_del_suo_paese(self):
        """Cortina è in Italia, ma a febbraio non ha il clima di Roma."""
        self.assertEqual(vademecum.resolve_climate_zone(CORTINA), "alpino")

    def test_destinazione_sconosciuta_non_inventa_un_clima(self):
        trip = FakeTrip("Ulan Bator, Mongolia", "2026-09-14", "2026-09-18")
        self.assertIsNone(vademecum.resolve_climate_zone(trip))
        self.assertIsNone(vademecum.build_climate(trip))

    def test_senza_data_leggibile_non_esiste_un_mese_e_quindi_niente_scheda(self):
        self.assertIsNone(vademecum.build_climate(FakeTrip("Lisbona, Portogallo")))
        self.assertIsNone(
            vademecum.build_climate(FakeTrip("Lisbona, Portogallo", "non-una-data"))
        )

    def test_il_link_alle_previsioni_e_una_ricerca_dichiarata_non_un_url_indovinato(self):
        """Stessa regola dei menù dei ristoranti: mai un URL costruito a mano
        che potrebbe non esistere. Una ricerca è sempre valida."""
        link = vademecum.forecast_link(LISBONA)
        self.assertTrue(link["url"].startswith("https://www.google.com/search?q="))
        self.assertIn("meteo", link["url"])

    def test_nessuna_previsione_meteo_spacciata_per_dato(self):
        """Il campo si chiama `note` e parla di clima. Da nessuna parte, in
        nessun campo, compare un'affermazione su che tempo FARÀ."""
        c = vademecum.build_climate(LISBONA)
        testo = " ".join(str(v) for v in c.values() if isinstance(v, str)).lower()
        for bugia in ("ci sarà il sole", "pioverà", "farà bel tempo", "previsto sole"):
            self.assertNotIn(bugia, testo)

    def test_nessun_orario_di_tramonto_stimato(self):
        """`sun_times` senza fuso orario vero sbaglia di due ore sul
        Portogallo. La durata della luce no: quella è corretta ovunque."""
        c = vademecum.build_climate(LISBONA)
        self.assertNotIn("sunset", c)
        self.assertNotIn("sunrise", c)
        self.assertIn("di luce", c.get("daylight_label", ""))


# --- La valigia -----------------------------------------------------------
class TestValigia(unittest.TestCase):
    def _gruppi(self, trip=LISBONA, itinerario=ITINERARIO, pois=POIS):
        clima = vademecum.build_climate(trip)
        gruppi = vademecum.build_packing(trip, itinerario, pois, clima)
        return {g["group"]: g["items"] for g in gruppi}

    def test_ogni_gruppo_ha_almeno_una_voce(self):
        for gruppo in vademecum.build_packing(
            LISBONA, ITINERARIO, POIS, vademecum.build_climate(LISBONA)
        ):
            self.assertTrue(gruppo["items"], gruppo["group"])

    def test_il_numero_di_cambi_dipende_dalla_durata_del_viaggio(self):
        corto = self._gruppi(FakeTrip("Lisbona, Portogallo", "2026-09-14", "2026-09-16"))
        lungo = self._gruppi(FakeTrip("Lisbona, Portogallo", "2026-09-14", "2026-09-24"))
        self.assertNotEqual(corto["Quanto portare"], lungo["Quanto portare"])

    def test_una_chiesa_in_programma_produce_la_riga_su_spalle_e_ginocchia(self):
        testo = " ".join(
            v for items in self._gruppi().values() for v in items
        ).lower()
        self.assertIn("ginocchia", testo)

    def test_il_verbo_e_accordato_col_numero_di_luoghi_di_culto(self):
        """Nome E verbo, non solo il nome.

        Il primo campione stampava "nel programma c'è 2 luoghi di culto": il
        plurale era stato risolto sul sostantivo e dimenticato sul verbo, che
        è esattamente lo stesso difetto da modulo prestampato della barra
        obliqua "luogo/luoghi", spostato di una parola. Un cliente che ha
        pagato lo legge come una svista, e le sviste visibili fanno dubitare
        anche dei dati che non può verificare.
        """
        def _riga(itinerario):
            for items in self._gruppi(itinerario=itinerario).values():
                for v in items:
                    if "ginocchia" in v:
                        return v
            return ""

        uno = _riga({"days": [{"day": 1, "blocks": [{"poi_id": "C1"}]}]})
        self.assertIn("c'è un luogo di culto", uno)
        self.assertNotIn("c'è 1", uno)

        due = _riga({"days": [{"day": 1, "blocks": [
            {"poi_id": "C1"}, {"poi_id": "C2"},
        ]}]})
        self.assertIn("ci sono 2 luoghi di culto", due)
        self.assertNotIn("c'è 2", due)

    def test_senza_luoghi_di_culto_quella_riga_non_compare(self):
        itinerario = {"days": [{"day": 1, "blocks": [{"poi_id": "M1"}]}]}
        testo = " ".join(
            v for items in self._gruppi(itinerario=itinerario).values() for v in items
        ).lower()
        self.assertNotIn("ginocchia", testo)

    def test_un_ristorante_di_fascia_alta_produce_la_riga_sul_vestito_buono(self):
        gruppi = self._gruppi()
        testo = " ".join(gruppi.get("Quello che chiede questo programma", [])).lower()
        self.assertTrue("elegante" in testo or "buono" in testo or "camicia" in testo)

    def test_il_freddo_cambia_i_vestiti(self):
        caldo = " ".join(v for items in self._gruppi().values() for v in items).lower()
        freddo = " ".join(
            v for items in self._gruppi(BERLINO_INVERNO).values() for v in items
        ).lower()
        self.assertNotEqual(caldo, freddo)

    def test_l_adattatore_compare_solo_dove_serve(self):
        """L'Italia e la Germania condividono la presa: l'adattatore per
        Berlino è una riga inutile. Il Regno Unito no."""
        self.assertFalse(vademecum._needs_adapter("Tipo F"))
        self.assertTrue(vademecum._needs_adapter("Tipo G"))
        self.assertTrue(vademecum._needs_adapter("Tipo J"))

    def test_la_lista_regge_un_itinerario_malformato(self):
        """`render_html()` non è protetto dal validatore: un blocco con un
        `poi_id` che è una lista non deve far cadere niente."""
        rotto = {"days": [{"day": 1, "blocks": [{"poi_id": ["M1"]}, "non-un-dict"]}]}
        self.assertTrue(vademecum.build_packing(LISBONA, rotto, POIS, None))

    def test_senza_clima_la_lista_esiste_lo_stesso(self):
        gruppi = vademecum.build_packing(LISBONA, ITINERARIO, POIS, None)
        self.assertTrue(gruppi)


class TestComeSiRiempie(unittest.TestCase):
    def test_i_passi_sono_in_ordine_e_hanno_tutti_un_titolo(self):
        passi = vademecum.build_suitcase_layout()
        self.assertGreaterEqual(len(passi), 6)
        for passo in passi:
            self.assertTrue(passo["title"])

    def test_con_la_stiva_compare_il_cambio_nel_bagaglio_a_mano(self):
        senza = " ".join(p["title"] for p in vademecum.build_suitcase_layout(False))
        con = " ".join(p["title"] for p in vademecum.build_suitcase_layout(True))
        self.assertNotIn("cambio completo", senza.lower())
        self.assertIn("cambio completo", con.lower())


# --- Cabina o stiva -------------------------------------------------------
class TestBagaglio(unittest.TestCase):
    def test_un_weekend_al_caldo_si_fa_in_cabina(self):
        b = vademecum.build_baggage(
            FakeTrip("Lisbona, Portogallo", "2026-09-14", "2026-09-16",
                     raw_notes="volo low cost"),
            vademecum.build_climate(LISBONA),
        )
        self.assertEqual(b["choice"], "cabina")

    def test_dieci_giorni_richiedono_la_stiva(self):
        trip = FakeTrip("Lisbona, Portogallo", "2026-09-14", "2026-09-24",
                        raw_notes="volo low cost")
        b = vademecum.build_baggage(trip, vademecum.build_climate(trip))
        self.assertEqual(b["choice"], "stiva")

    def test_il_freddo_sposta_la_soglia(self):
        """Otto giorni a Lisbona e otto a Berlino non producono la stessa
        valigia: i capi invernali occupano il doppio."""
        b = vademecum.build_baggage(
            BERLINO_INVERNO, vademecum.build_climate(BERLINO_INVERNO)
        )
        self.assertEqual(b["choice"], "stiva")

    def test_il_costo_totale_e_aritmetica_e_cresce_con_le_persone(self):
        uno = vademecum.build_baggage(LISBONA, vademecum.build_climate(LISBONA),
                                      travellers=1)
        due = vademecum.build_baggage(LISBONA, vademecum.build_climate(LISBONA),
                                      travellers=2)
        self.assertIn("2 acquisti", uno["total"])
        self.assertIn("4 acquisti", due["total"])

    def test_chi_viaggia_da_solo_non_legge_consigli_per_due(self):
        uno = vademecum.build_baggage(LISBONA, None, travellers=1)
        due = vademecum.build_baggage(LISBONA, None, travellers=2)
        self.assertLess(len(uno["notes"]), len(due["notes"]))

    def test_niente_tariffe_bagaglio_a_chi_parte_in_auto(self):
        trip = FakeTrip("Firenze, Italia", "2026-09-14", "2026-09-18",
                        raw_notes="andiamo in auto da Milano")
        self.assertIsNone(vademecum.build_baggage(trip, None))

    def test_ma_se_nomina_un_volo_le_tariffe_tornano(self):
        trip = FakeTrip("Firenze, Italia", "2026-09-14", "2026-09-18",
                        raw_notes="in auto fino all'aeroporto, poi volo per Firenze")
        self.assertIsNotNone(vademecum.build_baggage(trip, None))

    def test_le_tariffe_sono_dichiarate_come_indicative_e_datate(self):
        b = vademecum.build_baggage(LISBONA, None)
        self.assertIn(vademecum.BAGGAGE_PRICES_UPDATED, b["caveat"])
        self.assertIn("indicative", b["caveat"].lower())

    def test_nessun_residuo_di_scrittura_nel_testo_stampato(self):
        """Guardia contro il difetto vero trovato in revisione: una nota che
        cominciava con un frammento di editing ("Con il people label utile:")
        sarebbe finita, parola per parola, sotto gli occhi di un cliente
        pagante. Nessuna riga di questa sezione può contenere il nome di una
        variabile del codice."""
        b = vademecum.build_baggage(LISBONA, vademecum.build_climate(LISBONA),
                                    travellers=2)
        testo = " ".join(
            [b["reason"], b["total"], b["caveat"]] + list(b["notes"])
        ).lower()
        for residuo in ("people_label", "people label", "temp_max", "temp_min",
                        "none", "{", "}", "todo", "fixme"):
            self.assertNotIn(residuo, testo)


# --- L'assemblaggio -------------------------------------------------------
class TestBuildVademecum(unittest.TestCase):
    def test_ritorna_le_quattro_chiavi_sempre(self):
        v = vademecum.build_vademecum(LISBONA, ITINERARIO, pois=POIS, travellers=2)
        self.assertEqual(
            set(v), {"climate", "packing", "suitcase", "baggage"}
        )

    def test_non_solleva_mai_su_ingressi_assurdi(self):
        for trip in (FakeTrip(), FakeTrip("???"), None):
            v = vademecum.build_vademecum(trip)
            self.assertEqual(set(v), {"climate", "packing", "suitcase", "baggage"})

    def test_funziona_anche_con_un_trip_dizionario(self):
        """`pdf_renderer` riceve `trip` come dict, `pdf_extras` come oggetto:
        entrambe le forme devono passare."""
        v = vademecum.build_vademecum(
            {"destination": "Lisbona, Portogallo", "date_start": "2026-09-14",
             "date_end": "2026-09-18"}
        )
        self.assertIsNotNone(v["climate"])


# --- La resa nel documento ------------------------------------------------
class TestResaNelDocumento(unittest.TestCase):
    ITINERARIO_MINIMO = {
        "executive_summary": "x",
        "days": [{"day": 1, "title": "Centro", "blocks": [{"poi_id": "M1"}]}],
    }
    TRIP = {"destination": "Lisbona, Portogallo", "objective_function": "Cultura",
            "date_start": "2026-09-14", "date_end": "2026-09-18", "duration_days": 5}

    def _vademecum(self):
        return vademecum.build_vademecum(LISBONA, ITINERARIO, pois=POIS, travellers=2)

    def _html(self):
        return render_html(
            self.ITINERARIO_MINIMO, self.TRIP, vademecum=self._vademecum()
        )

    def test_vuoto_non_produce_niente(self):
        self.assertEqual(_render_vademecum(None), "")
        self.assertEqual(_render_vademecum({}), "")
        self.assertEqual(
            _render_vademecum(
                {"climate": None, "packing": [], "suitcase": [], "baggage": None}
            ), ""
        )

    def test_la_sezione_compare_con_la_sua_ancora(self):
        self.assertIn("id='vademecum'", self._html())

    def test_e_raggiungibile_dallindice(self):
        html = self._html()
        self.assertIn("href='#vademecum'", html)
        self.assertIn("Vademecum", html)

    def test_senza_dati_il_documento_resta_identico_a_prima(self):
        self.assertNotIn("vademecum", render_html(self.ITINERARIO_MINIMO, self.TRIP))

    def test_i_tre_blocchi_arrivano_nel_documento(self):
        html = self._html()
        self.assertIn("vad-climate", html)
        self.assertIn("vad-items", html)
        self.assertIn("vad-fares", html)

    def test_nessuna_proprieta_css_non_supportata_dal_motore(self):
        html = self._html()
        for vietata in ("linear-gradient", "rgba(", "display: flex", "opacity:"):
            self.assertNotIn(vietata, html)

    def test_nessun_url_non_cifrato(self):
        self.assertNotIn("http://", self._html())

    def test_il_testo_del_cliente_e_sempre_sfuggito(self):
        html = _render_vademecum({
            "climate": {"month_label": "<script>x</script>", "temp_max": 20,
                        "temp_min": 10, "note": "a & b"},
            "packing": [{"group": "<b>g</b>", "items": ["<i>x</i>"]}],
            "suitcase": [{"title": "<u>t</u>", "detail": "d & d"}],
            "baggage": {"choice": "cabina", "reason": "r & r", "notes": ["<em>n</em>"]},
        })
        self.assertNotIn("<script>", html)
        self.assertNotIn("<b>g</b>", html)
        self.assertIn("&amp;", html)

    def test_le_voci_della_valigia_stanno_su_due_colonne(self):
        """Il rimedio diretto ai «troppi spazi vuoti dispersivi»: una lista a
        colonna singola sprecava due terzi della larghezza del foglio."""
        html = _render_vademecum({
            "climate": None, "suitcase": [], "baggage": None,
            "packing": [{"group": "G", "items": ["a", "b", "c", "d"]}],
        })
        self.assertEqual(html.count("<tr>"), 2)

    def test_un_numero_dispari_di_voci_non_rompe_la_griglia(self):
        html = _render_vademecum({
            "climate": None, "suitcase": [], "baggage": None,
            "packing": [{"group": "G", "items": ["a", "b", "c"]}],
        })
        self.assertEqual(html.count("<td>"), 4)

    def test_il_verdetto_sul_bagaglio_si_legge_da_lontano(self):
        html = _render_vademecum({
            "climate": None, "packing": [], "suitcase": [],
            "baggage": {"choice": "cabina, ma stretta", "reason": "r",
                        "total": "t", "carriers": [], "notes": []},
        })
        self.assertIn("vad-badge", html)
        self.assertIn("cabina", html)
        self.assertIn("ma stretta", html)

    def test_la_stiva_si_distingue_a_colpo_docchio_dalla_cabina(self):
        base = {"climate": None, "packing": [], "suitcase": [], "carriers": []}
        cabina = _render_vademecum(
            {**base, "baggage": {"choice": "cabina", "notes": []}}
        )
        stiva = _render_vademecum(
            {**base, "baggage": {"choice": "stiva", "notes": []}}
        )
        self.assertNotIn("vad-badge-hold", cabina)
        self.assertIn("vad-badge-hold", stiva)

    def test_niente_caselle_unicode_che_il_motore_non_sa_disegnare(self):
        """I caratteri di casella non esistono nei font del renderer e
        uscirebbero come rettangoli vuoti: cioè come un errore di stampa."""
        html = self._html()
        for glifo in ("☐", "☑", "□", "✔"):
            self.assertNotIn(glifo, html)


class TestCablaggioInBuildPdfSections(unittest.TestCase):
    def test_la_chiave_e_fra_quelle_passate_al_renderer(self):
        from src.pdf_extras import _RENDER_SECTION_KEYS
        self.assertIn("vademecum", _RENDER_SECTION_KEYS)

    def test_render_pdf_accetta_il_parametro(self):
        import inspect
        from src.pdf_renderer import render_pdf
        self.assertIn("vademecum", inspect.signature(render_pdf).parameters)


if __name__ == "__main__":
    unittest.main()
