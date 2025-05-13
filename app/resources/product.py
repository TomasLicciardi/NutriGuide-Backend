"""
Funciones relacionadas con la gestión de productos en la base de datos.
"""

from sqlalchemy.orm import Session
from sqlalchemy import desc
from app.models.product import Product
from datetime import datetime
import json

def get_products_by_history_id(db: Session, history_id: int) -> list[Product]:
    """
    Obtiene todos los productos de un historial ordenados por fecha descendente.
    """
    return db.query(Product).filter(Product.history_id == history_id).order_by(desc(Product.date)).all()

def create_product(db: Session, result_json: dict, history_id: int, image_type: str, image_data: bytes = None) -> Product:
    """
    Crea un nuevo producto asociado a un historial en la base de datos.

    Args:
        db (Session): Sesión de la base de datos.
        result_json (dict): Resultado del análisis en formato diccionario.
        history_id (int): ID del historial asociado.
        image_type (str): Tipo de imagen (e.g., 'image/jpeg', 'image/png').
        image_data (bytes, optional): Datos binarios de la imagen.

    Returns:
        Product: Producto creado.
    """
    # Determinar si el producto es apto basado en el resultado del análisis
    clasificacion = result_json.get('clasificacion', {})
    is_suitable = all(info.get('apto', True) for info in clasificacion.values())
    
    product = Product(
        result_json=json.dumps(result_json),
        history_id=history_id,
        is_suitable=is_suitable,
        image_type=image_type,
        image=image_data,
        date=datetime.utcnow()
    )
    db.add(product)
    db.commit()
    db.refresh(product)
    return product
