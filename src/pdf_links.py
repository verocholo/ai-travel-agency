"""
Riparazione dei collegamenti INTERNI del PDF.

PERCHÉ QUESTO FILE ESISTE
Lorenzo ha segnalato: «i collegamenti non funzionano: quello per la guida
turistica che porta in fondo al documento non funziona, non funziona nemmeno
il collegamento per le recensioni». Non era un difetto del nostro HTML.

Misurato sul PDF prodotto: 60 annotazioni di collegamento, di cui 26 della
forma `file:///tmp/tmpXXXX.html#ancora`, zero `/GoTo`, zero `/Dests`.
wkhtmltopdf, quando il suo Qt non è la build patchata, ignora in silenzio
`--enable-internal-links` e traduce ogni `href="#x"` in un link a un FILE
temporaneo che sul computer del cliente non esiste. Il lettore PDF non
protesta: apre il nulla. È il peggior tipo di difetto — silenzioso e a valle.

Si poteva risolvere pretendendo la build patchata di wkhtmltopdf nel
Dockerfile. Non l'abbiamo fatto: significherebbe che la navigabilità del
documento dipende da quale .deb ha vinto l'ultima `apt-get`, e non è una cosa
che si possa verificare guardando il codice. Qui la si risolve DOPO, sul PDF
finito, in Python puro: qualunque sia il motore, il file che parte per la
casella del cliente ha collegamenti veri.

COME
1. `render_html` semina, in ogni punto bersaglio, una "sonda": un link
   invisibile verso `ancora-interna:<nome>`. wkhtmltopdf lo tratta
   come un link esterno qualunque e gli assegna un'annotazione — e
   un'annotazione porta con sé DUE informazioni che dall'HTML non si possono
   sapere: su quale pagina è finita l'ancora, e a quale altezza.
2. Qui si leggono quelle sonde, si riscrivono tutti i `file://…#x` in veri
   `/GoTo` verso la pagina e l'altezza giuste, e si neutralizzano le sonde.
3. La riscrittura è un *aggiornamento incrementale* (oggetti nuovi in coda +
   nuova xref + trailer con `/Prev`): il PDF originale non viene toccato di
   un byte, quindi un errore qui non può corrompere il documento.

CONTRATTO
`repair_internal_links` non solleva MAI e, se qualcosa non torna, lascia il
file esattamente com'era. Un documento con i link rotti è un difetto; un
documento corrotto è un rimborso.
"""

from __future__ import annotations

import re
from urllib.parse import unquote

# Schema fittizio delle sonde.
#
# È uno schema inventato (`ancora-interna:`), non un `http://`: wkhtmltopdf non
# risolve né contatta niente — si limita a copiare l'URI dentro l'annotazione,
# ed è tutto quello che ci serve. Un `http://` avrebbe funzionato uguale, ma
# avrebbe messo nel documento una stringa che SEMBRA una chiamata di rete: il
# test "nessuna risorsa esterna, il PDF si genera anche offline" sarebbe
# diventato rosso per un motivo falso, e il modo più veloce per rompere un
# prodotto è insegnare alla squadra che quel rosso lì si ignora.
#
# Il nome è in italiano di proposito: se un giorno finisse per sbaglio in un
# PDF consegnato, si capirebbe al volo da dove arriva.
PROBE_SCHEME = "ancora-interna"
PROBE_PREFIX = f"{PROBE_SCHEME}:"

_OBJ_RE = re.compile(rb"(?m)^(\d+)\s+(\d+)\s+obj\b")
_URI_APERTURA_RE = re.compile(rb"/URI\s*\(")
_RECT_RE = re.compile(
    rb"/Rect\s*\[\s*([\d.+-]+)\s+([\d.+-]+)\s+([\d.+-]+)\s+([\d.+-]+)\s*\]"
)
_KIDS_RE = re.compile(rb"/Kids\s*\[(.*?)\]", re.DOTALL)
_REF_RE = re.compile(rb"(\d+)\s+0\s+R")
_ANNOTS_INLINE_RE = re.compile(rb"/Annots\s*\[(.*?)\]", re.DOTALL)
_ANNOTS_REF_RE = re.compile(rb"/Annots\s+(\d+)\s+0\s+R")

