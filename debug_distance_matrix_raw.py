#!/usr/bin/env python3
"""
Script di DEBUG, non fa parte della pipeline (main.py). Stesso principio già
applicato a LiteAPI/Places — vedi debug_liteapi_raw.py per il razionale
completo: `map_distance_matrix_response()` in src/distance_matrix.py è stato
scritto da documentazione, mai esercitato con una chiamata reale.

Per testare la Distance Matrix serve un insieme di punti reali (id + coord).
Questo script li costruisce da soli passi già verificati: geocoding del
centro + una manciata di POI reali da Google Places (stesso identico
principio del Nodo 4.0: 1 "ancora" + POI). Non serve LiteAPI qui — il centro
geocodificato fa da sostituto dell'hotel-ancora solo per esercitare la
Distance Matrix in isolamento.

Uso:
  python debug_distance_matrix_raw.py "San Quirico d'Orcia, Toscana"
  python debug_distance_matrix_raw.py "Firenze, Toscana" --max-points 5

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
from src.distance_matrix import fetch_distance_matrix_raw, map_distance_matrix_response


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", help='es. "San Quirico d\'Orcia, Toscana"')
    parser.add_argument("--max-points", type=int, default=4, help="POI reali da includere oltre al centro (default 4)")
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
    print(f"lat={geo['lat']}, lng={geo['lng']}, location_type={geo['location_type']}")
    if is_imprecise_match(geo["location_type"]):
        print(f"⚠️  MATCH IMPRECISO — vedi debug_places_raw.py per il dettaglio del warning.")

    print(f"\n{'=' * 70}\n2) POI reali da Places (per costruire punti veri, non finti)\n{'=' * 70}")
    places_raw = fetch_nearby_raw(geo["lat"], geo["lng"], SETTINGS.google_maps_key)
    pois = map_places_response(places_raw)[: args.max_points]
    if not pois:
        print("❌ Zero POI trovati — impossibile costruire una matrice con >= 2 punti. Interrompo.")
        sys.exit(1)
    print(f"Uso {len(pois)} POI reali + 1 centro geocodificato come punti della matrice.")

    points = [{"id": "CENTRO", "coord": f"{geo['lat']},{geo['lng']}"}]
    for p in pois:
        points.append({"id": p.id, "coord": p.coord})
    for pt in points:
        print(f"  - {pt['id'][:24]:26} {pt['coord']}")

    # [AGGIORNATO 2026-07-11 — capstone live test] Prima questo script
    # interrogava SOLO mode="driving", come faceva anche la pipeline vera
    # prima del fix — vedi la nota estesa in src/distance_matrix.py sul bug
    # reale scoperto a San Marino (centro storico pedonale, "in auto" tornava
    # sempre 0 minuti). Ora verifica ENTRAMBE le modalità, proprio come fa
    # ora get_distance_matrix_multi_mode() nella pipeline reale.
    for mode in ("driving", "walking"):
        print(f"\n{'=' * 70}\n3) GOOGLE DISTANCE MATRIX (mode={mode}) — {len(points)}x{len(points)} punti\n{'=' * 70}")
        raw = fetch_distance_matrix_raw(points, SETTINGS.google_maps_key, mode=mode)
        print(f"status={raw.get('status')}")
        print(json.dumps(raw, indent=2, ensure_ascii=False)[:3000])
        if len(json.dumps(raw)) > 3000:
            print("... (troncato per leggibilità, JSON completo sopra)")

        if raw.get("status") != "OK":
            print(f"❌ status non OK per mode={mode}, mapping saltato per questa modalità.")
            continue

        print(f"\n{'=' * 70}\n4) VERIFICA del mapping (mode={mode})\n{'=' * 70}")
        travel_times = map_distance_matrix_response(raw, points, mode=mode)
        print(f"Mappati {len(travel_times)} tragitti su {len(points) * (len(points) - 1)} possibili (diagonale esclusa).")
        for tt in travel_times:
            print(f"  - {tt.origin_id[:20]:22} -> {tt.dest_id[:20]:22} {tt.minutes:4} min ({tt.mode})")
        missing = len(points) * (len(points) - 1) - len(travel_times)
        if missing:
            print(
                f"\n⚠️  {missing} tragitti attesi non sono comparsi nel risultato mappato ({mode}) — "
                f"controlla il JSON grezzo sopra per gli status diversi da 'OK' su quegli "
                f"elementi (es. ZERO_RESULTS se un punto non è raggiungibile in quella modalità)."
            )


if __name__ == "__main__":
    main()
