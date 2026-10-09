import 'package:flutter/foundation.dart';

import '../../data/api/api_client.dart';
import '../../data/api/readings_repository.dart';
import '../../domain/entities/reading.dart';

enum LatestReadingStatus { loading, loaded, empty, error }

/// Holds the most recent reading stored in the backend for a parcel, shown
/// on the home dashboard's "Última Lectura Global" card.
class LatestReadingProvider extends ChangeNotifier {
  final ReadingsRepository _readingsRepository;

  LatestReadingProvider({ReadingsRepository? readingsRepository})
    : _readingsRepository = readingsRepository ?? ReadingsRepository();

  LatestReadingStatus status = LatestReadingStatus.loading;
  Reading? reading;
  String? errorMessage;
  int _generation = 0;

  void clear() {
    _generation++;
    reading = null;
    errorMessage = null;
    status = LatestReadingStatus.empty;
    notifyListeners();
  }

  Future<void> fetchLatest(String parcelId) async {
    final generation = ++_generation;
    status = LatestReadingStatus.loading;
    errorMessage = null;
    notifyListeners();

    try {
      final result = await _readingsRepository.getLatestReading(parcelId);
      if (generation != _generation) return;
      reading = result;
      status = result == null
          ? LatestReadingStatus.empty
          : LatestReadingStatus.loaded;
      notifyListeners();
    } on ApiAuthException catch (e) {
      if (generation != _generation) return;
      if (generation != _generation) return;
      status = LatestReadingStatus.error;
      errorMessage = e.message;
      notifyListeners();
    } on ApiException catch (e) {
      if (generation != _generation) return;
      if (generation != _generation) return;
      status = LatestReadingStatus.error;
      errorMessage = e.message;
      notifyListeners();
    } catch (e) {
      if (generation != _generation) return;
      status = LatestReadingStatus.error;
      errorMessage = 'No se pudo cargar la última lectura: $e';
      notifyListeners();
    }
  }
}
