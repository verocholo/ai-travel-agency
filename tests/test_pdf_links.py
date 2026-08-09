"""
Test della riparazione dei collegamenti interni (`src/pdf_links.py`).

PERCHÉ QUESTO FILE ESISTE
Lorenzo ha segnalato che i collegamenti del PDF non funzionavano — quello per
la guida turistica e quello per le recensioni. Il codice HTML era corretto: gli
`href="#ancora"` c'erano tutti, e c'era pure il flag `--enable-internal-links`
sulla riga di comando. wkhtmltopdf lo ignorava in silenzio.

È il tipo di difetto che nessun test sull'HTML può prendere, perché l'HTML era
giusto. Bisogna guardare il PDF PRODOTTO. Questi test lo guardano.

I test in fondo (`TestSulPdfVero`) invocano davvero wkhtmltopdf: sono gli unici
che possono dire se il collegamento funziona sul file che arriva al cliente.
Se il binario non c'è, si saltano — non si fingono verdi.
"""

import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from src import pdf_links
from src.pdf_renderer import render_html


HAS_WKHTMLTOPDF = shutil.which("wkhtmltopdf") is not None


def _annot(num: int, uri: str, rect="[10 700 100 712]") -> bytes:
    return (
        f"{num} 0 obj\n<<\n/Type /Annot\n/Subtype /Link\n/Rect {rect}\n"
        f"/Border [0 0 0]\n/A <<\n/Type /Action\n/S /URI\n/URI ({uri})\n>>\n>>\nendobj\n"
    ).encode("latin-1")


def _finto_pdf() -> bytes:
    """PDF minimo ma STRUTTURALMENTE come quelli di wkhtmltopdf: xref classica,
    `/Annots` come riferimento indiretto a un array, azioni `/URI` in linea."""
    parts = [b"%PDF-1.4\n"]
    parts.append(b"1 0 obj\n<<\n/Type /Catalog\n/Pages 2 0 R\n>>\nendobj\n")
    parts.append(b"2 0 obj\n<<\n/Type /Pages\n/Kids \n[\n3 0 R\n4 0 R\n]\n/Count 2\n>>\nendobj\n")
    parts.append(b"3 0 obj\n<<\n/Type /Page\n/Parent 2 0 R\n/Annots 5 0 R\n"
                 b"/MediaBox [0 0 595 842]\n>>\nendobj\n")
    parts.append(b"4 0 obj\n<<\n/Type /Page\n/Parent 2 0 R\n/Annots 6 0 R\n"
                 b"/MediaBox [0 0 595 842]\n>>\nendobj\n")
    parts.append(b"5 0 obj\n[7 0 R 8 0 R]\nendobj\n")
    parts.append(b"6 0 obj\n[9 0 R]\nendobj\n")
    # pagina 1: il link rotto verso #recensione + un link esterno legittimo
    parts.append(_annot(7, "file:///tmp/tmpabc.html#recensione"))
    parts.append(_annot(8, "https://esempio.it/pagina#sezione"))
    # pagina 2: la sonda che dice dove sta davvero l'ancora
    parts.append(_annot(9, f"{pdf_links.PROBE_PREFIX}recensione", rect="[20 300 24 306]"))

    data = b"".join(parts)
    # xref coerente: `_incremental_update` legge `/Prev` e `/Size` da qui.
    offsets = {}
    for m in re.finditer(rb"(?m)^(\d+) 0 obj", data):
        offsets[int(m.group(1))] = m.start()
    xref_at = len(data)
    out = bytearray(data)
    out += b"xref\n0 10\n0000000000 65535 f \n"
    for n in range(1, 10):
        out += f"{offsets[n]:010d} 00000 n \n".encode("ascii")
    out += b"trailer\n<<\n/Size 10 \n/Info 1 0 R\n/Root 1 0 R\n>>\nstartxref\n"
    out += str(xref_at).encode("ascii") + b"\n%%EOF\n"
    return bytes(out)


class TestAnalisi(unittest.TestCase):

    def test_riconosce_sonde_link_rotti_e_link_esterni(self):
        a = pdf_links.analyse(_finto_pdf())
        self.assertEqual(a["pagine"], 2)
        self.assertIn("recensione", a["sonde"])
        self.assertEqual(a["sonde"]["recensione"][0], 1, "la sonda è sulla seconda pagina")
        self.assertIn("recensione", a["rotti"])
        self.assertEqual(a["esterni"], 1, "il link a un sito vero non è un difetto")

    def test_un_link_esterno_con_ancora_non_viene_scambiato_per_rotto(self):
        # `https://tripadvisor.it/x#recensioni` è un link legittimo: se lo
        # riscrivessimo in un salto interno, il cliente perderebbe la pagina
        # vera. Solo lo schema `file:` è sintomo del difetto di wkhtmltopdf.
        self.assertIsNone(pdf_links._anchor_of_uri("https://esempio.it/x#y"))
        self.assertEqual(pdf_links._anchor_of_uri("file:///tmp/a.html#y"), "y")
        self.assertIsNone(pdf_links._anchor_of_uri("file:///tmp/a.html"))


