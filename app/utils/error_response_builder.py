# app/utils/error_response_builder.py

"""
Utilidad para construir respuestas de error consistentes que el frontend puede manejar
"""

from app.config.image_analysis_config import ERROR_MESSAGES, ERROR_INSTRUCTIONS
from typing import Dict, Any

def build_error_response(error_type: str, custom_message: str = None, custom_instructions: str = None) -> Dict[str, Any]:
    """
    Construye una respuesta de error estructurada para el frontend
    
    Args:
        error_type: Tipo de error (debe existir en ERROR_MESSAGES)
        custom_message: Mensaje personalizado (opcional)
        custom_instructions: Instrucciones personalizadas (opcional)
    
    Returns:
        Dict con la estructura esperada por el frontend
    """
    return {
        "error": error_type,
        "message": custom_message or ERROR_MESSAGES.get(error_type, "Error desconocido"),
        "instructions": custom_instructions or ERROR_INSTRUCTIONS.get(error_type, "Intenta nuevamente")
    }

def build_image_error_response(error_type: str, image_metrics: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Construye una respuesta de error específica para problemas de imagen
    
    Args:
        error_type: Tipo de error de imagen
        image_metrics: Métricas de calidad de imagen (opcional)
    
    Returns:
        Dict con la estructura esperada por el frontend
    """
    response = build_error_response(error_type)
    
    # Agregar métricas si están disponibles (para debugging)
    if image_metrics:
        response["debug_info"] = {
            "image_metrics": image_metrics,
            "timestamp": __import__("datetime").datetime.now().isoformat()
        }
    
    return response

def build_confidence_error_response(confidence_score: float, threshold: float, is_critical: bool = False) -> Dict[str, Any]:
    """
    Construye una respuesta de error para problemas de confianza
    
    Args:
        confidence_score: Puntuación de confianza obtenida
        threshold: Umbral mínimo requerido
        is_critical: Si es una restricción crítica
    
    Returns:
        Dict con la estructura esperada por el frontend
    """
    restriction_type = "críticas" if is_critical else "normales"
    
    custom_message = f"Confianza del análisis: {confidence_score:.1%}. Se requiere {threshold:.1%} para restricciones {restriction_type}."
    custom_instructions = "Toma una foto más clara de la etiqueta completa con mejor iluminación" if is_critical else "Mejora la calidad de la imagen o toma una nueva foto"
    
    return build_error_response(
        error_type="low_confidence",
        custom_message=custom_message,
        custom_instructions=custom_instructions
    )

def build_api_error_response(original_error: str = None) -> Dict[str, Any]:
    """
    Construye una respuesta de error para problemas de API
    
    Args:
        original_error: Error original de la API (opcional)
    
    Returns:
        Dict con la estructura esperada por el frontend
    """
    response = build_error_response("api_error")
    
    if original_error:
        response["debug_info"] = {
            "original_error": str(original_error),
            "timestamp": __import__("datetime").datetime.now().isoformat()
        }
    
    return response

def build_timeout_error_response(elapsed_time: float = None) -> Dict[str, Any]:
    """
    Construye una respuesta de error para timeouts
    
    Args:
        elapsed_time: Tiempo transcurrido en segundos (opcional)
    
    Returns:
        Dict con la estructura esperada por el frontend
    """
    response = build_error_response("timeout")
    
    if elapsed_time:
        response["debug_info"] = {
            "elapsed_time_seconds": elapsed_time,
            "timestamp": __import__("datetime").datetime.now().isoformat()
        }
    
    return response

def build_rate_limit_error_response(retry_after: int = None) -> Dict[str, Any]:
    """
    Construye una respuesta de error para rate limiting
    
    Args:
        retry_after: Segundos hasta poder reintentar (opcional)
    
    Returns:
        Dict con la estructura esperada por el frontend
    """
    response = build_error_response("rate_limit")
    
    if retry_after:
        response["retry_after"] = retry_after
        response["message"] = f"Has alcanzado el límite de solicitudes. Intenta en {retry_after} segundos."
    
    return response

# Ejemplos de uso:
"""
# Error de imagen inválida
error_response = build_image_error_response("invalid_image", {"nitidez": 45.2, "brillo": 120.5})

# Error de baja confianza
error_response = build_confidence_error_response(0.72, 0.85, is_critical=False)

# Error de API
error_response = build_api_error_response("Connection timeout to Gemini API")

# Error de rate limit
error_response = build_rate_limit_error_response(retry_after=60)
"""
