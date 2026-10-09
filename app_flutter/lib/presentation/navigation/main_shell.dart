import 'package:flutter/material.dart';
import 'dart:async';
import 'package:provider/provider.dart';
import '../../data/sync/offline_runtime.dart';
import '../home/weather_provider.dart';
import '../farm/farm_provider.dart';
import 'sync_status_bar.dart';

import '../auth/auth_provider.dart';
import '../home/home_screen.dart';
import '../sensor/sensor_screen.dart';
import '../planification/planification_screen.dart';
import '../finance/finance_screen.dart';
import '../profile/profile_screen.dart';
import 'widgets/app_header.dart';
import 'widgets/app_bottom_nav.dart';

/// Root shell shown after authentication.
///
/// Owns the bottom navigation and keeps every section alive via
/// [IndexedStack] so switching tabs preserves each screen's state
/// (scroll position, form input, etc.)
class MainShell extends StatefulWidget {
  const MainShell({super.key});

  @override
  State<MainShell> createState() => _MainShellState();
}

class _MainShellState extends State<MainShell> {
  int _currentIndex = 0;
  Timer? _weatherTimer;
  String? _weatherFarm;
  @override
  void initState() {
    super.initState();
    OfflineRuntime.shared?.network.addListener(_networkChanged);
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final farm = context.watch<FarmProvider>().selectedFarmId;
    if (farm != _weatherFarm) {
      _weatherFarm = farm;
      _activateWeather();
    }
  }

  void _networkChanged() {
    if (OfflineRuntime.shared?.network.operational == true) _activateWeather();
  }

  void _activateWeather() {
    _weatherTimer?.cancel();
    if (OfflineRuntime.shared?.engine.foreground == false ||
        (_currentIndex != 0 && _currentIndex != 2) ||
        _weatherFarm == null) {
      return;
    }
    final farm = _weatherFarm;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted &&
          OfflineRuntime.shared?.engine.foreground != false &&
          farm != null &&
          farm == _weatherFarm &&
          (_currentIndex == 0 || _currentIndex == 2)) {
        unawaited(context.read<WeatherProvider>().fetchForecast(farm));
      }
    });
    _weatherTimer = Timer(const Duration(minutes: 15), _activateWeather);
  }

  void _select(int index) {
    setState(() => _currentIndex = index);
    _activateWeather();
  }

  @override
  void dispose() {
    _weatherTimer?.cancel();
    OfflineRuntime.shared?.network.removeListener(_networkChanged);
    super.dispose();
  }

  static const _items = [
    AppNavItem(
      icon: Icons.grid_view_outlined,
      activeIcon: Icons.grid_view_rounded,
      label: 'Panel',
    ),
    AppNavItem(
      icon: Icons.monitor_heart_outlined,
      activeIcon: Icons.monitor_heart,
      label: 'Diagnóstico',
    ),
    AppNavItem(
      icon: Icons.calendar_month_outlined,
      activeIcon: Icons.calendar_month,
      label: 'Planificación',
    ),
    AppNavItem(
      icon: Icons.show_chart,
      activeIcon: Icons.show_chart,
      label: 'Finanzas',
    ),
    AppNavItem(
      icon: Icons.people_outline,
      activeIcon: Icons.people,
      label: 'Perfil',
    ),
  ];

  // Kept in the same order as `_items` so index i maps to screen i.
  List<Widget> get _screens => [
    HomeScreen(),
    SensorScreen(),
    PlanificationScreen(active: _currentIndex == 2),
    FinanceScreen(),
    ProfileScreen(),
  ];

  static const _headerTitles = [
    'Panel General',
    'Diagnóstico Agronómico',
    'Planificación Climática',
    'Finanzas',
    'Configuración y Equipo',
  ];

  static const _headerSubtitles = [
    'Resumen operativo',
    'Análisis de suelo',
    'Calendario y alertas',
    'Ingresos y gastos',
    'Administración de cuenta',
  ];

  @override
  Widget build(BuildContext context) {
    final user = context.watch<AuthProvider>().user;

    return Scaffold(
      backgroundColor: Colors.white,
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(20, 10, 20, 0),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              AppHeader(
                title: _headerTitles[_currentIndex],
                subtitle: _headerSubtitles[_currentIndex],
                accentColor: _currentIndex == 1
                    ? const Color(0xFF4D8DFF)
                    : _currentIndex == 2
                    ? const Color(0xFF8B5CF6)
                    : _currentIndex == 3
                    ? const Color(0xFFF59E0B)
                    : _currentIndex == 4
                    ? const Color(0xFF5A2D22)
                    : const Color(0xFF31543B),
                userName: user?.name ?? user?.email,
                onNotificationsTap: () {},
                onProfileTap: () => _select(4),
              ),
              const SizedBox(height: 10),
              if (OfflineRuntime.shared != null) const SyncStatusBar(),
              Expanded(
                child: IndexedStack(index: _currentIndex, children: _screens),
              ),
            ],
          ),
        ),
      ),
      bottomNavigationBar: AppBottomNav(
        currentIndex: _currentIndex,
        items: _items,
        onTap: _select,
      ),
    );
  }
}