class TestRiparazione(unittest.TestCase):

    def test_il_link_rotto_diventa_un_salto_alla_pagina_giusta(self):
        nuovo, rapporto = pdf_links.repair_internal_links_bytes(_finto_pdf())
        self.assertIsNone(rapporto["errore"])
        self.assertEqual(rapporto["riscritti"], 1)
        self.assertEqual(rapporto["sonde"], 1)
        self.assertEqual(rapporto["non_risolte"], [])
        a = pdf_links.analyse(nuovo)
        self.assertEqual(a["rotti"], {}, "nessun collegamento interno deve restare morto")
        self.assertEqual(a["sonde"], {}, "le sonde devono sparire dal documento consegnato")
        self.assertGreaterEqual(a["goto"], 1)

    def test_non_tocca_il_prefisso_del_file(self):
        # L'aggiornamento è incrementale: il documento originale resta intatto
        # in testa. Se questo test cade, un errore qui può corrompere un PDF
        # già valido — ed è la sola cosa peggiore di un link rotto.
        originale = _finto_pdf()
        nuovo, _ = pdf_links.repair_internal_links_bytes(originale)
        self.assertTrue(nuovo.startswith(originale))
        self.assertGreater(len(nuovo), len(originale))

    def test_l_azione_riscritta_non_mangia_il_tipo_dell_annotazione(self):
        # [REGRESSIONE 2026-08-02] La prima versione cercava `/A` con `find()`
        # e agganciava la `A` di `/Annot`, producendo `/Type /A << … >>`:
        # pdfinfo rifiutava il file con «Dictionary key must be a name object».
        corpo = (b"<<\n/Type /Annot\n/Subtype /Link\n/Rect [1 2 3 4]\n/Border [0 0 0]\n"
                 b"/A <<\n/Type /Action\n/S /URI\n/URI (file:///t.html#x)\n>>\n>>\n")
        nuovo = pdf_links._goto_body(corpo, 40, 700.0)
        self.assertIn(b"/Type /Annot", nuovo)
        self.assertIn(b"/Subtype /Link", nuovo)
        self.assertIn(b"/Rect [1 2 3 4]", nuovo)
        self.assertIn(b"/S /GoTo", nuovo)
        self.assertNotIn(b"/URI", nuovo)
        self.assertNotIn(b"/Type /A <<", nuovo)

    def test_un_ancora_senza_sonda_viene_dichiarata_non_indovinata(self):
        # Non si inventa una destinazione: meglio un link che non fa niente di
        # un link che porta a caso a pagina 1. E il rapporto lo dice, così il
        # difetto è visibile nei log invece che nella casella del cliente.
        dati = _finto_pdf().replace(b"#recensione", b"#inesistente", 1)
        _, rapporto = pdf_links.repair_internal_links_bytes(dati)
        self.assertEqual(rapporto["non_risolte"], ["inesistente"])

    def test_non_solleva_mai_e_non_rovina_niente(self):
        for spazzatura in (b"", b"non un pdf", b"%PDF-1.4\nciao", _finto_pdf()[:120]):
            with self.subTest(n=len(spazzatura)):
                nuovo, rapporto = pdf_links.repair_internal_links_bytes(spazzatura)
                self.assertEqual(nuovo, spazzatura)
                self.assertIsInstance(rapporto, dict)

    def test_su_un_file_che_non_esiste_riporta_l_errore_senza_sollevare(self):
        rapporto = pdf_links.repair_internal_links("/tmp/questo-file-non-esiste-mai.pdf")
        self.assertTrue(rapporto["errore"])


