import 'dart:async';
import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:uuid/uuid.dart';

import '../../core/network_health.dart';
import '../api/api_client.dart';
import '../local/offline_database.dart';
import '../local/secure_vault.dart';
import 'sync_engine.dart';

class OfflineRuntime extends ChangeNotifier {
  OfflineRuntime({
    required this.database,
    required this.client,
    required this.vault,
    required this.engine,
    required this.network,
    DateTime Function()? clock,
  }) : clock = clock ?? DateTime.now;
  static OfflineRuntime? shared;
  static const offlineDuration = Duration(hours: 72);
  final OfflineDatabase database;
  final ApiClient client;
  final SecureVault vault;
  final SyncEngine engine;
  final NetworkHealth network;
  final DateTime Function() clock;
  String? account;
  String? role;
  bool localAccess = false;
  int _authorizationGeneration = 0;
  Future<void> _grantUpdates = Future.value();
  Future<void> _changeGrant(Future<void> Function() action) {
    final next = _grantUpdates.then((_) => action());
    _grantUpdates = next.catchError((Object _) {});
    return next;
  }

  DateTime? verifiedUntil;
  DateTime? verifiedFrom;
  final Map<String, Future<Map<String, dynamic>>> _weatherInflight = {};

  String requireAccount() {
    if (account == null ||
        !localAccess ||
        verifiedUntil == null ||
        verifiedFrom == null ||
        clock().isBefore(verifiedFrom!) ||
        !clock().isBefore(verifiedUntil!)) {
      throw ApiAuthException(
        'Necesitas iniciar sesión para preparar los datos de este dispositivo.',
      );
    }
    return account!;
  }

  Future<bool> authorize(String user) async {
    final generation = ++_authorizationGeneration;
    if (account != user) {
      account = user;
      role = null;
      localAccess = false;
      await engine.bind(user);
    }
    if (generation != _authorizationGeneration || account != user) return false;
    final now = clock();
    final stored = await vault.read('grant:$user');
    final grant = stored == null
        ? null
        : jsonDecode(stored) as Map<String, dynamic>;
    final verified = grant == null
        ? null
        : DateTime.parse(grant['verified_at'] as String);
    var authorizationTime = verified;
    final last = await vault.read('access:$user');
    var allowed =
        verified != null &&
        !now.isBefore(verified) &&
        now.difference(verified) < offlineDuration &&
        (last == null ||
            !now.isBefore(
              DateTime.parse(last).subtract(const Duration(minutes: 2)),
            ));
    if (generation != _authorizationGeneration || account != user) return false;
    if (allowed) role = grant!['role'] as String;
    if (network.canAttempt) {
      try {
        final profile = await client.get('/users/me') as Map<String, dynamic>;
        if (generation != _authorizationGeneration ||
            account != user ||
            profile['id'] != user) {
          return false;
        }
        role = profile['role'] as String;
        await _changeGrant(() async {
          if (generation != _authorizationGeneration || account != user) return;
          await vault.write(
            'grant:$user',
            jsonEncode({
              'verified_at': now.toUtc().toIso8601String(),
              'role': role,
            }),
          );
        });
        allowed = true;
        authorizationTime = now;
      } on ApiException catch (e) {
        if (e.statusCode == 401 || e.statusCode == 403) {
          allowed = false;
          await vault.remove('grant:$user');
          engine.sessionPaused = true;
        }
      } on ApiAuthException {
        allowed = false;
      }
    }
    if (generation != _authorizationGeneration || account != user) return false;
    localAccess = allowed;
    verifiedFrom = allowed ? authorizationTime : null;
    verifiedUntil = allowed ? authorizationTime!.add(offlineDuration) : null;
    if (allowed && engine.account != user) await engine.bind(user);
    if (!allowed) await engine.bind(null);
    if (allowed) {
      await vault.write('access:$user', now.toUtc().toIso8601String());
    }
    notifyListeners();
    return allowed;
  }

  Future<void> leave({bool explicit = false}) async {
    _authorizationGeneration++;
    final user = account;
    account = null;
    role = null;
    localAccess = false;
    verifiedUntil = null;
    verifiedFrom = null;
    await engine.bind(null);
    if (explicit && user != null) {
      await _changeGrant(() => vault.remove('grant:$user'));
    }
    if (explicit) await vault.remove('session');
    notifyListeners();
  }

