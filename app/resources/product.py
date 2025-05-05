"""
Funciones relacionadas con la gestión de productos en la base de datos.
"""

from sqlalchemy.orm import Session
from app.models.product import Product
from datetime import datetime

def get_products_by_history_id(db: Session, history_id: int) -> list[Product]:
    return db.query(Product).filter(Product.history_id == history_id).all()

def create_product(db: Session, name: str, result_json: str, history_id: int) -> Product:
    """
    Crea un nuevo producto asociado a un historial en la base de datos.

    Args:
        db (Session): Sesión de la base de datos.
        name (str): Nombre del producto.
        result_json (str): Resultado del análisis en formato JSON.
        history_id (int): ID del historial asociado.

    Returns:
        Product: Producto creado.
    """
    product = Product(name=name, result_json=result_json, history_id=history_id, date=datetime.utcnow())
    db.add(product)
    db.commit()
    db.refresh(product)
    return product
