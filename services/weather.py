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


class WeatherData:
    def __init__(self, raw: dict[str, Any]) -> None:
        current = raw["current_condition"][0]
        self.temp_c: int = int(current["temp_C"])
        self.feels_like_c: int = int(current["FeelsLikeC"])
        self.wind_kmph: int = int(current["windspeedKmph"])
        self.uv_index: int = int(current.get("uvIndex", 0))
        self.description: str = current["weatherDesc"][0]["value"]

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
            return WeatherData(json.loads(cached))

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"https://wttr.in/{city}?format=j1",
                headers={"Accept": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()

        await self._redis.set(key, json.dumps(data), ex=3600)
        logger.info("weather.fetched", city=city)
        return WeatherData(data)
