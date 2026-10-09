import 'dart:convert';
import 'dart:io';
import 'package:cryptography/cryptography.dart';
import 'package:drift/drift.dart' show MigrationStrategy;
import 'package:drift/native.dart';
import 'package:app_flutter/data/local/offline_database.dart';
import 'package:app_flutter/data/api/api_client.dart';
import 'package:app_flutter/data/api/readings_repository.dart';
import 'package:app_flutter/data/sensor/sensor_reading.dart';
import 'package:app_flutter/data/sync/offline_runtime.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/testing.dart';
import '../support/offline_fixture.dart';
import '../support/sensor_fixture.dart';

SensorReading capture(
  DateTime at, {
  String point = 'p1',
  String session = '58d763ad-19fd-4d19-a4ed-180ab7c66d36',
}) => SensorReading.decode(
  profile: syntheticProfile(),
  frame: syntheticFrame(),
  sessionId: session,
  deviceId: 'synthetic-unit',
  acquiredAt: at,
).withSamplingContext(pointId: point, depthCm: 20);

Map<String, dynamic> stored(
  SensorReading reading,
  String id, {
  List? results,
}) => {
  'id': id,
  'parcel_id': 'parcel-a',
  ...reading.payload(),
  'revision': 1,
  'derived_results': results ?? [],
};

