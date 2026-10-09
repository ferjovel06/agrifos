import '../../domain/entities/lab_analysis.dart';
import 'api_client.dart';
import '../sync/offline_runtime.dart';

class LabAnalysisRepository {
  LabAnalysisRepository({ApiClient? client}) : _client = client ?? ApiClient();

  final ApiClient _client;

  Future<List<LabAnalysis>> listForParcel(String parcelId) async {
    final runtime = OfflineRuntime.shared;
    if (runtime != null) {
      return (await runtime.read(
        'lab_analyses',
        parent: parcelId,
      )).map(LabAnalysis.fromJson).toList();
    }
    final response =
        await _client.get('/lab-analyses', query: {'parcel_id': parcelId})
            as List<dynamic>;
    return response
        .map((item) => LabAnalysis.fromJson(item as Map<String, dynamic>))
        .toList();
  }

  Future<LabAnalysis> create(String parcelId, LabAnalysisInput input) async {
    final runtime = OfflineRuntime.shared;
    if (runtime != null) {
      return LabAnalysis.fromJson(
        await runtime.save('lab_analyses', parcelId, input.toJson()),
      );
    }
    final response = await _client.post('/lab-analyses', {
      'parcel_id': parcelId,
      ...input.toJson(),
    });
    return LabAnalysis.fromJson(response);
  }

  Future<LabAnalysis> update(String id, LabAnalysisInput input) async {
    final runtime = OfflineRuntime.shared;
    if (runtime != null) {
      final row = (await runtime.read(
        'lab_analyses',
      )).where((r) => r['id'] == id).first;
      return LabAnalysis.fromJson(
        await runtime.save(
          'lab_analyses',
          row['parcel_id'] as String,
          input.toJson(),
          id: id,
        ),
      );
    }
    final response = await _client.patch('/lab-analyses/$id', input.toJson());
    return LabAnalysis.fromJson(response);
  }

  Future<void> delete(String id) async {
    final runtime = OfflineRuntime.shared;
    if (runtime != null) {
      if (!runtime.network.operational) {
        throw StateError('La eliminación requiere conexión con el servidor.');
      }
      final row = (await runtime.read(
        'lab_analyses',
      )).where((r) => r['id'] == id).first;
      if (row['_sync_status'] != 'synced') {
        throw StateError(
          'Revisa primero los cambios pendientes de esta muestra.',
        );
      }
    }
    await _client.delete('/lab-analyses/$id');
    if (runtime != null) await runtime.engine.synchronize();
  }
}
