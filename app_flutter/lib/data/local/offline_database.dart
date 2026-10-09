import 'dart:convert';

import 'package:cryptography/cryptography.dart';
import 'package:drift/drift.dart';
import 'offline_executor.dart';

typedef AccountKey = Future<SecretKey> Function(String account);

/// SQL-first Drift keeps the existing domain models and avoids generated copies
/// of encrypted payloads. All access goes through this account-scoped store.
class OfflineDatabase extends GeneratedDatabase {
  OfflineDatabase(super.executor, {required this.accountKey});
  factory OfflineDatabase.file(String path, {required AccountKey accountKey}) =>
      OfflineDatabase(openOfflineFile(path), accountKey: accountKey);

  final AccountKey accountKey;
  final _cipher = AesGcm.with256bits();
  final Map<String, Future<SecretKey>> _cacheKeys = {};
  Future<String> _cacheKey(String account, String logical) async {
    // Coordinates and query parameters must not remain in plaintext metadata.
    final key = await _cacheKeys.putIfAbsent(
      account,
      () async => Hkdf(hmac: Hmac.sha256(), outputLength: 32).deriveKey(
        secretKey: await accountKey(account),
        nonce: utf8.encode('agrifos-cache-lookup-v1'),
        info: const [],
      ),
    );
    final mac = await Hmac.sha256().calculateMac(
      utf8.encode(logical),
      secretKey: key,
    );
    return mac.bytes
        .map((byte) => byte.toRadixString(16).padLeft(2, '0'))
        .join();
  }

  @override
  int get schemaVersion => 2;
  @override
  Iterable<TableInfo<Table, dynamic>> get allTables => const [];
  @override
  List<DatabaseSchemaEntity> get allSchemaEntities => const [];
  @override
  MigrationStrategy get migration => MigrationStrategy(
    onCreate: (_) async {
      for (final sql in _schema) {
        await customStatement(sql);
      }
    },
    onUpgrade: (_, from, to) async {
      if (from != 1 || to != 2) {
        throw StateError('Unsupported offline migration $from → $to');
      }
      await transaction(() async {
        await customStatement(
          'ALTER TABLE entities ADD COLUMN processing_pending INTEGER NOT NULL DEFAULT 0',
        );
        await customStatement(
          'ALTER TABLE entities ADD COLUMN processing_group TEXT',
        );
        await _processingIndexes();
        // One-time migration of inferred metadata; ciphertext and AAD stay intact.
        for (final row in await rows(
          "SELECT * FROM entities WHERE kind='readings'",
          [],
        )) {
          final account = row['account'] as String;
          final data = await _decodeEntity(account, 'readings', row);
          final metadata = await _processingMetadata(
            account,
            'readings',
            data,
            row['dirty'] == 1,
          );
          await customStatement(
            'UPDATE entities SET processing_pending=?,processing_group=? WHERE account=? AND kind=? AND id=?',
            [metadata.$1, metadata.$2, account, 'readings', row['id']],
          );
        }
      });
    },
    beforeOpen: (_) async {
      await customStatement('PRAGMA journal_mode = WAL');
      await customStatement('PRAGMA synchronous = FULL');
    },
  );

  static const _schema = [
    '''CREATE TABLE entities (
      account TEXT NOT NULL, kind TEXT NOT NULL, id TEXT NOT NULL,
      farm TEXT NOT NULL, parent TEXT, data TEXT NOT NULL,
      revision INTEGER, dirty INTEGER NOT NULL DEFAULT 0, remote TEXT,
      processing_pending INTEGER NOT NULL DEFAULT 0, processing_group TEXT,
      PRIMARY KEY(account,kind,id))''',
    'CREATE INDEX entities_scope ON entities(account,kind,farm,parent)',
    'CREATE INDEX entities_processing_pending ON entities(account,kind,processing_pending,id)',
    'CREATE INDEX entities_processing_group ON entities(account,kind,processing_group,dirty,id)',
    '''CREATE TABLE outbox (
      account TEXT NOT NULL, operation_id TEXT NOT NULL, entity_id TEXT NOT NULL,
      entity TEXT NOT NULL, operation TEXT NOT NULL, payload_version INTEGER NOT NULL,
      farm TEXT NOT NULL, payload TEXT NOT NULL, created_at INTEGER NOT NULL,
      status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
      next_attempt INTEGER, error_code TEXT, remote TEXT, expected_revision INTEGER,
      PRIMARY KEY(account,operation_id))''',
    'CREATE INDEX outbox_due ON outbox(account,status,next_attempt,created_at)',
    '''CREATE TABLE cache (
      account TEXT NOT NULL, key TEXT NOT NULL, data TEXT NOT NULL,
      checked_at INTEGER NOT NULL, PRIMARY KEY(account,key))''',
    '''CREATE TABLE checkpoints (
      account TEXT PRIMARY KEY, cursor TEXT, synced_at INTEGER)''',
  ];

