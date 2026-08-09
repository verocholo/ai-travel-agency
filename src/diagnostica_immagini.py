"""
Prova a costo quasi zero delle cartine e delle fotografie vere — task #188.

IL PROBLEMA CHE QUESTO MODULO RISOLVE

Le cartine di Google e le fotografie dei luoghi sono le due cose che, quando
non funzionano, non si rompono: degradano. Il documento esce lo stesso, con
la cartina schematica disegnata in casa e con le copertine illustrate al
posto delle foto, e nessuno se ne accorge finche' non guarda il PDF finito.
E' il modo peggiore di rompersi, perche' non lascia tracce.

Finora l'unico modo di scoprire che una delle due API era spenta era
generare un itinerario vero: circa 1,50 euro di chiamate e quattro minuti di
attesa, per leggere alla fine una cartina disegnata a mano. Qui la stessa
risposta costa circa quattro centesimi e arriva in dieci secondi.

PERCHE' NON BASTA GUARDARE SE LA VARIABILE C'E'

`/v1/diagnostica` dice se `GOOGLE_MAPS_KEY` e' impostata. Non e' la stessa
domanda. Una chiave puo' esserci ed essere perfettamente valida, e le
cartine non uscire lo stesso, per tre motivi diversi che si sistemano in tre
posti diversi della console Google:

  1. la API "Maps Static API" non e' abilitata su quel progetto;
  2. la chiave ha una restrizione per API che esclude proprio quella;
  3. il progetto non ha la fatturazione attiva.

Tutti e tre danno lo stesso sintomo — nessuna cartina — e nessuno dei tre si
vede dalla presenza della variabile. L'unico modo di distinguerli e'
chiamare l'API vera e leggere cosa risponde, ed e' quello che si fa qui.

SICUREZZA

Il messaggio d'errore di una chiamata HTTP porta con se' la URL, e la URL
della Static Maps porta con se' la chiave in chiaro come parametro `key=`.
Una diagnostica che stampa l'errore grezzo e' una diagnostica che regala la
chiave a chiunque legga la risposta. Ogni testo che esce di qui passa da
`_pulisci()`, che applica la redazione condivisa E cancella il valore
letterale della chiave, per il caso in cui comparisse in una forma che le
espressioni regolari non riconoscono.
"""
from __future__ import annotations

import requests

from . import maps_static
from . import places_client
from . import redaction
from . import wikimedia


# Un punto fisso e famoso, scelto perche' su Wikimedia Commons ha di sicuro
# delle fotografie libere e su Google ha di sicuro dei luoghi attorno: se la
# prova fallisce qui, non e' colpa del posto.
PUNTO_DI_PROVA = (43.3186, 11.3316)  # Piazza del Campo, Siena
NOME_DI_PROVA = "Piazza del Campo"

# Il costo delle tre prove, in euro, dai listini di Google. Serve a dire in
# faccia a chi la lancia quanto sta spendendo: una diagnostica che costa e
# non lo dichiara e' una diagnostica che si smette di usare il giorno in cui
# si scopre il conto.
COSTO_CARTINA_EUR = 0.002
COSTO_RICERCA_EUR = 0.030
COSTO_FOTO_EUR = 0.007


def _pulisci(testo: object, api_key: str | None) -> str:
    """Nessun messaggio esce da qui con dentro la chiave.

    Due difese invece di una, perche' fanno due lavori diversi:
    `redact_secrets` riconosce le FORME note in cui un segreto viaggia
    (`key=...`, l'intestazione `X-Goog-Api-Key`), mentre la sostituzione
    letterale prende il valore anche dentro una frase che nessuna
    espressione regolare si aspettava. La prima protegge dai casi previsti,
    la seconda dai casi nuovi.
    """
    pulito = redaction.redact_secrets(str(testo))
    chiave = (api_key or "").strip()
    # La soglia sugli otto caratteri evita che una chiave vuota o assurda
    # trasformi ogni singola lettera del messaggio in "[nascosto]".
    if len(chiave) >= 8:
        pulito = pulito.replace(chiave, "[chiave nascosta]")
    return pulito[:400]


def _spento(nome: str, come: str) -> dict:
    return {
        "prova": nome,
        "esito": "non provato",
        "dettaglio": "manca la chiave Google: non c'e' niente da provare",
        "byte_ricevuti": None,
        "costo_eur": 0.0,
        "come_si_sistema": come,
    }


