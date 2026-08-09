"""
L'ORDINE dei capitoli del documento — task #182, 2026-08-03.

Richiesta di Lorenzo: «la parte del "prima di partire" va messa in fondo al
documento».

Perche' un controllo automatico su una cosa che si vede a occhio.

L'ordine dei capitoli non e' scritto in nessuna tabella: e' l'ordine in cui
delle righe `parts.append(...)` compaiono dentro una funzione lunga migliaia
di righe. E' quindi la cosa piu' facile del progetto da spostare per sbaglio —
basta aggiungere un capitolo nuovo nel punto comodo invece che in quello
giusto — e la piu' difficile da notare: il documento esce, e' completo, non
manca niente, semplicemente i capitoli sono in un altro ordine. Senza questi
controlli la richiesta di Lorenzo andrebbe rifatta il giorno in cui qualcuno
aggiunge una sezione, e nessuno se ne accorgerebbe fino al reclamo
successivo.

Il secondo controllo — indice e corpo nello stesso ordine — difende una cosa
diversa e piu' subdola: su carta l'indice non si clicca, si usa per capire
"quanto manca". Un indice che elenca i capitoli in un ordine e le pagine che
li presentano in un altro non e' un difetto estetico, e' un indice che manda
a cercare nel posto sbagliato.
"""
import unittest

from src import pdf_renderer


TRIP = {"destination": "Siena", "date_start": "2026-09-10",
        "date_end": "2026-09-12", "travelers": 2}

ITINERARIO = {"days": [{
    "day": 1, "title": "Centro", "blocks": [{
        "time": "10:00", "location": "Duomo", "poi_id": "A",
        "activity": "Visita", "duration_min": 60,
    }],
}]}

POI = [{"id": "A", "name": "Duomo", "lat": 43.3, "lng": 11.3, "type": "museum"}]

# Forme vere: `title` (non "voce") per la lista della sera prima, e i quattro
# blocchi di `src/vademecum.py`. Con le chiavi sbagliate le due sezioni non
# escono affatto e i controlli sull'ordine passerebbero misurando il nulla.
PREDEPARTURE = {"checklist": [
    {"title": "Documento d'identità valido", "detail": "senza non si parte"},
    {"title": "Biglietti del museo stampati", "detail": "la fila si evita così"},
]}

VADEMECUM = {
    "climate": {"month_label": "settembre", "zone_label": "mediterraneo"},
    "packing": [{"title": "Sempre", "items": ["scarpe comode", "giacca leggera"]}],
}

# Forma vera della sezione consigli (vedi `tips_generator.normalize_tips`):
# un dizionario con `sections` e `rain_plans`, non una lista. Costruire qui
# una forma inventata renderebbe verde un controllo che non tocca il
# documento vero.
TIPS = {
    "sections": [
        {"id": "biglietti", "title": "Biglietti e prenotazioni",
         "tips": ["Prenota lo slot della torre il giorno prima."]},
    ],
    "rain_plans": [
        {"day": 1, "summary": "Se piove, il museo al posto della passeggiata.",
         "swaps": [{"from": "Passeggiata", "to": "Pinacoteca",
                    "why": "al coperto, a dieci minuti"}]},
    ],
}

GUIDE = [{"poi_id": "A", "poi_name": "Duomo", "title": "Duomo",
          "history_summary": "Due righe di storia."}]

FEEDBACK_LINK = {"url": "https://tally.so/r/esempio"}


def _html(**extra):
    argomenti = dict(
        poi=POI, guides=GUIDE, predeparture=PREDEPARTURE, vademecum=VADEMECUM,
        tips=TIPS, feedback_link=FEEDBACK_LINK,
    )
    argomenti.update(extra)
    return pdf_renderer.render_html(ITINERARIO, TRIP, **argomenti)


def _posizione(html: str, ancora: str) -> int:
    """Dove comincia il CAPITOLO con quell'ancora (non la voce d'indice).

    Il titolo di sezione e l'ancora compaiono insieme e in quest'ordine solo
    nel corpo: nell'indice l'ancora e' dentro un `href`, che ha una forma
    diversa. Cercare il marcatore completo evita di misurare per sbaglio la
    posizione della voce d'indice, che sta sempre in cima e farebbe passare
    qualunque ordine.
    """
    marcatore = f"id='{ancora}'"
    posizione = html.find(marcatore)
    assert posizione >= 0, f"capitolo '{ancora}' assente dal documento"
    return posizione


