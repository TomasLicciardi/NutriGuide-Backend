# app/config/image_analysis_config.py

"""
Configuración para análisis de imágenes, validación de calidad, RAG y embeddings
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
    "confidence_threshold": 0.70,              # 70% confianza mínima normal
    "minimum_confidence_for_critical": 0.90,   # 90% para restricciones críticas  
    "max_retries": 3,                          # 3 intentos
    "retry_delay": 1.0,                        # Segundos entre intentos
    "critical_restrictions": ["sin_gluten", "sin_frutos_secos"]  # Restricciones críticas (alergias)
}

# Configuración RAG y Embeddings (NUEVO)
RAG_CONFIG = {
    "embedding_model": "text-embedding-004",
    "similarity_threshold": 0.3,               # Umbral mínimo de similitud para documentos RAG
    "max_rag_documents": 5,                    # Máximo documentos RAG a incluir
    "max_similar_ingredients": 3,              # Máximo ingredientes similares a buscar
    "ingredient_similarity_threshold": 0.8,    # Umbral para ingredientes similares
    "auto_create_embeddings": True,            # Crear embeddings automáticamente
    "embedding_cache_timeout": 86400,          # Cache de embeddings (24 horas)
}

# Configuración de clasificación de ingredientes (NUEVO)
INGREDIENT_CLASSIFICATION_CONFIG = {
    "base_ingredient_confidence": 0.9,         # Confianza para ingredientes base conocidos
    "additive_confidence": 0.9,                # Confianza para aditivos conocidos
    "default_confidence": 0.6,                 # Confianza por defecto
    "prefer_base_when_uncertain": True,        # Si hay duda, clasificar como BASE
    "save_classification_feedback": True,      # Guardar feedback de clasificación
}

# Configuración de las cinco restricciones soportadas (NUEVO)
SUPPORTED_RESTRICTIONS = {
    "vegano": {
        "name": "Vegano",
        "description": "Sin productos de origen animal",
        "critical": False,
        "confidence_required": 0.70
    },
    "vegetariano": {
        "name": "Vegetariano", 
        "description": "Sin carne ni pescado, permite lácteos y huevos",
        "critical": False,
        "confidence_required": 0.70
    },
    "sin_gluten": {
        "name": "Sin Gluten",
        "description": "Sin trigo, cebada, centeno y avena no certificada",
        "critical": True,  # Es alergia
        "confidence_required": 0.90
    },
    "sin_lactosa": {
        "name": "Sin Lactosa",
        "description": "Sin productos lácteos que contengan lactosa",
        "critical": False,
        "confidence_required": 0.70
    },
    "sin_frutos_secos": {
        "name": "Sin Frutos Secos",
        "description": "Sin frutos secos del árbol",
        "critical": True,  # Es alergia
        "confidence_required": 0.90
    }
}

# Mensajes de error personalizables (SINCRONIZADOS CON FRONTEND)
ERROR_MESSAGES = {
    "invalid_image": "La imagen no parece ser una etiqueta nutricional válida",
    "poor_quality": "La imagen está borrosa o tiene mala calidad", 
    "no_ingredients": "No se pudo encontrar la lista de ingredientes",
    "low_confidence": "El análisis no tiene suficiente confianza para ser preciso",
    "api_error": "Error interno del servidor",
    "timeout": "El análisis está tomando demasiado tiempo. Intenta con una imagen más clara.",
    "rate_limit": "Has alcanzado el límite de solicitudes por minuto",
    "network_error": "Error de conexión a internet",
    "rag_error": "Error obteniendo contexto de conocimiento",
    "embedding_error": "Error generando embeddings semánticos",
    "classification_error": "Error en clasificación de ingredientes"
}

# Instrucciones específicas para cada tipo de error (MEJORADO)
ERROR_INSTRUCTIONS = {
    "invalid_image": "Toma una foto de la etiqueta nutricional de un producto alimenticio",
    "poor_quality": "Asegúrate de que la imagen esté bien enfocada y con buena iluminación",
    "no_ingredients": "Enfócate en la sección de ingredientes del producto", 
    "low_confidence": "Toma una foto más clara y directa de la etiqueta",
    "api_error": "Intenta nuevamente en unos momentos",
    "timeout": "Usa una imagen más pequeña o con mejor calidad",
    "rate_limit": "Espera un momento antes de intentar nuevamente",
    "network_error": "Verifica tu conexión a internet e intenta nuevamente",
    "rag_error": "Error interno, intenta nuevamente",
    "embedding_error": "Error interno procesando ingredientes",
    "classification_error": "Error interno en análisis, intenta nuevamente"
}

# Configuración de logging (MEJORADO)
LOGGING_CONFIG = {
    "level": "INFO",
    "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    "log_image_metrics": True,       # Registrar métricas de calidad
    "log_analysis_time": True,       # Registrar tiempo de análisis
    "log_rag_performance": True,     # Registrar rendimiento RAG
    "log_ingredient_classification": True,  # Registrar clasificación de ingredientes
    "log_embedding_generation": True,      # Registrar generación de embeddings
}

# Configuración de rendimiento (NUEVO)
PERFORMANCE_CONFIG = {
    "max_analysis_time": 30.0,       # Tiempo máximo de análisis (segundos)
    "batch_embedding_size": 10,      # Tamaño de lote para embeddings
    "cache_classification_results": True,  # Cachear resultados de clasificación
    "parallel_processing": True,     # Procesamiento paralelo cuando sea posible
    "memory_limit_mb": 512,         # Límite de memoria para procesamiento
}
