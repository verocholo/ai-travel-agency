"""
Test della cartina d'insieme — segnalazione di Lorenzo del 2026-08-03:
«standardizza tutto e risolvi il problema delle cartine che non si vedono […]
se hai capito cosa intendo fare hai capito l'importanza che hanno le cartine».

Il difetto vero non era grafico. Era che la cartina d'insieme era l'UNICA
figura del documento costruita in modo diverso da tutte le altre: mentre le
cartine delle singole giornate hanno un piano (dove sta l'albergo, dove stanno
le tappe, con che centro e zoom è stato preso lo sfondo) e una rete di
sicurezza (se Google non risponde la figura la disegniamo noi), la cartina
d'insieme era un blocco di byte già finito scaricato da Google. Da questo
seguivano due cose, entrambe visibili al cliente:

  1. senza chiave o senza rete la cartina d'insieme spariva e basta, senza che
     il documento lo dicesse: il capitolo di apertura perdeva la sua metà;
  2. essendo un'immagine piatta non sapevamo dove fosse finito ciascun
     pallino, quindi non potevamo renderli cliccabili — cioè non potevamo
     fare la cosa che Lorenzo ha chiesto per prima.

Questi test fissano il comportamento nuovo così che non si possa tornare
indietro per distrazione.
"""

import unittest
from pathlib import Path
from unittest.mock import patch

from src import map_render, maps_static, pdf_extras
from src.pdf_renderer import render_html


RADICE = Path(__file__).resolve().parent.parent


