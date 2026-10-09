import 'dart:io';
import 'dart:convert';
import 'package:cryptography/cryptography.dart';
import 'package:drift/native.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:app_flutter/data/local/offline_database.dart';

Future<SecretKey> key(String user) async =>
    SecretKey(List.filled(32, user == 'farmer-a' ? 7 : 8));
void main() {
  test(
    'private coordinates are hidden in cache keys as well as encrypted payloads',
    () async {
      final db = OfflineDatabase(NativeDatabase.memory(), accountKey: key);
      const logical = 'weather:v1:12.1123:-86.2234:7';
      await db.putCache('farmer-a', logical, {
        'temperature': 25,
      }, DateTime.utc(2026));
      final stored = (await db.rows('SELECT key,data FROM cache', [])).single;
      expect(stored['key'], matches(RegExp(r'^[a-f0-9]{64}$')));
      expect(jsonEncode(stored).contains('12.1123'), isFalse);
      expect((await db.cache('farmer-a', logical))!['data'], {
        'temperature': 25,
      });
      expect(await db.cache('farmer-b', logical), isNull);
      await db.invalidateCache('farmer-a', logical);
      expect(await db.cache('farmer-a', logical), isNull);
      await db.close();
    },
  );
  test(
    'downloaded committed create keeps its stable retry after a lost acknowledgement',
    () async {
      final db = OfflineDatabase(NativeDatabase.memory(), accountKey: key);
      await db.enqueue(
        'farmer-a',
        'op',
        'sample',
        'readings',
        'create',
        'farm',
        {'parcel_id': 'parcel', 'nitrogen': 25},
        {'id': 'sample', 'nitrogen': 25},
        DateTime.utc(2026),
      );
      await db.mark('farmer-a', 'op', 'retry_wait', attempts: 1);
      await db.applyPage('farmer-a', {
        'changes': [
          {
            'entity': 'readings',
            'entity_id': 'sample',
            'farm_id': 'farm',
            'operation': 'upsert',
            'data': {'id': 'sample', 'nitrogen': 25, 'revision': 1},
          },
        ],
        'cursor': 'next',
        'has_more': false,
      }, DateTime.utc(2026));
      expect((await db.operations('farmer-a')).single['status'], 'retry_wait');
      expect(
        (await db.entities('farmer-a', 'readings')).single['nitrogen'],
        25,
      );
      await db.close();
    },
  );
  late Directory temp;
  setUp(() async {
    temp = await Directory.systemTemp.createTemp('agrifos-offline-test-');
  });
  tearDown(() async {
    await temp.delete(recursive: true);
  });

  test(
    'A: downloaded farms and parcels survive close and reopen, isolated by user',
    () async {
      final file = File('${temp.path}/offline.sqlite');
      var db = OfflineDatabase.file(file.path, accountKey: key);
      await db.putEntity('farmer-a', 'farms', {
        'id': 'farm-a',
        'name': 'Private coffee farm',
        'latitude': 12.1,
      }, 'farm-a');
      await db.putEntity('farmer-a', 'parcels', {
        'id': 'parcel-a',
        'name': 'Coffee plot',
        'farm_id': 'farm-a',
      }, 'farm-a');
      await db.close();
      db = OfflineDatabase.file(file.path, accountKey: key);
      expect(
        (await db.entities('farmer-a', 'farms')).single['name'],
        'Private coffee farm',
      );
      expect(
        (await db.entities('farmer-a', 'parcels', farm: 'farm-a')).single['id'],
        'parcel-a',
      );
      expect(await db.entities('farmer-b', 'farms'), isEmpty);
      await db.close();
      expect(
        String.fromCharCodes(await file.readAsBytes()),
        isNot(contains('Private coffee farm')),
      );
    },
  );
  test(
    'B: forced process exit preserves committed operation and local mutation',
    () async {
      final file = File('${temp.path}/offline.sqlite');
      final child = await Process.run('dart', [
        'run',
        'test/support/offline_crash_writer.dart',
        file.path,
      ]);
      expect(child.exitCode, 70, reason: '${child.stdout}\n${child.stderr}');
      final db = OfflineDatabase.file(file.path, accountKey: key);
      expect(
        (await db.entities('farmer-a', 'readings')).single['nitrogen'],
        25,
      );
      final op = (await db.operations('farmer-a')).single;
      expect(op['operation_id'], 'stable-op');
      expect(op['status'], 'pending');
      await db.mark('farmer-a', 'stable-op', 'in_progress', attempts: 1);
      await db.close();
      final reopened = OfflineDatabase.file(file.path, accountKey: key);
      await reopened.recover('farmer-a');
      expect(
        (await reopened.operations('farmer-a')).single['status'],
        'pending',
      );
      await reopened.close();
    },
    timeout: const Timeout(Duration(minutes: 2)),
  );
  test('local mutation and outbox rollback together if enqueue fails', () async {
    final db = OfflineDatabase(NativeDatabase.memory(), accountKey: key);
    await db.customStatement(
      "CREATE TRIGGER refuse_outbox BEFORE INSERT ON outbox BEGIN SELECT RAISE(ABORT,'fixture failure'); END",
    );
    await expectLater(
      db.enqueue(
        'farmer-a',
        'op',
        'entity',
        'readings',
        'create',
        'farm',
        {'parcel_id': 'parcel'},
        {'id': 'entity'},
        DateTime.utc(2026),
      ),
      throwsA(anything),
    );
    expect(await db.entities('farmer-a', 'readings'), isEmpty);
    expect(await db.operations('farmer-a'), isEmpty);
    await db.close();
  });
  test(
    'E: remote changes preserve local payload and both conflict versions',
    () async {
      final db = OfflineDatabase(NativeDatabase.memory(), accountKey: key);
      await db.enqueue(
        'farmer-a',
        'op',
        'sample',
        'lab_analyses',
        'update',
        'farm',
        {'parcel_id': 'parcel', 'nitrogen': 55},
        {'id': 'sample', 'nitrogen': 55},
        DateTime.utc(2026),
        expectedRevision: 1,
      );
      await db.applyPage('farmer-a', {
        'changes': [
          {
            'entity': 'lab_analyses',
            'entity_id': 'sample',
            'farm_id': 'farm',
            'operation': 'upsert',
            'data': {'id': 'sample', 'nitrogen': 77, 'revision': 2},
          },
        ],
        'cursor': 'next',
        'has_more': false,
      }, DateTime.utc(2026));
      final op = (await db.operations('farmer-a')).single;
      expect(op['status'], 'conflict');
      expect((op['payload'] as Map)['nitrogen'], 55);
      expect((op['remote'] as Map)['nitrogen'], 77);
      expect(
        (await db.entities('farmer-a', 'lab_analyses')).single['nitrogen'],
        55,
      );
      await db.close();
    },
  );
  test(
    'F: account-scoped AAD refuses ciphertext swapped between users',
    () async {
      final db = OfflineDatabase(NativeDatabase.memory(), accountKey: key);
      final data = await db.encrypt('farmer-a', 'sample', {'private': 'soil'});
      await expectLater(
        db.decrypt('farmer-b', 'sample', data),
        throwsA(anything),
      );
      await db.close();
    },
  );
}
