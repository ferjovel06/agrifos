import 'dart:convert';
import 'dart:io';
import 'package:app_flutter/domain/entities/fertilization_recommendation.dart';
import 'package:app_flutter/presentation/fertilization/fertilization_plan_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  FertilizationRecommendation fixture() => FertilizationRecommendation.fromJson(
    jsonDecode(
          File('test/fixtures/organic_recommendation.json').readAsStringSync(),
        )
        as Map<String, dynamic>,
  );

  test('backend fixture preserves liquid units and disables execution', () {
    final result = fixture();
    expect(result.scenarios.map((s) => s.name), [
      'Económico',
      'Bajo cloruro',
      'Orgánico',
    ]);
    final organic = result.scenarios.last.organic!;
    expect(organic.canApply, isFalse);
    expect(organic.candidates.map((p) => p.unit), ['kg', 'L', 'kg']);
    expect(organic.candidates[1].quantityHa, 100);
    expect(organic.candidates[1].plantUnit, 'mL');
    expect(organic.totalContributions['N'], closeTo(16.60, .02));
    expect(result.scenarios.last.applicationSchedule, isEmpty);
  });

  testWidgets('mobile selector shows partial evaluation and blocks schedule', (
    tester,
  ) async {
    await tester.binding.setSurfaceSize(const Size(390, 844));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    await tester.pumpWidget(
      MaterialApp(home: FertilizationPlanScreen(recommendation: fixture())),
    );
    await tester.tap(find.byType(DropdownButtonFormField<int>));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Orgánico').last);
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(
      find.text('Biol'),
      200,
      scrollable: find.byType(Scrollable).first,
    );
    expect(
      find.text('Fuentes y dosis totales · evaluación de referencia'),
      findsOneWidget,
    );
    await tester.scrollUntilVisible(
      find.text('Biol'),
      200,
      scrollable: find.byType(Scrollable).first,
    );
    expect(find.text('100\nL/ha'), findsOneWidget);
    expect(find.text('100\nkg/ha'), findsNothing);
    expect(find.text('1.372 t/ha · referencia'), findsOneWidget);
    await tester.tap(find.text('Aplicaciones'));
    await tester.pumpAndSettle();
    expect(
      find.textContaining('No hay dosis ni aplicaciones aprobadas'),
      findsOneWidget,
    );
    expect(find.text('Calendario de aplicación'), findsNothing);
    expect(tester.takeException(), isNull);
  });
}
