"""Variáveis de laboratório, análises e importação de CSV (RF-585, spec SENSOR_VIRTUAL §7.1-7.2).

Rotas sob `/api/softsensor`. Cenário mínimo: um projeto ativo, criado e ativado pela própria API
(mesmo esqueleto de test_softsensor.py). O parser do CSV tem testes próprios (test_lab_csv.py):
aqui só o que a rota acrescenta: papéis, escopo de projeto, transação, upsert, 413 e auditoria.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, insert, select

from ottima_core.bus import (
    KIND_LAB_SAMPLE_ADDED,
    KIND_LAB_SAMPLE_DELETED,
    KIND_LAB_SAMPLES_IMPORTED,
    KIND_LAB_VARIABLE_CREATED,
    KIND_LAB_VARIABLE_DELETED,
    KIND_LAB_VARIABLE_UPDATED,
)
from ottima_core.models import LabSample, SoftSensorDataset

VARS = "/api/softsensor/lab-variables"
IMPORT = "/api/softsensor/lab-samples/import"
CSV = {"Content-Type": "text/csv"}
MSG_SEM_PROJETO = "Nenhum projeto ativo"
MSG_NOME_REPETIDO = "Já existe uma variável de laboratório com esse nome"
MSG_NOME_INVALIDO = "Nome não pode conter ';' nem aspas"
MSG_FUTURO = "A data da coleta não pode estar no futuro"


async def _ativar(client, admin_headers, nome: str = "proj-lab") -> int:
    r = await client.post("/api/projects", json={"name": nome}, headers=admin_headers)
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    r = await client.post(f"/api/projects/{pid}/activate", headers=admin_headers)
    assert r.status_code == 200, r.text
    return pid


async def _variavel(client, admin_headers, nome: str = "pureza", **extra) -> int:
    r = await client.post(VARS, json={"name": nome, **extra}, headers=admin_headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _lancar(client, headers, var_id: int, value: float, sampled_at: str):
    return await client.post(
        f"{VARS}/{var_id}/samples",
        json={"value": value, "sampled_at": sampled_at},
        headers=headers,
    )


async def _analises(client, headers, var_id: int, **params) -> list[dict]:
    r = await client.get(f"{VARS}/{var_id}/samples", params=params, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


async def _importar(client, headers, corpo: bytes | str, tz: str = "America/Sao_Paulo"):
    if isinstance(corpo, str):
        corpo = corpo.encode()
    return await client.post(IMPORT, params={"tz": tz}, content=corpo, headers={**headers, **CSV})


async def _total_de_analises(db_session) -> int:
    return await db_session.scalar(select(func.count()).select_from(LabSample))


# --------------------------------------------------------------------------- variáveis


async def test_crud_de_variavel_exige_admin_e_lista_serve_operador(
    client, admin_headers, operator_headers
):
    await _ativar(client, admin_headers)
    corpo = {"name": "pureza", "eu": "%", "description": "Pureza do topo"}

    assert (await client.post(VARS, json=corpo, headers=operator_headers)).status_code == 403
    r = await client.post(VARS, json=corpo, headers=admin_headers)
    assert r.status_code == 201, r.text
    var_id = r.json()["id"]
    assert r.json() | {"id": 0} == {
        "id": 0,
        "name": "pureza",
        "eu": "%",
        "description": "Pureza do topo",
        "sample_count": 0,
        "last_sampled_at": None,
    }

    r = await client.get(VARS, headers=operator_headers)
    assert r.status_code == 200
    assert [v["name"] for v in r.json()] == ["pureza"]

    r = await client.patch(f"{VARS}/{var_id}", json={"eu": "ppm"}, headers=operator_headers)
    assert r.status_code == 403
    r = await client.patch(f"{VARS}/{var_id}", json={"eu": "ppm"}, headers=admin_headers)
    assert r.status_code == 200, r.text
    assert (r.json()["name"], r.json()["eu"]) == ("pureza", "ppm")  # campo omitido não muda

    assert (await client.delete(f"{VARS}/{var_id}", headers=operator_headers)).status_code == 403
    assert (await client.delete(f"{VARS}/{var_id}", headers=admin_headers)).status_code == 204
    assert (await client.get(VARS, headers=operator_headers)).json() == []


async def test_lista_traz_contagem_e_ultima_coleta(client, admin_headers, operator_headers):
    await _ativar(client, admin_headers)
    var_id = await _variavel(client, admin_headers)
    await _variavel(client, admin_headers, "sem-analise")
    await _lancar(client, operator_headers, var_id, 1.0, "2025-03-01T10:00:00Z")
    await _lancar(client, operator_headers, var_id, 2.0, "2025-03-02T10:00:00Z")

    por_nome = {v["name"]: v for v in (await client.get(VARS, headers=operator_headers)).json()}

    assert por_nome["pureza"]["sample_count"] == 2
    assert por_nome["pureza"]["last_sampled_at"].startswith("2025-03-02T10:00:00")
    assert por_nome["sem-analise"]["sample_count"] == 0
    assert por_nome["sem-analise"]["last_sampled_at"] is None


async def test_nome_repetido_e_409(client, admin_headers):
    await _ativar(client, admin_headers)
    await _variavel(client, admin_headers, "pureza")
    outra = await _variavel(client, admin_headers, "umidade")

    r = await client.post(VARS, json={"name": "pureza"}, headers=admin_headers)
    assert (r.status_code, r.json()["detail"]) == (409, MSG_NOME_REPETIDO)
    r = await client.patch(f"{VARS}/{outra}", json={"name": "pureza"}, headers=admin_headers)
    assert (r.status_code, r.json()["detail"]) == (409, MSG_NOME_REPETIDO)


@pytest.mark.parametrize("nome", ["a;b", 'a"b', '"a"', ";"])
async def test_nome_com_ponto_e_virgula_ou_aspas_e_422(client, admin_headers, nome):
    await _ativar(client, admin_headers)
    var_id = await _variavel(client, admin_headers, "ok")

    r = await client.post(VARS, json={"name": nome}, headers=admin_headers)
    assert (r.status_code, r.json()["detail"]) == (422, MSG_NOME_INVALIDO)
    r = await client.patch(f"{VARS}/{var_id}", json={"name": nome}, headers=admin_headers)
    assert (r.status_code, r.json()["detail"]) == (422, MSG_NOME_INVALIDO)


async def test_nome_e_aparado_e_nao_pode_ser_vazio(client, admin_headers):
    await _ativar(client, admin_headers)

    r = await client.post(VARS, json={"name": "  pureza  "}, headers=admin_headers)
    assert (r.status_code, r.json()["name"]) == (201, "pureza")
    # o aparado também vale para a unicidade
    r = await client.post(VARS, json={"name": " pureza"}, headers=admin_headers)
    assert r.status_code == 409
    for vazio in ("", "   "):
        r = await client.post(VARS, json={"name": vazio}, headers=admin_headers)
        assert r.status_code == 422, vazio


async def test_apagar_variavel_apaga_as_analises(
    client, admin_headers, operator_headers, db_session
):
    await _ativar(client, admin_headers)
    var_id = await _variavel(client, admin_headers)
    await _lancar(client, operator_headers, var_id, 1.0, "2025-03-01T10:00:00Z")

    assert (await client.delete(f"{VARS}/{var_id}", headers=admin_headers)).status_code == 204

    assert await _total_de_analises(db_session) == 0


async def test_variavel_usada_por_conjunto_nao_apaga(client, admin_headers, db_session):
    pid = await _ativar(client, admin_headers)
    var_id = await _variavel(client, admin_headers)
    db_session.add(
        SoftSensorDataset(
            project_id=pid,
            name="conjunto-A",
            lab_variable_id=var_id,
            input_tag_ids=[],
            period_s=1.0,
            start_ts=func.now(),
            created_by="user:1",
        )
    )
    await db_session.commit()

    r = await client.delete(f"{VARS}/{var_id}", headers=admin_headers)

    assert (r.status_code, r.json()["detail"]) == (409, "Variável usada pelo conjunto 'conjunto-A'")
    assert [v["id"] for v in (await client.get(VARS, headers=admin_headers)).json()] == [var_id]


# ---------------------------------------------------------------------------- análises


async def test_operador_lanca_e_apaga_analise(client, admin_headers, operator_headers):
    await _ativar(client, admin_headers)
    var_id = await _variavel(client, admin_headers)

    r = await _lancar(client, operator_headers, var_id, 98.5, "2025-03-01T10:00:00-03:00")
    assert r.status_code == 201, r.text
    [a] = await _analises(client, operator_headers, var_id)
    assert (a["value"], a["source"]) == (98.5, "manual")
    assert a["sampled_at"].startswith("2025-03-01T13:00:00")  # instante, não a hora digitada

    r = await client.delete(
        f"{VARS}/{var_id}/samples",
        params={"sampled_at": "2025-03-01T13:00:00+00:00"},  # o `+` precisa chegar como %2B
        headers=operator_headers,
    )
    assert r.status_code == 204, r.text
    assert await _analises(client, operator_headers, var_id) == []
    r = await client.delete(
        f"{VARS}/{var_id}/samples",
        params={"sampled_at": "2025-03-01T13:00:00Z"},
        headers=operator_headers,
    )
    assert r.status_code == 404


async def test_analise_no_futuro_e_422(client, admin_headers, operator_headers):
    await _ativar(client, admin_headers)
    var_id = await _variavel(client, admin_headers)

    r = await _lancar(client, operator_headers, var_id, 1.0, "2999-01-01T00:00:00Z")

    assert (r.status_code, r.json()["detail"]) == (422, MSG_FUTURO)
    assert await _analises(client, operator_headers, var_id) == []


async def test_analise_exige_fuso_e_valor_finito(client, admin_headers, operator_headers):
    await _ativar(client, admin_headers)
    var_id = await _variavel(client, admin_headers)

    r = await _lancar(client, operator_headers, var_id, 1.0, "2025-03-01T10:00:00")  # sem fuso
    assert r.status_code == 422
    r = await client.post(
        f"{VARS}/{var_id}/samples",
        content=b'{"value": NaN, "sampled_at": "2025-03-01T10:00:00Z"}',
        headers={**operator_headers, "Content-Type": "application/json"},
    )
    assert r.status_code == 422
    assert await _analises(client, operator_headers, var_id) == []


async def test_lancar_no_mesmo_instante_substitui(client, admin_headers, operator_headers):
    await _ativar(client, admin_headers)
    var_id = await _variavel(client, admin_headers)

    assert (
        await _lancar(client, operator_headers, var_id, 1.0, "2025-03-01T13:00:00Z")
    ).status_code == 201
    # mesmo instante, escrito em outro fuso
    r = await _lancar(client, operator_headers, var_id, 2.0, "2025-03-01T10:00:00-03:00")
    assert r.status_code == 201, r.text

    [a] = await _analises(client, operator_headers, var_id)
    assert a["value"] == 2.0


async def test_filtro_de_periodo_ordem_crescente_e_teto(
    client, admin_headers, operator_headers, db_session
):
    await _ativar(client, admin_headers)
    var_id = await _variavel(client, admin_headers)
    for dia, valor in ((3, 3.0), (1, 1.0), (2, 2.0)):
        await _lancar(client, operator_headers, var_id, valor, f"2025-03-0{dia}T10:00:00Z")

    todas = await _analises(client, operator_headers, var_id)
    assert [a["value"] for a in todas] == [1.0, 2.0, 3.0]
    janela = await _analises(
        client, operator_headers, var_id, start="2025-03-02T00:00:00Z", end="2025-03-02T23:59:59Z"
    )
    assert [a["value"] for a in janela] == [2.0]

    agora = datetime.now(UTC)
    await db_session.execute(
        insert(LabSample),
        [
            {
                "lab_variable_id": var_id,
                "sampled_at": agora - timedelta(seconds=i),
                "value": float(i),
                "source": "csv",
                "created_by": "user:1",
            }
            for i in range(1, 5200)  # i segundos antes de agora: todas posteriores a março/2025
        ],
    )
    await db_session.commit()
    cheia = await _analises(client, operator_headers, var_id)
    assert len(cheia) == 5000  # teto
    instantes = [a["sampled_at"] for a in cheia]
    assert instantes == sorted(instantes)  # crescente mesmo com o corte
    assert cheia[-1]["value"] == 1.0  # o corte descarta as MAIS ANTIGAS: a mais recente fica


# ------------------------------------------------------------------------------ escopo


async def test_variavel_de_outro_projeto_e_404(client, admin_headers, operator_headers):
    await _ativar(client, admin_headers, "A")
    var_a = await _variavel(client, admin_headers, "so-do-A")
    await _lancar(client, operator_headers, var_a, 1.0, "2025-03-01T10:00:00Z")
    await _ativar(client, admin_headers, "B")  # B vira o projeto ativo

    assert (await client.get(VARS, headers=operator_headers)).json() == []
    alvo = f"{VARS}/{var_a}"
    assert (await client.get(f"{alvo}/samples", headers=operator_headers)).status_code == 404
    r = await _lancar(client, operator_headers, var_a, 2.0, "2025-03-02T10:00:00Z")
    assert r.status_code == 404
    r = await client.delete(
        f"{alvo}/samples", params={"sampled_at": "2025-03-01T10:00:00Z"}, headers=operator_headers
    )
    assert r.status_code == 404
    assert (await client.patch(alvo, json={"eu": "x"}, headers=admin_headers)).status_code == 404
    assert (await client.delete(alvo, headers=admin_headers)).status_code == 404
    # o nome de outro projeto não existe no projeto ativo: o import recusa
    r = await _importar(client, operator_headers, "so-do-A;01/03/2025 10:00;1")
    assert r.status_code == 422
    assert "so-do-A" in r.json()["detail"]


async def test_sem_projeto_ativo_lista_vazia_e_escrita_409(client, admin_headers, operator_headers):
    assert (await client.get(VARS, headers=operator_headers)).json() == []

    r = await client.post(VARS, json={"name": "pureza"}, headers=admin_headers)
    assert (r.status_code, r.json()["detail"]) == (409, MSG_SEM_PROJETO)
    r = await _lancar(client, operator_headers, 1, 1.0, "2025-03-01T10:00:00Z")
    assert (r.status_code, r.json()["detail"]) == (409, MSG_SEM_PROJETO)
    r = await _importar(client, operator_headers, "pureza;01/03/2025 10:00;1")
    assert (r.status_code, r.json()["detail"]) == (409, MSG_SEM_PROJETO)


# -------------------------------------------------------------------------------- import


async def test_import_grava_e_devolve_contagem_por_variavel(
    client, admin_headers, operator_headers
):
    await _ativar(client, admin_headers)
    pureza = await _variavel(client, admin_headers, "pureza")
    umidade = await _variavel(client, admin_headers, "umidade")
    csv = (
        '"nome do TAG";"data/hora";"valor"\n'
        "pureza;01/03/2025 10:00;98,5\n"
        "pureza;02/03/2025 10:00;98.7\n"
        "umidade;2025-03-01T10:00:00-03:00;0,2\n"
    )

    r = await _importar(client, operator_headers, csv)

    assert r.status_code == 200, r.text
    assert r.json() == {"imported": 3, "by_variable": {"pureza": 2, "umidade": 1}}
    a, b = await _analises(client, operator_headers, pureza)
    assert (a["value"], a["source"], b["value"]) == (98.5, "csv", 98.7)
    assert a["sampled_at"].startswith("2025-03-01T13:00:00")  # 10:00 em São Paulo (UTC-3)
    [u] = await _analises(client, operator_headers, umidade)
    assert u["sampled_at"].startswith("2025-03-01T13:00:00")


async def test_reimportar_o_mesmo_csv_e_idempotente(
    client, admin_headers, operator_headers, db_session
):
    await _ativar(client, admin_headers)
    var_id = await _variavel(client, admin_headers)
    await _lancar(client, operator_headers, var_id, 1.0, "2025-03-01T13:00:00Z")  # manual
    csv = "pureza;01/03/2025 10:00;98,5\npureza;02/03/2025 10:00;98,7\n"

    assert (await _importar(client, operator_headers, csv)).status_code == 200
    antes = await _total_de_analises(db_session)
    assert (await _importar(client, operator_headers, csv)).status_code == 200

    assert antes == await _total_de_analises(db_session) == 2
    [a, _] = await _analises(client, operator_headers, var_id)
    assert (a["value"], a["source"]) == (98.5, "csv")  # o CSV substituiu a análise manual


async def test_import_recusado_nao_grava_nada(client, admin_headers, operator_headers, db_session):
    await _ativar(client, admin_headers)
    await _variavel(client, admin_headers)
    csv = "pureza;01/03/2025 10:00;98,5\nfantasma;01/03/2025 10:00;1\npureza;ontem;2\n"

    r = await _importar(client, operator_headers, csv)

    assert r.status_code == 422
    linhas = r.json()["detail"].split("; ")
    assert len(linhas) == 2  # um motivo por linha ruim, unidos por "; "
    assert linhas[0].startswith("linha 2:") and linhas[1].startswith("linha 3:")
    assert await _total_de_analises(db_session) == 0


async def test_import_vazio_ou_so_cabecalho_e_422(client, admin_headers, operator_headers):
    await _ativar(client, admin_headers)
    await _variavel(client, admin_headers)

    for corpo in ("", '"nome do TAG";"data/hora";"valor"\n'):
        r = await _importar(client, operator_headers, corpo)
        assert r.status_code == 422, corpo
        assert r.json()["detail"] == "Arquivo sem análises para importar"


async def test_import_exige_tz(client, admin_headers, operator_headers):
    await _ativar(client, admin_headers)
    r = await client.post(
        IMPORT, content=b"pureza;01/03/2025 10:00;1", headers={**operator_headers, **CSV}
    )
    assert r.status_code == 422


async def test_import_grande_atravessa_o_limite_de_parametros_do_driver(
    client, admin_headers, operator_headers, db_session
):
    await _ativar(client, admin_headers)
    await _variavel(client, admin_headers)
    # 40 mil linhas: um INSERT único passaria dos 32767 parâmetros do asyncpg
    base = datetime(2025, 1, 1, tzinfo=UTC)
    linhas = (f"pureza;{(base + timedelta(minutes=i)).isoformat()};{i}" for i in range(40_000))

    r = await _importar(client, operator_headers, "\n".join(linhas))

    assert r.status_code == 200, r.text
    assert r.json()["imported"] == 40_000
    assert await _total_de_analises(db_session) == 40_000


async def test_import_acima_de_5_mib_e_413(client, operator_headers):
    msg = "Arquivo excede o limite de 5 MiB."
    grande = b"x" * (5 * 1024 * 1024 + 1)

    # Content-Length declarado
    r = await _importar(client, operator_headers, grande)
    assert (r.status_code, r.json()["detail"]) == (413, msg)

    # sem Content-Length (chunked): o teto é imposto durante a leitura do stream
    async def em_pedacos():
        for i in range(0, len(grande), 64 * 1024):
            yield grande[i : i + 64 * 1024]

    r = await client.post(
        IMPORT, params={"tz": "UTC"}, content=em_pedacos(), headers={**operator_headers, **CSV}
    )
    assert (r.status_code, r.json()["detail"]) == (413, msg)


# -------------------------------------------------------------------------- auditoria


async def test_eventos_de_auditoria_saem_depois_do_commit(
    client, admin_headers, operator_headers, eventos
):
    await _ativar(client, admin_headers)
    await eventos()  # descarta o evento de ativação do projeto
    admin = (await client.get("/api/auth/me", headers=admin_headers)).json()
    oper = (await client.get("/api/auth/me", headers=operator_headers)).json()

    var_id = await _variavel(client, admin_headers)
    await client.patch(f"{VARS}/{var_id}", json={"eu": "%"}, headers=admin_headers)
    await _lancar(client, operator_headers, var_id, 1.0, "2025-03-01T13:00:00Z")
    await client.delete(
        f"{VARS}/{var_id}/samples",
        params={"sampled_at": "2025-03-01T13:00:00Z"},
        headers=operator_headers,
    )
    await _importar(client, operator_headers, "pureza;01/03/2025 10:00;1")
    await client.delete(f"{VARS}/{var_id}", headers=admin_headers)

    recebidos = await eventos()
    assert [(e["payload"]["kind"], e["origin"], e["severity"]) for e in recebidos] == [
        (KIND_LAB_VARIABLE_CREATED, f"user:{admin['id']}", "info"),
        (KIND_LAB_VARIABLE_UPDATED, f"user:{admin['id']}", "info"),
        (KIND_LAB_SAMPLE_ADDED, f"user:{oper['id']}", "info"),
        (KIND_LAB_SAMPLE_DELETED, f"user:{oper['id']}", "info"),
        (KIND_LAB_SAMPLES_IMPORTED, f"user:{oper['id']}", "info"),
        (KIND_LAB_VARIABLE_DELETED, f"user:{admin['id']}", "info"),
    ]
    importado = recebidos[4]["payload"]
    assert importado["imported"] == 1 and importado["by_variable"] == {"pureza": 1}
    assert importado["project_id"] > 0


async def test_operacao_que_falha_nao_emite_evento(
    client, admin_headers, operator_headers, eventos
):
    await _ativar(client, admin_headers)
    await _variavel(client, admin_headers)
    await eventos()

    await client.post(VARS, json={"name": "pureza"}, headers=admin_headers)  # 409
    await client.post(VARS, json={"name": "a;b"}, headers=admin_headers)  # 422
    await _importar(client, operator_headers, "fantasma;01/03/2025 10:00;1")  # 422

    assert await eventos() == []
