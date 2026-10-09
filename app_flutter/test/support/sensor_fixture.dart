import 'dart:async';
import 'dart:typed_data';
import 'package:app_flutter/data/sensor/sensor_protocol.dart';
import 'package:app_flutter/data/sensor/usb_sensor_service.dart';
import 'package:flutter_serial_communication/models/device_info.dart';

/// Entirely synthetic protocol. This is never a production sensor profile.
SensorProfile syntheticProfile({
  bool verified = true,
  int retries = 1,
  List<SensorVariable>? variables,
}) => SensorProfile(
  id: 'synthetic-test-only',
  sensorModel: 'Deterministic test fixture',
  documentReference:
      'Synthetic unit-test specification; no hardware compatibility',
  physicalDeviceId: 'synthetic-unit-test-only',
  identityEvidence: 'Deterministic fixture identity, no physical probe',
  verified: verified,
  vendorId: 1234,
  productId: 5678,
  baudRate: 9600,
  dataBits: 8,
  stopBits: 1,
  parity: 0,
  slaveId: 1,
  function: 3,
  startRegister: 20,
  registerCount: variables == null ? 3 : 1,
  variables:
      variables ??
      const [
        SensorVariable(
          key: 'nitrogen',
          registerOffset: 0,
          unit: 'mg/kg',
          analyte: 'N',
          scale: 1,
          range: [0, 100],
        ),
        SensorVariable(
          key: 'ec',
          registerOffset: 1,
          unit: 'uS/cm',
          analyte: 'ec',
          scale: 1,
        ),
        SensorVariable(
          key: 'temperature',
          registerOffset: 2,
          unit: 'degC',
          analyte: 'temperature',
          scale: 0.1,
          signed: true,
        ),
      ],
  responseTimeout: const Duration(milliseconds: 100),
  pollInterval: const Duration(milliseconds: 200),
  maxRetries: retries,
);

List<int> syntheticFrame([int nitrogen = 25]) =>
    withModbusCrc([1, 3, 6, nitrogen >> 8, nitrogen & 255, 3, 232, 255, 246]);

class FakeSerialTransport extends SerialTransport {
  final stream = StreamController<dynamic>.broadcast();
  final device = DeviceInfo(deviceId: 9, vendorId: 1234, productId: 5678);
  int opens = 0, writes = 0, closes = 0;
  bool permission = true, attached = true, sent = true;
  Completer<bool>? openGate;
  @override
  Future<List<DeviceInfo>> devices() async => attached ? [device] : [];
  @override
  Future<bool> open(DeviceInfo device, SensorProfile profile) async {
    opens++;
    return openGate == null ? permission : await openGate!.future;
  }

  @override
  Stream<dynamic> get bytes => stream.stream;
  @override
  Future<bool> write(Uint8List bytes) async {
    writes++;
    return sent;
  }

  @override
  Future<void> close() async {
    closes++;
  }
}

class ManualSensorClock {
  Duration now = Duration.zero;
  final jobs = <ManualTimer>[];
  Timer schedule(Duration duration, void Function() callback) {
    final timer = ManualTimer(now + duration, callback);
    jobs.add(timer);
    return timer;
  }

  void elapse(Duration duration) {
    final target = now + duration;
    while (true) {
      final pending =
          jobs.where((job) => job.isActive && job.due <= target).toList()
            ..sort((a, b) => a.due.compareTo(b.due));
      if (pending.isEmpty) break;
      final next = pending.first;
      now = next.due;
      next.cancel();
      next.callback();
    }
    now = target;
  }
}

class ManualTimer implements Timer {
  ManualTimer(this.due, this.callback);
  final Duration due;
  final void Function() callback;
  @override
  bool isActive = true;
  @override
  int get tick => isActive ? 0 : 1;
  @override
  void cancel() => isActive = false;
}
