/// Only recognized business messages may cross the API/UI boundary.
String apiErrorMessage(int status, Object? detail) {
  if (status == 408 || status == 504) {
    return 'El servidor tardó demasiado en responder. Intenta nuevamente.';
  }
  if (status >= 500) {
    return 'El servicio no está disponible en este momento. Intenta de nuevo más tarde.';
  }
  if (detail is Map && detail['code'] == 'mfa_required') {
    return 'Completa la verificación en dos pasos para continuar.';
  }
  const businessMessages = {
    'Correo o contraseña incorrectos.',
    'Esta cuenta no puede iniciar sesión.',
    'Confirma tu correo antes de iniciar sesión.',
    'Tu sesión venció. Inicia sesión de nuevo.',
    'Completa la verificación en dos pasos.',
    'Verifica el segundo factor antes de desactivarlo.',
    'El código no es válido o ya fue utilizado.',
    'La verificación venció o no es válida. Inicia sesión de nuevo.',
    'El enlace venció o ya fue utilizado. Solicita uno nuevo.',
    'Demasiados intentos. Intenta de nuevo más tarde.',
    'Demasiados intentos de verificación. Intenta de nuevo más tarde.',
    'El nombre debe tener al menos dos caracteres.',
    'La nueva contraseña debe ser diferente de la anterior.',
  };
  if (detail is String && businessMessages.contains(detail)) return detail;
  if (detail is String &&
      RegExp(
        r'^La contraseña debe tener al menos [0-9]+ caracteres\.$',
      ).hasMatch(detail)) {
    return detail;
  }
  return switch (status) {
    401 => 'Tu sesión venció o no es válida. Inicia sesión de nuevo.',
    403 => 'No tienes permiso para realizar esta acción.',
    404 =>
      'No encontramos la información solicitada. Actualiza e intenta de nuevo.',
    409 =>
      'La información cambió o ya existe. Actualiza antes de intentarlo de nuevo.',
    400 || 422 => 'Revisa los datos ingresados e intenta nuevamente.',
    429 =>
      'Demasiados intentos. Espera unos minutos antes de intentar de nuevo.',
    _ => 'No se pudo completar la solicitud. Intenta nuevamente.',
  };
}
