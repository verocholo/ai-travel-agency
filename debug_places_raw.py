#!/usr/bin/env python3
"""
Script di DEBUG, non fa parte della pipeline (main.py). Stesso principio già
applicato a LiteAPI in debug_liteapi_raw.py — vedi la nota lì per il
razionale completo: `map_places_response()` in src/places_client.py è stato
scritto da documentazione, mai esercitato con una chiamata reale (Google
Places API New). Prima di fidarsi che il mapping sia corretto, guardiamo il
JSON vero con i nostri occhi.

Include anche il controllo di precisione del geocoding introdotto dopo il
bug reale scoperto in Fase 3 (LiteAPI): "Val d'Orcia, Toscana" è stato
geocodificato a 60-70km dal luogo reale nonostante uno status "OK" — vedi
src/geocoding.py::is_imprecise_match(). Qui lo controlliamo ESPLICITAMENTE
prima di interrogare Places, invece di scoprirlo a valle guardando risultati
strani.

Uso:
  python debug_places_raw.py "San Quirico d'Orcia, Toscana"
  python debug_places_raw.py "Firenze, Toscana" --radius 3000

Richiede GOOGLE_MAPS_KEY nel tuo .env (la stessa della pipeline).
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.config import SETTINGS
from src.geocoding import geocode_full, is_imprecise_match, GeocodingError
from src.places_client import fetch_nearby_raw, map_places_response


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", help='es. "San Quirico d\'Orcia, Toscana"')
    parser.add_argument("--radius", type=int, default=3000, help="raggio in metri (default 3000, Cap. 5.5)")
    args = parser.parse_args()

    if not SETTINGS.google_maps_key:
        print("❌ GOOGLE_MAPS_KEY mancante nel .env")
        sys.exit(1)

    print(f"\n{'=' * 70}\n1) GEOCODING — {args.destination!r}\n{'=' * 70}")
    try:
        geo = geocode_full(args.destination, SETTINGS.google_maps_key)
    except GeocodingError as e:
        print(f"❌ {e}")
        sys.exit(1)
    print(f"lat={geo['lat']}, lng={geo['lng']}")
    print(f"location_type={geo['location_type']}")
    print(f"formatted_address={geo['formatted_address']!r}")
    if is_imprecise_match(geo["location_type"]):
        print(
            f"⚠️  MATCH IMPRECISO (location_type={geo['location_type']}) — Google non ha "
            f"trovato un indirizzo puntuale per questo input, probabilmente perché è il "
            f"nome di un'area/valle/regione senza un centro univoco (stesso bug reale "
            f"scoperto con 'Val d'Orcia, Toscana' in Fase 3 — vedi CHANGELOG.md). Le "
            f"coordinate sotto potrebbero essere lontane dal luogo che intendevi. Se il "
            f"formatted_address sopra non corrisponde a quello che ti aspettavi, riprova "
            f"con un nome di comune/indirizzo più specifico."
        )

    print(f"\n{'=' * 70}\n2) GOOGLE PLACES (New) — searchNearby, raggio {args.radius}m\n{'=' * 70}")
    raw = fetch_nearby_raw(geo["lat"], geo["lng"], SETTINGS.google_maps_key, radius_m=args.radius)
    places = raw.get("places", [])
    print(f"Trovati {len(places)} POI candidati.")
    print(json.dumps(places[:3], indent=2, ensure_ascii=False))
    if len(places) > 3:
        print(f"... e altri {len(places) - 3} (troncato per leggibilità, JSON completo sopra per i primi 3)")
    if not places:
        print("⚠️  ZERO POI trovati in questo raggio.")
        return

    print(f"\n{'=' * 70}\n3) VERIFICA del mapping (map_places_response)\n{'=' * 70}")
    pois = map_places_response(raw)
    print(f"Mappati {len(pois)} POI su {len(places)} candidati grezzi.")
    for p in pois:
        print(
            f"  - {p.id[:20]:22} {p.name[:35]:37} type={p.type:10} "
            f"energy_tag={p.energy_tag:6} open_days={p.open_days}"
        )
    print(
        "\nControlla a occhio: `type`/`energy_tag` sono euristiche NOSTRE su "
        "`primaryType` (non dati di Google) — se molti POI finiscono con "
        "energy_tag=MEDIUM di default o type=activity di default, potrebbe "
        "voler dire che i `primaryType` reali restituiti da Google non "
        "coincidono con quelli previsti in _ENERGY_LOOKUP/_TYPE_NORMALIZE "
        "(src/places_client.py) — in quel caso vanno estesi con i valori "
        "reali osservati qui sopra nel JSON grezzo."
    )


if __name__ == "__main__":
    main()
