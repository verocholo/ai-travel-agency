"""
[NUOVO 2026-07-11 — richiesta di Lorenzo: "facciamo tutto ciò che è
necessario per avere un prodotto ottimo, prima di andare su Make.com"]
Copre src/pdf_renderer.py: render_html() (funzione pura, testata come
qualunque generatore di testo/markup) e render_pdf() (invoca il binario
esterno wkhtmltopdf — testato sia in modo "unit" con subprocess mockato,
sia con un test di integrazione reale che genera davvero un PDF, perché
wkhtmltopdf è confermato presente in QUESTO ambiente sandbox — vedi la
nota di onestà in src/pdf_renderer.py sul fatto che questo non è ancora
stato verificato sul PC Windows di Lorenzo).
"""
import multiprocessing
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from src import pdf_renderer
from src.pdf_renderer import render_html, render_pdf, PdfRendererError, _build_poi_energy_lookup

TRIP = {
    "destination": "Roma",
    "objective_function": "BALANCED",
    "date_start": "2026-09-01",
    "date_end": "2026-09-04",
    "duration_days": 3,
    "budget_mode": "UNLIMITED",
    "budget_eur": 0,
}


def _concurrent_render_worker(itinerary, trip, output_path):
    """Funzione a livello di modulo (necessaria per essere pickle-abile da
    multiprocessing) usata dal test di stress sulla scrittura atomica."""
    try:
        render_pdf(itinerary, trip, output_path=output_path)
        return True
    except Exception:
        return False


