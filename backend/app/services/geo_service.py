"""
Geodesic Haversine Distance & Classroom GPS Geofence Verification Service.
"""
import math
from typing import Tuple

EARTH_RADIUS_METERS = 6_371_000.0


def haversine_distance_meters(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Computes great-circle distance in meters between two WGS84 coordinates."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)

    a = math.sin(d_phi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2.0) ** 2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return EARTH_RADIUS_METERS * c


def check_geofence(
    student_lat: float,
    student_lng: float,
    target_lat: float,
    target_lng: float,
    radius_meters: float,
) -> Tuple[bool, float]:
    dist = haversine_distance_meters(student_lat, student_lng, target_lat, target_lng)
    return dist <= radius_meters, round(dist, 2)
