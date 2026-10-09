import '../../domain/entities/reading.dart';
import '../../domain/entities/sensor_diagnostic.dart';
import '../sensor/usb_sensor_service.dart';
import 'api_client.dart';
import '../sync/offline_runtime.dart';

/// Sends sensor readings captured by the app to the Agrifos backend
class ReadingsRepository {
  final ApiClient _client;

  ReadingsRepository({ApiClient? client}) : _client = client ?? ApiClient();

  /// Submits [reading] for the given [parcelId].
  ///
  /// The USB sensor reports EC in µS/cm, but the backend stores and
  /// validates EC in dS/m (0-20 range), so it's converted here
  /// (1 dS/m = 1000 µS/cm) before sending.
  Future<Reading> submitReading({
    required String parcelId,
    required SensorReading reading,
  }) async {
    final payload = {
      'parcel_id': parcelId,
      'nitrogen': reading.nitrogen,
      'phosphorus': reading.phosphorus,
      'potassium': reading.potassium,
      'ec': reading.ec / 1000,
      'ph': reading.ph,
      'temperature': reading.temperature,
      'humidity': reading.humidity,
    };
    final runtime = OfflineRuntime.shared;
    if (runtime != null) {
      return Reading.fromJson(
        await runtime.save('readings', parcelId, {
          ...payload..remove('parcel_id'),
          'recorded_at': runtime.clock().toUtc().toIso8601String(),
        }),
      );
    }
    final response = await _client.post('/readings', payload);
    return Reading.fromJson(response);
  }

  /// Fetches the most recent stored reading for [parcelId], or `null` if
  /// the parcel has no readings yet.
  ///
  /// Reuses `GET /readings` (already sorted newest-first) with `limit=1`
  /// instead of adding a dedicated "latest" endpoint.
  Future<Reading?> getLatestReading(String parcelId) async {
    final runtime = OfflineRuntime.shared;
    if (runtime != null) {
      final rows = await runtime.read('readings', parent: parcelId);
      if (rows.isEmpty) return null;
      rows.sort(
        (a, b) =>
            (b['recorded_at'] as String).compareTo(a['recorded_at'] as String),
      );
      final reading = Reading.fromJson(rows.first);
      if (reading.syncStatus != 'synced') return reading;
      try {
        final diagnosis =
            await runtime.cachedGet('/diagnostics/readings/${reading.id}')
                as Map<String, dynamic>;
        return reading.copyWith(
          diagnosis: SensorDiagnostic.fromJson(diagnosis),
        );
      } catch (_) {
        return reading;
      }
    }
    final response = await _client.get(
      '/readings',
      query: {'parcel_id': parcelId, 'limit': '1'},
    );
    final list = (response as List).cast<Map<String, dynamic>>();
    if (list.isEmpty) return null;
    final reading = Reading.fromJson(list.first);
    final diagnosisResponse = await _client.get(
      '/diagnostics/readings/${reading.id}',
    );
    return reading.copyWith(
      diagnosis: SensorDiagnostic.fromJson(
        diagnosisResponse as Map<String, dynamic>,
      ),
    );
  }
}