# Scostamento verticale della destinazione rispetto al bordo alto del
# bersaglio: qualche punto di aria sopra il titolo. Senza, il titolo resta
# incollato al bordo superiore della finestra e sembra tagliato.
_TOP_PADDING = 14.0


class _Pdf:
    """Vista minima e di sola lettura su un PDF con xref classica."""

    def __init__(self, data: bytes):
        self.data = data
        self.objects: dict[int, tuple[int, int, int]] = {}
        for m in _OBJ_RE.finditer(data):
            if m.group(2) != b"0":
                continue
            num = int(m.group(1))
            end = data.find(b"endobj", m.end())
            if end == -1:
                continue
            self.objects[num] = (m.start(), m.end(), end)

    def body(self, num: int) -> bytes:
        pos = self.objects.get(num)
        return self.data[pos[1]: pos[2]] if pos else b""


def _page_order(pdf: _Pdf) -> list[int]:
    """Numeri degli oggetti pagina, nell'ordine di stampa.

    wkhtmltopdf produce un albero delle pagine piatto (un solo nodo `/Pages`
    con tutti i `/Kids`), ma la discesa ricorsiva costa tre righe e ci mette al
    riparo da una futura versione che lo annidi."""
    root = None
    for num in pdf.objects:
        if re.search(rb"/Type\s*/Pages", pdf.body(num)):
            root = num
            break
    if root is None:
        return []

    order: list[int] = []
    seen: set[int] = set()

    def descend(node: int) -> None:
        if node in seen or len(order) > 5000:
            return
        seen.add(node)
        body = pdf.body(node)
        if re.search(rb"/Type\s*/Pages", body):
            m = _KIDS_RE.search(body)
            if m:
                for ref in _REF_RE.finditer(m.group(1)):
                    descend(int(ref.group(1)))
        elif re.search(rb"/Type\s*/Page[\s/>\]]", body):
            order.append(node)

    descend(root)
    return order


def _annots_of_page(pdf: _Pdf, page_num: int) -> list[int]:
    """`/Annots` può essere un array inline oppure — ed è il caso di
    wkhtmltopdf — un riferimento indiretto a un oggetto array. Entrambi."""
    body = pdf.body(page_num)
    m = _ANNOTS_REF_RE.search(body)
    if m:
        arr = pdf.body(int(m.group(1)))
        return [int(r.group(1)) for r in _REF_RE.finditer(arr)]
    m = _ANNOTS_INLINE_RE.search(body)
    if m:
        return [int(r.group(1)) for r in _REF_RE.finditer(m.group(1))]
    return []


