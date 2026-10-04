import re
from functools import lru_cache

import pandas as pd
import pgeocode
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from drf_spectacular.utils import extend_schema

from .serializers import RouteOptimizationRequestSerializer, RouteOptimizationResponseSerializer
from routing_service.fuel_optimizer import FuelOptimizerService

# Pre-warm singleton: ساخت ایندکس مکانی در رم هنگام لود ماژول جهت حذف کامل تاخیر اولیه
OPTIMIZER_SERVICE = FuelOptimizerService()

@lru_cache(maxsize=1)
def get_us_city_data():
    nomi = pgeocode.Nominatim('us')
    cities = nomi._data_frame[
        ['place_name', 'state_code', 'latitude', 'longitude']
    ].dropna(subset=['place_name', 'state_code', 'latitude', 'longitude']).copy()
    cities['place_name'] = cities['place_name'].str.strip()
    cities['state_code'] = cities['state_code'].str.strip()
    cities = cities[
        (cities['place_name'] != '') &
        (cities['state_code'] != '') &
        cities['latitude'].between(-90, 90) &
        cities['longitude'].between(-180, 180)
    ]
    return cities.drop_duplicates(subset=['place_name', 'state_code'])


class CitiesAutocompleteView(APIView):
    def get(self, request, *args, **kwargs):
        query = request.query_params.get('q', '').strip()
        if not query:
            return Response([], status=status.HTTP_200_OK)

        cities = get_us_city_data()
        matches = cities[
            cities['place_name'].str.contains(re.escape(query), case=False, na=False)
        ].copy()
        matches['_starts_with_query'] = matches['place_name'].str.lower().str.startswith(
            query.lower(), na=False
        )
        matches = matches.sort_values(
            ['_starts_with_query', 'place_name', 'state_code'],
            ascending=[False, True, True],
        ).head(8)

        return Response([
            {
                'city': row.place_name,
                'state': row.state_code,
                'display': f'{row.place_name}, {row.state_code}',
                'lat': float(row.latitude),
                'lon': float(row.longitude),
            }
            for row in matches.itertuples(index=False)
        ], status=status.HTTP_200_OK)


def resolve_location(loc_dict):
    if 'lat' in loc_dict and 'lon' in loc_dict:
        return float(loc_dict['lat']), float(loc_dict['lon'])

    name = loc_dict.get('location_name', '').strip()
    nomi = pgeocode.Nominatim('us')
    
    if ',' in name:
        city, state = [x.strip() for x in name.split(',', 1)]
        df = nomi._data_frame
        matched = df[
            (df['place_name'].str.upper() == city.upper()) & 
            (df['state_code'].str.upper() == state.upper())
        ]
        if not matched.empty:
            return float(matched.iloc[0]['latitude']), float(matched.iloc[0]['longitude'])

    res = nomi.query_location(name)
    if not res.empty and not pd.isna(res.iloc[0]['latitude']):
        return float(res.iloc[0]['latitude']), float(res.iloc[0]['longitude'])

    raise ValueError(f"Could not resolve US coordinates for location: '{name}'")

class OptimizeRouteView(APIView):
    @extend_schema(
        request=RouteOptimizationRequestSerializer,
        responses={200: RouteOptimizationResponseSerializer},
        description="High-performance route and fuel optimization under 500-mile vehicle range."
    )
    def post(self, request, *args, **kwargs):
        serializer = RouteOptimizationRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            start_coords = resolve_location(serializer.validated_data['start'])
            finish_coords = resolve_location(serializer.validated_data['finish'])
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        try:
            result = OPTIMIZER_SERVICE.plan_fuel_stops(start_coords, finish_coords)
            return Response(result, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({'error': f"Optimization failed: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
