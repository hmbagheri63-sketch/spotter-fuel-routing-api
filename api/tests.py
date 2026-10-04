import json
from unittest.mock import patch

import pandas as pd
from django.test import TestCase
from django.urls import reverse


class CitiesAutocompleteTests(TestCase):
    @patch('api.views.get_us_city_data')
    def test_search_is_case_insensitive_and_prioritizes_prefixes(self, get_city_data):
        get_city_data.return_value = pd.DataFrame([
            {'place_name': 'North Austin', 'state_code': 'TX', 'latitude': 30.3, 'longitude': -97.7},
            {'place_name': 'Austin', 'state_code': 'TX', 'latitude': 30.2672, 'longitude': -97.7431},
        ])

        response = self.client.get(reverse('city-autocomplete'), {'q': 'AuS'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [
            {
                'city': 'Austin',
                'state': 'TX',
                'display': 'Austin, TX',
                'lat': 30.2672,
                'lon': -97.7431,
            },
            {
                'city': 'North Austin',
                'state': 'TX',
                'display': 'North Austin, TX',
                'lat': 30.3,
                'lon': -97.7,
            },
        ])

    @patch('api.views.get_us_city_data')
    def test_search_returns_at_most_eight_matches(self, get_city_data):
        get_city_data.return_value = pd.DataFrame([
            {
                'place_name': f'City {index} A',
                'state_code': 'TX',
                'latitude': 30.0,
                'longitude': -97.0,
            }
            for index in range(10)
        ])

        response = self.client.get(reverse('city-autocomplete'), {'q': 'a'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 8)


class RouteEndpointSlashTests(TestCase):
    @patch('api.views.OPTIMIZER_SERVICE.plan_fuel_stops', return_value={'ok': True})
    @patch(
        'api.views.resolve_location',
        side_effect=[(40.0, -74.0), (34.0, -118.0)] * 2,
    )
    def test_route_post_accepts_both_trailing_slash_forms(
        self,
        resolve_location,
        plan_fuel_stops,
    ):
        payload = {
            'start': {'lat': 40.0, 'lon': -74.0},
            'finish': {'lat': 34.0, 'lon': -118.0},
        }

        for path in ('/api/route/', '/api/route'):
            response = self.client.post(
                path,
                data=json.dumps(payload),
                content_type='application/json',
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {'ok': True})

        self.assertEqual(resolve_location.call_count, 4)
        self.assertEqual(plan_fuel_stops.call_count, 2)
