import '../../domain/entities/climate_alert.dart';
import 'api_client.dart';
import '../sync/offline_runtime.dart';

class AlertsRepository {
  AlertsRepository({ApiClient? client}) : _client = client ?? ApiClient();
  final ApiClient _client;

  Future<List<ClimateAlert>> load(
    String farmId, {
    bool evaluate = false,
  }) async {
    final runtime = OfflineRuntime.shared;
    final account = runtime?.requireAccount();
    if (runtime != null && !runtime.network.operational) {
      final response = await runtime.cachedGet('/alerts/farms/$farmId') as List;
      return response
          .map((item) => ClimateAlert.fromJson(item as Map<String, dynamic>))
          .toList();
    }
    final dynamic response = evaluate
        ? (await _client.post(
            '/alerts/farms/$farmId/evaluate',
            {},
          ))['active_alerts']
        : await _client.get('/alerts/farms/$farmId');
    if (runtime != null) {
      if (runtime.requireAccount() != account) {
        throw ApiAuthException('La cuenta cambió.');
      }
      await runtime.database.putCache(
        account!,
        '/alerts/farms/$farmId:{}',
        response as Object,
        runtime.clock(),
      );
    }
    return (response as List)
        .map((item) => ClimateAlert.fromJson(item as Map<String, dynamic>))
        .toList();
  }
}
