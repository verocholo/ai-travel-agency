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
        # La copertina finisce dove comincia la fascia d'intestazione del
        # documento. Prima si tagliava su `class='toc'`, cioè sull'indice a
        # pagina intera: da quando l'indice vive DENTRO la copertina (task
        # #168) quel marcatore non esiste più, e il taglio restituiva
        # silenziosamente l'intero documento — l'asserzione continuava a
        # passare senza più verificare niente sulla copertina.
        # Il marcatore è aperto di proposito (`class='cover` senza apice di
        # chiusura): la copertina porta anche una classe di densità
        # (`cover-airy`/`cover-roomy`) scelta in base a quanto è lungo
        # l'indice, e un marcatore chiuso tornerebbe a non trovare niente.
        cover = out.split("class='cover", 1)[1].split("class='header'", 1)[0]
        self.assertIn("Cosa troverai dentro", cover)
        self.assertIn("Il programma, giorno per giorno", cover)
        # Nessun costo/consiglio/guida è stato passato al renderer: quelle
        # voci non devono comparire in copertina.
        self.assertNotIn("Stima dei costi", cover)
        self.assertNotIn("Guide turistiche tascabili", cover)

    def _cover_of(self, out):
        return out.split("class='cover", 1)[1].split("class='header'", 1)[0]

    def _days(self, n):
        return [{"day": i, "title": f"Giorno lungo numero {i}",
                 "blocks": [{"time": "09:00", "activity": "Tappa", "location": "Roma"}]}
                for i in range(1, n + 1)]

    def test_cover_density_adapts_to_how_long_the_index_is(self):
        # La copertina deve arrivare in fondo al foglio SENZA passare alla
        # pagina dopo, e la sua altezza dipende dai giorni di viaggio: ogni
        # giornata e' una riga annidata nell'indice. Una spaziatura sola non
        # puo' funzionare per entrambi gli estremi — larga riempie il weekend
        # ma fa sbordare le due settimane, stretta non sborda mai ma lascia un
        # terzo di pagina bianco sui viaggi corti, che sono la maggioranza.
        # Le tre classi sono verificate qui perche' e' l'unico punto in cui il
        # difetto e' visibile PRIMA di stampare il PDF.
        corto = self._cover_of(render_html(
            {"destination": "Roma", "executive_summary": "x", "days": self._days(2)}, TRIP))
        self.assertIn("cover-airy", corto)
        self.assertNotIn("cover-roomy", corto)

        lungo = self._cover_of(render_html(
            {"destination": "Roma", "executive_summary": "x", "days": self._days(20)}, TRIP))
        self.assertNotIn("cover-airy", lungo)
        self.assertNotIn("cover-roomy", lungo)

    def test_cover_facts_do_not_repeat_the_dates_already_in_the_hero(self):
        # Le date e la durata stanno in grande nella fascia scura. Ripeterle
        # nei riquadri subito sotto era lo stesso difetto che aveva gia'
        # costretto a fondere copertina e indice: due elenchi contigui che
        # dicono la stessa cosa. Il test conta le occorrenze, non la presenza:
        # una sola, quella della fascia.
        out = render_html(
            {"destination": "Roma", "executive_summary": "x", "days": self._days(2)}, TRIP)
        cover = self._cover_of(out)
        # [AGGIORNATO 2026-08-05 — task #195] Le date in copertina non sono
        # piu' in forma tecnica ma scritte come le scriverebbe una persona
        # («14 → 16 settembre 2026»). Quello che il controllo protegge non e'
        # cambiato: devono comparire UNA volta sola.
        from src.pdf_renderer import _periodo_leggibile

        periodo = _periodo_leggibile(TRIP["date_start"], TRIP["date_end"])
        self.assertIn(periodo, cover,
                      "il periodo non compare: il controllo sarebbe vacuo")
        self.assertEqual(1, cover.count(periodo))
        self.assertNotIn(f"{TRIP['date_start']} \u2192 {TRIP['date_end']}", cover,
                         "la data in forma tecnica e' tornata in copertina")

    def test_cover_fact_grid_has_no_empty_filler_cells(self):
        # Una cella vuota accanto a due riquadri non si legge come "riga
        # incompleta": si legge come un riquadro che non e' stato stampato.
        # Meglio riquadri piu' larghi che chiudono la riga.
        cover = self._cover_of(render_html(
            {"destination": "Roma", "executive_summary": "x", "days": self._days(2)}, TRIP))
        griglia = cover.split("class='cover-facts'", 1)[1].split("</table>", 1)[0]
        self.assertNotIn("<td></td>", griglia)

    def test_cover_explains_how_to_read_the_document(self):
        # Tre cose che il cliente non scoprirebbe da solo: che il PDF e'
        # cliccabile, che ogni giornata ha la sua cartina, e che i dati
        # mancanti sono marcati invece che inventati. Riempiono la copertina
        # con qualcosa che serve — la differenza fra una pagina piena e una
        # pagina gonfiata.
        cover = self._cover_of(render_html(
            {"destination": "Roma", "executive_summary": "x", "days": self._days(2)}, TRIP))
        self.assertIn("Come si legge", cover)
        self.assertIn("cliccabile", cover)
        self.assertIn("cartina", cover)

    def test_cover_strip_omitted_when_there_is_almost_nothing_to_list(self):
        # Con una sola sezione la striscia a due colonne sarebbe sbilanciata
        # e peggiorerebbe l'impaginazione invece di migliorarla: meglio non
        # stamparla. (Un itinerario senza giorni produce il solo "colpo
        # d'occhio".)
        out = render_html({"destination": "Roma", "executive_summary": "x", "days": []}, TRIP)
        # La copertina finisce dove comincia la fascia d'intestazione del
        # documento. Prima si tagliava su `class='toc'`, cioè sull'indice a
        # pagina intera: da quando l'indice vive DENTRO la copertina (task
        # #168) quel marcatore non esiste più, e il taglio restituiva
        # silenziosamente l'intero documento — l'asserzione continuava a
        # passare senza più verificare niente sulla copertina.
        # Il marcatore è aperto di proposito (`class='cover` senza apice di
        # chiusura): la copertina porta anche una classe di densità
        # (`cover-airy`/`cover-roomy`) scelta in base a quanto è lungo
        # l'indice, e un marcatore chiuso tornerebbe a non trovare niente.
        cover = out.split("class='cover", 1)[1].split("class='header'", 1)[0]
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

    def _glance(self, out):
        """La fetta di documento del capitolo "a colpo d'occhio", e solo quella.

        [AGGIUNTO 2026-08-02 (ter) — task #168] I test di questo capitolo
        cercavano le proprie stringhe nel documento INTERO. È una debolezza
        già costata cara due volte in questo progetto: una verifica non
        delimitata continua a passare anche quando la cosa che dovrebbe
        proteggere è sparita, perché quella stringa esiste da qualche altra
        parte — qui la copertina, che nomina destinazione, date e durata una
        pagina prima. Delimitare la fetta è ciò che rende la verifica capace
        di fallire."""
        return out.split("class='at-a-glance-page'", 1)[1].split("Il viaggio in breve", 1)[0]

    def test_at_a_glance_page_present(self):
        out = render_html(self._itinerary(), TRIP)
        self.assertIn("colpo d'occhio", out.lower())
        self.assertIn("class='at-a-glance-page'", out)

    def test_at_a_glance_does_not_repeat_what_the_cover_already_says(self):
        """[AGGIUNTO 2026-08-02 (ter) — difetto visto sul PDF vero] Il capitolo
        stampava riquadri con destinazione, date, durata, budget e alloggio:
        cinque dati che la copertina, una pagina prima, aveva appena dato. Due
        elenchi contigui che dicono la stessa cosa — lo stesso difetto che
        aveva già imposto la fusione di copertina e indice."""
        hotels = [{"name": "Hotel Bello", "property_type": "Hotels", "price_night_eur": 120.0}]
        glance = self._glance(render_html(self._itinerary(), TRIP, hotels=hotels))
        self.assertNotIn("Destinazione", glance)
        self.assertNotIn("Durata", glance)
        self.assertNotIn("Budget", glance)
        self.assertNotIn("Hotel Bello", glance)
        self.assertNotIn(f"{TRIP['date_start']} &rarr; {TRIP['date_end']}", glance)

    def test_at_a_glance_gives_each_day_its_real_calendar_date(self):
        """Il quadro delle giornate deve dire qualcosa che l'indice di
        copertina non dice già: la data vera, con il giorno della settimana.
        Il 1 settembre 2026 è un martedì; il giorno 2 cade il 2 settembre —
        stessa convenzione senza "+1" di `triage._date_difference_days()`."""
        glance = self._glance(render_html(self._itinerary(), TRIP))
        self.assertIn("mar 1 set", glance)
        self.assertIn("mer 2 set", glance)

    def test_at_a_glance_shows_the_time_window_and_the_number_of_stops(self):
        itinerary = self._itinerary(days=[
            {"day": 1, "title": "Arrivo", "blocks": [
                {"time": "09:00", "activity": "Check-in", "location": "Hotel"},
                {"time": "15:30", "activity": "Passeggiata", "location": "Centro"},
                {"time": "20:00", "activity": "Cena", "location": "Trastevere"},
            ]},
            {"day": 2, "title": "Museo", "blocks": [
                {"time": "10:00", "activity": "Museo del Vino", "location": "Museo"},
            ]},
        ])
        glance = self._glance(render_html(itinerary, TRIP))
        self.assertIn("3 tappe", glance)
        self.assertIn("1 tappa", glance)
        # La finestra oraria va dal primo all'ultimo orario stampato, non
        # dal primo blocco all'ultimo nell'ordine della lista: se l'elenco
        # arrivasse disordinato, un "09:00-15:30" sarebbe una bugia.
        self.assertIn("09:00\u201320:00", glance)

    def test_at_a_glance_day_strip_lists_every_day_title(self):
        glance = self._glance(render_html(self._itinerary(), TRIP))
        self.assertIn("Giorno 1", glance)
        self.assertIn("Arrivo", glance)
        self.assertIn("Giorno 2", glance)
        self.assertIn("Museo", glance)

    def test_at_a_glance_disappears_from_document_and_index_when_it_has_nothing_to_say(self):
        """Senza giornate e senza cartina al capitolo non resta nulla. Un
        titolo con sotto il vuoto è peggio del capitolo assente, e una voce
        d'indice che porta a quel vuoto è peggio ancora."""
        out = render_html({"destination": "Roma", "executive_summary": "x", "days": []}, TRIP)
        self.assertNotIn("class='at-a-glance-page'", out)
        self.assertNotIn("Il tuo viaggio, a colpo d'occhio", out)

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

    def test_second_hotel_is_labelled_an_alternative_not_a_second_booking(self):
        """[AGGIUNTO 2026-08-02 — difetto visto rigenerando il campione] Due
        strutture stampate una sotto l'altra, identiche nel peso grafico e
        senza una parola sul rapporto fra loro: il cliente non può sapere se
        deve prenotarle entrambe. La copertina ne indica una sotto "BASE",
        l'itinerario è costruito attorno a quella e la stima dei costi conta
        solo quella — il documento deve dirlo dove le mostra."""
        hotels = [
            {"name": "Palazzo Ravizza", "property_type": "hotel", "price_night_eur": 140.0},
            {"name": "Hotel Athena", "property_type": "hotel", "price_night_eur": 118.0},
        ]
        out = render_html(self._itinerary(), TRIP, hotels=hotels)
        alloggio = out.split("id='alloggio'")[1].split("platforms-box")[0]
        self.assertIn("base del viaggio", alloggio)
        self.assertIn("alternativa", alloggio)
        self.assertLess(alloggio.index("base del viaggio"), alloggio.index("alternativa"))

    def test_single_hotel_gets_no_role_caption(self):
        """Con una struttura sola non c'è nessuna ambiguità da sciogliere, e
        una didascalia in più è solo rumore."""
        hotels = [{"name": "Palazzo Ravizza", "property_type": "hotel", "price_night_eur": 140.0}]
        out = render_html(self._itinerary(), TRIP, hotels=hotels)
        # (la regola CSS esiste sempre nel foglio di stile: qui conta che non
        # venga usata nella sezione)
        alloggio = out.split("id='alloggio'")[1].split("platforms-box")[0]
        self.assertNotIn("hotel-role", alloggio)
        self.assertNotIn("base del viaggio", alloggio)

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
        # [AGGIORNATO 2026-08-02 (ter) — task #168] Il titoletto "La tua mappa"
        # non c'è più: la cartina apre il capitolo "a colpo d'occhio" e il
        # titolo del capitolo la copre già. Un titolo di sezione seguito
        # immediatamente da un altro titolo di sezione era una riga di
        # inchiostro che non aggiungeva niente. Il marcatore giusto da
        # cercare è il contenitore dell'immagine.
        self.assertIn("class='map-image'", out)

    def test_no_map_section_when_bytes_absent(self):
        out = render_html(self._itinerary(), TRIP)
        self.assertNotIn("class='map-image'", out)
        self.assertNotIn("data:image/png;base64,", out)

    def test_map_disclaimer_present_when_map_shown(self):
        # Onestà sui limiti: le linee sono rette, non un vero percorso di
        # guida — deve essere dichiarato nel documento, non lasciato
        # implicito.
        out = render_html(self._itinerary(), TRIP, map_png_bytes=b"FAKE_PNG_BYTES")
        self.assertIn("non sono un percorso di navigazione", out)

    def test_la_cartina_dinsieme_arriva_anche_dal_piano(self):
        """[AGGIUNTO 2026-08-03 — «risolvi il problema delle cartine che non
        si vedono»] La cartina d'insieme non deve più dipendere dal fatto che
        Google risponda: se il piano porta un'immagine disegnata in casa, il
        capitolo la stampa lo stesso."""
        piano = {"png": b"SCHEMA_PNG", "map_source": "schema", "stops": []}
        out = render_html(self._itinerary(), TRIP, overview_map=piano)
        self.assertIn("class='at-a-glance-page'", out)
        self.assertIn("data:image/png;base64", out)

    def test_la_didascalia_dice_se_la_cartina_e_disegnata_in_casa(self):
        """Chi scambia lo schema per una mappa stradale e prova a seguirlo si
        perde: la differenza va scritta, non lasciata intuire."""
        schema = render_html(
            self._itinerary(), TRIP,
            overview_map={"png": b"X", "map_source": "schema", "stops": []},
        )
        self.assertIn("le strade no", schema)
        self.assertNotIn("Cartina stradale di tutto il viaggio", schema)

        strada = render_html(
            self._itinerary(), TRIP,
            overview_map={"png": b"X", "map_source": "google", "stops": []},
        )
        self.assertIn("Cartina stradale di tutto il viaggio", strada)
        self.assertNotIn("le strade no", strada)

    def test_il_piano_ha_la_precedenza_sui_byte_vecchi(self):
        """I due ingressi non devono produrre due cartine: il piano è quello
        nuovo e vince, i byte restano solo come strada di compatibilità."""
        out = render_html(
            self._itinerary(), TRIP,
            map_png_bytes=b"VECCHI_BYTE",
            overview_map={"png": b"NUOVO_PIANO", "map_source": "schema", "stops": []},
        )
        import base64 as _b64
        nuovo = _b64.b64encode(b"NUOVO_PIANO").decode("ascii")
        vecchio = _b64.b64encode(b"VECCHI_BYTE").decode("ascii")
        self.assertIn(nuovo, out)
        self.assertNotIn(vecchio, out)


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
        # [AGGIORNATO 2026-08-02] La scheda NON porta più `page-break`.
        # "Non spezzare a metà" era la regola giusta finché una scheda era un
        # riquadro corto; con la scheda completa (nove blocchi, quasi mezza
        # pagina) obbligava il motore a rimandare alla pagina successiva tutto
        # quello che non entrava, e il capitolo usciva a una scheda per pagina
        # con il 40% del foglio bianco — misurato sul campione. Ora la scheda
        # scorre, e il taglio cade dentro un elenco: si legge a cavallo di due
        # pagine come in qualsiasi libro.
        #
        # Quello che deve restare intero è la TESTA — occhiello, nome del
        # luogo e primo paragrafo — dentro il guscio `_keep_together()`
        # (`<table class='keep'>`). Senza, il cliente troverebbe il nome del
        # monumento in fondo a una pagina e la guida sulla successiva.
        self.assertIn("<div class='guide-card'>", out)
        self.assertNotIn("class='guide-card page-break'", out)
        testa = out.split("<div class='guide-card'>", 1)[1][:120]
        self.assertIn("class='keep'", testa)

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
        # [AGGIORNATO 2026-08-02] Due schede restano due riquadri distinti
        # (`guide-card`) con ciascuno la propria testa protetta; quello che è
        # cambiato è solo che la scheda può proseguire sulla pagina dopo
        # invece di trascinarcisi tutta. Vedi la nota estesa in
        # `test_guide_section_rendered_with_all_fields`.
        self.assertEqual(out.count("<div class='guide-card'>"), 2)
        self.assertIn("Il Colosseo", out)

    # [AGGIORNATO 2026-08-03] Da oggi il capitolo della recensione esce solo
    # se c'è una URL a cui rispondere: fare domande senza offrire un posto in
    # cui scriverle è una promessa rotta stampata su un documento pagato.
    # Questi controlli riguardano il CONTENUTO del capitolo, quindi passano
    # il link; l'assenza del link ha i suoi controlli dedicati in
    # test_link_recensione_2026_08_03.py.
    LINK = {"ref": "abc1234567", "url": "https://tally.so/r/wA5b2Q?ref=abc1234567"}

    def test_feedback_section_rendered_with_all_fields(self):
        out = render_html(self._base_itinerary(), TRIP, feedback=self.FEEDBACK,
                          feedback_link=self.LINK)
        self.assertIn("Che piacere risentirvi!", out)
        self.assertIn("Come è andata la sessione termale del Giorno 1?", out)
        self.assertIn("Il ritmo energetico proposto ha funzionato per voi?", out)
        self.assertIn("Ci autorizzi a usare le tue parole", out)
        self.assertIn("Grazie ancora per averci scelto.", out)

    def test_guides_and_feedback_together_both_present(self):
        out = render_html(self._base_itinerary(), TRIP, guides=[self.GUIDE],
                          feedback=self.FEEDBACK, feedback_link=self.LINK)
        self.assertIn("Le cascate bianche", out)
        self.assertIn("Che piacere risentirvi!", out)
        # Entrambe le sezioni devono comparire DOPO la struttura principale
        # dell'itinerario (executive summary), non prima.
        self.assertLess(out.index("executive_summary".replace("_", "-")) if False else out.index("Il viaggio in breve"),
                         out.index("Le cascate bianche"))
        self.assertLess(out.index("Le cascate bianche"), out.index("Che piacere risentirvi!"))

    def test_guide_and_feedback_text_is_escaped(self):
        guide = dict(self.GUIDE, history_summary="<script>alert(1)</script>")
        feedback = dict(self.FEEDBACK, intro_message="<b>ciao</b>")
        out = render_html(self._base_itinerary(), TRIP, guides=[guide], feedback=feedback,
                          feedback_link=self.LINK)
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
        # [2026-08-02] `hotel_point` serve perché la riga «H» compaia in
        # legenda: da oggi la si stampa solo se sulla figura c'è davvero un
        # pallino H da spiegare.
        "hotel_point": (41.8902, 12.4922),
        "png": None,
        "stops": [
            {"label": "1", "time": "09:00", "activity": "Visita", "location": "Colosseo",
             "poi_id": "P1", "type": "museum", "type_label": "Museo / cultura", "color": "orange"},
            {"label": "2", "time": "13:00", "activity": "Pranzo", "location": "Da Mario",
             "poi_id": "P2", "type": "restaurant", "type_label": "Dove mangiare", "color": "green"},
        ],
    }
    # [AGGIORNATO 2026-08-03 — task #179] Aggiunti `from_poi_id`/`to_poi_id`
    # (che `build_day_legs()` ha sempre prodotto e questo fixture non
    # copiava) e i metri. Non e' un dettaglio cosmetico: da oggi ogni
    # spostamento viene stampato DENTRO la tappa a cui porta, e la tappa la si
    # ritrova per `to_poi_id`. Senza quel campo il fixture avrebbe continuato
    # a passare per un'altra strada — il riquadro di coda "Rientro" — cioe'
    # avrebbe provato un comportamento che in produzione non capita mai.
    DIRECTIONS = [{
        "day": 1, "title": "Arrivo",
        "legs": [
            {"from_label": "H", "from_name": "Hotel Test", "from_poi_id": "H1",
             "to_label": "1", "to_name": "Colosseo", "to_poi_id": "P1",
             "arrival_time": "09:00", "minutes": 12, "mode": "walking", "mode_label": "a piedi",
             "metres": 900, "metres_estimated": False, "distance_text": "900 m",
             "url": "https://www.google.com/maps/dir/?api=1&origin=41.9,12.5"
                    "&destination=41.89,12.49&travelmode=walking"},
            {"from_label": "1", "from_name": "Colosseo", "from_poi_id": "P1",
             "to_label": "2", "to_name": "Da Mario", "to_poi_id": "P2",
             "arrival_time": "13:00", "minutes": None, "mode": "walking", "mode_label": "a piedi",
             "metres": 1200, "metres_estimated": True, "distance_text": "1,2 km",
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

    def test_la_legenda_non_promette_un_simbolo_che_sulla_figura_non_c_e(self):
        """[AGGIUNTO 2026-08-02] Se l'alloggio non è geolocalizzato la cartina
        non ha nessun pallino «H», ma la legenda lo spiegava lo stesso. Il
        cliente lo cerca, non lo trova, e da lì in poi non si fida più nemmeno
        dei numeri — che invece sono giusti."""
        senza_hotel = {k: v for k, v in self.DAY_MAP.items() if k != "hotel_point"}
        out = render_html(self._itinerary(), TRIP, day_maps=[senza_hotel])
        self.assertNotIn("Punto di partenza e rientro", out)
        # Le tappe restano: si perde il perno, non la legenda.
        self.assertIn("Colosseo", out)

    def test_la_didascalia_dice_che_lo_schema_non_ha_le_strade(self):
        """[AGGIUNTO 2026-08-02] Quando la figura è lo schema disegnato in casa
        e non la mappa stradale di Google, tacerlo è una bugia per omissione:
        chi prova a seguirla come una mappa si perde."""
        schema = dict(self.DAY_MAP, png=b"\x89PNG\r\n\x1a\nfinto", map_source="schema")
        out = render_html(self._itinerary(), TRIP, day_maps=[schema])
        self.assertIn("map-caption", out)
        self.assertIn("le strade no", out)
        # Con la cartina vera di Google la didascalia NON deve comparire:
        # sarebbe falsa, quella le strade ce le ha.
        google = dict(self.DAY_MAP, png=b"\x89PNG\r\n\x1a\nfinto", map_source="google")
        self.assertNotIn("le strade no", render_html(self._itinerary(), TRIP, day_maps=[google]))

    def test_legend_shows_the_place_name_not_the_street_address(self):
        """[AGGIUNTO 2026-08-02 — difetto visto rigenerando il campione con un
        payload completo] In legenda si stampava `location`, che nei blocchi
        veri è un indirizzo (o, peggio, il nome nudo della città): usciva
        «1 Siena» e «3 Via Giovanni Duprè 132». La legenda risponde a una sola
        domanda — "il puntino 1 cos'è?" — e un indirizzo non le risponde."""
        day_map = {
            "day": 1, "title": "Arrivo", "png": None,
            "stops": [
                {"label": "1", "time": "10:30", "activity": "Piazza del Campo",
                 "location": "Siena", "poi_id": "P1", "type": "activity",
                 "type_label": "Attività", "color": "orange"},
                {"label": "2", "time": "12:30", "activity": "Pranzo alla Taverna di San Giuseppe",
                 "location": "Via Giovanni Duprè 132", "poi_id": "P2", "type": "restaurant",
                 "type_label": "Dove mangiare", "color": "green"},
            ],
        }
        itinerary = {
            "destination": "Siena", "executive_summary": "Tre giorni.",
            "days": [{"day": 1, "title": "Arrivo", "blocks": [
                {"time": "10:30", "activity": "Piazza del Campo", "location": "Siena", "poi_id": "P1"},
                {"time": "12:30", "activity": "Pranzo alla Taverna di San Giuseppe",
                 "location": "Via Giovanni Duprè 132", "poi_id": "P2"},
            ]}],
        }
        out = render_html(itinerary, TRIP, day_maps=[day_map])
        legend = out.split("class='map-legend'")[1].split("</div></div>")[0]
        self.assertIn("<strong>Piazza del Campo</strong>", legend)
        self.assertIn("<strong>Pranzo alla Taverna di San Giuseppe</strong>", legend)
        # Il nome nudo della città accanto a un puntino non è un'informazione.
        self.assertNotIn("<strong>Siena</strong>", legend)
        self.assertNotIn("<strong>Via Giovanni Duprè 132</strong>", legend)

    def test_legend_prefers_the_proper_name_over_the_sentence(self):
        """[AGGIUNTO 2026-08-02, poche ore dopo il test qui sopra] `activity` è
        una FRASE: «2 Pranzo alla Taverna di San Giuseppe — 12:30 · Dove
        mangiare» ripete due volte che si mangia e non è quello che il cliente
        legge sull'insegna. `stop["name"]`, aggiunto in
        `maps_static.build_day_map_plans()`, è il nome proprio del posto: la
        legenda deve preferirlo."""
        day_map = {
            "day": 1, "title": "Arrivo", "png": None,
            "stops": [
                {"label": "1", "time": "12:30", "name": "Taverna di San Giuseppe",
                 "activity": "Pranzo alla Taverna di San Giuseppe",
                 "location": "Via Giovanni Duprè 132", "poi_id": "P1",
                 "type": "restaurant", "type_label": "Dove mangiare", "color": "green"},
            ],
        }
        out = render_html(self._itinerary(), TRIP, day_maps=[day_map])
        legend = out.split("class='map-legend'")[1].split("</div></div>")[0]
        self.assertIn("<strong>Taverna di San Giuseppe</strong>", legend)
        self.assertNotIn("<strong>Pranzo alla Taverna di San Giuseppe</strong>", legend)

    def test_legend_falls_back_to_location_when_the_activity_is_missing(self):
        """Il ripiego resta: meglio un indirizzo che un puntino senza nome."""
        day_map = {
            "day": 1, "title": "Arrivo", "png": None,
            "stops": [{"label": "1", "time": "10:30", "activity": "",
                       "location": "Piazza del Duomo 8", "poi_id": "P1",
                       "type": "museum", "type_label": "Museo / cultura", "color": "orange"}],
        }
        out = render_html(self._itinerary(), TRIP, day_maps=[day_map])
        self.assertIn("<strong>Piazza del Duomo 8</strong>", out)

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

    # --- Spostamenti dentro il programma del giorno -----------------------
    # [RISCRITTO 2026-08-03 — task #179, richiesta di Lorenzo: «la parte del
    # "come arrivare" appare ridondante, uniscila al programma del giorno»]
    def test_ogni_spostamento_sta_attaccato_alla_tappa_a_cui_porta(self):
        out = render_html(self._itinerary(), TRIP, directions=self.DIRECTIONS)
        # Il riquadro separato non deve piu' esistere: era la meta' ridondante.
        self.assertNotIn("Come arrivare — giorno 1", out)
        self.assertNotIn("class='leg-row'", out)
        # Due spostamenti, due righe: nessuno e' finito nel dimenticatoio.
        self.assertEqual(out.count("class='leg-inline'"), 2)
        # Il contenuto utile e' rimasto tutto: durata, distanza, link pronto.
        self.assertIn("circa 12 min a piedi", out)
        self.assertIn("900 m", out)
        self.assertIn("travelmode=walking", out)
        self.assertIn(">percorso</a>", out)
        # E la riga precede la tappa: si legge un attimo prima di alzarsi,
        # non due pagine dopo. Se un giorno finisse sotto, il PDF sarebbe
        # ancora "corretto" e completamente inutile — per questo l'ordine e'
        # verificato e non lasciato all'occhio.
        self.assertLess(out.index("class='leg-inline'"), out.index("Colosseo"))

    def test_nessuno_spostamento_resta_orfano_quando_manca_la_tappa(self):
        # Il tragitto verso "P9" non ha nessun blocco corrispondente nel
        # programma (capita quando l'ultima tappa e' il rientro in hotel).
        # Non deve sparire: finisce nel riquadro di coda.
        directions = [dict(self.DIRECTIONS[0], legs=list(self.DIRECTIONS[0]["legs"]) + [
            {"from_label": "2", "from_name": "Da Mario", "from_poi_id": "P2",
             "to_label": "H", "to_name": "Hotel Test", "to_poi_id": "P9",
             "minutes": 9, "mode": "walking", "mode_label": "a piedi",
             "metres": 700, "metres_estimated": False, "distance_text": "700 m",
             "url": "https://www.google.com/maps/dir/?api=1&travelmode=walking"},
        ])]
        out = render_html(self._itinerary(), TRIP, directions=directions)
        self.assertIn("Rientro", out)
        self.assertIn("verso Hotel Test", out)
        self.assertEqual(out.count("class='leg-inline'"), 3)

    def test_unknown_travel_time_is_declared_not_invented(self):
        # La seconda tratta ha `minutes: None` (nessuna misura reale dalla
        # Distance Matrix). Il documento deve DIRLO. Stampare una stima
        # plausibile qui significherebbe far perdere un treno a qualcuno.
        out = render_html(self._itinerary(), TRIP, directions=self.DIRECTIONS)
        self.assertIn("tempo da verificare sul momento", out)

    # --- Chilometri e percorrenze a piedi ---------------------------------
    # [AGGIUNTO 2026-08-03 — task #179, richiesta di Lorenzo: «inserire nel
    # programma del giorno il totale di chilometri/percorrenze a piedi»]
    def test_il_titolo_del_giorno_porta_il_totale_dei_chilometri(self):
        out = render_html(self._itinerary(), TRIP, directions=self.DIRECTIONS)
        self.assertIn("class='day-total'", out)
        # 900 m + 1200 m, tutti a piedi.
        self.assertIn("In movimento: circa 2,1 km, di cui 2,1 km a piedi", out)
        self.assertIn("min di cammino", out)

    def test_il_circa_compare_solo_quando_i_metri_sono_una_nostra_stima(self):
        # Stessa giornata, ma con entrambe le distanze misurate da Google:
        # sparisce il "circa". E' l'unico modo che ha il cliente per sapere
        # se il numero e' una misura o un calcolo nostro in linea d'aria.
        legs = [dict(l, metres_estimated=False) for l in self.DIRECTIONS[0]["legs"]]
        out = render_html(self._itinerary(), TRIP,
                          directions=[dict(self.DIRECTIONS[0], legs=legs)])
        self.assertIn("In movimento: 2,1 km", out)
        self.assertNotIn("In movimento: circa", out)

    def test_una_giornata_ferma_non_stampa_una_riga_di_chilometri(self):
        # Museo la mattina, ristorante di fianco: 250 m in tutto. Una riga
        # "In movimento: 250 m" non serve a nessuno, e una riga "0 m" sarebbe
        # falsa. La riga semplicemente non c'e'.
        legs = [dict(self.DIRECTIONS[0]["legs"][0], metres=250, distance_text="250 m")]
        out = render_html(self._itinerary(), TRIP,
                          directions=[dict(self.DIRECTIONS[0], legs=legs)])
        self.assertNotIn("class='day-total'", out)
        self.assertNotIn("In movimento", out)

    def test_i_chilometri_restano_anche_se_la_cartina_non_ce_la_fa(self):
        # Difetto vero, trovato scrivendo queste prove: il totale veniva
        # appeso al titolo del giorno, e il titolo del giorno viene stampato
        # SOLO insieme alla cartina. Bastava una chiamata a Google Static Maps
        # andata storta — il guasto piu' frequente di questo progetto — per
        # perdere in silenzio anche i chilometri, che con la cartina non
        # c'entrano nulla. Le due cose vanno provate separate.
        senza = render_html(self._itinerary(), TRIP, directions=self.DIRECTIONS)
        con = render_html(self._itinerary(), TRIP, directions=self.DIRECTIONS,
                          day_maps=[self.DAY_MAP])
        self.assertIn("class='day-total'", senza)
        self.assertIn("class='day-total'", con)
        # E una volta sola: con la cartina presente ci sono due punti che
        # potrebbero stamparlo, e stamparlo due volte sarebbe altrettanto
        # sbagliato che non stamparlo.
        self.assertEqual(con.count("class='day-total'"), 1)
        self.assertEqual(senza.count("class='day-total'"), 1)

    def test_senza_metri_conosciuti_niente_totale_inventato(self):
        legs = [{k: v for k, v in l.items() if k not in ("metres", "distance_text")}
                for l in self.DIRECTIONS[0]["legs"]]
        out = render_html(self._itinerary(), TRIP,
                          directions=[dict(self.DIRECTIONS[0], legs=legs)])
        self.assertNotIn("class='day-total'", out)

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
        # Maiuscolo voluto nel documento ("NON inclusa"/"NON incluse"): è l'unico
        # punto in cui il PDF ammette di non conoscere un prezzo, e deve saltare
        # all'occhio. L'asserzione lo verifica alla lettera proprio per questo.
        # La fixture ha UNA sola voce senza prezzo, quindi qui la frase è al
        # singolare: il plurale con la barra ("voce/i") era un difetto vero,
        # da modulo prestampato, e il test lo blocca in entrambe le direzioni.
        self.assertIn("NON inclusa nel totale", out)
        self.assertNotIn("voce/i", out)
        self.assertNotIn("NON incluse nel totale", out)
        self.assertIn("Sopra il budget indicato", out)

    def test_cost_table_uses_the_plural_when_more_than_one_price_is_missing(self):
        # Il compagno del test qui sopra: la stessa frase, ma con due voci
        # ignote. Serve a tenere coperto il ramo plurale, altrimenti una
        # correzione futura potrebbe stampare "2 voce è senza" senza che
        # nessun test se ne accorga.
        summary = dict(self.COST_SUMMARY)
        summary["unknown_count"] = 2
        out = render_html(self._itinerary(), TRIP, cost_summary=summary)
        self.assertIn("2 voci sono senza", out)
        self.assertIn("NON incluse nel totale", out)
        self.assertNotIn("NON inclusa nel totale", out)

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
        self.assertIn("class='cover", out)
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


class TestComeArrivareNonTornaDueVolte(unittest.TestCase):
    """[AGGIUNTO 2026-08-03 — task #179]

    Il riquadro "Come arrivare — giorno N" e la funzione che lo produceva
    (`_render_directions`) sono stati tolti: ripetevano, in un secondo
    elenco, gli stessi spostamenti gia' presenti nel programma del giorno.

    Questa prova non verifica il documento: verifica il CODICE. La differenza
    conta. Le prove sull'output qui sopra si accorgono che oggi il doppione
    non c'e'; non si accorgerebbero del passo che lo fa tornare, cioe' un
    domani in cui qualcuno ritrova la vecchia funzione, la vede definita, la
    crede viva e la ricollega. E' esattamente il modo in cui e' gia' tornato
    un doppione in questo progetto.
    """

    RADICE = Path(__file__).resolve().parent.parent

    def _sorgente(self):
        return (self.RADICE / "src" / "pdf_renderer.py").read_text(encoding="utf-8")

    def test_la_funzione_del_doppione_non_esiste_piu(self):
        self.assertNotIn("def _render_directions(", self._sorgente())

    def test_esiste_una_sola_funzione_che_stampa_uno_spostamento(self):
        sorgente = self._sorgente()
        self.assertEqual(sorgente.count("def _render_leg_inline("), 1)

    def test_il_titolo_del_riquadro_separato_non_e_piu_stampabile(self):
        # La stringa sopravvive solo dentro i commenti che spiegano perche'
        # e' stata tolta; quello che non deve tornare e' il pezzo di HTML che
        # la stampava.
        self.assertNotIn("Come arrivare &#8212; giorno", self._sorgente())
        self.assertNotIn("class='leg-row'", self._sorgente())


if __name__ == "__main__":
    unittest.main()