class TestRenderHtml(unittest.TestCase):
    def test_basic_html_includes_destination_and_summary(self):
        itinerary = {"destination": "Roma", "executive_summary": "Un bel viaggio.", "days": []}
        out = render_html(itinerary, TRIP)
        self.assertIn("Roma", out)
        self.assertIn("Un bel viaggio.", out)
        self.assertIn("<!DOCTYPE html>", out)
        self.assertIn("<style>", out)

    def test_output_is_self_contained_no_external_resources(self):
        # Nessun CDN/font remoto: il PDF deve poter essere generato anche
        # offline (wkhtmltopdf senza accesso di rete).
        itinerary = {"destination": "Roma", "executive_summary": "x", "days": []}
        out = render_html(itinerary, TRIP)
        self.assertNotIn("http://", out)
        self.assertNotIn("https://cdn", out)
        self.assertNotIn("fonts.googleapis", out)

    def test_budget_alert_rendered_when_present(self):
        itinerary = {
            "destination": "Roma", "executive_summary": "x", "days": [],
            "budget_alert": "Budget insufficiente per l'hotel richiesto.",
        }
        out = render_html(itinerary, TRIP)
        self.assertIn("Avviso Budget", out)
        self.assertIn("Budget insufficiente", out)

    def test_no_budget_alert_when_absent(self):
        itinerary = {"destination": "Roma", "executive_summary": "x", "days": []}
        out = render_html(itinerary, TRIP)
        self.assertNotIn("Avviso Budget", out)

    def test_days_and_blocks_rendered(self):
        itinerary = {
            "destination": "Roma", "executive_summary": "x",
            "days": [{"day": 1, "title": "Arrivo", "blocks": [
                {"time": "09:00", "activity": "Colosseo", "location": "Roma", "poi_id": "POI1",
                 "logistics": "15 min a piedi"},
            ]}],
        }
        out = render_html(itinerary, TRIP)
        self.assertIn("Giorno 1", out)
        self.assertIn("Colosseo", out)
        self.assertIn("09:00", out)
        self.assertIn("15 min a piedi", out)

    def test_poi_id_not_leaked_into_customer_document(self):
        # [DELIBERATO] A differenza di renderer.py (Markdown, uso interno
        # di revisione), il PDF cliente non deve mostrare il marcatore
        # grezzo di grounding `poi_id`.
        itinerary = {
            "destination": "Roma", "executive_summary": "x",
            "days": [{"day": 1, "title": "Arrivo", "blocks": [
                {"time": "09:00", "activity": "Colosseo", "location": "Roma", "poi_id": "POI1"},
            ]}],
        }
        out = render_html(itinerary, TRIP)
        self.assertNotIn("POI1", out)
        self.assertNotIn("SLOT LIBERO", out)

    def test_architect_tips_rendered_when_present(self):
        itinerary = {
            "destination": "Roma", "executive_summary": "x", "days": [],
            "architect_tips": ["Consiglio uno", "Consiglio due"],
        }
        out = render_html(itinerary, TRIP)
        self.assertIn("Architect's Tips", out)
        self.assertIn("Consiglio uno", out)
        self.assertIn("Consiglio due", out)

    def test_hotels_section_rendered_with_platform_links(self):
        hotels = [{"name": "Hotel Roma", "property_type": "Hotels"}]
        itinerary = {"destination": "Roma", "executive_summary": "x", "days": []}
        out = render_html(itinerary, TRIP, hotels=hotels)
        self.assertIn("Confronta anche su altre piattaforme", out)
        self.assertIn("Hotel Roma", out)
        self.assertIn("booking.com", out.lower())

    def test_no_hotels_no_platform_section(self):
        itinerary = {"destination": "Roma", "executive_summary": "x", "days": []}
        out = render_html(itinerary, TRIP)
        self.assertNotIn("Confronta anche su altre piattaforme", out)

    def test_html_special_characters_are_escaped(self):
        # Un'attività con caratteri HTML speciali non deve rompere il markup.
        itinerary = {
            "destination": "Roma", "executive_summary": "x",
            "days": [{"day": 1, "title": "Test", "blocks": [
                {"time": "09:00", "activity": "<script>alert(1)</script>", "location": "A&B", "poi_id": None},
            ]}],
        }
        out = render_html(itinerary, TRIP)
        self.assertNotIn("<script>alert(1)</script>", out)
        self.assertIn("&lt;script&gt;", out)

    def test_zero_days_does_not_crash(self):
        itinerary = {"destination": "Roma", "executive_summary": "x", "days": []}
        out = render_html(itinerary, TRIP)
        self.assertIsInstance(out, str)

    def test_broken_flag_and_skin_tone_emoji_stripped_not_left_broken(self):
        # [REGRESSIONE — secondo audit adversariale 2026-07-11, richiesta
        # di Lorenzo "rendiamolo perfetto"] Verificato dal vivo (rendering
        # reale + screenshot) che wkhtmltopdf mostra le bandiere (coppie di
        # "regional indicator symbol") come lettere in riquadro, e i
        # modificatori di tono della pelle come glifo "tofu" rotto accanto
        # all'emoji base — anche con un font a colori installato (limite
        # del motore WebKit datato, non del font). Qui verifichiamo solo la
        # parte testabile senza wkhtmltopdf: che i codepoint responsabili
        # vengano rimossi dall'HTML prima del rendering.
        itinerary = {
            "destination": "Roma",
            "executive_summary": "Bandiera \U0001F1EE\U0001F1F9 e mano \U0001F44D\U0001F3FD, semplice ⚠",
            "days": [],
        }
        out = render_html(itinerary, TRIP)
        self.assertNotIn("\U0001F1EE\U0001F1F9", out)  # regional indicator pair (bandiera)
        self.assertNotIn("\U0001F3FD", out)  # modificatore di tono della pelle
        self.assertIn("\U0001F44D", out)  # l'emoji base (mano) resta
        self.assertIn("⚠", out)  # l'emoji semplice non viene toccata

    def test_oversized_day_split_into_multiple_titled_cards(self):
        # [REGRESSIONE — secondo audit adversariale 2026-07-11] Un giorno
        # con molti blocchi (verificato dal vivo con un rendering PDF reale
        # a 60 blocchi: senza questo fix, il day-card superava un'intera
        # pagina A4 e il titolo del giorno non si ripeteva nella pagina di
        # continuazione) viene ora spezzato in più `.day-card`, ciascuna
        # con il proprio titolo — le successive marcate "(continua)".
        blocks = [
            {"time": f"{9 + i % 12:02d}:00", "activity": f"Attività {i}", "location": "Roma"}
            for i in range(45)
        ]
        itinerary = {
            "destination": "Roma", "executive_summary": "x",
            "days": [{"day": 1, "title": "Giorno mega", "blocks": blocks}],
        }
        out = render_html(itinerary, TRIP)
        self.assertEqual(out.count("class='day-card'"), 3)  # 45 blocchi / 20 per card = 3
        self.assertEqual(out.count("(continua)"), 2)  # tutte tranne la prima
        # Nessun blocco perso nello split.
        for i in range(45):
            self.assertIn(f"Attività {i}", out)

    def test_normal_sized_day_not_split(self):
        # Non-regressione: un giorno normale (sotto soglia) resta in
        # un'unica card, senza suffisso "(continua)".
        blocks = [
            {"time": "09:00", "activity": "Colosseo", "location": "Roma"},
            {"time": "14:00", "activity": "Foro Romano", "location": "Roma"},
        ]
        itinerary = {
            "destination": "Roma", "executive_summary": "x",
            "days": [{"day": 1, "title": "Arrivo", "blocks": blocks}],
        }
        out = render_html(itinerary, TRIP)
        self.assertEqual(out.count("class='day-card'"), 1)
        self.assertNotIn("(continua)", out)

    # -- Difetti grafici trovati ispezionando il PDF di esempio (2026-07-31) --
    # Tutti e tre nascono dalla stessa richiesta di Lorenzo ("migliorare la
    # parte grafica, il pdf in sé deve essere accattivante, bello da vedere
    # e facile da comprendere") e tutti e tre sono stati visti su un PDF
    # vero, non dedotti leggendo il codice.

    def test_day_card_does_not_force_its_own_page(self):
        # Il programma di una giornata NON deve essere tenuto insieme a
        # forza: quando cartina + blocchi + "Come arrivare" non entravano in
        # una pagina, wkhtmltopdf spostava tutto alla pagina dopo lasciando
        # ~metà pagina bianca sotto ogni cartina (3 pagine su 14 sprecate nel
        # PDF di esempio). La regola "non spezzare" appartiene al singolo
        # blocco orario, che tagliato a metà fra due pagine è illeggibile.
        css = pdf_renderer._CSS
        day_card_rule = css.split(".day-card {", 1)[1].split("}", 1)[0]
        self.assertNotIn("page-break-inside", day_card_rule)
        block_rule = css.split("\n    .block {", 1)[1].split("}", 1)[0]
        self.assertIn("page-break-inside: avoid", block_rule)

    def test_cover_lists_only_the_sections_actually_generated(self):
        # La copertina riempiva un terzo di pagina: i due terzi bianchi sotto
        # sono la prima cosa che vede chi ha appena pagato. Ora ospita "Cosa
        # troverai dentro" — che però deve elencare SOLO le sezioni davvero
        # prodotte: promettere in copertina un capitolo assente sarebbe un
        # bug visibile al cliente esattamente come un indice rotto.
        itinerary = {
            "destination": "Roma", "executive_summary": "x",
            "days": [{"day": 1, "title": "Arrivo", "blocks": [
                {"time": "09:00", "activity": "Colosseo", "location": "Roma"},
            ]}],
        }
        out = render_html(itinerary, TRIP)
        cover = out.split("class='cover'", 1)[1].split("class='toc'", 1)[0]
        self.assertIn("Cosa troverai dentro", cover)
        self.assertIn("Il programma, giorno per giorno", cover)
        # Nessun costo/consiglio/guida è stato passato al renderer: quelle
        # voci non devono comparire in copertina.
        self.assertNotIn("Stima dei costi", cover)
        self.assertNotIn("Guide turistiche tascabili", cover)

    def test_cover_strip_omitted_when_there_is_almost_nothing_to_list(self):
        # Con una sola sezione la striscia a due colonne sarebbe sbilanciata
        # e peggiorerebbe l'impaginazione invece di migliorarla: meglio non
        # stamparla. (Un itinerario senza giorni produce il solo "colpo
        # d'occhio".)
        out = render_html({"destination": "Roma", "executive_summary": "x", "days": []}, TRIP)
        cover = out.split("class='cover'", 1)[1].split("class='toc'", 1)[0]
        self.assertNotIn("Cosa troverai dentro", cover)

    def test_no_duplicate_google_maps_link_when_place_card_exists(self):
        # Ogni blocco mostrava DUE pulsanti quasi identici verso Google Maps:
        # quello della scheda luogo ("Info, orari e recensioni", che oltre
        # alla posizione dà orari e recensioni) e quello generico costruito
        # sulle sole coordinate. Vince la scheda, che è strettamente più
        # utile; il link generico resta solo per i POI senza scheda.
        itinerary = {
            "destination": "Roma", "executive_summary": "x",
            "days": [{"day": 1, "title": "Arrivo", "blocks": [
                {"time": "09:00", "activity": "Colosseo", "location": "Roma", "poi_id": "POI1"},
                {"time": "14:00", "activity": "Foro", "location": "Roma", "poi_id": "POI2"},
            ]}],
        }
        poi = [
            {"id": "POI1", "type": "museum", "name": "Colosseo", "lat": 41.89, "lng": 12.49},
            {"id": "POI2", "type": "activity", "name": "Foro", "lat": 41.892, "lng": 12.485},
        ]
        place_cards = {
            "POI1": {
                "poi_id": "POI1", "name": "Colosseo", "address": None, "phone": None,
                "menu_link": None,
                "info_link": {"url": "https://maps.google.com/?cid=1",
                              "label": "Info, orari e recensioni", "is_search": False},
            },
            # POI2 volutamente senza scheda: deve conservare il link generico.
        }
        out = render_html(itinerary, TRIP, poi=poi, place_cards=place_cards)
        block1 = out.split("Colosseo (Roma)", 1)[1].split("</div><div class='block'>", 1)[0]
        self.assertIn("Info, orari e recensioni", block1)
        self.assertNotIn("block-maps-link", block1)
        block2 = out.split("Foro (Roma)", 1)[1].split("</div></div>", 1)[0]
        self.assertIn("block-maps-link", block2)

    def test_header_meta_uses_solid_opaque_color_no_alpha_channel(self):
        # Bug reale trovato il 2026-07-12 durante la prima verifica dal vivo
        # su Windows (PC di Lorenzo), in DUE round successivi: (1) CSS
        # `opacity` su `.header .meta` produceva testo "fantasma/sdoppiato"
        # illeggibile (confermato da screenshot reale) su quella build di
        # wkhtmltopdf, mentre lo stesso testo bianco senza `opacity` (l'H1
        # sopra) restava nitido; (2) il fix iniziale (stessa trasparenza via
        # canale alpha di `rgba(255,255,255,0.85)`) ha fatto SPARIRE
        # completamente la riga — quella build gestisce male anche l'alpha
        # in rgba(), non solo `opacity`. Fix definitivo: nessuna forma di
        # trasparenza, un colore pieno e opaco (`#d7e6f5`, un azzurro molto
        # chiaro) — a prova di qualunque bug di compositing su motori
        # datati. Questo test blocca la regressione: fallisce se `opacity`
        # o un canale alpha rgba/rgb() con 4 argomenti ricompaiono nel CSS.
        itinerary = {"destination": "Roma", "executive_summary": "x", "days": []}
        out = render_html(itinerary, TRIP)
        self.assertNotIn("opacity", out)
        self.assertNotIn("rgba(", out)
        self.assertIn("#d7e6f5", out)

    def test_header_uses_solid_background_color_no_gradient(self):
        # Bug reale trovato il 2026-07-12 durante la prima verifica dal vivo
        # su Windows (PC di Lorenzo), TERZO giro: la causa reale di entrambi
        # i round precedenti (testo "fantasma" con `opacity`, poi sparito
        # con `rgba()`) non era il colore del testo ma lo SFONDO — il
        # `linear-gradient` di `.header` non si renderizzava affatto su
        # quella build di wkhtmltopdf, lasciando lo sfondo bianco
        # (confermato con uno screenshot reale: testo chiaro quasi
        # invisibile su bianco, non su blu scuro). Fix: sfondo a colore
        # pieno e solido, niente più `linear-gradient` — universalmente
        # supportato anche dai motori di rendering più datati. Questo test
        # blocca la regressione: fallisce se `linear-gradient` ricompare
        # nel CSS del documento.
        itinerary = {"destination": "Roma", "executive_summary": "x", "days": []}
        out = render_html(itinerary, TRIP)
        self.assertNotIn("linear-gradient", out)
        self.assertIn("background-color: #1a3b5c", out)