  Future<void> suspendLocal() async {
    _authorizationGeneration++;
    localAccess = false;
    verifiedUntil = null;
    verifiedFrom = null;
    await engine.bind(null);
    notifyListeners();
  }

  Future<Map<String, dynamic>?> cachedWeather(String farmId, int days) async {
    final user = requireAccount();
    final farm = (await database.entities(
      user,
      'farms',
    )).where((row) => row['id'] == farmId).firstOrNull;
    if (farm == null) return null;
    final key = _weatherKey(farm, days);
    final cached = await database.cache(user, key);
    if (account != user || cached == null) return null;
    return _weatherView(cached, farmId);
  }

  String _weatherKey(Map<String, dynamic> farm, int days) {
    double truncate(num value) => (value.toDouble() * 10000).truncate() / 10000;
    return 'weather:v1:${truncate(farm['latitude'] as num)}:${truncate(farm['longitude'] as num)}:$days';
  }

  Future<void> resolve(
    String operationId, {
    bool useRemote = false,
    Map<String, dynamic>? corrected,
  }) async {
    final user = requireAccount();
    final op = (await database.operations(
      user,
    )).where((row) => row['operation_id'] == operationId).first;
    if (op['status'] != 'conflict' && op['status'] != 'failed_permanent') {
      throw StateError('Esta operación aún está en espera.');
    }
    dynamic remote = op['remote'];
    if (remote is Map && remote.containsKey('remote')) {
      remote = remote['remote'];
    }
    if (useRemote) {
      if (remote is! Map ||
          (remote['id'] == null && remote['deleted'] != true)) {
        throw StateError('No hay una versión remota disponible.');
      }
      await database.transaction(() async {
        if (remote['deleted'] == true) {
          await database.customStatement(
            'DELETE FROM entities WHERE account=? AND kind=? AND id=?',
            [user, op['entity'], op['entity_id']],
          );
        } else {
          await database.putEntity(
            user,
            op['entity'] as String,
            Map<String, dynamic>.from(remote),
            op['farm'] as String,
            parent: remote['parcel_id'] as String?,
          );
        }
        // Keep the original encrypted candidate and conflict evidence in history.
        await database.customStatement(
          "UPDATE outbox SET status='synced',error_code='resolved_remote' WHERE account=? AND operation_id=?",
          [user, operationId],
        );
      });
    } else if (op['error_code'] == 'retry_exhausted' && corrected == null) {
      await database.mark(user, operationId, 'pending', attempts: 0);
    } else {
      if (op['entity'] != 'lab_analyses' || corrected == null) {
        throw StateError('Revisa la muestra antes de reenviarla.');
      }
      _validate('lab_analyses', corrected);
      final rows = await database.entities(user, 'lab_analyses');
      final local = rows.where((row) => row['id'] == op['entity_id']).first;
      final expected = remote is Map
          ? remote['revision'] as int?
          : op['expected_revision'] as int?;
      if (op['operation'] == 'update' && expected == null) {
        throw StateError(
          'La muestra fue eliminada o no tiene una revisión disponible. Conserva el registro para revisión.',
        );
      }
      await database.transaction(() async {
        await database.customStatement(
          "UPDATE outbox SET status='synced',error_code='replaced_after_review' WHERE account=? AND operation_id=?",
          [user, operationId],
        );
        await database.enqueue(
          user,
          const Uuid().v4(),
          op['entity_id'] as String,
          'lab_analyses',
          op['operation'] as String,
          op['farm'] as String,
          {'parcel_id': local['parcel_id'], ...corrected},
          {...local, ...corrected, 'revision': expected},
          clock(),
          expectedRevision: expected,
        );
      });
    }
    await engine.reload();
    if (network.operational) unawaited(engine.synchronize());
  }

