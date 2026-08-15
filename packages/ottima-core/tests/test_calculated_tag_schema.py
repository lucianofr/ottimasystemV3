"""Testes dos schemas de tag calculada (RF-208, ADR-033): validação pura, sem banco."""

import pytest
from pydantic import ValidationError

from ottima_core.schemas.calculated_tags import (
    MAX_CALC_INPUTS,
    MAX_CALC_SCRIPT_LENGTH,
    CalculatedTagCreate,
    CalculatedTagUpdate,
)
from ottima_core.schemas.tags import TagOut


def _dados(**overrides):
    dados = {
        "project_id": 1,
        "name": "vazao_total",
        "period_seconds": 5,
        "code": "OUT = IN1 + IN2",
        "input_tag_ids": [10, 20],
    }
    dados.update(overrides)
    return dados


def test_input_tag_ids_duplicado_reprova_no_create():
    with pytest.raises(ValidationError):
        CalculatedTagCreate(**_dados(input_tag_ids=[10, 10]))


def test_input_tag_ids_duplicado_reprova_no_update():
    with pytest.raises(ValidationError):
        CalculatedTagUpdate(input_tag_ids=[10, 10])


def test_input_tag_ids_acima_do_teto_reprova():
    with pytest.raises(ValidationError):
        CalculatedTagCreate(**_dados(input_tag_ids=list(range(1, MAX_CALC_INPUTS + 2))))


def test_input_tag_ids_no_teto_e_aceito():
    tag = CalculatedTagCreate(**_dados(input_tag_ids=list(range(1, MAX_CALC_INPUTS + 1))))
    assert len(tag.input_tag_ids) == MAX_CALC_INPUTS


def test_code_acima_do_teto_reprova():
    with pytest.raises(ValidationError):
        CalculatedTagCreate(**_dados(code="x" * (MAX_CALC_SCRIPT_LENGTH + 1)))


def test_code_no_teto_e_aceito():
    tag = CalculatedTagCreate(**_dados(code="OUT=1" + " " * (MAX_CALC_SCRIPT_LENGTH - 5)))
    assert len(tag.code) == MAX_CALC_SCRIPT_LENGTH


def test_update_code_acima_do_teto_reprova():
    with pytest.raises(ValidationError):
        CalculatedTagUpdate(code="x" * (MAX_CALC_SCRIPT_LENGTH + 1))


@pytest.mark.parametrize("period_seconds", [0, 3, 7, 15, 45, 61, 120])
def test_period_seconds_fora_do_conjunto_permitido_reprova(period_seconds):
    with pytest.raises(ValidationError):
        CalculatedTagCreate(**_dados(period_seconds=period_seconds))


@pytest.mark.parametrize("period_seconds", [1, 2, 5, 10, 30, 60])
def test_period_seconds_permitido_e_aceito(period_seconds):
    tag = CalculatedTagCreate(**_dados(period_seconds=period_seconds))
    assert tag.period_seconds == period_seconds


def test_update_sem_nenhum_campo_nao_produz_alteracao():
    assert CalculatedTagUpdate().model_dump(exclude_unset=True) == {}


def test_update_aceita_alteracao_parcial_so_do_code():
    upd = CalculatedTagUpdate(code="OUT = IN1 * 2")
    assert upd.model_dump(exclude_unset=True) == {"code": "OUT = IN1 * 2"}


def test_tag_out_aceita_tag_calculada_sem_connection_nem_node():
    tag = TagOut(
        id=1,
        connection_id=None,
        node_id=None,
        project_id=7,
        name="vazao_total",
        direction="r",
        data_type="float",
        eu="m3/h",
        description="",
        created_at="2024-01-01T00:00:00Z",
        updated_at="2024-01-01T00:00:00Z",
    )
    assert tag.project_id == 7
    assert tag.connection_id is None
    assert tag.node_id is None


def test_tag_out_aceita_tag_opc_classica():
    tag = TagOut(
        id=2,
        connection_id=5,
        node_id="ns=1;s=t1",
        project_id=None,
        name="t1",
        direction="r",
        data_type="float",
        eu="",
        description="",
        created_at="2024-01-01T00:00:00Z",
        updated_at="2024-01-01T00:00:00Z",
    )
    assert tag.connection_id == 5
    assert tag.node_id == "ns=1;s=t1"
    assert tag.project_id is None
