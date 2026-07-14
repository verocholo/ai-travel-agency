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
        self.assertIn("class='page-break'", out)

    def test_guide_falls_back_to_poi_name_when_title_missing(self):
        guide = dict(self.GUIDE)
        del guide["title"]
        out = render_html(self._base_itinerary(), TRIP, guides=[guide])
        self.assertIn("Terme di San Filippo", out)

    def test_multiple_guides_each_get_own_page_break_section(self):
        guide2 = dict(self.GUIDE, poi_name="Colosseo", title="Il Colosseo")
        out = render_html(self._base_itinerary(), TRIP, guides=[self.GUIDE, guide2])
        self.assertEqual(out.count("Guida turistica:"), 2)
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
