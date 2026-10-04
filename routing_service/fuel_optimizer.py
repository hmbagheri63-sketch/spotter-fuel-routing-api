import json
import logging
import math
import os
import tempfile
import threading
import time

import requests
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_PATH = os.path.join(BASE_DIR, 'data', 'fuel_stations_geocoded.csv')
CACHE_PATH = os.path.join(BASE_DIR, 'data', 'route_cache.json')

VEHICLE_RANGE_MILES = 500.0
VEHICLE_MPG = 10.0
MAX_DETOUR_MILES = 15.0
MIN_STOP_INTERVAL_MILES = 320.0
CACHE = {}
CACHE_LOCK = threading.RLock()
PREWARM_LOCK = threading.Lock()
LOGGER = logging.getLogger(__name__)
DEMO_ROUTES = (
    ((40.71, -74.01), (34.05, -118.24)),
    ((47.61, -122.33), (25.76, -80.19)),
    ((41.88, -87.63), (29.76, -95.37)),
)


def load_route_cache():
    try:
        with open(CACHE_PATH, 'r', encoding='utf-8') as cache_file:
            persisted_cache = json.load(cache_file)
        if not isinstance(persisted_cache, dict):
            raise ValueError("Route cache must contain a JSON object.")
    except FileNotFoundError:
        return
    except (json.JSONDecodeError, ValueError):
        LOGGER.exception("Could not load route cache from %s.", CACHE_PATH)
        return
    except OSError:
        LOGGER.exception("Could not read route cache from %s.", CACHE_PATH)
        return

    with CACHE_LOCK:
        CACHE.update(persisted_cache)


def persist_route_cache():
    cache_dir = os.path.dirname(CACHE_PATH)
    temporary_path = None
    try:
        with CACHE_LOCK:
            os.makedirs(cache_dir, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode='w',
                encoding='utf-8',
                dir=cache_dir,
                delete=False,
            ) as cache_file:
                temporary_path = cache_file.name
                json.dump(CACHE, cache_file)
            os.replace(temporary_path, CACHE_PATH)
    except OSError:
        LOGGER.exception("Could not persist route cache to %s.", CACHE_PATH)
        if temporary_path and os.path.exists(temporary_path):
            os.unlink(temporary_path)


def prewarm_demo_routes(service):
    for start_coords, finish_coords in DEMO_ROUTES:
        try:
            service.plan_fuel_stops(start_coords, finish_coords)
        except Exception:
            LOGGER.exception(
                "Could not pre-warm demo route from %s to %s.",
                start_coords,
                finish_coords,
            )

def haversine_vectorized(lat1, lon1, lat2_arr, lon2_arr):
    R = 3958.8
    phi1, phi2 = np.radians(lat1), np.radians(lat2_arr)
    dphi = np.radians(lat2_arr - lat1)
    dlambda = np.radians(lon2_arr - lon1)
    a = np.sin(dphi / 2)**2 + np.cos(phi1) * np.cos(phi2) * np.sin(dlambda / 2)**2
    return 2 * R * np.arctan2(np.sqrt(a), np.sqrt(1 - a))

