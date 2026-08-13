"""I collegamenti ai capitoli non dipendono piu' da un'ancora invisibile (task #205).

PERCHE' QUESTO FILE ESISTE

In produzione, il 13 agosto 2026, il servizio si e' fermato da solo con:

    «il documento ha 7 capitoli staccati e NESSUN collegamento interno che ci
    porti: chi legge non ha modo di arrivarci se non scorrendo il documento a
    mano»

Lo stesso identico codice, in sviluppo, ne produceva sessantacinque.

## Cosa era gia' stato escluso, misurandolo

- **`pypdf`**: bloccato alla versione di sviluppo e messo in produzione. I
  collegamenti restavano zero.
- **Le guide pubblicate su un indirizzo pubblico**: il campione costruito con
  `guide_urls` popolati da' gli stessi 65 collegamenti. Non e' quello.
- **Le opzioni di `wkhtmltopdf`** (`--outline`, numeri di pagina): provate una
  per una su una pagina di prova, il segnaposto sopravvive a tutte.

Resta una sola differenza fra i due ambienti: **il binario che stampa**. In
produzione e' una versione con le patch, in sviluppo quella normale — e la'
un'ancora larga due pixel non produce nessuna annotazione. Sparisce il
segnaposto, spariscono tutte le destinazioni.

## La riparazione, e la lezione che porta con se'

Il segnaposto serviva a **dedurre** una cosa che sappiamo gia': in che pagina
comincia ogni capitolo. Siamo noi a cucirli, in un ordine deciso da noi: il
conto e' «le pagine del documento principale, poi quelle di ogni capitolo in
fila».

**Quando un'informazione la sai per costruzione, non ricavarla guardando il
risultato.** Il segnaposto era un modo elegante di leggere qualcosa che
avevamo gia' in mano — e appena il motore di stampa ha smesso di collaborare,
quell'eleganza e' costata l'intera navigazione del documento.

Il segnaposto resta e ha la precedenza dove c'e': sa anche a che ALTEZZA della
pagina atterrare, cosa che il conto delle pagine non puo' sapere. La mappa per
costruzione e' la rete sotto.
"""

import io
import unittest

from src import fascicolo


def _pdf_di_prova(pagine: int, testo: str = "x") -> bytes:
    """Un PDF vero con il numero di pagine chiesto, scritto senza rete."""
    from pypdf import PdfWriter

    scrittore = PdfWriter()
    for _ in range(pagine):
        scrittore.add_blank_page(width=200, height=200)
    fuori = io.BytesIO()
    scrittore.write(fuori)
    return fuori.getvalue()


class TestIlContoDellePagineEQuelloGiusto(unittest.TestCase):

    def test_ogni_capitolo_comincia_dove_finisce_il_precedente(self):
        principale = _pdf_di_prova(10)
        capitoli = [_pdf_di_prova(3), _pdf_di_prova(2), _pdf_di_prova(4)]
        mappa = fascicolo.pagine_di_partenza(
            principale, capitoli, ["capitolo-a", "capitolo-b", "capitolo-c"])
        self.assertEqual(mappa, {"capitolo-a": 10, "capitolo-b": 13,
                                 "capitolo-c": 15})

    def test_un_capitolo_senza_ancora_non_rompe_il_conto(self):
        # Sposta comunque le pagine di quelli dopo: e' la parte che si
        # sbaglierebbe scrivendo il ciclo di fretta.
        mappa = fascicolo.pagine_di_partenza(
            _pdf_di_prova(5), [_pdf_di_prova(2), _pdf_di_prova(3)],
            [None, "capitolo-b"])
        self.assertEqual(mappa, {"capitolo-b": 7})

    def test_senza_capitoli_la_mappa_e_vuota(self):
        self.assertEqual(fascicolo.pagine_di_partenza(_pdf_di_prova(3), [], []), {})

    def test_dati_illeggibili_non_fanno_cadere_niente(self):
        # Questa funzione gira alla fine di una generazione da dodici minuti:
        # se sollevasse, butterebbe via tutto il lavoro per un conto di
        # pagine. Meglio nessuna mappa che nessun documento.
        for principale, capitoli in ((b"non un pdf", [b"nemmeno"]),
                                     (b"", [b""]), (None, None)):
            with self.subTest(principale=str(principale)[:12]):
                self.assertEqual(
                    fascicolo.pagine_di_partenza(principale, capitoli, ["a"]), {})


class TestSenzaNessunSegnapostoICapitoliRestanoRaGGIUNGIBILI(unittest.TestCase):
    """Il caso di produzione, riprodotto fedelmente.

    [SCRITTO DUE VOLTE, 2026-08-13 — e la prima versione era verde per il
    motivo sbagliato.] Il primo tentativo simulava l'assenza dei segnaposto
    spegnendo una regola nel foglio di stile del documento principale. Ma i
    capitoli hanno un foglio di stile PROPRIO: i loro segnaposto continuavano
    a esistere, i collegamenti si risolvevano come sempre, e la prova passava
    con o senza la riparazione nuova. L'ho scoperto mutando il prodotto: zero
    prove rosse.

    In produzione non manca UN segnaposto: non ne compare nessuno
    (`sonde: 0`). Qui si riproduce esattamente quello — il riparatore non ne
    riconosce piu' nemmeno uno — e la differenza si vede: **0 collegamenti
    senza la rete, 36 con**.
    """

    def _collegamenti(self, con_rete: bool) -> int:
        import tempfile
        from pathlib import Path

        import scripts_sample_pdf
        from src import fascicolo, pdf_links, pdf_renderer

        prefisso = pdf_links.PROBE_PREFIX
        uri_vero = pdf_links._uri_di
        mappa_vera = fascicolo.pagine_di_partenza

        def uri_senza_sonde(body):
            indirizzo = uri_vero(body)
            return None if (indirizzo and indirizzo.startswith(prefisso)) else indirizzo

        pdf_links._uri_di = uri_senza_sonde
        if not con_rete:
            fascicolo.pagine_di_partenza = lambda *a, **k: {}
        try:
            itin, trip, kwargs, _ = scripts_sample_pdf.build_sample_render_kwargs(
                con_fascicolo=True)
            percorso = str(Path(tempfile.mkdtemp()) / "campione.pdf")
            pdf_renderer.render_pdf(itin, trip, output_path=percorso, **kwargs)
            pdf_links._uri_di = uri_vero
            return pdf_links.analyse(Path(percorso).read_bytes())["goto"]
        finally:
            pdf_links._uri_di = uri_vero
            fascicolo.pagine_di_partenza = mappa_vera

    def test_senza_la_rete_il_documento_e_quello_del_13_agosto(self):
        # La riga di partenza: zero. E' il documento che si e' rifiutato di
        # partire, e prima ancora i due che erano partiti cosi'.
        self.assertEqual(self._collegamenti(con_rete=False), 0)

    def test_con_la_rete_i_capitoli_tornano_raggiungibili(self):
        self.assertGreater(
            self._collegamenti(con_rete=True), 20,
            "senza segnaposto i capitoli restano irraggiungibili: la mappa "
            "per costruzione non sta facendo il suo lavoro")


if __name__ == "__main__":
    unittest.main()
