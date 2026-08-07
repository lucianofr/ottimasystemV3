#!/usr/bin/env python3
"""Setup idempotente do ambiente L3: projeto + conexão + flow MPC+TFS + usuário operador.

Reusa helpers de tests/e2e/conftest.py; executa via `uv run python scripts/setup-l3.py`.
Idempotente: rodar 2x não duplica projeto/conexão/flow/usuário.

Retorno: resumo em stdout com project_id, connection_id, flow_id, mpc_block_id,
e URL /operacao/<flow_id>/<block_id>.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

# Imports de conftest.py (reuso de helpers e constantes)
# NOTA: sys.path já contém . (repo root) via uv run
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.e2e.conftest import (
    OPCSIM_URL,
    TS_FLOW_MPC,
    AmbienteMpc,
    grafo_mpc_tfs,
)

if TYPE_CHECKING:
    from httpx import Client

# ============================================================================
# Constantes e configuração
# ============================================================================

REPO_ROOT = Path(__file__).resolve().parents[1]
DEPLOY_DIR = REPO_ROOT / "deploy"

# Sufixo estável para a L3: "L3 F5 operacao" é o nome fixo do projeto.
PROJECT_NAME = "L3 F5 operacao"
CONNECTION_NAME = "opcsim-l3"
OPERATOR_USERNAME = "operador_e2e"
OPERATOR_PASSWORD = "OperadorE2E#2026"


def _deploy_env() -> dict[str, str]:
    """Lê pares do `deploy/.env` sem exportar."""
    valores: dict[str, str] = {}
    arquivo = DEPLOY_DIR / ".env"
    if not arquivo.exists():
        return valores
    for linha in arquivo.read_text(encoding="utf-8").splitlines():
        limpa = linha.strip()
        if not limpa or limpa.startswith("#") or "=" not in limpa:
            continue
        chave, _, valor = limpa.partition("=")
        valores[chave.strip()] = valor.strip()
    return valores


_DEPLOY = _deploy_env()


def _conf(nome: str, default: str) -> str:
    """Ambiente do processo vence; `deploy/.env` é o fallback; depois o default."""
    return os.environ.get(nome) or _DEPLOY.get(nome) or default


BASE = _conf("E2E_BASE_URL", "http://localhost:8080")
ADMIN_USER = _conf("E2E_ADMIN_USERNAME", _conf("OTTIMA_ADMIN_USERNAME", "admin"))
ADMIN_PASS = _conf("E2E_ADMIN_PASSWORD", _conf("OTTIMA_ADMIN_PASSWORD", ""))


# ============================================================================
# Helpers
# ============================================================================


def _criar_tag(admin: Client, conn_id: int, nome: str, node_id: str, direcao: str) -> int:
    """Cria tag ou retorna existente (idempotente por nome)."""
    # Tenta criar
    r = admin.post(
        "/api/tags",
        json={
            "connection_id": conn_id,
            "name": nome,
            "node_id": node_id,
            "direction": direcao,
            "data_type": "float",
        },
    )
    if r.status_code == 201:
        return int(r.json()["id"])
    if r.status_code == 409:
        # Já existe; recupera via GET
        r = admin.get(f"/api/tags?connection_id={conn_id}")
        if r.status_code == 200:
            for tag in r.json():
                if tag["name"] == nome:
                    return int(tag["id"])
    raise RuntimeError(f"Falha ao criar/recuperar tag {nome}: HTTP {r.status_code} {r.text}")


# ============================================================================
# Setup principal
# ============================================================================


def main() -> None:
    """Executa o setup idempotente do ambiente L3."""
    with httpx.Client(base_url=BASE, timeout=20) as admin:
        print(f"[*] Conectando a {BASE} como admin...", file=sys.stderr)

        # Autentica
        r = admin.post(
            "/api/auth/login",
            json={"username": ADMIN_USER, "password": ADMIN_PASS},
        )
        if r.status_code != 200:
            print(f"[!] Falha na autenticação: HTTP {r.status_code} {r.text}", file=sys.stderr)
            sys.exit(1)
        token = r.json()["access_token"]
        admin.headers["Authorization"] = f"Bearer {token}"
        print(f"[+] Autenticado como {ADMIN_USER}", file=sys.stderr)

        # ====================================================================
        # 1. Projeto
        # ====================================================================
        print(f"[*] Procurando projeto '{PROJECT_NAME}'...", file=sys.stderr)
        r = admin.get("/api/projects")
        if r.status_code != 200:
            print(f"[!] Falha ao listar projetos: HTTP {r.status_code}", file=sys.stderr)
            sys.exit(1)
        projetos = r.json()
        projeto_id = None
        for p in projetos:
            if p["name"] == PROJECT_NAME:
                projeto_id = int(p["id"])
                print(f"[+] Projeto encontrado: id={projeto_id}", file=sys.stderr)
                break

        if projeto_id is None:
            print(f"[*] Criando projeto '{PROJECT_NAME}'...", file=sys.stderr)
            r = admin.post("/api/projects", json={"name": PROJECT_NAME})
            if r.status_code != 201:
                print(f"[!] Falha ao criar projeto: HTTP {r.status_code} {r.text}", file=sys.stderr)
                sys.exit(1)
            projeto_id = int(r.json()["id"])
            print(f"[+] Projeto criado: id={projeto_id}", file=sys.stderr)

        # Ativa o projeto
        print(f"[*] Ativando projeto {projeto_id}...", file=sys.stderr)
        r = admin.post(f"/api/projects/{projeto_id}/activate")
        if r.status_code != 200:
            print(f"[!] Falha ao ativar: HTTP {r.status_code} {r.text}", file=sys.stderr)
            sys.exit(1)
        print("[+] Projeto ativo", file=sys.stderr)

        # ====================================================================
        # 2. Conexão OPC
        # ====================================================================
        print(f"[*] Procurando conexão '{CONNECTION_NAME}'...", file=sys.stderr)
        r = admin.get("/api/connections")
        if r.status_code != 200:
            print(f"[!] Falha ao listar conexões: HTTP {r.status_code}", file=sys.stderr)
            sys.exit(1)
        conexoes = r.json()
        conn_id = None
        for c in conexoes:
            if c["name"] == CONNECTION_NAME and c["project_id"] == projeto_id:
                conn_id = int(c["id"])
                print(f"[+] Conexão encontrada: id={conn_id}", file=sys.stderr)
                break

        if conn_id is None:
            print(f"[*] Criando conexão '{CONNECTION_NAME}'...", file=sys.stderr)
            r = admin.post(
                "/api/connections",
                json={
                    "project_id": projeto_id,
                    "name": CONNECTION_NAME,
                    "endpoint": OPCSIM_URL,
                    "security_policy": "none",
                    "security_mode": "none",
                    "auth_mode": "anonymous",
                    "watchdog_read_node_id": "ns=2;s=sim.watchdog.to_system",
                    "watchdog_write_node_id": "ns=2;s=sim.watchdog.from_system",
                    "watchdog_period_ms": 1000,
                },
            )
            if r.status_code != 201:
                print(
                    f"[!] Falha ao criar conexão: HTTP {r.status_code} {r.text}",
                    file=sys.stderr,
                )
                sys.exit(1)
            conn_id = int(r.json()["id"])
            print(f"[+] Conexão criada: id={conn_id}", file=sys.stderr)

        # Espera a conexão ficar up
        print("[*] Aguardando conexão estar operacional...", file=sys.stderr)
        for _ in range(30):
            r = admin.get(f"/api/connections/{conn_id}/health")
            if r.status_code == 200 and r.json().get("up"):
                print("[+] Conexão operacional", file=sys.stderr)
                break
            time.sleep(1.0)

        # ====================================================================
        # 3. Tags do PID de mv_pid (reusa constantes de conftest)
        # ====================================================================
        print("[*] Criando/verificando tags...", file=sys.stderr)
        tag_write = _criar_tag(admin, conn_id, "mv-pid-write", "ns=2;s=sim.output.float", "w")
        tag_mode_cmd = _criar_tag(admin, conn_id, "mv-pid-mode-cmd", "ns=2;s=sim.output.int", "w")
        tag_readback = _criar_tag(
            admin, conn_id, "mv-pid-readback", "ns=2;s=sim.mirror.float", "r"
        )
        tag_mode_read = _criar_tag(
            admin, conn_id, "mv-pid-mode-read", "ns=2;s=sim.mirror.int", "r"
        )
        print(
            f"[+] Tags: write={tag_write}, mode_cmd={tag_mode_cmd}, "
            f"readback={tag_readback}, mode_read={tag_mode_read}",
            file=sys.stderr,
        )

        # ====================================================================
        # 4. Flow com grafo MPC+TFS (reusa grafo_mpc_tfs de conftest)
        # ====================================================================
        ambiente = AmbienteMpc(
            project_id=projeto_id,
            conn_id=conn_id,
            write=tag_write,
            mode_cmd=tag_mode_cmd,
            readback=tag_readback,
            mode_read=tag_mode_read,
        )

        # Procura flow existente
        print("[*] Procurando flow existente...", file=sys.stderr)
        r = admin.get(f"/api/flows?project_id={projeto_id}")
        if r.status_code != 200:
            print(f"[!] Falha ao listar flows: HTTP {r.status_code}", file=sys.stderr)
            sys.exit(1)
        flows = r.json()
        flow_id = None
        for f in flows:
            if f["project_id"] == projeto_id:
                flow_id = int(f["id"])
                print(f"[+] Flow encontrado: id={flow_id}", file=sys.stderr)
                break

        if flow_id is None:
            print("[*] Criando flow...", file=sys.stderr)
            r = admin.post(
                "/api/flows",
                json={
                    "project_id": projeto_id,
                    "name": "L3-flow-operacao",
                    "ts_seconds": TS_FLOW_MPC,
                },
            )
            if r.status_code != 201:
                print(f"[!] Falha ao criar flow: HTTP {r.status_code} {r.text}", file=sys.stderr)
                sys.exit(1)
            flow_id = int(r.json()["id"])
            print(f"[+] Flow criado: id={flow_id}", file=sys.stderr)

        # SEMPRE atualizar grafo (idempotente: PUT com mesmo grafo é seguro)
        print("[*] Atualizando grafo do flow...", file=sys.stderr)
        grafo = grafo_mpc_tfs(ambiente, mpc_id="mpc1")
        r = admin.put(f"/api/flows/{flow_id}", json={"graph_json": grafo})
        if r.status_code != 200:
            print(
                "[!] Falha ao atualizar grafo: "
                f"HTTP {r.status_code} {r.text}",
                file=sys.stderr,
            )
            sys.exit(1)
        print("[+] Grafo atualizado", file=sys.stderr)

        # Verifica que o grafo foi salvo
        r = admin.get(f"/api/flows/{flow_id}")
        if r.status_code == 200:
            flow_data = r.json()
            num_nodes = len(flow_data.get("graph_json", {}).get("nodes", []))
            print(f"[+] Grafo verificado: {num_nodes} nó(s)", file=sys.stderr)

        # ====================================================================
        # 5. Deploy do flow
        # ====================================================================
        print("[*] Deployando flow...", file=sys.stderr)
        r = admin.post(f"/api/flows/{flow_id}/deploy")
        if r.status_code != 202:
            print(f"[!] Falha no deploy: HTTP {r.status_code} {r.text}", file=sys.stderr)
            sys.exit(1)
        print("[+] Flow deployado", file=sys.stderr)

        # Aguarda o runtime materializar
        print("[*] Aguardando flow estar running...", file=sys.stderr)
        for _ in range(30):
            r = admin.get(f"/api/flows/{flow_id}")
            if r.status_code == 200 and r.json().get("state") == "running":
                print("[+] Flow running", file=sys.stderr)
                break
            time.sleep(1.0)

        # Verifica que o MPC está disponível em /api/operate/mpcs
        print("[*] Verificando MPC em /api/operate/mpcs...", file=sys.stderr)
        r = admin.get("/api/operate/mpcs")
        if r.status_code == 200:
            mpcs = r.json()
            mpc_found = any(
                m.get("flow_id") == flow_id and m.get("block_id") == "mpc1" for m in mpcs
            )
            if mpc_found:
                print("[+] MPC registrado em /api/operate/mpcs", file=sys.stderr)
            else:
                print("[!] Aviso: MPC não encontrado em /api/operate/mpcs", file=sys.stderr)

        # ====================================================================
        # 6. Usuário operador
        # ====================================================================
        print("[*] Procurando usuário operador...", file=sys.stderr)
        r = admin.get("/api/users")
        if r.status_code == 200:
            usuarios = r.json()
            operador_existe = any(u["username"] == OPERATOR_USERNAME for u in usuarios)
        else:
            operador_existe = False

        if not operador_existe:
            print("[*] Criando usuário operador...", file=sys.stderr)
            r = admin.post(
                "/api/users",
                json={
                    "username": OPERATOR_USERNAME,
                    "name": "Operador E2E",
                    "password": OPERATOR_PASSWORD,
                    "role": "operator",
                },
            )
            if r.status_code != 201:
                print(
                    f"[!] Falha ao criar operador: HTTP {r.status_code} {r.text}",
                    file=sys.stderr,
                )
                sys.exit(1)
            print(f"[+] Operador criado: {OPERATOR_USERNAME}", file=sys.stderr)
        else:
            print(f"[+] Operador existente: {OPERATOR_USERNAME}", file=sys.stderr)

        # ====================================================================
        # 7. Resumo
        # ====================================================================
        print("\n" + "=" * 70, file=sys.stderr)
        print("SETUP L3 CONCLUÍDO COM SUCESSO", file=sys.stderr)
        print("=" * 70, file=sys.stderr)

        # Extrai block_id (id do MPC no grafo)
        mpc_block_id = "mpc1"
        operacao_url = f"{BASE}/operacao/{flow_id}/{mpc_block_id}"

        resultado = {
            "status": "ok",
            "project_id": projeto_id,
            "connection_id": conn_id,
            "flow_id": flow_id,
            "block_id": mpc_block_id,
            "operacao_url": operacao_url,
            "operator_username": OPERATOR_USERNAME,
        }

        print("\nResumo do ambiente L3:", file=sys.stderr)
        print(f"  project_id:      {projeto_id}", file=sys.stderr)
        print(f"  connection_id:   {conn_id}", file=sys.stderr)
        print(f"  flow_id:         {flow_id}", file=sys.stderr)
        print(f"  block_id (MPC):  {mpc_block_id}", file=sys.stderr)
        print(f"  Operacao URL:    {operacao_url}", file=sys.stderr)
        print(f"  Operador:        {OPERATOR_USERNAME}", file=sys.stderr)
        print("=" * 70, file=sys.stderr)

        # Output em JSON para parsing automatizado
        print(json.dumps(resultado, indent=2))


if __name__ == "__main__":
    main()
