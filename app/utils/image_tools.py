# app/utils/image_tools.py
from PIL import Image, ImageStat, ImageFilter
import io
import logging
from typing import Dict, Tuple
from app.config.image_analysis_config import IMAGE_QUALITY_CONFIG, COMPRESSION_CONFIG

logger = logging.getLogger(__name__)

def comprimir_imagen(file_bytes, calidad=50, max_dim=800):
    """Función original mantenida para compatibilidad"""
    imagen = Image.open(io.BytesIO(file_bytes)).convert("RGB")
    if max(imagen.size) > max_dim:
        imagen.thumbnail((max_dim, max_dim))
    buffer = io.BytesIO()
    imagen.save(buffer, format='JPEG', quality=calidad)
    buffer.seek(0)
    return Image.open(buffer)

def calcular_nitidez(imagen: Image.Image) -> float:
    """
    Calcula la nitidez de una imagen usando el filtro Laplaciano.
    Retorna un valor donde mayor = más nítida.
    """
    try:
        # Convertir a escala de grises
        gris = imagen.convert('L')
        
        # Aplicar filtro Laplaciano para detectar bordes
        laplaciano = gris.filter(ImageFilter.FIND_EDGES)
        
        # Calcular la varianza (mayor varianza = más nitidez)
        stat = ImageStat.Stat(laplaciano)
        nitidez = stat.var[0]
        
        return nitidez
    except Exception as e:
        logger.warning(f"Error calculando nitidez: {e}")
        return 0.0

def calcular_brillo_contraste(imagen: Image.Image) -> Tuple[float, float]:
    """
    Calcula el brillo y contraste promedio de una imagen.
    Retorna (brillo, contraste) donde 0-255 es el rango normal.
    """
    try:
        # Convertir a escala de grises para análisis
        gris = imagen.convert('L')
        stat = ImageStat.Stat(gris)
        
        brillo = stat.mean[0]  # Promedio de intensidad
        contraste = stat.stddev[0]  # Desviación estándar como medida de contraste
        
        return brillo, contraste
    except Exception as e:
        logger.warning(f"Error calculando brillo/contraste: {e}")
        return 128.0, 50.0

def es_etiqueta_nutricional(imagen: Image.Image) -> bool:
    """
    Análisis básico para determinar si la imagen podría ser una etiqueta nutricional.
    Retorna True si parece ser una etiqueta válida.
    """
    try:
        config = IMAGE_QUALITY_CONFIG
        
        # Verificar dimensiones mínimas
        ancho, alto = imagen.size
        if ancho < config["dimension_minima"] or alto < config["dimension_minima"]:
            return False
        
        # Verificar que no sea completamente uniforme (imagen sólida)
        stat = ImageStat.Stat(imagen.convert('L'))
        if stat.stddev[0] < config["variacion_minima"]:  # Muy poca variación
            return False
        
        # Verificar relación de aspecto razonable
        relacion_aspecto = max(ancho, alto) / min(ancho, alto)
        if relacion_aspecto > config["relacion_aspecto_maxima"]:  # Muy alargada
            return False
        
        return True
    except Exception as e:
        logger.warning(f"Error verificando etiqueta nutricional: {e}")
        return False

def analizar_calidad_imagen(file_bytes: bytes) -> Dict:
    """
    Analiza la calidad de una imagen para determinar si es apta para OCR.
    Retorna información sobre la calidad y validez de la imagen.
    """
    try:
        imagen = Image.open(io.BytesIO(file_bytes)).convert("RGB")
        
        # Calcular métricas de calidad
        nitidez = calcular_nitidez(imagen)
        brillo, contraste = calcular_brillo_contraste(imagen)
        
        # Verificar si es una etiqueta nutricional
        es_etiqueta = es_etiqueta_nutricional(imagen)
        
        # Usar configuración centralizada
        config = IMAGE_QUALITY_CONFIG
        
        # Análisis de calidad
        problemas = []
        
        if nitidez < config["nitidez_minima"]:
            problemas.append("Imagen demasiado borrosa")
        
        if brillo < config["brillo_minimo"]:
            problemas.append("Imagen demasiado oscura")
        elif brillo > config["brillo_maximo"]:
            problemas.append("Imagen demasiado brillante")
        
        if contraste < config["contraste_minimo"]:
            problemas.append("Bajo contraste")
        
        if not es_etiqueta:
            problemas.append("No parece ser una etiqueta nutricional")
        
        # Determinar si es válida
        es_valida = len(problemas) == 0
        
        return {
            "es_valida": es_valida,
            "nitidez": nitidez,
            "brillo": brillo,
            "contraste": contraste,
            "problemas": problemas,
            "razon": "; ".join(problemas) if problemas else "Imagen de buena calidad"
        }
        
    except Exception as e:
        logger.error(f"Error analizando calidad de imagen: {e}")
        return {
            "es_valida": False,
            "nitidez": 0.0,
            "brillo": 0.0,
            "contraste": 0.0,
            "problemas": ["Error al procesar la imagen"],
            "razon": f"Error al procesar la imagen: {str(e)}"
        }

def comprimir_imagen_inteligente(file_bytes: bytes, tipo_analisis: str = "etiqueta_nutricional") -> Image.Image:
    """
    Comprime una imagen de manera inteligente según el tipo de análisis.
    Para etiquetas nutricionales, prioriza la legibilidad del texto.
    """
    try:
        imagen = Image.open(io.BytesIO(file_bytes)).convert("RGB")
        
        # Obtener configuración según el tipo de análisis
        config = COMPRESSION_CONFIG.get(tipo_analisis, COMPRESSION_CONFIG["standard"])
        
        # Aplicar configuración específica
        max_dim = config["max_dimension"]
        calidad = config["quality"]
        
        # Mejorar contraste si es necesario y está habilitado
        if config.get("enhance_contrast", False):
            brillo, contraste = calcular_brillo_contraste(imagen)
            if contraste < IMAGE_QUALITY_CONFIG["contraste_minimo"]:
                # Aplicar mejora de contraste suave
                from PIL import ImageEnhance
                enhancer = ImageEnhance.Contrast(imagen)
                imagen = enhancer.enhance(1.2)
        
        # Redimensionar si es necesario
        if max(imagen.size) > max_dim:
            imagen.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
        
        # Comprimir manteniendo calidad
        buffer = io.BytesIO()
        imagen.save(buffer, format='JPEG', quality=calidad, optimize=True)
        buffer.seek(0)
        
        return Image.open(buffer)
        
    except Exception as e:
        logger.error(f"Error en compresión inteligente: {e}")
        # Fallback a compresión básica
        return comprimir_imagen(file_bytes)
