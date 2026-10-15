from fastapi_mail import FastMail, MessageSchema, ConnectionConfig
import os
from dotenv import load_dotenv

load_dotenv()


def _build_config() -> ConnectionConfig:
    # Se construye recién al enviar, no al importar: así el backend arranca
    # aunque no haya MAIL_* configurado (contenedor en K8s, tests). Antes,
    # int(os.getenv("MAIL_PORT")) sin default tiraba TypeError en el import
    # y tumbaba toda la app.
    return ConnectionConfig(
        MAIL_USERNAME=os.getenv("MAIL_USERNAME", ""),
        MAIL_PASSWORD=os.getenv("MAIL_PASSWORD", ""),
        MAIL_FROM=os.getenv("MAIL_FROM", "noreply@nutriguide.local"),
        MAIL_PORT=int(os.getenv("MAIL_PORT", "587")),
        MAIL_SERVER=os.getenv("MAIL_SERVER", "smtp.gmail.com"),
        MAIL_STARTTLS=os.getenv("MAIL_USE_TLS", "True").lower() == "true",
        MAIL_SSL_TLS=False,
        USE_CREDENTIALS=True,
        VALIDATE_CERTS=True
    )


async def send_email(subject: str, recipients: list[str], body: str):
    message = MessageSchema(
        subject=subject,
        recipients=recipients,
        body=body,
        subtype="plain"  # solo texto plano
    )
    fm = FastMail(_build_config())
    await fm.send_message(message)
