import 'dart:async';
import 'package:app_flutter/data/api/readings_repository.dart';
import 'package:app_flutter/data/sensor/usb_sensor_service.dart';
import 'package:app_flutter/domain/entities/reading.dart';
import 'package:app_flutter/presentation/sensor/sensor_provider.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_serial_communication/models/device_info.dart';
import '../support/sensor_fixture.dart';

Future<void> flush() => Future<void>.delayed(Duration.zero);
void main() {
  test(
    'dispose during USB permission wait closes the late port before another connection',
    () async {
      final transport = FakeSerialTransport()..openGate = Completer<bool>();
      final service = UsbSensorService(transport: transport);
      final opening = service.connect(
        profile: syntheticProfile(),
        device: transport.device,
      );
      await flush();
      expect(transport.opens, 1);
      final closing = service.dispose();
      transport.openGate!.complete(true);
      expect(await opening, isFalse);
      await closing;
      expect(transport.closes, greaterThanOrEqualTo(3));
      transport.openGate = null;
      expect(
        await service.connect(
          profile: syntheticProfile(),
          device: transport.device,
        ),
        isTrue,
      );
      await service.dispose();
      await transport.stream.close();
    },
  );
  test('port closes promptly with a paused reading subscriber', () async {
    final transport = FakeSerialTransport();
    final service = UsbSensorService(transport: transport);
    await service.connect(
      profile: syntheticProfile(),
      device: transport.device,
    );
    final sub = service.readings().listen((_) {}, onError: (Object _) {});
    sub.pause();
    await service.dispose().timeout(const Duration(seconds: 1));
    await sub.cancel();
    await transport.stream.close();
  });
  test(
    'one request accepts one frame even if two responses arrive together',
    () async {
      final transport = FakeSerialTransport();
      final timer = ManualSensorClock();
      final service = UsbSensorService(
        transport: transport,
        schedule: timer.schedule,
      );
      await service.connect(
        profile: syntheticProfile(),
        device: transport.device,
      );
      final readings = <SensorReading>[];
      final sub = service.readings().listen(
        readings.add,
        onError: (Object _) {},
      );
      transport.stream.add([...syntheticFrame(), ...syntheticFrame()]);
      await flush();
      expect(readings.length, 1);
      await sub.cancel();
      await service.dispose();
      await transport.stream.close();
    },
  );
  test(
    'no query without verified profile and explicit matching VID/PID',
    () async {
      final transport = FakeSerialTransport();
      final service = UsbSensorService(transport: transport);
      await expectLater(service.connect(), throwsStateError);
      await expectLater(
        service.connect(
          profile: syntheticProfile(verified: false),
          device: transport.device,
        ),
        throwsStateError,
      );
      await expectLater(
        service.connect(
          profile: syntheticProfile(),
          device: DeviceInfo(vendorId: 1, productId: 2),
        ),
        throwsA(isA<SensorAcquisitionException>()),
      );
      expect(transport.opens, 0);
      expect(transport.writes, 0);
      await transport.stream.close();
    },
  );
  test(
    'denied permission and unplug-before-open have no measurement',
    () async {
      final transport = FakeSerialTransport();
      final service = UsbSensorService(transport: transport);
      transport.permission = false;
      await expectLater(
        service.connect(profile: syntheticProfile(), device: transport.device),
        throwsA(isA<SensorAcquisitionException>()),
      );
      transport.attached = false;
      await expectLater(
        service.connect(profile: syntheticProfile(), device: transport.device),
        throwsA(isA<SensorDisconnectedException>()),
      );
      expect(transport.writes, 0);
      await service.dispose();
      await transport.stream.close();
    },
  );
  test(
    'bounded response retries and stale capture are cleared on disconnect',
    () async {
      final transport = FakeSerialTransport();
      final timer = ManualSensorClock();
      final provider = SensorProvider(
        service: UsbSensorService(
          transport: transport,
          schedule: timer.schedule,
        ),
      );
      await provider.selectDevice(syntheticProfile(), transport.device);
      await provider.connectAndListen();
      await flush();
      transport.stream.add(syntheticFrame());
      await flush();
      expect(provider.lastReading!.nitrogen, 25);
      final firstSession = provider.lastReading!.measurement!.sessionId;
      await provider.disconnect();
      expect(provider.lastReading, isNull);
      await provider.connectAndListen();
      await flush();
      transport.stream.add(syntheticFrame(30));
      await flush();
      expect(provider.lastReading!.measurement!.sessionId, isNot(firstSession));
      timer.elapse(const Duration(milliseconds: 200));
      await flush();
      timer.elapse(const Duration(milliseconds: 100));
      await flush();
      expect(provider.lastReading, isNull);
      timer.elapse(const Duration(milliseconds: 200));
      await flush();
      timer.elapse(const Duration(milliseconds: 100));
      await flush();
      expect(provider.status, SensorStatus.error);
      final writes = transport.writes;
      timer.elapse(const Duration(seconds: 2));
      await flush();
      expect(transport.writes, writes);
      provider.dispose();
      await flush();
      await transport.stream.close();
    },
  );
  test(
    'CRC failure invalidates displayed sample without artificial values',
    () async {
      final transport = FakeSerialTransport();
      final timer = ManualSensorClock();
      final provider = SensorProvider(
        service: UsbSensorService(
          transport: transport,
          schedule: timer.schedule,
        ),
      );
      await provider.selectDevice(syntheticProfile(), transport.device);
      await provider.connectAndListen();
      await flush();
      transport.stream.add(syntheticFrame());
      await flush();
      expect(provider.lastReading, isNotNull);
      timer.elapse(const Duration(milliseconds: 200));
      await flush();
      transport.stream.add(syntheticFrame()..[4] = 77);
      await flush();
      expect(provider.lastReading, isNull);
      expect(provider.errorMessage, contains('invalid_crc'));
      await provider.saveCurrentReading('parcel');
      expect(provider.savedReading, isNull);
      provider.dispose();
      await flush();
      await transport.stream.close();
    },
  );
  test(
    'changing parcels creates a new sampling session even at the same point',
    () async {
      final transport = FakeSerialTransport();
      final timer = ManualSensorClock();
      final repository = _CapturedReadings();
      final provider = SensorProvider(
        service: UsbSensorService(
          transport: transport,
          schedule: timer.schedule,
        ),
        readingsRepository: repository,
      );
      await provider.selectDevice(syntheticProfile(), transport.device);
      await provider.connectAndListen();
      for (final parcel in ['parcel-a', 'parcel-b', 'parcel-a']) {
        await flush();
        transport.stream.add(syntheticFrame());
        await flush();
        await provider.saveCurrentReading(parcel, pointId: 'same-point');
        timer.elapse(const Duration(milliseconds: 200));
      }
      expect(repository.captures.length, 3);
      expect(
        repository.captures
            .map((reading) => reading.measurement!.sessionId)
            .toSet()
            .length,
        3,
      );
      expect(transport.writes, 4);
      provider.dispose();
      await flush();
      await transport.stream.close();
    },
  );
  test(
    'stream errors stop acquisition and dispose ignores delayed events',
    () async {
      final transport = FakeSerialTransport();
      final timer = ManualSensorClock();
      final provider = SensorProvider(
        service: UsbSensorService(
          transport: transport,
          schedule: timer.schedule,
        ),
      );
      await provider.selectDevice(syntheticProfile(), transport.device);
      await provider.connectAndListen();
      await flush();
      transport.stream.addError(StateError('adapter disconnected'));
      await flush();
      expect(provider.status, SensorStatus.error);
      expect(provider.lastReading, isNull);
      provider.dispose();
      transport.stream.add(syntheticFrame());
      await flush();
      await transport.stream.close();
    },
  );
}

class _CapturedReadings extends ReadingsRepository {
  final captures = <SensorReading>[];
  @override
  Future<Reading> submitReading({
    required String parcelId,
    required SensorReading reading,
  }) async {
    captures.add(reading);
    return Reading.fromJson({
      'id': reading.measurementId,
      'parcel_id': parcelId,
      ...reading.payload(),
      'revision': 1,
    });
  }
}
