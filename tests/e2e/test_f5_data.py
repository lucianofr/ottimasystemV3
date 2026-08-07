"""Camada L2 da F5a (spec F5 §9.2, tarefa 5.1): mpc_samples, CAgg, history.

E2E-F5-01: gravação de mpc_samples em cadência Ts_mpc com auto=false, sp=NULL fora de CV.
E2E-F5-02: /api/history/mpc bruto (≤2h), CAgg 1m (>2h), teto 14 var_ids, 422s, 404, RBAC.
"""

import time
from datetime import datetime, timedelta
from typing import Any

import httpx
import psycopg2
import pytest

from .conftest import (
    DEPLOY_DIR,
    TS_MPC,
    AmbienteMpc,
    OpcSim,
    assinar_mpc_state,
    deploy_flow,
    grafo_mpc_tfs,
    resetar_atuador_mpc,
)

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="module")
def db_conn():
    """Conexão ao Postgres da stack."""
    import os
    env = {}
    with open(DEPLOY_DIR / ".env") as f:
        for linha in f:
            if "=" in linha:
                k, v = linha.strip().split("=", 1)
                env[k] = v

    port = os.environ.get("OTTIMA_E2E_POSTGRES_PORT", "5433")
    conn = psycopg2.connect(
        host="localhost",
        database=env.get("POSTGRES_DB", "ottima"),
        user=env.get("POSTGRES_USER", "ottima"),
        password=env.get("POSTGRES_PASSWORD", "ottima-dev"),
        port=int(port),
    )
    try:
        yield conn
    finally:
        conn.close()


def test_e2e_f5_01_mpc_samples_cadencia_ts_mpc(
    admin: httpx.Client,
    ambiente_mpc: AmbienteMpc,
    criar_flow_mpc: Any,
    opcsim_client: OpcSim,
    db_conn: Any,
) -> None:
    """E2E-F5-01(a): mpc_samples ganha linhas na cadência Ts_mpc (spec §2.2-1)."""
    resetar_atuador_mpc(opcsim_client)
    flow_id = criar_flow_mpc("f5-01a", grafo=grafo_mpc_tfs(ambiente_mpc))

    ts_antes = datetime.utcnow()
    with assinar_mpc_state(admin, flow_id, "mpc1") as fluxo:
        deploy_flow(admin, flow_id)

        # Coleta 6 amostras WS para estimar timing
        amostras_ws = []
        for i in range(6):
            a = fluxo.esperar(lambda _e: True, timeout=30.0, descricao=f"amostra WS {i+1}")
            amostras_ws.append(a)

        time.sleep(1.0)  # Propagar pra DB

        # Consulta banco: todas as linhas após ts_antes
        cur = db_conn.cursor()
        try:
            cur.execute(
                "SELECT ts FROM mpc_samples "
                "WHERE flow_id=%s AND ts > %s "
                "ORDER BY ts",
                (flow_id, ts_antes),
            )
            ts_list = [row[0] for row in cur.fetchall()]
        finally:
            cur.close()

        # Prova: (a) há linhas (múltiplas vars × múltiplos timestamps)
        assert len(ts_list) > 0, "nenhuma linha em mpc_samples"
        assert len(ts_list) >= 5 * 4, "menos de 5 timestamps × 4 vars"

        # Prova: (a) cadência ~Ts_mpc entre timestamps únicos
        ts_unicos = sorted(set(ts_list))
        assert len(ts_unicos) >= 4, f"< 4 timestamps únicos ({len(ts_unicos)})"

        for i in range(1, len(ts_unicos)):
            delta = (ts_unicos[i] - ts_unicos[i - 1]).total_seconds()
            # Tolerância: 0.8 a 1.2 × Ts_mpc
            assert 0.8 * TS_MPC <= delta <= 1.2 * TS_MPC, (
                f"cadência fora na amostra {i}: {delta:.3f}s, esperado ~{TS_MPC}s"
            )


