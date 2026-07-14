#!/usr/bin/env python3
"""
Script di DEBUG, non fa parte della pipeline (main.py). Serve a un solo
scopo, deliberatamente ristretto: mostrare la risposta GREZZA e REALE di
LiteAPI, prima di fidarci del mapping difensivo scritto "alla cieca" in
src/liteapi_client.py (senza accesso di rete/chiave in fase di sviluppo,
vedi la nota di onestà in quel file e in HTTP_MODULES_REALI.md §Nodo 3).

Perché uno script a parte e non "lancia --mode live e vedi cosa succede":
select_anchor_hotel() è scritto per essere DIFENSIVO — se un campo non è
nella forma attesa, scarta quella entry invece di far crashare tutto
(vedi _extract_total_price()). Questo è corretto per la pipeline in
produzione (non deve fermarsi per un singolo hotel malformato), ma è
PERICOLOSO come primo test: potrebbe scartare in silenzio hotel validi con
un mapping sbagliato, e main.py --mode live sembrerebbe funzionare lo
stesso (magari con un solo hotel selezionato invece di 5) senza che tu te
ne accorga. Qui invece vediamo il JSON vero con i nostri occhi, PRIMA di
fidarci del codice difensivo.

Uso:
  python debug_liteapi_raw.py "Val d'Orcia, Toscana"
  python debug_liteapi_raw.py "Forte dei Marmi, Toscana" --checkin 2026-09-14 --checkout 2026-09-17

Richiede GOOGLE_MAPS_KEY e LITEAPI_KEY nel tuo .env (le stesse della pipeline).
"""
from __future__ import annotations
import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.config import SETTINGS
from src.geocoding import geocode_full, is_imprecise_match, GeocodingError
from src.liteapi_client import LiteApiClient, _extract_total_price, LiteApiError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", help='es. "Val d\'Orcia, Toscana"')
    parser.add_argument("--checkin", default=None, help="YYYY-MM-DD (default: oggi+30gg)")
    parser.add_argument("--checkout", default=None, help="YYYY-MM-DD (default: checkin+3gg)")
    args = parser.parse_args()

    missing = []
    if not SETTINGS.google_maps_key:
        missing.append("GOOGLE_MAPS_KEY")
    if not SETTINGS.liteapi_key:
        missing.append("LITEAPI_KEY")
    if missing:
        print(f"❌ Variabili mancanti nel .env: {missing}")
        sys.exit(1)

    checkin = args.checkin or (date.today() + timedelta(days=30)).isoformat()
    checkout = args.checkout or (date.fromisoformat(checkin) + timedelta(days=3)).isoformat()

    print(f"\n{'=' * 70}\n1) GEOCODING — {args.destination!r}\n{'=' * 70}")
    try:
        geo = geocode_full(args.destination, SETTINGS.google_maps_key)
    except GeocodingError as e:
        print(f"❌ {e}")
        sys.exit(1)
    lat, lng = geo["lat"], geo["lng"]
    print(f"lat={lat}, lng={lng}")
    print(f"location_type={geo['location_type']}, formatted_address={geo['formatted_address']!r}")
    if is_imprecise_match(geo["location_type"]):
        # [AGGIUNTO 2026-07-10, dopo il bug reale "Val d'Orcia, Toscana" ->
        # Certaldo/Gambassi Terme, 60-70km di errore] — vedi CHANGELOG.md.
        print(
            f"⚠️  MATCH IMPRECISO (location_type={geo['location_type']}) — controlla che "
            f"formatted_address sopra corrisponda davvero al luogo che intendevi PRIMA di "
            f"fidarti dei risultati sotto. Se è un nome di area/valle/regione senza un "
            f"centro univoco, riprova con un comune specifico."
        )

    print(f"\n{'=' * 70}\n2) LITEAPI — data/hotels (ricerca per geocode, raggio 5km)\n{'=' * 70}")
    client = LiteApiClient(SETTINGS.liteapi_key)
    hotels_geo = client.search_hotels_by_geocode(lat, lng)
    print(f"Trovati {len(hotels_geo)} hotel candidati.")
    print(json.dumps(hotels_geo[:3], indent=2, ensure_ascii=False))
    if len(hotels_geo) > 3:
        print(f"... e altri {len(hotels_geo) - 3} (troncato per leggibilità, JSON completo sopra per i primi 3)")
    if not hotels_geo:
        print("⚠️  ZERO hotel trovati in questo raggio — vedi discussione sotto sulla copertura.")
        return

    hotel_ids = [h["id"] for h in hotels_geo]
    print(f"\n{'=' * 70}\n3) LITEAPI — hotels/rates ({checkin} → {checkout})\n{'=' * 70}")
    offers = client.search_hotel_offers(hotel_ids, checkin, checkout)
    print(f"Risposta rates per {len(offers)} hotel.")
    print(json.dumps(offers[:2], indent=2, ensure_ascii=False))
    if len(offers) > 2:
        print(f"... e altri {len(offers) - 2} (troncato — JSON completo sopra per i primi 2)")

    print(f"\n{'=' * 70}\n4) VERIFICA del mapping difensivo (_extract_total_price)\n{'=' * 70}")
    ok, failed = 0, 0
    for entry in offers:
        try:
            price = _extract_total_price(entry)
            print(f"  ✅ hotelId={entry.get('hotelId')}: prezzo estratto correttamente = {price}")
            ok += 1
        except LiteApiError as e:
            print(f"  ❌ hotelId={entry.get('hotelId')}: {e}")
            failed += 1
    print(f"\nRiepilogo: {ok} estratti correttamente, {failed} scartati dal mapping attuale.")
    if failed:
        print(
            "⚠️  Alcuni hotel sono stati scartati dal mapping difensivo — significa che la "
            "forma reale di 'retailRate.total' non è tra quelle previste in "
            "src/liteapi_client.py::_extract_total_price(). Incolla l'output di questo "
            "script così aggiorniamo il mapping sulla forma vera, non su quella ipotizzata."
        )


if __name__ == "__main__":
    main()
