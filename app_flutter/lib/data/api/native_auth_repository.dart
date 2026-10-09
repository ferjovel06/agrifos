import 'dart:async';

import 'package:http/http.dart' as http;

import 'package:app_flutter/domain/entities/app_user.dart';
import 'package:app_flutter/domain/entities/mfa_enrollment.dart';
import 'package:app_flutter/core/env.dart';

import 'api_client.dart';
import 'auth_repository.dart';

class NativeAuthRepository extends AuthRepository {
  final ApiClient _api;
  late final ApiClient _sessionApi;
  final http.Client _http;
  final StreamController<AuthEvent> _events = StreamController.broadcast();
  final String? _baseUrl;
  AppUser? _user;
  String? _token;
  String? _challengeId;
  DateTime? _expiresAt;
  DateTime? _challengeExpiresAt;
  Timer? _expiryTimer;
  bool _mfaVerified = false;
  int _generation = 0;
  StreamSubscription<Uri>? _linkSubscription;
  String? _recoveryToken;
  String? _linkError;

  factory NativeAuthRepository({
    http.Client? httpClient,
    String? baseUrl,
    Stream<Uri>? authLinks,
  }) {
    final repository = NativeAuthRepository._(
      httpClient ?? http.Client(),
      baseUrl,
    );
    repository._linkSubscription = authLinks?.listen((uri) {
      repository.handleAuthLink(uri).catchError((Object error) {
        if (repository._events.isClosed) return;
        repository._linkError = error is AuthException
            ? error.message
            : 'No se pudo abrir el enlace de acceso.';
        repository._events.add(AuthEvent.error);
      });
    });
    return repository;
  }

  NativeAuthRepository._(http.Client client, String? baseUrl)
    : _http = client,
      _api = ApiClient(httpClient: client, baseUrl: baseUrl),
      _baseUrl = baseUrl {
    _sessionApi = ApiClient(
      httpClient: _http,
      baseUrl: baseUrl,
      tokenProvider: () => accessToken,
    );
  }

  @override
  AppUser? get currentUser => _user;
  @override
  String? get accessToken =>
      _expiresAt?.isAfter(DateTime.now()) == true ? _token : null;
  @override
  Stream<AuthEvent> get authStateChanges => _events.stream;
  @override
  bool get requiresMfaVerification => _challengeId != null;
  @override
  bool get hasVerifiedMfaFactor => _mfaVerified;
  @override
  bool get supportsAccountManagement => true;
  @override
  int get passwordMinLength => Env.authPasswordMinLength;
  @override
  String? get authErrorMessage => _linkError;

  Future<T> _request<T>(Future<T> Function() request) async {
    try {
      return await request();
    } on ApiException catch (error) {
      throw AuthException(error.message);
    } on ApiAuthException catch (error) {
      throw AuthException(error.message);
    }
  }

  @override
  Future<bool> signUp({
    required String name,
    required String email,
    required String password,
    String role = 'farmer',
  }) async {
    await _request(
      () => _api.postPublic('/auth/register', {
        'name': name.trim(),
        'email': email.trim(),
        'password': password,
      }),
    );
    return true;
  }

  @override
  Future<void> sendPasswordReset(String email) async {
    await _request(
      () => _api.postPublic('/auth/password/forgot', {'email': email.trim()}),
    );
  }

  @override
  Future<void> resendEmailConfirmation(String email) async {
    await _request(
      () => _api.postPublic('/auth/email/resend', {'email': email.trim()}),
    );
  }

  Future<void> handleAuthLink(Uri uri) async {
    final expected = Uri.parse(Env.authRedirectUrl);
    if (uri.scheme != expected.scheme ||
        uri.host != expected.host ||
        uri.path != expected.path) {
      return;
    }
    final token = uri.queryParameters['token'];
    if (token == null || token.length < 32 || token.length > 128) return;
    switch (uri.queryParameters['type']) {
      case 'recovery':
        _clearSession();
        _recoveryToken = token;
        _events.add(AuthEvent.passwordRecovery);
      case 'confirmation':
        final generation = _generation;
        await _request(
          () => _api.postPublic('/auth/email/confirm', {'token': token}),
        );
        if (generation != _generation) return;
        _events.add(AuthEvent.emailConfirmed);
    }
  }

  @override
  Future<void> updatePassword({
    String? currentPassword,
    required String newPassword,
  }) async {
    if (currentPassword != null) {
      await _request(
        () => _sessionApi.post('/auth/password/change', {
          'current_password': currentPassword,
          'new_password': newPassword,
        }),
      );
      await signOut();
    } else {
      if (_recoveryToken == null) {
        throw AuthException('Solicita un nuevo enlace de recuperación.');
      }
      await _request(
        () => _api.postPublic('/auth/password/reset', {
          'token': _recoveryToken,
          'new_password': newPassword,
        }),
      );
      _recoveryToken = null;
    }
  }

  @override
  Future<MfaEnrollment> beginMfaEnrollment() async {
    final result = await _request(
      () => _sessionApi.post('/auth/mfa/enroll', {}),
    );
    return MfaEnrollment(
      factorId: result['factor_id'] as String,
      qrCode: result['qr_code'] as String,
      secret: result['secret'] as String,
    );
  }

