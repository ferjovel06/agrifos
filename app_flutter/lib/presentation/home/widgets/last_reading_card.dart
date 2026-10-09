import 'package:flutter/material.dart';

import '../../../domain/entities/nutrient_level.dart';
import '../../../domain/entities/reading.dart';
import '../../../domain/entities/sensor_diagnostic.dart';
import '../../../domain/reference/soil_reference_ranges.dart';
import '../../../shared/relative_time.dart';

/// "Última Lectura Global" card shown on the home dashboard: the most
/// recent stored reading (humidity, N/P/K, pH) plus live sensor connection
/// status.
class LastReadingCard extends StatelessWidget {
  const LastReadingCard({
    super.key,
    required this.reading,
    required this.isLoading,
    required this.isSensorConnected,
    this.errorMessage,
    this.onRetry,
  });

  final Reading? reading;
  final bool isLoading;
  final bool isSensorConnected;
  final String? errorMessage;
  final VoidCallback? onRetry;

  static const _titleColor = Color(0xFF472319);
  static const _labelColor = Color(0xFF8A8A8A);
  static const _borderColor = Color(0xFFEDE7E0);

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: _borderColor),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _Header(reading: reading),
          const SizedBox(height: 18),
          if (isLoading)
            const Padding(
              padding: EdgeInsets.symmetric(vertical: 12),
              child: Center(
                child: SizedBox(
                  width: 20,
                  height: 20,
                  child: CircularProgressIndicator(strokeWidth: 2),
                ),
              ),
            )
          else if (errorMessage != null)
            _ErrorState(message: errorMessage!, onRetry: onRetry)
          else if (reading == null)
            const Text(
              'Todavía no hay lecturas registradas para esta parcela.',
              style: TextStyle(color: _labelColor),
            )
          else ...[
            if (reading!.diagnosis != null) ...[
              _ServerDiagnosticNotice(diagnosis: reading!.diagnosis!),
              const SizedBox(height: 14),
            ],
            _MetricsGrid(reading: reading!),
            if (reading!.measurement != null) ...[
              const SizedBox(height: 12),
              const Text(
                'Medición original sin validación analítica de laboratorio.',
                style: TextStyle(fontSize: 12, color: _labelColor),
              ),
              if (reading!.derivedResults.isEmpty) ...[
                _OriginalValues(measurement: reading!.measurement!),
                const Text(
                  'Procesamiento pendiente de sincronización.',
                  style: TextStyle(fontSize: 12),
                ),
              ] else
                _ProcessedValues(result: reading!.derivedResults.last),
            ],
          ],
          const SizedBox(height: 16),
          _ConnectionFooter(isConnected: isSensorConnected),
        ],
      ),
    );
  }
}

class _OriginalValues extends StatelessWidget {
  const _OriginalValues({required this.measurement});
  final Map<String, dynamic> measurement;
  @override
  Widget build(BuildContext context) {
    final variables = measurement['variables'] as Map? ?? const {};
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        for (final entry in variables.entries)
          if (entry.value is Map)
            Text(
              '${entry.value['analyte'] ?? entry.key}: original '
              '${entry.value['raw_value'] ?? 'N/D'} ${entry.value['unit'] ?? 'unidad N/D'} · '
              '${entry.value['read_status'] ?? 'estado N/D'}',
              style: const TextStyle(fontSize: 11),
            ),
      ],
    );
  }
}

