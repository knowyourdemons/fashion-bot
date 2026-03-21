"""Tests for services/brief_weather.py — geocoding, weather, WMO emoji."""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import services.brief_weather as bw


@pytest.fixture(autouse=True)
def _clear_geocode_mem():
    """Clear in-memory geocode cache between tests."""
    bw._geocode_mem.clear()
    yield
    bw._geocode_mem.clear()


# ── wmo_to_emoji ─────────────────────────────────────────────────────────────

class TestWmoToEmoji:
    def test_clear_sky_code_0(self):
        assert bw.wmo_to_emoji(0) == "☀️"

    def test_clear_sky_code_1(self):
        assert bw.wmo_to_emoji(1) == "☀️"

    def test_partly_cloudy_code_2(self):
        assert bw.wmo_to_emoji(2) == "⛅"

    def test_partly_cloudy_code_3(self):
        assert bw.wmo_to_emoji(3) == "⛅"

    def test_rain_code_61(self):
        assert bw.wmo_to_emoji(61) == "🌧"

    def test_rain_code_63(self):
        assert bw.wmo_to_emoji(63) == "🌧"

    def test_rain_code_65(self):
        assert bw.wmo_to_emoji(65) == "🌧"

    def test_snow_code_71(self):
        assert bw.wmo_to_emoji(71) == "🌨"

    def test_snow_code_73(self):
        assert bw.wmo_to_emoji(73) == "🌨"

    def test_thunderstorm_code_95(self):
        assert bw.wmo_to_emoji(95) == "⛈"

    def test_fog_code_45(self):
        assert bw.wmo_to_emoji(45) == "🌫"

    def test_unknown_code_returns_default(self):
        assert bw.wmo_to_emoji(999) == "🌤"


# ── _geocode_city ────────────────────────────────────────────────────────────