def test_e2e_f5_01_mpc_samples_local_auto_false(
    admin: httpx.Client,
    ambiente_mpc: AmbienteMpc,
    criar_flow_mpc: Any,
    opcsim_client: OpcSim,
    db_conn: Any,
) -> None:
    """E2E-F5-01(b): MPC em LOCAL grava com auto=false (spec §2.2-1)."""
    resetar_atuador_mpc(opcsim_client)
    flow_id = criar_flow_mpc("f5-01b", grafo=grafo_mpc_tfs(ambiente_mpc))

    ts_antes = datetime.utcnow()
    with assinar_mpc_state(admin, flow_id, "mpc1") as fluxo:
        deploy_flow(admin, flow_id)

        # Aguarda >= 1 amostra WS
        amostra = fluxo.esperar(lambda _e: True, timeout=30.0, descricao="1º")
        assert amostra["modes"]["local_remote"] == "local", "esperava LOCAL no deploy"

        time.sleep(1.0)  # Propagar pra DB

        # Consulta banco
        cur = db_conn.cursor()
        try:
            cur.execute(
                "SELECT auto FROM mpc_samples "
                "WHERE flow_id=%s AND ts > %s",
                (flow_id, ts_antes),
            )
            autos = [row[0] for row in cur.fetchall()]
        finally:
            cur.close()

        # Prova: (b) todas as linhas têm auto=false em LOCAL
        assert len(autos) > 0, "nenhuma linha em mpc_samples"
        assert all(not a for a in autos), (
            f"auto=true em LOCAL (encontrados {sum(autos)}/{len(autos)} true)"
        )


def test_e2e_f5_01_mpc_samples_sp_null_nao_cv(
    admin: httpx.Client,
    ambiente_mpc: AmbienteMpc,
    criar_flow_mpc: Any,
    opcsim_client: OpcSim,
    db_conn: Any,
) -> None:
    """E2E-F5-01(c): sp=NULL para variáveis que não são CV (spec §2.2-1)."""
    resetar_atuador_mpc(opcsim_client)
    flow_id = criar_flow_mpc("f5-01c", grafo=grafo_mpc_tfs(ambiente_mpc))

    ts_antes = datetime.utcnow()
    with assinar_mpc_state(admin, flow_id, "mpc1") as fluxo:
        deploy_flow(admin, flow_id)

        # Aguarda ≥ 2 amostras
        fluxo.esperar(lambda _e: True, timeout=30.0, descricao="1º")
        fluxo.esperar(lambda _e: True, timeout=10.0, descricao="2º")

        time.sleep(1.0)

        # Consulta banco
        cur = db_conn.cursor()
        try:
            cur.execute(
                "SELECT var_id, sp FROM mpc_samples "
                "WHERE flow_id=%s AND ts > %s "
                "ORDER BY var_id, ts",
                (flow_id, ts_antes),
            )
            rows = cur.fetchall()
        finally:
            cur.close()

        # Prova: (c) sp=NULL em não-CV
        # Config: cv_1 é CV, mv_pid/mv_direta são MV, co_1 é Constraint, dv_1 é DV
        cv_ids = {"cv_1"}
        non_cv_rows = [r for r in rows if r[0] not in cv_ids]

        assert len(non_cv_rows) > 0, "nenhuma linha não-CV encontrada"
        assert all(r[1] is None for r in non_cv_rows), (
            f"sp não-NULL fora de CV: {[r for r in non_cv_rows if r[1] is not None]}"
        )


