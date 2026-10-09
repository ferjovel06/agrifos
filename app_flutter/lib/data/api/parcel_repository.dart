import '../../domain/entities/crop.dart';
import '../../domain/entities/parcel.dart';
import '../../domain/entities/phenological_stage.dart';
import '../../domain/entities/variety.dart';
import 'api_client.dart';
import '../sync/offline_runtime.dart';

class ParcelRepository {
  final ApiClient _client;

  ParcelRepository({ApiClient? client}) : _client = client ?? ApiClient();

  Future<List<Crop>> getCrops() async {
    final response =
        await (OfflineRuntime.shared?.cachedGet('/crops') ??
            _client.get('/crops'));
    final list = (response as List).cast<Map<String, dynamic>>();
    return list.map(Crop.fromJson).toList();
  }

  Future<List<Parcel>> getParcels(String farmId) async {
    final runtime = OfflineRuntime.shared;
    if (runtime != null) {
      return (await runtime.read(
        'parcels',
        farm: farmId,
      )).map(Parcel.fromJson).toList();
    }
    final response = await _client.get('/parcels', query: {'farm_id': farmId});
    final list = (response as List).cast<Map<String, dynamic>>();
    return list.map(Parcel.fromJson).toList();
  }

  Future<List<Variety>> getVarieties(String cropId) async {
    final response =
        await (OfflineRuntime.shared?.cachedGet(
              '/varieties',
              query: {'crop_id': cropId},
            ) ??
            _client.get('/varieties', query: {'crop_id': cropId}));
    final list = (response as List).cast<Map<String, dynamic>>();
    return list.map(Variety.fromJson).toList();
  }

  Future<List<PhenologicalStageTemplate>> getStageTemplates(
    String cropId,
  ) async {
    final response = await _get(
      '/phenological-stages/templates',
      query: {'crop_id': cropId},
    );
    final list = (response as List).cast<Map<String, dynamic>>();
    return list.map(PhenologicalStageTemplate.fromJson).toList();
  }

  Future<List<PhenologicalStageInstance>> getStageInstances(
    String parcelId,
  ) async {
    final runtime = OfflineRuntime.shared;
    if (runtime != null) {
      return (await runtime.read(
        'parcel_phenological_stages',
        parent: parcelId,
      )).map(PhenologicalStageInstance.fromJson).toList();
    }
    final response = await _get(
      '/phenological-stages/instances',
      query: {'parcel_id': parcelId},
    );
    final list = (response as List).cast<Map<String, dynamic>>();
    return list.map(PhenologicalStageInstance.fromJson).toList();
  }

  Future<void> createStageInstance({
    required String parcelId,
    required String templateId,
    required DateTime actualDate,
  }) async {
    final runtime = OfflineRuntime.shared;
    final account = runtime?.requireAccount();
    await _client.post('/phenological-stages/instances', {
      'parcel_id': parcelId,
      'template_id': templateId,
      'actual_date': _dateOnly(actualDate),
    });
    if (runtime != null) {
      if (runtime.requireAccount() != account) {
        throw ApiAuthException('La cuenta cambió.');
      }
      await runtime.database
          .customStatement('DELETE FROM cache WHERE account=? AND key=?', [
            runtime.requireAccount(),
            '/phenological-stages/instances:{"parcel_id":"$parcelId"}',
          ]);
      await runtime.engine.synchronize();
    }
  }

  Future<Parcel> createParcel({
    required String farmId,
    required String cropId,
    required String varietyId,
    required String name,
    required double areaHectares,
    required int plantsPerHectare,
    required DateTime plantingDate,
  }) async {
    final runtime = OfflineRuntime.shared;
    final account = runtime?.requireAccount();
    final response = await _client.post('/parcels', {
      'farm_id': farmId,
      'crop_id': cropId,
      'variety_id': varietyId,
      'name': name,
      'area_hectares': areaHectares,
      'plants_per_hectare': plantsPerHectare,
      'planting_date': _dateOnly(plantingDate),
    });
    if (runtime != null) {
      if (runtime.requireAccount() != account) {
        throw ApiAuthException('La cuenta cambió.');
      }
      final user = account!;
      await runtime.database.putEntity(
        user,
        'parcels',
        response,
        response["farm_id"] as String,
      );
      await runtime.engine.synchronize();
    }
    return Parcel.fromJson(response);
  }

  Future<Parcel> updateParcel({
    required String id,
    required String cropId,
    required String? varietyId,
    required String name,
    required double areaHectares,
    required int plantsPerHectare,
    required DateTime plantingDate,
  }) async {
    final runtime = OfflineRuntime.shared;
    final account = runtime?.requireAccount();
    final response = await _client.patch('/parcels/$id', {
      'crop_id': cropId,
      'variety_id': varietyId,
      'name': name,
      'area_hectares': areaHectares,
      'plants_per_hectare': plantsPerHectare,
      'planting_date': _dateOnly(plantingDate),
    });
    if (runtime != null) {
      if (runtime.requireAccount() != account) {
        throw ApiAuthException('La cuenta cambió.');
      }
      final user = account!;
      await runtime.database.putEntity(
        user,
        'parcels',
        response,
        response["farm_id"] as String,
      );
      await runtime.engine.synchronize();
    }
    return Parcel.fromJson(response);
  }

  Future<Parcel> updateParcelConfiguration({
    required String id,
    required String cropId,
    required String varietyId,
    required String stageTemplateId,
    required String name,
    required double areaHectares,
    required int plantsPerHectare,
    required DateTime plantingDate,
  }) async {
    final runtime = OfflineRuntime.shared;
    final account = runtime?.requireAccount();
    final response = await _client.patch('/parcels/$id/configuration', {
      'crop_id': cropId,
      'variety_id': varietyId,
      'phenological_stage_template_id': stageTemplateId,
      'name': name,
      'area_hectares': areaHectares,
      'plants_per_hectare': plantsPerHectare,
      'planting_date': _dateOnly(plantingDate),
    });
    if (runtime != null) {
      if (runtime.requireAccount() != account) {
        throw ApiAuthException('La cuenta cambió.');
      }
      final user = account!;
      await runtime.database.putEntity(
        user,
        'parcels',
        response,
        response["farm_id"] as String,
      );
      await runtime.engine.synchronize();
    }
    return Parcel.fromJson(response);
  }

  Future<dynamic> _get(String path, {Map<String, String>? query}) =>
      OfflineRuntime.shared?.cachedGet(path, query: query) ??
      _client.get(path, query: query);

  String _dateOnly(DateTime date) {
    final month = date.month.toString().padLeft(2, '0');
    final day = date.day.toString().padLeft(2, '0');
    return '${date.year}-$month-$day';
  }
}