def _ordine_indice(html: str) -> list[str]:
    """Le ancore dell'indice, nell'ordine in cui sono elencate."""
    import re

    # L'indice sta prima del primo capitolo: si taglia li'. Le voci sono
    # `href="#ancora"`; i rimandi interni sparsi nel programma verrebbero
    # dopo e non entrano nel taglio.
    fine = html.find("class='section-title'")
    return re.findall(r"href='#([a-z0-9-]+)'", html[:fine if fine > 0 else len(html)])


class TestPrimaDiPartireStaInFondo(unittest.TestCase):

    def test_il_capitolo_sta_dopo_i_costi_e_dopo_le_guide(self):
        """La richiesta di Lorenzo, tradotta in due disuguaglianze.

        "In fondo" non vuol dire "piu' in basso di prima": vuol dire dopo
        TUTTO cio' che racconta il viaggio, guide comprese. Misurare solo la
        distanza dai costi lascerebbe passare un documento in cui la lista
        della sera prima e' finita in mezzo alle guide.
        """
        html = _html()
        self.assertGreater(_posizione(html, "prima-di-partire"),
                           _posizione(html, "consigli"))
        self.assertGreater(_posizione(html, "prima-di-partire"),
                           _posizione(html, "piani-b"))
        self.assertGreater(_posizione(html, "prima-di-partire"),
                           _posizione(html, "guide"))

    def test_la_valigia_resta_attaccata_alla_lista_della_sera_prima(self):
        """Le due sezioni non si separano: sono lo stesso gesto."""
        html = _html()
        self.assertGreater(_posizione(html, "vademecum"),
                           _posizione(html, "prima-di-partire"))
        # E in mezzo non deve esserci nessun altro capitolo.
        fra = html[_posizione(html, "prima-di-partire"):_posizione(html, "vademecum")]
        for altra in ("costi", "consigli", "piani-b", "guide", "recensione"):
            self.assertNotIn(f"id='{altra}'", fra)

    def test_la_recensione_resta_l_ultima_cosa_di_tutte(self):
        """Si legge a viaggio finito: e' l'unico capitolo che ha senso li'."""
        html = _html()
        self.assertGreater(_posizione(html, "recensione"),
                           _posizione(html, "vademecum"))

    def test_il_programma_del_viaggio_non_viene_interrotto(self):
        """Il motivo vero dello spostamento.

        Fra il programma giorno per giorno e i costi non deve piu' esserci
        nessun capitolo di adempimenti: e' la parte per cui il cliente ha
        pagato, e si legge di fila.
        """
        html = _html()

        # Il tratto da guardare va dal programma al primo capitolo che gli
        # viene subito dopo. Quale sia dipende da cosa contiene il documento:
        # con i preventivi e' "costi", senza e' "consigli". Prendere sempre
        # "costi" non funziona — in questa prova non c'e' nessun preventivo,
        # quindi quel capitolo non viene stampato affatto — e cadere sulla
        # fine del documento sarebbe peggio che inutile: il tratto
        # comprenderebbe la coda, dove "prima di partire" ci deve stare, e il
        # controllo fallirebbe proprio quando il documento e' giusto.
        fine = None
        for candidato in ("costi", "consigli"):
            if f"id='{candidato}'" in html:
                fine = _posizione(html, candidato)
                break
        assert fine is not None, (
            "il documento di prova non ha nessun capitolo dopo il programma: "
            "senza un estremo destro questo controllo non misura niente"
        )

        fra = html[_posizione(html, "giorno-per-giorno"):fine]
        self.assertNotIn("id='prima-di-partire'", fra)
        self.assertNotIn("id='vademecum'", fra)


class TestIndiceECorpoConcordano(unittest.TestCase):

    def test_l_indice_elenca_i_capitoli_nell_ordine_delle_pagine(self):
        html = _html()
        indice = [a for a in _ordine_indice(html) if f"id='{a}'" in html]
        posizioni = [_posizione(html, a) for a in indice]
        self.assertEqual(
            posizioni, sorted(posizioni),
            "l'indice elenca i capitoli in un ordine diverso da quello in cui "
            f"il documento li presenta: {indice}",
        )

    def test_nessuna_voce_d_indice_punta_a_un_capitolo_inesistente(self):
        """Un link morto stampato in copertina.

        Su carta non si vede affatto; a schermo porta all'inizio del file.
        """
        html = _html(predeparture=None, vademecum=None, tips=None,
                     feedback_link=None)
        for ancora in _ordine_indice(html):
            self.assertIn(f"id='{ancora}'", html,
                          f"l'indice rimanda a '{ancora}', che non esiste")


if __name__ == "__main__":
    unittest.main()
