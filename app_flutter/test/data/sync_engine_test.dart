import 'dart:async';
import 'dart:convert';
import 'package:http/http.dart' as http;
import 'package:flutter_test/flutter_test.dart';
import '../support/offline_fixture.dart';

void main() {
  late OfflineFixture f;
  setUp(() async {
    f = OfflineFixture();
    await f.prepare();
  });
  tearDown(() async {
    await f.close();
  });
  for (final malformed in ['invalid-json', '{"data":{"id":"another-record","revision":1}}']) {
    test('malformed acknowledgement is retryable and cannot replace the local entity: $malformed', () async {
      await f.queue();
      f.handler = (request) async {
        if (request.url.path == '/users/me') return OfflineFixture.json({'id':f.user,'role':'farmer'});
        if (request.url.path == '/sync/changes') return OfflineFixture.json({'changes':[],'cursor':'next','has_more':false});
        return http.Response(malformed,200);
      };
      await f.engine.synchronize();
      expect((await f.database.operations(f.user!)).single['status'], 'retry_wait');
      expect((await f.database.entities(f.user!,'readings')).single['id'], 'reading');
    });
  }
  test(
    'expired cursor prepares a new snapshot without losing queued mutations',
    () async {
      await f.queue();
      await f.database.mark(
        f.user!,
        'op',
        'retry_wait',
        next: f.clock.add(const Duration(hours: 1)),
      );
      var pages = 0;
      f.handler = (request) async {
        if (request.url.path == '/users/me') {
          return OfflineFixture.json({'id': f.user, 'role': 'farmer'});
        }
        pages++;
        if (pages == 1) {
          return OfflineFixture.json({'detail': 'Expired'}, status: 410);
        }
        expect(request.url.queryParameters.containsKey('cursor'), isFalse);
        return OfflineFixture.json({
          'changes': [],
          'cursor': 'new',
          'has_more': false,
        });
      };
      await f.engine.synchronize();
      expect(pages, 2);
      expect(await f.database.cursor(f.user!), 'new');
      expect(
        (await f.database.operations(f.user!)).single['operation_id'],
        'op',
      );
    },
  );
  test(
    'HTTP date Retry-After and attempt cap preserve a manually recoverable operation',
    () async {
      await f.queue();
      await f.database.mark(f.user!, 'op', 'pending', attempts: 7);
      f.handler = (request) async {
        if (request.url.path == '/users/me') {
          return OfflineFixture.json({'id': f.user, 'role': 'farmer'});
        }
        if (request.url.path == '/sync/changes') {
          return OfflineFixture.json({
            'changes': [],
            'cursor': 'new',
            'has_more': false,
          });
        }
        return OfflineFixture.json(
          {'detail': 'Busy'},
          status: 429,
          headers: {'retry-after': 'Thu, 08 Oct 2026 14:00:00 GMT'},
        );
      };
      await f.engine.synchronize();
      var op = (await f.database.operations(f.user!)).single;
      expect(
        op['next_attempt'],
        DateTime.utc(2026, 10, 8, 14).millisecondsSinceEpoch,
      );
      expect(op['status'], 'failed_permanent');
      expect(op['error_code'], 'retry_exhausted');
      f.network.hint(false);
      await f.runtime.resolve('op');
      op = (await f.database.operations(f.user!)).single;
      expect(op['operation_id'], 'op');
      expect(op['status'], 'pending');
      expect(op['attempts'], 0);
    },
  );

  test(
    'C/D: lost response replays stable operation, acknowledges once, deduplicates concurrent runs',
    () async {
      await f.queue();
      var posts = 0;
      final committed = <String>{};
      f.handler = (request) async {
        if (request.url.path == '/users/me') {
          return OfflineFixture.json({'id': f.user, 'role': 'farmer'});
        }
        if (request.url.path == '/sync/changes') {
          return OfflineFixture.json({
            'changes': [],
            'cursor': 'next',
            'has_more': false,
          });
        }
        final body = jsonDecode(request.body) as Map<String, dynamic>;
        committed.add(body['operation_id'] as String);
        posts++;
        if (posts == 1) {
          throw http.ClientException('Response lost after commit');
        }
        return OfflineFixture.json({
          'data': {
            'id': 'reading',
            'parcel_id': 'parcel-a',
            'nitrogen': 25,
            'revision': 1,
          },
        });
      };
      await Future.wait([f.engine.synchronize(), f.engine.synchronize()]);
      var op = (await f.database.operations(f.user!)).single;
      expect(op['status'], 'retry_wait');
      expect(posts, 1);
      f.clock = f.clock.add(const Duration(hours: 1));
      f.network.hint(true);
      await f.engine.synchronize();
      op = (await f.database.operations(f.user!)).single;
      expect(op['status'], 'synced');
      expect(committed, {'op'});
      expect(posts, 2);
    },
  );
  for (final code in [403, 409, 422, 429, 503]) {
    test('HTTP $code is classified and payload remains recoverable', () async {
      await f.queue();
      f.handler = (request) async {
        if (request.url.path == '/users/me') {
          return OfflineFixture.json({'id': f.user, 'role': 'farmer'});
        }
        if (request.url.path == '/sync/changes') {
          return OfflineFixture.json({
            'changes': [],
            'cursor': 'next',
            'has_more': false,
          });
        }
        return OfflineFixture.json(
          {
            'detail': {
              'remote': {'id': 'reading', 'nitrogen': 77, 'revision': 2},
            },
          },
          status: code,
          headers: {'retry-after': '3600'},
        );
      };
      await f.engine.synchronize();
      final op = (await f.database.operations(f.user!)).single;
      expect(
        op['status'],
        code == 409
            ? 'conflict'
            : code == 403 || code == 422
            ? 'failed_permanent'
            : 'retry_wait',
      );
      expect((op['payload'] as Map)['nitrogen'], 25);
      if (code == 429) {
        expect(
          op['next_attempt'],
          f.clock.add(const Duration(hours: 1)).millisecondsSinceEpoch,
        );
      }
    });
  }
  test('401 renews once then pauses without dropping operations', () async {
    await f.queue();
    f.handler = (request) async => request.url.path == '/users/me'
        ? OfflineFixture.json({'id': f.user, 'role': 'farmer'})
        : OfflineFixture.json({'detail': 'Expired'}, status: 401);
    await f.engine.synchronize();
    expect(f.refreshes, 1);
    expect(f.engine.sessionPaused, isTrue);
    expect((await f.database.operations(f.user!)).single['status'], 'pending');
  });
  test(
    'F: identity changes during delivery never apply response to another account',
    () async {
      await f.queue();
      final reply = Completer<http.Response>();
      final sent = Completer<void>();
      f.handler = (request) async {
        if (request.url.path == '/users/me') {
          return OfflineFixture.json({'id': f.user, 'role': 'farmer'});
        }
        sent.complete();
        return reply.future;
      };
      final run = f.engine.synchronize();
      await sent.future;
      f.user = 'farmer-b';
      await f.engine.bind('farmer-b');
      reply.complete(
        OfflineFixture.json({
          'data': {'id': 'reading', 'nitrogen': 25, 'revision': 1},
        }),
      );
      await run;
      expect(await f.database.entities('farmer-b', 'readings'), isEmpty);
      expect(
        (await f.database.operations('farmer-a')).single['status'],
        'in_progress',
      );
      await f.database.recover('farmer-a');
      expect(
        (await f.database.operations('farmer-a')).single['status'],
        'pending',
      );
    },
  );
  test(
    'a network hint does not establish operational backend access',
    () async {
      f.network.hint(true);
      expect(f.network.operational, isFalse);
      f.handler = (_) async =>
          throw http.ClientException('Backend unreachable');
      await f.engine.synchronize();
      expect(f.network.state.name, 'unreachable');
      f.network.hint(false);
      f.calls.clear();
      await f.engine.synchronize();
      expect(f.calls, isEmpty);
    },
  );
}