  Future<List<Map<String, dynamic>>> read(
    String kind, {
    String? farm,
    String? parent,
  }) async {
    final user = requireAccount();
    var data = await database.entities(user, kind, farm: farm, parent: parent);
    if (data.isEmpty &&
        await database.cursor(user) == null &&
        network.canAttempt) {
      await engine.synchronize();
      if (account != user) throw ApiAuthException('La cuenta cambió.');
      data = await database.entities(user, kind, farm: farm, parent: parent);
    }
    if (account != user) throw ApiAuthException('La cuenta cambió.');
    if (data.isEmpty && await database.cursor(user) == null) {
      throw ApiException(
        0,
        'Necesitas conexión inicial para descargar esta información.',
      );
    }
    return data;
  }

  Future<dynamic> cachedGet(String path, {Map<String, String>? query}) async {
    final user = requireAccount();
    final key = '$path:${jsonEncode(query ?? {})}';
    final stored = await database.cache(user, key);
    if (account != user) throw ApiAuthException('La cuenta cambió.');
    if (stored != null) return stored['data'];
    if (!network.operational) {
      throw ApiException(0, 'Esta información necesita una descarga inicial.');
    }
    final data = await client.get(path, query: query);
    if (account != user) throw ApiAuthException('La cuenta cambió.');
    await database.putCache(user, key, data as Object, clock());
    return data;
  }

  Future<Map<String, dynamic>> save(
    String kind,
    String parcelId,
    Map<String, dynamic> payload, {
    String? id,
  }) async {
    final user = requireAccount();
    if (role != 'farmer' && role != 'admin') {
      throw ApiAuthException('Esta cuenta tiene acceso de solo lectura.');
    }
    _validate(kind, payload);
    final parcel = (await database.entities(
      user,
      'parcels',
    )).where((p) => p['id'] == parcelId).firstOrNull;
    if (parcel == null) {
      throw StateError('Descarga la parcela antes de registrar una muestra.');
    }
    Map<String, dynamic>? previous;
    if (id != null) {
      previous = (await database.entities(
        user,
        kind,
      )).where((row) => row['id'] == id).firstOrNull;
      if (previous == null || previous['parcel_id'] != parcelId) {
        throw StateError('La muestra no está disponible en esta parcela.');
      }
      if (previous['_sync_status'] != 'synced') {
        throw StateError(
          'Sincroniza o revisa primero los cambios pendientes de esta muestra.',
        );
      }
    }
    final entityId = id ?? const Uuid().v4();
    final values = {'parcel_id': parcelId, ...payload};
    final local = {
      'id': entityId,
      ...values,
      'recorded_at':
          previous?['recorded_at'] ?? clock().toUtc().toIso8601String(),
      'revision': previous?['revision'],
      '_sync_status': 'pending',
    };
    final operation = const Uuid().v4();
    if (account != user) throw ApiAuthException('La cuenta cambió.');
    await database.enqueue(
      user,
      operation,
      entityId,
      kind,
      id == null ? 'create' : 'update',
      parcel['farm_id'] as String,
      values,
      local,
      clock(),
      expectedRevision: previous?['revision'] as int?,
    );
    await engine.reload();
    if (network.operational) unawaited(engine.synchronize());
    return local;
  }

  void _validate(String kind, Map<String, dynamic> data) {
    void range(String key, double low, double high) {
      final value = data[key];
      if (value is! num || !value.isFinite || value < low || value > high) {
        throw ArgumentError('Valor inválido: $key');
      }
    }

    if (kind == 'readings') {
      for (final key in ['nitrogen', 'phosphorus', 'potassium']) {
        range(key, 0, 1000);
      }
      range('ec', 0, 20);
      range('ph', 2, 10);
      range('temperature', -10, 60);
      range('humidity', 0, 100);
    } else {
      for (final key in [
        'sample_code',
        'lab',
        'ph_method',
        'ec_method',
        'phosphorus_method',
        'potassium_method',
      ]) {
        final text = data[key];
        final min = key == 'sample_code' ? 1 : 2,
            max = key == 'lab' ? 150 : 100;
        if (text is! String || text.trim().length < min || text.length > max) {
          throw ArgumentError('Texto inválido: $key');
        }
      }
      range('ph', 2, 10);
      range('ec', 0, 20);
      range('organic_matter_pct', 0, 100);
      range('cic', 0, 200);
      range('depth_start_cm', 0, 200);
      range('depth_end_cm', 0, 300);
      if ((data['depth_end_cm'] as num) <= (data['depth_start_cm'] as num)) {
        throw ArgumentError('Revisa la profundidad.');
      }
      var total = 0.0;
      for (final key in ['clay_pct', 'silt_pct', 'sand_pct']) {
        range(key, 0, 100);
        total += (data[key] as num).toDouble();
      }
      if (total < 99.5 || total > 100.5) {
        throw ArgumentError('La textura debe sumar 100%.');
      }
      for (final key in [
        'nitrogen',
        'phosphorus',
        'potassium',
        'calcium',
        'magnesium',
        'sulfur',
      ]) {
        range(key, 0, double.maxFinite);
      }
      if (DateTime.parse(data['sampled_at'] as String).isAfter(clock())) {
        throw ArgumentError('La fecha no puede estar en el futuro.');
      }
    }
  }

