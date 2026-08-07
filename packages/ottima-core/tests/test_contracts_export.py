import json
import re
from pathlib import Path

from ottima_core.contracts_export import build_contracts, main

# frontend/src/lib/contracts.gen.ts: gerado a partir daqui via `npm run generate:contracts`
# (tarefa 1.3, débito 0.2 da F4) — fonte única = build_contracts(), não editar à mão.
GEN_TS_PATH = Path(__file__).resolve().parents[3] / "frontend" / "src" / "lib" / "contracts.gen.ts"


def test_json_tem_os_5_tipos_de_bloco():
    contratos = build_contracts()
    assert set(contratos["port_contracts"]) == {"opc_read", "opc_write", "script", "tfs", "mpc"}


def test_schemas_ws_presentes():
    # MpcVarState (spec F4 §5.1, tarefa 1.3) vem aninhado no schema de MpcState
    # (`vars: dict[str, MpcVarState]`) — não é chave própria de `ws_payloads`.
    contratos = build_contracts()
    assert set(contratos["ws_payloads"]) == {"FlowStatus", "PortValue", "MpcState"}
    for schema in contratos["ws_payloads"].values():
        assert schema["type"] == "object"
        assert "properties" in schema


def test_tipos_fixos_tem_nome_direcao_e_tipo():
    contratos = build_contracts()
    for tipo in ("opc_read", "opc_write", "tfs"):
        contrato = contratos["port_contracts"][tipo]
        assert contrato["dynamic"] is False
        assert len(contrato["ports"]) > 0
        for porta in contrato["ports"]:
            assert set(porta) == {"name", "direction", "type"}
            assert porta["direction"] in ("input", "output")


def test_tfs_tem_as_4_portas_fixas_do_spec():
    contratos = build_contracts()
    tfs = contratos["port_contracts"]["tfs"]
    nomes = {porta["name"] for porta in tfs["ports"]}
    assert nomes == {"u1", "u2", "y1", "y2"}


def test_script_e_mpc_sao_regras_dinamicas_com_source():
    # Script: IN1..INn / OUT1..OUTn por config (spec F3 §3.3). MPC: entradas = ids de
    # cvs+constraints+dvs, saídas = ids de mvs (spec F4 §2.2, plano F4a tarefa 1.2) — o bloco
    # MPC ainda não existe em flowgraph.py, então a regra é declarada aqui, não derivada.
    contratos = build_contracts()
    for tipo in ("script", "mpc"):
        contrato = contratos["port_contracts"][tipo]
        assert contrato["dynamic"] is True
        assert isinstance(contrato["source"], str) and contrato["source"]
        direcoes = {regra["direction"] for regra in contrato["rules"]}
        assert direcoes == {"input", "output"}


def test_saida_e_deterministica_entre_execucoes(capsys):
    main()
    primeira = capsys.readouterr().out
    main()
    segunda = capsys.readouterr().out
    assert primeira == segunda
    assert primeira.strip() != ""


def test_main_imprime_json_valido_com_as_duas_secoes(capsys):
    main()
    corpo = json.loads(capsys.readouterr().out)
    assert set(corpo) == {"port_contracts", "ws_payloads"}
    assert corpo == build_contracts()


def test_gen_ts_tem_campo_ts_em_mpcstate_e_mpcprediction():
    # tarefa 1.3 (débito 0.2 da F4): `MpcState.ts`/`MpcPrediction.ts` (bus.py, tarefas
    # 1.1/1.2) precisam sobreviver à regeneração do TS. Trava o `contracts.gen.ts`
    # commitado — não só o JSON intermediário — para pegar regen esquecida.
    texto = GEN_TS_PATH.read_text(encoding="utf-8")
    for nome in ("MpcState", "MpcPrediction"):
        corpo = re.search(rf"export interface {nome} \{{(.*?)\n\}}", texto, re.DOTALL)
        assert corpo, f"interface {nome} não encontrada em {GEN_TS_PATH}"
        assert re.search(r"\bts: string;", corpo.group(1)), (
            f"{nome} sem campo `ts` em {GEN_TS_PATH} — rode npm run generate:contracts"
        )
