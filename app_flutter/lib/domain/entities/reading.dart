import 'sensor_diagnostic.dart';

/// A soil/sensor reading as stored by the backend (`GET /readings`).
///
/// Mirrors `ReadingRead` in `app/schemas/reading.py`. Units match what the
/// backend stores: nitrogen/phosphorus/potassium in mg/kg, ec in dS/m,
/// temperature in °C, humidity in %.
class Reading {
  final String syncStatus;
  final String id;
  final String parcelId;
  final double? nitrogen;
  final double? phosphorus;
  final double? potassium;
  final double? ec;
  final double? ph;
  final double? temperature;
  final double? humidity;
  final Map<String, dynamic>? measurement;
  final List<Map<String, dynamic>> derivedResults;
  final DateTime recordedAt;
  final DateTime? receivedAt;
  final SensorDiagnostic? diagnosis;

  const Reading({
    this.syncStatus = 'synced',
    required this.id,
    required this.parcelId,
    required this.nitrogen,
    required this.phosphorus,
    required this.potassium,
    required this.ec,
    required this.ph,
    required this.temperature,
    required this.humidity,
    required this.recordedAt,
    this.receivedAt,
    this.diagnosis,
    this.measurement,
    this.derivedResults = const [],
  });

  factory Reading.fromJson(Map<String, dynamic> json) {
    return Reading(
      syncStatus: json['_sync_status'] as String? ?? 'synced',
      id: json['id'] as String,
      parcelId: json['parcel_id'] as String,
      nitrogen: (json['nitrogen'] as num?)?.toDouble(),
      phosphorus: (json['phosphorus'] as num?)?.toDouble(),
      potassium: (json['potassium'] as num?)?.toDouble(),
      ec: (json['ec'] as num?)?.toDouble(),
      ph: (json['ph'] as num?)?.toDouble(),
      temperature: (json['temperature'] as num?)?.toDouble(),
      humidity: (json['humidity'] as num?)?.toDouble(),
      measurement: json['measurement'] as Map<String, dynamic>?,
      derivedResults: (json['derived_results'] as List? ?? const [])
          .cast<Map<String, dynamic>>(),
      recordedAt: DateTime.parse(json['recorded_at'] as String).toLocal(),
      receivedAt: json['received_at'] == null
          ? null
          : DateTime.parse(json['received_at'] as String).toLocal(),
      diagnosis: json['diagnosis'] == null
          ? null
          : SensorDiagnostic.fromJson(
              json['diagnosis'] as Map<String, dynamic>,
            ),
    );
  }

  Reading copyWith({SensorDiagnostic? diagnosis}) {
    return Reading(
      syncStatus: syncStatus,
      id: id,
      parcelId: parcelId,
      nitrogen: nitrogen,
      phosphorus: phosphorus,
      potassium: potassium,
      ec: ec,
      ph: ph,
      temperature: temperature,
      humidity: humidity,
      recordedAt: recordedAt,
      receivedAt: receivedAt,
      diagnosis: diagnosis ?? this.diagnosis,
      measurement: measurement,
      derivedResults: derivedResults,
    );
  }
}
