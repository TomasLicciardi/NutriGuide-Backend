# app/config/image_analysis_config.py
"""
Configuración centralizada para análisis de imágenes, pipeline multi-fuente y tiers.

Fuente única de verdad para pesos de tiers, umbrales y parámetros del pipeline.
"""

IMAGE_QUALITY_CONFIG = {
    "nitidez_minima": 60.0,
    "brillo_minimo": 40.0,
    "brillo_maximo": 220.0,
    "contraste_minimo": 25.0,
    "dimension_minima": 200,
    "relacion_aspecto_maxima": 4.0,
    "variacion_minima": 15.0,
}

COMPRESSION_CONFIG = {
    "etiqueta_nutricional": {
        "max_dimension": 1400,
        "quality": 90,
        "enhance_contrast": True,
    },
    "standard": {
        "max_dimension": 800,
        "quality": 60,
        "enhance_contrast": False,
    }
}

# ═══════════════════════════════════════════════════════════════════════════════
# Knowledge Base — Control de calidad
# ═══════════════════════════════════════════════════════════════════════════════
KB_CONFIG = {
    "min_write_confidence": 0.75,
    "min_confidence_for_override": 0.85,
}

ERROR_MESSAGES = {
    "invalid_image": "La imagen no parece ser una etiqueta nutricional válida",
    "poor_quality": "La imagen está borrosa o tiene mala calidad",
    "no_ingredients": "No se pudo encontrar la lista de ingredientes",
    "low_confidence": "El análisis no tiene suficiente confianza para ser preciso",
    "api_error": "Error interno del servidor",
    "timeout": "El análisis está tomando demasiado tiempo. Intenta con una imagen más clara.",
    "network_error": "Error de conexión a internet",
}

ERROR_INSTRUCTIONS = {
    "invalid_image": "Toma una foto de la etiqueta nutricional de un producto alimenticio",
    "poor_quality": "Asegúrate de que la imagen esté bien enfocada y con buena iluminación",
    "no_ingredients": "Enfócate en la sección de ingredientes del producto",
    "low_confidence": "Toma una foto más clara y directa de la etiqueta",
    "api_error": "Intenta nuevamente en unos momentos",
    "timeout": "Usa una imagen más pequeña o con mejor calidad",
    "network_error": "Verifica tu conexión a internet e intenta nuevamente",
}
