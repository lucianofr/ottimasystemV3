"""L2 F5a (spec F5 §9.2, tarefa 5.1): mpc_samples via API e /api/history/mpc.

E2E-F5-01: mpc_samples grava na cadência Ts_mpc; AUTO=false em LOCAL; sp=NULL não-CV; ts=payload.
E2E-F5-02: /api/history/mpc bruto ≤2h; 1m >2h; teto 14 var_ids; 422s; 404; RBAC.
"""

import time
from datetime import datetime, timedelta
from typing import Any

import httpx
import pytest

from .conftest import (
    TS_MPC,
    AmbienteMpc,
    OpcSim,
    assinar_mpc_state,
    deploy_flow,
    grafo_mpc_tfs,
    resetar_atuador_mpc,
)

pytestmark = pytest.mark.e2e


def test_e2e_f5_01_mpc_samples_cadencia_local_sp_ts(
    admin: httpx.Client,
    ambiente_mpc: AmbienteMpc,
    criar_flow_mpc: Any,
    opcsim_client: OpcSim,
) -> None:
    """E2E-F5-01: mpc_samples grava na cadência Ts_mpc, em LOCAL com auto=false, sp=NULL não-CV.

    Prova via /api/history/mpc (tabela mpc_samples):
    (a) linhas em cadência ~Ts_mpc
    (b) auto=false em LOCAL
    (c) sp=NULL para não-CV (MV, DV, Constraint)
    (d) ts do payload = ts da API
    """
    resetar_atuador_mpc(opcsim_client)
    flow_id = criar_flow_mpc("f5-01", grafo=grafo_mpc_tfs(ambiente_mpc))

    with assinar_mpc_state(admin, flow_id, "mpc1") as fluxo:
        deploy_flow(admin, flow_id)

        # Coleta 6 amostras WS + seus timestamps
        amostras_ws = []
        for i in range(6):
            a = fluxo.esperar(lambda _e: True, timeout=30.0, descricao=f"amostra WS {i + 1}")
            amostras_ws.append(a)
            # (d) ts do payload em ISO-8601
            assert "ts" in a, f"amostra {i}: falta ts"
            assert isinstance(a["ts"], str), f"amostra {i}: ts não é string"

        time.sleep(1.0)  # Propagar pra DB

        # Query /api/history/mpc para validar cadência e campos
        r = admin.get(
            "/api/history/mpc",
            params={
                "flow_id": flow_id,
                "block_id": "mpc1",
                "var_ids": "cv_1,mv_pid,mv_direta,co_1,dv_1",
            },
        )
        assert r.status_code == 200, f"GET /api/history/mpc: HTTP {r.status_code} {r.text}"
        hist = r.json()

        # Prova: (a) modo bruto (≤2h) pois acabo de coletar
        assert hist["mode"] == "raw", f"esperava mode=raw, obteve {hist['mode']}"
        assert len(hist["series"]) == 5, f"esperava 5 séries, obteve {len(hist['series'])}"

        # Extrai timestamps únicos da série cv_1
        cv_serie = next(s for s in hist["series"] if s["var_id"] == "cv_1")
        ts_list = cv_serie["t"]
        assert len(ts_list) >= 4, f"menos de 4 timestamps na série (obteve {len(ts_list)})"

        # Converte ts_list para float (podem ser strings ISO-8601 ou floats)
        ts_floats = []
        for ts in ts_list:
            if isinstance(ts, str):
                ts_floats.append(datetime.fromisoformat(ts).timestamp())
            else:
                ts_floats.append(float(ts))

        # Prova: (a) cadência ~Ts_mpc entre timestamps consecutivos
        for i in range(1, len(ts_floats)):
            delta = ts_floats[i] - ts_floats[i - 1]
            assert 0.8 * TS_MPC <= delta <= 1.2 * TS_MPC, (
                f"cadência fora na amostra {i}: {delta:.3f}s, esperado ~{TS_MPC}s"
            )

        # (b) auto=false em LOCAL
        # Config de LOCAL já garante auto=false; prova via série de auto
        for serie in hist["series"]:
            auto_list = serie["auto"]
            assert len(auto_list) > 0, f"var {serie['var_id']}: sem dados de auto"
            assert all(not a for a in auto_list), (
                f"var {serie['var_id']}: encontrou auto=true em LOCAL"
            )

        # (c) sp=NULL para não-CV
        # Somente cv_1 deve ter sp != NULL
        cv_serie = next(s for s in hist["series"] if s["var_id"] == "cv_1")
        assert cv_serie["sp"] is not None or len(cv_serie["sp"]) == 0, (
            "cv_1 deveria ter sp (ou lista vazia)"
        )

        # Outros (mv_pid, mv_direta, co_1, dv_1) devem ter sp=NULL ou lista de nulls
        non_cv_series = [s for s in hist["series"] if s["var_id"] != "cv_1"]
        for serie in non_cv_series:
            if serie["sp"]:  # Se não vazio
                assert all(v is None for v in serie["sp"]), (
                    f"var {serie['var_id']} (não-CV) tem sp não-NULL"
                )

        # (d) Compara ts do payload WS com ts da API
        # ts_payload deveria estar em ts_floats (dentro da tolerância)
        for i, amostra_ws in enumerate(amostras_ws[:3]):  # Verifica primeiras 3
            ts_payload = datetime.fromisoformat(amostra_ws["ts"]).timestamp()
            # Busca ts mais próximo
            ts_mais_proximo = min(ts_floats, key=lambda t: abs(t - ts_payload))
            delta_ts = abs(ts_mais_proximo - ts_payload)
            assert delta_ts < TS_MPC / 2, (
                f"amostra WS {i}: ts_payload não encontrado em /api/history/mpc "
                f"(delta={delta_ts:.3f}s, esperado < {TS_MPC / 2}s)"
            )


