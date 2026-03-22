"""
Погодный сервис: wttr.in + Redis кэш TTL=3600.
"""
import json
from typing import Any

import httpx
import redis.asyncio as aioredis
import structlog

logger = structlog.get_logger()

TEMP_RULES: list[tuple[tuple[int, int], str]] = [
    ((20, 99),  "лёгкая одежда без куртки"),
    ((15, 20),  "тепло — лёгкая кофта"),
    ((10, 15),  "прохладно — лёгкая куртка"),
    ((5, 10),   "холодно — тёплая куртка"),
    ((0, 5),    "около нуля — утеплиться"),
    ((-5, 0),   "мороз — тёплая одежда"),
    ((-99, -5), "сильный мороз — максимальное утепление"),
]

DELTA_RULES: dict[int, str] = {
    8: "⚠️ Резкое похолодание вечером на {n}°C",
    5: "⚠️ Вечером холоднее на {n}°C",
}

PRECIP_RULES: dict[str, str] = {
    "rain_morning":  "🌧 Дождь — непромокаемая куртка",
    "rain_evening":  "🌧 Вечером дождь — возьми дождевик",
    "snow":          "❄️ Снег — зимняя одежда",
    "sleet":         "🌨 Мокрый снег — водоотталкивающая куртка",
}

WIND_RULES: dict[int, str] = {
    15: "💨 Сильный ветер — закрытая одежда",
    10: "💨 Ветрено — куртка с капюшоном",
}

SPECIAL_RULES: dict[str, str] = {
    "fog":          "🌫 Туман — яркая одежда (заметность)",
    "thunder":      "⛈ Гроза — лучше остаться дома",
    "hot":          "☀️ Жара — панамка + солнцезащитный крем",
    "uv_high":      "🌞 Высокий УФ — панамка обязательна",
    "transitional": "Переменная погода — одеть слоями",
}


def calc_wind_chill(temp_c: float, wind_kmph: float) -> float:
    """Calculate wind chill (felt temperature).

    Uses Environment Canada formula for temp ≤ 10°C and wind ≥ 4.8 km/h.
    Returns original temp if conditions don't apply.
    """
    if temp_c > 10 or wind_kmph < 4.8:
        return temp_c
    wc = 13.12 + 0.6215 * temp_c - 11.37 * (wind_kmph ** 0.16) + 0.3965 * temp_c * (wind_kmph ** 0.16)
    return round(wc, 1)


class WeatherData:
    def __init__(self, raw: dict[str, Any]) -> None:
        current = raw["current_condition"][0]
        self.temp_c: int = int(current["temp_C"])
        self.feels_like_c: int = int(current["FeelsLikeC"])
        self.wind_kmph: int = int(current["windspeedKmph"])
        self.uv_index: int = int(current.get("uvIndex", 0))
        self.description: str = current["weatherDesc"][0]["value"]

        # Wind chill — effective temperature for outfit selection
        self.wind_chill_c: float = calc_wind_chill(self.temp_c, self.wind_kmph)

        # Вечерняя температура из почасового
        hourly = raw["weather"][0].get("hourly", [])
        evening = [h for h in hourly if int(h.get("time", "0")) >= 1800]
        self.evening_temp: int = int(evening[0]["tempC"]) if evening else self.temp_c

        # Осадки
        weather_code = int(current.get("weatherCode", 0))
        self.is_rain = weather_code in range(263, 300)
        self.is_snow = weather_code in range(320, 400)
        self.is_sleet = weather_code in range(311, 320)
        self.is_thunder = weather_code in range(386, 400)
        self.is_fog = weather_code in (143, 248, 260)

    def get_temp_advice(self) -> str:
        for (low, high), advice in TEMP_RULES:
            if low <= self.temp_c < high:
                return advice
        return ""

    def get_alerts(self) -> list[str]:
        alerts: list[str] = []

        # Дельта температуры вечером
        delta = self.temp_c - self.evening_temp
        for threshold, template in sorted(DELTA_RULES.items(), reverse=True):
            if delta >= threshold:
                alerts.append(template.format(n=delta))
                break

        # Осадки
        if self.is_thunder:
            alerts.append(SPECIAL_RULES["thunder"])
        elif self.is_snow:
            alerts.append(PRECIP_RULES["snow"])
        elif self.is_sleet:
            alerts.append(PRECIP_RULES["sleet"])
        elif self.is_rain:
            alerts.append(PRECIP_RULES["rain_morning"])

        # Ветер
        for threshold, msg in sorted(WIND_RULES.items(), reverse=True):
            if self.wind_kmph >= threshold:
                alerts.append(msg)
                break

        # Туман
        if self.is_fog:
            alerts.append(SPECIAL_RULES["fog"])

        # UV
        if self.uv_index >= 6:
            alerts.append(SPECIAL_RULES["uv_high"])
        elif self.temp_c >= 28:
            alerts.append(SPECIAL_RULES["hot"])

        return alerts

    def to_summary(self) -> str:
        advice = self.get_temp_advice()
        alerts = self.get_alerts()
        parts = [f"{self.temp_c}°C, {self.description}", advice] + alerts
        return "\n".join(p for p in parts if p)


