from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import desc
import base64
from app.database.connection import get_db
from app.models import History, Product
from app.utils.jwt import JWTBearer, extract_user_id
from app.schemas.history_schemas import HistoryResponse, ProductDetailResponse, DeleteResponse
from app.resources.history import get_history_by_user_id, create_history_for_user
import json
from io import BytesIO


def _reducir_imagen(data: bytes, image_type: str, max_side: int = 1000):
    try:
        from PIL import Image
        img = Image.open(BytesIO(data))
        if max(img.size) <= max_side and len(data) < 400_000:
            return data, image_type
        img.thumbnail((max_side, max_side))
        out = BytesIO()
        img.convert("RGB").save(out, format="JPEG", quality=80, optimize=True)
        return out.getvalue(), "image/jpeg"
    except Exception:
        return data, image_type

router = APIRouter(
    prefix="/history",
    tags=["History"],
    dependencies=[Depends(JWTBearer())]
)

"""
Rutas relacionadas con el historial de análisis de los usuarios.
"""

@router.get("/")
def obtener_historial(token: str = Depends(JWTBearer()), db: Session = Depends(get_db)):
    """
    Obtiene el historial de análisis de un usuario autenticado.
    Lista todos los productos ordenados por fecha, mostrando solo información básica.
    Si no existe historial, devuelve una lista vacía.
    """
    usuario_id = extract_user_id(token)
    historial = get_history_by_user_id(db, usuario_id)
    
    if not historial:
        # Retornar lista vacía en lugar de error 404
        return []
        
    # Solo las columnas que se muestran: cargar la fila entera traía la foto
    # (cientos de KB por producto) para cada ítem del historial, y la lista
    # tardaba segundos en abrir.
    productos = (
        db.query(Product.id, Product.date, Product.is_suitable)
        .filter(Product.history_id == historial.id)
        .order_by(desc(Product.date))
        .all()
    )
    return [{
        "id": p.id,
        "date": p.date,
        "is_suitable": p.is_suitable
    } for p in productos]

@router.get("/product/{id}", response_model=ProductDetailResponse)
def obtener_producto(id: int, token: str = Depends(JWTBearer()), db: Session = Depends(get_db)):
    """
    Obtiene los detalles completos de un producto específico.
    """
    usuario_id = extract_user_id(token)
    
    producto = db.query(Product).join(History).filter(
        Product.id == id,
        History.user_id == usuario_id
    ).first()
    
    if not producto:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    
    # Validar que result_json no sea None
    if producto.result_json is None:
        raise HTTPException(status_code=500, detail="Datos del producto incompletos")
    
    result_json = json.loads(producto.result_json)
    image_url = f"/history/product/{producto.id}/image"
    
    return ProductDetailResponse(
        id=producto.id,
        date=producto.date,
        is_suitable=producto.is_suitable,
        result_json=result_json,
        image_type=producto.image_type,
        image_url=image_url
    )

@router.get("/product/{id}/image")
async def obtener_imagen_producto(
    id: int,
    token: str = Depends(JWTBearer()),
    db: Session = Depends(get_db)
):
    """
    Obtiene la imagen de un producto específico.
    """
    usuario_id = extract_user_id(token)
    producto = db.query(Product).join(History).filter(
        Product.id == id,
        History.user_id == usuario_id
    ).first()

    if not producto or not producto.image:
        raise HTTPException(status_code=404, detail="Imagen no encontrada")

    # La pantalla de detalle muestra la foto chica: se manda reducida (JPEG,
    # lado mayor 1000 px) en vez del archivo original de varios MB.
    data, media_type = _reducir_imagen(producto.image, producto.image_type)
    return StreamingResponse(BytesIO(data), media_type=media_type)

# Eliminar un producto específico del historial
@router.delete("/product/{id}", response_model=DeleteResponse)
async def eliminar_producto(id: int, token: str = Depends(JWTBearer()), db: Session = Depends(get_db)):
    """
    Elimina un producto específico del historial.
    Si es el último producto, también se elimina el historial.
    """
    usuario_id = extract_user_id(token)

    producto = db.query(Product).join(History).filter(
        Product.id == id,
        History.user_id == usuario_id
    ).first()

    if not producto:
        raise HTTPException(status_code=404, detail="Producto no encontrado")

    history_id = producto.history_id

    # Eliminar el producto
    db.delete(producto)
    db.commit()

    # Verificar si ya no quedan productos asociados a ese historial
    productos_restantes = db.query(Product).filter_by(history_id=history_id).count()
    if productos_restantes == 0:
        historial = db.query(History).filter_by(id=history_id).first()
        if historial:
            db.delete(historial)
            db.commit()
        return DeleteResponse(mensaje="Producto eliminado. También se eliminó el historial vacío.")

    return DeleteResponse(mensaje="Producto eliminado exitosamente.")


# Eliminar el historial completo de un usuario
@router.delete("/", response_model=DeleteResponse)
async def eliminar_historial(token: str = Depends(JWTBearer()), db: Session = Depends(get_db)):
    """
    Elimina todo el historial del usuario.
    """
    usuario_id = extract_user_id(token)

    # Reemplazar consulta directa con get_history_by_user_id
    historial = get_history_by_user_id(db, usuario_id)
    if not historial:
        raise HTTPException(status_code=404, detail="Historial no encontrado")

    for producto in db.query(Product).filter_by(history_id=historial.id).all():
        db.delete(producto)  # ORM delete: arrastra product_ingredients por cascade
    db.delete(historial)
    db.commit() 

    return DeleteResponse(mensaje="Historial y productos asociados eliminados exitosamente")
