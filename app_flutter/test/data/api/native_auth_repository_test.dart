import 'dart:async';
import 'dart:convert';

import 'package:app_flutter/data/api/api_client.dart';
import 'package:app_flutter/data/api/auth_repository.dart';
import 'package:app_flutter/data/api/native_auth_repository.dart';
import 'package:app_flutter/presentation/auth/auth_provider.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_dotenv/flutter_dotenv.dart';
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
  setUp(
    () => dotenv.loadFromString(
      envString:
          'AUTH_REDIRECT_URL=dev.agrifos.agrifos://auth-callback/\nAUTH_PASSWORD_MIN_LENGTH=12',
    ),
  );

  test(
    'registration uses native endpoint and never sends a client-selected role',
    () async {
      final auth = repository((request) {
        expect(request.url.path, '/auth/register');
        expect(request.headers['Authorization'], isNull);
        expect(jsonDecode(request.body), {
          'name': 'Test user',
          'email': 'user@example.com',
          'password': 'Test-password-123',
        });
        return jsonResponse({'message': 'Revisa tu correo.'}, 202);
      });
      final provider = AuthProvider(auth);
      addTearDown(provider.dispose);
      expect(
        await provider.signUp(
          name: 'Test user',
          email: 'user@example.com',
          password: 'Test-password-123',
          role: 'admin',
        ),
        true,
      );
      expect(provider.status, AuthStatus.emailConfirmationPending);
      expect(auth.accessToken, isNull);
      expect(provider.passwordMinLength, 12);
      expect(provider.supportsSessionPersistence, false);
    },
  );

  test(
    'recovery link opens recovery without a session and posts a one-use proof',
    () async {
      final token = 'a' * 43;
      final auth = repository((request) {
        expect(request.url.path, '/auth/password/reset');
        expect(jsonDecode(request.body), {
          'token': token,
          'new_password': 'New-password-123',
        });
        expect(request.headers['Authorization'], isNull);
        return http.Response('', 204);
      });
      final provider = AuthProvider(auth);
      addTearDown(provider.dispose);
      await auth.handleAuthLink(
        Uri.parse(
          'dev.agrifos.agrifos://auth-callback/?type=recovery&token=$token',
        ),
      );
      await Future<void>.delayed(Duration.zero);
      expect(provider.status, AuthStatus.passwordRecovery);
      expect(provider.user, isNull);
      expect(auth.accessToken, isNull);
      expect(await provider.updateRecoveredPassword('New-password-123'), true);
      await provider.completePasswordRecoveryFlow();
      expect(provider.status, AuthStatus.idle);
      await expectLater(
        auth.updatePassword(newPassword: 'New-password-123'),
        throwsA(isA<AuthException>()),
      );
    },
  );

  test(
    'confirmation link returns pending signup to login without publishing a token',
    () async {
      final auth = repository((request) {
        if (request.url.path == '/auth/register') return jsonResponse({}, 202);
        expect(request.url.path, '/auth/email/confirm');
        return http.Response('', 204);
      });
      final provider = AuthProvider(auth);
      addTearDown(provider.dispose);
      await provider.signUp(
        name: 'Test user',
        email: 'user@example.com',
        password: 'Test-password-123',
      );
      await auth.handleAuthLink(
        Uri.parse(
          'dev.agrifos.agrifos://auth-callback/?type=confirmation&token=${'a' * 43}',
        ),
      );
      await Future<void>.delayed(Duration.zero);
      expect(provider.status, AuthStatus.idle);
      expect(provider.emailConfirmationRequired, false);
      expect(auth.accessToken, isNull);
    },
  );

  test('foreign hosts, paths and malformed link tokens are ignored', () async {
    final auth = repository((_) => throw StateError('Unexpected HTTP request'));
    final provider = AuthProvider(auth);
    addTearDown(provider.dispose);
    for (final uri in [
      'https://example.com/auth-callback/?type=recovery&token=${'a' * 43}',
      'dev.agrifos.agrifos://other-host/?type=recovery&token=${'a' * 43}',
      'dev.agrifos.agrifos://auth-callback/other?type=recovery&token=${'a' * 43}',
      'dev.agrifos.agrifos://auth-callback/?type=recovery&token=short',
    ]) {
      await auth.handleAuthLink(Uri.parse(uri));
    }
    await Future<void>.delayed(Duration.zero);
    expect(provider.status, AuthStatus.idle);
  });

  test(
    'password change attaches the native token and closes the local session',
    () async {
      final auth = repository((request) {
        if (request.url.path == '/auth/login') return jsonResponse(session);
        if (request.url.path == '/users/me') return jsonResponse(profile);
        expect(request.url.path, '/auth/password/change');
        expect(request.headers['Authorization'], 'Bearer native-test-token');
        return http.Response('', 204);
      });
      final provider = AuthProvider(auth);
      addTearDown(provider.dispose);
      await provider.signIn(
        email: 'user@example.com',
        password: 'Test-password-123',
      );
      expect(
        await provider.updatePassword(
          currentPassword: 'Test-password-123',
          newPassword: 'New-password-123',
        ),
        true,
      );
      expect(provider.status, AuthStatus.idle);
      expect(auth.accessToken, isNull);
    },
  );

  test(
    'MFA enrollment and disable replace session tokens without reoffering enrollment',
    () async {
      final auth = repository((request) {
        switch (request.url.path) {
          case '/auth/login':
            return jsonResponse(session);
          case '/users/me':
            return jsonResponse(profile);
          case '/auth/mfa/enroll':
            return jsonResponse({
              'factor_id': 'factor-1',
              'qr_code': '<svg/>',
              'secret': 'TEST-SECRET',
            });
          case '/auth/mfa/enroll/confirm':
            return jsonResponse({...session, 'access_token': 'elevated-token'});
          case '/auth/mfa/disable':
            expect(request.headers['Authorization'], 'Bearer elevated-token');
            return jsonResponse({
              ...session,
              'access_token': 'replacement-token',
            });
          default:
            throw StateError('Unexpected request');
        }
      });
      final provider = AuthProvider(auth);
      addTearDown(provider.dispose);
      await provider.signIn(
        email: 'user@example.com',
        password: 'Test-password-123',
      );
      final enrollment = await provider.beginMfaEnrollment();
      expect(enrollment?.factorId, 'factor-1');
      expect(
        await provider.confirmMfaEnrollment(
          factorId: 'factor-1',
          code: '123456',
        ),
        true,
      );
      expect(auth.accessToken, 'elevated-token');
      expect(await provider.disableMfa(), true);
      await Future<void>.delayed(Duration.zero);
      expect(auth.accessToken, 'replacement-token');
      expect(provider.status, AuthStatus.authenticated);
      expect(provider.mfaEnabled, false);
    },
  );
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
      expect(auth.supportsAccountManagement, true);
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
    expect(provider.status, AuthStatus.mfaEnrollmentOffered);
    await provider.skipMfaEnrollment();
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
