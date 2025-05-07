from fastapi import APIRouter, HTTPException, Depends, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from app.database.connection import get_db
from app.models.product import Product

router = APIRouter(prefix="/products", tags=["products"])

@router.get("/{product_id}/image")
async def obtener_imagen_producto(product_id: int, db: Session = Depends(get_db)):
    """
    Obtiene la imagen de un producto por su ID.

    Args:
        product_id (int): ID del producto.
        db (Session): Sesión de la base de datos.

    Returns:
        StreamingResponse: Imagen del producto.
    """
    producto = db.query(Product).filter(Product.id == product_id).first()
    if not producto or not producto.image:
        raise HTTPException(status_code=404, detail="Imagen no encontrada")

    return StreamingResponse(
        iter([producto.image]),
        media_type="image/jpeg"  # Cambia esto según el formato de la imagen (e.g., image/png)
    )

@router.get("/{product_id}")
async def obtener_producto(product_id: int, db: Session = Depends(get_db)):
    """
    Obtiene los detalles de un producto por su ID.

    Args:
        product_id (int): ID del producto.
        db (Session): Sesión de la base de datos.

    Returns:
        dict: Detalles del producto.
    """
    producto = db.query(Product).filter(Product.id == product_id).first()
    if not producto:
        raise HTTPException(status_code=404, detail="Producto no encontrado")

    return {
        "id": producto.id,
        "name": producto.name,
        "result_json": producto.result_json,
        "date": producto.date,
        "image_url": f"/products/{producto.id}/image"  # URL para obtener la imagen
    }

@router.post("/")
async def crear_producto(
    name: str,
    result_json: str,
    history_id: int,
    image: UploadFile = File(None),
    db: Session = Depends(get_db)
):
    """
    Crea un nuevo producto con una imagen opcional.

    Args:
        name (str): Nombre del producto.
        result_json (str): Resultado del análisis en formato JSON.
        history_id (int): ID del historial asociado.
        image (UploadFile): Imagen del producto.
        db (Session): Sesión de la base de datos.

    Returns:
        dict: Detalles del producto creado.
    """
    producto = Product(
        name=name,
        result_json=result_json,
        history_id=history_id,
        image=await image.read() if image else None
    )
    db.add(producto)
    db.commit()
    db.refresh(producto)

    return {"id": producto.id, "mensaje": "Producto creado exitosamente"}