class FuelOptimizerService:
    def __init__(self):
        if not os.path.exists(CSV_PATH):
            raise FileNotFoundError(f"Geocoded fuel stations not found at: {CSV_PATH}")
        self.df = pd.read_csv(CSV_PATH)
        load_route_cache()
        print(f"[FuelOptimizerService] Loaded {len(self.df)} fuel stations.")

    def start_prewarming(self):
        if PREWARM_LOCK.locked():
            return

        def prewarm():
            try:
                prewarm_demo_routes(self)
            finally:
                PREWARM_LOCK.release()

        if PREWARM_LOCK.acquire(blocking=False):
            thread = threading.Thread(
                target=prewarm,
                name='route-cache-prewarm',
                daemon=True,
            )
            thread.start()

    def get_route_osrm(self, start_coords, finish_coords):
        # درخواست با overview=simplified جهت کاهش ۹۸ درصدی پهنای باند و کاهش زمان پاسخ به کمتر از ۱ ثانیه
        url = (
            f"https://router.project-osrm.org/route/v1/driving/"
            f"{start_coords[1]},{start_coords[0]};{finish_coords[1]},{finish_coords[0]}"
            f"?overview=simplified&geometries=geojson"
        )
        headers = {'User-Agent': 'SpotterFuelRouter/1.0'}
        resp = requests.get(url, headers=headers, timeout=12)
        resp.raise_for_status()
        data = resp.json()

        if data.get('code') != 'Ok' or not data.get('routes'):
            raise ValueError("Route calculation failed via OSRM.")

        route = data['routes'][0]
        distance_miles = route['distance'] * 0.000621371
        coordinates = route['geometry']['coordinates']

        return {
            'distance_miles': distance_miles,
            'geojson': route['geometry'],
            'coordinates': [(c[1], c[0]) for c in coordinates]
        }

    def plan_fuel_stops(self, start_coords, finish_coords):
        cache_key = (
            f"{round(start_coords[0], 2)},{round(start_coords[1], 2)}->"
            f"{round(finish_coords[0], 2)},{round(finish_coords[1], 2)}"
        )
        with CACHE_LOCK:
            if cache_key in CACHE:
                return CACHE[cache_key]

        t0 = time.perf_counter()
        route_data = self.get_route_osrm(start_coords, finish_coords)
        t1 = time.perf_counter()
        total_distance = route_data['distance_miles']
        coords = route_data['coordinates']

        c_arr = np.array(coords)
        lat_arr, lon_arr = c_arr[:, 0], c_arr[:, 1]

        # فواصل گره‌های خط سیر
        dists = haversine_vectorized(lat_arr[:-1], lon_arr[:-1], lat_arr[1:], lon_arr[1:])
        cumulative_distances = np.concatenate([[0.0], np.cumsum(dists)])

        route_rad = np.radians(c_arr)
        route_tree = cKDTree(route_rad)
        station_rad = np.radians(self.df[['latitude', 'longitude']].values)
        dists_rad, nearest_indices = route_tree.query(station_rad, k=1)
        dists_miles = dists_rad * 3958.8

        valid_mask = dists_miles <= MAX_DETOUR_MILES
        filtered_df = self.df[valid_mask].copy()
        filtered_df['route_mile'] = cumulative_distances[nearest_indices[valid_mask]]
        filtered_df.sort_values('route_mile', inplace=True)

        # الگوریتم تخصیص توقف بهینه
        selected_stops = []
        current_mile = 0.0
        remaining_fuel_miles = VEHICLE_RANGE_MILES
        total_optimized_cost = 0.0

        while (total_distance - current_mile) > remaining_fuel_miles:
            max_reachable = current_mile + remaining_fuel_miles
            safety_target = max_reachable - 30.0
            search_start = current_mile + MIN_STOP_INTERVAL_MILES

            valid_stations = filtered_df[
                filtered_df['route_mile'].between(search_start, safety_target)
            ]
            if valid_stations.empty:
                valid_stations = filtered_df[
                    (filtered_df['route_mile'] > current_mile + 100.0) &
                    (filtered_df['route_mile'] <= max_reachable)
                ]

            if valid_stations.empty:
                break

            best_station = valid_stations.loc[valid_stations['Retail Price'].idxmin()]

            distance_leg = best_station['route_mile'] - current_mile
            price = float(best_station['Retail Price'])
            gallons = distance_leg / VEHICLE_MPG
            leg_cost = gallons * price
            total_optimized_cost += leg_cost

            stop_item = {
                'id': int(best_station['OPIS Truckstop ID']),
                'name': str(best_station['Truckstop Name']).strip(),
                'address': str(best_station['Address']).strip(),
                'city': str(best_station['City']).strip(),
                'state': str(best_station['State']).strip(),
                'price': price,
                'latitude': float(best_station['latitude']),
                'longitude': float(best_station['longitude']),
                'route_mile': float(best_station['route_mile']),
            }
            stop_item['gallons_refueled'] = round(gallons, 2)
            stop_item['cost_at_stop'] = round(leg_cost, 2)
            selected_stops.append(stop_item)

            current_mile = float(best_station['route_mile'])
            remaining_fuel_miles = VEHICLE_RANGE_MILES

        final_leg_distance = total_distance - current_mile
        final_price = selected_stops[-1]['price'] if selected_stops else float(self.df['Retail Price'].median())
        total_optimized_cost += (final_leg_distance / VEHICLE_MPG) * final_price

        avg_retail_price = float(self.df['Retail Price'].mean())
        unoptimized_cost = (total_distance / VEHICLE_MPG) * avg_retail_price
        total_savings = max(0.0, unoptimized_cost - total_optimized_cost)

        result = {
            'total_distance_miles': round(total_distance, 2),
            'total_fuel_cost': round(total_optimized_cost, 2),
            'unoptimized_fuel_cost': round(unoptimized_cost, 2),
            'total_savings_usd': round(total_savings, 2),
            'total_gallons_consumed': round(total_distance / VEHICLE_MPG, 2),
            'fuel_stops_count': len(selected_stops),
            'fuel_stops': selected_stops,
            'route_geojson': route_data['geojson']
        }
        t2 = time.perf_counter()
        print(f"[OSRM Call] Took {t1 - t0:.2f}s")
        print(f"[Python Optimization] Took {t2 - t1:.4f}s")
        with CACHE_LOCK:
            CACHE[cache_key] = result
        persist_route_cache()
        return result