def _uri_di(body: bytes) -> str | None:
    """L'indirizzo dentro `/URI (...)`, con le sequenze di fuga sciolte.

    [AGGIUNTO 2026-08-05 — task #190] Serve perché il PDF finale non è più
    scritto da un solo programma. Finché wkhtmltopdf era l'unico produttore,
    l'indirizzo compariva in chiaro — `(ancora-interna:capitolo-duomo)` — e
    bastava leggerlo. Da quando le guide vengono unite al documento
    principale dentro un unico file, l'ultimo a scrivere è pypdf, che
    protegge ogni carattere non alfanumerico in ottale: la stessa identica
    stringa diventa `(ancora\\055interna\\072capitolo\\055duomo)`.

    Misurato prima di scrivere questa funzione: sul file unito, `analyse()`
    contava 4 collegamenti «esterni» e ZERO sonde. Cioè tutti i rimandi
    interni del fascicolo sarebbero rimasti rotti, in silenzio, esattamente
    il difetto che questo modulo esiste per chiudere.

    Regole della sintassi PDF (§7.3.4.2) che qui contano davvero:
      - `\\ddd` è un byte in ottale (da una a tre cifre);
      - `\\n \\r \\t \\b \\f \\( \\) \\\\` sono i soliti;
      - una barra a fine riga è una continuazione: sparisce insieme all'a capo;
      - le parentesi tonde possono essere annidate, se bilanciate.

    L'ultima riga è il motivo per cui non basta un'espressione regolare non
    ingorda: `(...(...)...)` la farebbe fermare alla prima chiusa.
    """
    m = _URI_APERTURA_RE.search(body)
    if not m:
        return None
    i = m.end()
    profondita = 1
    fuori = bytearray()
    while i < len(body):
        c = body[i]
        if c == 0x5C:  # barra rovesciata
            i += 1
            if i >= len(body):
                break
            d = body[i]
            if 0x30 <= d <= 0x37:  # cifra ottale
                cifre = bytearray()
                while i < len(body) and len(cifre) < 3 and 0x30 <= body[i] <= 0x37:
                    cifre.append(body[i])
                    i += 1
                fuori.append(int(cifre.decode("ascii"), 8) & 0xFF)
                continue
            if d in (0x0A, 0x0D):  # continuazione di riga: si butta via
                i += 1
                if d == 0x0D and i < len(body) and body[i] == 0x0A:
                    i += 1
                continue
            fuori.append({
                0x6E: 0x0A, 0x72: 0x0D, 0x74: 0x09,
                0x62: 0x08, 0x66: 0x0C,
            }.get(d, d))
            i += 1
            continue
        if c == 0x28:  # (
            profondita += 1
        elif c == 0x29:  # )
            profondita -= 1
            if profondita == 0:
                return fuori.decode("latin-1", "replace")
        fuori.append(c)
        i += 1
    return None


def _rect(body: bytes) -> tuple[float, float, float, float] | None:
    m = _RECT_RE.search(body)
    if not m:
        return None
    try:
        return tuple(float(m.group(i)) for i in range(1, 5))  # type: ignore[return-value]
    except ValueError:
        return None


def _anchor_of_uri(uri: str) -> str | None:
    """Nome dell'ancora se l'URI è un link interno tradotto male, altrimenti
    `None`. Solo `file:`: un `https://…#sezione` verso un sito vero è un link
    esterno legittimo e non va toccato."""
    if not uri.startswith("file:"):
        return None
    if "#" not in uri:
        return None
    name = uri.rsplit("#", 1)[1].strip()
    return unquote(name) or None


def analyse(data: bytes) -> dict:
    """Fotografia dei collegamenti di un PDF. Usata dai test e dalla
    diagnostica; non modifica niente."""
    pdf = _Pdf(data)
    pages = _page_order(pdf)
    page_of: dict[int, int] = {}
    for index, page_num in enumerate(pages):
        for annot in _annots_of_page(pdf, page_num):
            page_of[annot] = index

    probes: dict[str, tuple[int, float]] = {}
    broken: dict[str, list[int]] = {}
    external = 0
    for num in pdf.objects:
        body = pdf.body(num)
        if b"/Subtype /Link" not in body and b"/Subtype/Link" not in body:
            continue
        uri = _uri_di(body)
        if uri is None:
            continue
        if uri.startswith(PROBE_PREFIX):
            name = unquote(uri[len(PROBE_PREFIX):]).strip("/")
            rect = _rect(body)
            if name and rect and num in page_of and name not in probes:
                probes[name] = (page_of[num], rect[3])
            continue
        anchor = _anchor_of_uri(uri)
        if anchor:
            broken.setdefault(anchor, []).append(num)
        else:
            external += 1
    return {
        "pagine": len(pages),
        "sonde": probes,
        "rotti": broken,
        "esterni": external,
        "goto": data.count(b"/S /GoTo") + data.count(b"/S/GoTo"),
    }


