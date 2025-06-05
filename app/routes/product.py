from fastapi import APIRouter, HTTPException, Depends, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from app.database.connection import get_db
from app.models import Product, History
from app.utils.jwt import JWTBearer, extract_user_id
from app.schemas.product_schemas import ProductDetail, ImageResponse
from io import BytesIO

router = APIRouter()  # Removemos el prefix para manejar las rutas completas

@router.get("/products/{id}/image", response_model=None, responses={
    200: {
        "content": {"image/jpeg": {}, "image/png": {}, "image/gif": {}, "image/webp": {}},
        "description": "Retorna la imagen del producto",
    },
    404: {"description": "Imagen no encontrada"},
    403: {"description": "No autorizado"}
})
async def get_product_image(
    id: int,
    token: str = Depends(JWTBearer()),
    db: Session = Depends(get_db)
):
    """
    Obtiene la imagen de un producto específico.
    La imagen se sirve en su formato original (jpeg, png, etc.).
    """
    # Primero verificar si el producto existe
    producto = db.query(Product).filter(Product.id == id).first()
    if not producto:
        raise HTTPException(
            status_code=404,
            detail=f"Producto con ID {id} no encontrado"
        )
    
    # Verificar si el usuario tiene acceso al producto
    usuario_id = extract_user_id(token)
    producto_usuario = db.query(Product).join(History).filter(
        Product.id == id,
        History.user_id == usuario_id
    ).first()
    
    if not producto_usuario:
        raise HTTPException(
            status_code=403,
            detail="No tiene permiso para acceder a esta imagen"
        )

    # Verificar si el producto tiene una imagen
    if not producto.image:
        raise HTTPException(
            status_code=404,
            detail="El producto no tiene una imagen asociada"
        )

    return StreamingResponse(
        BytesIO(producto.image),
        media_type=producto.image_type,
        headers={
            "Cache-Control": "max-age=3600",
            "Content-Disposition": f'inline; filename="product_{id}.{producto.image_type.split("/")[1]}"'
        }
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
        "result_json": producto.result_json,
        "date": producto.date,
        "is_suitable": producto.is_suitable,
        "image_url": f"/products/{producto.id}/image"  # URL para obtener la imagen
    }

@router.post("/products")
async def crear_producto(
    result_json: str,
    history_id: int,
    is_suitable: bool,
    image: UploadFile = File(None),
    db: Session = Depends(get_db)
):
    """
    Crea un nuevo producto con una imagen opcional.

    Args:
        result_json (str): Resultado del análisis en formato JSON.
        history_id (int): ID del historial asociado.
        is_suitable (bool): Indica si el producto es apto.
        image (UploadFile): Imagen del producto.
        db (Session): Sesión de la base de datos.

    Returns:
        dict: Detalles del producto creado.
    """
    # Determinar el tipo de imagen si existe
    image_data = None
    image_type = "image/jpeg"  # valor por defecto
    
    if image:
        image_data = await image.read()
        if image.content_type:
            image_type = image.content_type
        elif image.filename:
            if image.filename.lower().endswith('.png'):
                image_type = "image/png"
            elif image.filename.lower().endswith('.webp'):
                image_type = "image/webp"
            elif image.filename.lower().endswith('.gif'):
                image_type = "image/gif"
    
    producto = Product(
        result_json=result_json,
        is_suitable=is_suitable,
        history_id=history_id,
        image=image_data,
        image_type=image_type
    )
    db.add(producto)
    db.commit()
    db.refresh(producto)

    return {"id": producto.id, "mensaje": "Producto creado exitosamente"}