class TestIlPianoDinsieme(unittest.TestCase):
    """`build_overview_plan()` è pura: non tocca la rete, mette insieme le
    tappe di tutte le giornate in un piano solo."""

    def _piani_giornalieri(self):
        return [
            {
                "day": 1, "title": "Centro",
                "hotel_point": (43.32, 11.33), "hotel_name": "Albergo",
                "hotel_id": "H1",
                "stops": [
                    {"poi_id": "P1", "name": "Duomo", "point": (43.317, 11.328), "label": "1"},
                    {"poi_id": "P2", "name": "Piazza", "point": (43.318, 11.332), "label": "2"},
                ],
            },
            {
                "day": 2, "title": "Fuori porta",
                "hotel_point": (43.32, 11.33), "hotel_name": "Albergo",
                "hotel_id": "H1",
                "stops": [
                    # Ripetuto di proposito: lo stesso posto visto due giorni.
                    {"poi_id": "P1", "name": "Duomo", "point": (43.317, 11.328), "label": "1"},
                    {"poi_id": "P3", "name": "Fortezza", "point": (43.325, 11.320), "label": "2"},
                ],
            },
        ]

    def test_mette_insieme_tutte_le_tappe(self):
        piano = maps_static.build_overview_plan(self._piani_giornalieri())
        self.assertIsNotNone(piano)
        self.assertEqual([s["poi_id"] for s in piano["stops"]], ["P1", "P2", "P3"])

    def test_un_posto_visitato_due_volte_occupa_un_pallino_solo(self):
        """Due pallini sovrapposti nello stesso punto non aggiungono niente e
        rendono la figura illeggibile proprio dove è più fitta."""
        piano = maps_static.build_overview_plan(self._piani_giornalieri())
        ids = [s["poi_id"] for s in piano["stops"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_il_numero_del_pallino_e_il_giorno_non_lordine(self):
        """Su una cartina che copre tutto il viaggio la domanda del cliente non
        è «questa è la seconda tappa?» ma «quando ci vado?»."""
        piano = maps_static.build_overview_plan(self._piani_giornalieri())
        per_id = {s["poi_id"]: s["label"] for s in piano["stops"]}
        self.assertEqual(per_id["P1"], "1")
        self.assertEqual(per_id["P2"], "1")
        self.assertEqual(per_id["P3"], "2")

    def test_lalbergo_viene_riportato_una_volta_sola(self):
        piano = maps_static.build_overview_plan(self._piani_giornalieri())
        self.assertEqual(piano["hotel_point"], (43.32, 11.33))
        self.assertEqual(piano["hotel_id"], "H1")

    def test_senza_tappe_non_si_inventa_una_cartina_vuota(self):
        self.assertIsNone(maps_static.build_overview_plan([]))
        self.assertIsNone(maps_static.build_overview_plan(None))
        self.assertIsNone(maps_static.build_overview_plan([{"day": 1, "stops": []}]))

    def test_regge_dati_sporchi_senza_esplodere(self):
        """Arriva da una pipeline che degrada in silenzio: qui può passare di
        tutto, e un'eccezione costerebbe l'intero capitolo di apertura."""
        piano = maps_static.build_overview_plan(
            ["non un dizionario", None, {"day": 3, "stops": ["neanche questo", None]},
             {"day": 4, "stops": [{"poi_id": "P9", "point": (43.3, 11.3)}]}]
        )
        self.assertEqual([s["poi_id"] for s in piano["stops"]], ["P9"])


class TestLaCartinaDinsiemeHaLaReteDiSicurezza(unittest.TestCase):
    """Senza chiave Google la figura non deve sparire: deve uscire lo schema
    disegnato in casa, esattamente come per le singole giornate."""

    def _piani(self):
        return [{
            "day": 1, "title": "Centro",
            "hotel_point": (43.320, 11.330), "hotel_name": "Albergo", "hotel_id": "H1",
            "stops": [
                {"poi_id": "P1", "name": "Duomo", "point": (43.317, 11.328), "label": "1"},
                {"poi_id": "P2", "name": "Fortezza", "point": (43.325, 11.320), "label": "2"},
            ],
        }]

    def test_senza_chiave_esce_lo_schema_non_il_nulla(self):
        piano = maps_static.build_overview_map(
            [], [], {"days": []}, api_key=None, day_plans=self._piani(),
        )
        self.assertIsNotNone(piano)
        finito = map_render.attach_local_maps([piano])[0]
        self.assertTrue(finito.get("png"))
        self.assertEqual(finito.get("map_source"), "schema")

    def test_lo_schema_porta_con_se_la_posizione_dei_pallini(self):
        """È la parte che rende possibile la cartina cliccabile: dentro un PNG
        non si clicca niente, serve sapere DOVE è finito ogni pallino."""
        piano = maps_static.build_overview_map(
            [], [], {"days": []}, api_key=None, day_plans=self._piani(),
        )
        finito = map_render.attach_local_maps([piano])[0]
        pins = finito.get("pins")
        self.assertTrue(pins, "senza `pins` la cartina non può diventare cliccabile")
        for pin in pins:
            for chiave in ("label", "x_pct", "y_pct", "r_pct"):
                self.assertIn(chiave, pin)
            self.assertGreaterEqual(pin["x_pct"], 0)
            self.assertLessEqual(pin["x_pct"], 100)


class TestLeSezioniPortanoLaCartinaDinsieme(unittest.TestCase):

    def test_la_chiave_di_sezione_esiste_ed_e_accettata_dal_renderer(self):
        """Se `overview_map` non fosse nella lista bianca verrebbe buttata
        prima di arrivare al documento; se il renderer non la accettasse,
        OGNI documento fallirebbe con un errore di argomento inatteso."""
        self.assertIn("overview_map", pdf_extras._RENDER_SECTION_KEYS)
        sezioni, _errori = pdf_extras.split_render_kwargs(
            {"overview_map": {"png": b"X", "map_source": "schema", "stops": []}}
        )
        self.assertIn("overview_map", sezioni)
        # Non deve sollevare: è la prova che la firma del renderer è allineata.
        render_html({"days": []}, {"destination": "Siena"}, **sezioni)

    def test_si_puo_spegnere_senza_rompere_il_resto(self):
        with patch.object(maps_static, "build_overview_map") as finto:
            sezioni = pdf_extras.build_pdf_sections(
                {"days": []}, _TripFinto(), None,
                include_overview_map=False, include_day_maps=False,
                include_directions=False, include_costs=False, include_tips=False,
                include_place_links=False, include_predeparture=False,
                include_vademecum=False, include_checklist_sheet=False,
            )
        finto.assert_not_called()
        self.assertIsNone(sezioni["overview_map"])


def _png_finto(larghezza: int, altezza: int) -> bytes:
    """I primi 24 byte di un PNG: firma, lunghezza del blocco, `IHDR`,
    larghezza e altezza. Al renderer non serve altro — legge le misure da qui
    per sapere che forma ha l'immagine, e il resto lo ricopia in base64 senza
    guardarlo. Costruirlo a mano evita di dipendere da Pillow nei test."""
    return (
        b"\x89PNG\r\n\x1a\n"
        + (13).to_bytes(4, "big") + b"IHDR"
        + larghezza.to_bytes(4, "big") + altezza.to_bytes(4, "big")
    )


class TestLaCartinaSiPuoCliccare(unittest.TestCase):
    """Richiesta di Lorenzo del 2026-08-03: «la cartina deve essere
    interattiva, ci puoi cliccare e li trovi tutto quello inerente a quello
    (orari, biglietti, info, guida turistica, come arrivare) […] come se fosse
    uno zoom out dal macro al micro».

    Il rischio di questa funzione non è che non funzioni: è che funzioni a
    metà e non si veda. Una zona cliccabile è invisibile per costruzione,
    quindi un link che punta a un'ancora inesistente, o una zona spostata di
    dieci punti percentuali, o un pallino promesso cliccabile e inerte
    passerebbero il collaudo a vista senza che nessuno se ne accorga — e il
    cliente ci arriverebbe prima di noi.
    """

    def _piano(self):
        return {
            "png": _png_finto(1280, 876),
            "map_source": "schema",
            "stops": [
                {"poi_id": "P1", "name": "Duomo", "label": "1"},
                {"poi_id": "P2", "name": "Fortezza", "label": "2"},
            ],
            "pins": [
                {"label": "H", "poi_id": None, "x_pct": 50.0, "y_pct": 50.0, "r_pct": 2.0},
                {"label": "1", "poi_id": "P1", "x_pct": 30.0, "y_pct": 40.0, "r_pct": 2.0},
                {"label": "2", "poi_id": "P2", "x_pct": 70.0, "y_pct": 60.0, "r_pct": 2.0},
            ],
        }

    def _documento(self, guides=None, guide_urls=None):
        return render_html(
            {"days": []}, {"destination": "Siena"},
            overview_map=self._piano(),
            guides=guides if guides is not None else [
                {"poi_id": "P1", "poi_name": "Duomo", "title": "Il Duomo"},
            ],
            guide_urls=guide_urls,
            poi=[{"id": "P1", "name": "Duomo"}, {"id": "P2", "name": "Fortezza"}],
        )

    def test_il_pallino_con_la_guida_diventa_cliccabile(self):
        out = self._documento()
        self.assertIn("map-clickable", out)
        self.assertIn("class='map-hit'", out)

    def test_il_pallino_senza_destinazione_resta_muto(self):
        """P2 non ha guida e l'albergo non è un'attrazione: promettere un
        click che non porta da nessuna parte è peggio del pallino muto."""
        out = self._documento()
        self.assertEqual(out.count("class='map-hit'"), 1)

    def test_senza_nessuna_guida_non_esce_nessuna_zona_cliccabile(self):
        out = self._documento(guides=[])
        # Sul marcatore COMPLETO, non sul solo nome della classe: la regola
        # di stile `.map-hit { … }` sta nel foglio di stile in cima al
        # documento e c'e' sempre. Un controllo sul nome nudo passerebbe
        # sempre e non direbbe niente.
        self.assertNotIn("class='map-hit'", out)
        # …e soprattutto la cartina esce lo stesso: l'interattività è un
        # miglioramento, non una condizione per vedere la figura.
        self.assertIn("map-image", out)

    def test_la_zona_cliccabile_e_quadrata_sulla_carta_non_in_percentuale(self):
        """Le percentuali orizzontali e verticali si riferiscono a due lati
        diversi della stessa immagine: usare lo stesso numero per entrambe
        darebbe un rettangolo schiacciato, spostato rispetto al pallino
        proprio nella direzione in cui l'immagine è più lunga."""
        import re
        from src import pdf_renderer
        html = pdf_renderer._render_map_hits(
            self._piano(), _png_finto(1280, 876),
            {"P1": {"href": "#guida-duomo", "titolo": "Duomo"}},
        )
        larg = float(re.search(r"width:([\d.]+)%", html).group(1))
        alt = float(re.search(r"height:([\d.]+)%", html).group(1))
        lato_x = larg / 100 * 1280
        lato_y = alt / 100 * 876
        self.assertAlmostEqual(lato_x, lato_y, delta=1.0)

    def test_la_zona_non_esce_mai_dai_bordi_dellimmagine(self):
        import re
        from src import pdf_renderer
        piano = self._piano()
        # Pallino appiccicato all'angolo: senza il taglio la zona uscirebbe.
        piano["pins"] = [
            {"label": "1", "poi_id": "P1", "x_pct": 0.0, "y_pct": 100.0, "r_pct": 3.0},
        ]
        html = pdf_renderer._render_map_hits(
            piano, _png_finto(1280, 876),
            {"P1": {"href": "#guida-duomo", "titolo": "Duomo"}},
        )
        valori = {k: float(v) for k, v in re.findall(r"(left|top|width|height):([\d.]+)%", html)}
        self.assertGreaterEqual(valori["left"], 0.0)
        self.assertGreaterEqual(valori["top"], 0.0)
        self.assertLessEqual(valori["left"] + valori["width"], 100.01)
        self.assertLessEqual(valori["top"] + valori["height"], 100.01)

    def test_senza_geometria_dei_pallini_non_si_indovina(self):
        """Se il piano non dice dove sono finiti i pallini — succede con le
        vecchie cartine scaricate già disegnate da Google — non si appoggia
        NIENTE sopra: una zona cliccabile nel posto sbagliato manda il
        cliente sulla guida di un'altra attrazione."""
        from src import pdf_renderer
        piano = self._piano()
        piano.pop("pins")
        self.assertEqual(
            pdf_renderer._render_map_hits(
                piano, _png_finto(1280, 876), {"P1": {"href": "#x"}}
            ),
            "",
        )

    def test_anche_la_riga_di_legenda_porta_alla_guida(self):
        """Centrare il dito su un pallino di sei millimetri è difficile su un
        telefono e impossibile su carta: il nome scritto per esteso è il
        bersaglio che funziona davvero."""
        out = render_html(
            {"days": [{"day": 1, "title": "Centro", "blocks": []}]},
            {"destination": "Siena"},
            day_maps=[{
                "day": 1, "title": "Centro", "png": _png_finto(1280, 876),
                "map_source": "schema", "hotel_point": None,
                "stops": [{"poi_id": "P1", "name": "Duomo", "label": "1"}],
                "pins": [{"label": "1", "poi_id": "P1", "x_pct": 30.0,
                          "y_pct": 40.0, "r_pct": 2.0}],
            }],
            guides=[{"poi_id": "P1", "poi_name": "Duomo", "title": "Il Duomo"}],
            poi=[{"id": "P1", "name": "Duomo"}],
        )
        self.assertIn("legend-link", out)

    def test_il_link_del_pallino_punta_a_unancora_che_esiste_davvero(self):
        """Un rimando interno a un'ancora inesistente in un PDF non dà
        errore: semplicemente non succede niente al click. È il difetto più
        difficile da vedere e il più frustrante da subire."""
        import re
        out = self._documento()
        destinazione = re.search(r"class='map-hit' href='#([^']+)'", out).group(1)
        # `_anchor()` stampa il punto di atterraggio come `id`; il PDF ci
        # arriva perche' `src/pdf_links.py` riscrive i rimandi interni dopo
        # la stampa usando la sonda che l'ancora si porta dietro.
        self.assertIn(f"id='{destinazione}'", out)

    def test_niente_indirizzi_non_cifrati_nemmeno_qui(self):
        out = self._documento(guide_urls={"P1": "http://esempio.invalid/g.pdf"})
        self.assertNotIn("http://", out)


class TestDoveVaAFinireIlClick(unittest.TestCase):
    """`_costruisci_pin_targets()` decide UNA cosa: se la guida di
    quell'attrazione è un documento a sé ospitato su Render o un capitolo di
    questo stesso PDF. Le due strade non devono convivere per caso."""

    def _costruisci(self, **kwargs):
        from src import pdf_renderer
        return pdf_renderer._costruisci_pin_targets(**kwargs)

    def test_di_norma_si_resta_dentro_il_documento(self):
        bersagli = self._costruisci(
            guide_anchors={"P1": "guida-duomo"},
            poi_by_id={"P1": {"name": "Duomo"}},
        )
        self.assertEqual(bersagli["P1"]["href"], "#guida-duomo")
        self.assertEqual(bersagli["P1"]["modo"], "interno")
        self.assertEqual(bersagli["P1"]["titolo"], "Duomo")

    def test_se_la_guida_e_un_documento_a_se_vince_quella(self):
        bersagli = self._costruisci(
            guide_anchors={"P1": "guida-duomo"},
            poi_by_id={"P1": {"name": "Duomo"}},
            guide_urls={"P1": "https://esempio.invalid/guide/duomo.pdf"},
        )
        self.assertEqual(bersagli["P1"]["href"], "https://esempio.invalid/guide/duomo.pdf")
        self.assertEqual(bersagli["P1"]["modo"], "documento")

    def test_un_indirizzo_non_cifrato_viene_scartato_non_stampato(self):
        bersagli = self._costruisci(
            guide_anchors={"P1": "guida-duomo"},
            poi_by_id={},
            guide_urls={"P1": "http://esempio.invalid/g.pdf"},
        )
        self.assertEqual(bersagli["P1"]["href"], "#guida-duomo")

    def test_senza_guide_non_si_inventa_nessuna_destinazione(self):
        self.assertEqual(self._costruisci(guide_anchors=None, poi_by_id=None), {})


class TestNonSiPagaGoogleDueVoltePerLaStessaFigura(unittest.TestCase):
    """La cartina d'insieme si può chiedere da due porte diverse:
    `build_pdf_extras(include_map=...)` (la vecchia, byte nudi) e
    `build_pdf_sections(include_overview_map=...)` (la nuova, con piano e rete
    di sicurezza). Accenderle tutte e due significa pagare Google due volte a
    ogni vendita e allungare l'esecuzione, che è già vicina al tetto dei 300
    secondi di Make. Il documento verrebbe fuori identico, quindi l'errore non
    si vedrebbe: per questo il controllo sta qui e non nell'occhio di nessuno.
    """

    def _sorgente(self, nome: str) -> str:
        return (RADICE / nome).read_text(encoding="utf-8")

    def test_il_servizio_http_spegne_la_strada_vecchia(self):
        testo = self._sorgente("service.py")
        self.assertIn("include_map=False", testo)
        self.assertIn("include_overview_map=include_map", testo)
        self.assertNotIn("include_map=include_map", testo)

    def test_il_cli_spegne_la_strada_vecchia(self):
        testo = self._sorgente("main.py")
        self.assertIn("include_map=False", testo)
        self.assertNotIn("include_map=True", testo)


class _TripFinto:
    """Il minimo che `build_pdf_sections()` legge da un viaggio."""
    email = "x@example.com"
    destination = "Siena"
    date_start = "2026-09-10"
    date_end = "2026-09-12"
    duration_days = 2
    budget_eur = 500
    budget_mode = "total"
    objective_function = "balanced"
    raw_notes = ""
    dest_lat = 43.32
    dest_lng = 11.33

    def to_dict(self):
        return {
            "email": self.email, "destination": self.destination,
            "date_start": self.date_start, "date_end": self.date_end,
            "duration_days": self.duration_days, "budget_eur": self.budget_eur,
        }


if __name__ == "__main__":
    unittest.main()
