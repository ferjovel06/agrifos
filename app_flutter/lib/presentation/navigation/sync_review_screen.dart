import 'package:flutter/material.dart';
import '../../data/api/lab_analysis_repository.dart';
import '../../data/sync/offline_runtime.dart';
import '../../domain/entities/lab_analysis.dart';
import '../lab_analysis/lab_analysis_screen.dart';

const _labels = {
  'nitrogen': 'Nitrógeno',
  'phosphorus': 'Fósforo',
  'potassium': 'Potasio',
  'ph': 'pH',
  'ec': 'Conductividad (dS/m)',
  'sample_code': 'Código de muestra',
  'lab': 'Laboratorio',
  'sampled_at': 'Fecha de muestreo',
  'organic_matter_pct': 'Materia orgánica (%)',
  'cic': 'CIC',
  'calcium': 'Calcio',
  'magnesium': 'Magnesio',
  'sulfur': 'Azufre',
  'depth_start_cm': 'Profundidad inicial (cm)',
  'depth_end_cm': 'Profundidad final (cm)',
  'clay_pct': 'Arcilla (%)',
  'silt_pct': 'Limo (%)',
  'sand_pct': 'Arena (%)',
};

class SyncReviewScreen extends StatefulWidget {
  const SyncReviewScreen({super.key});
  @override
  State<SyncReviewScreen> createState() => _SyncReviewScreenState();
}

class _SyncReviewScreenState extends State<SyncReviewScreen> {
  final runtime = OfflineRuntime.shared!;
  late final String? account = runtime.account;
  String? _error;
  Future<void> _resolve(Map<String, dynamic> op) async {
    try {
      await runtime.resolve(op['operation_id'] as String, useRemote: true);
    } catch (_) {
      if (mounted) {
        setState(
          () => _error =
              'No se pudo aplicar la revisión. La información sigue guardada.',
        );
      }
    }
  }

  Future<void> _edit(Map<String, dynamic> op) async {
    final row = await runtime.database.entity(
      account!,
      'lab_analyses',
      op['entity_id'] as String,
    );
    if (!mounted || runtime.account != account || row == null) return;
    await Navigator.of(context).push(
      MaterialPageRoute<bool>(
        builder: (_) => LabAnalysisFormScreen(
          parcelId: row['parcel_id'] as String,
          analysis: LabAnalysis.fromJson(row),
          repository: LabAnalysisRepository(),
          onUpdate: (_, input) => runtime.resolve(
            op['operation_id'] as String,
            corrected: input.toJson(),
          ),
        ),
      ),
    );
    if (mounted) setState(() {});
  }

  @override
  Widget build(BuildContext context) => AnimatedBuilder(
    animation: Listenable.merge([runtime, runtime.engine]),
    builder: (context, _) {
      if (runtime.account != account || !runtime.localAccess) {
        return Scaffold(
          appBar: AppBar(title: const Text('Cambios guardados')),
          body: const Center(
            child: Text('La cuenta cambió. Vuelve a iniciar sesión.'),
          ),
        );
      }
      return Scaffold(
        appBar: AppBar(title: const Text('Cambios guardados')),
        body: FutureBuilder<List<Map<String, dynamic>>>(
          future: runtime.database.operations(account!),
          builder: (context, snapshot) {
            if (!snapshot.hasData) {
              return const Center(child: CircularProgressIndicator());
            }
            return ListView(
              padding: const EdgeInsets.all(16),
              children: [
                const Text(
                  'Los cambios siguen guardados en este dispositivo. Revisa las versiones antes de elegir; el historial conserva tu registro original.',
                ),
                if (_error != null)
                  Text(_error!, style: const TextStyle(color: Colors.red)),
                ...snapshot.data!.reversed.map((op) {
                  dynamic remote = op['remote'];
                  if (remote is Map && remote.containsKey('remote')) {
                    remote = remote['remote'];
                  }
                  final payload = op['payload'] as Map;
                  final review =
                      op['status'] == 'conflict' ||
                      op['status'] == 'failed_permanent';
                  final label = switch (op['status']) {
                    'synced' => 'Confirmado o archivado tras revisión',
                    'conflict' => 'Requiere revisión: hay cambios remotos',
                    'failed_permanent' =>
                      'Requiere revisión: no se pudo guardar en el servidor',
                    'retry_wait' => 'Pendiente de sincronizar; en espera',
                    'in_progress' => 'Sincronizando…',
                    _ => 'Pendiente de sincronizar',
                  };
                  return Card(
                    child: ExpansionTile(
                      title: Text(
                        op['entity'] == 'readings'
                            ? 'Lectura de suelo'
                            : '${payload['sample_code'] ?? 'Muestra de laboratorio'}',
                      ),
                      subtitle: Text(label),
                      children: [
                        Padding(
                          padding: const EdgeInsets.all(12),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              if (remote is Map && remote['deleted'] == true)
                                const Text(
                                  'La muestra fue eliminada en el servidor.',
                                ),
                              ...payload.entries
                                  .where(
                                    (entry) => _labels.containsKey(entry.key),
                                  )
                                  .map(
                                    (entry) => Padding(
                                      padding: const EdgeInsets.symmetric(
                                        vertical: 3,
                                      ),
                                      child: Text(
                                        '${_labels[entry.key]} · En dispositivo: ${entry.value}${remote is Map && remote[entry.key] != null ? ' · En servidor: ${remote[entry.key]}' : ''}',
                                      ),
                                    ),
                                  ),
                              if (review &&
                                  remote is Map &&
                                  (remote['id'] != null ||
                                      remote['deleted'] == true))
                                TextButton(
                                  onPressed: () => _resolve(op),
                                  child: const Text(
                                    'Conservar versión del servidor',
                                  ),
                                ),
                              if (review && op['entity'] == 'lab_analyses')
                                TextButton(
                                  onPressed: () => _edit(op),
                                  child: const Text(
                                    'Revisar mi muestra y reenviar',
                                  ),
                                ),
                              if (op['error_code'] == 'retry_exhausted')
                                TextButton(
                                  onPressed: () => runtime.resolve(
                                    op['operation_id'] as String,
                                  ),
                                  child: const Text(
                                    'Reintentar el mismo cambio',
                                  ),
                                ),
                            ],
                          ),
                        ),
                      ],
                    ),
                  );
                }),
              ],
            );
          },
        ),
      );
    },
  );
}