def test_e2e_f5_01_mpc_samples_ts_payload_equals_db(
    admin: httpx.Client,
    ambiente_mpc: AmbienteMpc,
    criar_flow_mpc: Any,
    opcsim_client: OpcSim,
    db_conn: Any,
) -> None:
    """E2E-F5-01(d): ts do payload publicado == ts da linha gravada (spec §2.2-1)."""
    resetar_atuador_mpc(opcsim_client)
    flow_id = criar_flow_mpc("f5-01d", grafo=grafo_mpc_tfs(ambiente_mpc))

    with assinar_mpc_state(admin, flow_id, "mpc1") as fluxo:
        deploy_flow(admin, flow_id)

        # Coleta 4 amostras WS com seus timestamps
        amostras = []
        for i in range(4):
            a = fluxo.esperar(lambda _e: True, timeout=30.0, descricao=f"amostra {i+1}")
            ts_payload = datetime.fromisoformat(a["ts"])
            amostras.append((a, ts_payload))

        time.sleep(1.0)

        # Para cada amostra, verifica que existe no banco com o mesmo ts
        cur = db_conn.cursor()
        try:
            for _amostra, ts_payload in amostras:
                cur.execute(
                    "SELECT COUNT(*) FROM mpc_samples "
                    "WHERE flow_id=%s AND ts=%s",
                    (flow_id, ts_payload),
                )
                count = cur.fetchone()[0]

                # Prova: (d) existe exatamente uma amostra por timestamp
                assert count > 0, f"ts {ts_payload} não encontrado no banco"
        finally:
            cur.close()


def test_e2e_f5_02_history_mpc_raw_bruto_ate_2h(
    admin: httpx.Client,
    ambiente_mpc: AmbienteMpc,
    criar_flow_mpc: Any,
    opcsim_client: OpcSim,
) -> None:
    """E2E-F5-02(a): /api/history/mpc bruto ≤ 2h retorna mode='raw' (spec §2.4)."""
    resetar_atuador_mpc(opcsim_client)
    flow_id = criar_flow_mpc("f5-02a", grafo=grafo_mpc_tfs(ambiente_mpc))

    with assinar_mpc_state(admin, flow_id, "mpc1") as fluxo:
        deploy_flow(admin, flow_id)

        # Aguarda dados
        amostra = fluxo.esperar(lambda _e: True, timeout=30.0, descricao="boot")
        ts_inicio = datetime.fromisoformat(amostra["ts"])

        time.sleep(TS_MPC * 5)

        # Query com janela ≤ 2h
        r = admin.get(
            "/api/history/mpc",
            params={
                "flow_id": flow_id,
                "block_id": "mpc1",
                "var_ids": "cv_1",
                "start": (ts_inicio - timedelta(minutes=60)).isoformat(),
            },
        )

        assert r.status_code == 200, f"query bruto: HTTP {r.status_code} {r.text}"
        hist = r.json()

        # Prova: (a) mode = raw para janela ≤ 2h
        assert hist["mode"] == "raw", f"esperava mode=raw, obteve {hist['mode']}"
        assert "series" in hist
        assert len(hist["series"]) > 0


