# app/config/image_analysis_config.py

"""
Configuración para análisis de imágenes y validación de calidad
"""

# Configuración de calidad de imagen
IMAGE_QUALITY_CONFIG = {
    # Umbrales para validación de calidad (MÁS ESTRICTOS)
    "nitidez_minima": 60.0,          # Más estricto (antes 50.0)
    "brillo_minimo": 40.0,           # Más estricto (antes 30.0)
    "brillo_maximo": 220.0,          # Más estricto (antes 240.0)
    "contraste_minimo": 25.0,        # Más estricto (antes 20.0)
    
    # Dimensiones de imagen
    "dimension_minima": 200,         # Más estricto (antes 100)
    "relacion_aspecto_maxima": 4.0,  # Más estricto (antes 5.0)
    
    # Variación para detectar imágenes uniformes
    "variacion_minima": 15.0,        # Más estricto (antes 10.0)
}

# Configuración de compresión inteligente
COMPRESSION_CONFIG = {
    "etiqueta_nutricional": {
        "max_dimension": 1400,       # Más resolución (antes 1200)
        "quality": 90,               # Más calidad (antes 85)
        "enhance_contrast": True,    # Mejorar contraste si es necesario
    },
    "standard": {
        "max_dimension": 800,
        "quality": 60,               # Mejorado (antes 50)
        "enhance_contrast": False,
    }
}

# Configuración de validación cruzada
VALIDATION_CONFIG = {
    "confidence_threshold": 0.90,              # 90% confianza mínima
    "minimum_confidence_for_critical": 0.90,   # 90% para restricciones críticas
    "max_retries": 3,                          # 3 intentos
    "retry_delay": 1.0,                        # Segundos entre intentos
    "critical_restrictions": ["sin_gluten", "sin_frutos_secos", "vegano", "sin lactosa"]  # Restricciones críticas
}

# Mensajes de error personalizables (SINCRONIZADOS CON FRONTEND)
ERROR_MESSAGES = {
    "invalid_image": "La imagen no parece ser una etiqueta nutricional válida",
    "poor_quality": "La imagen está borrosa o tiene mala calidad", 
    "no_label_detected": "No se pudo detectar información nutricional en la imagen",
    "low_confidence": "El análisis no tiene suficiente confianza para ser preciso",
    "api_error": "Error interno del servidor",
    "timeout": "El análisis está tomando demasiado tiempo. Intenta con una imagen más clara.",
    "rate_limit": "Has alcanzado el límite de solicitudes por minuto",
    "network_error": "Error de conexión a internet"
}

# Instrucciones específicas para cada tipo de error (NUEVO)
ERROR_INSTRUCTIONS = {
    "invalid_image": "Toma una foto de la etiqueta nutricional de un producto alimenticio",
    "poor_quality": "Asegúrate de que la imagen esté bien enfocada y con buena iluminación",
    "no_label_detected": "Enfócate en la sección de información nutricional del producto", 
    "low_confidence": "Toma una foto más clara y directa de la etiqueta",
    "api_error": "Intenta nuevamente en unos momentos",
    "timeout": "Usa una imagen más pequeña o con mejor calidad",
    "rate_limit": "Espera un momento antes de intentar nuevamente",
    "network_error": "Verifica tu conexión a internet e intenta nuevamente"
}

# Configuración de logging
LOGGING_CONFIG = {
    "level": "INFO",
    "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    "log_image_metrics": True,       # Registrar métricas de calidad
    "log_analysis_time": True,       # Registrar tiempo de análisis
}