void main() {
  tearDown(() => OfflineRuntime.shared = null);
  test(
    'failed v1 backfill rolls back DDL and can reopen with the correct account key',
    () async {
      final folder = await Directory.systemTemp.createTemp(
        'agrifos-sensor-upgrade-rollback-',
      );
      final file = File('${folder.path}/offline.sqlite');
      Future<SecretKey> key(String _) async => SecretKey(List.filled(32, 17));
      final old = _OfflineV1(NativeDatabase(file), accountKey: key);
      final originalCiphertexts = <String, String>{};
      for (final id in ['raw-a', 'raw-b']) {
        final row = stored(capture(DateTime.utc(2026, 10, 8)), id);
        final ciphertext = await old.encrypt('account', 'readings:$id', row);
        originalCiphertexts[id] = ciphertext;
        await old.customStatement(
          'INSERT INTO entities(account,kind,id,farm,parent,data,revision,dirty) VALUES(?,?,?,?,?,?,?,?)',
          ['account', 'readings', id, 'farm-a', 'parcel-a', ciphertext, 1, 0],
        );
      }
      final queued = await old.encrypt('account', 'operation:op', {
        'original': 'kept',
      });
      await old.customStatement(
        'INSERT INTO outbox(account,operation_id,entity_id,entity,operation,payload_version,farm,payload,created_at,status) VALUES(?,?,?,?,?,1,?,?,0,?)',
        [
          'account',
          'op',
          'raw-pending',
          'readings',
          'create',
          'farm-a',
          queued,
          'pending',
        ],
      );
      await old.close();
      var keyCalls = 0;
      final failing = OfflineDatabase(
        NativeDatabase(file),
        accountKey: (_) async {
          if (++keyCalls == 3) {
            throw StateError('Fixture key unavailable midway through backfill');
          }
          return key('account');
        },
      );
      await expectLater(
        failing.entity('account', 'readings', 'raw-a'),
        throwsStateError,
      );
      await failing.close();
      final inspect = _OfflineV1(NativeDatabase(file), accountKey: key);
      expect(
        (await inspect.rows('PRAGMA user_version', [])).single['user_version'],
        1,
      );
      expect(
        (await inspect.rows(
          'PRAGMA table_info(entities)',
          [],
        )).map((row) => row['name']),
        isNot(contains('processing_pending')),
      );
      expect(
        (await inspect.rows('SELECT data FROM entities WHERE id=?', [
          'raw-a',
        ])).single['data'],
        originalCiphertexts['raw-a'],
      );
      expect((await inspect.operations('account')).single['payload'], {
        'original': 'kept',
      });
      await inspect.close();
      final repaired = OfflineDatabase(NativeDatabase(file), accountKey: key);
      expect(
        (await repaired.entity('account', 'readings', 'raw-a'))!['nitrogen'],
        25,
      );
      expect(
        (await repaired.rows('PRAGMA user_version', [])).single['user_version'],
        2,
      );
      expect(
        (await repaired.rows('SELECT data FROM entities WHERE id=?', [
          'raw-b',
        ])).single['data'],
        originalCiphertexts['raw-b'],
      );
      expect((await repaired.operations('account')).single['payload'], {
        'original': 'kept',
      });
      await repaired.close();
      await folder.delete(recursive: true);
    },
  );
  test(
    'more than 200 repeats require an explicit batch and do not prevent a separate point',
    () async {
      final f = OfflineFixture();
      await f.prepare();
      final samePoint = capture(f.clock);
      for (var i = 0; i < 201; i++) {
        await f.database.putEntity(
          f.user!,
          'readings',
          stored(samePoint, 'large-${i.toString().padLeft(3, '0')}'),
          'farm-a',
          parent: 'parcel-a',
        );
      }
      await f.database.putEntity(
        f.user!,
        'readings',
        stored(
          capture(
            f.clock,
            point: 'p2',
            session: 'independent-sampling-session',
          ),
          'small',
        ),
        'farm-a',
        parent: 'parcel-a',
      );
      final batches = <List>[];
      f.handler = (request) async {
        if (request.url.path == '/users/me') {
          return OfflineFixture.json({'id': f.user, 'role': 'farmer'});
        }
        if (request.url.path == '/readings/process') {
          final ids = (jsonDecode(request.body) as Map)['reading_ids'] as List;
          batches.add(ids);
          return OfflineFixture.json(
            ids.map((id) => {'reading_id': id}).toList(),
          );
        }
        return OfflineFixture.json({
          'changes': [],
          'cursor': 'bounded',
          'has_more': false,
        });
      };
      await f.engine.synchronize();
      expect(batches, [
        ['small'],
      ]);
      expect(f.engine.error, contains('Grupo mayor de 200'));
      expect((await f.database.pendingProcessing(f.user!)).length, 2);
      await f.close();
    },
  );
  test(
    'real SQLite v1 upgrade retains ciphertext, original data, outbox and checkpoint',
    () async {
      final folder = await Directory.systemTemp.createTemp(
        'agrifos-sensor-v1-',
      );
      final file = File('${folder.path}/offline.sqlite');
      Future<SecretKey> key(String _) async => SecretKey(List.filled(32, 17));
      final old = _OfflineV1(NativeDatabase(file), accountKey: key);
      final row = stored(capture(DateTime.utc(2026, 10, 8)), 'raw-a');
      final ciphertext = await old.encrypt('account', 'readings:raw-a', row);
      await old.customStatement(
        'INSERT INTO entities(account,kind,id,farm,parent,data,revision,dirty) VALUES(?,?,?,?,?,?,?,?)',
        [
          'account',
          'readings',
          'raw-a',
          'farm-a',
          'parcel-a',
          ciphertext,
          1,
          0,
        ],
      );
      final payload = {'parcel_id': 'parcel-a', 'nitrogen': 25};
      final queued = await old.encrypt('account', 'operation:op-a', payload);
      await old.customStatement(
        'INSERT INTO outbox(account,operation_id,entity_id,entity,operation,payload_version,farm,payload,created_at,status) VALUES(?,?,?,?,?,1,?,?,0,?)',
        [
          'account',
          'op-a',
          'new-raw',
          'readings',
          'create',
          'farm-a',
          queued,
          'pending',
        ],
      );
      await old.customStatement(
        'INSERT INTO checkpoints(account,cursor,synced_at) VALUES(?,?,?)',
        ['account', 'kept-cursor', 0],
      );
      await old.close();
      final upgraded = OfflineDatabase(NativeDatabase(file), accountKey: key);
      expect(
        (await upgraded.entity('account', 'readings', 'raw-a'))!['measurement'],
        row['measurement'],
      );
      expect(
        (await upgraded.rows('SELECT data FROM entities', [])).single['data'],
        ciphertext,
      );
      expect((await upgraded.operations('account')).single['payload'], payload);
      expect(await upgraded.cursor('account'), 'kept-cursor');
      expect((await upgraded.pendingProcessing('account')).length, 1);
      final token = (await upgraded.rows(
        'SELECT processing_group FROM entities',
        [],
      )).single['processing_group'];
      expect(token, matches(RegExp(r'^[0-9a-f]{64}$')));
      expect(token, isNot(contains('p1')));
      await upgraded.close();
      await folder.delete(recursive: true);
    },
  );
  test(
    'existing encrypted outbox keeps acquisition time, UUID, omissions and immutable evidence',
    () async {
      final f = OfflineFixture();
      await f.prepare();
      f.network.hint(false);
      OfflineRuntime.shared = f.runtime;
      final reading = capture(f.clock.subtract(const Duration(hours: 1)));
      final repository = ReadingsRepository(client: f.client);
      final first = await repository.submitReading(
        parcelId: 'parcel-a',
        reading: reading,
      );
      final retry = await repository.submitReading(
        parcelId: 'parcel-a',
        reading: reading,
      );
      expect(first.id, reading.measurementId);
      expect(retry.id, first.id);
      expect(first.recordedAt.toUtc(), reading.acquiredAt);
      expect(first.phosphorus, isNull);
      final operations = await f.database.operations(f.user!);
      expect(operations.length, 1);
      expect(
        (operations.single['payload'] as Map)['measurement'],
        reading.measurement!.toJson(),
      );
      expect(
        (operations.single['payload'] as Map)['recorded_at'],
        reading.acquiredAt.toIso8601String(),
      );
      await expectLater(
        repository.submitReading(
          parcelId: 'parcel-a',
          reading: reading.withSamplingContext(pointId: 'another'),
        ),
        throwsStateError,
      );
      final latest = await repository.getLatestReading('parcel-a');
      expect(latest!.measurement!['point_id'], 'p1');
      expect(f.calls, isEmpty);
      await f.close();
    },
  );
  test(
    'remote optional nulls and reordered keys preserve capture idempotence without changing evidence',
    () async {
      final f = OfflineFixture();
      await f.prepare();
      f.network.hint(false);
      OfflineRuntime.shared = f.runtime;
      final reading = capture(f.clock.subtract(const Duration(hours: 1)));
      final repository = ReadingsRepository(client: f.client);
      await repository.submitReading(parcelId: 'parcel-a', reading: reading);
      final operation = (await f.database.operations(f.user!)).single;
      final measurement = reading.measurement!.toJson();
      final variables = measurement['variables'] as Map;
      final remote =
          Map<String, dynamic>.fromEntries(
            measurement.entries.toList().reversed,
          )..addAll({
            'location': null,
            'soil_type': null,
            'variables': Map.fromEntries(
              variables.entries.toList().reversed.map(
                (entry) => MapEntry(entry.key, {
                  ...Map.fromEntries(
                    (entry.value as Map).entries.toList().reversed,
                  ),
                  'declared_range': entry.value['declared_range'],
                }),
              ),
            ),
          });
      await f.database.acknowledge(f.user!, operation, {
        ...stored(reading, reading.measurementId),
        'measurement': remote,
      });
      final same = await repository.submitReading(
        parcelId: 'parcel-a',
        reading: reading,
      );
      expect(same.id, reading.measurementId);
      expect(same.syncStatus, 'synced');
      expect((await f.database.operations(f.user!)).single['status'], 'synced');
      for (final mutation in ['point', 'range', 'value']) {
        final changed =
            jsonDecode(jsonEncode(reading.payload())) as Map<String, dynamic>;
        final evidence = changed['measurement'] as Map;
        if (mutation == 'point') {
          evidence['point_id'] = 'another-point';
        } else if (mutation == 'range') {
          evidence['variables']['nitrogen']['declared_range'] = [100, 0];
        } else {
          evidence['variables']['nitrogen']['raw_value'] = 26;
        }
        await expectLater(
          f.runtime.save('readings', 'parcel-a', changed),
          throwsStateError,
        );
      }
      await f.close();
    },
  );
  test(
    'online provenanced reading displays without forbidden legacy diagnostics',
    () async {
      final reading = capture(DateTime.utc(2026, 10, 8));
      final calls = <String>[];
      final client = ApiClient(
        baseUrl: 'https://fixture.invalid',
        tokenProvider: () => 'fixture',
        httpClient: MockClient((request) async {
          calls.add(request.url.path);
          if (request.url.path == '/readings') {
            return OfflineFixture.json([stored(reading, 'measurement')]);
          }
          return OfflineFixture.json({
            'detail': 'Legacy diagnosis intentionally unsupported',
          }, status: 422);
        }),
      );
      final latest = await ReadingsRepository(
        client: client,
      ).getLatestReading('parcel-a');
      expect(latest!.nitrogen, 25);
      expect(latest.measurement, isNotNull);
      expect(calls, ['/readings']);
    },
  );
  test(
    'processing failure preserves synced raw data and retries once on next sync',
    () async {
      final f = OfflineFixture();
      await f.prepare();
      final reading = capture(f.clock.subtract(const Duration(hours: 1)));
      final original = stored(reading, 'raw-a');
      await f.database.putEntity(
        f.user!,
        'readings',
        original,
        'farm-a',
        parent: 'parcel-a',
      );
      var attempts = 0;
      List<Map<String, dynamic>> results = [];
      f.handler = (request) async {
        if (request.url.path == '/users/me') {
          return OfflineFixture.json({'id': f.user, 'role': 'farmer'});
        }
        if (request.url.path == '/readings/process') {
          attempts++;
          final payload = jsonDecode(request.body) as Map;
          expect(payload['reading_ids'], ['raw-a']);
          expect(payload.containsKey('calibration_id'), isFalse);
          if (attempts == 1) {
            return OfflineFixture.json({
              'detail': 'Temporary processing failure',
            }, status: 503);
          }
          results = [
            {
              'id': 'derived-a',
              'reading_id': 'raw-a',
              'algorithm_version': 'fixture',
              'variables': {},
            },
          ];
          return OfflineFixture.json(results);
        }
        return OfflineFixture.json({
          'changes': [
            {
              'entity': 'readings',
              'entity_id': 'raw-a',
              'farm_id': 'farm-a',
              'operation': 'upsert',
              'data': {...original, 'derived_results': results},
            },
          ],
          'cursor': 'fixture-cursor',
          'has_more': false,
        });
      };
      await f.engine.synchronize();
      expect(attempts, 1);
      expect(f.engine.error, contains('Originales guardados'));
      expect((await f.database.pendingProcessing(f.user!)).length, 1);
      expect(
        (await f.database.entity(
          f.user!,
          'readings',
          'raw-a',
        ))!['_sync_status'],
        'synced',
      );
      await f.engine.synchronize();
      expect(attempts, 2);
      expect(await f.database.pendingProcessing(f.user!), isEmpty);
      expect(
        (await f.database.entity(f.user!, 'readings', 'raw-a'))!['measurement'],
        original['measurement'],
      );
      await f.engine.synchronize();
      expect(attempts, 2);
      expect(await f.database.operations(f.user!), isEmpty);
      await f.close();
    },
  );
  test(
    'duplicate processing acknowledgements leave all originals pending',
    () async {
      final f = OfflineFixture();
      await f.prepare();
      for (final id in ['raw-a', 'raw-b']) {
        await f.database.putEntity(
          f.user!,
          'readings',
          stored(capture(f.clock), id),
          'farm-a',
          parent: 'parcel-a',
        );
      }
      f.handler = (request) async {
        if (request.url.path == '/users/me') {
          return OfflineFixture.json({'id': f.user, 'role': 'farmer'});
        }
        if (request.url.path == '/readings/process') {
          return OfflineFixture.json([
            {'reading_id': 'raw-a'},
            {'reading_id': 'raw-a'},
          ]);
        }
        return OfflineFixture.json({
          'changes': [],
          'cursor': 'kept',
          'has_more': false,
        });
      };
      await f.engine.synchronize();
      expect(f.engine.error, contains('Procesamiento pendiente'));
      final pending = await f.database.pendingProcessing(f.user!);
      expect(pending.length, 1);
      final members = await f.database.processingGroup(
        f.user!,
        pending.single['_processing_group'] as String,
      );
      expect(members.map((row) => row['id']).toSet(), {'raw-a', 'raw-b'});
      expect(await f.database.operations(f.user!), isEmpty);
      await f.close();
    },
  );
  test(
    'same session sends every parcel, device and decoder boundary to the backend',
    () async {
      final f = OfflineFixture();
      await f.prepare();
      final rows = <Map<String, dynamic>>[];
      for (var index = 0; index < 3; index++) {
        final row = stored(
          capture(f.clock.subtract(Duration(minutes: 3 - index))),
          'boundary-$index',
        );
        if (index == 1) {
          row['parcel_id'] = 'parcel-b';
          row['measurement'] = {
            ...row['measurement'] as Map,
            'device_id': 'another-physical-unit',
            'sensor_model': 'another-synthetic-model',
            'protocol_version': 'another-synthetic-protocol',
            'profile_id': 'another-synthetic-decoder',
          };
        }
        rows.add(row);
        await f.database.putEntity(
          f.user!,
          'readings',
          row,
          'farm-a',
          parent: row['parcel_id'] as String,
        );
      }
      final batches = <List>[];
      f.handler = (request) async {
        if (request.url.path == '/users/me') {
          return OfflineFixture.json({'id': f.user, 'role': 'farmer'});
        }
        if (request.url.path == '/readings/process') {
          final ids = (jsonDecode(request.body) as Map)['reading_ids'] as List;
          batches.add(ids);
          return OfflineFixture.json(
            ids.map((id) => {'reading_id': id}).toList(),
          );
        }
        return OfflineFixture.json({
          'changes': [],
          'cursor': 'kept',
          'has_more': false,
        });
      };
      expect((await f.database.pendingProcessing(f.user!)).length, 1);
      await f.engine.synchronize();
      expect(batches, [
        ['boundary-0', 'boundary-1', 'boundary-2'],
      ]);
      await f.close();
    },
  );
  test(
    'processing sends the entire A,A,B,A,A,A route and prior versions only with new repeats',
    () async {
      final f = OfflineFixture();
      await f.prepare();
      final rows = <String, Map<String, dynamic>>{};
      final points = ['A', 'A', 'B', 'A', 'A', 'A'];
      for (var index = 0; index < points.length; index++) {
        final point = points[index], id = '$index';
        final reading = capture(
          f.clock
              .subtract(const Duration(hours: 1))
              .add(Duration(seconds: index)),
          point: point,
        );
        rows[id] = stored(reading, id);
        await f.database.putEntity(
          f.user!,
          'readings',
          rows[id]!,
          'farm-a',
          parent: 'parcel-a',
        );
      }
      final batches = <List>[];
      f.handler = (request) async {
        if (request.url.path == '/users/me') {
          return OfflineFixture.json({'id': f.user, 'role': 'farmer'});
        }
        if (request.url.path == '/readings/process') {
          final ids = (jsonDecode(request.body) as Map)['reading_ids'] as List;
          batches.add(ids);
          final results = ids
              .map(
                (id) => {
                  'id': 'derived-$id',
                  'reading_id': id,
                  'variables': {},
                },
              )
              .toList();
          for (final result in results) {
            rows[result['reading_id']]!['derived_results'] = [result];
          }
          return OfflineFixture.json(results);
        }
        return OfflineFixture.json({
          'changes': rows.entries
              .map(
                (row) => {
                  'entity': 'readings',
                  'entity_id': row.key,
                  'farm_id': 'farm-a',
                  'operation': 'upsert',
                  'data': row.value,
                },
              )
              .toList(),
          'cursor': 'fixture-cursor',
          'has_more': false,
        });
      };
      await f.engine.synchronize();
      expect(batches, [
        ['0', '1', '2', '3', '4', '5'],
      ]);
      rows['repeat'] = stored(capture(f.clock, point: 'A'), 'repeat');
      await f.database.putEntity(
        f.user!,
        'readings',
        rows['repeat']!,
        'farm-a',
        parent: 'parcel-a',
      );
      await f.engine.synchronize();
      expect(batches.last.toSet(), {'0', '1', '2', '3', '4', '5', 'repeat'});
      await f.close();
    },
  );
}

