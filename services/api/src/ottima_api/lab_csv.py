"""Parser do CSV de análises de laboratório (RF-585, spec do sensor virtual §7.2).

Função pura: bytes entram, linhas validadas saem. Qualquer problema recusa o arquivo inteiro
(nada é importado pela metade); a rota transforma `LabCsvError.problems` em 422.
"""

import csv
import io
import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

MAX_LAB_CSV_BYTES = 5 * 1024 * 1024  # teto aplicado pela rota (413), antes de chamar o parser
MAX_PROBLEMS = 50

_BR_FORMATS = ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M")


@dataclass(frozen=True)
class LabCsvRow:
    variable_id: int
    sampled_at: datetime  # UTC aware
    value: float


class LabCsvError(ValueError):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


class _FusoInvalido(Exception):
    """O fuso do cliente não existe: vale para o arquivo inteiro, não para uma linha."""


def _number(text: str) -> float | None:
    # "1.234,5" (milhar + decimal) é ambíguo: recusa em vez de adivinhar. float() aceitaria "1_0".
    if "_" in text or ("," in text and "." in text):
        return None
    try:
        return float(text.replace(",", "."))
    except ValueError:
        return None


def _instant(text: str, tz: str) -> datetime | None:
    for fmt in _BR_FORMATS:
        try:
            when = datetime.strptime(text, fmt)
            break
        except ValueError:
            continue
    else:
        try:
            when = datetime.fromisoformat(text)
        except ValueError:
            return None
    if when.tzinfo is None:
        try:
            when = when.replace(tzinfo=ZoneInfo(tz))
        except (KeyError, ValueError, OSError) as e:
            raise _FusoInvalido from e
    try:
        return when.astimezone(UTC)
    except OverflowError:  # ex.: 9999-12-31 com offset negativo estoura o limite do datetime
        return None


def _row(cells: list[str], known: Mapping[str, int], tz: str, now: datetime) -> LabCsvRow | str:
    """Devolve a linha válida ou o motivo (só o primeiro problema da linha)."""
    if len(cells) != 3:
        return f"esperadas 3 colunas, encontradas {len(cells)}"
    name, when, raw = cells
    if name not in known:
        return f"variável de laboratório {name!r} não existe no projeto ativo"
    instant = _instant(when, tz)
    if instant is None:
        return f"data/hora {when!r} ilegível (use dd/mm/aaaa hh:mm ou ISO-8601)"
    if instant > now:
        return f"data/hora {when!r} é posterior ao momento atual"
    value = _number(raw)
    if value is None or not math.isfinite(value):
        return f"valor {raw!r} não é um número finito"
    return LabCsvRow(known[name], instant, value)


def parse_lab_csv(
    data: bytes, *, tz: str, known: Mapping[str, int], now: datetime
) -> list[LabCsvRow]:
    """`known` mapeia nome da variável -> id; `tz` é o fuso IANA do cliente; `now` é aware."""
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        line = data.count(b"\n", 0, e.start) + 1
        raise LabCsvError([f"linha {line}: arquivo não está em UTF-8"]) from e

    problems: list[str] = []
    rows: dict[tuple[int, datetime], LabCsvRow] = {}  # mesma variável e instante: vale a última
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=";")
    first = True
    last_line = 0
    try:
        for raw_cells in reader:
            start, last_line = (
                last_line + 1,
                reader.line_num,
            )  # registro entre aspas pode ter várias linhas
            cells = [c.strip() for c in raw_cells]
            if not any(cells):
                continue
            if first:
                first = False
                if len(cells) == 3 and _number(cells[2]) is None:
                    continue  # cabeçalho
            try:
                row = _row(cells, known, tz, now)
            except _FusoInvalido:
                problems.append(f"linha {start}: fuso horário {tz!r} inválido")
                break
            if isinstance(row, str):
                problems.append(f"linha {start}: {row}")
                if len(problems) >= MAX_PROBLEMS:
                    break
            else:
                rows[row.variable_id, row.sampled_at] = row
    except csv.Error:  # ex.: campo acima do limite do módulo csv
        problems.append(f"linha {last_line + 1}: CSV malformado")

    if problems:
        raise LabCsvError(problems)
    return list(rows.values())
