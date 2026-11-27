import { Geolocation } from '@capacitor/geolocation';
import { isNativePlatform } from './platformService';

export interface GeoCoordinatesResult {
  latitude: number;
  longitude: number;
  accuracy: number;
  timestamp: number;
}

/**
 * Unified GPS service:
 * - Native (Android / iOS): Uses @capacitor/geolocation with explicit runtime permission check.
 * - Web: Uses HTML5 navigator.geolocation with high accuracy.
 */
export async function getCurrentGeoPosition(): Promise<GeoCoordinatesResult> {
  if (isNativePlatform()) {
    const perm = await Geolocation.checkPermissions();
    if (perm.location !== 'granted' && perm.coarseLocation !== 'granted') {
      const req = await Geolocation.requestPermissions();
      if (req.location !== 'granted' && req.coarseLocation !== 'granted') {
        throw new Error(
          'Location permission denied. Enable GPS access in device settings to verify classroom proximity.'
        );
      }
    }

    const pos = await Geolocation.getCurrentPosition({
      enableHighAccuracy: true,
      timeout: 12000,
      maximumAge: 0,
    });
    return {
      latitude: pos.coords.latitude,
      longitude: pos.coords.longitude,
      accuracy: pos.coords.accuracy ?? 0,
      timestamp: pos.timestamp,
    };
  }

  if (!navigator.geolocation) {
    throw new Error('Geolocation API is unavailable in this browser.');
  }

  const pos = await new Promise<GeolocationPosition>((resolve, reject) => {
    navigator.geolocation.getCurrentPosition(resolve, reject, {
      enableHighAccuracy: true,
      timeout: 12000,
      maximumAge: 0,
    });
  });

  return {
    latitude: pos.coords.latitude,
    longitude: pos.coords.longitude,
    accuracy: pos.coords.accuracy,
    timestamp: pos.timestamp,
  };
}
