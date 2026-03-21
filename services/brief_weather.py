"""
Геокодинг и погода для Morning Brief (Open-Meteo + Nominatim).
Отдельно от services/weather.py (wttr.in + Redis cache).
"""
import httpx
import structlog

logger = structlog.get_logger()

_SEASONS = {
    12: "winter", 1: "winter", 2: "winter",
    3: "spring",  4: "spring", 5: "spring",
    6: "summer",  7: "summer", 8: "summer",
    9: "autumn",  10: "autumn", 11: "autumn",
}


def wmo_to_emoji(code: int) -> str:
    """WMO weather code → emoji for Telegram text."""
    if code in (0, 1):
        return "☀️"
    if code in (2, 3):
        return "⛅"
    if code in (45, 48):
        return "🌫"
    if code in (51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82):
        return "🌧"
    if code in (71, 73, 75, 77, 85, 86):
        return "🌨"
    if code in (95, 96, 99):
        return "⛈"
    return "🌤"


_geocode_mem: dict[str, tuple[float, float] | None] = {}


async def _geocode_city(city: str) -> tuple[float, float] | None:
    """Geocode with in-memory + Redis cache (7 days TTL)."""
    if not city:
        return None

    # In-memory cache (lives until container restart)
    if city in _geocode_mem:
        return _geocode_mem[city]

    # Redis cache
    try:
        from core.redis import get_redis
        _r = get_redis()
        cached = await _r.get(f"geocode:{city}")
        if cached:
            lat, lon = cached.decode().split(",")
            result = (float(lat), float(lon))
            _geocode_mem[city] = result
            return result
    except Exception:
        pass

    # Nominatim API
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://nominatim.openstreetmap.org/search",
                params={"q": city, "format": "json", "limit": 1},
                headers={"User-Agent": "FashionBot/1.0"},
            )
            data = resp.json()
            if data:
                result = (float(data[0]["lat"]), float(data[0]["lon"]))
                _geocode_mem[city] = result
                # Redis: 7 days TTL
                try:
                    _r = get_redis()
                    await _r.set(f"geocode:{city}", f"{result[0]},{result[1]}", ex=604800)
                except Exception:
                    pass
                return result
    except Exception as e:
        logger.warning("brief.geocode.failed", city=city, error=str(e))

    _geocode_mem[city] = None
    return None


_EMPTY_WEATHER = {"temp_now": None, "temp_morning": None, "temp_day": None, "temp_evening": None, "precip_evening": 0, "precip_max": 0, "wmo_morning": 0, "wmo_day": 0, "wmo_evening": 0}


async def _get_weather(lat: float, lon: float, tz: str) -> dict:
    # Redis cache: 15 min TTL
    import json as _json
    _cache_key = f"weather_om:{lat:.2f}:{lon:.2f}"
    try:
        from core.redis import get_redis
        _r = get_redis()
        _cached = await _r.get(_cache_key)
        if _cached:
            return _json.loads(_cached)
    except Exception:
        pass

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "hourly": "temperature_2m,precipitation_probability,weather_code",
                    "current": "temperature_2m,weather_code",
                    "timezone": tz,
                    "forecast_days": 1,
                },
            )
            data = resp.json()
            hourly = data.get("hourly", {})
            temps = hourly.get("temperature_2m", [])
            precip = hourly.get("precipitation_probability", [])
            current = data.get("current", {})
            temp_now = current.get("temperature_2m")
            wmo_codes = hourly.get("weather_code", [])
            result = {
                "temp_now": round(temp_now, 1) if temp_now is not None else None,
                "temp_morning": round(temps[7], 1) if len(temps) > 7 else None,
                "temp_day": round(temps[14], 1) if len(temps) > 14 else None,
                "temp_evening": round(temps[18], 1) if len(temps) > 18 else None,
                "precip_evening": precip[18] if len(precip) > 18 else 0,
                "precip_max": max(precip[:18]) if len(precip) > 18 else 0,
                "wmo_morning": wmo_codes[7] if len(wmo_codes) > 7 else 0,
                "wmo_day": wmo_codes[14] if len(wmo_codes) > 14 else 0,
                "wmo_evening": wmo_codes[18] if len(wmo_codes) > 18 else 0,
            }
            # Cache 15 min
            try:
                await _r.set(_cache_key, _json.dumps(result), ex=900)
            except Exception:
                pass
            return result
    except Exception as e:
        logger.warning("brief.weather.failed", error=str(e))
        return dict(_EMPTY_WEATHER)


async def _get_weather_tomorrow(lat: float, lon: float, tz: str) -> dict:
    """Fetch TOMORROW's weather from Open-Meteo (forecast_days=2, take day index 1)."""
    import json as _json
    _cache_key = f"weather_om_tmrw:{lat:.2f}:{lon:.2f}"
    try:
        from core.redis import get_redis
        _r = get_redis()
        _cached = await _r.get(_cache_key)
        if _cached:
            return _json.loads(_cached)
    except Exception:
        pass

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "hourly": "temperature_2m,precipitation_probability,weather_code",
                    "timezone": tz,
                    "forecast_days": 2,
                },
            )
            data = resp.json()
            hourly = data.get("hourly", {})
            temps = hourly.get("temperature_2m", [])
            precip = hourly.get("precipitation_probability", [])
            wmo_codes = hourly.get("weather_code", [])
            # Tomorrow's data starts at index 24 (hour 0 of day 2)
            off = 24
            result = {
                "temp_now": None,
                "temp_morning": round(temps[off + 7], 1) if len(temps) > off + 7 else None,
                "temp_day": round(temps[off + 14], 1) if len(temps) > off + 14 else None,
                "temp_evening": round(temps[off + 18], 1) if len(temps) > off + 18 else None,
                "precip_evening": precip[off + 18] if len(precip) > off + 18 else 0,
                "precip_max": max(precip[off:off + 18]) if len(precip) > off + 18 else 0,
                "wmo_morning": wmo_codes[off + 7] if len(wmo_codes) > off + 7 else 0,
                "wmo_day": wmo_codes[off + 14] if len(wmo_codes) > off + 14 else 0,
                "wmo_evening": wmo_codes[off + 18] if len(wmo_codes) > off + 18 else 0,
            }
            # Cache 30 min (evening brief, less stale tolerance)
            try:
                from core.redis import get_redis
                _r = get_redis()
                await _r.set(_cache_key, _json.dumps(result), ex=1800)
            except Exception:
                pass
            return result
    except Exception as e:
        logger.warning("brief.weather_tomorrow.failed", error=str(e))
        return dict(_EMPTY_WEATHER)
