import 'dart:async';
import 'dart:convert';

import 'package:app_flutter/data/api/api_client.dart';
import 'package:app_flutter/data/api/auth_repository.dart';
import 'package:app_flutter/data/api/native_auth_repository.dart';
import 'package:app_flutter/presentation/auth/auth_provider.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

const profile = {
  'id': 'user-1',
  'email': 'user@example.com',
  'name': 'Test user',
  'role': 'farmer',
};
const session = {
  'access_token': 'native-test-token',
  'token_type': 'bearer',
  'expires_in': 900,
};
const challenge = {
  'mfa_required': true,
  'challenge_id': 'challenge-1',
  'expires_in': 300,
};

http.Response jsonResponse(Object body, [int status = 200]) => http.Response(
  jsonEncode(body),
  status,
  headers: {'content-type': 'application/json; charset=utf-8'},
);

NativeAuthRepository repository(
  FutureOr<http.Response> Function(http.Request) handler,
) => NativeAuthRepository(
  httpClient: MockClient((request) async => handler(request)),
  baseUrl: 'https://api.example.com',
);

void main() {
  test(
    'login loads server-owned profile before publishing the native token',
    () async {
      late NativeAuthRepository auth;
      auth = repository((request) {
        if (request.url.path == '/auth/login') {
          expect(request.headers['Authorization'], isNull);
          expect(jsonDecode(request.body), {
            'email': 'user@example.com',
            'password': 'test-password',
          });
          return jsonResponse(session);
        }
        expect(request.url.path, '/users/me');
        expect(request.headers['Authorization'], 'Bearer native-test-token');
        expect(auth.accessToken, isNull);
        return jsonResponse(profile);
      });
      addTearDown(auth.dispose);
      await auth.signIn(email: ' user@example.com ', password: 'test-password');
      expect(auth.accessToken, 'native-test-token');
      expect(auth.currentUser?.role, 'farmer');
      expect(auth.requiresMfaVerification, false);
      expect(auth.supportsAccountManagement, false);
    },
  );

  test(
    'password challenge keeps user and token absent until OTP succeeds',
    () async {
      final paths = <String>[];
      final auth = repository((request) {
        paths.add(request.url.path);
        switch (request.url.path) {
          case '/auth/login':
            return jsonResponse(challenge);
          case '/auth/mfa/verify':
            expect(request.headers['Authorization'], isNull);
            expect(jsonDecode(request.body), {
              'challenge_id': 'challenge-1',
              'code': '123456',
            });
            return jsonResponse(session);
          default:
            return jsonResponse(profile);
        }
      });
      final provider = AuthProvider(auth);
      addTearDown(provider.dispose);
      await provider.signIn(
        email: 'user@example.com',
        password: 'test-password',
      );
      expect(provider.status, AuthStatus.mfaRequired);
      expect(provider.user, isNull);
      expect(auth.accessToken, isNull);
      expect(paths, ['/auth/login']);
      expect(await provider.verifyMfa('123456'), true);
      expect(provider.status, AuthStatus.authenticated);
      expect(auth.hasVerifiedMfaFactor, true);
      expect(paths, ['/auth/login', '/auth/mfa/verify', '/users/me']);
    },
  );

  for (final status in [401, 429, 503]) {
    test(
      'MFA error $status keeps the challenge and never opens a session',
      () async {
        final auth = repository(
          (request) => request.url.path == '/auth/login'
              ? jsonResponse(challenge)
              : jsonResponse({'detail': 'Verificación rechazada.'}, status),
        );
        final provider = AuthProvider(auth);
        addTearDown(provider.dispose);
        await provider.signIn(
          email: 'user@example.com',
          password: 'test-password',
        );
        expect(await provider.verifyMfa('123456'), false);
        expect(provider.status, AuthStatus.mfaRequired);
        expect(provider.errorMessage, 'Verificación rechazada.');
        expect(auth.accessToken, isNull);
        expect(auth.currentUser, isNull);
      },
    );
  }

  test('profile rejection does not retain a login token', () async {
    final auth = repository(
      (request) => request.url.path == '/auth/login'
          ? jsonResponse(session)
          : jsonResponse({'detail': 'Acceso denegado.'}, 403),
    );
    addTearDown(auth.dispose);
    await expectLater(
      auth.signIn(email: 'user@example.com', password: 'test-password'),
      throwsA(isA<AuthException>()),
    );
    expect(auth.accessToken, isNull);
    expect(auth.currentUser, isNull);
  });

  test('logout clears a pending MFA challenge', () async {
    final auth = repository((_) => jsonResponse(challenge));
    final provider = AuthProvider(auth);
    addTearDown(provider.dispose);
    await provider.signIn(email: 'user@example.com', password: 'test-password');
    await provider.signOut();
    expect(provider.status, AuthStatus.idle);
    expect(auth.requiresMfaVerification, false);
    expect(await provider.verifyMfa('123456'), false);
    expect(provider.status, AuthStatus.idle);
  });

  test('a response arriving after logout cannot recreate a session', () async {
    final reply = Completer<http.Response>();
    final requested = Completer<void>();
    final auth = repository((_) {
      requested.complete();
      return reply.future;
    });
    addTearDown(auth.dispose);
    final login = auth.signIn(
      email: 'user@example.com',
      password: 'test-password',
    );
    await requested.future;
    await auth.signOut();
    reply.complete(jsonResponse(session));
    await login;
    expect(auth.accessToken, isNull);
    expect(auth.currentUser, isNull);
  });

  testWidgets('expiry returns the provider to login and removes the token', (
    tester,
  ) async {
    final auth = repository(
      (request) => jsonResponse(
        request.url.path == '/auth/login'
            ? {...session, 'expires_in': 1}
            : profile,
      ),
    );
    final provider = AuthProvider(auth);
    addTearDown(provider.dispose);
    await provider.signIn(email: 'user@example.com', password: 'test-password');
    expect(provider.status, AuthStatus.authenticated);
    await tester.pump(const Duration(seconds: 2));
    expect(provider.status, AuthStatus.idle);
    expect(auth.accessToken, isNull);
    expect(provider.user, isNull);
  });

  test(
    'protected API requests use the configured session and fail after logout',
    () async {
      final auth = repository(
        (request) =>
            jsonResponse(request.url.path == '/auth/login' ? session : profile),
      );
      addTearDown(auth.dispose);
      ApiClient.defaultTokenProvider = () => auth.accessToken;
      addTearDown(() => ApiClient.defaultTokenProvider = () => null);
      final client = ApiClient(
        baseUrl: 'https://api.example.com',
        httpClient: MockClient((request) async {
          expect(request.headers['Authorization'], 'Bearer native-test-token');
          return jsonResponse([]);
        }),
      );
      addTearDown(client.close);
      await auth.signIn(email: 'user@example.com', password: 'test-password');
      await client.get('/farms');
      await auth.signOut();
      await expectLater(client.get('/farms'), throwsA(isA<ApiAuthException>()));
    },
  );

  test(
    'connection errors are shown in Spanish without starting a session',
    () async {
      final auth = repository(
        (_) => throw http.ClientException('private transport detail'),
      );
      final provider = AuthProvider(auth);
      addTearDown(provider.dispose);
      expect(
        await provider.signIn(
          email: 'user@example.com',
          password: 'test-password',
        ),
        false,
      );
      expect(
        provider.errorMessage,
        'No se pudo conectar con el servidor. Revisa tu conexión.',
      );
      expect(auth.accessToken, isNull);
    },
  );
}
