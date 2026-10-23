"""Cálculo de la próxima ejecución de un recordatorio (CU-05). Funciones puras, sin base.

Las fechas se calculan en la zona horaria IANA de la paciente y se devuelven en UTC.

Reglas:
- `first_sunday`: el primer domingo de cada mes, a la hora local configurada.
- `every_n_days`: cada N días contados desde la fecha ancla (cadencia estable).
- `every_n_months`: el mismo día del mes que la fecha ancla, cada N meses; si el mes es más
  corto, el último día de ese mes (31 de enero + 1 mes → 28 o 29 de febrero).

Cambios de horario: una hora local que no existe (el salto de primavera, p. ej. 02:30 en
America/Tijuana) se recorre hacia adelante el tamaño del salto; una hora ambigua (el regreso
de otoño) toma la primera ocurrencia. Es lo que hace zoneinfo con `fold=0`.

Siempre se devuelve la PRIMERA ocurrencia estrictamente posterior a `after`: si el despachador
estuvo dormido y se perdieron varias, no se generan ráfagas de avisos atrasados.
"""

import calendar
from datetime import UTC, date, datetime, time, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

FREQUENCIES = ("first_sunday", "every_n_days", "every_n_months")
# Límite de seguridad para los bucles (un recordatorio mensual nunca necesita tantos pasos)
_MAX_STEPS = 1000


class ScheduleError(ValueError):
    pass


@lru_cache
def _valid_zones() -> frozenset[str]:
    return frozenset(available_timezones())


def zone(name: str) -> ZoneInfo:
    """ZoneInfo de un nombre IANA válido; rechaza rutas y nombres desconocidos."""
    if name not in _valid_zones():
        raise ScheduleError(f"Zona horaria desconocida: {name}")
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        raise ScheduleError(f"Zona horaria desconocida: {name}") from None


def at_local(day: date, local_time: time, tz: ZoneInfo) -> datetime:
    """Instante UTC de `day` a `local_time` en `tz` (huecos hacia adelante, ambigüedad: primera)."""
    local = datetime.combine(day, local_time.replace(tzinfo=None, fold=0), tzinfo=tz)
    return local.astimezone(UTC)


def first_sunday(year: int, month: int) -> date:
    first = date(year, month, 1)
    return first + timedelta(days=(6 - first.weekday()) % 7)


def add_months(day: date, months: int, anchor_day: int) -> date:
    """`day` + `months` meses, con el día del ancla ajustado al último día del mes destino."""
    index = day.year * 12 + (day.month - 1) + months
    year, month = divmod(index, 12)
    month += 1
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(anchor_day, last))


def next_run(
    *,
    frequency: str,
    interval_n: int | None,
    local_time: time,
    tz_name: str,
    anchor: date,
    after: datetime,
) -> datetime:
    """Primera ocurrencia (en UTC) estrictamente posterior a `after`."""
    if after.tzinfo is None:
        raise ScheduleError("`after` debe tener zona horaria")
    tz = zone(tz_name)
    after_local_day = after.astimezone(tz).date()

    if frequency == "first_sunday":
        year, month = after_local_day.year, after_local_day.month
        for _ in range(_MAX_STEPS):
            candidate = at_local(first_sunday(year, month), local_time, tz)
            if candidate > after:
                return candidate
            year, month = (year + 1, 1) if month == 12 else (year, month + 1)

    elif frequency == "every_n_days":
        if not interval_n or interval_n < 1:
            raise ScheduleError("every_n_days requiere interval_n >= 1")
        # Salta directo cerca de `after` y avanza de N en N
        elapsed = (after_local_day - anchor).days
        steps = max(0, elapsed // interval_n - 1)
        day = anchor + timedelta(days=steps * interval_n)
        for _ in range(_MAX_STEPS):
            candidate = at_local(day, local_time, tz)
            if candidate > after:
                return candidate
            day += timedelta(days=interval_n)

    elif frequency == "every_n_months":
        if not interval_n or interval_n < 1:
            raise ScheduleError("every_n_months requiere interval_n >= 1")
        months_elapsed = (after_local_day.year - anchor.year) * 12 + (
            after_local_day.month - anchor.month
        )
        k = max(0, months_elapsed // interval_n - 1)
        for _ in range(_MAX_STEPS):
            candidate = at_local(add_months(anchor, k * interval_n, anchor.day), local_time, tz)
            if candidate > after:
                return candidate
            k += 1

    else:
        raise ScheduleError(f"Frecuencia desconocida: {frequency}")

    raise ScheduleError("No se encontró una próxima ejecución")  # pragma: no cover
