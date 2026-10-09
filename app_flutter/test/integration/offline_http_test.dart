import 'dart:convert';
import 'dart:io';
import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:app_flutter/core/network_health.dart';
import 'package:app_flutter/data/api/api_client.dart';
import 'package:app_flutter/data/local/offline_database.dart';
import 'package:app_flutter/data/sync/offline_runtime.dart';
import 'package:app_flutter/data/sync/sync_engine.dart';
import '../support/offline_fixture.dart' show MemoryVault;

class LostAcknowledgementClient extends http.BaseClient {
  final delegate = http.Client();
  bool lost = false;
  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    final response = await delegate.send(request);
    if (!lost &&
        request.method == 'POST' &&
        request.url.path == '/sync/operations' &&
        request is http.Request &&
        (jsonDecode(request.body) as Map)['entity'] == 'readings' &&
        response.statusCode == 200) {
      await response.stream.drain<void>();
      lost = true;
      throw http.ClientException(
        'Deliberate lost response after a real PostgreSQL commit',
      );
    }
    return response;
  }

  @override
  void close() => delegate.close();
}

void main() {
  const path = String.fromEnvironment('OFFLINE_FIXTURE_PATH');
  test(
    'A/C/D/E: reopen SQLite, reconnect over real HTTP, replay receipt and review real conflict',
    () async {
      final config =
          jsonDecode(await File(path).readAsString()) as Map<String, dynamic>;
      final user = config['user'] as String;
      final parcel = config['parcel'] as String;
      final folder = await Directory.systemTemp.createTemp(
        'agrifos-offline-http-',
      );
      final file = File('${folder.path}/offline.sqlite');
      final vault =
          MemoryVault(); // OS keychain validation is separate from this protocol test.
      final key = SecretKey(List.filled(32, 11));
      final network = NetworkHealth()..hint(true);
      final transport = LostAcknowledgementClient();
      final client = ApiClient(
        baseUrl: config['base_url'] as String,
        httpClient: transport,
        tokenProvider: () => config['token'] as String,
        userProvider: () => user,
        network: network,
      );
      var now = DateTime.now();
      late OfflineDatabase db;
      late SyncEngine engine;
      late OfflineRuntime runtime;
      void open() {
        db = OfflineDatabase.file(file.path, accountKey: (_) async => key);
        engine = SyncEngine(
          database: db,
          client: client,
          identity: () => user,
          refreshSession: () async => false,
          network: network,
          clock: () => now,
        );
        runtime = OfflineRuntime(
          database: db,
          client: client,
          vault: vault,
          engine: engine,
          network: network,
          clock: () => now,
        );
      }

      open();
      try {
        expect(await runtime.authorize(user), isTrue);
        await engine.synchronize();
        expect(
          (await runtime.read(
            'farms',
          )).any((row) => row['id'] == config['farm']),
          isTrue,
        );
        network.hint(false);
        final readingPayload = config['reading_payload'] == null
            ? {
                'nitrogen': 20,
                'phosphorus': 10,
                'potassium': 30,
                'ph': 6,
                'ec': 0.4,
                'temperature': 24,
                'humidity': 60,
                'recorded_at': now.toUtc().toIso8601String(),
              }
            : Map<String, dynamic>.from(config['reading_payload'] as Map);
        final reading = await runtime.save('readings', parcel, readingPayload);
        final labPayload = Map<String, dynamic>.from(
          config['lab_payload'] as Map,
        )..remove('parcel_id');
        final lab = await runtime.save('lab_analyses', parcel, labPayload);
        final queued = await db.operations(user);
        expect(queued.length, 2);
        expect(queued.every((op) => op['status'] == 'pending'), isTrue);
        final operation = queued.firstWhere(
          (op) => op['entity_id'] == reading['id'],
        )['operation_id'];
        engine.dispose();
        await db.close();
        open();
        expect(await runtime.authorize(user), isTrue);
        expect((await runtime.read('readings')).single['id'], reading['id']);
        if (config['reading_payload'] != null) {
          final restored = (await runtime.read('readings')).single;
          expect(restored['measurement'], readingPayload['measurement']);
          expect(restored['recorded_at'], readingPayload['recorded_at']);
          expect(restored['humidity'], isNull);
        }
        network.hint(true);
        await engine.synchronize();
        expect(transport.lost, isTrue);
        expect(
          (await db.operations(
            user,
          )).firstWhere((op) => op['operation_id'] == operation)['status'],
          'retry_wait',
        );
        now = now.add(const Duration(minutes: 20));
        network.hint(true);
        await Future.wait([engine.synchronize(), engine.synchronize()]);
        expect(
          (await db.operations(user)).every((op) => op['status'] == 'synced'),
          isTrue,
        );
        if (config['reading_payload'] != null) {
          final processed = (await runtime.read('readings')).single;
          final results = (processed['derived_results'] as List).cast<Map>();
          expect(results, isNotEmpty);
          expect(results.single['reading_id'], reading['id']);
          expect((results.single['variables'] as Map)['nitrogen'], isNotNull);
          final original =
              ((readingPayload['measurement'] as Map)['variables']
                      as Map)['nitrogen']
                  as Map;
          final received =
              ((processed['measurement'] as Map)['variables']
                      as Map)['nitrogen']
                  as Map;
          for (final entry in original.entries) {
            expect(received[entry.key], entry.value);
          }
          expect(await db.pendingProcessing(user), isEmpty);
          await engine.synchronize();
          expect(
            (await runtime.read('readings')).single['derived_results'],
            results,
          );
        }
        final local = (await runtime.read('lab_analyses')).single;
        expect(local['revision'], 1);
        await client.patch('/lab-analyses/${lab['id']}', {'nitrogen': 77});
        network.hint(false);
        await runtime.save('lab_analyses', parcel, {
          ...labPayload,
          'nitrogen': 55,
        }, id: lab['id'] as String);
        network.hint(true);
        await engine.synchronize();
        final conflict = (await db.operations(
          user,
        )).where((op) => op['status'] == 'conflict').single;
        expect((conflict['payload'] as Map)['nitrogen'], 55);
        expect((conflict['remote'] as Map)['nitrogen'], 77);
        expect((await runtime.read('lab_analyses')).single['nitrogen'], 55);
        network.hint(false);
        await runtime.resolve(
          conflict['operation_id'] as String,
          useRemote: true,
        );
        expect((await runtime.read('lab_analyses')).single['nitrogen'], 77);
        final history = (await db.operations(
          user,
        )).where((op) => op['operation_id'] == conflict['operation_id']).single;
        expect((history['payload'] as Map)['nitrogen'], 55);
        await File('.dart_tool/offline-result.json').writeAsString(
          jsonEncode({
            'reading': reading['id'],
            'operation': operation,
            'lab': lab['id'],
            'initial_queued_operations': 2,
            'deferred_processing_returned': config['reading_payload'] != null,
          }),
        );
      } finally {
        engine.dispose();
        await db.close();
        transport.close();
      }
    },
    skip: path.isEmpty
        ? 'NOT RUN: run scripts/offline_integration.py against an isolated PostgreSQL fixture'
        : false,
    timeout: const Timeout(Duration(minutes: 2)),
  );
}
