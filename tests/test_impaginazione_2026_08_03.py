"""
IMPAGINAZIONE: un paragrafo non si spezza fra due pagine — task #183.

Richiesta di Lorenzo: «migliorare l'impaginazione per evitare di spezzare lo
stesso paragrafo».

Perche' serve un controllo automatico e non basta guardare il campione.

Il difetto e' invisibile nel codice e visibile solo sulla carta, a valle di
un motore di stampa che nessuno di noi controlla: un paragrafo si spezza
oppure no a seconda di quanto testo lo precede in quella pagina. Aggiungere
tre righe a un capitolo dieci pagine prima puo' rimettere il difetto senza
che nessuno tocchi la parte che lo riguarda. Un campione guardato a occhio
oggi non dice niente sul campione di domani.

Il secondo motivo e' piu' insidioso e riguarda l'altra meta' della richiesta.
La regola opposta — «non spezzare MAI niente» — e' facile da scrivere e
produce il reclamo precedente di Lorenzo, «troppi spazi vuoti dispersivi»:
un blocco che non entra nello spazio rimasto scende INTERO alla pagina dopo
e lascia bianco tutto il resto. Le due richieste sono in tensione, e il punto
in cui si incontrano e' un numero — `LIMITE_PROSA_UNITA`. Questi controlli
fissano il numero e, soprattutto, fissano che il numero ESISTA: se un domani
qualcuno lo togliesse per "sistemare" un paragrafo lungo, il documento
tornerebbe pieno di vuoti e nessuno collegherebbe le due cose.
"""
import re
import unittest

from src import pdf_renderer
from src import poi_pdf


TRIP = {"destination": "Siena", "date_start": "2026-09-10",
        "date_end": "2026-09-12", "travelers": 2}

ITINERARIO = {"days": [{
    "day": 1, "title": "Centro", "blocks": [{
        "time": "10:00", "location": "Duomo", "poi_id": "A",
        "activity": "Visita", "duration_min": 60,
    }],
}]}

POI = [{"id": "A", "name": "Duomo", "lat": 43.3, "lng": 11.3, "type": "museum"}]

# Un testo a tre paragrafi, ciascuno della lunghezza vera dei paragrafi delle
# guide misurata sul campione (fra i 340 e i 530 caratteri): sono quelli che
# la regola deve proteggere.
STORIA = "\n\n".join([
    "Il Duomo di Siena e' la cattedrale della citta' e uno dei pochi edifici "
    "gotici italiani costruiti quasi per intero prima della peste del 1348, "
    "che fermo' l'ampliamento in corso e lascio' in piedi il fianco del "
    "cosiddetto Duomo Nuovo, oggi visitabile come belvedere. " * 2,
    "La facciata a fasce di marmo bianco e verde e' il segno araldico della "
    "citta' e si ritrova su tutti gli edifici pubblici del centro storico, "
    "dal Palazzo Pubblico alle torri delle contrade. " * 2,
    "Il pavimento a tarsie marmoree resta coperto per gran parte dell'anno e "
    "viene scoperto per poche settimane, di solito fra agosto e ottobre: e' "
    "l'unico periodo in cui si vede per intero. " * 2,
])

GUIDE = [{"poi_id": "A", "poi_name": "Duomo", "title": "Duomo",
          "history_summary": STORIA}]


def _html_principale():
    return pdf_renderer.render_html(ITINERARIO, TRIP, poi=POI, guides=GUIDE)


