import 'dart:typed_data';

/// No production profile ships until the manual and physical device are verified.
class SensorProfile {
  const SensorProfile({
    required this.id,
    required this.sensorModel,
    required this.documentReference,
    required this.physicalDeviceId,
    required this.identityEvidence,
    required this.verified,
    required this.vendorId,
    required this.productId,
    required this.baudRate,
    required this.dataBits,
    required this.stopBits,
    required this.parity,
    required this.slaveId,
    required this.function,
    required this.startRegister,
    required this.registerCount,
    required this.variables,
    required this.responseTimeout,
    required this.pollInterval,
    required this.maxRetries,
  });

  final String id, sensorModel, documentReference;
  final String physicalDeviceId, identityEvidence;
  final bool verified;
  final int vendorId, productId, baudRate, dataBits, stopBits, parity;
  final int slaveId, function, startRegister, registerCount, maxRetries;
  final Duration responseTimeout, pollInterval;
  final List<SensorVariable> variables;

  void validate({bool requireVerified = true}) {
    if ((requireVerified && !verified) ||
        id.trim().isEmpty ||
        sensorModel.trim().isEmpty ||
        physicalDeviceId.trim().isEmpty ||
        physicalDeviceId.length > 120 ||
        identityEvidence.trim().isEmpty ||
        documentReference.trim().isEmpty) {
      throw StateError(
        'Perfil pendiente de verificar con el manual y el sensor real.',
      );
    }
    if (vendorId < 1 ||
        vendorId > 65535 ||
        productId < 1 ||
        productId > 65535 ||
        baudRate <= 0 ||
        dataBits < 5 ||
        dataBits > 8 ||
        ![1, 2, 3].contains(stopBits) ||
        parity < 0 ||
        parity > 4 ||
        slaveId < 1 ||
        slaveId > 247 ||
        ![3, 4].contains(function) ||
        startRegister < 0 ||
        startRegister > 65535 ||
        registerCount < 1 ||
        registerCount > 125 ||
        startRegister + registerCount > 65536 ||
        responseTimeout <= Duration.zero ||
        pollInterval < responseTimeout ||
        maxRetries < 0 ||
        maxRetries > 5 ||
        variables.isEmpty) {
      throw ArgumentError('Parámetros de lectura documentados inválidos.');
    }
    final keys = <String>{}, offsets = <int>{};
    for (final variable in variables) {
      variable.validate(registerCount);
      if (!keys.add(variable.key) || !offsets.add(variable.registerOffset)) {
        throw ArgumentError('Variables o registros duplicados en el perfil.');
      }
    }
  }

  Uint8List request() {
    validate();
    return Uint8List.fromList(
      withModbusCrc([
        slaveId,
        function,
        startRegister >> 8,
        startRegister & 255,
        registerCount >> 8,
        registerCount & 255,
      ]),
    );
  }
}

class SensorVariable {
  const SensorVariable({
    required this.key,
    required this.registerOffset,
    required this.unit,
    required this.analyte,
    required this.scale,
    this.signed = false,
    this.range,
  });
  final String key, unit, analyte;
  final int registerOffset;
  final double scale;
  final bool signed;
  final List<double>? range;

  static const keys = {
    'nitrogen',
    'phosphorus',
    'potassium',
    'ec',
    'ph',
    'temperature',
    'humidity',
  };
  static const units = {
    'nitrogen': {'mg/kg', 'mg/L', 'ppm', '%'},
    'phosphorus': {'mg/kg', 'mg/L', 'ppm', '%'},
    'potassium': {'mg/kg', 'mg/L', 'ppm', '%'},
    'ec': {'dS/m', 'mS/cm', 'uS/cm'},
    'ph': {'pH'},
    'temperature': {'degC'},
    'humidity': {'%'},
  };
  static const analytes = {
    'nitrogen': {'N', 'NO3-N', 'NO3', 'unidentified'},
    'phosphorus': {'P', 'P2O5', 'unidentified'},
    'potassium': {'K', 'K2O', 'unidentified'},
    'ec': {'ec'},
    'ph': {'ph'},
    'temperature': {'temperature'},
    'humidity': {'humidity'},
  };
  void validate(int count) {
    if (!keys.contains(key) ||
        !(units[key]?.contains(unit) ?? false) ||
        !(analytes[key]?.contains(analyte) ?? false) ||
        registerOffset < 0 ||
        registerOffset >= count ||
        !scale.isFinite ||
        !(65535 * scale).isFinite ||
        scale <= 0 ||
        (range != null &&
            (range!.length != 2 ||
                range!.any((v) => !v.isFinite) ||
                range![0] >= range![1]))) {
      throw ArgumentError('Variable, unidad, escala o rango no verificado.');
    }
  }

