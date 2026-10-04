from contextlib import redirect_stdout
from io import StringIO
import os
import tempfile
from unittest.mock import patch

import numpy as np
import pandas as pd
from django.test import SimpleTestCase
from django.urls import resolve

from . import fuel_optimizer
from .fuel_optimizer import CACHE, DEMO_ROUTES, FuelOptimizerService, haversine_vectorized


class FuelOptimizerProjectionTests(SimpleTestCase):
    def setUp(self):
        CACHE.clear()
        self.cache_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.cache_directory.cleanup)
        self.cache_path_patcher = patch(
            'routing_service.fuel_optimizer.CACHE_PATH',
            os.path.join(self.cache_directory.name, 'route_cache.json'),
        )
        self.cache_path_patcher.start()
        self.addCleanup(self.cache_path_patcher.stop)

    def test_vectorized_projection_feeds_greedy_stop_selection(self):
        service = object.__new__(FuelOptimizerService)
        service.df = pd.DataFrame([
            {
                'OPIS Truckstop ID': 1,
                'Truckstop Name': 'Stop One',
                'Address': '1 Main',
                'City': 'Test',
                'State': 'TX',
                'Retail Price': 3.00,
                'latitude': 0.1,
                'longitude': 6.0,
            },
            {
                'OPIS Truckstop ID': 2,
                'Truckstop Name': 'Stop Two',
                'Address': '2 Main',
                'City': 'Test',
                'State': 'TX',
                'Retail Price': 2.50,
                'latitude': 0.1,
                'longitude': 12.0,
            },
            {
                'OPIS Truckstop ID': 3,
                'Truckstop Name': 'Too Far',
                'Address': '3 Main',
                'City': 'Test',
                'State': 'TX',
                'Retail Price': 1.00,
                'latitude': 1.0,
                'longitude': 6.0,
            },
        ])
        coords = [(0.0, float(lon)) for lon in range(0, 17, 3)]
        segment_miles = haversine_vectorized(
            0.0, 0.0, np.array([0.0]), np.array([3.0])
        )[0]
        route_data = {
            'distance_miles': 1104.0,
            'coordinates': coords,
            'geojson': {'type': 'LineString', 'coordinates': []},
        }

        with patch.object(service, 'get_route_osrm', return_value=route_data):
            result = service.plan_fuel_stops((0, 0), (0, 16))

        self.assertEqual([stop['id'] for stop in result['fuel_stops']], [1, 2])
        self.assertAlmostEqual(
            result['fuel_stops'][0]['route_mile'], 2 * segment_miles
        )
        self.assertAlmostEqual(
            result['fuel_stops'][1]['route_mile'], 4 * segment_miles
        )

    def test_plan_result_is_cached_by_rounded_coordinates(self):
        service = object.__new__(FuelOptimizerService)
        service.df = pd.DataFrame([
            {'latitude': 0.0, 'longitude': 0.0, 'Retail Price': 3.0},
        ])
        route_data = {
            'distance_miles': 100.0,
            'coordinates': [(0.0, 0.0), (0.0, 1.0)],
            'geojson': {'type': 'LineString', 'coordinates': []},
        }

        with patch.object(service, 'get_route_osrm', return_value=route_data) as osrm:
            output = StringIO()
            with redirect_stdout(output):
                first_result = service.plan_fuel_stops((0.001, 0.001), (0.0, 1.0))
                second_result = service.plan_fuel_stops((0.002, 0.002), (0.0, 1.0))

        self.assertIs(first_result, second_result)
        osrm.assert_called_once()
        self.assertIn('[OSRM Call] Took ', output.getvalue())
        self.assertIn('[Python Optimization] Took ', output.getvalue())

    def test_route_cache_persists_and_loads_from_json(self):
        CACHE['test-route'] = {'total_distance_miles': 123.0}

        fuel_optimizer.persist_route_cache()
        CACHE.clear()
        fuel_optimizer.load_route_cache()

        self.assertEqual(CACHE, {'test-route': {'total_distance_miles': 123.0}})

    def test_prewarm_helper_calculates_all_demo_routes(self):
        service = object.__new__(FuelOptimizerService)
        with patch.object(service, 'plan_fuel_stops') as plan_route:
            fuel_optimizer.prewarm_demo_routes(service)

        self.assertEqual(
            [call.args for call in plan_route.call_args_list],
            list(DEMO_ROUTES),
        )

    def test_route_endpoint_resolves_with_or_without_trailing_slash(self):
        self.assertEqual(resolve('/api/route').url_name, 'optimize-route-no-slash')
        self.assertEqual(resolve('/api/route/').url_name, 'optimize-route')