class WeatherService:
    def __init__(self, redis_client: aioredis.Redis) -> None:
        self._redis = redis_client

    async def get(self, city: str) -> WeatherData:
        key = f"weather:cache:{city}"

        cached = await self._redis.get(key)
        if cached:
            _cached_data = json.loads(cached)
            if "data" in _cached_data and "current_condition" not in _cached_data:
                _cached_data = _cached_data["data"]
            return WeatherData(_cached_data)

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"https://wttr.in/{city}?format=j1",
                headers={"Accept": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()

        # wttr.in может возвращать {"data": {...}} — разворачиваем
        if "data" in data and "current_condition" not in data:
            data = data["data"]
        await self._redis.set(key, json.dumps(data), ex=3600)
        logger.info("weather.fetched", city=city)
        return WeatherData(data)

    async def get_forecast_day(self, city: str, day: int = 1) -> dict:
        """Погода на день прогноза из wttr.in (day=0 сегодня, day=1 завтра).

        Возвращает dict: temp_morning, temp_evening, precip_evening (как _get_weather).
        Переиспользует кеш weather:cache:{city} (1h TTL).
        """
        key = f"weather:cache:{city}"
        raw = None

        cached = await self._redis.get(key)
        if cached:
            raw = json.loads(cached)
            if "data" in raw and "current_condition" not in raw:
                raw = raw["data"]

        if raw is None:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"https://wttr.in/{city}?format=j1",
                    headers={"Accept": "application/json"},
                )
                resp.raise_for_status()
                raw = resp.json()
            if "data" in raw and "current_condition" not in raw:
                raw = raw["data"]
            await self._redis.set(key, json.dumps(raw), ex=3600)

        weather_days = raw.get("weather", [])
        day_idx = min(day, len(weather_days) - 1)
        day_data = weather_days[day_idx] if weather_days else {}
        hourly = day_data.get("hourly", [])

        # Утро ≈ 07:00 (time=700)
        morning_h = next(
            (h for h in hourly if int(h.get("time", "0")) >= 600), hourly[0] if hourly else {}
        )
        # Вечер ≈ 21:00 (time=2100)
        evening_h = next(
            (h for h in reversed(hourly) if int(h.get("time", "0")) >= 1800),
            hourly[-1] if hourly else {},
        )

        temp_morning = float(morning_h.get("tempC", day_data.get("mintempC", 10)))
        temp_evening = float(evening_h.get("tempC", temp_morning))
        weather_code = int(morning_h.get("weatherCode", 116))
        is_rain = weather_code in range(263, 300)
        precip_evening = 60.0 if is_rain else 0.0

        # Wind chill for outfit selection
        wind_morning = float(morning_h.get("windspeedKmph", 0))
        felt_morning = calc_wind_chill(temp_morning, wind_morning)

        # UV index
        uv = int(morning_h.get("uvIndex", 0))

        return {
            "temp_morning": temp_morning,
            "temp_evening": temp_evening,
            "felt_morning": felt_morning,
            "precip_evening": precip_evening,
            "wind_kmph": wind_morning,
            "uv_index": uv,
        }
