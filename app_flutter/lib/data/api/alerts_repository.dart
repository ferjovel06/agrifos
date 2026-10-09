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
    if (runtime != null && !runtime.network.operational) {
      final response = await runtime.cachedGet('/alerts/farms/$farmId') as List;
      return response
          .map((item) => ClimateAlert.fromJson(item as Map<String, dynamic>))
          .toList();
    }
    Future<dynamic> request() async => evaluate
        ? (await _client.post(
            '/alerts/farms/$farmId/evaluate',
            {},
          ))['active_alerts']
        : _client.get('/alerts/farms/$farmId');
    final response = runtime == null
        ? await request()
        : await runtime.storeOnlineCache('/alerts/farms/$farmId:{}', request);
    return (response as List)
        .map((item) => ClimateAlert.fromJson(item as Map<String, dynamic>))
        .toList();
  }
}
