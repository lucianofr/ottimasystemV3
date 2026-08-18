async def _criar(client, headers, name: str) -> dict:
    r = await client.post("/api/projects", json={"name": name}, headers=headers)
    assert r.status_code == 201
    return r.json()


async def test_crud_basico_e_papeis(client, admin_headers, operator_headers):
    p = await _criar(client, admin_headers, "Planta A")
    assert p["is_active"] is False  # projetos nascem inativos (ADR-017)
    r = await client.get("/api/projects", headers=operator_headers)
    assert r.status_code == 200 and len(r.json()) == 1  # operador enxerga tudo
    assert (
        await client.post("/api/projects", json={"name": "X"}, headers=operator_headers)
    ).status_code == 403


async def test_ativacao_e_troca_atomica(client, admin_headers):
    a = await _criar(client, admin_headers, "A")
    b = await _criar(client, admin_headers, "B")
    assert (
        await client.post(f"/api/projects/{a['id']}/activate", headers=admin_headers)
    ).status_code == 200
    assert (
        await client.post(f"/api/projects/{b['id']}/activate", headers=admin_headers)
    ).status_code == 200
    projetos = (await client.get("/api/projects", headers=admin_headers)).json()
    ativos = [p for p in projetos if p["is_active"]]
    assert len(ativos) == 1 and ativos[0]["id"] == b["id"]  # nunca 2 ativos (ADR-017)


async def test_delete_de_projeto_ativo_409(client, admin_headers):
    p = await _criar(client, admin_headers, "Ativo")
    await client.post(f"/api/projects/{p['id']}/activate", headers=admin_headers)
    r = await client.delete(f"/api/projects/{p['id']}", headers=admin_headers)
    assert r.status_code == 409
    assert r.json()["detail"] == "Desative o projeto antes de excluí-lo"


async def test_delete_cascateia_conexoes(client, admin_headers):
    p = await _criar(client, admin_headers, "ComConexao")
    c = await client.post(
        "/api/connections",
        json={"project_id": p["id"], "name": "plc1", "endpoint": "opc.tcp://10.0.0.5:4840"},
        headers=admin_headers,
    )
    assert c.status_code == 201
    apagado = await client.delete(f"/api/projects/{p['id']}", headers=admin_headers)
    assert apagado.status_code == 204
    r = await client.get(f"/api/connections?project_id={p['id']}", headers=admin_headers)
    assert r.json() == []

async def test_delete_cascateia_tag_calculada_com_entradas(client, admin_headers):
    """Regressão: tag calculada consumindo tag OPC do MESMO projeto não pode virar 500 no
    DELETE do projeto. O RESTRICT de `calculated_tag_inputs.source_tag_id` é deliberado
    (impede apagar uma tag que alimenta um script); a API garante input do mesmo projeto
    (`_validar_entradas`), então as arestas de input saem junto e o cascade do banco flui."""
    p = await _criar(client, admin_headers, "ComCalcInput")
    c = await client.post(
        "/api/connections",
        json={"project_id": p["id"], "name": "plc-calc", "endpoint": "opc.tcp://10.0.0.6:4840"},
        headers=admin_headers,
    )
    assert c.status_code == 201
    opc = await client.post(
        "/api/tags",
        json={
            "connection_id": c.json()["id"],
            "name": "FT-CALC",
            "node_id": "ns=2;s=FT-CALC",
            "direction": "r",
            "data_type": "float",
        },
        headers=admin_headers,
    )
    assert opc.status_code == 201
    calc1 = await client.post(
        "/api/calculated-tags",
        json={
            "project_id": p["id"],
            "name": "CALC-1",
            "period_seconds": 1,
            "code": "OUT = IN1",
            "input_tag_ids": [opc.json()["id"]],
        },
        headers=admin_headers,
    )
    assert calc1.status_code == 201, calc1.text
    calc2 = await client.post(
        "/api/calculated-tags",
        json={
            "project_id": p["id"],
            "name": "CALC-2",
            "period_seconds": 1,
            "code": "OUT = IN1 + 1.0",
            "input_tag_ids": [calc1.json()["id"]],
        },
        headers=admin_headers,
    )
    assert calc2.status_code == 201, calc2.text
    opc_id, calc1_id = opc.json()["id"], calc1.json()["id"]

    apagado = await client.delete(f"/api/projects/{p['id']}", headers=admin_headers)
    assert apagado.status_code == 204
    # Cascade completo: conexão, tags (OPC e calculadas) e arestas de input somem juntas.
    conexoes = await client.get(f"/api/connections?project_id={p['id']}", headers=admin_headers)
    assert conexoes.json() == []
    calcs = await client.get(f"/api/calculated-tags?project_id={p['id']}", headers=admin_headers)
    assert calcs.json() == []
    assert (await client.get(f"/api/tags/{opc_id}", headers=admin_headers)).status_code == 404
    assert (
        await client.get(f"/api/calculated-tags/{calc1_id}", headers=admin_headers)
    ).status_code == 404