def _leggi_errore_google(testo: str) -> str | None:
    """Traduce in italiano i tre errori che contano davvero.

    Google risponde in inglese e con nomi di codice (`REQUEST_DENIED`,
    `API_KEY_SERVICE_BLOCKED`, `PERMISSION_DENIED`) che dicono la cosa
    giusta a chi li conosce gia'. Chi sta guardando questa risposta e'
    Lorenzo, che deve sapere QUALE casella spuntare nella console — non
    quale costante ha restituito il server.
    """
    t = (testo or "").lower()
    if "api_key_service_blocked" in t or "not authorized to use this api" in t:
        return ("la chiave e' valida ma questa API non le e' permessa: nella "
                "console Google, Credenziali -> la tua chiave -> Restrizioni "
                "API, aggiungi 'Maps Static API' e 'Places API (New)' oppure "
                "scegli 'Non limitare la chiave'")
    if "has not been used in project" in t or "is disabled" in t or \
            "service_disabled" in t:
        return ("la API non e' abilitata su questo progetto: nella console "
                "Google, API e servizi -> Abilita API, cerca il nome che "
                "compare nell'errore e premi Abilita")
    if "billing" in t:
        return ("il progetto Google non ha la fatturazione attiva: senza "
                "quella queste API rispondono errore anche con la chiave "
                "giusta")
    if "api key not valid" in t or "invalid_argument" in t or \
            "api_key_invalid" in t:
        return ("la chiave non e' valida: probabilmente e' stata copiata "
                "male, oppure e' stata cancellata dalla console")
    if "permission_denied" in t or "request_denied" in t:
        return ("Google ha rifiutato la richiesta: quasi sempre e' l'API non "
                "abilitata oppure una restrizione sulla chiave")
    return None


def prova_cartina(api_key: str | None) -> dict:
    """Una sola chiamata a Static Maps, con un solo segnaposto.

    Piu' piccola possibile — 200x150 pixel — perche' il prezzo di Static Maps
    non dipende dalla dimensione ma il tempo di risposta si', e questa prova
    deve poter essere lanciata senza pensarci.
    """
    if not (api_key or "").strip():
        return _spento(
            "cartina Google (Maps Static API)",
            "imposta GOOGLE_MAPS_KEY su Render",
        )
    url = maps_static.build_static_map_url(
        markers_by_style=[{"color": "red", "label": "1",
                           "points": [PUNTO_DI_PROVA]}],
        paths=[],
        api_key=api_key,
        size="200x150",
    )
    if not url:
        # Non puo' succedere con un segnaposto passato a mano, ma una
        # diagnostica che va in errore mentre diagnostica e' inutile due volte.
        return {
            "prova": "cartina Google (Maps Static API)",
            "esito": "errore",
            "dettaglio": "non sono riuscito a costruire la richiesta",
            "byte_ricevuti": None,
            "costo_eur": 0.0,
            "come_si_sistema": None,
        }
    try:
        png = maps_static.fetch_static_map_png(url, timeout=15)
    except Exception as e:  # noqa: BLE001 — vedi docstring del modulo
        grezzo = _pulisci(e, api_key)
        return {
            "prova": "cartina Google (Maps Static API)",
            "esito": "errore",
            "dettaglio": grezzo,
            "byte_ricevuti": None,
            "costo_eur": COSTO_CARTINA_EUR,
            "come_si_sistema": _leggi_errore_google(grezzo),
        }
    return {
        "prova": "cartina Google (Maps Static API)",
        "esito": "ok",
        "dettaglio": f"ricevuta un'immagine di {len(png)} byte: le cartine "
                     f"vere funzionano",
        "byte_ricevuti": len(png),
        "costo_eur": COSTO_CARTINA_EUR,
        "come_si_sistema": None,
    }


