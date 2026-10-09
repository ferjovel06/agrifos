import '../../domain/entities/farm.dart';
import 'api_client.dart';
import '../sync/offline_runtime.dart';

/// Talks to the Agrifos backend's `/farms` endpoints.
class FarmRepository {
  final ApiClient _client;

  FarmRepository({ApiClient? client}) : _client = client ?? ApiClient();

  /// Fetches every farm owned by the current user.
  Future<List<Farm>> getFarms() async {
    final runtime = OfflineRuntime.shared;
    if (runtime != null) {
      return (await runtime.read('farms')).map(Farm.fromJson).toList();
    }
    final response = await _client.get('/farms');
    final list = (response as List).cast<Map<String, dynamic>>();
    return list.map(Farm.fromJson).toList();
  }

  /// Creates a new farm for the current user.
  Future<Farm> createFarm({
    required String name,
    required double areaHectares,
    required double latitude,
    required double longitude,
  }) async {
    final runtime = OfflineRuntime.shared;
    Future<dynamic> request() => _client.post('/farms', {
      'name': name,
      'area_hectares': areaHectares,
      'latitude': latitude,
      'longitude': longitude,
    });
    final response = runtime == null
        ? await request()
        : await runtime.storeOnlineEntity('farms', request);
    return Farm.fromJson(response);
  }

  Future<Farm> updateFarm({
    required String id,
    required String name,
    required double areaHectares,
    required double latitude,
    required double longitude,
  }) async {
    final runtime = OfflineRuntime.shared;
    Future<dynamic> request() => _client.patch('/farms/$id', {
      'name': name,
      'area_hectares': areaHectares,
      'latitude': latitude,
      'longitude': longitude,
    });
    final response = runtime == null
        ? await request()
        : await runtime.storeOnlineEntity('farms', request);
    return Farm.fromJson(response);
  }
}