def _solo_testo(html: str) -> str:
    """Quello che finisce sulla carta, senza marcatori e senza spazi doppi."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


class TestLaRegolaInSe(unittest.TestCase):

    def test_un_paragrafo_corto_viene_tenuto_insieme(self):
        """Il caso normale: e' la richiesta di Lorenzo, in una riga."""
        uscita = pdf_renderer._tieni_uniti_i_paragrafi(
            "<p class='guide-para'>Due righe di storia del Duomo.</p>"
        )
        self.assertIn("<table class='keep-prosa'>", uscita)
        self.assertIn("Due righe di storia del Duomo.", uscita)

    def test_un_paragrafo_lunghissimo_resta_spezzabile(self):
        """L'altra meta' della richiesta, quella che si dimentica sempre.

        Un blocco piu' alto dello spazio che resta in fondo alla pagina, se
        dichiarato inscindibile, non ci sta e scende tutto: il fondo della
        pagina resta bianco. Su un paragrafo di venti righe si perdono
        diciannove righe di carta — molto piu' fastidioso della cesura che
        si voleva evitare. Oltre la soglia si preferisce spezzare.
        """
        lungo = "Parola " * (pdf_renderer.LIMITE_PROSA_UNITA // 3)
        uscita = pdf_renderer._tieni_uniti_i_paragrafi(
            f"<p class='guide-para'>{lungo}</p>"
        )
        self.assertNotIn("keep-prosa", uscita)

    def test_la_soglia_si_misura_sul_testo_stampato_non_sui_marcatori(self):
        """Un paragrafo pieno di link non e' un paragrafo lungo.

        Se la misura contasse anche gli attributi `href`, tre collegamenti
        basterebbero a far sembrare lunghissimo un paragrafo di due righe, e
        proprio i paragrafi piu' utili — quelli che portano da qualche parte —
        sarebbero gli unici lasciati spezzare.
        """
        con_link = (
            "<p class='guide-para'>Il percorso completo "
            "<a href='https://www.google.com/maps/dir/?api=1&amp;origin=43.31"
            ",11.33&amp;destination=43.32,11.32&amp;travelmode=walking'>si apre "
            "su Maps</a> in un tocco.</p>"
        )
        self.assertIn("keep-prosa",
                      pdf_renderer._tieni_uniti_i_paragrafi(con_link))

    def test_le_entita_valgono_un_carattere_sola(self):
        """L'italiano e' pieno di apostrofi, e `_esc()` li scrive `&#x27;`.

        Sei caratteri al posto di uno: su un testo italiano la misura si
        gonfierebbe di circa un decimo, e la soglia scatterebbe su paragrafi
        che sulla carta sono corti. La misura si fa su cio' che si legge.
        """
        pezzo = "l&#x27;acqua e&#x27;"  # 20 caratteri scritti, 10 stampati
        self.assertEqual(len(pezzo), 20)
        self.assertEqual(pdf_renderer._lunghezza_visibile(pezzo), 10)

    def test_un_contenitore_con_dentro_altri_blocchi_non_viene_avvolto(self):
        """Il guscio va attorno ai paragrafi, non attorno ai capitoli.

        Un `<div>` che contiene altri `<div>` e' una scatola, non un
        paragrafo: renderla inscindibile significherebbe dichiarare
        inscindibile mezza pagina, cioe' proprio il difetto che la soglia
        serve a evitare.
        """
        contenitore = (
            "<div class='disclaimer'>Testo<div class='dentro'>Altro</div></div>"
        )
        self.assertNotIn(
            "keep-prosa", pdf_renderer._tieni_uniti_i_paragrafi(contenitore)
        )

    def test_la_passata_non_cambia_una_parola_di_quello_che_si_legge(self):
        """E' impaginazione, non riscrittura.

        Una regola che tocca il documento intero con un'espressione regolare
        e' comoda e pericolosa: basta una parentesi sbagliata perche' mangi
        del testo. Il controllo confronta il testo stampato prima e dopo.
        """
        prima = _html_principale()
        # `render_html` applica gia' la passata: rifarla non deve cambiare
        # nulla, ne' aggiungere gusci ai gusci ne' togliere parole.
        dopo = pdf_renderer._tieni_uniti_i_paragrafi(prima)
        self.assertEqual(_solo_testo(prima), _solo_testo(dopo))


class TestLaRegolaEApplicataAiDocumentiVeri(unittest.TestCase):
    """Una funzione giusta che nessuno chiama non impagina niente."""

    def test_il_documento_principale_passa_dalla_regola(self):
        html = _html_principale()
        self.assertIn("<table class='keep-prosa'>", html)

    def test_nel_documento_principale_nessun_paragrafo_corto_resta_scoperto(self):
        """Il controllo vero: si guarda il documento, non la funzione.

        Se un capitolo nuovo scrivesse i suoi paragrafi in un modo che la
        passata non riconosce, questo e' il punto in cui si vede.
        """
        html = _html_principale()
        for m in re.finditer(
            r"<(p|div) class='(guide-para|section-intro|disclaimer)'>"
            r"((?:(?!</?(?:p|div)\b).)*?)</\1>", html, re.DOTALL,
        ):
            if pdf_renderer._lunghezza_visibile(m.group(3)) > \
                    pdf_renderer.LIMITE_PROSA_UNITA:
                continue
            prima = html[max(0, m.start() - 60):m.start()]
            self.assertIn(
                "<table class='keep-prosa'><tr><td>", prima,
                "questo paragrafo puo' spezzarsi fra due pagine: "
                f"{_solo_testo(m.group(3))[:70]}",
            )

    def test_anche_le_guide_per_attrazione_passano_dalla_regola(self):
        """Sono quasi solo prosa: e' il documento dove si vedeva di piu'."""
        html = poi_pdf.build_guide_html(GUIDE[0], destination="Siena")
        self.assertIn("<table class='keep-prosa'>", html)


class TestIlGuscioEsisteDavveroPerIlMotoreDiStampa(unittest.TestCase):
    """Un marcatore senza la sua regola di stile e' decorazione.

    Il guscio funziona solo perche' il foglio di stile dichiara
    `page-break-inside: avoid` su quella classe. Senza la regola, l'HTML
    sarebbe pieno di tabelle e il PDF identico a prima: un difetto che
    passerebbe tutti gli altri controlli.
    """

    def test_il_foglio_di_stile_del_documento_principale_la_dichiara(self):
        html = _html_principale()
        self.assertRegex(
            html, r"\.keep-prosa\s*\{[^}]*page-break-inside:\s*avoid",
        )

    def test_il_foglio_di_stile_delle_guide_la_dichiara(self):
        html = poi_pdf.build_guide_html(GUIDE[0], destination="Siena")
        self.assertRegex(
            html, r"\.keep-prosa\s*\{[^}]*page-break-inside:\s*avoid",
        )

    def test_il_guscio_non_aggiunge_bordi_ne_spaziature(self):
        """Deve essere invisibile: cambia dove si spezza, non come si vede."""
        html = _html_principale()
        regola = re.search(r"\.keep-prosa\s*\{[^}]*\}", html).group(0)
        self.assertIn("margin: 0", regola)
        self.assertIn("border: none", regola)


class TestNienteChewkhtmltopdfNonSappiaDisegnare(unittest.TestCase):
    """Le trappole note del motore, ricontrollate sul documento nuovo."""

    def test_la_passata_non_introduce_costrutti_non_supportati(self):
        html = _html_principale()
        for vietato in ("linear-gradient", "opacity", "rgba(", "display: flex"):
            self.assertNotIn(vietato, html)


if __name__ == "__main__":
    unittest.main()