class TestGeocodeCity:
    @pytest.mark.asyncio
    async def test_returns_none_for_empty_city(self):
        result = await bw._geocode_city("")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_cached_from_mem(self):
        bw._geocode_mem["Vilnius"] = (54.68, 25.28)
        result = await bw._geocode_city("Vilnius")
        assert result == (54.68, 25.28)

    @pytest.mark.asyncio
    async def test_returns_cached_from_redis(self):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=b"54.68,25.28")

        with patch("core.redis.get_redis", return_value=mock_redis):
            result = await bw._geocode_city("Vilnius")

        assert result == (54.68, 25.28)
        # Should also populate in-memory cache
        assert bw._geocode_mem["Vilnius"] == (54.68, 25.28)

    @pytest.mark.asyncio
    async def test_fetches_from_nominatim_api(self):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.set = AsyncMock()

        mock_response = MagicMock()
        mock_response.json.return_value = [{"lat": "54.68", "lon": "25.28"}]

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("core.redis.get_redis", return_value=mock_redis), \
             patch("services.brief_weather.httpx.AsyncClient", return_value=mock_client):
            result = await bw._geocode_city("Vilnius")

        assert result == (54.68, 25.28)

    @pytest.mark.asyncio
    async def test_caches_in_mem_and_redis_after_api(self):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.set = AsyncMock()

        mock_response = MagicMock()
        mock_response.json.return_value = [{"lat": "40.71", "lon": "-74.01"}]

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("core.redis.get_redis", return_value=mock_redis), \
             patch("services.brief_weather.httpx.AsyncClient", return_value=mock_client):
            await bw._geocode_city("NewYork")

        # In-memory cache populated
        assert bw._geocode_mem["NewYork"] == (40.71, -74.01)
        # Redis set called with 7-day TTL
        mock_redis.set.assert_called_once_with("geocode:NewYork", "40.71,-74.01", ex=604800)

    @pytest.mark.asyncio
    async def test_returns_none_on_api_failure(self):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=Exception("connection error"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("core.redis.get_redis", return_value=mock_redis), \
             patch("services.brief_weather.httpx.AsyncClient", return_value=mock_client):
            result = await bw._geocode_city("Nowhere")

        assert result is None

    @pytest.mark.asyncio
    async def test_caches_none_on_failure(self):
        """Negative cache: None is stored in _geocode_mem so we don't retry."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=Exception("timeout"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("core.redis.get_redis", return_value=mock_redis), \
             patch("services.brief_weather.httpx.AsyncClient", return_value=mock_client):
            await bw._geocode_city("BadCity")

        assert "BadCity" in bw._geocode_mem
        assert bw._geocode_mem["BadCity"] is None


# ── _get_weather ─────────────────────────────────────────────────────────────

def _make_hourly_data(n=24):
    """Helper: build a realistic hourly weather response."""
    return {
        "hourly": {
            "temperature_2m": [float(i) for i in range(n)],
            "precipitation_probability": [i * 2 for i in range(n)],
            "weather_code": [i % 4 for i in range(n)],
        },
        "current": {
            "temperature_2m": 12.345,
            "weather_code": 0,
        },
    }


class TestGetWeather:
    @pytest.mark.asyncio
    async def test_returns_cached_from_redis(self):
        cached = {"temp_now": 10.0, "temp_morning": 5.0, "temp_day": 12.0,
                  "temp_evening": 8.0, "precip_evening": 20, "precip_max": 40,
                  "wmo_morning": 0, "wmo_day": 2, "wmo_evening": 1}
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=json.dumps(cached).encode())

        with patch("core.redis.get_redis", return_value=mock_redis):
            result = await bw._get_weather(54.68, 25.28, "Europe/Vilnius")

        assert result == cached

    @pytest.mark.asyncio
    async def test_fetches_from_api_when_not_cached(self):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.set = AsyncMock()

        api_data = _make_hourly_data()
        mock_response = MagicMock()
        mock_response.json.return_value = api_data

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("core.redis.get_redis", return_value=mock_redis), \
             patch("services.brief_weather.httpx.AsyncClient", return_value=mock_client):
            result = await bw._get_weather(54.68, 25.28, "Europe/Vilnius")

        assert result["temp_now"] == 12.3  # rounded from 12.345
        assert result["temp_morning"] is not None
        assert result["temp_day"] is not None
        assert result["temp_evening"] is not None

    @pytest.mark.asyncio
    async def test_returns_empty_weather_on_api_failure(self):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=Exception("API down"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("core.redis.get_redis", return_value=mock_redis), \
             patch("services.brief_weather.httpx.AsyncClient", return_value=mock_client):
            result = await bw._get_weather(54.68, 25.28, "Europe/Vilnius")

        assert result["temp_now"] is None
        assert result["temp_morning"] is None
        assert result["precip_max"] == 0

    @pytest.mark.asyncio
    async def test_extracts_morning_day_evening_temps(self):
        """Morning=index 7, Day=index 14, Evening=index 18."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.set = AsyncMock()

        api_data = _make_hourly_data()
        mock_response = MagicMock()
        mock_response.json.return_value = api_data

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("core.redis.get_redis", return_value=mock_redis), \
             patch("services.brief_weather.httpx.AsyncClient", return_value=mock_client):
            result = await bw._get_weather(54.68, 25.28, "Europe/Vilnius")

        # temps are [0.0, 1.0, ..., 23.0], so index 7=7.0, 14=14.0, 18=18.0
        assert result["temp_morning"] == 7.0
        assert result["temp_day"] == 14.0
        assert result["temp_evening"] == 18.0

    @pytest.mark.asyncio
    async def test_caches_result_in_redis_with_ttl(self):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.set = AsyncMock()

        api_data = _make_hourly_data()
        mock_response = MagicMock()
        mock_response.json.return_value = api_data

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("core.redis.get_redis", return_value=mock_redis), \
             patch("services.brief_weather.httpx.AsyncClient", return_value=mock_client):
            await bw._get_weather(54.68, 25.28, "Europe/Vilnius")

        # Redis set called with 15-min TTL (ex=900)
        call_args = mock_redis.set.call_args
        assert call_args[1]["ex"] == 900 or call_args[0][2] == 900 or \
               (len(call_args[1]) > 0 and call_args[1].get("ex") == 900)

    @pytest.mark.asyncio
    async def test_precip_max_and_evening(self):
        """precip_evening=index 18, precip_max=max of first 18."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.set = AsyncMock()

        api_data = _make_hourly_data()
        mock_response = MagicMock()
        mock_response.json.return_value = api_data

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("core.redis.get_redis", return_value=mock_redis), \
             patch("services.brief_weather.httpx.AsyncClient", return_value=mock_client):
            result = await bw._get_weather(54.68, 25.28, "Europe/Vilnius")

        # precip = [0, 2, 4, ..., 46], index 18 = 36, max of first 18 = max([0,2,...,34]) = 34
        assert result["precip_evening"] == 36
        assert result["precip_max"] == 34

    @pytest.mark.asyncio
    async def test_wmo_codes_extracted(self):
        """wmo_morning=index 7, wmo_day=index 14, wmo_evening=index 18."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.set = AsyncMock()

        api_data = _make_hourly_data()
        mock_response = MagicMock()
        mock_response.json.return_value = api_data

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("core.redis.get_redis", return_value=mock_redis), \
             patch("services.brief_weather.httpx.AsyncClient", return_value=mock_client):
            result = await bw._get_weather(54.68, 25.28, "Europe/Vilnius")

        # weather_code = [i % 4 for i in range(24)], so index 7=3, 14=2, 18=2
        assert result["wmo_morning"] == 7 % 4  # 3
        assert result["wmo_day"] == 14 % 4      # 2
        assert result["wmo_evening"] == 18 % 4  # 2
