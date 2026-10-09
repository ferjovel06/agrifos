import 'dart:async';
import 'package:flutter/services.dart';
import 'package:flutter_serial_communication/flutter_serial_communication.dart';
import 'package:flutter_serial_communication/models/device_info.dart';
import 'package:uuid/uuid.dart';
import 'sensor_protocol.dart';
import 'sensor_reading.dart';
export 'sensor_reading.dart';

class SensorDisconnectedException implements Exception {
  SensorDisconnectedException(this.message);
  final String message;
  @override
  String toString() => message;
}

class SensorAcquisitionException implements Exception {
  SensorAcquisitionException(this.code, this.message);
  final String code, message;
  @override
  String toString() => '$message ($code)';
}

/// Existing Android plugin retained behind a small testable transport seam.
class SerialTransport {
  final _plugin = FlutterSerialCommunication();
  Future<List<DeviceInfo>> devices() => _plugin.getAvailableDevices();
  Future<bool> open(DeviceInfo device, SensorProfile profile) async {
    final opened = await _plugin.connect(device, profile.baudRate);
    if (opened) {
      await _plugin.setParameters(
        profile.baudRate,
        profile.dataBits,
        profile.stopBits,
        profile.parity,
      );
    }
    return opened;
  }

  Stream<dynamic> get bytes =>
      _plugin.getSerialMessageListener().receiveBroadcastStream();
  Future<bool> write(Uint8List bytes) => _plugin.write(bytes);
  Future<void> close() => _plugin.disconnect();
}

class UsbSensorService {
  UsbSensorService({
    SerialTransport? transport,
    DateTime Function()? clock,
    Timer Function(Duration, void Function())? schedule,
  }) : _transport = transport ?? SerialTransport(),
       _clock = clock ?? DateTime.now,
       _schedule = schedule ?? Timer.new;
  final SerialTransport _transport;
  final DateTime Function() _clock;
  final Timer Function(Duration, void Function()) _schedule;
  SensorProfile? _profile;
  ModbusRtuParser? _parser;
  StreamSubscription<dynamic>? _subscription;
  Timer? _timeout, _nextPoll;
  StreamController<SensorReading>? _controller;
  int _generation = 0, _attempts = 0;
  String? _sessionId;
  bool _awaiting = false;
  Future<void> _portTail = Future.value();

  Future<T> _portAction<T>(Future<T> Function() action) {
    final next = _portTail.then((_) => action());
    _portTail = next.then<void>((_) {}, onError: (Object _) {});
    return next;
  }

  Future<List<DeviceInfo>> availableDevices() => _transport.devices();
  Future<bool> connect({SensorProfile? profile, DeviceInfo? device}) async {
    if (profile == null || device == null) {
      throw StateError(
        'Validación física pendiente: selecciona un dispositivo y un perfil verificado.',
      );
    }
    profile.validate();
    if (device.vendorId != profile.vendorId ||
        device.productId != profile.productId) {
      throw SensorAcquisitionException(
        'incompatible_device',
        'VID/PID incompatible con el perfil documentado.',
      );
    }
    await dispose();
    final generation = _generation;
    return _portAction(() async {
      if (generation != _generation) return false;
      try {
        final available = await _transport.devices();
        if (!available.any(
          (d) =>
              d.deviceId == device.deviceId &&
              d.vendorId == device.vendorId &&
              d.productId == device.productId,
        )) {
          throw SensorDisconnectedException(
            'El dispositivo seleccionado ya no está conectado.',
          );
        }
        final opened = await _transport.open(device, profile);
        if (generation != _generation) {
          await _transport.close();
          return false;
        }
        if (!opened) {
          throw SensorAcquisitionException(
            'usb_permission_or_open',
            'No se pudo abrir USB. Revisa el permiso Android, el adaptador y la alimentación.',
          );
        }
        _profile = profile;
        _parser = ModbusRtuParser(profile);
        _sessionId = const Uuid().v4();
        _attempts = 0;
        return true;
      } catch (_) {
        await _transport.close();
        rethrow;
      }
    });
  }

