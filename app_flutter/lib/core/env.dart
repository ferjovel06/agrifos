import 'package:flutter_dotenv/flutter_dotenv.dart';

class Env {
  static String get authRedirectUrl => dotenv.get(
    'AUTH_REDIRECT_URL',
    fallback: 'dev.agrifos.agrifos://auth-callback/',
  );
  static int get authPasswordMinLength =>
      int.parse(dotenv.get('AUTH_PASSWORD_MIN_LENGTH', fallback: '12'));
  static String get authProvider {
    const override = String.fromEnvironment('AUTH_PROVIDER');
    final value = override.isNotEmpty
        ? override
        : dotenv.get('AUTH_PROVIDER', fallback: 'supabase');
    if (value != 'native' && value != 'supabase') {
      throw StateError('AUTH_PROVIDER must be native or supabase.');
    }
    return value;
  }

  static String get supabaseUrl => dotenv.get('SUPABASE_URL');
  static String get supabasePublishableKey =>
      dotenv.get('SUPABASE_PUBLISHABLE_KEY');

  /// Base URL of the Agrifos FastAPI backend, e.g. https://api.agrifos.com
  static String get apiBaseUrl {
    const override = String.fromEnvironment('API_BASE_URL');
    return override.isNotEmpty ? override : dotenv.get('API_BASE_URL');
  }
}
