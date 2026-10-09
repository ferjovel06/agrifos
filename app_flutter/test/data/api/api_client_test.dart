import 'dart:async';
import 'dart:convert';

import 'package:app_flutter/data/api/api_client.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

void main() {
  ApiClient client(FutureOr<http.Response> Function(http.Request) handler) {
    final api = ApiClient(
      httpClient: MockClient((request) async => handler(request)),
      baseUrl: 'https://api.example.com',
      tokenProvider: () => 'test-token',
    );
    addTearDown(api.close);
    return api;
  }

  Matcher message(String text) => isA<ApiException>().having(
    (error) => error.message,
    'user message',
    text,
  );

  for (final body in [
    '<html>Traceback: database password</html>',
    jsonEncode({'detail': 'SQLAlchemyError: database password'}),
    jsonEncode({
      'detail': {'message': 'internal code', 'stack': 'secret'},
    }),
  ]) {
    test('server failure hides diagnostics: $body', () async {
      final api = client((_) => http.Response(body, 500));
      await expectLater(
        api.get('/farms'),
        throwsA(
          message(
            'El servicio no está disponible en este momento. Intenta de nuevo más tarde.',
          ),
        ),
      );
    });
  }

  test('404 uses a Spanish recovery message', () async {
    final api = client((_) => http.Response('{"detail":"Not Found"}', 404));
    await expectLater(
      api.get('/farms'),
      throwsA(
        message(
          'No encontramos la información solicitada. Actualiza e intenta de nuevo.',
        ),
      ),
    );
  });

  test('validation payload never displays field data or raw objects', () async {
    final api = client(
      (_) => http.Response(
        jsonEncode({
          'detail': [
            {
              'loc': ['body', 'password'],
              'input': 'secret',
            },
          ],
        }),
        422,
      ),
    );
    await expectLater(
      api.get('/farms'),
      throwsA(message('Revisa los datos ingresados e intenta nuevamente.')),
    );
  });

  test('known login rejection remains actionable', () async {
    final api = client(
      (_) => http.Response(
        jsonEncode({'detail': 'Correo o contraseña incorrectos.'}),
        401,
        headers: {'content-type': 'application/json; charset=utf-8'},
      ),
    );
    await expectLater(
      api.postPublic('/auth/login', {}),
      throwsA(message('Correo o contraseña incorrectos.')),
    );
  });

  test('invalid JSON success becomes a friendly failure', () async {
    final api = client((_) => http.Response('<html>proxy failure</html>', 200));
    await expectLater(
      api.get('/farms'),
      throwsA(
        message(
          'No se pudo interpretar la respuesta del servidor. Intenta nuevamente.',
        ),
      ),
    );
  });

  test('wrong object shape becomes a friendly failure', () async {
    final api = client((_) => http.Response('[]', 200));
    await expectLater(
      api.postPublic('/auth/login', {}),
      throwsA(
        message(
          'No se pudo interpretar la respuesta del servidor. Intenta nuevamente.',
        ),
      ),
    );
  });

  test('connection failures hide transport details', () async {
    final api = client(
      (_) => throw http.ClientException('SocketException private IP'),
    );
    await expectLater(
      api.get('/farms'),
      throwsA(
        message('No se pudo conectar con el servidor. Revisa tu conexión.'),
      ),
    );
  });

  test('timeout failures offer a retry', () async {
    final api = client((_) => throw TimeoutException('technical timeout'));
    await expectLater(
      api.get('/farms'),
      throwsA(
        message(
          'El servidor tardó demasiado en responder. Intenta nuevamente.',
        ),
      ),
    );
  });

  test('missing session requests login without sending a request', () async {
    final api = ApiClient(
      httpClient: MockClient(
        (_) => throw StateError('Request must not be sent'),
      ),
      baseUrl: 'https://api.example.com',
      tokenProvider: () => null,
    );
    addTearDown(api.close);
    await expectLater(api.get('/farms'), throwsA(isA<ApiAuthException>()));
  });
}