def prova_foto_google(api_key: str | None) -> dict:
    """Due chiamate: trova un luogo, poi scarica la sua fotografia.

    Servono entrambe perche' il riferimento a una fotografia di Google scade:
    non si puo' tenerne uno scritto qui dentro e riusarlo. E' anche il motivo
    per cui questa e' la prova piu' cara delle tre.
    """
    nome = "fotografie Google (Places API New)"
    if not (api_key or "").strip():
        return _spento(nome, "imposta GOOGLE_MAPS_KEY su Render")
    lat, lng = PUNTO_DI_PROVA
    try:
        grezzo = places_client.fetch_nearby_raw(
            lat, lng, api_key, radius_m=300, max_results=1,
        )
    except Exception as e:  # noqa: BLE001
        testo = _pulisci(e, api_key)
        return {
            "prova": nome,
            "esito": "errore",
            "dettaglio": f"la ricerca dei luoghi non ha risposto: {testo}",
            "byte_ricevuti": None,
            "costo_eur": COSTO_RICERCA_EUR,
            "come_si_sistema": _leggi_errore_google(testo),
        }
    punti = places_client.map_places_response(grezzo)
    riferimento = next(
        (p.photo_ref for p in punti if getattr(p, "photo_ref", None)), None,
    )
    if not riferimento:
        # Caso vero e diverso dagli altri: le API rispondono, ma su quel
        # posto Google non ha fotografie. Chiamarlo "errore" manderebbe a
        # cercare un guasto che non c'e'.
        return {
            "prova": nome,
            "esito": "parziale",
            "dettaglio": "la ricerca dei luoghi funziona, ma per questo punto "
                         "Google non ha restituito nessuna fotografia",
            "byte_ricevuti": None,
            "costo_eur": COSTO_RICERCA_EUR,
            "come_si_sistema": None,
        }
    immagine = places_client.fetch_place_photo(riferimento, api_key, 400)
    if not immagine:
        return {
            "prova": nome,
            "esito": "errore",
            "dettaglio": "il luogo dichiara una fotografia ma lo scaricamento "
                         "non ha prodotto un'immagine",
            "byte_ricevuti": None,
            "costo_eur": COSTO_RICERCA_EUR + COSTO_FOTO_EUR,
            "come_si_sistema": _leggi_errore_google("permission_denied"),
        }
    return {
        "prova": nome,
        "esito": "ok",
        "dettaglio": f"scaricata una fotografia di {len(immagine)} byte: le "
                     f"foto di Google funzionano",
        "byte_ricevuti": len(immagine),
        "costo_eur": COSTO_RICERCA_EUR + COSTO_FOTO_EUR,
        "come_si_sistema": None,
    }


def prova_wikimedia() -> dict:
    """La sorgente principale delle fotografie, e non costa niente.

    Non ha chiavi, non ha quote e non ha fatturazione: se questa fallisce e'
    la rete del servizio a non uscire, il che e' un'informazione diversa e
    piu' grave delle altre due.
    """
    nome = "fotografie libere (Wikimedia Commons)"
    esito = wikimedia.cerca_immagine(NOME_DI_PROVA, contesto="Siena")
    if esito is None:
        return {
            "prova": nome,
            "esito": "errore",
            "dettaglio": "nessuna risposta da Wikimedia: se anche le prove "
                         "Google falliscono, il servizio non sta uscendo in "
                         "rete affatto",
            "byte_ricevuti": None,
            "costo_eur": 0.0,
            "come_si_sistema": "controlla che il servizio abbia rete in uscita",
        }
    return {
        "prova": nome,
        "esito": "ok",
        "dettaglio": f"trovata «{esito.titolo}» di {len(esito.byte)} byte, "
                     f"licenza {esito.licenza}",
        "byte_ricevuti": len(esito.byte),
        "costo_eur": 0.0,
        "come_si_sistema": None,
    }


def esegui(api_key: str | None, *, solo: str | None = None) -> dict:
    """Le tre prove, oppure una sola se `solo` la nomina.

    `solo` esiste per un motivo pratico: la prova delle fotografie di Google
    costa quindici volte quella della cartina, e chi sta sistemando solo le
    cartine non ha nessun motivo di pagarla ogni volta che ricontrolla.
    """
    scelta = (solo or "").strip().lower()
    prove: list[dict] = []
    if scelta in ("", "tutto", "cartina"):
        prove.append(prova_cartina(api_key))
    if scelta in ("", "tutto", "foto"):
        prove.append(prova_wikimedia())
        prove.append(prova_foto_google(api_key))

    if not prove:
        return {
            "errore": f"non so cosa provare: «{scelta}». "
                      f"Valori accettati: tutto, cartina, foto",
        }

    ok = sum(1 for p in prove if p["esito"] == "ok")
    costo = round(sum(p["costo_eur"] for p in prove), 4)
    return {
        "prove_riuscite": f"{ok}/{len(prove)}",
        "costo_di_questa_verifica_eur": costo,
        # La riga da leggere per prima quando qualcosa non va: un elenco di
        # istruzioni, gia' in italiano, senza doverle ricavare dai dettagli.
        "da_fare": [p["come_si_sistema"] for p in prove
                    if p.get("come_si_sistema")],
        "dettaglio": prove,
    }