/// Historical local v1 schema fixture; production upgrades remain additive.
class _OfflineV1 extends OfflineDatabase {
  _OfflineV1(super.executor, {required super.accountKey});
  @override
  int get schemaVersion => 1;
  @override
  MigrationStrategy get migration => MigrationStrategy(
    onCreate: (_) async {
      for (final statement in [
        'CREATE TABLE entities(account TEXT NOT NULL,kind TEXT NOT NULL,id TEXT NOT NULL,farm TEXT NOT NULL,parent TEXT,data TEXT NOT NULL,revision INTEGER,dirty INTEGER NOT NULL DEFAULT 0,remote TEXT,PRIMARY KEY(account,kind,id))',
        'CREATE TABLE outbox(account TEXT NOT NULL,operation_id TEXT NOT NULL,entity_id TEXT NOT NULL,entity TEXT NOT NULL,operation TEXT NOT NULL,payload_version INTEGER NOT NULL,farm TEXT NOT NULL,payload TEXT NOT NULL,created_at INTEGER NOT NULL,status TEXT NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,next_attempt INTEGER,error_code TEXT,remote TEXT,expected_revision INTEGER,PRIMARY KEY(account,operation_id))',
        'CREATE TABLE cache(account TEXT NOT NULL,key TEXT NOT NULL,data TEXT NOT NULL,checked_at INTEGER NOT NULL,PRIMARY KEY(account,key))',
        'CREATE TABLE checkpoints(account TEXT PRIMARY KEY,cursor TEXT,synced_at INTEGER)',
      ]) {
        await customStatement(statement);
      }
    },
  );
}