  double decode(List<int> bytes) {
    final offset = registerOffset * 2;
    var value = (bytes[offset] << 8) | bytes[offset + 1];
    if (signed && value >= 32768) value -= 65536;
    return value * scale;
  }

  /// Only map chemically compatible documented magnitudes into the legacy API.
  double? apiValue(double value) {
    if (!value.isFinite) return null;
    if (key == 'nitrogen' && analyte == 'N' && unit == 'mg/kg' ||
        key == 'phosphorus' && analyte == 'P' && unit == 'mg/kg' ||
        key == 'potassium' && analyte == 'K' && unit == 'mg/kg' ||
        key == 'ph' && analyte == 'ph' && unit == 'pH' ||
        key == 'temperature' && analyte == 'temperature' && unit == 'degC' ||
        key == 'humidity' && analyte == 'humidity' && unit == '%') {
      return value;
    }
    if (key == 'ec' && analyte == 'ec') {
      if (unit == 'dS/m' || unit == 'mS/cm') return value;
      if (unit == 'uS/cm') return value / 1000;
    }
    return null;
  }
}

int modbusCrc(List<int> bytes) {
  var crc = 65535;
  for (final byte in bytes) {
    crc ^= byte;
    for (var bit = 0; bit < 8; bit++) {
      crc = (crc & 1) == 1 ? (crc >> 1) ^ 0xa001 : crc >> 1;
    }
  }
  return crc;
}

List<int> withModbusCrc(List<int> bytes) {
  final crc = modbusCrc(bytes);
  return [...bytes, crc & 255, crc >> 8];
}

class SerialFrame {
  SerialFrame({this.bytes, this.errorCode, this.exceptionCode});
  final List<int>? bytes;
  final String? errorCode;
  final int? exceptionCode;
  bool get valid => bytes != null && errorCode == null;
}

/// One bounded, iterative RTU parser. Partial data expires at request timeout.
class ModbusRtuParser {
  ModbusRtuParser(this.profile) {
    profile.validate(requireVerified: false);
  }
  final SensorProfile profile;
  final List<int> _buffer = [];
  int get bufferedBytes => _buffer.length;
  void clear() => _buffer.clear();
  SerialFrame? expire() {
    if (_buffer.isEmpty) return null;
    clear();
    return SerialFrame(errorCode: 'incomplete_frame');
  }

  List<SerialFrame> add(List<int> chunk) {
    if (chunk.length > 4096 || chunk.any((b) => b < 0 || b > 255)) {
      clear();
      return [SerialFrame(errorCode: 'receive_overflow')];
    }
    final results = <SerialFrame>[];
    for (final byte in chunk) {
      _buffer.add(byte);
      while (_buffer.length >= 2) {
        if (_buffer[0] != profile.slaveId ||
            ![profile.function, profile.function | 128].contains(_buffer[1])) {
          _buffer.removeAt(0);
          continue;
        }
        if (_buffer.length < 3) break;
        final exception = _buffer[1] == (profile.function | 128);
        if (!exception && _buffer[2] != profile.registerCount * 2) {
          results.add(SerialFrame(errorCode: 'unexpected_length'));
          _buffer.removeAt(0);
          continue;
        }
        final length = exception ? 5 : 5 + profile.registerCount * 2;
        if (_buffer.length < length) break;
        final frame = _buffer.sublist(0, length);
        final received = frame[length - 2] | (frame[length - 1] << 8);
        if (modbusCrc(frame.sublist(0, length - 2)) != received) {
          results.add(SerialFrame(errorCode: 'invalid_crc'));
          _buffer.removeAt(0);
          continue;
        }
        _buffer.removeRange(0, length);
        results.add(
          exception
              ? SerialFrame(
                  errorCode: 'device_exception',
                  exceptionCode: frame[2],
                )
              : SerialFrame(bytes: List.unmodifiable(frame)),
        );
      }
    }
    return results;
  }
}
