import 'dart:async';
import 'package:flutter/foundation.dart';
import 'package:flutter_serial_communication/models/device_info.dart';
import 'package:uuid/uuid.dart';
import '../../data/api/readings_repository.dart';
import '../../data/sensor/sensor_protocol.dart';
import '../../data/sensor/usb_sensor_service.dart';
import '../../domain/entities/reading.dart';
import '../../domain/entities/sensor_diagnostic.dart';

enum SensorStatus { disconnected, connecting, connected, reconnecting, error }

enum SaveStatus { idle, saving, saved, error }

class SensorProvider extends ChangeNotifier {
  SensorProvider({
    ReadingsRepository? readingsRepository,
    UsbSensorService? service,
  }) : _readingsRepository = readingsRepository ?? ReadingsRepository(),
       _service = service ?? UsbSensorService();
  final UsbSensorService _service;
  final ReadingsRepository _readingsRepository;
  SensorStatus status = SensorStatus.disconnected;
  SensorReading? lastReading;
  String? errorMessage =
      'Validación física pendiente: falta el modelo, manual y perfil verificado del sensor.';
  SaveStatus saveStatus = SaveStatus.idle;
  String? saveErrorMessage;
  SensorDiagnostic? savedDiagnosis;
  Reading? savedReading;
  SensorProfile? _profile;
  DeviceInfo? _device;
  StreamSubscription<SensorReading>? _readings;
  int _generation = 0;
  bool _disposed = false;
  (String, String, double?, String?)? _samplingKey;
  String? _samplingSession;

  Future<List<DeviceInfo>> availableDevices() => _service.availableDevices();

  /// A reviewed manual/profile and an explicitly selected USB device are required.
  /// Merely plugging in a generic adapter never sends a query.
  Future<void> selectDevice(SensorProfile profile, DeviceInfo device) async {
    profile.validate();
    await disconnect();
    _profile = profile;
    _device = device;
    errorMessage = null;
    notifyListeners();
  }

  Future<void> connectAndListen() async {
    if (_disposed ||
        status == SensorStatus.connecting ||
        status == SensorStatus.connected) {
      return;
    }
    final generation = ++_generation;
    _clearSample();
    status = SensorStatus.connecting;
    errorMessage = null;
    notifyListeners();
    try {
      await _readings?.cancel();
      final connected = await _service.connect(
        profile: _profile,
        device: _device,
      );
      if (_disposed || generation != _generation) return;
      if (!connected) {
        throw SensorDisconnectedException(
          'No se pudo conectar al dispositivo seleccionado.',
        );
      }
      status = SensorStatus.connected;
      _readings = _service.readings().listen(
        (reading) {
          if (_disposed || generation != _generation) return;
          _clearSample();
          lastReading = reading;
          errorMessage = null;
          notifyListeners();
        },
        onError: (Object error) {
          if (_disposed || generation != _generation) return;
          _clearSample();
          errorMessage = error.toString();
          if (error is SensorDisconnectedException ||
              error is SensorAcquisitionException &&
                  error.code == 'device_exception') {
            status = SensorStatus.error;
          }
          notifyListeners();
        },
        onDone: () {
          if (_disposed || generation != _generation) return;
          _clearSample();
          status = SensorStatus.error;
          errorMessage ??=
              'No hay una medición válida. Reconecta el dispositivo seleccionado.';
          notifyListeners();
        },
      );
      notifyListeners();
    } catch (error) {
      if (_disposed || generation != _generation) return;
      _clearSample();
      status = SensorStatus.error;
      errorMessage = error.toString();
      notifyListeners();
    }
  }

  void _clearSample() {
    lastReading = null;
    savedDiagnosis = null;
    savedReading = null;
    saveStatus = SaveStatus.idle;
    saveErrorMessage = null;
  }

  Future<void> saveCurrentReading(
    String parcelId, {
    String? pointId,
    double? depthCm,
    String? soilType,
  }) async {
    final sample = lastReading;
    if (pointId != null) {
      final key = (parcelId, pointId.trim(), depthCm, soilType?.trim());
      if (key != _samplingKey) {
        _samplingKey = key;
        _samplingSession = const Uuid().v4();
      }
    }
    final reading = pointId == null
        ? sample
        : sample?.withSamplingContext(
            pointId: pointId,
            depthCm: depthCm,
            soilType: soilType,
            sessionId: _samplingSession,
          );
    if (status != SensorStatus.connected ||
        reading == null ||
        saveStatus == SaveStatus.saving ||
        saveStatus == SaveStatus.saved) {
      return;
    }
    final generation = _generation;
    saveStatus = SaveStatus.saving;
    saveErrorMessage = null;
    notifyListeners();
    try {
      final result = await _readingsRepository.submitReading(
        parcelId: parcelId,
        reading: reading,
      );
      if (_disposed || generation != _generation || lastReading != sample) {
        return;
      }
      savedDiagnosis = result.diagnosis;
      savedReading = result;
      saveStatus = SaveStatus.saved;
      notifyListeners();
    } catch (error) {
      if (_disposed || generation != _generation || lastReading != sample) {
        return;
      }
      saveStatus = SaveStatus.error;
      saveErrorMessage = 'No se pudo guardar la lectura: $error';
      notifyListeners();
    }
  }

  Future<void> disconnect() async {
    _generation++;
    _samplingKey = null;
    _samplingSession = null;
    _clearSample();
    status = SensorStatus.disconnected;
    errorMessage = null;
    await _readings?.cancel();
    _readings = null;
    await _service.dispose();
    if (!_disposed) notifyListeners();
  }

  @override
  void dispose() {
    _disposed = true;
    _generation++;
    _readings?.cancel();
    unawaited(_service.dispose());
    super.dispose();
  }
}
