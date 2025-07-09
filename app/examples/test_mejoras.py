# Archivo de ejemplo para probar las mejoras implementadas

import asyncio
import os
from app.services.gemini_service import analizar_imagen
from app.utils.image_tools import analizar_calidad_imagen

async def test_mejoras():
    """
    Ejemplo de cómo usar las nuevas funcionalidades implementadas:
    
    1. Validación de calidad de imagen
    2. Análisis con confianza
    3. Manejo de errores mejorado
    4. Compresión inteligente
    """
    
    # Ejemplo 1: Cargar una imagen para prueba
    # (Reemplaza con la ruta de una imagen real)
    imagen_path = "test_image.jpg"
    
    if os.path.exists(imagen_path):
        with open(imagen_path, 'rb') as f:
            contenido = f.read()
        
        # Ejemplo 2: Analizar calidad antes del procesamiento
        print("=== ANÁLISIS DE CALIDAD ===")
        calidad = analizar_calidad_imagen(contenido)
        print(f"Imagen válida: {calidad['es_valida']}")
        print(f"Nitidez: {calidad['nitidez']}")
        print(f"Brillo: {calidad['brillo']}")
        print(f"Contraste: {calidad['contraste']}")
        print(f"Problemas: {calidad['problemas']}")
        
        # Ejemplo 3: Análisis con restricciones normales
        print("\n=== ANÁLISIS CON RESTRICCIONES NORMALES ===")
        restricciones_normales = ["vegano", "sin_lactosa"]
        resultado = await analizar_imagen(contenido, restricciones_normales)
        
        print(f"Restricciones: {restricciones_normales}")
        print(f"Resultado: {resultado}")
        
        if "error" in resultado:
            print(f"❌ Error detectado: {resultado['error']}")
            print(f"📱 Mensaje: {resultado['message']}")
            print(f"🔧 NOTA: Este error NO se guardará en BD - el frontend debe mostrar modal")
        else:
            print(f"✅ Confianza: {resultado.get('confidence', 'No disponible')}")
            print(f"📝 Ingredientes: {resultado.get('ingredientes', 'No disponible')}")
            print(f"⚠️ Puede contener: {resultado.get('puede_contener', 'No disponible')}")
            print(f"🗄️ NOTA: Este análisis SÍ se guardará en BD")
        
        # Ejemplo 4: Análisis con restricciones CRÍTICAS (requiere 90% confianza)
        print("\n=== ANÁLISIS CON RESTRICCIONES CRÍTICAS ===")
        restricciones_criticas = ["sin_gluten", "sin_frutos_secos"]
        resultado_critico = await analizar_imagen(contenido, restricciones_criticas)
        
        print(f"Restricciones críticas: {restricciones_criticas}")
        print(f"Resultado crítico: {resultado_critico}")
        
        if "error" in resultado_critico:
            print(f"❌ Error detectado: {resultado_critico['error']}")
            print(f"📱 Mensaje: {resultado_critico['message']}")
            print(f"🔧 NOTA: Este error NO se guardará en BD - el frontend debe mostrar modal")
        else:
            print(f"✅ Confianza: {resultado_critico.get('confidence', 'No disponible')}")
            print(f"📝 Ingredientes: {resultado_critico.get('ingredientes', 'No disponible')}")
            print(f"⚠️ Puede contener: {resultado_critico.get('puede_contener', 'No disponible')}")
            print(f"🗄️ NOTA: Este análisis SÍ se guardará en BD")
        
        # Ejemplo 5: Análisis sin restricciones
        print("\n=== ANÁLISIS SIN RESTRICCIONES ===")
        resultado_basico = await analizar_imagen(contenido)
        print(f"Resultado básico: {resultado_basico}")
        
        # Mostrar información de configuración
        print("\n=== CONFIGURACIÓN ACTUAL ===")
        from app.config.image_analysis_config import VALIDATION_CONFIG, ERROR_MESSAGES, ERROR_INSTRUCTIONS
        print(f"Confianza normal: {VALIDATION_CONFIG['confidence_threshold']:.1%}")
        print(f"Confianza crítica: {VALIDATION_CONFIG['minimum_confidence_for_critical']:.1%}")
        print(f"Restricciones críticas: {VALIDATION_CONFIG['critical_restrictions']}")
        print(f"Máximo intentos: {VALIDATION_CONFIG['max_retries']}")
        print("\n=== TIPOS DE ERROR CONFIGURADOS ===")
        for error_type, message in ERROR_MESSAGES.items():
            print(f"• {error_type}: {message}")
            if error_type in ERROR_INSTRUCTIONS:
                print(f"  Instrucción: {ERROR_INSTRUCTIONS[error_type]}")
        
    else:
        print(f"Archivo de imagen no encontrado: {imagen_path}")
        print("Coloca una imagen de prueba en la carpeta backend/ con el nombre 'test_image.jpg'")
        print("\n=== CONFIGURACIÓN ACTUAL (SIN IMAGEN) ===")
        from app.config.image_analysis_config import VALIDATION_CONFIG, ERROR_MESSAGES
        print(f"Confianza normal: {VALIDATION_CONFIG['confidence_threshold']:.1%}")
        print(f"Confianza crítica: {VALIDATION_CONFIG['minimum_confidence_for_critical']:.1%}")
        print(f"Restricciones críticas: {VALIDATION_CONFIG['critical_restrictions']}")
        print(f"Máximo intentos: {VALIDATION_CONFIG['max_retries']}")
        print(f"\n✅ {len(ERROR_MESSAGES)} tipos de error configurados para el frontend")

if __name__ == "__main__":
    asyncio.run(test_mejoras())
