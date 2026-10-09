import unittest

from app.integrations.met_weather_codes import met_weather_code


class MetWeatherCodeTests(unittest.TestCase):
    def test_preserves_symbol_groups_across_time_of_day(self):
        cases = {
            "clearsky": 0,
            "fair": 1,
            "partlycloudy": 2,
            "cloudy": 3,
            "fog": 45,
            "lightrain": 63,
            "rain": 63,
            "heavyrain": 65,
            "sleet": 67,
            "heavysleet": 67,
            "lightsnow": 73,
            "snow": 73,
            "heavysnow": 75,
            "lightrainshowers": 81,
            "rainshowers": 81,
            "heavyrainshowers": 82,
            "lightsnowshowers": 85,
            "snowshowers": 85,
            "heavysnowshowers": 85,
            "heavyrainshowersandthunder": 95,
            "snowandthunder": 95,
            "sleetshowersandthunder": 95,
        }
        for symbol, expected in cases.items():
            for suffix in ("", "_day", "_night", "_polartwilight"):
                with self.subTest(symbol=symbol, suffix=suffix):
                    result = met_weather_code(symbol + suffix)
                    self.assertEqual(result, expected)
                    self.assertIs(type(result), int)

    def test_preserves_fallback_for_missing_and_unknown_symbols(self):
        for symbol in (None, "", "unknown_symbol"):
            with self.subTest(symbol=symbol):
                self.assertEqual(met_weather_code(symbol), 3)
