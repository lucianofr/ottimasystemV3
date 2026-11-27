"""Sensor virtual na API (RF-584, ADR-046; spec §5.6 passo 1, §7.4 e §8.4): ativação de modelo
(`POST /api/operate/{flow}/{bloco}/model`), consulta (`GET /api/softsensor/blocks|models`) e a
faxina de vínculos no save do flow.

Cenário auto-contido (mesmo esqueleto de test_operate_fuzzy.py): projeto, conexão, duas tags de
entrada e um flow com `r1`, `r2` (opc_read) alimentando `sv1` (`soft_sensor_pls`, 2 entradas).
Os modelos entram direto no banco, com artefatos sintéticos de `ottima_core.softsensor`.
"""

import json

import pytest
from redis.asyncio import Redis
from sqlalchemy import func, select

from ottima_core.bus import CHANNEL_FLOW_COMMANDS
from ottima_core.models import SoftSensorBinding, SoftSensorModel
from ottima_core.softsensor import synthetic

# ------------------------------------------------------------------------- fixtures locais


@pytest.fixture
async def comandos(redis_url):
    """Assinante de `flow.commands`, mesmo padrão de test_operate.py."""
    sub = Redis.from_url(redis_url, decode_responses=True)
    pubsub = sub.pubsub()
    await pubsub.subscribe(CHANNEL_FLOW_COMMANDS)
    await pubsub.get_message(timeout=5)  # confirmação do SUBSCRIBE

    async def recebidos() -> list[dict]:
        msgs = []
        while (
            m := await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.5)
        ) is not None:
            msgs.append(json.loads(m["data"]))
        return msgs

    yield recebidos
    await pubsub.aclose()
    await sub.aclose()


# ---------------------------------------------------------------- construtores do cenário