  Future<void> _processingIndexes() async {
    await customStatement(_schema[2]);
    await customStatement(_schema[3]);
  }

  Future<(int, String?)> _processingMetadata(
    String account,
    String kind,
    Map<String, dynamic> data,
    bool dirty,
  ) async {
    final measurement = data['measurement'];
    if (kind != 'readings' || measurement is! Map) return (0, null);
    final group = await _cacheKey(
      account,
      // Partition only by acquisition session within the account. The backend
      // must see every parcel, device, decoder and point boundary in that route.
      'sensor-group:v1:${jsonEncode(measurement['session_id'])}',
    );
    final results = data['derived_results'];
    return (
      !dirty && (results == null || results is List && results.isEmpty) ? 1 : 0,
      group,
    );
  }

  Future<List<Map<String, dynamic>>> pendingProcessing(String account) async {
    final pending = await rows(
      "SELECT * FROM entities WHERE account=? AND kind='readings' AND processing_pending=1 GROUP BY processing_group ORDER BY MIN(id) LIMIT 201",
      [account],
    );
    return Future.wait(
      pending.map(
        (row) async => {
          ...await _decodeEntity(account, 'readings', row),
          '_processing_group': row['processing_group'],
        },
      ),
    );
  }

  Future<List<Map<String, dynamic>>> processingGroup(
    String account,
    String group,
  ) async {
    final members = await rows(
      "SELECT * FROM entities WHERE account=? AND kind='readings' AND processing_group=? AND dirty=0 ORDER BY id LIMIT 201",
      [account, group],
    );
    return Future.wait(
      members.map((row) => _decodeEntity(account, 'readings', row)),
    );
  }

  Future<List<Map<String, dynamic>>> rows(
    String sql,
    List<Object?> args,
  ) async => (await customSelect(
    sql,
    variables: args.map(_variable).toList(),
  ).get()).map((row) => row.data).toList();
  Variable _variable(Object? value) => switch (value) {
    int v => Variable<int>(v),
    String v => Variable<String>(v),
    _ => Variable<String>(null),
  };

  Future<String> encrypt(String account, String scope, Object data) async {
    final box = await _cipher.encrypt(
      utf8.encode(jsonEncode(data)),
      secretKey: await accountKey(account),
      aad: utf8.encode('$account:$scope'),
    );
    return jsonEncode({
      'n': base64Encode(box.nonce),
      'c': base64Encode(box.cipherText),
      'm': base64Encode(box.mac.bytes),
    });
  }

  Future<dynamic> decrypt(String account, String scope, String data) async {
    final map = jsonDecode(data) as Map<String, dynamic>;
    final clear = await _cipher.decrypt(
      SecretBox(
        base64Decode(map['c'] as String),
        nonce: base64Decode(map['n'] as String),
        mac: Mac(base64Decode(map['m'] as String)),
      ),
      secretKey: await accountKey(account),
      aad: utf8.encode('$account:$scope'),
    );
    return jsonDecode(utf8.decode(clear));
  }

  Future<List<Map<String, dynamic>>> entities(
    String account,
    String kind, {
    String? farm,
    String? parent,
  }) async {
    final result = await rows(
      'SELECT * FROM entities WHERE account=? AND kind=?'
      '${farm == null ? '' : ' AND farm=?'}${parent == null ? '' : ' AND parent=?'} ORDER BY id',
      [account, kind, ?farm, ?parent],
    );
    return Future.wait(result.map((row) => _decodeEntity(account, kind, row)));
  }

  Future<Map<String, dynamic>?> entity(
    String account,
    String kind,
    String id,
  ) async {
    final result = await rows(
      'SELECT * FROM entities WHERE account=? AND kind=? AND id=?',
      [account, kind, id],
    );
    return result.isEmpty ? null : _decodeEntity(account, kind, result.single);
  }

  Future<Map<String, dynamic>> _decodeEntity(
    String account,
    String kind,
    Map<String, dynamic> row,
  ) async => {
    ...await decrypt(account, '$kind:${row['id']}', row['data'] as String)
        as Map<String, dynamic>,
    '_sync_status': row['dirty'] == 1 ? 'pending' : 'synced',
    'revision': row['revision'],
  };

