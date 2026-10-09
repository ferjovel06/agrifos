import 'package:app_flutter/data/sensor/sensor_reading.dart';
import 'package:app_flutter/domain/entities/reading.dart';
import 'package:app_flutter/presentation/home/widgets/last_reading_card.dart';
import 'package:app_flutter/presentation/sensor/widgets/telemetry_card.dart';
import 'package:app_flutter/presentation/sensor/sensor_provider.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import '../../../support/sensor_fixture.dart';

void main() {
  testWidgets(
    'partial raw reading shows missing variables without invented zeros or confidence',
    (tester) async {
      final reading = SensorReading.decode(
        profile: syntheticProfile(),
        frame: syntheticFrame(),
        sessionId: 'synthetic',
        deviceId: 'unit',
        acquiredAt: DateTime.utc(2026),
      );
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(
              child: TelemetryCard(
                status: SensorStatus.connected,
                reading: reading,
                saveStatus: SaveStatus.idle,
                onAction: () {},
              ),
            ),
          ),
        ),
      );
      expect(find.textContaining('Sin calibración validada'), findsOneWidget);
      expect(find.textContaining('N: 25.0 mg/kg'), findsOneWidget);
      expect(find.textContaining('ec: 1000.0 uS/cm'), findsOneWidget);
      expect(find.text('—'), findsWidgets);
      expect(find.textContaining('confiabilidad'), findsNothing);
    },
  );
  testWidgets(
    'saved reading shows filtered and calibrated results with their model versions',
    (tester) async {
      final reading = Reading.fromJson({
        'id': 'raw',
        'parcel_id': 'parcel',
        'nitrogen': null,
        'recorded_at': '2026-01-01T00:00:00Z',
        'measurement': {'contract_version': 1},
        'derived_results': [
          {
            'algorithm_version': 'same-point-centered-1',
            'created_at': '2026-01-02',
            'variables': {
              'nitrogen': {
                'raw': {'analyte': 'NO3', 'unit': 'ppm', 'value': 25},
                'filtered': 24,
                'quality_state': 'valid',
                'accuracy_state': 'calibrated',
                'reason_codes': [
                  'CENTERED_WINDOW_EDGE',
                  'STABILIZATION_NOT_ESTABLISHED',
                ],
                'calibration': {
                  'value': 23,
                  'profile_id': 'candidate-confirmed-in-fixture',
                  'profile_version': 2,
                },
              },
            },
          },
        ],
      });
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(
              child: LastReadingCard(
                reading: reading,
                isLoading: false,
                isSensorConnected: false,
              ),
            ),
          ),
        ),
      );
      expect(
        find.textContaining(
          'NO3: original 25 ppm · filtrado 24 ppm · calibrado 23 ppm',
        ),
        findsOneWidget,
      );
      expect(find.textContaining('25 mg/kg'), findsNothing);
      expect(
        find.textContaining('modelo candidate-confirmed-in-fixture v2'),
        findsOneWidget,
      );
      expect(find.text('—'), findsWidgets);
      expect(
        find.text('Ventana incompleta en el extremo: se conserva el original.'),
        findsOneWidget,
      );
      expect(
        find.text('Tiempo de estabilización aún sin determinar.'),
        findsOneWidget,
      );
      expect(find.text('Rango del fabricante no documentado.'), findsOneWidget);
    },
  );
  testWidgets(
    'home restores an incompatible raw analyte and unit before derived results exist',
    (tester) async {
      final reading = Reading.fromJson({
        'id': 'raw',
        'parcel_id': 'parcel',
        'recorded_at': '2026-01-01T00:00:00Z',
        'measurement': {
          'contract_version': 1,
          'variables': {
            'nitrogen': {
              'analyte': 'NO3',
              'unit': 'ppm',
              'raw_value': 25,
              'read_status': 'valid',
            },
          },
        },
      });
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: LastReadingCard(
              reading: reading,
              isLoading: false,
              isSensorConnected: false,
            ),
          ),
        ),
      );
      expect(find.text('NO3: original 25 ppm · valid'), findsOneWidget);
      expect(find.textContaining('25 mg/kg'), findsNothing);
      expect(find.textContaining('25%'), findsNothing);
      expect(
        find.text('Procesamiento pendiente de sincronización.'),
        findsOneWidget,
      );
    },
  );
}
