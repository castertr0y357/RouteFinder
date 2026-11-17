import logging
from typing import Optional
import googlemaps
from django.conf import settings
from geopy.geocoders import Nominatim
from geopy.exc import GeopyError

logger = logging.getLogger(__name__)

def get_zip_from_coords(lat: float, lon: float) -> Optional[str]:
    """
    Reverse geocodes latitude and longitude to find a zip code using Nominatim (OSM).
    Returns the zip code as a string, or None if not found.
    """
    if getattr(settings, 'MOCK_MODE', False):
        logger.info(f"MOCK_MODE: Mocking zip code lookup for coords ({lat}, {lon})")
        return "90210"

    try:
        # User-agent is required by Nominatim's usage policy
        geolocator = Nominatim(user_agent="routefinder_app")
        location = geolocator.reverse((lat, lon), addressdetails=True, timeout=10)
        
        if location and 'address' in location.raw:
            address = location.raw['address']
            # Postal code can be 'postcode' or 'postal-code' depending on the region
            return address.get('postcode') or address.get('postal-code')
            
    except (GeopyError, Exception) as e:
        logger.error(f"Reverse geocoding error: {str(e)}")
        
    return None

def get_address_from_coords(lat: float, lon: float) -> Optional[str]:
    """
    Reverse geocodes latitude and longitude to find a full address using Nominatim (OSM).
    Returns the formatted address as a string, or None if not found.
    """
    if getattr(settings, 'MOCK_MODE', False):
        logger.info(f"MOCK_MODE: Mocking address lookup for coords ({lat}, {lon})")
        return f"123 Mock St, Springfield, {get_zip_from_coords(lat, lon)}"

    try:
        geolocator = Nominatim(user_agent="routefinder_app")
        location = geolocator.reverse((lat, lon), timeout=10)
        
        if location:
            return location.address
            
    except (GeopyError, Exception) as e:
        logger.error(f"Reverse geocoding error: {str(e)}")
        
    return None



def get_coords_from_zip(zip_code: str) -> Optional[tuple]:
    """Resolve a US zip code to (lat, lon) coordinates."""
    if not zip_code:
        return None
    if getattr(settings, 'MOCK_MODE', False):
        return (36.0957, -79.2670)

    api_key = getattr(settings, 'GOOGLE_MAPS_API_KEY', None)
    if api_key:
        try:
            gmaps = googlemaps.Client(key=api_key)
            results = gmaps.geocode(f"{zip_code}, USA")
            if results:
                loc = results[0]['geometry']['location']
                return (float(loc['lat']), float(loc['lng']))
        except Exception as e:
            logger.warning(f"Google geocoding failed for zip {zip_code}: {e}")

    try:
        from geopy.geocoders import Nominatim
        geolocator = Nominatim(user_agent="RouteFinder/1.0")
        location = geolocator.geocode(f"{zip_code}, USA", timeout=5)
        if location:
            return (float(location.latitude), float(location.longitude))
    except Exception as e:
        logger.warning(f"Nominatim geocoding failed for zip {zip_code}: {e}")

    return None


def filter_sales_by_radius(sales: list, zip_code: str, radius: int) -> list:
    """Filter scraped listings to those within `radius` miles of `zip_code`."""
    if not sales or not zip_code:
        return sales

    origin = get_coords_from_zip(zip_code)
    if not origin:
        logger.warning(f"Could not geocode zip {zip_code}; skipping strict radius filter.")
        return sales

    from geopy.distance import geodesic
    api_key = getattr(settings, 'GOOGLE_MAPS_API_KEY', None)
    gmaps = googlemaps.Client(key=api_key) if api_key else None

    filtered = []
    dropped = 0
    missing = 0
    for item in sales:
        if not isinstance(item, dict):
            continue
        lat = item.get('lat')
        lng = item.get('lng') if item.get('lng') is not None else item.get('lon')
        if (lat is None or lng is None) and item.get('address') and gmaps and not getattr(settings, 'MOCK_MODE', False):
            try:
                res = gmaps.geocode(item['address'])
                if res:
                    loc = res[0]['geometry']['location']
                    lat, lng = float(loc['lat']), float(loc['lng'])
                    item['lat'] = lat
                    item['lng'] = lng
            except Exception as e:
                logger.debug(f"Address geocode failed for '{item.get('address')}': {e}")

        if lat is None or lng is None:
            missing += 1
            filtered.append(item)
            continue
        try:
            dist = geodesic(origin, (float(lat), float(lng))).miles
            if dist <= float(radius):
                item['distance_miles'] = round(dist, 1)
                filtered.append(item)
            else:
                dropped += 1
        except (ValueError, TypeError):
            missing += 1
            filtered.append(item)

    logger.info(
        f"Radius filter for {zip_code} ({radius} mi): total={len(sales)}, kept={len(filtered)}, dropped={dropped}, missing_coords={missing}"
    )
    return filtered