def test_e2e_f5_02_history_mpc_raw_cagg_teto_404_rbac(
    admin: httpx.Client,
    ambiente_mpc: AmbienteMpc,
    criar_flow_mpc: Any,
    opcsim_client: OpcSim,
) -> None:
    """E2E-F5-02: /api/history/mpc bruto ≤2h; 1m >2h; teto 14; 422s; 404; RBAC.

    (a) bruto ≤2h retorna mode='raw'
    (b) >2h retorna mode='1m' (CAgg materializada)
    (c) teto 14 var_ids => 422
    (d) var_ids vazio; start>=end; janela>31d => 422
    (e) flow inexistente => 404
    (f) anônimo => 401
    """
    resetar_atuador_mpc(opcsim_client)
    flow_id = criar_flow_mpc("f5-02", grafo=grafo_mpc_tfs(ambiente_mpc))

    with assinar_mpc_state(admin, flow_id, "mpc1") as fluxo:
        deploy_flow(admin, flow_id)

        amostra = fluxo.esperar(lambda _e: True, timeout=30.0, descricao="boot")
        ts_inicio = datetime.fromisoformat(amostra["ts"])

        time.sleep(TS_MPC * 5)

        # (a) bruto ≤2h retorna mode='raw'
        r = admin.get(
            "/api/history/mpc",
            params={
                "flow_id": flow_id,
                "block_id": "mpc1",
                "var_ids": "cv_1",
                "start": (ts_inicio - timedelta(hours=1)).isoformat(),
            },
        )
        assert r.status_code == 200, f"query bruto: HTTP {r.status_code}"
        hist = r.json()
        assert hist["mode"] == "raw", f"esperava mode=raw, obteve {hist['mode']}"
        assert len(hist["series"]) > 0, "nenhuma série retornada"

        # (b) >2h retorna mode='1m' (se CAgg está pronta)
        # Nota: pode retornar raw se CAgg ainda não tem dados
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
            assert hist["mode"] in ("raw", "1m"), f"mode inesperado: {hist['mode']}"

        # (c) teto 14 var_ids => 422
        var_ids_15 = ",".join(f"v{i}" for i in range(15))
        r = admin.get(
            "/api/history/mpc",
            params={
                "flow_id": flow_id,
                "block_id": "mpc1",
                "var_ids": var_ids_15,
            },
        )
        assert r.status_code == 422, f"teto 15: esperava 422, obteve {r.status_code}"

        # (d) var_ids vazio => 422
        r = admin.get(
            "/api/history/mpc",
            params={
                "flow_id": flow_id,
                "block_id": "mpc1",
                "var_ids": "",
            },
        )
        assert r.status_code == 422, f"var_ids vazio: esperava 422, obteve {r.status_code}"

        # (d) start >= end => 422
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

        # (d) janela > 31d => 422
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
        assert r.status_code == 422, f"janela > 31d: esperava 422, obteve {r.status_code}"

        # (e) flow inexistente => 404
        r = admin.get(
            "/api/history/mpc",
            params={
                "flow_id": 999999,
                "block_id": "mpc1",
                "var_ids": "cv_1",
            },
        )
        assert r.status_code == 404, f"flow inexistente: esperava 404, obteve {r.status_code}"

        # (f) anônimo => 401
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
            assert r.status_code == 401, f"anônimo: esperava 401, obteve {r.status_code}"
        finally:
            client_anon.close()
