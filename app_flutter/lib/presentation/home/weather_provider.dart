import 'package:flutter/foundation.dart';
import '../../data/api/weather_repository.dart';
import '../../domain/entities/weather_forecast.dart';

enum WeatherStatus { initial, loading, loaded, error }

class WeatherProvider extends ChangeNotifier {
  WeatherProvider({WeatherRepository? repository})
    : _repository = repository ?? WeatherRepository();
  final WeatherRepository _repository;
  WeatherStatus status = WeatherStatus.initial;
  WeatherForecast? forecast;
  String? errorMessage;
  String? _farm;
  Future<void>? _flight;
  int _generation = 0;
  void clear() {
    _generation++;
    _farm = null;
    _flight = null;
    forecast = null;
    errorMessage = null;
    status = WeatherStatus.initial;
    notifyListeners();
  }

  Future<void> fetchForecast(String farmId, {bool force = false}) {
    if (_farm == farmId && _flight != null) return _flight!;
    _farm = farmId;
    final generation = ++_generation;
    final future = _fetch(farmId, force, generation);
    _flight = future;
    return future.whenComplete(() {
      if (generation == _generation) _flight = null;
    });
  }

  Future<void> _fetch(String farmId, bool force, int generation) async {
    if (forecast?.farmId != farmId) forecast = null;
    try {
      status = forecast == null ? WeatherStatus.loading : WeatherStatus.loaded;
      errorMessage = null;
      notifyListeners();
      final data = force
          ? await _repository.refresh(farmId)
          : await _repository.getForecast(farmId, days: 7);
      if (generation != _generation) return;
      forecast = data;
      status = WeatherStatus.loaded;
    } catch (_) {
      if (generation != _generation) return;
      status = forecast == null ? WeatherStatus.error : WeatherStatus.loaded;
      errorMessage = forecast == null
          ? 'Necesitas conexión inicial para descargar el pronóstico.'
          : 'No se pudo actualizar. Estás viendo información guardada.';
    }
    notifyListeners();
  }
}
