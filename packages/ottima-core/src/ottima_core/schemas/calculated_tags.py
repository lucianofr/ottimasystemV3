"""Schemas de tag calculada (RF-208, ADR-033): script Python + período fixo.

Validação de existência no banco (`project_id`, cada `input_tag_ids`) e validação de
conteúdo do script (`check_script_code`) ficam fora daqui — são responsabilidade do
router (wave 2), que já tem sessão de banco aberta.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

MAX_CALC_INPUTS = 8
# Scripts reais de tag calculada ficam na casa de dezenas de linhas; o teto protege
# compile()/ast.parse() de entrada patológica (RecursionError/MemoryError do parser do
# CPython em aninhamento profundo, achado da revisão de fase 5) sem apertar nenhum script
# real — mesmo espírito de MAX_FUZZY_FLL_LENGTH (flowgraph/parse.py).
MAX_CALC_SCRIPT_LENGTH = 20_000
PeriodSeconds = Literal[1, 2, 5, 10, 30, 60]


def _erro_ids_duplicados(input_tag_ids: list[int]) -> str | None:
    """A mesma tag em duas posições faz IN1/IN2 valerem o mesmo — quase sempre erro de
    digitação, e mascara a intenção de quais tags realmente alimentam o script."""
    if len(set(input_tag_ids)) != len(input_tag_ids):
        return "input_tag_ids não pode repetir a mesma tag em duas posições"
    return None


class CalculatedTagCreate(BaseModel):
    project_id: int
    name: str = Field(min_length=1)
    eu: str = ""
    description: str = ""
    period_seconds: PeriodSeconds
    code: str = Field(min_length=1, max_length=MAX_CALC_SCRIPT_LENGTH)
    input_tag_ids: list[int] = Field(default_factory=list, max_length=MAX_CALC_INPUTS)

    @model_validator(mode="after")
    def _sem_ids_duplicados(self) -> "CalculatedTagCreate":
        erro = _erro_ids_duplicados(self.input_tag_ids)
        if erro:
            raise ValueError(erro)
        return self


class CalculatedTagUpdate(BaseModel):
    """Atualização parcial; `project_id` está ausente de propósito — dono do id-space
    (RF-208) é imutável após a criação."""

    name: str | None = Field(default=None, min_length=1)
    eu: str | None = None
    description: str | None = None
    period_seconds: PeriodSeconds | None = None
    code: str | None = Field(default=None, min_length=1, max_length=MAX_CALC_SCRIPT_LENGTH)
    input_tag_ids: list[int] | None = Field(default=None, max_length=MAX_CALC_INPUTS)

    @model_validator(mode="after")
    def _sem_ids_duplicados(self) -> "CalculatedTagUpdate":
        if self.input_tag_ids is not None:
            erro = _erro_ids_duplicados(self.input_tag_ids)
            if erro:
                raise ValueError(erro)
        return self


class CalculatedTagOut(BaseModel):
    """Montado pelo router a partir de `Tag` + `CalculatedTag` + `CalculatedTagInput`
    ordenados por posição — não é `from_attributes` porque não existe um único objeto
    ORM com essa forma (a lista `input_tag_ids` cruza três tabelas)."""

    id: int
    project_id: int
    name: str
    eu: str
    description: str
    data_type: Literal["float"]
    period_seconds: PeriodSeconds
    code: str
    input_tag_ids: list[int]
    created_at: datetime
    updated_at: datetime
