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
                    "hourly": "temperature_2m,precipitation_probability",
                    "timezone": tz,
                    "forecast_days": 1,
                },
            )
            hourly = resp.json().get("hourly", {})
            temps = hourly.get("temperature_2m", [])
            precip = hourly.get("precipitation_probability", [])
            return {
                "temp_morning": round(temps[7], 1) if len(temps) > 7 else None,
                "temp_day": round(temps[14], 1) if len(temps) > 14 else None,
                "temp_evening": round(temps[18], 1) if len(temps) > 18 else None,
                "precip_evening": precip[18] if len(precip) > 18 else 0,
                "precip_max": max(precip[:18]) if len(precip) > 18 else 0,
            }
    except Exception as e:
        logger.warning("brief.weather.failed", error=str(e))
        return {"temp_morning": None, "temp_day": None, "temp_evening": None, "precip_evening": 0, "precip_max": 0}
