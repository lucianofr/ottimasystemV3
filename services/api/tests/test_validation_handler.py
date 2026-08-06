"""Handler global de `RequestValidationError` (spec F5 §4.3-1, plano F5a tarefa 0.3).

Todo 422 de forma (corpo/query/path reprovados pelo schema Pydantic) tem de sair
`{"detail": "<string única pt-BR>"}` — mesmo contrato dos 422 de domínio (padrão `api.ts`,
ver test_flows.py::_mensagem). O FastAPI hoje vaza a lista `[{loc, msg, type}, ...]`; este
handler pega só o primeiro erro e traduz.
"""


async def _cenario(client, admin_headers, nome: str) -> tuple[int, str]:
    """Flow salvo com um bloco `mpc` mínimo — mesmo esqueleto de test_operate.py::_cenario,
    mas só o suficiente pra rota `/mode` existir (a reprovação de forma nunca chega no corpo
    da rota, então o grafo não precisa ser MPC de verdade)."""
    r = await client.post("/api/projects", json={"name": nome}, headers=admin_headers)
    assert r.status_code == 201, r.text
    project_id = r.json()["id"]
    r = await client.post(
        "/api/connections",
        json={"project_id": project_id, "name": "c1", "endpoint": "opc.tcp://h:4840"},
        headers=admin_headers,
    )
    assert r.status_code == 201, r.text
    r = await client.post(
        "/api/flows",
        json={"project_id": project_id, "name": "f1", "ts_seconds": 1},
        headers=admin_headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"], "m1"


async def test_axis_invalido_detail_string_traduzida(client, admin_headers, operator_headers):
    """Eixo fora de `local_remote|man_auto` — `literal_error` do Pydantic vira string pt-BR."""
    flow_id, block_id = await _cenario(client, admin_headers, "AxisInvalido")
    r = await client.post(
        f"/api/operate/{flow_id}/{block_id}/mode",
        json={"axis": "temperatura", "value": "remote"},
        headers=operator_headers,
    )
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert isinstance(detail, str), detail
    assert detail == "body.axis: valor inválido; esperado um de: local_remote, man_auto"


async def test_campo_obrigatorio_ausente_detail_string_traduzida(
    client, admin_headers, operator_headers
):
    """`value` ausente do corpo — `missing` do Pydantic vira string pt-BR."""
    flow_id, block_id = await _cenario(client, admin_headers, "ValueAusente")
    r = await client.post(
        f"/api/operate/{flow_id}/{block_id}/mode",
        json={"axis": "local_remote"},
        headers=operator_headers,
    )
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert isinstance(detail, str), detail
    assert detail == "body.value: campo obrigatório"


async def test_duas_reprovacoes_usa_so_a_primeira(client, admin_headers, operator_headers):
    """`axis` e `value` reprovados juntos: `detail` traz só o primeiro erro (ordem dos campos
    do schema `ModeCommand`), nunca a lista inteira."""
    flow_id, block_id = await _cenario(client, admin_headers, "DuasReprovacoes")
    r = await client.post(
        f"/api/operate/{flow_id}/{block_id}/mode",
        json={"axis": "temperatura", "value": "ligado"},
        headers=operator_headers,
    )
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert isinstance(detail, str), detail
    assert detail == "body.axis: valor inválido; esperado um de: local_remote, man_auto"
