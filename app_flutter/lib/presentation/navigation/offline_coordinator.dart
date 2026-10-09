import 'dart:async';
import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../data/sync/offline_runtime.dart';
import '../auth/auth_provider.dart';
import '../farm/farm_provider.dart';
import '../farm/parcel_provider.dart';
import '../home/latest_reading_provider.dart';
import '../home/weather_provider.dart';
import '../sensor/sensor_provider.dart';

class OfflineCoordinator extends StatefulWidget {
  const OfflineCoordinator({super.key, required this.child});
  final Widget child;
  @override
  State<OfflineCoordinator> createState() => _OfflineCoordinatorState();
}

class _OfflineCoordinatorState extends State<OfflineCoordinator>
    with WidgetsBindingObserver {
  StreamSubscription<List<ConnectivityResult>>? _connection;
  AuthProvider? _auth;
  int _revision = -1;
  String? _user;
  bool _disposed = false;
  OfflineRuntime get runtime => OfflineRuntime.shared!;
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    runtime.engine.addListener(_syncChanged);
    _connection = Connectivity().onConnectivityChanged.listen((signals) {
      final available = !signals.contains(ConnectivityResult.none);
      runtime.network.hint(available);
      if (available && runtime.localAccess) {
        unawaited(runtime.engine.synchronize());
      }
    });
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final auth = context.read<AuthProvider>();
    if (_auth == auth) return;
    _auth?.removeListener(_authChanged);
    _auth = auth;
    auth.addListener(_authChanged);
  }

  void _authChanged() {
    final user = _auth?.user?.id;
    if (user == _user) return;
    _user = user;
    // Clear provider state at an identity boundary, including kept-alive tabs.
    unawaited(context.read<FarmProvider>().loadFarms(userId: null));
    unawaited(context.read<ParcelProvider>().loadForFarm(null));
    context.read<LatestReadingProvider>().clear();
    context.read<WeatherProvider>().clear();
    unawaited(context.read<SensorProvider>().disconnect());
    if (user == null) unawaited(runtime.leave());
  }

  void _syncChanged() {
    if (_disposed ||
        _revision == runtime.engine.revision ||
        !runtime.localAccess) {
      return;
    }
    _revision = runtime.engine.revision;
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      if (!mounted || !runtime.localAccess) return;
      final user = runtime.account;
      final farms = context.read<FarmProvider>();
      final parcels = context.read<ParcelProvider>();
      final readings = context.read<LatestReadingProvider>();
      await farms.loadFarms(force: true, userId: user);
      if (!mounted || runtime.account != user) return;
      await parcels.loadForFarm(farms.selectedFarmId, force: true);
      if (!mounted || runtime.account != user) return;
      if (parcels.selectedParcelId case final id?) {
        await readings.fetchLatest(id);
      }
    });
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state != AppLifecycleState.resumed) runtime.engine.setForeground(false);
    if (state == AppLifecycleState.resumed) {
      unawaited(_resume());
    }
  }

  Future<void> _resume() async {
    final signals = await Connectivity().checkConnectivity();
    runtime.network.hint(!signals.contains(ConnectivityResult.none));
    await _auth?.verifyLocalAccess();
    if (mounted && runtime.localAccess) runtime.engine.setForeground(true);
  }

  @override
  Widget build(BuildContext context) => widget.child;
  @override
  void dispose() {
    _disposed = true;
    _connection?.cancel();
    _auth?.removeListener(_authChanged);
    runtime.engine.removeListener(_syncChanged);
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }
}
