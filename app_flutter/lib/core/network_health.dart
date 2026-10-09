import 'package:flutter/foundation.dart';

enum BackendReachability { unknown, offline, unreachable, operational }

class NetworkHealth extends ChangeNotifier {
  static final shared = NetworkHealth();
  bool? networkAvailable;
  BackendReachability state = BackendReachability.unknown;
  void hint(bool available) {
    networkAvailable = available;
    state = available
        ? BackendReachability.unknown
        : BackendReachability.offline;
    notifyListeners();
  }

  void success() {
    if (state == BackendReachability.operational) return;
    state = BackendReachability.operational;
    notifyListeners();
  }

  void failure() {
    state = networkAvailable == false
        ? BackendReachability.offline
        : BackendReachability.unreachable;
    notifyListeners();
  }

  bool get canAttempt => state != BackendReachability.offline;
  bool get operational => state == BackendReachability.operational;
}