async def test_nome_duplicado_409_e_404(client, admin_headers):
    await _criar(client, admin_headers, "Unico")
    r = await client.post("/api/projects", json={"name": "Unico"}, headers=admin_headers)
    assert r.status_code == 409
    assert (await client.get("/api/projects/99999", headers=admin_headers)).status_code == 404


async def test_ativacao_de_projeto_diferente_publica_o_evento(client, admin_headers, eventos):
    """A troca real é a dica de reconciliação que o worker e o runtime consomem (RF-101)."""
    a = await _criar(client, admin_headers, "EvtA")
    b = await _criar(client, admin_headers, "EvtB")
    assert (
        await client.post(f"/api/projects/{a['id']}/activate", headers=admin_headers)
    ).status_code == 200
    await eventos()  # consome o evento da primeira ativação

    r = await client.post(f"/api/projects/{b['id']}/activate", headers=admin_headers)
    assert r.status_code == 200
    (ev,) = await eventos()
    assert ev["payload"] == {"kind": "project_activated", "project_id": b["id"], "name": "EvtB"}


async def test_reativar_o_projeto_ja_ativo_nao_publica_evento(client, admin_headers, eventos):
    """Desde a F3 este evento é destrutivo: o supervisor do flow-runtime para TODOS os flows
    rodando ao recebê-lo (spec §2.2-8, gancho RF-101). Reativar quem já é o ativo não é
    transição, então não pode republicar — senão um clique redundante em "ativar" derruba a
    planta em silêncio. A rota segue idempotente no contrato HTTP.
    """
    p = await _criar(client, admin_headers, "JaAtivo")
    assert (
        await client.post(f"/api/projects/{p['id']}/activate", headers=admin_headers)
    ).status_code == 200
    await eventos()  # consome o evento da ativação real

    r = await client.post(f"/api/projects/{p['id']}/activate", headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["is_active"] is True
    assert await eventos() == []


async def test_ativacao_zera_desired_state_dos_flows(client, admin_headers):
    """Ativar um projeto zera o estado desejado de **todos** os flows: após a troca, nada
    pode ficar "Rodando — aguardando confirmação" de projeto que não é o ativo, e nenhum
    flow pode ser auto-ativado por retomada/reconciliação a partir de um `desired_state`
    órfão (ADR-017: boot parado, comando manual sempre vence). O runtime já para a
    execução (`flow_stopped`/`project_activated`); a ativação alinha o desejado ao efeito.
    """
    a = await _criar(client, admin_headers, "Origem")
    b = await _criar(client, admin_headers, "Destino")
    flows = []
    for pid, nome in ((a["id"], "F-A"), (b["id"], "F-B")):
        r = await client.post(
            "/api/flows",
            json={"project_id": pid, "name": nome, "ts_seconds": 1},
            headers=admin_headers,
        )
        assert r.status_code == 201, r.text
        flows.append(r.json()["id"])
        # /deploy grava desired_state=running (intenção); o runtime de teste não sobe nada.
        d = await client.post(f"/api/flows/{flows[-1]}/deploy", headers=admin_headers)
        assert d.status_code == 202, d.text

    r = await client.post(f"/api/projects/{b['id']}/activate", headers=admin_headers)
    assert r.status_code == 200, r.text

    detalhe = (await client.get(f"/api/flows/{flows[0]}", headers=admin_headers)).json()
    assert detalhe["desired_state"] == "stopped"  # flow do projeto anterior: parou de fato
    detalhe = (await client.get(f"/api/flows/{flows[1]}", headers=admin_headers)).json()
    assert detalhe["desired_state"] == "stopped"  # nem o do projeto novo auto-ativa


async def test_reativar_o_projeto_ativo_nao_zera_desired_state(client, admin_headers):
    """Reativar o projeto que já é o ativo não é transição: o evento não sai e o runtime não
    para nada — logo o desejado também não pode ser zerado, senão um clique redundante deixa
    a planta em operação "Parado — aguardando confirmação" para sempre e desarma em
    silêncio a retomada automática (TD-005/ADR-025), que exige `desired_state` 'running'.
    """
    p = await _criar(client, admin_headers, "Vigente")
    r = await client.post(
        "/api/flows",
        json={"project_id": p["id"], "name": "F", "ts_seconds": 1},
        headers=admin_headers,
    )
    assert r.status_code == 201, r.text
    flow_id = r.json()["id"]
    r = await client.post(f"/api/projects/{p['id']}/activate", headers=admin_headers)
    assert r.status_code == 200, r.text
    d = await client.post(f"/api/flows/{flow_id}/deploy", headers=admin_headers)
    assert d.status_code == 202, d.text

    r = await client.post(f"/api/projects/{p['id']}/activate", headers=admin_headers)
    assert r.status_code == 200, r.text

    detalhe = (await client.get(f"/api/flows/{flow_id}", headers=admin_headers)).json()
    assert detalhe["desired_state"] == "running"  # clique redundante não muda nada