class _ProcessedValues extends StatelessWidget {
  const _ProcessedValues({required this.result});
  final Map<String, dynamic> result;
  @override
  Widget build(BuildContext context) {
    final variables = result['variables'] as Map<String, dynamic>? ?? const {};
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          'Algoritmo: ${result['algorithm_version']} · ${result['created_at'] ?? ''}',
          style: const TextStyle(fontSize: 11),
        ),
        for (final entry in variables.entries)
          if (entry.value is Map)
            Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  '${((entry.value as Map)['raw'] as Map?)?['analyte'] ?? entry.key}: '
                  'original ${((entry.value as Map)['raw'] as Map?)?['value'] ?? 'N/D'} ${_unit(entry.value as Map)} · '
                  'filtrado ${(entry.value as Map)['filtered'] ?? 'N/D'} ${_unit(entry.value as Map)} · '
                  'calibrado ${((entry.value as Map)['calibration'] as Map?)?['value'] ?? 'N/D'} ${_unit(entry.value as Map)} · '
                  '${(entry.value as Map)['quality_state']} / ${(entry.value as Map)['accuracy_state']}'
                  '${(entry.value as Map)['calibration'] == null ? '' : ' · modelo ${((entry.value as Map)['calibration'] as Map)['profile_id']} v${((entry.value as Map)['calibration'] as Map)['profile_version']}'}',
                  style: const TextStyle(fontSize: 11),
                ),
                for (final warning in _warnings(entry.value as Map))
                  Text(
                    warning,
                    style: const TextStyle(
                      fontSize: 11,
                      color: Color(0xFF95511E),
                    ),
                  ),
                if ((entry.value as Map)['reason_codes'] is List &&
                    ((entry.value as Map)['reason_codes'] as List).isNotEmpty)
                  Tooltip(
                    message: ((entry.value as Map)['reason_codes'] as List)
                        .join(', '),
                    child: const Text(
                      'Detalles de calidad disponibles',
                      style: TextStyle(fontSize: 10),
                    ),
                  ),
              ],
            ),
      ],
    );
  }

  String _unit(Map value) =>
      ((value['raw'] as Map?)?['unit'] as String?) ?? 'unidad N/D';

  List<String> _warnings(Map value) {
    final codes = value['reason_codes'] as List? ?? const [];
    final raw = value['raw'] as Map?;
    final warnings = <String>[];
    if (raw?['declared_range'] == null) {
      warnings.add('Rango del fabricante no documentado.');
    }
    const descriptions = {
      'INSUFFICIENT_REPETITIONS':
          'Repeticiones insuficientes: se conserva el original.',
      'CENTERED_WINDOW_EDGE':
          'Ventana incompleta en el extremo: se conserva el original.',
      'STABILIZATION_NOT_ESTABLISHED':
          'Tiempo de estabilización aún sin determinar.',
      'INSUFFICIENT_STABILIZATION': 'La sonda todavía no se ha estabilizado.',
      'OUTSIDE_DECLARED_RANGE':
          'Valor fuera del rango declarado; requiere confirmación.',
      'INVALID_DECLARED_RANGE':
          'Rango declarado incompatible; requiere revisión.',
      'TRANSMISSION_SUSPECT': 'Comunicación sospechosa; repite la medición.',
      'TRANSMISSION_INVALID': 'Trama incompatible; no utilizar para cálculos.',
      'MAD_OUTLIER': 'Valor atípico entre repeticiones; requiere revisión.',
      'ABRUPT_JUMP': 'Cambio abrupto entre repeticiones; requiere revisión.',
      'EXCESS_REPEATABILITY_DISPERSION':
          'Dispersión elevada entre repeticiones.',
      'PHYSICAL_CONTEXT_INCOMPLETE': 'Punto o contexto físico incompleto.',
    };
    for (final code in codes) {
      final text = descriptions[code];
      if (text != null) warnings.add(text);
    }
    return warnings;
  }
}

class _ServerDiagnosticNotice extends StatelessWidget {
  const _ServerDiagnosticNotice({required this.diagnosis});

  final SensorDiagnostic diagnosis;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      decoration: BoxDecoration(
        color: const Color(0xFFF1F6F2),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            diagnosis.displayLabel,
            style: const TextStyle(
              color: Color(0xFF315E45),
              fontSize: 12,
              fontWeight: FontWeight.w700,
            ),
          ),
          if (diagnosis.actionableWarnings.isNotEmpty) ...[
            const SizedBox(height: 4),
            for (final warning in diagnosis.actionableWarnings)
              Padding(
                padding: const EdgeInsets.only(top: 2),
                child: Text(
                  '• $warning',
                  style: const TextStyle(
                    color: Color(0xFF725B52),
                    fontSize: 11,
                    height: 1.3,
                  ),
                ),
              ),
          ],
        ],
      ),
    );
  }
}

