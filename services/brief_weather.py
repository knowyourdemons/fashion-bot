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


async def _geocode_city(city: str) -> tuple[float, float] | None:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://nominatim.openstreetmap.org/search",
                params={"q": city, "format": "json", "limit": 1},
                headers={"User-Agent": "FashionBot/1.0"},
            )
            data = resp.json()
            if data:
                return float(data[0]["lat"]), float(data[0]["lon"])
    except Exception as e:
        logger.warning("brief.geocode.failed", city=city, error=str(e))
    return None


async def _get_weather(lat: float, lon: float, tz: str) -> dict:
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
            return {
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
    except Exception as e:
        logger.warning("brief.weather.failed", error=str(e))
        return {"temp_now": None, "temp_morning": None, "temp_day": None, "temp_evening": None, "precip_evening": 0, "precip_max": 0}