async def _projeto(client, headers, nome: str) -> int:
    r = await client.post("/api/projects", json={"name": nome}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _conexao(client, headers, project_id: int, nome: str) -> int:
    r = await client.post(
        "/api/connections",
        json={"project_id": project_id, "name": nome, "endpoint": "opc.tcp://x:4840"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _tag(client, headers, conn_id: int, nome: str) -> int:
    r = await client.post(
        "/api/tags",
        json={
            "connection_id": conn_id,
            "name": nome,
            "node_id": f"ns=2;s={nome}",
            "direction": "r",
            "data_type": "float",
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _no(node_id: str, tipo: str, exec_order: int, **config) -> dict:
    return {
        "id": node_id,
        "type": tipo,
        "position": {"x": 0.0, "y": 0.0},
        "data": {"exec_order": exec_order, **config},
    }


def _aresta(source: str, target: str, target_handle: str, id_: str) -> dict:
    return {
        "id": id_,
        "source": source,
        "sourceHandle": "out",
        "target": target,
        "targetHandle": target_handle,
    }


def _grafo(tags: list[int], sv: dict | None, *, ligar: bool = True) -> dict:
    """`r1`, `r2` (opc_read) e, se dado, o nó `sv` ligado às duas entradas."""
    nos = [_no("r1", "opc_read", 1, tag_id=tags[0]), _no("r2", "opc_read", 2, tag_id=tags[1])]
    arestas = []
    if sv is not None:
        nos.append(sv)
        if ligar:
            arestas = [_aresta("r1", "sv1", "IN1", "e1"), _aresta("r2", "sv1", "IN2", "e2")]
    return {"nodes": nos, "edges": arestas}


def _sv(tipo: str = "soft_sensor_pls", **extra) -> dict:
    return _no("sv1", tipo, 3, n_inputs=2, output_eu="%", **extra)


async def _salvar(client, headers, flow_id: int, grafo: dict) -> None:
    r = await client.put(f"/api/flows/{flow_id}", json={"graph_json": grafo}, headers=headers)
    assert r.status_code == 200, r.text


async def _cenario(client, admin_headers, nome: str, ts: float = 1) -> dict:
    """Projeto ativo com um flow que tem o bloco `sv1` (PLS, 2 entradas) e os `opc_read`."""
    pid = await _projeto(client, admin_headers, nome)
    cid = await _conexao(client, admin_headers, pid, f"plc-{nome}")
    tags = [await _tag(client, admin_headers, cid, f"{nome}-T{i}") for i in (1, 2)]
    r = await client.post(
        "/api/flows",
        json={"project_id": pid, "name": nome, "ts_seconds": ts},
        headers=admin_headers,
    )
    assert r.status_code == 201, r.text
    flow_id = r.json()["id"]
    await _salvar(client, admin_headers, flow_id, _grafo(tags, _sv()))
    r = await client.post(f"/api/projects/{pid}/activate", headers=admin_headers)
    assert r.status_code == 200, r.text
    return {"project_id": pid, "flow_id": flow_id, "tags": tags}


async def _modelo(
    session, project_id: int, nome: str, artefato: tuple | None = None
) -> SoftSensorModel:
    """Linha de `soft_sensor_models` com artefato sintético (PLS de 2 entradas por padrão)."""
    meta, blob = artefato or synthetic.pls([1.0, 2.0], 0.0, period_s=1.0)
    modelo = SoftSensorModel(
        project_id=project_id,
        name=nome,
        method=meta.method,
        period_s=meta.period_s,
        n_inputs=len(meta.inputs),
        input_tag_ids=[],
        meta=meta.model_dump(mode="json"),
        weights=blob,
        created_by="user:1",
    )
    session.add(modelo)
    await session.commit()
    return modelo


async def _vinculo(session, flow_id: int, block_id: str = "sv1") -> tuple | None:
    """Colunas cruas do vínculo `(desired, active, candidate)`; `None` se não existe.
    Consulta por colunas: o upsert da API é Core e o mapa de identidade ficaria velho."""
    linha = (
        await session.execute(
            select(
                SoftSensorBinding.desired_model_id,
                SoftSensorBinding.active_model_id,
                SoftSensorBinding.candidate_model_id,
            ).where(SoftSensorBinding.flow_id == flow_id, SoftSensorBinding.block_id == block_id)
        )
    ).first()
    return None if linha is None else tuple(linha)


async def _inserir_vinculo(session, flow_id: int, block_id: str = "sv1", **colunas) -> None:
    session.add(
        SoftSensorBinding(flow_id=flow_id, block_id=block_id, updated_by="runtime", **colunas)
    )
    await session.commit()


async def _ativar(client, headers, flow_id: int, model_id: int, block_id: str = "sv1"):
    return await client.post(
        f"/api/operate/{flow_id}/{block_id}/model", json={"model_id": model_id}, headers=headers
    )


async def _id_do_usuario(client, headers) -> int:
    r = await client.get("/api/auth/me", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["id"]


# --------------------------------------------------------------------------------- /model


async def test_ativacao_grava_o_desejado_e_publica_o_comando(
    client, admin_headers, db_session, comandos
):
    c = await _cenario(client, admin_headers, "AtivaOk")
    modelo = await _modelo(db_session, c["project_id"], "m1")
    user_id = await _id_do_usuario(client, admin_headers)

    r = await _ativar(client, admin_headers, c["flow_id"], modelo.id)

    assert r.status_code == 202, r.text
    assert r.text == ""
    assert await _vinculo(db_session, c["flow_id"]) == (modelo.id, None, None)
    publicados = await comandos()
    assert len(publicados) == 1
    assert publicados[0]["flow_id"] == c["flow_id"]
    assert publicados[0]["cmd"] == "soft_sensor_model"
    assert publicados[0]["args"] == {"block_id": "sv1", "model_id": modelo.id}
    assert publicados[0]["user"] == f"user:{user_id}"
    por = await db_session.scalar(
        select(SoftSensorBinding.updated_by).where(SoftSensorBinding.flow_id == c["flow_id"])
    )
    assert por == f"user:{user_id}"


async def test_ativacao_exige_admin(client, admin_headers, operator_headers, db_session, comandos):
    c = await _cenario(client, admin_headers, "AtivaOper")
    modelo = await _modelo(db_session, c["project_id"], "m1")

    r = await _ativar(client, operator_headers, c["flow_id"], modelo.id)

    assert r.status_code == 403, r.text
    assert await _vinculo(db_session, c["flow_id"]) is None
    assert await comandos() == []


async def test_ativacao_anonima_401(client, comandos):
    r = await client.post("/api/operate/1/sv1/model", json={"model_id": 1})
    assert r.status_code == 401
    assert await comandos() == []


async def test_ativacao_de_flow_inexistente_404(client, admin_headers, comandos):
    r = await _ativar(client, admin_headers, 999_999, 1)
    assert r.status_code == 404, r.text
    assert await comandos() == []


@pytest.mark.parametrize(
    ("caso", "trecho"),
    [
        ("metodo", "Modelo 'm-x' é ESN; o bloco 'sv1' é PLS"),
        ("entradas", "Modelo 'm-x' tem 3 entradas; o bloco 'sv1' tem 2"),
        ("periodo", "Período do modelo (1.5 s) não é múltiplo do Ts do flow (1 s)"),
        ("outro_projeto", "não existe neste projeto"),
        ("inexistente", "Modelo 999999 não existe neste projeto"),
        ("bloco_comum", "Bloco 'r1' não é um bloco de sensor virtual"),
        ("bloco_ausente", "Bloco 'nada' não encontrado no flow"),
    ],
)
async def test_ativacao_recusada(client, admin_headers, db_session, comandos, caso, trecho):
    c = await _cenario(client, admin_headers, f"Recusa-{caso}")
    artefatos = {
        "metodo": synthetic.esn(2),
        "entradas": synthetic.pls([1.0, 2.0, 3.0], 0.0),
        "periodo": synthetic.pls([1.0, 2.0], 0.0, period_s=1.5),
    }
    project_id = c["project_id"]
    if caso == "outro_projeto":
        project_id = await _projeto(client, admin_headers, "Outro")
    modelo = await _modelo(db_session, project_id, "m-x", artefatos.get(caso))
    model_id = 999_999 if caso == "inexistente" else modelo.id
    block_id = {"bloco_comum": "r1", "bloco_ausente": "nada"}.get(caso, "sv1")

    r = await _ativar(client, admin_headers, c["flow_id"], model_id, block_id)

    assert r.status_code == 422, r.text
    assert trecho in r.json()["detail"]
    assert await _vinculo(db_session, c["flow_id"], block_id) is None
    assert await comandos() == []


async def test_ativacao_nunca_escreve_ativo_nem_candidato(
    client, admin_headers, db_session, comandos
):
    c = await _cenario(client, admin_headers, "AtivaSoDesejado")
    em_uso = await _modelo(db_session, c["project_id"], "em-uso")
    novo = await _modelo(db_session, c["project_id"], "novo")
    await _inserir_vinculo(
        db_session, c["flow_id"], desired_model_id=em_uso.id, active_model_id=em_uso.id
    )

    r = await _ativar(client, admin_headers, c["flow_id"], novo.id)

    assert r.status_code == 202, r.text
    assert await _vinculo(db_session, c["flow_id"]) == (novo.id, em_uso.id, None)


async def test_reativar_o_mesmo_modelo_e_idempotente(client, admin_headers, db_session, comandos):
    c = await _cenario(client, admin_headers, "Reativa")
    modelo = await _modelo(db_session, c["project_id"], "m1")

    primeira = await _ativar(client, admin_headers, c["flow_id"], modelo.id)
    segunda = await _ativar(client, admin_headers, c["flow_id"], modelo.id)

    assert (primeira.status_code, segunda.status_code) == (202, 202)
    assert await _vinculo(db_session, c["flow_id"]) == (modelo.id, None, None)
    n = await db_session.scalar(
        select(func.count())
        .select_from(SoftSensorBinding)
        .where(SoftSensorBinding.flow_id == c["flow_id"])
    )
    assert n == 1
    assert (
        len(await comandos()) == 2
    )  # cada ativação publica: reenviar é o caminho do comando perdido


# ---------------------------------------------------------------------------------- GET


async def test_blocks_e_models_exigem_login(client):
    assert (await client.get("/api/softsensor/blocks")).status_code == 401
    assert (await client.get("/api/softsensor/models")).status_code == 401


async def test_blocks_lista_so_o_projeto_ativo_com_o_vinculo(
    client, admin_headers, operator_headers, db_session
):
    c = await _cenario(client, admin_headers, "BlocosAtivo")
    modelo = await _modelo(db_session, c["project_id"], "m1")
    outro = await _modelo(db_session, c["project_id"], "m2")
    await _inserir_vinculo(
        db_session,
        c["flow_id"],
        desired_model_id=outro.id,
        active_model_id=modelo.id,
        candidate_model_id=outro.id,
    )
    # Segundo projeto, não ativo, com o seu próprio sensor virtual: não pode aparecer.
    inativo = await _projeto(client, admin_headers, "BlocosInativo")
    cid = await _conexao(client, admin_headers, inativo, "plc-inativo")
    tags = [await _tag(client, admin_headers, cid, f"I-T{i}") for i in (1, 2)]
    r = await client.post(
        "/api/flows",
        json={"project_id": inativo, "name": "FlowInativo", "ts_seconds": 1},
        headers=admin_headers,
    )
    await _salvar(client, admin_headers, r.json()["id"], _grafo(tags, _sv()))

    r = await client.get("/api/softsensor/blocks", headers=operator_headers)

    assert r.status_code == 200, r.text
    assert r.json() == [
        {
            "flow_id": c["flow_id"],
            "flow_name": "BlocosAtivo",
            "block_id": "sv1",
            "label": "sv1",  # nó sem `label`: cai para o id do bloco
            "method": "pls",
            "n_inputs": 2,
            "ts_seconds": 1.0,
            "desired_model_id": outro.id,
            "active_model_id": modelo.id,
            "candidate_model_id": outro.id,
            "active_input_names": ["x0", "x1"],  # do modelo EM USO, não do candidato
            "warmup_s": 1.0,
        }
    ]


async def test_blocks_sem_vinculo_devolve_ids_nulos(
    client, admin_headers, operator_headers, db_session
):
    await _cenario(client, admin_headers, "BlocosSemVinculo")

    r = await client.get("/api/softsensor/blocks", headers=operator_headers)

    (bloco,) = r.json()
    assert (
        bloco["desired_model_id"],
        bloco["active_model_id"],
        bloco["candidate_model_id"],
    ) == (None, None, None)


async def test_blocks_sem_projeto_ativo_lista_vazia(client, admin_headers, operator_headers):
    pid = await _projeto(client, admin_headers, "SemAtivo")
    cid = await _conexao(client, admin_headers, pid, "plc-sem")
    tags = [await _tag(client, admin_headers, cid, f"S-T{i}") for i in (1, 2)]
    r = await client.post(
        "/api/flows",
        json={"project_id": pid, "name": "FlowSemAtivo", "ts_seconds": 1},
        headers=admin_headers,
    )
    await _salvar(client, admin_headers, r.json()["id"], _grafo(tags, _sv()))

    r = await client.get("/api/softsensor/blocks", headers=operator_headers)

    assert r.status_code == 200, r.text
    assert r.json() == []


async def test_models_lista_o_projeto_ativo(client, admin_headers, operator_headers, db_session):
    c = await _cenario(client, admin_headers, "ModelosAtivo")
    modelo = await _modelo(db_session, c["project_id"], "enxofre-v1")
    outro_projeto = await _projeto(client, admin_headers, "ModelosOutro")
    await _modelo(db_session, outro_projeto, "alheio")

    r = await client.get("/api/softsensor/models", headers=operator_headers)

    assert r.status_code == 200, r.text
    (item,) = r.json()
    assert item["id"] == modelo.id
    assert item["name"] == "enxofre-v1"
    assert item["method"] == "pls"
    assert item["period_s"] == 1.0
    assert item["n_inputs"] == 2
    assert item["warmup_steps"] == 1
    assert item["metrics"] == {}
    assert item["input_names"] == ["x0", "x1"]
    assert item["created_at"]


async def test_models_nunca_devolve_os_pesos(client, admin_headers, operator_headers, db_session):
    c = await _cenario(client, admin_headers, "ModelosSemPesos")
    await _modelo(db_session, c["project_id"], "m1")

    r = await client.get("/api/softsensor/models", headers=operator_headers)

    (item,) = r.json()
    assert "weights" not in item
    assert "meta" not in item  # nem o JSON bruto do artefato: só a projeção
    assert "weights" not in r.text


async def test_models_sem_projeto_ativo_lista_vazia(client, operator_headers):
    r = await client.get("/api/softsensor/models", headers=operator_headers)
    assert r.status_code == 200, r.text
    assert r.json() == []


# ------------------------------------------------------------------- poda no save do flow


async def test_save_que_remove_o_bloco_apaga_o_vinculo(client, admin_headers, db_session):
    c = await _cenario(client, admin_headers, "PodaRemove")
    modelo = await _modelo(db_session, c["project_id"], "m1")
    await _inserir_vinculo(db_session, c["flow_id"], desired_model_id=modelo.id)

    await _salvar(client, admin_headers, c["flow_id"], _grafo(c["tags"], None))

    assert await _vinculo(db_session, c["flow_id"]) is None


async def test_save_que_troca_o_tipo_do_bloco_apaga_o_vinculo(client, admin_headers, db_session):
    c = await _cenario(client, admin_headers, "PodaTipo")
    modelo = await _modelo(db_session, c["project_id"], "m1")
    await _inserir_vinculo(db_session, c["flow_id"], desired_model_id=modelo.id)

    constante = _no("sv1", "constant", 3, value=1.0)
    await _salvar(client, admin_headers, c["flow_id"], _grafo(c["tags"], constante, ligar=False))

    assert await _vinculo(db_session, c["flow_id"]) is None


async def test_save_que_troca_o_metodo_do_bloco_apaga_o_vinculo(client, admin_headers, db_session):
    """pls -> esn continua sendo sensor virtual, mas é outro tipo (spec §7.4): o modelo PLS
    do vínculo não serve ao bloco ESN."""
    c = await _cenario(client, admin_headers, "PodaMetodo")
    modelo = await _modelo(db_session, c["project_id"], "m1")
    await _inserir_vinculo(db_session, c["flow_id"], desired_model_id=modelo.id)

    await _salvar(client, admin_headers, c["flow_id"], _grafo(c["tags"], _sv("soft_sensor_esn")))

    assert await _vinculo(db_session, c["flow_id"]) is None


async def test_save_que_so_muda_rotulo_mantem_o_vinculo(client, admin_headers, db_session):
    c = await _cenario(client, admin_headers, "PodaRotulo")
    modelo = await _modelo(db_session, c["project_id"], "m1")
    await _inserir_vinculo(
        db_session, c["flow_id"], desired_model_id=modelo.id, active_model_id=modelo.id
    )

    await _salvar(
        client, admin_headers, c["flow_id"], _grafo(c["tags"], _sv(label="Enxofre estimado"))
    )

    assert await _vinculo(db_session, c["flow_id"]) == (modelo.id, modelo.id, None)


async def test_save_poda_so_o_bloco_que_saiu(client, admin_headers, db_session):
    """Dois sensores virtuais no flow; o save remove um e o vínculo do outro sobrevive."""
    c = await _cenario(client, admin_headers, "PodaSeletiva")
    modelo = await _modelo(db_session, c["project_id"], "m1")
    await _inserir_vinculo(db_session, c["flow_id"], "sv1", desired_model_id=modelo.id)
    await _inserir_vinculo(db_session, c["flow_id"], "sv2", desired_model_id=modelo.id)
    sv2 = _no("sv2", "soft_sensor_pls", 3, n_inputs=2, output_eu="")
    grafo = _grafo(c["tags"], sv2, ligar=False)
    grafo["edges"] = [_aresta("r1", "sv2", "IN1", "e1"), _aresta("r2", "sv2", "IN2", "e2")]

    await _salvar(client, admin_headers, c["flow_id"], grafo)

    assert await _vinculo(db_session, c["flow_id"], "sv1") is None
    assert await _vinculo(db_session, c["flow_id"], "sv2") == (modelo.id, None, None)