class TestAtAGlanceHotelPriceCuratedSectionsAndMap(unittest.TestCase):
    """
    [AGGIUNTO 2026-07-12 — richiesta di Lorenzo: "layout migliore/
    infografica", "cartina + percorsi", "ristoranti/hotel/intrattenimento
    in funzione del tipo di vacanza", "segnare ogni costo (hotel,
    ristoranti)"] Copre i nuovi parametri opzionali `poi`/`map_png_bytes`
    di `render_html()` e le sezioni aggiuntive che abilitano.
    """

    def _itinerary(self, **overrides):
        base = {
            "destination": "Roma",
            "executive_summary": "Un bel viaggio.",
            "days": [
                {"day": 1, "title": "Arrivo", "blocks": [
                    {"time": "09:00", "activity": "Check-in", "location": "Hotel", "poi_id": "H1"},
                ]},
                {"day": 2, "title": "Museo", "blocks": [
                    {"time": "10:00", "activity": "Museo del Vino", "location": "Museo", "poi_id": "POI3"},
                ]},
            ],
        }
        base.update(overrides)
        return base

    def test_at_a_glance_page_present_with_stat_tiles(self):
        out = render_html(self._itinerary(), TRIP)
        self.assertIn("colpo d'occhio", out.lower())
        self.assertIn("at-a-glance-page", out)
        self.assertIn("Destinazione", out)
        self.assertIn("Roma", out)
        self.assertIn("3 giorni", out)

    def test_at_a_glance_day_strip_lists_every_day_title_only(self):
        out = render_html(self._itinerary(), TRIP)
        self.assertIn("Giorno 1", out)
        self.assertIn("Arrivo", out)
        self.assertIn("Giorno 2", out)
        self.assertIn("Museo", out)

    def test_at_a_glance_shows_first_hotel_name_when_provided(self):
        hotels = [{"name": "Hotel Bello", "property_type": "Hotels", "price_night_eur": 120.0}]
        out = render_html(self._itinerary(), TRIP, hotels=hotels)
        self.assertIn("Alloggio", out)
        self.assertIn("Hotel Bello", out)

    def test_full_day_by_day_detail_still_present_after_at_a_glance(self):
        # La pagina di sintesi si AGGIUNGE, non sostituisce il dettaglio
        # giorno-per-giorno completo (interpretazione dichiarata a Lorenzo).
        out = render_html(self._itinerary(), TRIP)
        self.assertIn("class='day-card'", out)
        self.assertIn("Check-in", out)
        self.assertIn("Museo del Vino", out)

    def test_hotel_price_per_night_shown(self):
        hotels = [{"name": "Hotel Bello", "property_type": "Hotels", "price_night_eur": 120.0}]
        out = render_html(self._itinerary(), TRIP, hotels=hotels)
        self.assertIn("120.0€/notte", out)

    def test_hotel_without_price_omits_price_suffix_not_a_fake_number(self):
        hotels = [{"name": "Hotel Senza Prezzo", "property_type": "Hotels", "price_night_eur": None}]
        out = render_html(self._itinerary(), TRIP, hotels=hotels)
        self.assertIn("Hotel Senza Prezzo", out)
        self.assertNotIn("None€/notte", out)

    def test_curated_restaurant_section_rendered_with_price_badge(self):
        poi = [{"id": "POI1", "type": "restaurant", "name": "Trattoria Toscana", "price_level": "MODERATE"}]
        out = render_html(self._itinerary(), TRIP, poi=poi)
        self.assertIn("Dove mangiare", out)
        self.assertIn("Trattoria Toscana", out)
        # [CORRETTO 2026-07-13 — audit di revisione completa, gap di
        # mutation-testing trovato dall'agente di audit qualità test]
        # `assertIn("€€", out)` è debole: combacerebbe anche con "€€€"
        # (EXPENSIVE) o "€€€€" (VERY_EXPENSIVE) — non avrebbe rilevato una
        # mutazione che restituisse il simbolo di fascia sbagliata. Il
        # badge HTML esatto delimita il simbolo dentro `</span>` (vedi
        # pdf_renderer.py riga 367), quindi confrontiamo il markup intero.
        self.assertIn("<span class='price-badge'>€€</span>", out)
        self.assertNotIn("<span class='price-badge'>€€€</span>", out)

    def test_curated_activity_section_grouped_under_cosa_fare(self):
        poi = [
            {"id": "POI3", "type": "museum", "name": "Museo del Vino", "price_level": "INEXPENSIVE"},
            {"id": "POI4", "type": "activity", "name": "Escursione Guidata", "price_level": None},
        ]
        out = render_html(self._itinerary(), TRIP, poi=poi)
        self.assertIn("Cosa fare", out)
        self.assertIn("Museo del Vino", out)
        self.assertIn("Escursione Guidata", out)

    def test_poi_without_price_level_shows_no_fake_badge(self):
        poi = [{"id": "POI4", "type": "activity", "name": "Escursione Guidata", "price_level": None}]
        out = render_html(self._itinerary(), TRIP, poi=poi)
        self.assertIn("Escursione Guidata</div>", out)  # nessun <span class='price-badge'> annidato

    def test_no_poi_no_curated_sections(self):
        out = render_html(self._itinerary(), TRIP)
        self.assertNotIn("Dove mangiare", out)
        self.assertNotIn("Cosa fare", out)
        self.assertNotIn("Shopping", out)

    def test_curated_shopping_section_grouped_separately_from_cosa_fare(self):
        # [AGGIUNTO 2026-07-13 (ter) — categoria shopping, confermata come
        # miglioramento generale di prodotto via AskUserQuestion] Un POI
        # type="shopping" deve finire nella sua sezione dedicata, non in
        # "Cosa fare" (dove sarebbe finito prima di questa modifica, dato
        # che "Cosa fare" era "tutto ciò che non è restaurant").
        poi = [
            {"id": "POI5", "type": "shopping", "name": "Mercato di San Lorenzo", "price_level": None},
            {"id": "POI3", "type": "museum", "name": "Museo del Vino", "price_level": None},
        ]
        out = render_html(self._itinerary(), TRIP, poi=poi)
        self.assertIn("Shopping", out)
        self.assertIn("Mercato di San Lorenzo", out)
        self.assertIn("Cosa fare", out)
        self.assertIn("Museo del Vino", out)
        # Il mercato compare nella sezione Shopping, non in Cosa fare —
        # verificato confrontando le posizioni dei due marker di sezione.
        shopping_idx = out.index("<div class='section-title'>Shopping</div>")
        cosa_fare_idx = out.index("<div class='section-title'>Cosa fare</div>")
        mercato_idx = out.index("Mercato di San Lorenzo")
        self.assertTrue(shopping_idx < mercato_idx < cosa_fare_idx)

    def test_map_embedded_as_base64_when_bytes_provided(self):
        out = render_html(self._itinerary(), TRIP, map_png_bytes=b"FAKE_PNG_BYTES")
        self.assertIn("data:image/png;base64,", out)
        self.assertIn("La tua mappa", out)

    def test_no_map_section_when_bytes_absent(self):
        out = render_html(self._itinerary(), TRIP)
        self.assertNotIn("La tua mappa", out)
        self.assertNotIn("data:image/png;base64,", out)

    def test_map_disclaimer_present_when_map_shown(self):
        # Onestà sui limiti: le linee sono rette, non un vero percorso di
        # guida — deve essere dichiarato nel documento, non lasciato
        # implicito.
        out = render_html(self._itinerary(), TRIP, map_png_bytes=b"FAKE_PNG_BYTES")
        self.assertIn("non un percorso di guida calcolato", out)