  Stream<SensorReading> readings() {
    if (_profile == null || _controller != null) {
      throw StateError(
        'Conecta primero un perfil verificado; solo se permite una adquisición.',
      );
    }
    final generation = _generation;
    final controller = StreamController<SensorReading>();
    _controller = controller;
    _subscription = _transport.bytes.listen(
      (event) {
        if (generation != _generation || !_awaiting) return;
        if (event is! List || event.any((byte) => byte is! int)) {
          _fail(
            SensorAcquisitionException(
              'invalid_serial_data',
              'Datos seriales incompatibles.',
            ),
          );
          return;
        }
        for (final parsed in _parser!.add(event.cast<int>())) {
          if (!parsed.valid) {
            controller.addError(
              SensorAcquisitionException(
                parsed.errorCode!,
                'No hay una medición válida; revisa la comunicación y alimentación.',
              ),
            );
            if (parsed.errorCode == 'device_exception') {
              _fail(
                SensorAcquisitionException(
                  'device_exception',
                  'La sonda rechazó la lectura (${parsed.exceptionCode}).',
                ),
              );
              return;
            }
            continue;
          }
          _timeout?.cancel();
          _awaiting = false;
          _attempts = 0;
          controller.add(
            SensorReading.decode(
              profile: _profile!,
              frame: parsed.bytes!,
              sessionId: _sessionId!,
              deviceId: _profile!.physicalDeviceId,
              acquiredAt: _clock().toUtc(),
            ),
          );
          _nextPoll?.cancel();
          _nextPoll = _schedule(
            _profile!.pollInterval,
            () => _query(generation),
          );
          // One outstanding request accepts one response, never duplicate copies.
          return;
        }
      },
      onError: (Object error) {
        _fail(SensorDisconnectedException('Conexión USB interrumpida: $error'));
      },
      onDone: () {
        if (generation == _generation) {
          _fail(SensorDisconnectedException('Canal USB cerrado.'));
        }
      },
    );
    unawaited(_query(generation));
    return controller.stream;
  }

  Future<void> _query(int generation) async {
    if (generation != _generation || _profile == null || _controller == null) {
      return;
    }
    _parser!.clear();
    _awaiting = true;
    _attempts++;
    _timeout = _schedule(_profile!.responseTimeout, () {
      if (generation != _generation) return;
      final partial = _parser!.expire();
      _controller?.addError(
        SensorAcquisitionException(
          partial?.errorCode ?? 'timeout',
          'No hay una medición válida: respuesta incompleta o fuera de tiempo.',
        ),
      );
      _awaiting = false;
      if (_attempts <= _profile!.maxRetries) {
        _nextPoll = _schedule(_profile!.pollInterval, () => _query(generation));
      } else {
        _fail(
          SensorDisconnectedException(
            'Se agotaron los reintentos de lectura USB.',
          ),
        );
      }
    });
    try {
      final sent = await _transport.write(_profile!.request());
      if (generation == _generation && !sent) {
        _fail(
          SensorDisconnectedException(
            'El adaptador no pudo transmitir la solicitud.',
          ),
        );
      }
    } catch (error) {
      if (generation == _generation) {
        _fail(SensorDisconnectedException('Error USB: $error'));
      }
    }
  }

  void _fail(Object error) {
    final controller = _controller;
    if (controller == null || controller.isClosed) return;
    controller.addError(error);
    unawaited(dispose());
  }

  Future<void> dispose() async {
    _generation++;
    _timeout?.cancel();
    _nextPoll?.cancel();
    _timeout = _nextPoll = null;
    _awaiting = false;
    _profile = null;
    _parser?.clear();
    _parser = null;
    final subscription = _subscription;
    _subscription = null;
    final controller = _controller;
    _controller = null;
    await subscription?.cancel();
    if (controller != null && !controller.isClosed) {
      // A paused subscriber must never hold the physical USB resource open.
      unawaited(controller.close());
    }
    await _portAction(() async {
      try {
        await _transport.close();
      } catch (_) {
        /* Already detached. */
      }
    });
  }
}
