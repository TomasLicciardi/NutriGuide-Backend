from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from sqlalchemy.orm import Session
from app.services.gemini_service import gemini_service
from app.database.connection import get_db
from app.models import History, Product, User
from app.utils.jwt import JWTBearer, extract_user_id
from app.schemas.product_schemas import ImageType
from app.schemas.analysis_schemas import AnalysisResponseV2, ErrorResponse
from app.resources.history import get_history_by_user_id, create_history_for_user
from app.resources.user import get_user_by_id
import json
import time
import logging

# Configurar logging
logger = logging.getLogger(__name__)

"""
Rutas unificadas para el análisis de productos alimenticios.
FLUJO UNIFICADO:
1. OCR con Gemini → extraer ingredientes + advertencias
2. Embeddings DB → clasificar cada ingrediente (BASE/ADITIVO)
3. RAG + Gemini → clasificar solo ingredientes BASE
4. Guardar en BD → resultado final
"""

router = APIRouter(prefix="/analysis", tags=["analysis"])

@router.post("/", response_model=AnalysisResponseV2)
async def analizar_producto(
    file: UploadFile = File(...),
    token: str = Depends(JWTBearer()),
    db: Session = Depends(get_db)
):
    """
    ENDPOINT UNIFICADO de análisis de productos alimenticios.
    
    FLUJO COMPLETO:
    1. 📸 OCR con Gemini → extraer ingredientes + advertencias  
    2. 🧠 Embeddings DB → clasificar cada ingrediente (BASE/ADITIVO)
    3. 🤖 RAG + Gemini → clasificar solo ingredientes BASE para restricciones
    4. 💾 Guardar en BD → resultado final unificado
    
    Returns:
        AnalysisResponseV2: Resultado completo del análisis
    """
    start_time = time.time()
    usuario_id = extract_user_id(token)
    
    # Obtener o crear historial del usuario
    historial = get_history_by_user_id(db, usuario_id)
    if not historial:
        historial = create_history_for_user(db, usuario_id)

    # Obtener restricciones del usuario
    usuario = get_user_by_id(db, usuario_id)
    restricciones_usuario = usuario.get_restrictions() if usuario else []

    # Leer contenido de la imagen
    image_data = await file.read()
    
    # Validar tipo de imagen
    content_type = file.content_type or "image/jpeg"
    try:
        image_type = ImageType(content_type)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Tipo de imagen no soportado. Tipos permitidos: {', '.join([t.value for t in ImageType])}"
        )
    
    # 🔥 FASE 1: PRIMERA PETICIÓN A GEMINI - OCR
    try:
        logger.info("🔍 FASE 1: Extracción OCR con Gemini")
        ocr_result = await gemini_service.extract_ingredients_ocr(image_data, image_type.value)
        
        if not ocr_result.get("success"):
            raise HTTPException(
                status_code=400 if ocr_result.get("error") in ["poor_quality", "invalid_image"] else 500,
                detail=ErrorResponse(
                    error=ocr_result.get("error", "unknown"),
                    message=ocr_result.get("message", "Error en OCR"),
                    confidence=ocr_result.get("confidence", 0.0)
                ).dict()
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error en extracción OCR: {str(e)}"
        )
    
    # 🔥 FASE 2: CLASIFICACIÓN CON EMBEDDINGS + RAG
    try:
        logger.info("🧠 FASE 2: Clasificación con embeddings + RAG")
        ingredientes_detectados = ocr_result["ingredients"]
        allergen_warnings = ocr_result.get("allergen_warnings", "")
        
        # USAR FLUJO UNIFICADO:
        # 1. Embeddings DB → clasificar cada ingrediente (BASE/ADITIVO)
        # 2. Solo ingredientes BASE → SEGUNDA PETICIÓN a Gemini con RAG
        classification_result = await gemini_service.classify_ingredients_with_embeddings_and_rag(
            ingredientes_detectados, allergen_warnings, db
        )
        
        if not classification_result.get("success"):
            raise HTTPException(
                status_code=422,
                detail=ErrorResponse(
                    error=classification_result.get("error", "classification_failed"),
                    message=classification_result.get("message", "Error en clasificación"),
                    confidence=classification_result.get("confidence", 0.0)
                ).dict()
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error en clasificación: {str(e)}"
        )
    
    # 🔥 FASE 3: ALMACENAMIENTO EN BD
    try:
        logger.info("💾 FASE 3: Guardando en base de datos")
        
        # Debug: mostrar restricciones del usuario
        logger.info(f"🔍 Usuario: {usuario.username if usuario else 'Anónimo'}")
        logger.info(f"🔍 Restricciones del usuario: {restricciones_usuario}")
        
        # Calcular veredicto del usuario
        user_verdict = calculate_user_verdict(classification_result, restricciones_usuario)
        logger.info(f"🔍 User verdict calculado: {user_verdict}")
        
        # Extraer ingredientes clasificados
        classified_ingredients = classification_result.get("classified_ingredients", [])
        
        # Construir resultado final completo para compatibilidad
        base_ingredients = [ing for ing in classified_ingredients if ing["type"] == "BASE"]
        additives = [ing for ing in classified_ingredients if ing["type"] == "ADITIVO"]
        
        final_result = {
            "user_verdict": user_verdict,
            "classification": {
                "vegano": {"apto": classification_result["restrictions"]["vegano"]["apto"], 
                          "motivo": classification_result["restrictions"]["vegano"].get("motivo")},
                "vegetariano": {"apto": classification_result["restrictions"]["vegetariano"]["apto"], 
                               "motivo": classification_result["restrictions"]["vegetariano"].get("motivo")},
                "sin_gluten": {"apto": classification_result["restrictions"]["sin_gluten"]["apto"], 
                              "motivo": classification_result["restrictions"]["sin_gluten"].get("motivo")},
                "sin_lactosa": {"apto": classification_result["restrictions"]["sin_lactosa"]["apto"], 
                               "motivo": classification_result["restrictions"]["sin_lactosa"].get("motivo")},
                "sin_frutos_secos": {"apto": classification_result["restrictions"]["sin_frutos_secos"]["apto"], 
                                    "motivo": classification_result["restrictions"]["sin_frutos_secos"].get("motivo")}
            },
            "detected_ingredients": ingredientes_detectados,
            "base_ingredients": [ing["name"] for ing in base_ingredients],
            "additives": [ing["name"] for ing in additives],
            "allergen_warnings": allergen_warnings,
            "confidence": min(ocr_result["confidence"], classification_result["confidence"])
        }
        
        # Crear producto en BD
        nuevo_producto = Product(
            history_id=historial.id,
            image=image_data,
            image_type=image_type.value,
            
            # Resultados OCR
            ocr_result_json=json.dumps(ocr_result),
            extracted_ingredients=json.dumps(ingredientes_detectados),
            allergen_warnings=allergen_warnings,
            ocr_confidence=ocr_result["confidence"],
            
            # Resultados clasificación
            classification_result_json=json.dumps(classification_result),
            classification_confidence=classification_result["confidence"],
            
            # Restricciones individuales
            is_vegan=classification_result["restrictions"]["vegano"]["apto"],
            vegan_reason=classification_result["restrictions"]["vegano"].get("motivo"),
            is_vegetarian=classification_result["restrictions"]["vegetariano"]["apto"],
            vegetarian_reason=classification_result["restrictions"]["vegetariano"].get("motivo"),
            is_gluten_free=classification_result["restrictions"]["sin_gluten"]["apto"],
            gluten_free_reason=classification_result["restrictions"]["sin_gluten"].get("motivo"),
            is_lactose_free=classification_result["restrictions"]["sin_lactosa"]["apto"],
            lactose_free_reason=classification_result["restrictions"]["sin_lactosa"].get("motivo"),
            is_nut_free=classification_result["restrictions"]["sin_frutos_secos"]["apto"],
            nut_free_reason=classification_result["restrictions"]["sin_frutos_secos"].get("motivo"),
            
            # Resultado completo para compatibilidad
            result_json=json.dumps(final_result),
            
            # Metadatos
            is_suitable=user_verdict,
            processing_status="completed"
        )
        
        db.add(nuevo_producto)
        db.commit()
        
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Error almacenando en BD: {str(e)}"
        )
    
    # 🔥 FASE 4: RESPUESTA FINAL
    processing_time = time.time() - start_time
    
    logger.info(f"✅ ANÁLISIS COMPLETADO en {processing_time:.2f}s - {len(base_ingredients)} BASE, {len(additives)} ADITIVOS")
    
    # Agregar processing_time al resultado final
    final_result["processing_time"] = processing_time
    
    return AnalysisResponseV2(
        user_verdict=user_verdict,
        classification={
            "vegano": {"apto": classification_result["restrictions"]["vegano"]["apto"], 
                      "motivo": classification_result["restrictions"]["vegano"].get("motivo")},
            "vegetariano": {"apto": classification_result["restrictions"]["vegetariano"]["apto"], 
                           "motivo": classification_result["restrictions"]["vegetariano"].get("motivo")},
            "sin_gluten": {"apto": classification_result["restrictions"]["sin_gluten"]["apto"], 
                          "motivo": classification_result["restrictions"]["sin_gluten"].get("motivo")},
            "sin_lactosa": {"apto": classification_result["restrictions"]["sin_lactosa"]["apto"], 
                           "motivo": classification_result["restrictions"]["sin_lactosa"].get("motivo")},
            "sin_frutos_secos": {"apto": classification_result["restrictions"]["sin_frutos_secos"]["apto"], 
                                "motivo": classification_result["restrictions"]["sin_frutos_secos"].get("motivo")}
        },
        detected_ingredients=ingredientes_detectados,
        base_ingredients=[ing["name"] for ing in base_ingredients],
        additives=[ing["name"] for ing in additives],
        allergen_warnings=allergen_warnings,
        confidence=min(ocr_result["confidence"], classification_result["confidence"]),
        processing_time=processing_time
    )