class TestBuildPoiEnergyLookup(unittest.TestCase):
    """[AGGIUNTO 2026-07-13 — audit di revisione completa, miglioramento
    di prodotto: barra del ritmo energetico giornaliero nel PDF cliente]
    Test unitari diretti su `_build_poi_energy_lookup()`, la funzione pura
    che isola la logica di mapping id->energy_tag dal rendering HTML."""

    def test_none_poi_returns_empty_dict(self):
        self.assertEqual(_build_poi_energy_lookup(None), {})

    def test_empty_list_returns_empty_dict(self):
        self.assertEqual(_build_poi_energy_lookup([]), {})

    def test_builds_id_to_energy_tag_mapping(self):
        poi = [
            {"id": "P1", "energy_tag": "HIGH"},
            {"id": "P2", "energy_tag": "LOW"},
        ]
        self.assertEqual(_build_poi_energy_lookup(poi), {"P1": "HIGH", "P2": "LOW"})

    def test_poi_without_id_skipped(self):
        # Difesa in profondità: un POI malformato senza 'id' non deve
        # produrre una entry con chiave None nel lookup.
        poi = [{"energy_tag": "HIGH"}, {"id": "P2", "energy_tag": "LOW"}]
        self.assertEqual(_build_poi_energy_lookup(poi), {"P2": "LOW"})


class TestEnergyChips(unittest.TestCase):
    """[AGGIUNTO 2026-07-13 — audit di revisione completa, richiesta
    esplicita di Lorenzo: "aggiungi qualsiasi tipo di miglioramento:
    grafico di contenuto... per rendere il lavoro ancor più completo"]
    [SOSTITUITO 2026-07-13 (bis) — bug reale trovato da Lorenzo leggendo
    un vero PDF: la prima versione (`TestEnergyPacingBar`, una barra di
    pallini in cima al giorno con l'unico testo leggibile chiuso in un
    attributo HTML `title`) era invisibile in un documento PDF statico —
    un `title` è un tooltip che appare solo al passaggio del mouse in un
    browser, non in un file stampato/esportato. Questi test coprono la
    versione corretta: un chip testuale (colore + etichetta SEMPRE
    visibile, non in un attributo) agganciato al singolo blocco a cui si
    riferisce.] Copre l'integrazione end-to-end in `render_html()`: un
    chip per blocco con `energy_tag` reale noto, nessun chip per blocchi
    senza un id riconosciuto — mai un dato inventato."""

    def _itinerary(self, **overrides):
        base = {
            "destination": "Roma",
            "executive_summary": "Un bel viaggio.",
            "days": [
                {"day": 1, "title": "Arrivo", "blocks": [
                    {"time": "09:00", "activity": "Check-in", "location": "Hotel", "poi_id": "H1"},
                    {"time": "15:00", "activity": "Museo del Vino", "location": "Museo", "poi_id": "POI3"},
                ]},
                {"day": 2, "title": "Riposo", "blocks": [
                    {"time": "09:00", "activity": "Slot libero", "location": "", "poi_id": None},
                ]},
            ],
        }
        base.update(overrides)
        return base

    # NOTA: `_CSS` contiene sempre le regole `.energy-chip`/`.energy-legend`
    # (sono nel <style>, incluso in OGNI documento), e la legenda stessa
    # include sempre un chip di esempio per ciascuno dei tre livelli —
    # quindi un controllo con `assertIn`/`assertNotIn` sulla sola
    # sottostringa "energy-chip"/"energy-legend" darebbe sempre falsi
    # positivi (il CSS statico) o falsi negativi (l'esempio nella
    # legenda). I test sotto usano invece i marcatori ESATTI degli
    # elementi realmente istanziati (`<div class='energy-legend'>`) e,
    # per contare i chip PER BLOCCO (non quello di esempio nella
    # legenda), la sottostringa `<span class='energy-chip ENERGY-XXX'>`
    # (senza `title=`, a differenza della vecchia barra: il chip è nel
    # testo visibile, non in un attributo).

    def test_no_poi_no_energy_chip_no_legend(self):
        out = render_html(self._itinerary(), TRIP)
        self.assertNotIn("<span class='energy-chip", out)
        self.assertNotIn("<div class='energy-legend'>", out)

    def test_chip_shown_for_block_with_known_energy_tag(self):
        poi = [{"id": "POI3", "type": "museum", "name": "Museo del Vino", "energy_tag": "HIGH"}]
        out = render_html(self._itinerary(), TRIP, poi=poi)
        self.assertIn("<span class='energy-chip energy-high'>energia alta</span>", out)

    def test_legend_shown_only_when_energy_data_present(self):
        poi = [{"id": "POI3", "type": "museum", "name": "Museo del Vino", "energy_tag": "HIGH"}]
        out = render_html(self._itinerary(), TRIP, poi=poi)
        self.assertIn("<div class='energy-legend'>", out)
        self.assertIn("energia alta", out)
        self.assertIn("energia media", out)
        self.assertIn("energia bassa", out)

    def test_block_with_unrecognized_or_missing_poi_id_gets_no_placeholder_chip(self):
        # Il blocco "Check-in" (poi_id="H1") non è nella lista `poi`
        # passata (solo hotel/ristoranti/attività REALMENTE forniti come
        # POI, non gli hotel) — deve essere semplicemente omesso, MAI un
        # chip inventato/segnaposto. Stesso per lo "Slot libero"
        # (poi_id=None) del giorno 2.
        poi = [{"id": "POI3", "type": "museum", "name": "Museo del Vino", "energy_tag": "HIGH"}]
        out = render_html(self._itinerary(), TRIP, poi=poi)
        # La legenda usa lo stesso identico markup del chip di esempio,
        # quindi isoliamo la sezione dei day-card (dopo la legenda) prima
        # di contare — un solo chip PER BLOCCO deve comparire lì (quello
        # di POI3), non due (che indicherebbe un chip spurio per il
        # blocco H1 o per lo slot libero senza poi_id).
        day_cards_html = out.split("<div class='day-card'>", 1)[1]
        self.assertEqual(day_cards_html.count("<span class='energy-chip energy-high'>energia alta</span>"), 1)
        self.assertEqual(day_cards_html.count("energy-chip energy-medium"), 0)
        self.assertEqual(day_cards_html.count("energy-chip energy-low"), 0)

    def test_all_three_energy_levels_map_to_distinct_css_classes(self):
        itinerary = {
            "destination": "Roma",
            "executive_summary": "x",
            "days": [{"day": 1, "title": "Giorno intenso", "blocks": [
                {"time": "09:00", "activity": "A", "location": "", "poi_id": "PA"},
                {"time": "12:00", "activity": "B", "location": "", "poi_id": "PB"},
                {"time": "18:00", "activity": "C", "location": "", "poi_id": "PC"},
            ]}],
        }
        poi = [
            {"id": "PA", "type": "activity", "name": "A", "energy_tag": "HIGH"},
            {"id": "PB", "type": "activity", "name": "B", "energy_tag": "MEDIUM"},
            {"id": "PC", "type": "activity", "name": "C", "energy_tag": "LOW"},
        ]
        out = render_html(itinerary, TRIP, poi=poi)
        self.assertIn("<span class='energy-chip energy-high'>energia alta</span>", out)
        self.assertIn("<span class='energy-chip energy-medium'>energia media</span>", out)
        self.assertIn("<span class='energy-chip energy-low'>energia bassa</span>", out)

    def test_unrecognized_energy_tag_value_produces_no_chip_not_a_crash(self):
        # Difesa in profondità: un `energy_tag` con un valore inatteso
        # (non HIGH/MEDIUM/LOW) non deve far crashare il rendering né
        # produrre un chip con una classe CSS inesistente.
        poi = [{"id": "POI3", "type": "museum", "name": "Museo del Vino", "energy_tag": "SCONOSCIUTO"}]
        out = render_html(self._itinerary(), TRIP, poi=poi)
        self.assertNotIn("energy-sconosciuto", out)
        self.assertNotIn("<span class='energy-chip", out)
        # Nessuna legenda "orfana": se nessun chip comparirà davvero da
        # nessuna parte nel documento, non ha senso mostrare la legenda.
        self.assertNotIn("<div class='energy-legend'>", out)