class TestAncoreNellHtml(unittest.TestCase):
    """Il contratto fra HTML e riparazione: ogni `href="#x"` stampato nel
    documento deve avere il suo bersaglio con la sonda. Un `href` senza sonda
    resterebbe un link morto — e questo test lo prende senza generare un PDF."""

    def _html(self):
        itinerary = {
            "destination": "Siena",
            "executive_summary": "Un bel viaggio.",
            "days": [{"day": 1, "title": "Centro", "blocks": [
                {"time": "10:00", "activity": "Piazza del Campo", "location": "Siena",
                 "poi_id": "POI1"}]}],
        }
        trip = {"destination": "Siena", "date_start": "2026-09-01",
                "date_end": "2026-09-03", "duration_days": 2, "budget_eur": 500}
        guides = [{"poi_id": "POI1", "poi_name": "Piazza del Campo",
                   "title": "Piazza del Campo", "history_summary": "Storia.",
                   "practical_tips": ["Vai presto."]}]
        return render_html(
            itinerary, trip,
            hotels=[{"name": "Hotel", "price_night_eur": 100}],
            guides=guides,
            feedback={"intro_message": "Com'è andata?", "questions": ["Ti è servito?"]},
        )

    def test_ogni_collegamento_interno_ha_il_suo_bersaglio(self):
        html = self._html()
        bersagli = set(re.findall(r"id='([^']+)' class='anchor-probe'", html))
        partenze = set(re.findall(r"href='#([^']+)'", html))
        self.assertTrue(partenze, "il documento deve avere collegamenti interni")
        self.assertEqual(
            partenze - bersagli, set(),
            "collegamenti interni senza ancora: sarebbero morti nel PDF",
        )

    def test_ogni_bersaglio_porta_la_sua_sonda(self):
        html = self._html()
        for nome in re.findall(r"id='([^']+)' class='anchor-probe'", html):
            self.assertIn(
                f"{pdf_links.PROBE_PREFIX}{nome}", html,
                f"l'ancora '{nome}' non ha la sonda: nel PDF sarebbe irraggiungibile",
            )

    def test_la_guida_del_poi_e_raggiungibile_dal_programma(self):
        # È il collegamento che Lorenzo ha segnalato per primo: dal blocco
        # della giornata alla scheda della guida in fondo al documento.
        html = self._html()
        self.assertIn("href='#guida-poi1'", html.lower())
        self.assertIn("id='guida-poi1' class='anchor-probe'", html.lower())

    def test_le_sonde_non_si_vedono(self):
        # Bianco su bianco e due pixel: se qualcuno domani toglie la regola CSS,
        # il cliente si ritrova puntini sparsi per tutto il documento.
        html = self._html()
        self.assertIn(".anchor-probe { font-size: 2px", html)
        self.assertIn("color: #ffffff", html)


@unittest.skipUnless(HAS_WKHTMLTOPDF, "wkhtmltopdf non installato")
class TestSulPdfVero(unittest.TestCase):
    """L'unico test che può dire la verità: si stampa il PDF e lo si legge."""

    @classmethod
    def setUpClass(cls):
        html = TestAncoreNellHtml()._html()
        cls.tmp = tempfile.mkdtemp(prefix="collegamenti-")
        html_path = Path(cls.tmp) / "d.html"
        html_path.write_text(html, encoding="utf-8")
        cls.pdf_path = Path(cls.tmp) / "d.pdf"
        subprocess.run(
            ["wkhtmltopdf", "--quiet", "--enable-internal-links", "--outline",
             str(html_path), str(cls.pdf_path)],
            capture_output=True, timeout=120,
        )
        cls.prima = cls.pdf_path.read_bytes()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_ogni_ancora_dichiarata_lascia_una_sonda_nel_pdf(self):
        # Se un bersaglio non produce annotazione (per esempio perché qualcuno
        # lo rimpicciolisce a dimensione zero), la sua destinazione diventa
        # inconoscibile e il link resta morto. Qui si accende il rosso.
        a = pdf_links.analyse(self.prima)
        self.assertTrue(a["sonde"], "nessuna sonda: la riparazione sarebbe cieca")
        self.assertEqual(sorted(set(a["rotti"]) - set(a["sonde"])), [])

    def test_dopo_la_riparazione_non_resta_un_solo_link_morto(self):
        nuovo, rapporto = pdf_links.repair_internal_links_bytes(self.prima)
        self.assertIsNone(rapporto["errore"])
        a = pdf_links.analyse(nuovo)
        self.assertEqual(a["rotti"], {})
        self.assertEqual(a["sonde"], {})
        self.assertGreater(a["goto"], 0)

    def test_il_pdf_riparato_resta_leggibile_da_un_lettore_vero(self):
        # [REGRESSIONE 2026-08-02] La prima versione produceva un file che
        # poppler apriva a suon di «Dictionary key must be a name object».
        if not shutil.which("pdfinfo"):
            self.skipTest("poppler-utils non installato")
        nuovo, _ = pdf_links.repair_internal_links_bytes(self.prima)
        out = Path(self.tmp) / "riparato.pdf"
        out.write_bytes(nuovo)
        res = subprocess.run(["pdfinfo", str(out)], capture_output=True, text=True, timeout=60)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertNotIn("Syntax Error", res.stderr)
        self.assertIn("Pages:", res.stdout)


if __name__ == "__main__":
    unittest.main()