def _neutralised_probe(body: bytes) -> bytes:
    """La sonda ha fatto il suo mestiere: ora deve sparire.

    Non si può cancellare un oggetto in un aggiornamento incrementale senza
    riscrivere anche l'array `/Annots` della pagina che lo cita — più oggetti
    toccati, più modi di sbagliare. La si svuota invece: stessa annotazione,
    niente più azione e rettangolo degenere. Un lettore non ci trova niente su
    cui cliccare, che è esattamente il punto."""
    return b"<<\n/Type /Annot\n/Subtype /Link\n/Rect [0 0 0 0]\n/Border [0 0 0]\n>>\n"


def _goto_body(body: bytes, page_obj: int, top: float) -> bytes:
    """Sostituisce l'azione `/URI` con una `/GoTo` verso una destinazione
    esplicita.

    `/XYZ null <top> null`: `null` su ascissa e zoom significa «non toccare».
    Un lettore che scorre a sinistra o cambia lo zoom sotto le mani del
    cliente ogni volta che segue un link è più fastidioso del link rotto."""
    action = (
        b"/A <<\n/Type /Action\n/S /GoTo\n/D ["
        + str(page_obj).encode("ascii")
        + b" 0 R /XYZ null "
        + f"{top:.2f}".encode("ascii")
        + b" null]\n>>\n"
    )
    # [CORRETTO 2026-08-02] Qui c'era `body.find(b"/A")`, che agganciava il
    # `/A` di `/Annot` — due righe più in su — e produceva `/Type /A << … >>`:
    # un PDF che pdfinfo rifiutava con «Dictionary key must be a name object».
    # Difetto trovato solo perché il file prodotto è stato riaperto, non perché
    # il codice sembrasse sbagliato.
    m = re.search(rb"/A\s*<<", body)
    if not m:
        return body
    start = m.start()
    # Fine del dizionario `/A << … >>`: si conta l'annidamento invece di
    # cercare il primo `>>`, che sarebbe quello interno.
    open_at = body.find(b"<<", start)
    if open_at == -1:
        return body
    depth, i = 0, open_at
    while i < len(body) - 1:
        pair = body[i:i + 2]
        if pair == b"<<":
            depth += 1
            i += 2
            continue
        if pair == b">>":
            depth -= 1
            i += 2
            if depth == 0:
                break
            continue
        i += 1
    else:
        return body
    return body[:start] + action + body[i:]


def _incremental_update(data: bytes, replacements: dict[int, bytes]) -> bytes:
    """Accoda gli oggetti riscritti, una nuova tabella xref e un trailer con
    `/Prev`. Il contenuto originale resta intatto in testa al file: se
    qualcosa qui è sbagliato, il peggio che può succedere è che il lettore
    ricada sulla revisione precedente."""
    m = re.search(rb"trailer\s*<<(.*?)>>\s*startxref\s+(\d+)", data[-3000:], re.DOTALL)
    if not m:
        raise ValueError("trailer non trovato")
    trailer_body = m.group(1)
    prev = int(m.group(2))

    root = re.search(rb"/Root\s+(\d+)\s+0\s+R", trailer_body)
    if not root:
        raise ValueError("/Root non trovato")
    info = re.search(rb"/Info\s+(\d+)\s+0\s+R", trailer_body)
    size = re.search(rb"/Size\s+(\d+)", trailer_body)
    if not size:
        raise ValueError("/Size non trovato")

    out = bytearray(data)
    if not out.endswith(b"\n"):
        out += b"\n"

    offsets: dict[int, int] = {}
    for num in sorted(replacements):
        offsets[num] = len(out)
        out += str(num).encode("ascii") + b" 0 obj\n"
        out += replacements[num].strip() + b"\n"
        out += b"endobj\n"

    xref_at = len(out)
    out += b"xref\n"
    nums = sorted(offsets)
    group: list[int] = []
    for num in nums + [None]:  # type: ignore[list-item]
        if group and (num is None or num != group[-1] + 1):
            out += f"{group[0]} {len(group)}\n".encode("ascii")
            for g in group:
                out += f"{offsets[g]:010d} {0:05d} n \n".encode("ascii")
            group = []
        if num is not None:
            group.append(num)

    out += b"trailer\n<<\n/Size " + size.group(1) + b"\n"
    out += b"/Root " + root.group(1) + b" 0 R\n"
    if info:
        out += b"/Info " + info.group(1) + b" 0 R\n"
    out += b"/Prev " + str(prev).encode("ascii") + b"\n>>\n"
    out += b"startxref\n" + str(xref_at).encode("ascii") + b"\n%%EOF\n"
    return bytes(out)


