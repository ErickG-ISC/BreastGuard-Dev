"""CU-05: próxima ejecución de recordatorios (función pura; sin base de datos)."""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from backend.app.services.reminder_schedule import (
    ScheduleError,
    add_months,
    first_sunday,
    next_run,
)

TIJUANA = "America/Tijuana"
MX = "America/Mexico_City"


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=UTC)


def local(tz: str, *args) -> datetime:
    return datetime(*args, tzinfo=ZoneInfo(tz))


def run(frequency, after, *, tz=MX, at=time(9, 0), n=None, anchor=date(2026, 1, 1)):
    return next_run(
        frequency=frequency, interval_n=n, local_time=at, tz_name=tz, anchor=anchor, after=after
    )


class TestPrimerDomingo:
    @pytest.mark.parametrize(
        ("year", "month", "expected"),
        [
            (2026, 2, date(2026, 2, 1)),  # el día 1 es domingo
            (2026, 6, date(2026, 6, 7)),  # el día 1 es lunes: cae en día 7
            (2026, 10, date(2026, 10, 4)),
            (2026, 11, date(2026, 11, 1)),
        ],
    )
    def test_primer_domingo(self, year, month, expected):
        assert first_sunday(year, month) == expected
        assert expected.weekday() == 6

    def test_el_del_mes_si_aun_no_pasa(self):
        after = local(MX, 2026, 10, 1, 8, 0)
        assert run("first_sunday", after) == local(MX, 2026, 10, 4, 9, 0)

    def test_el_del_mes_siguiente_si_ya_paso_la_hora(self):
        after = local(MX, 2026, 10, 4, 9, 30)
        assert run("first_sunday", after) == local(MX, 2026, 11, 1, 9, 0)

    def test_la_hora_exacta_cuenta_como_pasada(self):
        after = local(MX, 2026, 10, 4, 9, 0)
        assert run("first_sunday", after) == local(MX, 2026, 11, 1, 9, 0)

    def test_cambio_de_anio(self):
        after = local(MX, 2026, 12, 6, 10, 0)
        assert run("first_sunday", after) == local(MX, 2027, 1, 3, 9, 0)


class TestHorarioDeVeranoTijuana:
    def test_hora_inexistente_se_recorre_hacia_adelante(self):
        # 8 de marzo de 2026: a las 02:00 el reloj salta a las 03:00 (PST -8 → PDT -7)
        result = run(
            "every_n_days",
            utc(2026, 3, 7, 12),
            tz=TIJUANA,
            at=time(2, 30),
            n=1,
            anchor=date(2026, 3, 1),
        )
        assert result == utc(2026, 3, 8, 10, 30)
        assert result.astimezone(ZoneInfo(TIJUANA)).hour == 3

    def test_hora_ambigua_toma_la_primera_ocurrencia(self):
        # 1 de noviembre de 2026: la 01:30 ocurre dos veces; se toma la de PDT (-7)
        result = run("first_sunday", utc(2026, 10, 15), tz=TIJUANA, at=time(1, 30))
        assert result == utc(2026, 11, 1, 8, 30)

    def test_misma_hora_local_antes_y_despues_del_cambio(self):
        before = run("first_sunday", utc(2026, 2, 15), tz=TIJUANA)
        after = run("first_sunday", utc(2026, 3, 15), tz=TIJUANA)
        assert before == utc(2026, 3, 1, 17, 0)  # PST: 09:00 = 17:00 UTC
        assert after == utc(2026, 4, 5, 16, 0)  # PDT: 09:00 = 16:00 UTC
        for value in (before, after):
            assert value.astimezone(ZoneInfo(TIJUANA)).time() == time(9, 0)

    def test_ciudad_de_mexico_sin_horario_de_verano(self):
        assert run("first_sunday", utc(2026, 3, 15), tz=MX) == utc(2026, 4, 5, 15, 0)


class TestCadaNDias:
    def test_cadencia_desde_el_ancla(self):
        anchor = date(2026, 10, 1)
        after = local(MX, 2026, 10, 1, 10, 0)
        assert run("every_n_days", after, n=28, anchor=anchor) == local(MX, 2026, 10, 29, 9, 0)

    def test_el_mismo_dia_del_ancla_si_aun_no_es_la_hora(self):
        anchor = date(2026, 10, 1)
        after = local(MX, 2026, 10, 1, 8, 0)
        assert run("every_n_days", after, n=7, anchor=anchor) == local(MX, 2026, 10, 1, 9, 0)

    def test_tras_dormir_meses_da_una_sola_ocurrencia_futura(self):
        anchor = date(2026, 1, 1)
        after = local(MX, 2026, 10, 22, 12, 0)
        result = run("every_n_days", after, n=14, anchor=anchor)
        assert result > after
        assert result - after <= timedelta(days=14)
        assert (result.astimezone(ZoneInfo(MX)).date() - anchor).days % 14 == 0


class TestCadaNMeses:
    @pytest.mark.parametrize(
        ("day", "months", "expected"),
        [
            (date(2026, 1, 31), 1, date(2026, 2, 28)),
            (date(2028, 1, 31), 1, date(2028, 2, 29)),  # bisiesto
            (date(2026, 1, 31), 2, date(2026, 3, 31)),
            (date(2026, 8, 31), 1, date(2026, 9, 30)),
            (date(2026, 11, 15), 3, date(2027, 2, 15)),
        ],
    )
    def test_add_months(self, day, months, expected):
        assert add_months(day, months, day.day) == expected

    def test_meses_cortos_no_arrastran_el_dia(self):
        anchor = date(2026, 1, 31)
        feb = run("every_n_months", local(MX, 2026, 2, 1), n=1, anchor=anchor)
        assert feb == local(MX, 2026, 2, 28, 9, 0)
        # Después de febrero vuelve al 31, no se queda en 28
        mar = run("every_n_months", feb, n=1, anchor=anchor)
        assert mar == local(MX, 2026, 3, 31, 9, 0)

    def test_cada_seis_meses(self):
        anchor = date(2026, 4, 10)
        result = run("every_n_months", local(MX, 2026, 4, 10, 9, 0), n=6, anchor=anchor)
        assert result == local(MX, 2026, 10, 10, 9, 0)

    def test_tras_dormir_anios_da_una_sola_ocurrencia_futura(self):
        anchor = date(2020, 5, 31)
        after = local(MX, 2026, 10, 22)
        assert run("every_n_months", after, n=6, anchor=anchor) == local(MX, 2026, 11, 30, 9, 0)


class TestValidacion:
    @pytest.mark.parametrize("tz", ["Mars/Base", "../../etc/passwd", "", "america/tijuana"])
    def test_zona_desconocida(self, tz):
        with pytest.raises(ScheduleError):
            run("first_sunday", utc(2026, 1, 1), tz=tz)

    @pytest.mark.parametrize("frequency", ["every_n_days", "every_n_months"])
    @pytest.mark.parametrize("n", [None, 0, -1])
    def test_intervalo_obligatorio(self, frequency, n):
        with pytest.raises(ScheduleError):
            run(frequency, utc(2026, 1, 1), n=n)

    def test_frecuencia_desconocida(self):
        with pytest.raises(ScheduleError):
            run("weekly", utc(2026, 1, 1))

    def test_after_sin_zona_horaria(self):
        with pytest.raises(ScheduleError):
            run("first_sunday", datetime(2026, 1, 1))

    def test_siempre_devuelve_utc(self):
        assert run("first_sunday", utc(2026, 1, 1), tz=TIJUANA).tzinfo == UTC
