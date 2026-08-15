"""Testes de tags calculadas (RF-208, ADR-033): CRUD, validação de script e cascata de FK."""


async def _projeto(client, headers, name: str) -> dict:
    r = await client.post("/api/projects", json={"name": name}, headers=headers)
    assert r.status_code == 201
    return r.json()


async def _tag_opc(client, headers, project_id: int, name: str) -> dict:
    """Tag OPC de origem: conexão dedicada por chamada, nome sem colisão entre testes."""
    c = await client.post(
        "/api/connections",
        json={"project_id": project_id, "name": f"conn-{name}", "endpoint": "opc.tcp://x:4840"},
        headers=headers,
    )
    assert c.status_code == 201
    t = await client.post(
        "/api/tags",
        json={
            "connection_id": c.json()["id"],
            "name": name,
            "node_id": f"ns=2;s={name}",
            "direction": "r",
            "data_type": "float",
        },
        headers=headers,
    )
    assert t.status_code == 201
    return t.json()


def _codigo_soma(n: int) -> str:
    if n == 0:
        return "OUT = 1.0"
    return "OUT = " + " + ".join(f"IN{i}" for i in range(1, n + 1))


def _corpo_calc(project_id: int, name: str, input_tag_ids: list[int], **overrides) -> dict:
    corpo = {
        "project_id": project_id,
        "name": name,
        "period_seconds": 1,
        "code": _codigo_soma(len(input_tag_ids)),
        "input_tag_ids": input_tag_ids,
    }
    corpo.update(overrides)
    return corpo


async def test_cria_lista_ordem_e_aparece_em_tags(client, admin_headers, operator_headers):
    p = await _projeto(client, admin_headers, "CalcProj")
    t1 = await _tag_opc(client, admin_headers, p["id"], "FT-101")
    t2 = await _tag_opc(client, admin_headers, p["id"], "FT-102")
    corpo = _corpo_calc(
        p["id"], "SomaVazao", [t2["id"], t1["id"]], eu="m3/h", period_seconds=5
    )  # ordem proposital invertida
    r = await client.post("/api/calculated-tags", json=corpo, headers=admin_headers)
    assert r.status_code == 201, r.text
    saida = r.json()
    assert saida["input_tag_ids"] == [t2["id"], t1["id"]]
    assert saida["project_id"] == p["id"]
    assert saida["period_seconds"] == 5
    assert saida["data_type"] == "float"

    listadas = (await client.get("/api/tags", headers=operator_headers)).json()
    calc = next(t for t in listadas if t["id"] == saida["id"])
    assert calc["connection_id"] is None
    assert calc["project_id"] == p["id"]
    assert calc["direction"] == "r"
    assert calc["data_type"] == "float"
    assert calc["node_id"] is None


async def test_nome_duplicado_mesmo_projeto_409(client, admin_headers):
    p = await _projeto(client, admin_headers, "Dup")
    corpo = _corpo_calc(p["id"], "Calc1", [])
    assert (
        await client.post("/api/calculated-tags", json=corpo, headers=admin_headers)
    ).status_code == 201
    r = await client.post("/api/calculated-tags", json=corpo, headers=admin_headers)
    assert r.status_code == 409
    assert r.json()["detail"] == "Nome de tag já em uso neste projeto"


async def test_nome_igual_em_projetos_diferentes_201(client, admin_headers):
    a = await _projeto(client, admin_headers, "ProjA")
    b = await _projeto(client, admin_headers, "ProjB")
    assert (
        await client.post(
            "/api/calculated-tags", json=_corpo_calc(a["id"], "Igual", []), headers=admin_headers
        )
    ).status_code == 201
    assert (
        await client.post(
            "/api/calculated-tags", json=_corpo_calc(b["id"], "Igual", []), headers=admin_headers
        )
    ).status_code == 201


async def test_in_fora_do_alcance_422(client, admin_headers):
    p = await _projeto(client, admin_headers, "OffByOne")
    t1 = await _tag_opc(client, admin_headers, p["id"], "A")
    t2 = await _tag_opc(client, admin_headers, p["id"], "B")
    corpo = _corpo_calc(p["id"], "Calc", [t1["id"], t2["id"]], code="OUT = IN3")
    r = await client.post("/api/calculated-tags", json=corpo, headers=admin_headers)
    assert r.status_code == 422
    assert "IN3" in r.json()["detail"]


async def test_sem_out_422(client, admin_headers):
    p = await _projeto(client, admin_headers, "SemOut")
    corpo = _corpo_calc(p["id"], "Calc", [], code="x = 1.0")
    r = await client.post("/api/calculated-tags", json=corpo, headers=admin_headers)
    assert r.status_code == 422
    assert "OUT" in r.json()["detail"]


async def test_syntax_error_422(client, admin_headers):
    p = await _projeto(client, admin_headers, "Sintaxe")
    corpo = _corpo_calc(p["id"], "Calc", [], code="OUT = (1 +")
    r = await client.post("/api/calculated-tags", json=corpo, headers=admin_headers)
    assert r.status_code == 422
    assert "sintaxe" in r.json()["detail"].lower()