  Future<Map<String, dynamic>> weather(
    String farmId,
    int days, {
    bool manual = false,
  }) async {
    final user = requireAccount();
    final farm = (await database.entities(
      user,
      'farms',
    )).where((f) => f['id'] == farmId).firstOrNull;
    if (farm == null) {
      throw StateError('Descarga la finca antes de consultar su clima.');
    }
    final key = _weatherKey(farm, days);
    final cached = await database.cache(user, key);
    if (account != user) throw ApiAuthException('La cuenta cambió.');
    final attempted = await database.cache(user, '$key:attempt');
    if (!manual &&
        cached == null &&
        attempted != null &&
        clock().difference(attempted['checked_at'] as DateTime) <
            const Duration(minutes: 15)) {
      throw ApiException(
        0,
        'El pronóstico no está disponible. Espera antes de volver a consultar.',
      );
    }
    if (cached != null &&
        (!manual &&
                clock().difference(cached['checked_at'] as DateTime) <
                    const Duration(minutes: 15) ||
            !network.operational)) {
      return _weatherView(cached, farmId);
    }
    if (!network.operational) {
      if (cached != null) return _weatherView(cached, farmId);
      throw ApiException(
        0,
        'Necesitas conexión inicial para descargar el pronóstico.',
      );
    }
    final flightKey = '$user:$key';
    final inflight = _weatherInflight[flightKey];
    if (inflight != null) return {...await inflight, 'farm_id': farmId};
    final future = () async {
      try {
        await database.putCache(user, '$key:attempt', {
          'attempted': true,
        }, clock());
        final data =
            await client.get(
                  '/weather/farms/$farmId/forecast',
                  query: {'days': '$days'},
                )
                as Map<String, dynamic>;
        if (account != user) throw ApiAuthException('La cuenta cambió.');
        // Store only public normalized weather; identity is attached on read.
        final neutral = Map<String, dynamic>.from(data)
          ..remove('farm_id')
          ..remove('farm_name');
        await database.putCache(user, key, neutral, clock());
        return _weatherView({'data': neutral, 'checked_at': clock()}, farmId);
      } catch (_) {
        if (cached != null && account == user) {
          // Retain good data and the validation attempt time to limit failed retries.
          await database.putCache(user, key, cached['data'] as Object, clock());
          return _weatherView(cached, farmId, failed: true);
        }
        rethrow;
      } finally {
        _weatherInflight.remove(flightKey);
      }
    }();
    _weatherInflight[flightKey] = future;
    return future;
  }

  Map<String, dynamic> _weatherView(
    Map<String, dynamic> entry,
    String farm, {
    bool failed = false,
  }) {
    final data = Map<String, dynamic>.from(entry['data'] as Map);
    final updated =
        DateTime.tryParse(data['updated_at'] as String? ?? '') ??
        entry['checked_at'] as DateTime;
    final age = clock().difference(updated);
    return {
      ...data,
      'farm_id': farm,
      'updated_at': updated.toUtc().toIso8601String(),
      'freshness': age >= const Duration(hours: 6)
          ? 'historical'
          : failed ||
                age >= const Duration(minutes: 30) ||
                data['freshness'] == 'stale'
          ? 'stale'
          : 'fresh',
      'offline': !network.operational,
    };
  }
}
