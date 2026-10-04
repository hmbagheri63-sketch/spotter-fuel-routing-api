from rest_framework import serializers

class LocationInputSerializer(serializers.Serializer):
    lat = serializers.FloatField(required=False)
    lon = serializers.FloatField(required=False)
    location_name = serializers.CharField(required=False, max_length=150)

    def validate(self, data):
        has_coords = 'lat' in data and 'lon' in data
        has_name = 'location_name' in data and data.get('location_name', '').strip() != ''
        if not has_coords and not has_name:
            raise serializers.ValidationError(
                "Either coordinates (lat and lon) or a location_name must be provided."
            )
        return data

class RouteOptimizationRequestSerializer(serializers.Serializer):
    start = LocationInputSerializer(help_text="Start location coordinates or city name")
    finish = LocationInputSerializer(help_text="Finish location coordinates or city name")

class FuelStopSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    address = serializers.CharField()
    city = serializers.CharField()
    state = serializers.CharField()
    price = serializers.FloatField()
    latitude = serializers.FloatField()
    longitude = serializers.FloatField()
    route_mile = serializers.FloatField()
    gallons_refueled = serializers.FloatField()
    cost_at_stop = serializers.FloatField()

class RouteOptimizationResponseSerializer(serializers.Serializer):
    total_distance_miles = serializers.FloatField()
    total_fuel_cost = serializers.FloatField()
    unoptimized_fuel_cost = serializers.FloatField()
    total_savings_usd = serializers.FloatField()
    total_gallons_consumed = serializers.FloatField()
    fuel_stops_count = serializers.IntegerField()
    fuel_stops = FuelStopSerializer(many=True)
    route_geojson = serializers.DictField()
