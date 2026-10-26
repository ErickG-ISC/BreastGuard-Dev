"""Envío de correos (recordatorios de CU-05 e invitaciones de ADR 0008) detrás de un adaptador.

- `EMAIL_BACKEND=console`: no envía; solo registra el destinatario enmascarado.
- `EMAIL_BACKEND=resend`: API HTTP de Resend con `urllib` (sin dependencias). Requiere
  `RESEND_API_KEY`; remitente `EMAIL_FROM` (por defecto `onboarding@resend.dev`, que sin dominio
  verificado solo entrega al correo dueño de la cuenta de Resend).

Modo discreto (por defecto): asunto y texto genéricos, sin la marca ni palabras que revelen el
tema (mama, cáncer, autoexploración, análisis). Siempre lleva el enlace de baja.
"""

import json
import logging
import os
import urllib.error
import urllib.request
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


class ResendEmailSender:
    """Proveedor real. Un error de red o de Resend se convierte en EmailError (sin detalles)."""

    API_URL = "https://api.resend.com/emails"
    TIMEOUT_SECONDS = 10

    def __init__(self, api_key: str, sender: str):
        self.api_key = api_key
        self.sender = sender

    def send(self, message: EmailMessage) -> None:
        payload = {
            "from": f"{message.from_name} <{self.sender}>",
            "to": [message.to],
            "subject": message.subject,
            "text": message.body,
        }
        request = urllib.request.Request(
            self.API_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "User-Agent": "breastguard/1.0",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.TIMEOUT_SECONDS) as response:
                response.read()
        except urllib.error.HTTPError as exc:
            # Solo el código: la respuesta de Resend puede repetir la dirección de destino
            raise EmailError(f"Resend respondió {exc.code}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise EmailError(f"Resend no disponible ({type(exc).__name__})") from None
        logger.info("Correo (resend) para %s", mask(message.to))


def get_sender() -> EmailSender:
    backend = os.environ.get("EMAIL_BACKEND", "console")
    if backend == "console":
        return ConsoleEmailSender()
    if backend == "resend":
        api_key = os.environ.get("RESEND_API_KEY", "")
        if not api_key:
            raise EmailError("EMAIL_BACKEND=resend requiere RESEND_API_KEY")
        return ResendEmailSender(api_key, os.environ.get("EMAIL_FROM", "onboarding@resend.dev"))
    raise EmailError(f"EMAIL_BACKEND no soportado: {backend}")


INVITATION_SUBJECTS = {
    "invite": "Invitación a BreastGuard",
    "reset": "Restablece tu acceso a BreastGuard",
}
INVITATION_BODIES = {
    "invite": (
        "Hola, {name}:\n\nTe invitaron a BreastGuard ({institution}). Para activar tu cuenta, "
        "abre este enlace y elige tu contraseña. Vence en {hours} horas y solo sirve una vez:\n\n"
        "{url}\n\nSi no esperabas esta invitación, ignora este correo."
    ),
    "reset": (
        "Hola, {name}:\n\nSe restableció tu acceso a BreastGuard ({institution}). Abre este "
        "enlace para elegir una contraseña nueva. Vence en {hours} horas y solo sirve una vez:"
        "\n\n{url}\n\nSi no lo pediste, avisa al administrador de tu institución."
    ),
}


def compose_invitation(
    *, to: str, name: str, institution: str, purpose: str, url: str, hours: int
) -> EmailMessage:
    body = INVITATION_BODIES[purpose].format(
        name=name, institution=institution, url=url, hours=hours
    )
    return EmailMessage(
        to=to,
        subject=INVITATION_SUBJECTS[purpose],
        body=body,
        from_name="BreastGuard",
    )


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
