import 'dart:async';
import 'dart:math';
import 'package:flutter/foundation.dart';

import '../../core/network_health.dart';
import '../api/api_client.dart';
import '../local/offline_database.dart';

class SyncEngine extends ChangeNotifier {
  SyncEngine({
    required this.database,
    required this.client,
    required this.identity,
    required this.refreshSession,
    required this.network,
    DateTime Function()? clock,
    Random? random,
  }) : clock = clock ?? DateTime.now,
       random = random ?? Random();
  final OfflineDatabase database;
  final ApiClient client;
  final String? Function() identity;
  final Future<bool> Function() refreshSession;
  final NetworkHealth network;
  final DateTime Function() clock;
  final Random random;
  String? account;
  bool syncing = false;
  bool sessionPaused = false;
  String? error;
  DateTime? syncedAt;
  List<Map<String, dynamic>> pending = [];
  Future<void>? _running;
  Timer? _retry;
  bool foreground = true;
  int revision = 0;
  String? _runningAccount;

  Future<void> bind(String? next) async {
    _retry?.cancel();
    account = next;
    pending = [];
    syncedAt = null;
    sessionPaused = false;
    error = null;
    revision++;
    notifyListeners();
    if (next != null) {
      await database.recover(next);
      await reload();
    }
  }

  bool _same(String user) => account == user && identity() == user;
  Future<void> reload() async {
    final user = account;
    if (user == null) return;
    final ops = await database.operations(user);
    final last = await database.lastSync(user);
    if (!_same(user)) return;
    pending = ops.where((op) => op['status'] != 'synced').toList();
    syncedAt = last;
    revision++;
    notifyListeners();
  }

  Future<void> synchronize() {
    if (_running != null) {
      return _runningAccount == account
          ? _running!
          : _running!.then((_) => synchronize());
    }
    _runningAccount = account;
    _running = _run().whenComplete(() {
      _running = null;
      _runningAccount = null;
    });
    return _running!;
  }

  Future<void> _run() async {
    final user = account;
    if (user == null || !_same(user) || !network.canAttempt || !foreground) {
      return;
    }
    _retry?.cancel();
    syncing = true;
    error = null;
    sessionPaused = false;
    notifyListeners();
    try {
      // This authenticated request confirms the backend is operational. No
      // timer treats a Wi-Fi hint as a successful connection.
      await _authenticatedGet('/users/me', user);
      if (!_same(user)) return;
      final due = await database.operations(user, dueOnly: true, now: clock());
      for (final op in due) {
        if (!_same(user) || !foreground) return;
        await _deliver(user, op);
        if (sessionPaused || !network.operational) break;
      }
      if (sessionPaused || !_same(user) || !network.operational) return;
      String? cursor = await database.cursor(user);
      var resetSnapshot = false;
      while (_same(user) && foreground) {
        Map<String, dynamic> page;
        try {
          page =
              await _authenticatedGet(
                    '/sync/changes',
                    user,
                    query: {'cursor': ?cursor, 'limit': '100'},
                  )
                  as Map<String, dynamic>;
        } on ApiException catch (e) {
          if (e.statusCode != 410 || resetSnapshot || !_same(user)) rethrow;
          resetSnapshot = true;
          cursor = null;
          // Reset only the expired cursor. Local entities and outbox survive.
          await database.customStatement(
            'UPDATE checkpoints SET cursor=NULL WHERE account=?',
            [user],
          );
          continue;
        }
        if (!_same(user)) return;
        await database.applyPage(user, page, clock());
        cursor = page['cursor'] as String;
        if (page['has_more'] != true) break;
      }
    } on ApiAuthException {
      sessionPaused = true;
      error = 'Inicia sesión para sincronizar. Los cambios siguen guardados.';
    } on ApiException catch (e) {
      if (e.statusCode == 401) {
        sessionPaused = true;
        error = 'Inicia sesión para sincronizar. Los cambios siguen guardados.';
      } else {
        error = 'No se pudo sincronizar. Los datos siguen en este dispositivo.';
      }
    } catch (_) {
      error = 'No se pudo sincronizar. Revisa los cambios pendientes.';
    } finally {
      syncing = false;
      await reload();
      _schedule();
      notifyListeners();
    }
  }

  Future<dynamic> _authenticatedGet(
    String path,
    String user, {
    Map<String, String>? query,
  }) async {
    try {
      return await client.get(path, query: query);
    } on ApiException catch (e) {
      if (e.statusCode != 401 || !await refreshSession() || !_same(user)) {
        rethrow;
      }
      return client.get(path, query: query);
    }
  }

