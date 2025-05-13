from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from typing import Union, Dict, Any

class AppError(Exception):
    def __init__(self, status_code: int, detail: Union[str, Dict[str, Any]]):
        self.status_code = status_code
        self.detail = detail

async def validation_error_handler(request: Request, exc: ValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "detail": [
                {
                    "loc": error["loc"],
                    "msg": error["msg"],
                    "type": error["type"]
                }
                for error in exc.errors()
            ]
        }
    )

async def sqlalchemy_error_handler(request: Request, exc: SQLAlchemyError):
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Error en la base de datos. Por favor, inténtelo de nuevo más tarde."
        }
    )

async def app_error_handler(request: Request, exc: AppError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail}
    )

def register_error_handlers(app: FastAPI):
    """
    Registra los manejadores de errores en la aplicación.
    """
    app.add_exception_handler(ValidationError, validation_error_handler)
    app.add_exception_handler(SQLAlchemyError, sqlalchemy_error_handler)
    app.add_exception_handler(AppError, app_error_handler)