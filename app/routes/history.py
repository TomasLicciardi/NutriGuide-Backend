from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database.connection import get_db
from app.models import History, User, Product
from app.utils.jwt import *
import json
from app.resources.history import get_history_by_user_id, create_history_for_user

router = APIRouter(
    prefix="/history",  # Cambio a "history" en inglés
    tags=["History"],
    dependencies=[Depends(JWTBearer())]
)

"""
Rutas relacionadas con el historial de análisis de los usuarios.
"""

# Obtener historial completo del usuario, ordenado por fecha (más reciente primero)
@router.get("/")
def obtener_historial(token: str = Depends(JWTBearer()), db: Session = Depends(get_db)):
    """
    Obtiene el historial de análisis de un usuario autenticado.

    Args:
        token (str): Token JWT del usuario autenticado.
        db (Session): Sesión de la base de datos.

    Returns:
        dict: Detalles del historial y productos analizados.
    """
    usuario_id = extract_user_id(token)

    # Reemplazar consulta directa con get_history_by_user_id
    historial = get_history_by_user_id(db, usuario_id)
    if not historial:
        raise HTTPException(status_code=404, detail="Historial no encontrado")

    productos = db.query(Product).filter_by(history_id=historial.id).order_by(Product.date.desc()).all()

    return {
        "historial_id": historial.id,
        "usuario_id": historial.user_id,
        "productos_analizados": [
            {
                "id": p.id,
                "resultado": json.loads(p.result_json),
                "fecha": p.date
            } for p in productos
        ]
    }

# Obtener un producto analizado específico
@router.get("/{id}")
def obtener_producto(id: int, token: str = Depends(JWTBearer()), db: Session = Depends(get_db)):
    usuario_id = extract_user_id(token)

    producto = db.query(Product).join(History).filter(
        Product.id == id,
        History.user_id == usuario_id
    ).first()

    if not producto:
        raise HTTPException(status_code=404, detail="Producto no encontrado")

    return {
        "id": producto.id,
        "resultado": json.loads(producto.result_json),
        "fecha": producto.date
    }

# Eliminar un producto específico del historial
@router.delete("/product/{id}")
async def eliminar_producto(id: int, token: str = Depends(JWTBearer()), db: Session = Depends(get_db)):
    usuario_id = extract_user_id(token)

    # Buscar el producto específico con su historial
    producto = db.query(Product).join(History).filter(
        Product.id == id,
        History.user_id == usuario_id
    ).first()

    if not producto:
        raise HTTPException(status_code=404, detail="Producto no encontrado")

    # Eliminar el producto de la base de datos
    db.delete(producto)
    db.commit()

    return {"mensaje": "Producto eliminado exitosamente"}

# Eliminar el historial completo de un usuario
@router.delete("/")
async def eliminar_historial(token: str = Depends(JWTBearer()), db: Session = Depends(get_db)):
    """
    Elimina el historial de análisis de un usuario autenticado.

    Args:
        token (str): Token JWT del usuario autenticado.
        db (Session): Sesión de la base de datos.

    Returns:
        dict: Mensaje de confirmación de la eliminación.
    """
    usuario_id = extract_user_id(token)

    # Reemplazar consulta directa con get_history_by_user_id
    historial = get_history_by_user_id(db, usuario_id)
    if not historial:
        raise HTTPException(status_code=404, detail="Historial no encontrado")

    db.query(Product).filter_by(history_id=historial.id).delete()
    db.delete(historial)
    db.commit()

    return {"mensaje": "Historial y productos asociados eliminados exitosamente"}