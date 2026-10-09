import 'package:flutter/material.dart';
import '../../core/network_health.dart';
import '../../data/sync/offline_runtime.dart';
import 'sync_review_screen.dart';

class SyncStatusBar extends StatelessWidget {
  const SyncStatusBar({super.key});
  @override
  Widget build(BuildContext context) {
    final runtime = OfflineRuntime.shared!;
    final engine = runtime.engine;
    return AnimatedBuilder(
      animation: Listenable.merge([engine, runtime.network, runtime]),
      builder: (context, _) {
        final review = engine.pending.any(
          (op) =>
              op['status'] == 'conflict' || op['status'] == 'failed_permanent',
        );
        final connection = switch (runtime.network.state) {
          BackendReachability.offline => 'Sin conexión',
          BackendReachability.unreachable => 'Servidor inaccesible',
          BackendReachability.unknown => 'Comprobando conexión',
          BackendReachability.operational => 'Conexión disponible',
        };
        final status = engine.syncing
            ? 'Sincronizando…'
            : review
            ? 'Requiere revisión'
            : engine.error != null
            ? 'No se pudo sincronizar'
            : engine.pending.isNotEmpty
            ? '${engine.pending.length} cambios pendientes'
            : engine.syncedAt != null
            ? 'Todo sincronizado'
            : 'Preparando datos';
        final last = engine.syncedAt;
        return Padding(
          padding: const EdgeInsets.only(bottom: 8),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Wrap(
                spacing: 8,
                crossAxisAlignment: WrapCrossAlignment.center,
                children: [
                  Semantics(
                    liveRegion: true,
                    child: Text(
                      '$connection · $status',
                      style: const TextStyle(fontSize: 12),
                    ),
                  ),
                  TextButton(
                    onPressed: engine.syncing ? null : engine.synchronize,
                    child: const Text('Sincronizar ahora'),
                  ),
                  if (engine.pending.isNotEmpty)
                    TextButton(
                      onPressed: () => Navigator.of(context).push(
                        MaterialPageRoute<void>(
                          builder: (_) => const SyncReviewScreen(),
                        ),
                      ),
                      child: const Text('Ver cambios'),
                    ),
                ],
              ),
              Text(
                'Datos guardados en este dispositivo${last == null ? '' : ' · Última sincronización: ${last.toLocal().day}/${last.toLocal().month} ${last.toLocal().hour.toString().padLeft(2, '0')}:${last.toLocal().minute.toString().padLeft(2, '0')}'}',
                style: const TextStyle(fontSize: 10, color: Colors.black54),
              ),
            ],
          ),
        );
      },
    );
  }
}
