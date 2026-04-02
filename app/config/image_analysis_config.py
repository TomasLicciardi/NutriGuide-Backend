# app/config/image_analysis_config.py
"""
Configuración centralizada para análisis de imágenes, pipeline multi-fuente y tiers.
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

VALIDATION_CONFIG = {
    "confidence_threshold": 0.70,
    "minimum_confidence_for_critical": 0.90,
    "max_retries": 3,
    "retry_delay": 1.0,
    "critical_restrictions": ["sin_tacc", "sin_frutos_secos"],
}

# 4 restricciones soportadas
SUPPORTED_RESTRICTIONS = {
    "sin_tacc": {
        "name": "Sin TACC",
        "description": "Sin trigo, avena, cebada y centeno",
        "critical": True,
        "confidence_required": 0.90,
    },
    "sin_lactosa": {
        "name": "Sin Lactosa",
        "description": "Sin productos lácteos que contengan lactosa",
        "critical": True,
        "confidence_required": 0.85,
    },
    "sin_frutos_secos": {
        "name": "Sin Frutos Secos",
        "description": "Sin frutos secos ni maní",
        "critical": True,
        "confidence_required": 0.90,
    },
    "vegano": {
        "name": "Vegano",
        "description": "Sin productos de origen animal",
        "critical": False,
        "confidence_required": 0.70,
    },
}

# Pesos de confianza por tier
TIER_WEIGHTS = {
    "allergen_text": 0.98,
    "deterministic": 0.97,
    "knowledge_base": 0.93,
    "openfoodfacts": 0.85,
    "pubchem": 0.75,
    "gemini": 0.65,
}

# Configuración del pipeline
PIPELINE_CONFIG = {
    "max_analysis_time": 45.0,
    "tier_3_5_timeout": 15.0,
    "translation_batch_size": 50,
    "pubchem_max_concurrent": 4,
    "off_rate_limit_per_min": 100,
    "default_unsafe_for_medical": True,
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
