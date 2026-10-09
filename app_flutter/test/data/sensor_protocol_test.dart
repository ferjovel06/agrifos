import 'package:app_flutter/data/sensor/sensor_protocol.dart';
import 'package:app_flutter/data/sensor/sensor_reading.dart';
import 'package:flutter_test/flutter_test.dart';
import '../support/sensor_fixture.dart';

void main() {
  test('CRC matches a published Modbus example and requests are read-only', () {
    expect(withModbusCrc([1, 3, 0, 0, 0, 10]), [1, 3, 0, 0, 0, 10, 197, 205]);
    expect(syntheticProfile().request()[1], 3);
    expect(() => syntheticProfile(verified: false).request(), throwsStateError);
  });
  test(
    'chunked frames, noise and multiple complete frames drain iteratively',
    () {
      final parser = ModbusRtuParser(syntheticProfile());
      final frame = syntheticFrame();
      expect(
        parser.add([88, 77, ...frame.take(4)]).where((r) => r.valid),
        isEmpty,
      );
      final results = parser.add([...frame.skip(4), ...syntheticFrame(30)]);
      expect(results.where((r) => r.valid).length, 2);
      expect(parser.bufferedBytes, 0);
    },
  );
  test('bad CRC never decodes, resynchronizes, and partial data expire', () {
    final parser = ModbusRtuParser(syntheticProfile());
    final bad = syntheticFrame()..[4] = 77;
    final results = parser.add([...bad, ...syntheticFrame(30)]);
    expect(results.any((r) => r.errorCode == 'invalid_crc'), isTrue);
    expect(results.where((r) => r.valid).length, 1);
    parser.add(syntheticFrame().take(4).toList());
    expect(parser.expire()!.errorCode, 'incomplete_frame');
    expect(parser.bufferedBytes, 0);
    expect(parser.add(syntheticFrame()).single.valid, isTrue);
  });
  test('exception responses and impossible serial chunks are bounded', () {
    final parser = ModbusRtuParser(syntheticProfile());
    expect(parser.add(withModbusCrc([1, 131, 2])).single.exceptionCode, 2);
    expect(
      parser.add(List.filled(4097, 1)).single.errorCode,
      'receive_overflow',
    );
    expect(parser.add([256]).single.errorCode, 'receive_overflow');
    expect(parser.bufferedBytes, 0);
    for (var i = 0; i < 100; i++) {
      parser.add(List.filled(4096, 77));
    }
    expect(parser.bufferedBytes, lessThanOrEqualTo(1));
  });
  test(
    'only documented variables, signed decoding and units are preserved',
    () {
      final acquired = DateTime.utc(2026, 10, 8);
      final reading = SensorReading.decode(
        profile: syntheticProfile(),
        frame: syntheticFrame(),
        sessionId: 's',
        deviceId: 'd',
        acquiredAt: acquired,
      );
      expect(reading.nitrogen, 25);
      expect(reading.ec, 1);
      expect(reading.temperature, -1);
      expect(reading.phosphorus, isNull);
      expect(reading.humidity, isNull);
      expect(reading.measurement!.variables.keys, [
        'nitrogen',
        'ec',
        'temperature',
      ]);
      expect(reading.measurement!.variables['ec']!.rawValue, 1000);
      expect(reading.acquiredAt, acquired);
      expect(reading.measurement!.frameHex.length, lessThanOrEqualTo(512));
    },
  );
  test('out-of-manufacturer-range raw values remain suspect and unchanged', () {
    final reading = SensorReading.decode(
      profile: syntheticProfile(),
      frame: syntheticFrame(101),
      sessionId: 's',
      deviceId: 'd',
      acquiredAt: DateTime.utc(2026),
    );
    expect(reading.nitrogen, 101);
    expect(reading.measurement!.variables['nitrogen']!.readStatus, 'suspect');
    expect(reading.measurement!.variables['nitrogen']!.rawValue, 101);
  });
  test('chemical species and concentration units never convert silently', () {
    const nitrate = SensorVariable(
      key: 'nitrogen',
      registerOffset: 0,
      analyte: 'NO3',
      unit: 'mg/kg',
      scale: 1,
    );
    const solution = SensorVariable(
      key: 'nitrogen',
      registerOffset: 0,
      analyte: 'N',
      unit: 'mg/L',
      scale: 1,
    );
    expect(nitrate.apiValue(10), isNull);
    expect(solution.apiValue(10), isNull);
    expect(
      () => syntheticProfile(
        variables: const [
          SensorVariable(
            key: 'nitrogen',
            registerOffset: 0,
            unit: 'arbitrary',
            analyte: 'N',
            scale: 1,
          ),
        ],
      ).validate(),
      throwsArgumentError,
    );
  });
  test('GPS cannot be attached without valid coordinates and consent', () {
    expect(
      () => MeasurementLocation(
        latitude: 12,
        longitude: -86,
        accuracyM: 5,
        consent: false,
      ),
      throwsArgumentError,
    );
    expect(
      () => MeasurementLocation(
        latitude: 91,
        longitude: -86,
        accuracyM: 5,
        consent: true,
      ),
      throwsArgumentError,
    );
  });
}