class _Header extends StatelessWidget {
  const _Header({required this.reading});

  final Reading? reading;

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisAlignment: MainAxisAlignment.spaceBetween,
      children: [
        const Row(
          children: [
            Text(
              '#',
              style: TextStyle(
                fontSize: 18,
                fontWeight: FontWeight.w800,
                color: LastReadingCard._titleColor,
              ),
            ),
            SizedBox(width: 6),
            Text(
              'Última Lectura Global',
              style: TextStyle(
                fontSize: 16,
                fontWeight: FontWeight.w800,
                color: LastReadingCard._titleColor,
              ),
            ),
          ],
        ),
        if (reading != null)
          Row(
            children: [
              Icon(
                Icons.access_time_rounded,
                size: 14,
                color: Colors.grey.shade500,
              ),
              const SizedBox(width: 4),
              Text(
                formatRelativeTime(reading!.recordedAt),
                style: TextStyle(fontSize: 12, color: Colors.grey.shade500),
              ),
            ],
          ),
      ],
    );
  }
}

class _MetricsGrid extends StatelessWidget {
  const _MetricsGrid({required this.reading});

  final Reading reading;

  @override
  Widget build(BuildContext context) {
    final serverNitrogen = reading.diagnosis?.parameter('nitrogen');
    final serverPhosphorus = reading.diagnosis?.parameter('phosphorus');
    final serverPotassium = reading.diagnosis?.parameter('potassium');
    final serverPh = reading.diagnosis?.parameter('ph');
    final nitrogenLevel =
        reading.nitrogen == null || reading.measurement != null
        ? null
        : NpkThresholds.nitrogen(reading.nitrogen!);
    final phosphorusLevel =
        reading.phosphorus == null || reading.measurement != null
        ? null
        : NpkThresholds.phosphorus(reading.phosphorus!);
    final potassiumLevel =
        reading.potassium == null || reading.measurement != null
        ? null
        : NpkThresholds.potassium(reading.potassium!);
    final phLevel = reading.ph == null || reading.measurement != null
        ? null
        : classifySoilParameter(SoilParameterId.ph, reading.ph!);

    return Column(
      children: [
        Row(
          children: [
            Expanded(
              child: _MetricTile(
                label: 'Humedad',
                value: _format(reading.humidity, '%'),
                valueColor: const Color(0xFF2563EB),
                message: 'Lectura informativa',
              ),
            ),
            Expanded(
              child: _MetricTile(
                label: 'Nitrógeno',
                value: _format(reading.nitrogen, ' mg/kg'),
                valueColor: serverNitrogen == null
                    ? _nutrientColor(nitrogenLevel)
                    : _colorForDiagnosticLevel(serverNitrogen.level),
                message:
                    serverNitrogen?.message ?? _nutrientMessage(nitrogenLevel),
              ),
            ),
          ],
        ),
        const SizedBox(height: 16),
        Row(
          children: [
            Expanded(
              child: _MetricTile(
                label: 'Fósforo',
                value: _format(reading.phosphorus, ' mg/kg'),
                valueColor: serverPhosphorus == null
                    ? _nutrientColor(phosphorusLevel)
                    : _colorForDiagnosticLevel(serverPhosphorus.level),
                message:
                    serverPhosphorus?.message ??
                    _nutrientMessage(phosphorusLevel),
              ),
            ),
            Expanded(
              child: _MetricTile(
                label: 'Potasio',
                value: _format(reading.potassium, ' mg/kg'),
                valueColor: serverPotassium == null
                    ? _nutrientColor(potassiumLevel)
                    : _colorForDiagnosticLevel(serverPotassium.level),
                message:
                    serverPotassium?.message ??
                    _nutrientMessage(potassiumLevel),
              ),
            ),
          ],
        ),
        const SizedBox(height: 16),
        Row(
          children: [
            Expanded(
              child: _MetricTile(
                label: 'pH',
                value: reading.ph?.toStringAsFixed(1) ?? '—',
                valueColor: serverPh == null
                    ? phLevel == null
                          ? Colors.grey
                          : _colorForPhLevel(phLevel)
                    : _colorForDiagnosticLevel(serverPh.level, ph: true),
                message:
                    serverPh?.message ??
                    (phLevel == null
                        ? 'Sin calibración validada'
                        : _messageForPhLevel(phLevel)),
              ),
            ),
            const Expanded(child: SizedBox.shrink()),
          ],
        ),
      ],
    );
  }

