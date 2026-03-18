"""Tests for weather service."""
import pytest
from unittest.mock import patch, AsyncMock

from services.weather import WeatherData, WeatherService

MOCK_WEATHER = {
    "current_condition": [{
        "temp_C": "15",
        "FeelsLikeC": "13",
        "windspeedKmph": "8",
        "uvIndex": "3",
        "weatherDesc": [{"value": "Partly cloudy"}],
        "weatherCode": "116",
    }],
    "weather": [{"hourly": [{"time": "1800", "tempC": "10"}]}],
}


def test_weather_data_parse():
    w = WeatherData(MOCK_WEATHER)
    assert w.temp_c == 15
    assert w.evening_temp == 10


def test_temp_advice():
    # temp=15°C → диапазон (15,20) → "тепло — лёгкая кофта"
    w = WeatherData(MOCK_WEATHER)
    advice = w.get_temp_advice()
    assert "кофта" in advice or "куртка" in advice  # лёгкая верхняя одежда


def test_delta_alert():
    w = WeatherData(MOCK_WEATHER)
    alerts = w.get_alerts()
    # delta = 15 - 10 = 5 → alert expected
    assert any("Вечером" in a for a in alerts)
