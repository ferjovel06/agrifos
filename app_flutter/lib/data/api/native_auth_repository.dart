import 'dart:async';

import 'package:http/http.dart' as http;

import 'package:app_flutter/domain/entities/app_user.dart';

import 'api_client.dart';
import 'auth_repository.dart';

class NativeAuthRepository extends AuthRepository {
  final ApiClient _api;
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

  factory NativeAuthRepository({http.Client? httpClient, String? baseUrl}) {
    return NativeAuthRepository._(httpClient ?? http.Client(), baseUrl);
  }

  NativeAuthRepository._(http.Client client, String? baseUrl)
    : _http = client,
      _api = ApiClient(httpClient: client, baseUrl: baseUrl),
      _baseUrl = baseUrl;

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
    _events.add(AuthEvent.signedIn);
  }

  @override
  Future<bool> hasMfaEnabled() async => _mfaVerified;

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
  }

  @override
  void dispose() {
    _generation++;
    _expiryTimer?.cancel();
    _api.close();
    _events.close();
  }
}