  String _format(double? value, String unit) =>
      value == null ? '—' : '${value.toStringAsFixed(0)}$unit';
  Color _nutrientColor(NutrientLevel? level) =>
      level == null ? Colors.grey : NpkThresholds.colorFor(level);
  String _nutrientMessage(NutrientLevel? level) => level == null
      ? 'Sin calibración validada'
      : NpkThresholds.messageFor(level);

  Color _colorForPhLevel(SoilLevel level) {
    switch (level) {
      case SoilLevel.deficient:
        return const Color(0xFFD64545);
      case SoilLevel.optimal:
        return const Color(0xFF2563EB);
      case SoilLevel.high:
        return const Color(0xFFE08A2C);
      case SoilLevel.critical:
        return const Color(0xFFB91C1C);
    }
  }

  Color _colorForDiagnosticLevel(SoilDiagnosticLevel level, {bool ph = false}) {
    switch (level) {
      case SoilDiagnosticLevel.deficient:
        return const Color(0xFFD64545);
      case SoilDiagnosticLevel.optimal:
        return ph ? const Color(0xFF2563EB) : const Color(0xFF3B8A61);
      case SoilDiagnosticLevel.high:
        return const Color(0xFFE08A2C);
      case SoilDiagnosticLevel.critical:
        return const Color(0xFFB91C1C);
    }
  }

  String _messageForPhLevel(SoilLevel level) {
    switch (level) {
      case SoilLevel.deficient:
        return 'Acidez: requiere atención';
      case SoilLevel.optimal:
        return 'Rango óptimo';
      case SoilLevel.high:
        return 'Alcalinidad';
      case SoilLevel.critical:
        return 'Nivel crítico';
    }
  }
}

class _MetricTile extends StatelessWidget {
  const _MetricTile({
    required this.label,
    required this.value,
    required this.valueColor,
    this.message,
  });

  final String label;
  final String value;
  final Color valueColor;
  final String? message;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          label.toUpperCase(),
          style: const TextStyle(
            fontSize: 11,
            fontWeight: FontWeight.w700,
            letterSpacing: 0.4,
            color: LastReadingCard._labelColor,
          ),
        ),
        const SizedBox(height: 4),
        Text(
          value,
          style: TextStyle(
            fontSize: 20,
            fontWeight: FontWeight.w800,
            color: valueColor,
          ),
        ),
        if (message != null) ...[
          const SizedBox(height: 2),
          Text(
            message!,
            style: TextStyle(
              fontSize: 11,
              fontWeight: FontWeight.w600,
              color: valueColor,
            ),
          ),
        ],
      ],
    );
  }
}

class _ConnectionFooter extends StatelessWidget {
  const _ConnectionFooter({required this.isConnected});

  final bool isConnected;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      decoration: BoxDecoration(
        color: const Color(0xFFF7F5F1),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Row(
        children: [
          Container(
            width: 8,
            height: 8,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              color: isConnected ? Colors.green : Colors.grey.shade400,
            ),
          ),
          const SizedBox(width: 8),
          Text(
            isConnected ? 'Sensor NPK conectado' : 'Sensor NPK desconectado',
            style: TextStyle(
              fontSize: 13,
              fontWeight: FontWeight.w600,
              color: Colors.grey.shade700,
            ),
          ),
        ],
      ),
    );
  }
}

class _ErrorState extends StatelessWidget {
  const _ErrorState({required this.message, this.onRetry});

  final String message;
  final VoidCallback? onRetry;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(message, style: const TextStyle(color: Colors.red)),
        if (onRetry != null)
          Align(
            alignment: Alignment.centerLeft,
            child: TextButton(
              onPressed: onRetry,
              child: const Text('Reintentar'),
            ),
          ),
      ],
    );
  }
}