  Future<void> _deliver(String user, Map<String, dynamic> op) async {
    final id = op['operation_id'] as String;
    final attempts = (op['attempts'] as int) + 1;
    await database.mark(user, id, 'in_progress', attempts: attempts);
    try {
      final body = {
        'operation_id': id,
        'entity_id': op['entity_id'],
        'farm_id': op['farm'],
        'entity': op['entity'],
        'operation': op['operation'],
        'payload_version': op['payload_version'],
        'expected_revision': op['expected_revision'],
        'payload': op['payload'],
      };
      Map<String, dynamic> response;
      try {
        response = await client.postForUser('/sync/operations', body, user);
      } on ApiException catch (e) {
        if (e.statusCode != 401 || !await refreshSession() || !_same(user)) {
          rethrow;
        }
        response = await client.postForUser('/sync/operations', body, user);
      }
      if (!_same(user)) {
        return; // Restart recovery replays this same operation ID.
      }
      await database.acknowledge(
        user,
        op,
        response['data'] as Map<String, dynamic>,
      );
    } on ApiAuthException {
      await database.mark(user, id, 'pending', error: 'session_required');
      sessionPaused = true;
    } on ApiException catch (e) {
      if (e.statusCode == 401) {
        await database.mark(user, id, 'pending', error: 'session_required');
        sessionPaused = true;
      } else if (e.statusCode == 409) {
        await database.mark(
          user,
          id,
          'conflict',
          error: 'conflict',
          remote: e.detail,
        );
      } else if (e.statusCode == 403 ||
          e.statusCode == 404 ||
          e.statusCode == 422 ||
          (e.statusCode >= 400 &&
              e.statusCode < 500 &&
              e.statusCode != 429 &&
              e.statusCode != 408)) {
        await database.mark(
          user,
          id,
          'failed_permanent',
          error: 'http_${e.statusCode}',
          remote: e.detail,
        );
      } else {
        final delay = Duration(
          seconds:
              min(3600, 15 * pow(2, min(attempts - 1, 8)).toInt()) +
              random.nextInt(15),
        );
        var next = clock().add(delay);
        final seconds = int.tryParse(e.retryAfter ?? '');
        DateTime? deadline = seconds == null
            ? _httpDate(e.retryAfter)
            : clock().add(Duration(seconds: max(0, seconds)));
        if (deadline != null && deadline.isAfter(next)) next = deadline;
        await database.mark(
          user,
          id,
          attempts >= 8 ? 'failed_permanent' : 'retry_wait',
          next: next,
          error: attempts >= 8 ? 'retry_exhausted' : 'http_${e.statusCode}',
        );
      }
      error =
          'No se pudo sincronizar. Hay cambios pendientes o que requieren revisión.';
    }
  }

  DateTime? _httpDate(String? value) {
    if (value == null) return null;
    // IMF-fixdate is handled without a new dependency.
    final match = RegExp(
      r'^\w{3}, (\d{2}) (\w{3}) (\d{4}) (\d{2}):(\d{2}):(\d{2}) GMT$',
    ).firstMatch(value);
    if (match == null) return null;
    const months = [
      'Jan',
      'Feb',
      'Mar',
      'Apr',
      'May',
      'Jun',
      'Jul',
      'Aug',
      'Sep',
      'Oct',
      'Nov',
      'Dec',
    ];
    final month = months.indexOf(match[2]!) + 1;
    return month == 0
        ? null
        : DateTime.utc(
            int.parse(match[3]!),
            month,
            int.parse(match[1]!),
            int.parse(match[4]!),
            int.parse(match[5]!),
            int.parse(match[6]!),
          );
  }

  void setForeground(bool value) {
    foreground = value;
    if (!value) {
      _retry?.cancel();
    } else {
      unawaited(synchronize());
    }
  }

  void _schedule() {
    if (!foreground || sessionPaused || !network.operational) return;
    final dates =
        pending
            .where(
              (op) =>
                  op['status'] == 'retry_wait' && op['next_attempt'] != null,
            )
            .map(
              (op) => DateTime.fromMillisecondsSinceEpoch(
                op['next_attempt'] as int,
              ),
            )
            .toList()
          ..sort();
    if (dates.isEmpty) return;
    final wait = dates.first.difference(clock());
    _retry = Timer(
      wait.isNegative ? const Duration(seconds: 1) : wait,
      () => unawaited(synchronize()),
    );
  }

  @override
  void dispose() {
    _retry?.cancel();
    super.dispose();
  }
}
