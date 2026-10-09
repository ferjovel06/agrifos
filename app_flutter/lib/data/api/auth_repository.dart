import 'package:app_flutter/domain/entities/app_user.dart';
import 'package:app_flutter/domain/entities/mfa_enrollment.dart';

class AuthException implements Exception {
  final String message;
  AuthException(this.message);
}

enum AuthEvent { changed, signedIn, passwordRecovery, emailConfirmed, error }

abstract class AuthRepository {
  AppUser? get currentUser;
  String? get accessToken;
  Stream<AuthEvent> get authStateChanges;
  bool get requiresMfaVerification;
  bool get hasVerifiedMfaFactor;
  bool get supportsAccountManagement => false;
  bool get supportsSessionPersistence => false;
  int get passwordMinLength => 8;
  String? get authErrorMessage => null;

  Future<void> signIn({required String email, required String password});
  Future<void> verifyMfa(String code);
  Future<void> signOut();
  Future<bool> hasMfaEnabled();
  Future<void> updateNameMetadata(String name);
  void dispose() {}

  Never _unavailable() =>
      throw AuthException('Esta función todavía no está disponible.');

  Future<bool> signUp({
    required String name,
    required String email,
    required String password,
    String role = 'farmer',
  }) async => _unavailable();
  Future<MfaEnrollment> beginMfaEnrollment() async => _unavailable();
  Future<void> confirmMfaEnrollment({
    required String factorId,
    required String code,
  }) async => _unavailable();
  Future<void> cancelMfaEnrollment(String factorId) async => _unavailable();
  Future<void> disableMfa() async => _unavailable();
  Future<void> sendPasswordReset(String email) async => _unavailable();
  Future<void> resendEmailConfirmation(String email) async => _unavailable();
  Future<void> updatePassword({
    String? currentPassword,
    required String newPassword,
  }) async => _unavailable();
}
