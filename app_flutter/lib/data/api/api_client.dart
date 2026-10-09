import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;
import 'package:supabase_flutter/supabase_flutter.dart';

import '../../core/env.dart';
import '../../core/network_health.dart';

/// Thrown when the backend returns a non-2xx response.
class ApiException implements Exception {
  final int statusCode;
  final String message;
  final String? retryAfter;
  final dynamic detail;
  ApiException(this.statusCode, this.message, {this.retryAfter, this.detail});

  @override
  String toString() => message;
}

/// Thrown when there is no authenticated Supabase session to attach.
class ApiAuthException implements Exception {
  final String message;
  ApiAuthException(this.message);

  @override
  String toString() => message;
}

/// Small wrapper around [http.Client] that talks to the Agrifos FastAPI
/// backend, attaching the current Supabase session's JWT as a Bearer token
/// and mapping error responses to [ApiException].
class ApiClient {
  final http.Client _http;
  final NetworkHealth _network;
  final String? baseUrl;
  final String? Function()? tokenProvider;
  final String? Function()? userProvider;

  ApiClient({
    http.Client? httpClient,
    NetworkHealth? network,
    this.baseUrl,
    this.tokenProvider,
    this.userProvider,
  }) : _http = httpClient ?? http.Client(),
       _network = network ?? NetworkHealth.shared;

  Uri _uri(String path) => Uri.parse('${baseUrl ?? Env.apiBaseUrl}$path');

  Future<Map<String, String>> _headers() async {
    final token = tokenProvider != null
        ? tokenProvider!()
        : Supabase.instance.client.auth.currentSession?.accessToken;
    if (token == null) {
      throw ApiAuthException(
        'No hay una sesión activa. Inicia sesión de nuevo.',
      );
    }
    return {
      'Content-Type': 'application/json',
      'Authorization': 'Bearer $token',
    };
  }

  Future<Map<String, dynamic>> post(String path, Map<String, dynamic> body) =>
      _post(path, body);

  Future<Map<String, dynamic>> postForUser(
    String path,
    Map<String, dynamic> body,
    String user,
  ) => _post(path, body, expectedUser: user);

  Future<Map<String, dynamic>> _post(
    String path,
    Map<String, dynamic> body, {
    String? expectedUser,
  }) async {
    final headers = await _headers();
    if (expectedUser != null &&
        (userProvider != null
                ? userProvider!()
                : Supabase.instance.client.auth.currentUser?.id) !=
            expectedUser) {
      throw ApiAuthException('La cuenta cambió. Se detuvo la sincronización.');
    }
    final response = await _send(
      _http.post(_uri(path), headers: headers, body: jsonEncode(body)),
    );
    final decoded = _decode(response);
    if (decoded is! Map<String, dynamic>) {
      throw ApiException(502, 'El servidor devolvió una confirmación inválida.');
    }
    return decoded;
  }

  Future<dynamic> get(String path, {Map<String, String>? query}) async {
    final headers = await _headers();
    final uri = _uri(path).replace(queryParameters: query);
    final response = await _send(_http.get(uri, headers: headers));
    return _decode(response);
  }

  Future<Map<String, dynamic>> patch(
    String path,
    Map<String, dynamic> body,
  ) async {
    final headers = await _headers();
    final response = await _send(
      _http.patch(_uri(path), headers: headers, body: jsonEncode(body)),
    );
    return _decode(response) as Map<String, dynamic>;
  }

  Future<void> delete(String path) async {
    final headers = await _headers();
    final response = await _send(_http.delete(_uri(path), headers: headers));
    _decode(response);
  }

  Future<http.Response> _send(Future<http.Response> request) async {
    try {
      final response = await request.timeout(const Duration(seconds: 15));
      _network.success();
      return response;
    } on TimeoutException {
      _network.failure();
      throw ApiException(
        408,
        'El servidor tardó demasiado en responder. Intenta nuevamente.',
      );
    } on http.ClientException {
      _network.failure();
      throw ApiException(
        0,
        'No se pudo conectar con el servidor. Revisa tu conexión.',
      );
    }
  }

  dynamic _decode(http.Response response) {
    if (response.statusCode >= 200 && response.statusCode < 300) {
      if (response.body.isEmpty) return null;
      try {
        return jsonDecode(utf8.decode(response.bodyBytes));
      } on FormatException {
        throw ApiException(502, 'El servidor devolvió una respuesta inválida.');
      }
    }

    String message = 'Error del servidor (${response.statusCode}).';
    dynamic detail;
    try {
      final decoded = jsonDecode(utf8.decode(response.bodyBytes));
      if (decoded is Map && decoded['detail'] != null) {
        message = decoded['detail'].toString();
        detail = decoded['detail'];
      }
    } catch (_) {
      // response body wasn't JSON, keep the default message
    }
    throw ApiException(
      response.statusCode,
      message,
      retryAfter: response.headers['retry-after'],
      detail: detail,
    );
  }
}
