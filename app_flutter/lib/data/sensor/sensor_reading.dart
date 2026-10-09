import 'package:uuid/uuid.dart';
import 'sensor_protocol.dart';

class SensorReading {
  SensorReading({
    this.nitrogen,
    this.phosphorus,
    this.potassium,
    this.ec,
    this.ph,
    this.temperature,
    this.humidity,
    DateTime? acquiredAt,
    String? measurementId,
    this.measurement,
  }) : acquiredAt = (acquiredAt ?? DateTime.now()).toUtc(),
       measurementId = measurementId ?? const Uuid().v4();

  /// Values compatible with the API; EC is dS/m, never an assumed raw unit.
  final double? nitrogen, phosphorus, potassium, ec, ph, temperature, humidity;
  final DateTime acquiredAt;
  final String measurementId;
  final MeasurementProvenance? measurement;
  SensorReading withSamplingContext({
    required String pointId,
    double? depthCm,
    String? soilType,
    String? sessionId,
  }) {
    if (pointId.trim().isEmpty ||
        pointId.length > 120 ||
        (depthCm != null && (!depthCm.isFinite || depthCm < 0)) ||
        (soilType != null &&
            (soilType.trim().isEmpty || soilType.length > 120))) {
      throw ArgumentError('Punto, profundidad o tipo de suelo inválido.');
    }
    final original = measurement;
    if (original == null) {
      throw StateError('La lectura no tiene procedencia verificable.');
    }
    return SensorReading(
      nitrogen: nitrogen,
      phosphorus: phosphorus,
      potassium: potassium,
      ec: ec,
      ph: ph,
      temperature: temperature,
      humidity: humidity,
      acquiredAt: acquiredAt,
      measurementId: measurementId,
      measurement: MeasurementProvenance(
        sessionId: sessionId ?? original.sessionId,
        deviceId: original.deviceId,
        sensorModel: original.sensorModel,
        profileId: original.profileId,
        acquiredAt: original.acquiredAt,
        variables: original.variables,
        frameHex: original.frameHex,
        pointId: pointId.trim(),
        depthCm: depthCm,
        soilType: soilType?.trim(),
        location: original.location,
      ),
    );
  }

  Map<String, dynamic> payload() => {
    'nitrogen': nitrogen,
    'phosphorus': phosphorus,
    'potassium': potassium,
    'ec': ec,
    'ph': ph,
    'temperature': temperature,
    'humidity': humidity,
    'recorded_at': acquiredAt.toIso8601String(),
    if (measurement != null) 'measurement': measurement!.toJson(),
    if (measurement != null) 'measurement_id': measurementId,
  };

  factory SensorReading.decode({
    required SensorProfile profile,
    required List<int> frame,
    required String sessionId,
    required String deviceId,
    required DateTime acquiredAt,
  }) {
    final data = frame.sublist(3, frame.length - 2);
    final flat = <String, double?>{}, variables = <String, MeasuredVariable>{};
    for (final specification in profile.variables) {
      final value = specification.decode(data);
      final outside =
          specification.range != null &&
          (value < specification.range![0] || value > specification.range![1]);
      variables[specification.key] = MeasuredVariable(
        rawValue: value,
        unit: specification.unit,
        analyte: specification.analyte,
        declaredRange: specification.range,
        readStatus: outside ? 'suspect' : 'valid',
      );
      flat[specification.key] = specification.apiValue(value);
    }
    return SensorReading(
      nitrogen: flat['nitrogen'],
      phosphorus: flat['phosphorus'],
      potassium: flat['potassium'],
      ec: flat['ec'],
      ph: flat['ph'],
      temperature: flat['temperature'],
      humidity: flat['humidity'],
      acquiredAt: acquiredAt,
      measurement: MeasurementProvenance(
        sessionId: sessionId,
        deviceId: deviceId,
        sensorModel: profile.sensorModel,
        profileId: profile.id,
        acquiredAt: acquiredAt,
        variables: variables,
        frameHex: frame
            .take(256)
            .map((v) => v.toRadixString(16).padLeft(2, '0'))
            .join(),
      ),
    );
  }
}

class MeasuredVariable {
  MeasuredVariable({
    required this.rawValue,
    required this.unit,
    required this.analyte,
    required this.readStatus,
    List<double>? declaredRange,
  }) : declaredRange = declaredRange == null
           ? null
           : List.unmodifiable(declaredRange);
  final double rawValue;
  final String unit, analyte, readStatus;
  final List<double>? declaredRange;
  Map<String, dynamic> toJson() => {
    'raw_value': rawValue,
    'unit': unit,
    'analyte': analyte,
    'read_status': readStatus,
    if (declaredRange != null) 'declared_range': declaredRange,
  };
}

class MeasurementProvenance {
  MeasurementProvenance({
    required this.sessionId,
    required this.deviceId,
    required this.sensorModel,
    required this.profileId,
    required this.acquiredAt,
    required Map<String, MeasuredVariable> variables,
    required this.frameHex,
    this.pointId,
    this.depthCm,
    this.soilType,
    this.location,
  }) : variables = Map.unmodifiable(variables);
  final String sessionId, deviceId, sensorModel, profileId, frameHex;
  final DateTime acquiredAt;
  final Map<String, MeasuredVariable> variables;
  final String? pointId;
  final String? soilType;
  final double? depthCm;
  final MeasurementLocation? location;
  Map<String, dynamic> toJson() => {
    'contract_version': 1,
    'session_id': sessionId,
    'device_id': deviceId,
    'sensor_model': sensorModel,
    'protocol_version': 'modbus-rtu-1',
    'profile_id': profileId,
    'acquired_at': acquiredAt.toUtc().toIso8601String(),
    'variables': variables.map((key, value) => MapEntry(key, value.toJson())),
    'frame_hex': frameHex,
    if (pointId != null) 'point_id': pointId,
    if (depthCm != null) 'depth_cm': depthCm,
    if (soilType != null) 'soil_type': soilType,
    if (location != null) 'location': location!.toJson(),
  };
}

class MeasurementLocation {
  MeasurementLocation({
    required this.latitude,
    required this.longitude,
    required this.accuracyM,
    required bool consent,
  }) {
    if (!consent ||
        !latitude.isFinite ||
        !longitude.isFinite ||
        latitude < -90 ||
        latitude > 90 ||
        longitude < -180 ||
        longitude > 180 ||
        !accuracyM.isFinite ||
        accuracyM < 0) {
      throw ArgumentError('Ubicación inválida o sin consentimiento.');
    }
  }
  final double latitude, longitude, accuracyM;
  Map<String, dynamic> toJson() => {
    'consent': true,
    'latitude': latitude,
    'longitude': longitude,
    'accuracy_m': accuracyM,
  };
}
