import 'dart:io';
import 'package:cryptography/cryptography.dart';
import 'package:app_flutter/data/local/offline_database.dart';

Future<void> main(List<String> args) async {
  final db = OfflineDatabase.file(
    args.single,
    accountKey: (_) async => SecretKey(List.filled(32, 7)),
  );
  await db.enqueue(
    'farmer-a',
    'stable-op',
    'stable-entity',
    'readings',
    'create',
    'farm-a',
    {'parcel_id': 'parcel-a', 'nitrogen': 25},
    {'id': 'stable-entity', 'parcel_id': 'parcel-a', 'nitrogen': 25},
    DateTime.utc(2026),
  );
  // Terminate the process without closing SQLite or its background isolate.
  exit(70);
}