  Future<void> putEntity(
    String account,
    String kind,
    Map<String, dynamic> data,
    String farm, {
    bool dirty = false,
    String? parent,
  }) async {
    final id = data['id'] as String;
    final encrypted = await encrypt(account, '$kind:$id', data);
    final processing = await _processingMetadata(account, kind, data, dirty);
    await customStatement(
      '''INSERT INTO entities(account,kind,id,farm,parent,data,revision,dirty,processing_pending,processing_group)
      VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(account,kind,id) DO UPDATE SET
      farm=excluded.farm,parent=excluded.parent,data=excluded.data,
      revision=excluded.revision,dirty=excluded.dirty,remote=NULL,
      processing_pending=excluded.processing_pending,processing_group=excluded.processing_group''',
      [
        account,
        kind,
        id,
        farm,
        parent,
        encrypted,
        data['revision'],
        dirty ? 1 : 0,
        processing.$1,
        processing.$2,
      ],
    );
  }

  Future<void> enqueue(
    String account,
    String operationId,
    String entityId,
    String entity,
    String operation,
    String farm,
    Map<String, dynamic> payload,
    Map<String, dynamic> local,
    DateTime now, {
    int? expectedRevision,
  }) async {
    final sealed = await encrypt(account, 'operation:$operationId', payload);
    await transaction(() async {
      final pending = await rows(
        "SELECT operation_id FROM outbox WHERE account=? AND entity_id=? AND status != 'synced'",
        [account, entityId],
      );
      if (pending.isNotEmpty) {
        throw StateError(
          'Esta muestra ya tiene cambios pendientes. Sincronízalos o revísalos primero.',
        );
      }
      await putEntity(
        account,
        entity,
        local,
        farm,
        dirty: true,
        parent: payload['parcel_id'] as String,
      );
      await customStatement(
        '''INSERT INTO outbox(account,operation_id,entity_id,entity,
        operation,payload_version,farm,payload,created_at,status,expected_revision)
        VALUES(?,?,?,?,?,1,?,?,?,'pending',?)''',
        [
          account,
          operationId,
          entityId,
          entity,
          operation,
          farm,
          sealed,
          now.millisecondsSinceEpoch,
          expectedRevision,
        ],
      );
    });
  }

  Future<List<Map<String, dynamic>>> operations(
    String account, {
    bool dueOnly = false,
    bool activeOnly = false,
    DateTime? now,
  }) async {
    final records = await rows(
      'SELECT * FROM outbox WHERE account=?'
      '${dueOnly ? " AND status IN ('pending','retry_wait') AND (next_attempt IS NULL OR next_attempt<=?)" : ''}'
      '${activeOnly ? " AND status != 'synced'" : ''}'
      ' ORDER BY created_at,operation_id',
      [account, if (dueOnly) now!.millisecondsSinceEpoch],
    );
    return Future.wait(records.map((row) => _decodeOperation(account, row)));
  }

  Future<Map<String, dynamic>?> operation(String account, String id) async {
    final result = await rows(
      'SELECT * FROM outbox WHERE account=? AND operation_id=?',
      [account, id],
    );
    return result.isEmpty ? null : _decodeOperation(account, result.single);
  }

  Future<Map<String, dynamic>> _decodeOperation(
    String account,
    Map<String, dynamic> row,
  ) async => {
    ...row,
    'payload': await decrypt(
      account,
      'operation:${row['operation_id']}',
      row['payload'] as String,
    ),
    if (row['remote'] != null)
      'remote': await decrypt(
        account,
        'remote:${row['operation_id']}',
        row['remote'] as String,
      ),
  };

  Future<void> recover(String account) => customStatement(
    "UPDATE outbox SET status='pending' WHERE account=? AND status='in_progress'",
    [account],
  );
  Future<void> mark(
    String account,
    String id,
    String status, {
    int? attempts,
    DateTime? next,
    String? error,
    Object? remote,
  }) async {
    await customStatement(
      '''UPDATE outbox SET status=?,attempts=COALESCE(?,attempts),
      next_attempt=?,error_code=?,remote=? WHERE account=? AND operation_id=?''',
      [
        status,
        attempts,
        next?.millisecondsSinceEpoch,
        error,
        remote == null ? null : await encrypt(account, 'remote:$id', remote),
        account,
        id,
      ],
    );
  }

  Future<void> acknowledge(
    String account,
    Map<String, dynamic> op,
    Map<String, dynamic> data,
  ) async {
    await transaction(() async {
      await putEntity(
        account,
        op['entity'] as String,
        data,
        op['farm'] as String,
        parent: data['parcel_id'] as String?,
      );
      await mark(account, op['operation_id'] as String, 'synced');
    });
  }