  @override
  Future<void> confirmMfaEnrollment({
    required String factorId,
    required String code,
  }) async {
    final generation = _generation;
    final result = await _request(
      () => _sessionApi.post('/auth/mfa/enroll/confirm', {
        'factor_id': factorId,
        'code': code,
      }),
    );
    await _request(() => _openSession(result, generation, mfaVerified: true));
  }

  @override
  Future<void> cancelMfaEnrollment(String factorId) =>
      _request(() => _sessionApi.delete('/auth/mfa/enroll/$factorId'));

  @override
  Future<void> disableMfa() async {
    final generation = _generation;
    final result = await _request(
      () => _sessionApi.post('/auth/mfa/disable', {}),
    );
    await _request(
      () => _openSession(
        result,
        generation,
        mfaVerified: false,
        event: AuthEvent.changed,
      ),
    );
  }

  @override
  Future<void> signIn({required String email, required String password}) async {
    _clearSession();
    final generation = _generation;
    try {
      final response = await _api.postPublic('/auth/login', {
        'email': email.trim(),
        'password': password,
      });
      if (generation != _generation) return;
      if (response['mfa_required'] == true) {
        final challenge = response['challenge_id'];
        final lifetime = _lifetime(response);
        if (challenge is! String || challenge.isEmpty) {
          throw AuthException('La respuesta de acceso no es válida.');
        }
        _challengeId = challenge;
        _challengeExpiresAt = DateTime.now().add(lifetime);
        _events.add(AuthEvent.changed);
      } else {
        await _openSession(response, generation, mfaVerified: false);
      }
    } on ApiException catch (error) {
      throw AuthException(error.message);
    }
  }

  @override
  Future<void> verifyMfa(String code) async {
    if (_challengeId == null ||
        _challengeExpiresAt?.isAfter(DateTime.now()) != true) {
      await signOut();
      throw AuthException('La verificación venció. Inicia sesión de nuevo.');
    }
    final generation = _generation;
    try {
      final response = await _api.postPublic('/auth/mfa/verify', {
        'challenge_id': _challengeId,
        'code': code,
      });
      await _openSession(response, generation, mfaVerified: true);
    } on ApiException catch (error) {
      throw AuthException(error.message);
    }
  }

  Duration _lifetime(Map<String, dynamic> response) {
    final seconds = response['expires_in'];
    if (seconds is! int || seconds <= 0) {
      throw AuthException('La respuesta de acceso no es válida.');
    }
    return Duration(seconds: seconds);
  }

  Future<void> _openSession(
    Map<String, dynamic> response,
    int generation, {
    required bool mfaVerified,
    AuthEvent event = AuthEvent.signedIn,
  }) async {
    if (generation != _generation) return;
    final token = response['access_token'];
    if (token is! String ||
        token.isEmpty ||
        response['token_type'] != 'bearer') {
      throw AuthException('La respuesta de acceso no es válida.');
    }
    final expiresAt = DateTime.now().add(_lifetime(response));
    final profileApi = ApiClient(
      httpClient: _http,
      baseUrl: _baseUrl,
      tokenProvider: () => token,
    );
    final profile = await profileApi.get('/users/me') as Map<String, dynamic>;
    if (generation != _generation) return;
    if (!expiresAt.isAfter(DateTime.now())) {
      throw AuthException('Tu sesión venció. Inicia sesión de nuevo.');
    }
    _user = AppUser(
      id: profile['id'] as String,
      email: profile['email'] as String,
      name: profile['name'] as String?,
      role: profile['role'] as String?,
    );
    _token = token;
    _expiresAt = expiresAt;
    _mfaVerified = mfaVerified;
    _challengeId = null;
    _challengeExpiresAt = null;
    _expiryTimer?.cancel();
    _expiryTimer = Timer(expiresAt.difference(DateTime.now()), signOut);
    _events.add(event);
  }

  @override
  Future<bool> hasMfaEnabled() async {
    final result = await _request(() => _sessionApi.get('/auth/mfa/status'));
    return result['enabled'] == true;
  }

  @override
  Future<void> updateNameMetadata(String name) async {
    if (_user == null || accessToken == null) {
      throw AuthException('Tu sesión venció. Inicia sesión de nuevo.');
    }
    // The profile screen already saves the name through PATCH /users/me.
    _user = AppUser(
      id: _user!.id,
      email: _user!.email,
      name: name.trim(),
      role: _user!.role,
    );
    _events.add(AuthEvent.changed);
  }

  @override
  Future<void> signOut() async {
    _clearSession();
    _events.add(AuthEvent.changed);
  }

  void _clearSession() {
    _generation++;
    _expiryTimer?.cancel();
    _token = null;
    _expiresAt = null;
    _user = null;
    _challengeId = null;
    _challengeExpiresAt = null;
    _mfaVerified = false;
    _recoveryToken = null;
  }

  @override
  void dispose() {
    _generation++;
    _expiryTimer?.cancel();
    _api.close();
    _linkSubscription?.cancel();
    _events.close();
  }
}
