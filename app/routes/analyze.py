from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from app.services.gemini_service import analizar_imagen
from app.database.connection import get_db
from app.models import History, Product, User
from app.utils.jwt import JWTBearer, extract_user_id
from app.schemas.auth_schemas import Token
from app.schemas.product_schemas import ImageType, ProductAnalysisResponse
from app.resources.history import get_history_by_user_id, create_history_for_user
from app.resources.user import get_user_by_id
from app.resources.product import create_product
import json

"""
Rutas relacionadas con el análisis de productos alimenticios.
"""

router = APIRouter(prefix="/analysis", tags=["analysis"])

@router.post("/", response_model=ProductAnalysisResponse)
async def analizar_producto(
    file: UploadFile = File(...),
    token: str = Depends(JWTBearer()),
    db: Session = Depends(get_db)
):
    """
    Analiza un producto alimenticio a partir de una imagen de su etiqueta.

    Args:
        file (UploadFile): Archivo de imagen de la etiqueta.
        token (str): Token JWT del usuario autenticado.
        db (Session): Sesión de la base de datos.

    Returns:
        ProductAnalysisResponse: Resultado del análisis y detalles del producto creado.
    """
    usuario_id = extract_user_id(token)    # Obtener o crear el historial del usuario
    historial = get_history_by_user_id(db, usuario_id)
    if not historial:
        historial = create_history_for_user(db, usuario_id)

    # Obtener las restricciones del usuario
    usuario = get_user_by_id(db, usuario_id)
    restricciones = usuario.get_restrictions() if usuario else []

    # Leer el contenido de la imagen una sola vez
    image_data = await file.read()
    
    # Validar y obtener el tipo de imagen
    content_type = file.content_type
    if not content_type:
        # Intentar determinar el tipo de imagen por la extensión del archivo
        if file.filename.lower().endswith('.png'):
            content_type = ImageType.PNG.value
        elif file.filename.lower().endswith('.webp'):
            content_type = ImageType.WEBP.value
        elif file.filename.lower().endswith('.gif'):
            content_type = ImageType.GIF.value
        else:
            content_type = ImageType.JPEG.value
    
    # Verificar que el tipo de imagen es soportado
    try:
        image_type = ImageType(content_type)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Tipo de imagen no soportado. Tipos permitidos: {', '.join([t.value for t in ImageType])}"
        )
      # Analizar la imagen pasando los bytes directamente
    try:
        print(f"Iniciando análisis de imagen: {len(image_data)} bytes, con restricciones: {restricciones}")
        resultado = await analizar_imagen(image_data, restricciones=restricciones)
        print(f"Análisis completado correctamente")
    except Exception as e:
        print(f"Error durante el análisis de la imagen: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error al analizar la imagen: {str(e)}"
        )
    
    # Crear el producto con la nueva estructura
    try:
        print(f"Creando producto en la base de datos")
        nuevo_producto = create_product(
            db, 
            result_json=resultado,
            history_id=historial.id,
            image_type=image_type.value,
            image_data=image_data
        )
        print(f"Producto creado correctamente con ID: {nuevo_producto.id}")
    except Exception as e:
        print(f"Error al crear el producto en la base de datos: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error al guardar el producto: {str(e)}"
        )

    return ProductAnalysisResponse(
        product_id=nuevo_producto.id,
        is_suitable=nuevo_producto.is_suitable,
        result_json=resultado
    )