class TestBlockMapsLink(unittest.TestCase):
    """[AGGIUNTO 2026-07-13 (ter) — richiesta di Lorenzo: "i collegamenti
    maps risultano un po' dispersivi", confermata come miglioramento
    generale di prodotto (non specifico al suo viaggio)] Copre
    `_build_location_lookup()`/`_render_maps_link()`: un link diretto
    'apri su Google Maps' per ogni blocco la cui coordinata reale
    (lat/lng, da `hotels`/`poi`) è nota — mai un link costruito su un
    nome/indirizzo indovinato, mai un link per un blocco senza
    coordinate reali disponibili."""

    def _itinerary(self):
        return {
            "destination": "Roma",
            "executive_summary": "x",
            "days": [{"day": 1, "title": "Arrivo", "blocks": [
                {"time": "09:00", "activity": "Check-in", "location": "Hotel", "poi_id": "H1"},
                {"time": "15:00", "activity": "Museo del Vino", "location": "Museo", "poi_id": "POI3"},
                {"time": "18:00", "activity": "Slot libero", "location": "", "poi_id": None},
                {"time": "20:00", "activity": "Sconosciuto", "location": "", "poi_id": "POI-IGNOTO"},
            ]}],
        }

    def test_no_hotels_no_poi_no_links_at_all(self):
        # NOTA: `_CSS` contiene sempre le regole `.block-maps-link` (sono
        # nel <style>, incluso in OGNI documento) — verifichiamo l'assenza
        # dell'elemento realmente istanziato (`<div class='block-maps-link'>`),
        # non della sola sottostringa di classe.
        out = render_html(self._itinerary(), TRIP)
        self.assertNotIn("<div class='block-maps-link'>", out)

    def test_link_shown_for_hotel_and_poi_with_known_coordinates(self):
        hotels = [{"id": "H1", "name": "Hotel Bello", "lat": 41.9, "lng": 12.5}]
        poi = [{"id": "POI3", "type": "museum", "name": "Museo del Vino", "lat": 41.89, "lng": 12.49}]
        out = render_html(self._itinerary(), TRIP, hotels=hotels, poi=poi)
        self.assertIn(
            "<div class='block-maps-link'>"
            "<a href='https://www.google.com/maps/search/?api=1&amp;query=41.9,12.5'>"
            "🗺️ Apri su Google Maps</a></div>",
            out,
        )
        self.assertIn("query=41.89,12.49", out)

    def test_no_link_for_block_without_poi_id_or_with_unknown_id(self):
        hotels = [{"id": "H1", "name": "Hotel Bello", "lat": 41.9, "lng": 12.5}]
        poi = [{"id": "POI3", "type": "museum", "name": "Museo del Vino", "lat": 41.89, "lng": 12.49}]
        out = render_html(self._itinerary(), TRIP, hotels=hotels, poi=poi)
        # Solo 2 link nell'intero documento (H1 e POI3) — nessuno per lo
        # slot libero (poi_id=None) né per l'id sconosciuto (POI-IGNOTO,
        # non presente né tra gli hotel né tra i poi passati).
        self.assertEqual(out.count("<div class='block-maps-link'>"), 2)

    def test_no_crash_when_hotel_or_poi_missing_lat_lng(self):
        # Difesa in profondità: un hotel/poi malformato senza lat/lng non
        # deve far crashare il rendering né produrre un link con
        # coordinate mancanti/None.
        hotels = [{"id": "H1", "name": "Hotel Bello"}]
        out = render_html(self._itinerary(), TRIP, hotels=hotels)
        self.assertNotIn("<div class='block-maps-link'>", out)


class TestGuideAndFeedbackSections(unittest.TestCase):
    """
    [AGGIUNTO 2026-07-12 — richiesta di Lorenzo: "aggiungerli al pdf che si
    genera", chiarita con "Voglio tutti e tre nello stesso PDF"] Copre i
    parametri `guides`/`feedback` di `render_html()`, aggiunti per
    incorporare guide turistiche per-POI e il messaggio di feedback
    post-viaggio nello STESSO documento PDF, invece che solo in file .md
    separati come prima di questa modifica.
    """

    GUIDE = {
        "poi_name": "Terme di San Filippo",
        "title": "Le cascate bianche della Val d'Orcia",
        "history_summary": "Formazioni calcaree naturali note fin dal Medioevo.",
        "practical_tips": ["Porta scarpe antiscivolo", "Arriva presto per evitare la folla"],
        "best_time_to_visit": "Mattina presto o tardo pomeriggio",
        "estimated_visit_duration": "2-3 ore",
        "consiglio_personalizzato": "Perfetto per una pausa rigenerante tra due tappe sportive.",
        "disclaimer": "Orari e accesso possono variare — verificare prima della visita.",
    }

    FEEDBACK = {
        "intro_message": "Che piacere risentirvi!",
        "questions": [
            "Come è andata la sessione termale del Giorno 1?",
            "Il ritmo energetico proposto ha funzionato per voi?",
        ],
        "testimonial_request": "Ci autorizzi a usare le tue parole per una testimonianza pubblica?",
        "closing_message": "Grazie ancora per averci scelto.",
    }

    def _base_itinerary(self):
        return {"destination": "Val d'Orcia", "executive_summary": "x", "days": []}

    def test_no_guides_no_feedback_by_default_no_regression(self):
        # Nessuna sezione aggiuntiva se non esplicitamente richiesta — un
        # chiamante esistente che non passa guides/feedback ottiene
        # esattamente lo stesso HTML di prima di questa modifica. La
        # REGOLA CSS `.page-break` resta sempre nello stylesheet (come
        # ogni altra classe), quindi qui verifichiamo che nessun elemento
        # la USI (`class='page-break'`), non che la parola non compaia
        # mai nell'HTML.
        out = render_html(self._base_itinerary(), TRIP)
        self.assertNotIn("class='page-break'", out)
        self.assertNotIn("Facci sapere com'è andata", out)

    def test_guide_section_rendered_with_all_fields(self):
        out = render_html(self._base_itinerary(), TRIP, guides=[self.GUIDE])
        self.assertIn("Le cascate bianche della Val d&#x27;Orcia", out)
        self.assertIn("Formazioni calcaree naturali note fin dal Medioevo.", out)
        self.assertIn("Porta scarpe antiscivolo", out)
        self.assertIn("Mattina presto o tardo pomeriggio", out)
        self.assertIn("2-3 ore", out)
        self.assertIn("Perfetto per una pausa rigenerante", out)
        self.assertIn("Orari e accesso possono variare", out)
        # [AGGIORNATO 2026-07-31] La guida ora ha una sua classe grafica
        # (`guide-card`) e continua ad applicare la regola condivisa
        # `page-break` — che dal 2026-07-13 significa "non spezzare a metà",
        # non "vai a pagina nuova". È quest'ultima la proprietà che conta:
        # una guida tagliata in due è inutilizzabile davanti al monumento.
        self.assertIn("class='guide-card page-break'", out)

    def test_guide_falls_back_to_poi_name_when_title_missing(self):
        guide = dict(self.GUIDE)
        del guide["title"]
        out = render_html(self._base_itinerary(), TRIP, guides=[guide])
        self.assertIn("Terme di San Filippo", out)

    def test_multiple_guides_each_get_own_page_break_section(self):
        # [AGGIORNATO 2026-07-31] L'etichetta era "Guida turistica:"; Lorenzo
        # ha chiesto esplicitamente la dicitura "guida turistica tascabile"
        # (la stessa che compare sul link dentro il giorno-per-giorno, così
        # il cliente riconosce dove sta atterrando). Cambia la stringa, non
        # il contratto: ogni guida resta una sezione a sé.
        guide2 = dict(self.GUIDE, poi_name="Colosseo", title="Il Colosseo")
        out = render_html(self._base_itinerary(), TRIP, guides=[self.GUIDE, guide2])
        self.assertEqual(out.count("<div class='guide-eyebrow'>Guida turistica tascabile</div>"), 2)
        self.assertEqual(out.count("class='guide-card page-break'"), 2)
        self.assertIn("Il Colosseo", out)

    def test_feedback_section_rendered_with_all_fields(self):
        out = render_html(self._base_itinerary(), TRIP, feedback=self.FEEDBACK)
        self.assertIn("Che piacere risentirvi!", out)
        self.assertIn("Come è andata la sessione termale del Giorno 1?", out)
        self.assertIn("Il ritmo energetico proposto ha funzionato per voi?", out)
        self.assertIn("Ci autorizzi a usare le tue parole", out)
        self.assertIn("Grazie ancora per averci scelto.", out)

    def test_guides_and_feedback_together_both_present(self):
        out = render_html(self._base_itinerary(), TRIP, guides=[self.GUIDE], feedback=self.FEEDBACK)
        self.assertIn("Le cascate bianche", out)
        self.assertIn("Che piacere risentirvi!", out)
        # Entrambe le sezioni devono comparire DOPO la struttura principale
        # dell'itinerario (executive summary), non prima.
        self.assertLess(out.index("executive_summary".replace("_", "-")) if False else out.index("Executive Summary"),
                         out.index("Le cascate bianche"))
        self.assertLess(out.index("Le cascate bianche"), out.index("Che piacere risentirvi!"))

    def test_guide_and_feedback_text_is_escaped(self):
        guide = dict(self.GUIDE, history_summary="<script>alert(1)</script>")
        feedback = dict(self.FEEDBACK, intro_message="<b>ciao</b>")
        out = render_html(self._base_itinerary(), TRIP, guides=[guide], feedback=feedback)
        self.assertNotIn("<script>", out)
        self.assertNotIn("<b>ciao</b>", out)