  Future<String?> cursor(String account) async =>
      (await rows('SELECT cursor FROM checkpoints WHERE account=?', [
            account,
          ])).firstOrNull?['cursor']
          as String?;
  Future<DateTime?> lastSync(String account) async {
    final time =
        (await rows('SELECT synced_at FROM checkpoints WHERE account=?', [
              account,
            ])).firstOrNull?['synced_at']
            as int?;
    return time == null ? null : DateTime.fromMillisecondsSinceEpoch(time);
  }

  Future<void> applyPage(
    String account,
    Map<String, dynamic> page,
    DateTime now,
  ) async {
    await transaction(() async {
      for (final change
          in (page['changes'] as List).cast<Map<String, dynamic>>()) {
        final kind = change['entity'] as String,
            id = change['entity_id'] as String;
        final pending = await rows(
          "SELECT operation_id,operation,status,expected_revision FROM outbox WHERE account=? AND entity=? AND entity_id=? AND status!='synced'",
          [account, kind, id],
        );
        final remote = change['operation'] == 'delete'
            ? {'deleted': true}
            : change['data'] as Map<String, dynamic>;
        if (pending.isNotEmpty) {
          // Preserve the locally edited candidate and the complete remote version.
          for (final op in pending) {
            // A committed create with a lost acknowledgement must still replay
            // its receipt; downloading it cannot turn a retry into a conflict.
            if (change['operation'] != 'delete' &&
                op['operation'] == 'create' &&
                [
                  'pending',
                  'in_progress',
                  'retry_wait',
                ].contains(op['status'])) {
              continue;
            }
            if (change['operation'] != 'delete' &&
                op['expected_revision'] != null &&
                remote['revision'] is int &&
                (remote['revision'] as int) <=
                    (op['expected_revision'] as int)) {
              continue;
            }
            await mark(
              account,
              op['operation_id'] as String,
              'conflict',
              error: 'remote_changed',
              remote: remote,
            );
          }
          continue;
        }
        if (change['operation'] == 'delete') {
          if (kind == 'farms' || kind == 'parcels') {
            final predicate = kind == 'farms' ? 'farm=?' : 'parent=?';
            await customStatement(
              'DELETE FROM entities WHERE account=? AND $predicate AND dirty=0',
              [account, id],
            );
            if (kind == 'farms') {
              await customStatement(
                "UPDATE outbox SET status='failed_permanent',error_code='scope_revoked' WHERE account=? AND farm=? AND status!='synced'",
                [account, id],
              );
            }
          }
          await customStatement(
            'DELETE FROM entities WHERE account=? AND kind=? AND id=?',
            [account, kind, id],
          );
        } else {
          await putEntity(
            account,
            kind,
            remote,
            change['farm_id'] as String,
            parent: remote['parcel_id'] as String?,
          );
        }
      }
      await customStatement(
        '''INSERT INTO checkpoints(account,cursor,synced_at) VALUES(?,?,?)
        ON CONFLICT(account) DO UPDATE SET cursor=excluded.cursor,synced_at=excluded.synced_at''',
        [
          account,
          page['cursor'],
          page['has_more'] == true ? null : now.millisecondsSinceEpoch,
        ],
      );
    });
  }

  Future<Map<String, dynamic>?> cache(String account, String key) async {
    final row = (await rows('SELECT * FROM cache WHERE account=? AND key=?', [
      account,
      await _cacheKey(account, key),
    ])).firstOrNull;
    if (row == null) return null;
    return {
      'data': await decrypt(account, 'cache:$key', row['data'] as String),
      'checked_at': DateTime.fromMillisecondsSinceEpoch(
        row['checked_at'] as int,
      ),
    };
  }

  Future<void> putCache(
    String account,
    String key,
    Object data,
    DateTime now,
  ) async => customStatement(
    '''INSERT INTO cache(account,key,data,checked_at) VALUES(?,?,?,?)
      ON CONFLICT(account,key) DO UPDATE SET data=excluded.data,checked_at=excluded.checked_at''',
    [
      account,
      await _cacheKey(account, key),
      await encrypt(account, 'cache:$key', data),
      now.millisecondsSinceEpoch,
    ],
  );

  Future<void> invalidateCache(String account, String key) async =>
      customStatement('DELETE FROM cache WHERE account=? AND key=?', [
        account,
        await _cacheKey(account, key),
      ]);
}
