"""Testes de variável historiada (RF-308, ADR-041): CRUD, nome derivado (D6), regra de
porta de entrada sem aresta (D7) e a cascata pela linha de `tags` (D5)."""


async def _projeto(client, headers, nome: str) -> dict:
    r = await client.post("/api/projects", json={"name": nome}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


async def _conexao(client, headers, project_id: int, nome: str = "plc") -> int:
    r = await client.post(
        "/api/connections",
        json={"project_id": project_id, "name": nome, "endpoint": "opc.tcp://x:4840"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _tag(client, headers, conn_id: int, nome: str, direcao: str, tipo: str = "float") -> int:
    r = await client.post(
        "/api/tags",
        json={
            "connection_id": conn_id,
            "name": nome,
            "node_id": f"ns=2;s={nome}",
            "direction": direcao,
            "data_type": tipo,
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _flow(client, headers, project_id: int, nome: str, ts: float = 1) -> dict:
    r = await client.post(
        "/api/flows",
        json={"project_id": project_id, "name": nome, "ts_seconds": ts},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _calc_tag(client, headers, project_id: int, name: str) -> dict:
    """Tag calculada só como veículo de colisão de nome (D6) — código e período são
    irrelevantes para os testes deste arquivo, só a linha em `tags` importa."""
    r = await client.post(
        "/api/calculated-tags",
        json={
            "project_id": project_id,
            "name": name,
            "period_seconds": 1,
            "code": "OUT = 1.0",
            "input_tag_ids": [],
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _no(node_id: str, tipo: str, exec_order: int, **config) -> dict:
    return {
        "id": node_id,
        "type": tipo,
        "position": {"x": 0.0, "y": 0.0},
        "data": {"exec_order": exec_order, **config},
    }


def _aresta(source: str, source_handle: str, target: str, target_handle: str, id_: str = "e1"):
    return {
        "id": id_,
        "source": source,
        "sourceHandle": source_handle,
        "target": target,
        "targetHandle": target_handle,
    }


def _grafo(tag_r: int, tag_w: int, label_r: str = "") -> dict:
    """r1 (opc_read) -> w1 (opc_write) e r1 -> int1 (integrator): cobre porta de SAÍDA
    (`r1.out`), porta de ENTRADA conectada (`w1.in`) e porta de ENTRADA opcional sem
    aresta (`int1.reset`, D7) no mesmo grafo."""
    return {
        "nodes": [
            _no("r1", "opc_read", 1, label=label_r, tag_id=tag_r),
            _no("w1", "opc_write", 2, tag_id=tag_w),
            _no("int1", "integrator", 3, time_base="s"),
        ],
        "edges": [
            _aresta("r1", "out", "w1", "in", "e1"),
            _aresta("r1", "out", "int1", "in", "e2"),
        ],
    }


async def _salvar(client, headers, flow_id: int, graph: dict):
    return await client.put(f"/api/flows/{flow_id}", json={"graph_json": graph}, headers=headers)


async def _cenario(client, headers, nome: str, label_r: str = "") -> tuple[dict, int, int]:
    """Projeto com tag de leitura, tag de escrita e flow já salvo com `_grafo`."""
    p = await _projeto(client, headers, nome)
    cid = await _conexao(client, headers, p["id"])
    leitura = await _tag(client, headers, cid, f"FT-{nome}", "r")
    escrita = await _tag(client, headers, cid, f"FV-{nome}", "w")
    flow = await _flow(client, headers, p["id"], nome)
    salvo = await _salvar(client, headers, flow["id"], _grafo(leitura, escrita, label_r))
    assert salvo.status_code == 200, salvo.text
    return salvo.json()["flow"], leitura, escrita


# --------------------------------------------------------------------------------- POST


async def test_post_porta_de_saida_201(client, admin_headers):
    flow, _, _ = await _cenario(client, admin_headers, "Saida")
    r = await client.post(
        "/api/historized-vars",
        json={"flow_id": flow["id"], "block_id": "r1", "port": "out", "eu": "°C"},
        headers=admin_headers,
    )
    assert r.status_code == 201, r.text
    corpo = r.json()
    assert corpo["name"] == f"{flow['name']}.r1.out"
    assert corpo["eu"] == "°C"
    assert corpo["flow_id"] == flow["id"]
    assert corpo["block_id"] == "r1"
    assert corpo["port"] == "out"


async def test_post_porta_de_entrada_com_aresta_201(client, admin_headers):
    flow, _, _ = await _cenario(client, admin_headers, "EntradaOk")
    r = await client.post(
        "/api/historized-vars",
        json={"flow_id": flow["id"], "block_id": "w1", "port": "in"},
        headers=admin_headers,
    )
    assert r.status_code == 201, r.text
    assert r.json()["name"] == f"{flow['name']}.w1.in"


async def test_post_flow_inexistente_404(client, admin_headers):
    r = await client.post(
        "/api/historized-vars",
        json={"flow_id": 987654, "block_id": "r1", "port": "out"},
        headers=admin_headers,
    )
    assert r.status_code == 404
    assert r.json()["detail"] == "Flow não encontrado"


async def test_post_grafo_nao_salvo_422(client, admin_headers):
    p = await _projeto(client, admin_headers, "GrafoVazio")
    flow = await _flow(client, admin_headers, p["id"], "SemGrafo")
    r = await client.post(
        "/api/historized-vars",
        json={"flow_id": flow["id"], "block_id": "r1", "port": "out"},
        headers=admin_headers,
    )
    assert r.status_code == 422
    assert "salve o desenho" in r.json()["detail"]


async def test_post_bloco_inexistente_422(client, admin_headers):
    flow, _, _ = await _cenario(client, admin_headers, "BlocoFantasma")
    r = await client.post(
        "/api/historized-vars",
        json={"flow_id": flow["id"], "block_id": "fantasma", "port": "out"},
        headers=admin_headers,
    )
    assert r.status_code == 422
    assert r.json()["detail"] == "Bloco não existe no grafo salvo do flow"


async def test_post_porta_inexistente_422(client, admin_headers):
    flow, _, _ = await _cenario(client, admin_headers, "PortaFantasma")
    r = await client.post(
        "/api/historized-vars",
        json={"flow_id": flow["id"], "block_id": "r1", "port": "in"},
        headers=admin_headers,
    )
    assert r.status_code == 422
    assert r.json()["detail"] == "Porta não existe neste bloco"


async def test_post_entrada_sem_aresta_422(client, admin_headers):
    """D7: `int1.reset` é porta de entrada declarada mas opcional — sem aresta, ficaria
    COLD para sempre no runtime, então o cadastro recusa."""
    flow, _, _ = await _cenario(client, admin_headers, "EntradaSolta")
    r = await client.post(
        "/api/historized-vars",
        json={"flow_id": flow["id"], "block_id": "int1", "port": "reset"},
        headers=admin_headers,
    )
    assert r.status_code == 422
    assert (
        r.json()["detail"]
        == "Porta de entrada sem aresta conectada nunca produz valor e não pode ser historiada"
    )


async def test_post_duplicado_409(client, admin_headers):
    flow, _, _ = await _cenario(client, admin_headers, "Duplicado")
    corpo = {"flow_id": flow["id"], "block_id": "w1", "port": "in"}
    r1 = await client.post("/api/historized-vars", json=corpo, headers=admin_headers)
    assert r1.status_code == 201, r1.text
    r2 = await client.post("/api/historized-vars", json=corpo, headers=admin_headers)
    assert r2.status_code == 409
    assert r2.json()["detail"] == "Esta porta já está historiada"


async def test_nome_usa_label_e_cai_para_block_id_na_colisao(client, admin_headers):
    """D6: nome preferido usa o label do bloco; colide -> cai para o `block_id` bruto."""
    flow, _, _ = await _cenario(client, admin_headers, "NomeFallback", label_r="Leitura")
    preferido = f"{flow['name']}.Leitura.out"
    alternativo = f"{flow['name']}.r1.out"
    await _calc_tag(client, admin_headers, flow["project_id"], preferido)

    r = await client.post(
        "/api/historized-vars",
        json={"flow_id": flow["id"], "block_id": "r1", "port": "out"},
        headers=admin_headers,
    )
    assert r.status_code == 201, r.text
    assert r.json()["name"] == alternativo


async def test_ambos_nomes_colidem_409(client, admin_headers):
    flow, _, _ = await _cenario(client, admin_headers, "Colisao2", label_r="Leitura")
    preferido = f"{flow['name']}.Leitura.out"
    alternativo = f"{flow['name']}.r1.out"
    await _calc_tag(client, admin_headers, flow["project_id"], preferido)
    await _calc_tag(client, admin_headers, flow["project_id"], alternativo)

    r = await client.post(
        "/api/historized-vars",
        json={"flow_id": flow["id"], "block_id": "r1", "port": "out"},
        headers=admin_headers,
    )
    assert r.status_code == 409
    assert r.json()["detail"] == "Nome de tag já em uso neste projeto"


# ---------------------------------------------------------------------------------- GET


async def test_get_lista_por_flow_ordenada(client, admin_headers):
    flow, _, _ = await _cenario(client, admin_headers, "Lista")
    await client.post(
        "/api/historized-vars",
        json={"flow_id": flow["id"], "block_id": "w1", "port": "in", "eu": "kg"},
        headers=admin_headers,
    )
    await client.post(
        "/api/historized-vars",
        json={"flow_id": flow["id"], "block_id": "r1", "port": "out"},
        headers=admin_headers,
    )
    r = await client.get(f"/api/historized-vars?flow_id={flow['id']}", headers=admin_headers)
    assert r.status_code == 200
    lista = r.json()
    assert [v["block_id"] for v in lista] == ["r1", "w1"]
    assert lista[1]["eu"] == "kg"


# -------------------------------------------------------------------------------- DELETE


async def test_delete_remove_a_linha_de_tags(client, admin_headers):
    flow, _, _ = await _cenario(client, admin_headers, "DeleteVar")
    r = await client.post(
        "/api/historized-vars",
        json={"flow_id": flow["id"], "block_id": "w1", "port": "in"},
        headers=admin_headers,
    )
    tag_id = r.json()["tag_id"]

    dele = await client.delete(f"/api/historized-vars/{tag_id}", headers=admin_headers)
    assert dele.status_code == 204
    assert (await client.get(f"/api/tags/{tag_id}", headers=admin_headers)).status_code == 404

    outra = await client.delete(f"/api/historized-vars/{tag_id}", headers=admin_headers)
    assert outra.status_code == 404
    assert outra.json()["detail"] == "Variável historiada não encontrada"


# ---------------------------------------------------------------------- Poda e cascata


async def test_poda_no_put_remove_registro_e_tag(client, admin_headers):
    flow, leitura, escrita = await _cenario(client, admin_headers, "Poda")
    r = await client.post(
        "/api/historized-vars",
        json={"flow_id": flow["id"], "block_id": "int1", "port": "out"},
        headers=admin_headers,
    )
    assert r.status_code == 201, r.text
    tag_id = r.json()["tag_id"]

    # Novo grafo sem o bloco `int1`: a poda do save tem de remover o registro e a tag.
    novo_grafo = {
        "nodes": [
            _no("r1", "opc_read", 1, tag_id=leitura),
            _no("w1", "opc_write", 2, tag_id=escrita),
        ],
        "edges": [_aresta("r1", "out", "w1", "in")],
    }
    salvo = await _salvar(client, admin_headers, flow["id"], novo_grafo)
    assert salvo.status_code == 200, salvo.text

    lista = await client.get(f"/api/historized-vars?flow_id={flow['id']}", headers=admin_headers)
    assert lista.json() == []
    assert (await client.get(f"/api/tags/{tag_id}", headers=admin_headers)).status_code == 404


async def test_poda_no_put_remove_entrada_que_perdeu_a_aresta(client, admin_headers):
    """Outro ramo da poda (D7 reaplicado no save): a porta CONTINUA existindo, mas a aresta
    que a alimentava saiu — sem isso a série viraria NULL para sempre.

    Usa `int1.reset` (entrada OPCIONAL do integrator): desconectar uma entrada obrigatória
    reprovaria o grafo no 422 da validação e a poda nunca rodaria.
    """
    flow, leitura, escrita = await _cenario(client, admin_headers, "PodaAresta")
    com_reset = _grafo(leitura, escrita)
    com_reset["edges"].append(_aresta("r1", "out", "int1", "reset", "e3"))
    assert (await _salvar(client, admin_headers, flow["id"], com_reset)).status_code == 200

    r = await client.post(
        "/api/historized-vars",
        json={"flow_id": flow["id"], "block_id": "int1", "port": "reset"},
        headers=admin_headers,
    )
    assert r.status_code == 201, r.text
    tag_id = r.json()["tag_id"]

    # Mesmo grafo, só a aresta `r1.out -> int1.reset` removida: `reset` continua sendo porta
    # declarada do bloco, mas sem origem nunca produz valor.
    salvo = await _salvar(client, admin_headers, flow["id"], _grafo(leitura, escrita))
    assert salvo.status_code == 200, salvo.text

    lista = await client.get(f"/api/historized-vars?flow_id={flow['id']}", headers=admin_headers)
    assert lista.json() == []
    assert (await client.get(f"/api/tags/{tag_id}", headers=admin_headers)).status_code == 404


async def test_delete_flow_remove_variavel_historiada_sem_deixar_orfa(client, admin_headers):
    flow, _, _ = await _cenario(client, admin_headers, "DeleteFlow")
    r = await client.post(
        "/api/historized-vars",
        json={"flow_id": flow["id"], "block_id": "w1", "port": "in"},
        headers=admin_headers,
    )
    assert r.status_code == 201, r.text
    tag_id = r.json()["tag_id"]

    dele = await client.delete(f"/api/flows/{flow['id']}", headers=admin_headers)
    assert dele.status_code == 204
    assert (await client.get(f"/api/tags/{tag_id}", headers=admin_headers)).status_code == 404


# --------------------------------------------------------------------------------- Papéis


async def test_papeis_403(client, admin_headers, operator_headers):
    flow, _, _ = await _cenario(client, admin_headers, "Papeis")
    corpo = {"flow_id": flow["id"], "block_id": "w1", "port": "in"}
    r = await client.post("/api/historized-vars", json=corpo, headers=operator_headers)
    assert r.status_code == 403

    criado = await client.post("/api/historized-vars", json=corpo, headers=admin_headers)
    assert criado.status_code == 201, criado.text
    tag_id = criado.json()["tag_id"]

    r = await client.delete(f"/api/historized-vars/{tag_id}", headers=operator_headers)
    assert r.status_code == 403

    r = await client.get(f"/api/historized-vars?flow_id={flow['id']}", headers=operator_headers)
    assert r.status_code == 200