def calculate_user_verdict(classification_result: dict, user_restrictions: list) -> bool:
    """
    Calcula veredicto final para el usuario basado en sus restricciones activas
    """
    logger.info(f"🔍 Calculando veredicto para restricciones: {user_restrictions}")
    
    if not user_restrictions:
        logger.info("✅ Sin restricciones de usuario → APTO")
        return True  # Sin restricciones = apto
    
    # Mapeo de restricciones para compatibilidad
    restriction_mapping = {
        'sin_tacc': 'sin_gluten',  # TACC = gluten en Argentina
        'celiacos': 'sin_gluten',
        'lactose_free': 'sin_lactosa',
        'nut_free': 'sin_frutos_secos',
        'vegan': 'vegano',
        'vegetarian': 'vegetariano'
    }
    
    classification = classification_result["restrictions"]
    logger.info(f"🔍 Clasificaciones disponibles: {list(classification.keys())}")
    
    for restriction in user_restrictions:
        # Mapear restricción si es necesario
        mapped_restriction = restriction_mapping.get(restriction, restriction)
        logger.info(f"🔍 Evaluando '{restriction}' → '{mapped_restriction}'")
        
        if mapped_restriction in classification:
            is_apt = classification[mapped_restriction]["apto"]
            reason = classification[mapped_restriction].get("motivo")
            logger.info(f"🔍 Restricción '{mapped_restriction}': apto={is_apt}, motivo='{reason}'")
            
            if not is_apt:
                logger.info(f"❌ NO APTO por restricción '{restriction}' ('{mapped_restriction}'): {reason}")
                return False  # Una restricción no cumplida = no apto
        else:
            logger.warning(f"⚠️ Restricción '{mapped_restriction}' no encontrada en clasificación")
    
    logger.info("✅ Todas las restricciones cumplidas → APTO")
    return True  # Todas las restricciones cumplidas = apto