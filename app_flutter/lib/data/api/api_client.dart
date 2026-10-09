import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

import '../../core/env.dart';
import 'api_error_message.dart';

/// Thrown when the backend returns a non-2xx response.
class ApiException implements Exception {
  final int statusCode;
  final String message;
  ApiException(this.statusCode, this.message);

  @override
  String toString() => message;
}

/// Thrown when there is no authenticated session to attach.
class ApiAuthException implements Exception {
  final String message;
  ApiAuthException(this.message);

  @override
  String toString() => message;
}

/// Small wrapper around [http.Client] that talks to the Agrifos FastAPI
/// backend, attaching the current session's JWT as a Bearer token
/// and mapping error responses to [ApiException].
class ApiClient {
  void close() => _http.close();
  static String? Function() defaultTokenProvider = () => null;
  final http.Client _http;
  final String? Function()? tokenProvider;
  final String? baseUrl;

  ApiClient({http.Client? httpClient, this.tokenProvider, this.baseUrl})
    : _http = httpClient ?? http.Client();

  Uri _uri(String path) => Uri.parse('${baseUrl ?? Env.apiBaseUrl}$path');

  Future<Map<String, String>> _headers() async {
    final token = (tokenProvider ?? defaultTokenProvider)();
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

  Future<Map<String, dynamic>> post(
    String path,
    Map<String, dynamic> body,
  ) async => _post(path, body, await _headers());

  Future<Map<String, dynamic>> postPublic(
    String path,
    Map<String, dynamic> body,
  ) async => _post(path, body, {'Content-Type': 'application/json'});

  Future<Map<String, dynamic>> _post(
    String path,
    Map<String, dynamic> body,
    Map<String, String> headers,
  ) async {
    final response = await _send(
      _http.post(_uri(path), headers: headers, body: jsonEncode(body)),
    );
    return _decodeObject(response);
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
    return _decodeObject(response);
  }

  Future<void> delete(String path) async {
    final headers = await _headers();
    final response = await _send(_http.delete(_uri(path), headers: headers));
    _decode(response);
  }

  Future<http.Response> _send(Future<http.Response> request) async {
    try {
      return await request.timeout(const Duration(seconds: 15));
    } on TimeoutException {
      throw ApiException(
        408,
        'El servidor tardó demasiado en responder. Intenta nuevamente.',
      );
    } on http.ClientException {
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
        throw ApiException(
          response.statusCode,
          'No se pudo interpretar la respuesta del servidor. Intenta nuevamente.',
        );
      }
    }

    Object? detail;
    try {
      final decoded = jsonDecode(utf8.decode(response.bodyBytes));
      if (decoded is Map && decoded['detail'] != null) {
        detail = decoded['detail'];
      }
    } catch (_) {
      // response body wasn't JSON, keep the default message
    }
    throw ApiException(
      response.statusCode,
      apiErrorMessage(response.statusCode, detail),
    );
  }

  Map<String, dynamic> _decodeObject(http.Response response) {
    final decoded = _decode(response);
    if (decoded == null) return <String, dynamic>{};
    if (decoded is Map<String, dynamic>) return decoded;
    throw ApiException(
      response.statusCode,
      'No se pudo interpretar la respuesta del servidor. Intenta nuevamente.',
    );
  }
}
