#!/usr/bin/env python3
"""Supervisor de campanha: mantem o MPC da debutanizadora rodando em REMOTO+AUTO.

Um `comm_failure` de OPC derruba o flow em definitivo (ADR-017: retomada e so por
deploy manual) e o bloco MPC volta para LOCAL. Numa campanha de horas isso pararia o
controle na primeira piscada de rede. Este laco faz o que um operador faria: detecta o
flow fora do ar, redeploya, rearma REMOTO+AUTO e reaplica os setpoints correntes.

Os setpoints vivem em `planta_virtual/setpoints.json` -- alterar o arquivo muda o alvo
na proxima passada, e e assim que os testes de degrau desta campanha sao feitos.

    uv run python planta_virtual/supervisor_mpc.py
"""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

RAIZ = Path(__file__).resolve().parents[1]
SETPOINTS = RAIZ / "planta_virtual" / "setpoints.json"
FLOW_NOME = "Controle-MPC-Debutanizadora"
BLOCO = "mpc1"
INTERVALO_S = 15.0
TOLERANCIA_SP = 1e-6


def agora() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def log(msg: str) -> None:
    print(f"{agora()} {msg}", flush=True)


def _env() -> dict[str, str]:
    valores: dict[str, str] = {}
    for linha in (RAIZ / "deploy" / ".env").read_text().splitlines():
        linha = linha.strip()
        if linha and not linha.startswith("#") and "=" in linha:
            chave, _, valor = linha.partition("=")
            valores[chave.strip()] = valor.strip()
    return valores


def login() -> httpx.Client:
    env = _env()
    cliente = httpx.Client(
        base_url=os.environ.get("OTTIMA_BASE_URL", "http://localhost:8080"), timeout=30.0
    )
    r = cliente.post(
        "/api/auth/login",
        json={
            "username": env["OTTIMA_ADMIN_USERNAME"],
            "password": env["OTTIMA_ADMIN_PASSWORD"],
        },
    )
    r.raise_for_status()
    cliente.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return cliente


def flow_id(api: httpx.Client) -> int:
    for f in api.get("/api/flows").json():
        if f["name"] == FLOW_NOME:
            return int(f["id"])
    raise SystemExit(f"flow '{FLOW_NOME}' nao encontrado")


def alvos() -> dict[str, float]:
    if not SETPOINTS.exists():
        return {}
    return {k: float(v) for k, v in json.loads(SETPOINTS.read_text()).items()}


def estado_bloco(api: httpx.Client, fid: int) -> dict[str, Any]:
    flows = api.get("/api/health/workers").json().get("flow_runtime", {}).get("flows", {})
    flow = flows.get(str(fid), {})
    return {"state": flow.get("state"), "mpc": flow.get("mpc", {}).get(BLOCO, {})}


def sp_vigentes(api: httpx.Client, fid: int) -> dict[str, float]:
    """Ultimo SP publicado por CV (fonte: `mpc_samples`, o mesmo que alimenta o trend)."""
    ids = ",".join(alvos())
    if not ids:
        return {}
    r = api.get("/api/history/mpc", params={"flow_id": fid, "block_id": BLOCO, "var_ids": ids})
    if r.status_code != 200:
        return {}
    saida: dict[str, float] = {}
    for serie in r.json()["series"]:
        if serie["sp"] and serie["sp"][-1] is not None:
            saida[serie["var_id"]] = float(serie["sp"][-1])
    return saida


def aplicar_sp(api: httpx.Client, fid: int, desejado: dict[str, float]) -> None:
    for var_id, valor in desejado.items():
        r = api.post(f"/api/operate/{fid}/{BLOCO}/sp", json={"var_id": var_id, "value": valor})
        log(f"  sp {var_id} := {valor} -> HTTP {r.status_code}")


def armar(api: httpx.Client, fid: int) -> None:
    """Leva o bloco a REMOTO+AUTO e reaplica os setpoints do arquivo.

    O gate de armar exige entradas ja medidas (`cold_input`), entao a espera antes do
    primeiro comando nao e folga: logo apos um deploy o bloco ainda nao viu nenhuma CV.
    """
    time.sleep(25.0)
    for eixo, valor in (("local_remote", "remote"), ("man_auto", "auto")):
        r = api.post(f"/api/operate/{fid}/{BLOCO}/mode", json={"axis": eixo, "value": valor})
        log(f"  modo {eixo}={valor} -> HTTP {r.status_code}")
        time.sleep(12.0)
    estado = estado_bloco(api, fid)
    log(f"  modo apos rearme: {json.dumps(estado['mpc'].get('mode'))}")
    if estado["mpc"].get("mode", {}).get("man_auto") == "auto":
        aplicar_sp(api, fid, alvos())


def rearmar(api: httpx.Client, fid: int) -> None:
    log("flow fora do ar: redeployando")
    r = api.post(f"/api/flows/{fid}/deploy")
    log(f"  deploy -> HTTP {r.status_code}")
    for _ in range(60):
        time.sleep(2.0)
        if estado_bloco(api, fid)["state"] == "running":
            break
    else:
        log("  flow nao voltou a rodar; nova tentativa na proxima passada")
        return
    armar(api, fid)


def main() -> None:
    api = login()
    fid = flow_id(api)
    log(f"supervisor ativo sobre flow {fid}/{BLOCO}")
    ultimo_estado = ""
    while True:
        try:
            estado = estado_bloco(api, fid)
            modo = estado["mpc"].get("mode", {})
            resumo = f"{estado['state']}/{modo.get('local_remote')}/{modo.get('man_auto')}"
            if resumo != ultimo_estado:
                log(f"estado: {resumo}")
                ultimo_estado = resumo
            if estado["state"] != "running":
                rearmar(api, fid)
                ultimo_estado = ""
            elif modo.get("local_remote") != "remote" or modo.get("man_auto") != "auto":
                # Redeploy (hot-swap de config) devolve o bloco a LOCAL/MAN com o flow de pe.
                log("bloco fora de REMOTO+AUTO: rearmando")
                armar(api, fid)
                ultimo_estado = ""
            else:
                desejado = alvos()
                vigente = sp_vigentes(api, fid)
                divergente = {
                    k: v
                    for k, v in desejado.items()
                    if k not in vigente or abs(vigente[k] - v) > TOLERANCIA_SP
                }
                if divergente:
                    log(f"reaplicando setpoints divergentes: {divergente}")
                    aplicar_sp(api, fid, divergente)
        except Exception as exc:  # noqa: BLE001 - supervisor nunca pode morrer
            log(f"erro na passada: {type(exc).__name__}: {exc}")
        time.sleep(INTERVALO_S)


if __name__ == "__main__":
    main()