async def test_dunder_422(client, admin_headers):
    p = await _projeto(client, admin_headers, "Dunder")
    corpo = _corpo_calc(p["id"], "Calc", [], code="OUT = ().__class__")
    r = await client.post("/api/calculated-tags", json=corpo, headers=admin_headers)
    assert r.status_code == 422
    assert "dunder" in r.json()["detail"].lower()


async def test_entrada_de_outro_projeto_422(client, admin_headers):
    a = await _projeto(client, admin_headers, "Origem")
    b = await _projeto(client, admin_headers, "Destino")
    tag_a = await _tag_opc(client, admin_headers, a["id"], "FT-1")
    corpo = _corpo_calc(b["id"], "Calc", [tag_a["id"]], code="OUT = IN1")
    r = await client.post("/api/calculated-tags", json=corpo, headers=admin_headers)
    assert r.status_code == 422


async def test_patch_entrada_igual_a_propria_tag_422_nao_409(client, admin_headers):
    p = await _projeto(client, admin_headers, "AutoRef")
    corpo = _corpo_calc(p["id"], "Calc", [])
    criado = (await client.post("/api/calculated-tags", json=corpo, headers=admin_headers)).json()
    r = await client.patch(
        f"/api/calculated-tags/{criado['id']}",
        json={"input_tag_ids": [criado["id"]]},
        headers=admin_headers,
    )
    assert r.status_code == 422, r.text
    assert "si mesma" in r.json()["detail"].lower()


async def test_patch_substitui_entradas_reordena(client, admin_headers):
    p = await _projeto(client, admin_headers, "PatchReorder")
    t1 = await _tag_opc(client, admin_headers, p["id"], "A")
    t2 = await _tag_opc(client, admin_headers, p["id"], "B")
    corpo = _corpo_calc(p["id"], "Calc", [t1["id"], t2["id"]])
    criado = (await client.post("/api/calculated-tags", json=corpo, headers=admin_headers)).json()
    assert criado["input_tag_ids"] == [t1["id"], t2["id"]]

    r = await client.patch(
        f"/api/calculated-tags/{criado['id']}",
        json={"input_tag_ids": [t2["id"], t1["id"]]},
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["input_tag_ids"] == [t2["id"], t1["id"]]


async def test_patch_sem_input_tag_ids_preserva(client, admin_headers):
    p = await _projeto(client, admin_headers, "PatchPreserva")
    t1 = await _tag_opc(client, admin_headers, p["id"], "A")
    corpo = _corpo_calc(p["id"], "Calc", [t1["id"]])
    criado = (await client.post("/api/calculated-tags", json=corpo, headers=admin_headers)).json()

    r = await client.patch(
        f"/api/calculated-tags/{criado['id']}", json={"eu": "kg"}, headers=admin_headers
    )
    assert r.status_code == 200, r.text
    assert r.json()["input_tag_ids"] == [t1["id"]]
    assert r.json()["eu"] == "kg"


async def test_delete_tag_opc_usada_como_entrada_409(client, admin_headers):
    p = await _projeto(client, admin_headers, "DelOpc")
    t1 = await _tag_opc(client, admin_headers, p["id"], "A")
    corpo = _corpo_calc(p["id"], "Calc", [t1["id"]])
    assert (
        await client.post("/api/calculated-tags", json=corpo, headers=admin_headers)
    ).status_code == 201

    r = await client.delete(f"/api/tags/{t1['id']}", headers=admin_headers)
    assert r.status_code == 409
    assert r.json()["detail"] == "Tag é entrada de uma tag calculada e não pode ser removida"


async def test_delete_tag_calculada_usada_como_entrada_409(client, admin_headers):
    p = await _projeto(client, admin_headers, "DelCalc")
    base = (
        await client.post(
            "/api/calculated-tags", json=_corpo_calc(p["id"], "Base", []), headers=admin_headers
        )
    ).json()
    depende = _corpo_calc(p["id"], "Depende", [base["id"]])
    assert (
        await client.post("/api/calculated-tags", json=depende, headers=admin_headers)
    ).status_code == 201

    r = await client.delete(f"/api/calculated-tags/{base['id']}", headers=admin_headers)
    assert r.status_code == 409


async def test_delete_happy_path_204(client, admin_headers):
    p = await _projeto(client, admin_headers, "DelOk")
    criado = (
        await client.post(
            "/api/calculated-tags", json=_corpo_calc(p["id"], "Solo", []), headers=admin_headers
        )
    ).json()
    r = await client.delete(f"/api/calculated-tags/{criado['id']}", headers=admin_headers)
    assert r.status_code == 204
    assert (await client.get(f"/api/tags/{criado['id']}", headers=admin_headers)).status_code == 404


async def test_papeis_rotas_de_escrita_403(client, admin_headers, operator_headers):
    p = await _projeto(client, admin_headers, "Papeis")
    corpo = _corpo_calc(p["id"], "Calc", [])
    r = await client.post("/api/calculated-tags", json=corpo, headers=operator_headers)
    assert r.status_code == 403

    criado = (await client.post("/api/calculated-tags", json=corpo, headers=admin_headers)).json()
    r = await client.patch(
        f"/api/calculated-tags/{criado['id']}", json={"eu": "x"}, headers=operator_headers
    )
    assert r.status_code == 403
    r = await client.delete(f"/api/calculated-tags/{criado['id']}", headers=operator_headers)
    assert r.status_code == 403
