from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from app.services.gemini_service import analizar_imagen
from app.database.connection import get_db
from app.models import History, Product, User
from app.utils.jwt import JWTBearer, extract_user_id
import json
from app.resources.history import get_history_by_user_id, create_history_for_user
from app.resources.user import get_user_by_id
from app.resources.product import create_product  # Importar función para crear productos

"""
Rutas relacionadas con el análisis de productos alimenticios.
"""

router = APIRouter(prefix="/analysis", tags=["analysis"])  # Cambio a "analysis" en inglés


@router.post("/")
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
        JSONResponse: Resultado del análisis y detalles del producto creado.
    """
    usuario_id = extract_user_id(token)

    # Reemplazar consulta directa con get_history_by_user_id
    historial = get_history_by_user_id(db, usuario_id)
    if not historial:
        historial = create_history_for_user(db, usuario_id)

    # Reemplazar consulta directa con get_user_by_id
    usuario = get_user_by_id(db, usuario_id)
    restricciones = usuario.get_restrictions() if usuario else []

    resultado = await analizar_imagen(file, restricciones=restricciones)

    # Usar la función centralizada para crear productos
    nuevo_producto = create_product(db, name=file.filename, result_json=json.dumps(resultado), history_id=historial.id)

    return JSONResponse(content={
        "mensaje": "Análisis completado y guardado.",  # Mensaje en español
        "producto_id": nuevo_producto.id,
        "resultado": resultado
    })
