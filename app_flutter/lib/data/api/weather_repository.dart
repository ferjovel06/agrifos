import '../../domain/entities/weather_forecast.dart';
import 'api_client.dart';
import '../sync/offline_runtime.dart';

class WeatherRepository {
  final ApiClient _client;

  WeatherRepository({ApiClient? client}) : _client = client ?? ApiClient();

  Future<WeatherForecast> getForecast(String farmId, {int days = 7}) async {
    final runtime = OfflineRuntime.shared;
    if (runtime != null) {
      return WeatherForecast.fromJson(await runtime.weather(farmId, days));
    }
    final response = await _client.get(
      '/weather/farms/$farmId/forecast',
      query: {'days': '$days'},
    );
    return WeatherForecast.fromJson(response as Map<String, dynamic>);
  }

  Future<WeatherForecast> refresh(String farmId, {int days = 7}) async {
    final runtime = OfflineRuntime.shared;
    if (runtime == null) return getForecast(farmId, days: days);
    return WeatherForecast.fromJson(
      await runtime.weather(farmId, days, manual: true),
    );
  }
}
