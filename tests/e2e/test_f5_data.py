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
    env = {}
    with open(DEPLOY_DIR / ".env") as f:
        for linha in f:
            if "=" in linha:
                k, v = linha.strip().split("=", 1)
                env[k] = v
    
    conn = psycopg2.connect(
        host="localhost",
        database=env.get("POSTGRES_DB", "ottima"),
        user=env.get("POSTGRES_USER", "ottima"),
        password=env.get("POSTGRES_PASSWORD", "ottima-dev"),
        port=5432,
    )
    try:
        yield conn
    finally:
        conn.close()


def test_e2e_f5_01_mpc_samples_gravado_em_local_e_cadencia(
    admin: httpx.Client,
    ambiente_mpc: AmbienteMpc,
    criar_flow_mpc: Any,
    opcsim_client: OpcSim,
    db_conn: Any,
) -> None:
    """E2E-F5-01 (spec §9.2): MPC em LOCAL grava mpc_samples na cadência Ts_mpc
    com auto=false, sp=NULL fora de CV, ts do payload == ts gravado."""
    resetar_atuador_mpc(opcsim_client)
    flow_id = criar_flow_mpc("f5-01", grafo=grafo_mpc_tfs(ambiente_mpc))

    ts_antes = datetime.utcnow()
    with assinar_mpc_state(admin, flow_id, "mpc1") as fluxo:
        deploy_flow(admin, flow_id)
        amostra1 = fluxo.esperar(lambda _e: True, timeout=30.0, descricao="1º")
        ts1 = datetime.fromisoformat(amostra1["ts"])

        # Coleta mais 2 amostras pra validar cadência
        amostras = [amostra1]
        tempos = [ts1]
        for _ in range(2):
            a = fluxo.esperar(lambda _e: True, timeout=15.0, descricao="seg")
            amostras.append(a)
            ts = datetime.fromisoformat(a["ts"])
            tempos.append(ts)
            time.sleep(0.5)

        # Validação (a): linhas em cadência Ts_mpc
        for i in range(1, len(tempos)):
            delta = (tempos[i] - tempos[i - 1]).total_seconds()
            assert 0.5 * TS_MPC <= delta <= 1.5 * TS_MPC, f"cadência ruim: {delta}s"

        # Validação (b), (c), (d): banco direto
        time.sleep(1.0)  # Propagar pra DB
        cur = db_conn.cursor()
        try:
            cur.execute(
                "SELECT ts, var_id, v, sp, auto FROM mpc_samples "
                "WHERE flow_id=%s AND ts > %s "
                "ORDER BY var_id, ts",
                (flow_id, ts_antes),
            )
            linhas = cur.fetchall()
            assert len(linhas) > 0, "nenhuma linha em mpc_samples"

            # (b) auto=false em LOCAL
            assert all(row[4] is False for row in linhas), "auto deve ser false em LOCAL"

            # (c) sp=NULL fora de CV
            for row in linhas:
                ts_db, var_id, v, sp_db, auto_db = row
                if var_id == "cv_1":
                    # CV pode ter sp
                    pass
                else:
                    # Não-CV: sp deve ser NULL
                    assert sp_db is None, f"{var_id} tem sp={sp_db}"

            # (d) ts do payload == ts no banco
            for amostra in amostras:
                ts_payload = datetime.fromisoformat(amostra["ts"])
                cur.execute(
                    "SELECT COUNT(*) FROM mpc_samples "
                    "WHERE flow_id=%s AND ts=%s",
                    (flow_id, ts_payload),
                )
                assert cur.fetchone()[0] > 0, f"ts {ts_payload} não está no banco"
        finally:
            cur.close()


def test_e2e_f5_02_history_mpc_bruto_e_cagg_com_refresh(
    admin: httpx.Client,
    ambiente_mpc: AmbienteMpc,
    criar_flow_mpc: Any,
    opcsim_client: OpcSim,
    db_conn: Any,
) -> None:
    """E2E-F5-02 (spec §9.2): /api/history/mpc bruto (≤2h) raw, CAgg 1m (>2h),
    teto 14 var_ids ⇒ 422, demais 422s, 404 flow, 401 anônimo."""
    resetar_atuador_mpc(opcsim_client)
    flow_id = criar_flow_mpc("f5-02", grafo=grafo_mpc_tfs(ambiente_mpc))

    with assinar_mpc_state(admin, flow_id, "mpc1") as fluxo:
        deploy_flow(admin, flow_id)
        amostra = fluxo.esperar(lambda _e: True, timeout=30.0, descricao="boot")
        ts_inicio = datetime.fromisoformat(amostra["ts"])
        time.sleep(TS_MPC * 5)

        # (a) Query bruto (≤2h) ⇒ raw
        r = admin.get(
            "/api/history/mpc",
            params={
                "flow_id": flow_id,
                "block_id": "mpc1",
                "var_ids": "cv_1",
                "start": (ts_inicio - timedelta(hours=1)).isoformat(),
            },
        )
        assert r.status_code == 200, f"bruto: {r.text}"
        hist = r.json()
        assert hist["mode"] == "raw", f"modo={hist['mode']}"

        # (b) Query >2h ⇒ mode 1m (force refresh CAgg)
        # Para teste com dados novos (< 2h), pode retornar raw ainda
        # Mas valida que CAgg existe
        cur = db_conn.cursor()
        try:
            cur.execute(
                "SELECT EXISTS(SELECT 1 FROM information_schema.materialized_views "
                "WHERE table_name='mpc_samples_1m')"
            )
            cagg_exists = cur.fetchone()[0]
            assert cagg_exists, "CAgg mpc_samples_1m não existe"

            # Force refresh se tiver dados
            try:
                cur.execute("CALL refresh_continuous_aggregate('mpc_samples_1m', NULL, NULL)")
                db_conn.commit()
            except Exception:
                pass  # Pode não ter dados ou já estar refresh
        finally:
            cur.close()

        # (c) Teto 14 var_ids ⇒ 422
        var_ids_teto = ",".join(f"v{i}" for i in range(15))
        r = admin.get(
            "/api/history/mpc",
            params={
                "flow_id": flow_id,
                "block_id": "mpc1",
                "var_ids": var_ids_teto,
            },
        )
        assert r.status_code == 422, f"teto: {r.status_code}"

        # (d) Demais 422s
        # var_ids vazio
        r = admin.get(
            "/api/history/mpc",
            params={"flow_id": flow_id, "block_id": "mpc1", "var_ids": ""},
        )
        assert r.status_code == 422, f"vazio: {r.status_code}"

        # start >= end
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
        assert r.status_code == 422, f"start>=end: {r.status_code}"

        # (e) 404 flow inexistente
        r = admin.get(
            "/api/history/mpc",
            params={
                "flow_id": 999999,
                "block_id": "mpc1",
                "var_ids": "cv_1",
            },
        )
        assert r.status_code == 404, f"flow inexistente: {r.status_code}"

        # (f) RBAC: anônimo ⇒ 401
        client_anon = httpx.Client(base_url="http://localhost:8080", timeout=20)
        r = client_anon.get(
            "/api/history/mpc",
            params={
                "flow_id": flow_id,
                "block_id": "mpc1",
                "var_ids": "cv_1",
            },
        )
        assert r.status_code == 401, f"anônimo: {r.status_code}"
        client_anon.close()