class TestNewSections2026_07_31(unittest.TestCase):
    """
    [AGGIUNTO 2026-07-31 — blocco di richieste di Lorenzo dopo aver testato
    dal vivo, in Interrail, il PDF generato per sé]

    Copre le sezioni nuove del documento cliente: cartina per giornata con
    legenda numerata, "Come arrivare" spostamento per spostamento, stima dei
    costi, Architect's Tips per direttrici, piani B se piove, menù/info dei
    ristoranti, link interni alle guide tascabili, copertina e indice.

    I fixture qui sotto NON sono inventati a mano: sono l'output reale di
    `maps_static.build_day_map_plans()`, `directions.build_directions_by_day()`,
    `cost_estimator.estimate_costs()` e `place_links.build_place_cards_by_id()`
    su un itinerario di prova, copiato pari pari. Un fixture "verosimile"
    scritto a mano è il modo classico per avere test verdi su una forma di
    dato che in produzione non esiste.
    """

    DAY_MAP = {
        "day": 1,
        "title": "Arrivo",
        "hotel_name": "Hotel Test",
        "png": None,
        "stops": [
            {"label": "1", "time": "09:00", "activity": "Visita", "location": "Colosseo",
             "poi_id": "P1", "type": "museum", "type_label": "Museo / cultura", "color": "orange"},
            {"label": "2", "time": "13:00", "activity": "Pranzo", "location": "Da Mario",
             "poi_id": "P2", "type": "restaurant", "type_label": "Dove mangiare", "color": "green"},
        ],
    }
    DIRECTIONS = [{
        "day": 1, "title": "Arrivo",
        "legs": [
            {"from_label": "H", "from_name": "Hotel Test", "to_label": "1", "to_name": "Colosseo",
             "arrival_time": "09:00", "minutes": 12, "mode": "walking", "mode_label": "a piedi",
             "url": "https://www.google.com/maps/dir/?api=1&origin=41.9,12.5"
                    "&destination=41.89,12.49&travelmode=walking"},
            {"from_label": "1", "from_name": "Colosseo", "to_label": "2", "to_name": "Da Mario",
             "arrival_time": "13:00", "minutes": None, "mode": "walking", "mode_label": "a piedi",
             "url": "https://www.google.com/maps/dir/?api=1&origin=41.89,12.49"
                    "&destination=41.895,12.48&travelmode=walking"},
        ],
    }]
    COST_SUMMARY = {
        "travellers": 1, "nights": 3,
        "lines": [
            {"category": "lodging", "category_label": "Alloggio", "label": "Hotel Test",
             "detail": "3 notti × 100 € a notte (prezzo reale del fornitore)",
             "min_eur": 300.0, "max_eur": 300.0, "known": True},
            {"category": "meals", "category_label": "Pasti e ristoranti", "label": "Da Mario",
             "detail": "fascia di prezzo non fornita — [Da Verificare]",
             "min_eur": None, "max_eur": None, "known": False},
        ],
        "total_min_eur": 300.0, "total_max_eur": 300.0, "unknown_count": 1,
        "budget_eur": 250.0, "budget_verdict": "over",
        "excluded_note": "Non inclusi in questa stima: viaggio di andata e ritorno.",
    }
    TIPS = {
        "sections": [
            {"category_id": "biglietti", "title": "Biglietti e prenotazioni",
             "tips": ["Prenota il Colosseo con almeno due settimane di anticipo."]},
            {"category_id": "risparmio", "title": "Risparmio e pagamenti",
             "tips": ["Le carte estere passano ovunque, ma i bar piccoli preferiscono contanti."]},
        ],
        "rain_plans": [
            {"day": 1, "summary": "Se piove, il pomeriggio si sposta al chiuso.",
             "swaps": [{"replaces": "Passeggiata al Foro", "name": "Musei Capitolini",
                        "poi_id": "P3", "why": "A dieci minuti a piedi e completamente coperto."}]},
        ],
        "dropped_swaps": 0,
    }
    PLACE_CARDS = {
        "P2": {
            "poi_id": "P2", "name": "Da Mario",
            "address": "Via Roma 1", "phone": "+39 06 1234567",
            "menu_link": {"url": "https://damario.example/menu", "label": "Menù del ristorante",
                          "is_search": False},
            "info_link": {"url": "https://www.google.com/maps/search/?api=1&query=41.895,12.48",
                          "label": "Apri in Google Maps", "is_search": False},
        },
    }

    def _itinerary(self):
        return {
            "destination": "Roma",
            "executive_summary": "Tre giorni a Roma.",
            "days": [{"day": 1, "title": "Arrivo", "blocks": [
                {"time": "09:00", "activity": "Visita", "location": "Colosseo", "poi_id": "P1"},
                {"time": "13:00", "activity": "Pranzo", "location": "Da Mario", "poi_id": "P2"},
            ]}],
        }

    # --- Cartina del giorno + legenda numerata ---------------------------
    def test_day_map_legend_names_every_numbered_marker(self):
        # LA richiesta: "non si capisce cosa siano gli indicatori, sarebbe
        # opportuno indicare vicino ad ogni indicatore cosa sono e il numero".
        # Il numero da solo non basta: deve stare accanto al NOME.
        out = render_html(self._itinerary(), TRIP, day_maps=[self.DAY_MAP])
        self.assertIn("<span class='map-pin pin-orange'>1</span>", out)
        self.assertIn("<span class='map-pin pin-green'>2</span>", out)
        self.assertIn("Colosseo", out)
        self.assertIn("Museo / cultura", out)
        self.assertIn("Dove mangiare", out)
        # L'alloggio è il punto di partenza e rientro: senza questa riga il
        # marker "H" resta senza spiegazione, che è il difetto originale.
        self.assertIn("Punto di partenza e rientro", out)

    def test_legend_survives_a_missing_map_image(self):
        # La quota Google si esaurisce, la rete cade. In quel caso il cliente
        # perde la figura ma NON deve perdere l'informazione: la legenda è la
        # risposta vera alla richiesta, l'immagine è il contorno.
        no_png = dict(self.DAY_MAP, png=None)
        out = render_html(self._itinerary(), TRIP, day_maps=[no_png])
        self.assertNotIn("data:image/png;base64", out)
        self.assertIn("map-legend", out)
        self.assertIn("<span class='map-pin pin-orange'>1</span>", out)

    def test_day_map_is_matched_by_day_number_not_by_position(self):
        # Se un giorno non ha cartina, un accoppiamento posizionale
        # stamperebbe la cartina del giorno 2 sotto il titolo del giorno 1 —
        # un errore che il cliente scopre solo in strada, sbagliando strada.
        itinerary = self._itinerary()
        itinerary["days"].append({"day": 2, "title": "Centro", "blocks": [
            {"time": "10:00", "activity": "Giro", "location": "Trastevere", "poi_id": "P9"},
        ]})
        day2_map = dict(self.DAY_MAP, day=2, stops=[
            dict(self.DAY_MAP["stops"][0], label="1", location="Trastevere"),
        ])
        out = render_html(itinerary, TRIP, day_maps=[day2_map])
        # La cartina esiste solo per il giorno 2: il blocco `day-open` (che
        # contiene la cartina) deve comparire una volta sola, e con quel
        # titolo.
        self.assertEqual(out.count("class='day-open'"), 1)
        self.assertIn("<div class='day-title'>Giorno 2 — Centro</div>", out)

    # --- Come arrivare ----------------------------------------------------
    def test_directions_render_each_leg_with_ready_to_open_route(self):
        out = render_html(self._itinerary(), TRIP, directions=self.DIRECTIONS)
        self.assertIn("Come arrivare — giorno 1", out)
        self.assertIn("H → 1", out)
        self.assertIn("1 → 2", out)
        self.assertIn("circa 12 min a piedi", out)
        self.assertIn("arrivo previsto 09:00", out)
        self.assertIn("apri il percorso", out)
        self.assertIn("travelmode=walking", out)

    def test_unknown_travel_time_is_declared_not_invented(self):
        # La seconda tratta ha `minutes: None` (nessuna misura reale dalla
        # Distance Matrix). Il documento deve DIRLO. Stampare una stima
        # plausibile qui significherebbe far perdere un treno a qualcuno.
        out = render_html(self._itinerary(), TRIP, directions=self.DIRECTIONS)
        self.assertIn("tempo di percorrenza da verificare sul momento", out)

    def test_directions_numbers_are_the_same_numbers_drawn_on_the_map(self):
        # Il patto implicito fra le due sezioni: se la cartina dice "2" e la
        # tratta dice "2", sono lo stesso posto. Le etichette arrivano
        # entrambe dagli stessi `day_plans` (vedi build_pdf_sections), e
        # questo test blocca il giorno in cui qualcuno le calcolasse due
        # volte in due modi diversi.
        map_labels = [s["label"] for s in self.DAY_MAP["stops"]]
        leg_labels = [leg["to_label"] for leg in self.DIRECTIONS[0]["legs"]]
        self.assertEqual(map_labels, [l for l in leg_labels if l != "H"])

    # --- Stima dei costi --------------------------------------------------
    def test_cost_table_totals_only_the_known_lines(self):
        out = render_html(self._itinerary(), TRIP, cost_summary=self.COST_SUMMARY)
        self.assertIn("Stima dei costi e dettaglio budget", out)
        self.assertIn("Hotel Test", out)
        # La voce senza prezzo resta VISIBILE (ometterla nasconderebbe una
        # spesa) ma marcata, e il totale resta quello delle sole voci note.
        self.assertIn("[Da Verificare]", out)
        self.assertIn("Totale stimato", out)
        # Maiuscolo voluto nel documento ("NON incluse"): è l'unico punto in cui
        # il PDF ammette di non conoscere un prezzo, e deve saltare all'occhio.
        # L'asserzione lo verifica alla lettera proprio per questo.
        self.assertIn("NON incluse nel totale", out)
        self.assertIn("Sopra il budget indicato", out)

    def test_cost_section_absent_when_there_is_nothing_to_estimate(self):
        # Nessuna riga = nessuna sezione e nessuna voce di indice: un indice
        # che rimanda a una pagina vuota è un difetto che il cliente vede.
        out = render_html(self._itinerary(), TRIP, cost_summary={"lines": []})
        self.assertNotIn("Stima dei costi e dettaglio budget", out)

    # --- Architect's Tips per direttrici + piani B ------------------------
    def test_tips_are_grouped_by_directive(self):
        out = render_html(self._itinerary(), TRIP, tips=self.TIPS)
        self.assertIn("Architect&#x27;s Tips", out)
        self.assertIn("Biglietti e prenotazioni", out)
        self.assertIn("Risparmio e pagamenti", out)
        self.assertEqual(out.count("class='tip-group'"), 2)

    def test_legacy_flat_tips_used_only_when_the_new_ones_are_missing(self):
        # Un itinerario generato PRIMA di questa modifica (o una chiamata
        # fallita) non deve lasciare il cliente senza consigli: meglio la
        # vecchia lista piatta che una sezione vuota.
        itinerary = dict(self._itinerary(), architect_tips=["Porta scarpe comode."])
        out = render_html(itinerary, TRIP)
        self.assertIn("Porta scarpe comode.", out)
        self.assertIn("class='tips-box'", out)
        # E quando i consigli nuovi ci sono, i vecchi NON si sommano ad essi:
        # due sezioni di consigli nello stesso documento sono un difetto.
        out2 = render_html(itinerary, TRIP, tips=self.TIPS)
        self.assertNotIn("Porta scarpe comode.", out2)

    def test_rain_plans_rendered_as_explicit_swaps(self):
        out = render_html(self._itinerary(), TRIP, tips=self.TIPS)
        self.assertIn("Piani B: se piove", out)
        self.assertIn("Passeggiata al Foro", out)
        self.assertIn("Musei Capitolini", out)
        self.assertIn("completamente coperto", out)

    # --- Menù e info dei ristoranti ---------------------------------------
    def test_restaurant_block_carries_menu_and_info_links(self):
        out = render_html(self._itinerary(), TRIP, place_cards=self.PLACE_CARDS)
        self.assertIn("https://damario.example/menu", out)
        self.assertIn("Menù del ristorante", out)
        self.assertIn("Apri in Google Maps", out)
        self.assertIn("Via Roma 1 · +39 06 1234567", out)

    def test_place_links_only_on_the_block_they_belong_to(self):
        # `P1` (il Colosseo) non ha scheda: il suo blocco non deve ereditare
        # i link del ristorante.
        out = render_html(self._itinerary(), TRIP, place_cards=self.PLACE_CARDS)
        self.assertEqual(out.count("https://damario.example/menu"), 1)

    # --- Link interni alle guide tascabili --------------------------------
    def test_guide_link_in_the_day_plan_points_at_that_exact_guide(self):
        # "reindirizzi il cliente alla fine del pdf ... portandolo
        # DIRETTAMENTE sull'attrazione richiesta": il link deve puntare
        # all'ancora della guida di QUEL poi_id, non alla sezione generica.
        guide = {
            "poi_id": "P1", "poi_name": "Colosseo", "title": "Il Colosseo",
            "history_summary": "Storia.", "practical_tips": ["Arriva presto."],
            "best_time_to_visit": "Mattina", "estimated_visit_duration": "2 ore",
            "consiglio_personalizzato": "Riposa dopo.", "disclaimer": "Verifica gli orari.",
        }
        out = render_html(self._itinerary(), TRIP, guides=[guide])
        self.assertIn("Guida turistica tascabile</a>", out)
        anchor = guide["_anchor"]
        self.assertIn(f"href='#{anchor}'", out)
        self.assertIn(f"id='{anchor}'", out)

    def test_no_dead_guide_link_when_the_guide_failed_for_that_poi(self):
        # Una guida può fallire (rete, parsing) e viene saltata. Il blocco di
        # quel POI non deve restare con un link che non porta da nessuna
        # parte: in un PDF un'ancora rotta non dà errore, semplicemente non
        # succede nulla — e il cliente pensa che il documento sia rotto.
        guide = {
            "poi_id": "P2", "poi_name": "Da Mario", "title": "Da Mario",
            "history_summary": "Storia.", "practical_tips": ["Prenota."],
            "best_time_to_visit": "Sera", "estimated_visit_duration": "1 ora",
            "consiglio_personalizzato": "x", "disclaimer": "y",
        }
        out = render_html(self._itinerary(), TRIP, guides=[guide])
        self.assertEqual(out.count("Guida turistica tascabile</a>"), 1)

    # --- Copertina e indice -----------------------------------------------
    def test_cover_page_is_present_and_states_the_no_invented_data_promise(self):
        out = render_html(self._itinerary(), TRIP)
        self.assertIn("class='cover'", out)
        self.assertIn("Itinerario su misura", out)
        self.assertIn("mai sostituito da una stima inventata", out)

    def test_toc_lists_only_sections_that_actually_exist(self):
        bare = render_html(self._itinerary(), TRIP)
        self.assertNotIn("Stima dei costi e dettaglio budget</a>", bare)
        self.assertNotIn("Piani B: se piove</a>", bare)

        full = render_html(
            self._itinerary(), TRIP,
            cost_summary=self.COST_SUMMARY, tips=self.TIPS,
        )
        self.assertIn("Stima dei costi e dettaglio budget</a>", full)
        self.assertIn("Piani B: se piove</a>", full)
        # Ogni voce dell'indice deve avere una destinazione reale nel
        # documento: un indice che punta al vuoto è un difetto visibile.
        import re
        for anchor in re.findall(r"<a href='#([a-z0-9\-]+)'>", full):
            self.assertIn(f"id='{anchor}'", full, f"l'indice punta a '#{anchor}', che non esiste")

    # --- Tutto insieme, e i vincoli di wkhtmltopdf ------------------------
    def test_full_document_still_respects_the_engine_constraints(self):
        # Le tre proprietà che il motore Qt WebKit (~2014) di wkhtmltopdf non
        # sa rendere hanno già rotto il documento tre volte sul PC di
        # Lorenzo. Le sezioni nuove non fanno eccezione: qui il controllo
        # gira sul documento COMPLETO, non su quello minimo.
        out = render_html(
            self._itinerary(), TRIP,
            hotels=[{"name": "Hotel Test", "property_type": "Hotels", "price_night_eur": 100}],
            day_maps=[self.DAY_MAP], directions=self.DIRECTIONS,
            cost_summary=self.COST_SUMMARY, tips=self.TIPS,
            place_cards=self.PLACE_CARDS,
        )
        self.assertNotIn("opacity", out)
        self.assertNotIn("rgba(", out)
        self.assertNotIn("linear-gradient", out)
        self.assertNotIn("display: flex", out)
        self.assertNotIn("display:flex", out)

    def test_sections_are_independent_of_each_other(self):
        # Ogni sezione degrada da sola (best-effort in build_pdf_sections):
        # il documento deve restare valido con QUALUNQUE sottoinsieme.
        for name, kwargs in (
            ("solo cartine", {"day_maps": [self.DAY_MAP]}),
            ("solo tragitti", {"directions": self.DIRECTIONS}),
            ("solo costi", {"cost_summary": self.COST_SUMMARY}),
            ("solo consigli", {"tips": self.TIPS}),
            ("solo schede luogo", {"place_cards": self.PLACE_CARDS}),
            ("niente", {}),
        ):
            with self.subTest(name):
                out = render_html(self._itinerary(), TRIP, **kwargs)
                self.assertTrue(out.startswith("<!DOCTYPE html>"))
                self.assertTrue(out.rstrip().endswith("</html>"))


