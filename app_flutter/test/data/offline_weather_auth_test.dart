import 'dart:async';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:app_flutter/data/api/api_client.dart';
import 'package:app_flutter/data/api/fertilization_repository.dart';
import 'package:app_flutter/data/sync/offline_runtime.dart';
import '../support/offline_fixture.dart';

void main() {
  late OfflineFixture f;
  setUp(() async {
    f = OfflineFixture();
    await f.prepare();
  });
  tearDown(() async {
    OfflineRuntime.shared = null;
    await f.close();
  });
  test('a pending laboratory sample cannot trigger a remote agronomic calculation', () async {
    await f.queue(entity:'sample', kind:'lab_analyses');
    OfflineRuntime.shared = f.runtime;
    final repository = FertilizationRepository(client:f.client);
    await expectLater(repository.createFromLabAnalysis(parcelId:'parcel-a',labAnalysisId:'sample',
      yieldUnit:'qq_gold_ha',fruitStage:'green'), throwsA(isA<ApiException>()));
    expect(f.calls, isEmpty);
    expect((await f.database.operations('farmer-a')).single['status'], 'pending');
  });
  test(
    'an old authorization response cannot restore a grant after explicit logout',
    () async {
      final response = Completer<http.Response>();
      final sent = Completer<void>();
      f.handler = (_) {
        sent.complete();
        return response.future;
      };
      final authorization = f.runtime.authorize('farmer-a');
      await sent.future;
      await f.runtime.leave(explicit: true);
      response.complete(
        OfflineFixture.json({'id': 'farmer-a', 'role': 'farmer'}),
      );
      expect(await authorization, isFalse);
      expect(await f.vault.read('grant:farmer-a'), isNull);
      expect(f.runtime.localAccess, isFalse);
    },
  );
  test(
    'failed first weather download is throttled without inventing a forecast',
    () async {
      f.handler = (_) async =>
          OfflineFixture.json({'detail': 'Unavailable'}, status: 503);
      await expectLater(f.runtime.weather('farm-a', 7), throwsA(anything));
      final calls = f.calls.length;
      for (var i = 0; i < 10; i++) {
        await expectLater(f.runtime.weather('farm-a', 7), throwsA(anything));
      }
      expect(f.calls.length, calls);
      f.clock = f.clock.add(const Duration(minutes: 15));
      await expectLater(f.runtime.weather('farm-a', 7), throwsA(anything));
      expect(f.calls.length, calls + 1);
    },
  );
  test('clock rollback during an unlocked session fails closed', () async {
    f.clock = f.clock.subtract(const Duration(hours: 1));
    await expectLater(f.runtime.read('farms'), throwsA(anything));
  });
  test(
    'G: ten repeated and concurrent openings share one backend call per location',
    () async {
      final values = await Future.wait(
        List.generate(10, (_) => f.runtime.weather('farm-a', 7)),
      );
      expect(values.every((value) => value['farm_id'] == 'farm-a'), isTrue);
      expect(f.calls.where((path) => path.startsWith('/weather')).length, 1);
      for (var i = 0; i < 10; i++) {
        await f.runtime.weather('farm-a', 7);
      }
      expect(f.calls.where((path) => path.startsWith('/weather')).length, 1);
      f.clock = f.clock.add(const Duration(minutes: 15));
      await f.runtime.weather('farm-a', 7);
      expect(f.calls.where((path) => path.startsWith('/weather')).length, 2);
    },
  );
  test(
    'H: backend failure retains cached forecast, waits, and eventually labels history',
    () async {
      final first = await f.runtime.weather('farm-a', 7);
      f.clock = f.clock.add(const Duration(minutes: 16));
      f.handler = (_) async =>
          throw http.ClientException('Provider/backend unavailable');
      final stale = await f.runtime.weather('farm-a', 7);
      expect(stale['current'], first['current']);
      expect(stale['freshness'], 'stale');
      final count = f.calls.length;
      for (var i = 0; i < 10; i++) {
        await f.runtime.weather('farm-a', 7);
      }
      expect(f.calls.length, count);
      f.clock = f.clock.add(const Duration(hours: 6));
      expect((await f.runtime.weather('farm-a', 7))['freshness'], 'historical');
    },
  );
  test(
    'offline weather makes zero HTTP calls and does not mix distinct coordinates',
    () async {
      await f.runtime.weather('farm-a', 7);
      await f.database.putEntity('farmer-a', 'farms', {
        'id': 'farm-b',
        'latitude': 14.1,
        'longitude': -90.2,
      }, 'farm-b');
      f.network.hint(false);
      f.calls.clear();
      expect((await f.runtime.weather('farm-a', 7))['offline'], isTrue);
      await expectLater(f.runtime.weather('farm-b', 7), throwsA(anything));
      expect(f.calls, isEmpty);
    },
  );
  test(
    'equivalent coordinates reuse public forecast without mixing farm identities',
    () async {
      await f.database.putEntity('farmer-a', 'farms', {
        'id': 'farm-b',
        'latitude': 12.112349,
        'longitude': -86.223459,
      }, 'farm-b');
      await f.runtime.weather('farm-a', 7);
      final other = await f.runtime.weather('farm-b', 7);
      expect(other['farm_id'], 'farm-b');
      expect(f.calls.length, 1);
    },
  );
  test(
    'offline access expires after 72 hours and network failures cannot extend it',
    () async {
      f.network.hint(false);
      f.clock = f.clock.add(const Duration(hours: 71));
      expect(await f.runtime.authorize('farmer-a'), isTrue);
      f.clock = f.clock.add(const Duration(hours: 2));
      expect(await f.runtime.authorize('farmer-a'), isFalse);
      await expectLater(f.runtime.read('farms'), throwsA(anything));
    },
  );
  test(
    'first login offline is refused and explicit logout preserves queued data',
    () async {
      await f.queue();
      await f.runtime.leave(explicit: true);
      f.network.hint(false);
      expect(await f.runtime.authorize('farmer-a'), isFalse);
      expect(
        (await f.database.operations('farmer-a')).single['operation_id'],
        'op',
      );
      f.user = 'farmer-b';
      expect(await f.runtime.authorize('farmer-b'), isFalse);
      expect(await f.database.entities('farmer-b', 'farms'), isEmpty);
    },
  );
  test(
    'clock rollback does not extend a previously granted offline window',
    () async {
      f.network.hint(false);
      f.clock = f.clock.subtract(const Duration(hours: 1));
      expect(await f.runtime.authorize('farmer-a'), isFalse);
    },
  );
}