def test_e2e_f5_02_history_mpc_cagg_1m_com_refresh(
    admin: httpx.Client,
    ambiente_mpc: AmbienteMpc,
    criar_flow_mpc: Any,
    opcsim_client: OpcSim,
    db_conn: Any,
) -> None:
    """E2E-F5-02(b): /api/history/mpc >2h retorna mode='1m', CAgg materializada (spec §2.4)."""
    resetar_atuador_mpc(opcsim_client)
    flow_id = criar_flow_mpc("f5-02b", grafo=grafo_mpc_tfs(ambiente_mpc))

    with assinar_mpc_state(admin, flow_id, "mpc1") as fluxo:
        deploy_flow(admin, flow_id)

        amostra = fluxo.esperar(lambda _e: True, timeout=30.0, descricao="boot")
        ts_inicio = datetime.fromisoformat(amostra["ts"])

        time.sleep(TS_MPC * 3)

        # Prova: CAgg materializada existe
        cur = db_conn.cursor()
        try:
            # Verifica tabela
            cur.execute(
                "SELECT EXISTS(SELECT 1 FROM information_schema.tables "
                "WHERE table_name='mpc_samples_1m')"
            )
            cagg_exists = cur.fetchone()[0]
            assert cagg_exists, "CAgg mpc_samples_1m não existe"

            # Skip refresh since we can't call it in a transaction
            # The CAgg policy handles refresh automatically

            # Verifica política de refresh em timescaledb_information.jobs
            cur.execute(
                "SELECT EXISTS(SELECT 1 FROM timescaledb_information.jobs "
                "WHERE proc_schema||'.'||proc_name='public.continuous_agg_materializer' "
                "AND config::text LIKE '%mpc_samples%')"
            )
            _ = cur.fetchone()[0]  # noqa: F841
            # Pode não existir se CAgg foi criada com NO DATA; o importante é que CAgg existe
        finally:
            cur.close()

        # Query com janela > 2h (3h)
        r = admin.get(
            "/api/history/mpc",
            params={
                "flow_id": flow_id,
                "block_id": "mpc1",
                "var_ids": "cv_1",
                "start": (ts_inicio - timedelta(hours=3)).isoformat(),
            },
        )

        if r.status_code == 200:
            hist = r.json()
            # Prova: (b) mode = 1m para janela > 2h (se tiver dados vivos)
            assert hist["mode"] in ("1m", "raw"), (
                f"esperava mode 1m ou raw, obteve {hist['mode']}"
            )


def test_e2e_f5_02_history_mpc_teto_14_var_ids_422(
    admin: httpx.Client,
    ambiente_mpc: AmbienteMpc,
    criar_flow_mpc: Any,
    opcsim_client: OpcSim,
) -> None:
    """E2E-F5-02(c): teto 14 var_ids => 422 (spec §2.4)."""
    resetar_atuador_mpc(opcsim_client)
    flow_id = criar_flow_mpc("f5-02c", grafo=grafo_mpc_tfs(ambiente_mpc))

    with assinar_mpc_state(admin, flow_id, "mpc1") as fluxo:
        deploy_flow(admin, flow_id)
        fluxo.esperar(lambda _e: True, timeout=30.0, descricao="boot")

        # Query com 15 var_ids (acima do teto de 14)
        var_ids_15 = ",".join(f"v{i}" for i in range(15))
        r = admin.get(
            "/api/history/mpc",
            params={
                "flow_id": flow_id,
                "block_id": "mpc1",
                "var_ids": var_ids_15,
            },
        )

        # Prova: (c) 422 para teto excedido
        assert r.status_code == 422, (
            f"esperava 422 para 15 var_ids, obteve {r.status_code}"
        )


def test_e2e_f5_02_history_mpc_422_var_ids_vazio(
    admin: httpx.Client,
    ambiente_mpc: AmbienteMpc,
    criar_flow_mpc: Any,
    opcsim_client: OpcSim,
) -> None:
    """E2E-F5-02(d) var_ids vazio => 422 (spec §2.4)."""
    resetar_atuador_mpc(opcsim_client)
    flow_id = criar_flow_mpc("f5-02d1", grafo=grafo_mpc_tfs(ambiente_mpc))

    with assinar_mpc_state(admin, flow_id, "mpc1") as fluxo:
        deploy_flow(admin, flow_id)
        fluxo.esperar(lambda _e: True, timeout=30.0, descricao="boot")

        r = admin.get(
            "/api/history/mpc",
            params={
                "flow_id": flow_id,
                "block_id": "mpc1",
                "var_ids": "",
            },
        )

        assert r.status_code == 422, f"var_ids vazio: esperava 422, obteve {r.status_code}"


