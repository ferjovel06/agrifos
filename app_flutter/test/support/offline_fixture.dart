import 'dart:convert';
import 'package:cryptography/cryptography.dart';
import 'package:drift/native.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:app_flutter/core/network_health.dart';
import 'package:app_flutter/data/api/api_client.dart';
import 'package:app_flutter/data/local/offline_database.dart';
import 'package:app_flutter/data/local/secure_vault.dart';
import 'package:app_flutter/data/sync/offline_runtime.dart';
import 'package:app_flutter/data/sync/sync_engine.dart';

class MemoryVault extends SecureVault {
  MemoryVault() : super('fixture');
  final Map<String, String> values = {};
  @override
  Future<String?> read(String key) async => values[key];
  @override
  Future<void> write(String key, String value) async {
    values[key] = value;
  }

  @override
  Future<void> remove(String key) async {
    values.remove(key);
  }
}

class OfflineFixture {
  OfflineFixture() {
    database = OfflineDatabase(
      NativeDatabase.memory(),
      accountKey: (_) async => SecretKey(List.filled(32, 7)),
    );
    client = ApiClient(
      baseUrl: 'https://fixture.invalid',
      network: network,
      tokenProvider: () => token,
      userProvider: () => user,
      httpClient: MockClient((request) async {
        calls.add(request.url.path);
        if (handler != null) return await handler!(request);
        if (request.url.path == '/users/me') {
          return json({'id': user, 'role': 'farmer'});
        }
        if (request.url.path == '/sync/changes') {
          return json({
            'changes': [],
            'cursor': 'checkpoint',
            'has_more': false,
          });
        }
        return json(weatherData(request.url.path.split('/')[3], clock));
      }),
    );
    engine = SyncEngine(
      database: database,
      client: client,
      identity: () => user,
      network: network,
      clock: () => clock,
      refreshSession: () async {
        refreshes++;
        return refreshAllowed;
      },
    );
    runtime = OfflineRuntime(
      database: database,
      client: client,
      vault: vault,
      engine: engine,
      network: network,
      clock: () => clock,
    );
  }
  String? user = 'farmer-a';
  String token = 'fixture-bearer';
  DateTime clock = DateTime.utc(2026, 10, 8, 12);
  int refreshes = 0;
  bool refreshAllowed = false;
  final network = NetworkHealth();
  final vault = MemoryVault();
  final calls = <String>[];
  Future<http.Response> Function(http.Request)? handler;
  late final OfflineDatabase database;
  late final ApiClient client;
  late final SyncEngine engine;
  late final OfflineRuntime runtime;
  static http.Response json(
    Object data, {
    int status = 200,
    Map<String, String>? headers,
  }) => http.Response(
    jsonEncode(data),
    status,
    headers: {'content-type': 'application/json', ...?headers},
  );
  Future<void> prepare() async {
    network.hint(true);
    await runtime.authorize(user!);
    await database.putEntity(user!, 'farms', {
      'id': 'farm-a',
      'user_id': user,
      'name': 'Coffee farm',
      'area_hectares': 1,
      'latitude': 12.112345,
      'longitude': -86.223456,
    }, 'farm-a');
    await database.putEntity(user!, 'parcels', {
      'id': 'parcel-a',
      'farm_id': 'farm-a',
      'crop_id': 'coffee',
      'variety_id': null,
      'name': 'Coffee parcel',
      'area_hectares': 1,
      'plants_per_hectare': 3000,
      'planting_date': '2025-01-01',
    }, 'farm-a');
    await database.applyPage(user!, {
      'changes': [],
      'cursor': 'checkpoint',
      'has_more': false,
    }, clock);
    calls.clear();
  }

  Future<void> queue({
    String id = 'op',
    String entity = 'reading',
    String kind = 'readings',
  }) => database.enqueue(
    user!,
    id,
    entity,
    kind,
    'create',
    'farm-a',
    {'parcel_id': 'parcel-a', 'nitrogen': 25},
    {'id': entity, 'parcel_id': 'parcel-a', 'nitrogen': 25},
    clock,
  );
  Future<void> close() async {
    engine.dispose();
    await database.close();
  }
}

Map<String, dynamic> weatherData(String farm, DateTime now) => {
  'farm_id': farm,
  'provider': 'Open-Meteo',
  'updated_at': now.toIso8601String(),
  'freshness': 'fresh',
  'current': {
    'observed_at': now.toIso8601String(),
    'temperature_c': 25,
    'relative_humidity_pct': 60,
    'precipitation_mm': 1,
    'weather_code': 61,
    'condition': 'Lluvia',
    'wind_speed_kmh': 10,
  },
  'daily': List.generate(
    7,
    (i) => {
      'date': now.add(Duration(days: i)).toIso8601String(),
      'temperature_max_c': 28,
      'precipitation_mm': 1,
    },
  ),
};
