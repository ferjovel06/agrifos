import 'dart:convert';
import 'package:cryptography/cryptography.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

class SecureVault {
  SecureVault(this.namespace, {FlutterSecureStorage? storage})
    : storage = storage ?? const FlutterSecureStorage();
  final String namespace;
  final FlutterSecureStorage storage;
  final Map<String, Future<SecretKey>> _keys = {};
  Future<String?> read(String key) => storage.read(key: '$namespace:$key');
  Future<void> write(String key, String value) =>
      storage.write(key: '$namespace:$key', value: value);
  Future<void> remove(String key) => storage.delete(key: '$namespace:$key');
  Future<SecretKey> key(String account) => _keys.putIfAbsent(account, () async {
    final stored = await read('key:$account');
    if (stored != null) return SecretKey(base64Decode(stored));
    final key = await AesGcm.with256bits().newSecretKey();
    await write('key:$account', base64Encode(await key.extractBytes()));
    return key;
  });
}

class SecureSessionStorage extends LocalStorage {
  SecureSessionStorage(this.vault, this.legacyKey);
  final SecureVault vault;
  final String legacyKey;
  @override
  Future<void> initialize() async {
    final legacy = SharedPreferencesLocalStorage(persistSessionKey: legacyKey);
    await legacy.initialize();
    final old = await legacy.accessToken();
    if (old != null) {
      if (await vault.read('session') == null) {
        await vault.write('session', old);
      }
      // Remove plaintext only after the encrypted write succeeds.
      await legacy.removePersistedSession();
    }
  }

  @override
  Future<bool> hasAccessToken() async => await accessToken() != null;
  @override
  Future<String?> accessToken() => vault.read('session');
  @override
  Future<void> persistSession(String value) => vault.write('session', value);
  @override
  Future<void> removePersistedSession() => vault.remove('session');
}

class SecurePkceStorage extends GotrueAsyncStorage {
  SecurePkceStorage(this.vault);
  final SecureVault vault;
  @override
  Future<String?> getItem({required String key}) => vault.read('pkce:$key');
  @override
  Future<void> setItem({required String key, required String value}) =>
      vault.write('pkce:$key', value);
  @override
  Future<void> removeItem({required String key}) => vault.remove('pkce:$key');
}