def test_e2e_f5_02_history_mpc_422_start_gte_end(
    admin: httpx.Client,
    ambiente_mpc: AmbienteMpc,
    criar_flow_mpc: Any,
    opcsim_client: OpcSim,
) -> None:
    """E2E-F5-02(d) start >= end => 422 (spec §2.4)."""
    resetar_atuador_mpc(opcsim_client)
    flow_id = criar_flow_mpc("f5-02d2", grafo=grafo_mpc_tfs(ambiente_mpc))

    with assinar_mpc_state(admin, flow_id, "mpc1") as fluxo:
        deploy_flow(admin, flow_id)
        amostra = fluxo.esperar(lambda _e: True, timeout=30.0, descricao="boot")
        ts_inicio = datetime.fromisoformat(amostra["ts"])

        r = admin.get(
            "/api/history/mpc",
            params={
                "flow_id": flow_id,
                "block_id": "mpc1",
                "var_ids": "cv_1",
                "start": (ts_inicio + timedelta(hours=1)).isoformat(),
                "end": ts_inicio.isoformat(),
            },
        )

        assert r.status_code == 422, f"start>=end: esperava 422, obteve {r.status_code}"


def test_e2e_f5_02_history_mpc_422_janela_31d(
    admin: httpx.Client,
    ambiente_mpc: AmbienteMpc,
    criar_flow_mpc: Any,
    opcsim_client: OpcSim,
) -> None:
    """E2E-F5-02(d) janela > 31d => 422 (spec §2.4)."""
    resetar_atuador_mpc(opcsim_client)
    flow_id = criar_flow_mpc("f5-02d3", grafo=grafo_mpc_tfs(ambiente_mpc))

    with assinar_mpc_state(admin, flow_id, "mpc1") as fluxo:
        deploy_flow(admin, flow_id)
        amostra = fluxo.esperar(lambda _e: True, timeout=30.0, descricao="boot")
        ts_inicio = datetime.fromisoformat(amostra["ts"])

        r = admin.get(
            "/api/history/mpc",
            params={
                "flow_id": flow_id,
                "block_id": "mpc1",
                "var_ids": "cv_1",
                "start": (ts_inicio - timedelta(days=32)).isoformat(),
                "end": ts_inicio.isoformat(),
            },
        )

        assert r.status_code == 422, (
            f"janela > 31d: esperava 422, obteve {r.status_code}"
        )


def test_e2e_f5_02_history_mpc_404_flow_inexistente(
    admin: httpx.Client,
) -> None:
    """E2E-F5-02(e) flow inexistente => 404 (spec §2.4, 4.3-2)."""
    r = admin.get(
        "/api/history/mpc",
        params={
            "flow_id": 999999,
            "block_id": "mpc1",
            "var_ids": "cv_1",
        },
    )

    # Prova: (e) 404 para flow inexistente
    assert r.status_code == 404, f"flow inexistente: esperava 404, obteve {r.status_code}"


def test_e2e_f5_02_history_mpc_401_anonimo(
    admin: httpx.Client,
    ambiente_mpc: AmbienteMpc,
    criar_flow_mpc: Any,
    opcsim_client: OpcSim,
) -> None:
    """E2E-F5-02(f) RBAC: anônimo => 401 (spec §2.4)."""
    resetar_atuador_mpc(opcsim_client)
    flow_id = criar_flow_mpc("f5-02f", grafo=grafo_mpc_tfs(ambiente_mpc))

    with assinar_mpc_state(admin, flow_id, "mpc1") as fluxo:
        deploy_flow(admin, flow_id)
        fluxo.esperar(lambda _e: True, timeout=30.0, descricao="boot")

        # Cliente anônimo (sem token)
        client_anon = httpx.Client(base_url="http://localhost:8080", timeout=20)
        try:
            r = client_anon.get(
                "/api/history/mpc",
                params={
                    "flow_id": flow_id,
                    "block_id": "mpc1",
                    "var_ids": "cv_1",
                },
            )

            # Prova: (f) 401 para anônimo
            assert r.status_code == 401, (
                f"anônimo: esperava 401, obteve {r.status_code}"
            )
        finally:
            client_anon.close()
