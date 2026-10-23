"""Envío de correos de recordatorio (CU-05) detrás de un adaptador.

`EMAIL_BACKEND=console` (único por ahora) solo registra destinatario enmascarado y asunto, nunca
el cuerpo. Un proveedor real (Resend, Brevo, SMTP) se agrega como otra clase con `send()`.

Modo discreto (por defecto): asunto y texto genéricos, sin la marca ni palabras que revelen el
tema (mama, cáncer, autoexploración, análisis). Siempre lleva el enlace de baja.
"""

import logging
import os
from dataclasses import dataclass
from typing import Protocol

logger = logging.getLogger(__name__)

DISCREET_SUBJECT = "Tienes un recordatorio pendiente"
DISCREET_BODY = "Hola:\n\nTienes un recordatorio pendiente. Entra a tu cuenta para verlo."

SUBJECTS = {
    "self_exam": "BreastGuard: es momento de tu autoexploración",
    "repeat_analysis": "BreastGuard: recordatorio para repetir tu análisis",
}
BODIES = {
    "self_exam": (
        "Hola:\n\nEs momento de tu autoexploración guiada. Conocer tu cuerpo te ayuda a notar "
        "cualquier cambio; si notas algo distinto, consulta a tu médico.\n\n"
        "Herramienta de apoyo al diagnóstico. No sustituye el criterio ni la consulta médica."
    ),
    "repeat_analysis": (
        "Hola:\n\nTe recordamos repetir tu análisis de imagen según lo que acordaste con tu "
        "médico.\n\n"
        "Herramienta de apoyo al diagnóstico. No sustituye el criterio ni la consulta médica."
    ),
}


class EmailError(Exception):
    pass


@dataclass(frozen=True)
class EmailMessage:
    to: str
    subject: str
    body: str
    from_name: str


class EmailSender(Protocol):
    def send(self, message: EmailMessage) -> None: ...


def mask(email: str) -> str:
    """p***@d***.com: suficiente para depurar sin exponer la dirección en los logs."""
    local, _, domain = email.partition("@")
    host, _, tld = domain.rpartition(".")
    return f"{local[:1]}***@{host[:1]}***.{tld}" if host else "***"


class ConsoleEmailSender:
    """Desarrollo y demo: no envía nada, solo deja constancia en el log.

    Ni el cuerpo ni el asunto: fuera del modo discreto el asunto revela el tema.
    """

    def send(self, message: EmailMessage) -> None:
        logger.info("Correo (consola) para %s", mask(message.to))


def get_sender() -> EmailSender:
    backend = os.environ.get("EMAIL_BACKEND", "console")
    if backend == "console":
        return ConsoleEmailSender()
    raise EmailError(f"EMAIL_BACKEND no soportado: {backend}")


def compose(*, to: str, kind: str, discreet: bool, unsubscribe_url: str) -> EmailMessage:
    subject = DISCREET_SUBJECT if discreet else SUBJECTS[kind]
    body = DISCREET_BODY if discreet else BODIES[kind]
    footer = f"\n\nPara dejar de recibir este recordatorio: {unsubscribe_url}"
    return EmailMessage(
        to=to,
        subject=subject,
        body=body + footer,
        from_name=os.environ.get("EMAIL_FROM_NAME", "Recordatorios"),
    )