def repair_internal_links_bytes(data: bytes) -> tuple[bytes, dict]:
    """Versione pura (byte in, byte fuori) — è quella che i test esercitano.

    Ritorna `(dati, rapporto)`. Se non c'è niente da fare, o se qualcosa non
    torna, ritorna i dati IDENTICI a quelli in ingresso."""
    report = {"riscritti": 0, "sonde": 0, "non_risolte": [], "errore": None}
    try:
        pdf = _Pdf(data)
        pages = _page_order(pdf)
        if not pages:
            report["errore"] = "nessuna pagina"
            return data, report
        page_of: dict[int, int] = {}
        for index, page_num in enumerate(pages):
            for annot in _annots_of_page(pdf, page_num):
                page_of[annot] = index

        probes: dict[str, tuple[int, float]] = {}
        broken: list[tuple[int, str]] = []
        probe_objs: list[int] = []
        for num in pdf.objects:
            body = pdf.body(num)
            if b"/Subtype /Link" not in body and b"/Subtype/Link" not in body:
                continue
            uri = _uri_di(body)
            if uri is None:
                continue
            if uri.startswith(PROBE_PREFIX):
                probe_objs.append(num)
                name = unquote(uri[len(PROBE_PREFIX):]).strip("/")
                rect = _rect(body)
                if name and rect and num in page_of and name not in probes:
                    # `rect[3]` è il bordo ALTO del rettangolo in coordinate
                    # PDF (l'origine è in basso a sinistra): è lì che comincia
                    # la sezione, quindi è lì che deve atterrare il cliente.
                    probes[name] = (page_of[num], rect[3] + _TOP_PADDING)
                continue
            anchor = _anchor_of_uri(uri)
            if anchor:
                broken.append((num, anchor))

        replacements: dict[int, bytes] = {}
        unresolved: set[str] = set()
        for num, anchor in broken:
            target = probes.get(anchor)
            if target is None:
                unresolved.add(anchor)
                continue
            page_index, top = target
            page_obj = pages[page_index]
            new_body = _goto_body(pdf.body(num), page_obj, top)
            if new_body != pdf.body(num):
                replacements[num] = new_body

        for num in probe_objs:
            replacements[num] = _neutralised_probe(pdf.body(num))

        report["riscritti"] = sum(1 for n in replacements if n not in probe_objs)
        report["sonde"] = len(probe_objs)
        report["non_risolte"] = sorted(unresolved)

        if not replacements:
            return data, report
        return _incremental_update(data, replacements), report
    except Exception as exc:  # pragma: no cover - rete di sicurezza
        report["errore"] = f"{type(exc).__name__}: {exc}"
        return data, report


def repair_internal_links(pdf_path: str) -> dict:
    """Ripara i collegamenti interni del file indicato, sul posto.

    Non solleva mai. Se la riparazione fallisce, il file resta quello che
    wkhtmltopdf ha prodotto: link interni morti, ma documento leggibile."""
    report = {"riscritti": 0, "sonde": 0, "non_risolte": [], "errore": None}
    try:
        with open(pdf_path, "rb") as fh:
            data = fh.read()
    except OSError as exc:
        report["errore"] = f"lettura: {exc}"
        return report
    new_data, report = repair_internal_links_bytes(data)
    if new_data is data or new_data == data:
        return report
    try:
        with open(pdf_path, "wb") as fh:
            fh.write(new_data)
    except OSError as exc:
        report["errore"] = f"scrittura: {exc}"
    return report