class TestRenderPdf(unittest.TestCase):
    def test_missing_binary_raises_clear_error(self):
        itinerary = {"destination": "Roma", "executive_summary": "x", "days": []}
        with patch("src.pdf_renderer.shutil.which", return_value=None):
            with self.assertRaises(PdfRendererError) as ctx:
                render_pdf(itinerary, TRIP)
        self.assertIn("wkhtmltopdf", str(ctx.exception))
        self.assertIn("wkhtmltopdf.org", str(ctx.exception))

    def test_subprocess_failure_surfaces_stderr_not_swallowed(self):
        itinerary = {"destination": "Roma", "executive_summary": "x", "days": []}
        fake_result = MagicMock(returncode=1, stderr="errore fittizio di rendering")
        with patch("src.pdf_renderer.shutil.which", return_value="/usr/bin/wkhtmltopdf"), \
             patch("src.pdf_renderer.subprocess.run", return_value=fake_result):
            with self.assertRaises(PdfRendererError) as ctx:
                render_pdf(itinerary, TRIP)
        self.assertIn("errore fittizio di rendering", str(ctx.exception))

    def test_none_itinerary_raises_clear_error_not_attributeerror(self):
        # [REGRESSIONE — audit adversariale 2026-07-11] Prima del fix,
        # render_pdf(None, ...) sollevava un AttributeError criptico da
        # dentro render_html() (None.get(...)) invece del PdfRendererError
        # esplicito previsto per ogni altro fallimento di questa funzione.
        with self.assertRaises(PdfRendererError) as ctx:
            render_pdf(None, TRIP)
        self.assertIn("None", str(ctx.exception))

    def test_none_trip_raises_clear_error_not_attributeerror(self):
        itinerary = {"destination": "Roma", "executive_summary": "x", "days": []}
        with self.assertRaises(PdfRendererError):
            render_pdf(itinerary, None)

    def test_silent_wkhtmltopdf_success_with_no_file_written_is_caught(self):
        # [REGRESSIONE — audit adversariale 2026-07-11] Prima del fix,
        # se wkhtmltopdf ritornava returncode=0 senza scrivere alcun file
        # (es. directory senza permessi), render_pdf() restituiva comunque
        # `output_path` come se avesse avuto successo — un falso "successo"
        # che si propagava fino a main.py. Ora deve sollevare PdfRendererError.
        itinerary = {"destination": "Roma", "executive_summary": "x", "days": []}
        fake_result = MagicMock(returncode=0, stderr="")
        with tempfile.TemporaryDirectory() as tmp_dir:
            out_path = os.path.join(tmp_dir, "output.pdf")
            with patch("src.pdf_renderer.shutil.which", return_value="/usr/bin/wkhtmltopdf"), \
                 patch("src.pdf_renderer.subprocess.run", return_value=fake_result):
                with self.assertRaises(PdfRendererError) as ctx:
                    render_pdf(itinerary, TRIP, output_path=out_path)
            self.assertIn("non ha prodotto un file PDF valido", str(ctx.exception))
            # Nessun file corrotto/vuoto deve restare a quel path dopo il fallimento.
            self.assertFalse(os.path.exists(out_path))

    @unittest.skipIf(shutil.which("wkhtmltopdf") is None, "wkhtmltopdf non installato in questo ambiente")
    def test_concurrent_writes_to_same_output_path_do_not_corrupt(self):
        # [REGRESSIONE — audit adversariale 2026-07-11] Test di integrazione
        # reale (non mockato): prima del fix a scrittura atomica, invocazioni
        # concorrenti che scrivevano allo STESSO output_path potevano
        # corrompersi a vicenda (file troncato/misto). Con temp-file-poi-
        # os.replace(), ogni processo produce un PDF completo e valido prima
        # di sostituire il file finale — non ci sono stati intermedi visibili.
        itinerary = {
            "destination": "Roma", "executive_summary": "Un bel viaggio di prova.",
            "days": [{"day": 1, "title": "Arrivo", "blocks": [
                {"time": "09:00", "activity": "Colosseo", "location": "Roma"},
            ]}],
        }
        with tempfile.TemporaryDirectory() as tmp_dir:
            out_path = os.path.join(tmp_dir, "shared_output.pdf")
            with multiprocessing.Pool(processes=5) as pool:
                results = pool.starmap(
                    _concurrent_render_worker,
                    [(itinerary, TRIP, out_path) for _ in range(5)],
                )
            self.assertTrue(all(results), f"almeno un worker ha fallito: {results}")
            # Il file finale, chiunque l'abbia scritto per ultimo, deve
            # essere un PDF completo e valido — mai un file troncato/misto.
            data = Path(out_path).read_bytes()
            self.assertTrue(data.startswith(b"%PDF-"))
            self.assertIn(b"%%EOF", data[-1024:])

    @unittest.skipIf(shutil.which("wkhtmltopdf") is None, "wkhtmltopdf non installato in questo ambiente")
    def test_real_pdf_is_generated_and_starts_with_pdf_magic_bytes(self):
        # Test di integrazione reale (non mockato) — genera davvero un PDF
        # e verifica che sia un file PDF valido, non solo che il comando
        # sia stato invocato con i parametri giusti.
        itinerary = {
            "destination": "Roma", "executive_summary": "Un bel viaggio di prova.",
            "days": [{"day": 1, "title": "Arrivo", "blocks": [
                {"time": "09:00", "activity": "Colosseo", "location": "Roma", "poi_id": "POI1"},
            ]}],
        }
        path = render_pdf(itinerary, TRIP, hotels=[{"name": "Hotel Test", "property_type": "Hotels"}])
        with open(path, "rb") as f:
            header = f.read(5)
        self.assertEqual(header, b"%PDF-")


if __name__ == "__main__":
    unittest.main()
