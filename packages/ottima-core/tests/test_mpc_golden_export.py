"""`ottima_core.mpc_golden_export` (plano F5b tarefa 6.1, spec F5 §7.6-2/4).

Vetores-golden do bloco MPC: `derive_horizons`, `mpc_state_dimension`, arredondamento
banker's, tetos de variável e o veredito de `_check_mpc_caps/_matrix/_numbers/_horizons`
(mesmo escopo que `mpcLogic.golden.check.ts`, tarefa 6.2, espelha do lado TS). O JSON
commitado em `frontend/src/features/flows/mpc/mpcLogic.golden.json` é a fonte de verdade
compartilhada; divergir de qualquer lado (Python ou TS) vira teste vermelho.
"""

from pathlib import Path

from ottima_core.mpc_golden_export import build_golden, main

_GOLDEN_PATH = (
    Path(__file__).resolve().parents[3] / "frontend/src/features/flows/mpc/mpcLogic.golden.json"
)


def test_saida_e_deterministica_entre_execucoes(capsys):
    main()
    primeira = capsys.readouterr().out
    main()
    segunda = capsys.readouterr().out
    assert primeira == segunda
    assert primeira.strip() != ""


def test_saida_bate_com_o_json_commitado(capsys):
    main()
    saida = capsys.readouterr().out
    commitado = _GOLDEN_PATH.read_text(encoding="utf-8")
    assert saida == commitado, "regenere o golden: uv run python -m ottima_core.mpc_golden_export"


def test_json_tem_as_quatro_secoes_do_escopo():
    golden = build_golden()
    assert set(golden) == {"arredondamento_bankers", "dimensao_estado", "horizontes", "validacao"}


def test_arredondamento_bankers_segue_o_half_even_do_round_do_python():
    casos = {caso["valor"]: caso["esperado"] for caso in build_golden()["arredondamento_bankers"]}
    assert casos[2.5] == 2  # par mais próximo abaixo
    assert casos[3.5] == 4  # par mais próximo acima
    assert casos[0.5] == 0
    assert casos[100.5] == 100


def test_horizontes_bate_com_o_caso_canonico_do_brief():
    casos = {
        (caso["multiplier"], caso["ts_flow"], tuple(caso["tss"])): caso
        for caso in build_golden()["horizontes"]
    }
    caso = casos[(5, 1.0, (600.0,))]
    assert caso["ts_mpc"] == 5.0
    assert caso["np"] == 120
    assert caso["nc"] == 30


def test_validacao_tem_um_caso_aprovado_e_varios_reprovados():
    vereditos = build_golden()["validacao"]
    assert any(caso["esperado"] == {"erros": 0, "avisos": 0} for caso in vereditos)
    reprovados = [
        caso for caso in vereditos if caso["esperado"]["erros"] or caso["esperado"]["avisos"]
    ]
    assert len(reprovados) >= 15  # um por regra de caps/matrix/numbers/horizons + dimensao


def test_validacao_cobre_erro_e_aviso_isolados():
    # Np>60 (aviso) sem nenhum erro junto, e dimensao>120 (aviso) idem — prova que o golden
    # não confunde "reprovado" com "sempre erro": avisos não bloqueiam (spec §2.2-5/7).
    vereditos = {caso["regra"]: caso["esperado"] for caso in build_golden()["validacao"]}
    aviso_only = [v for v in vereditos.values() if v["avisos"] > 0 and v["erros"] == 0]
    assert len(aviso_only) >= 2


def test_regras_de_validacao_sao_unicas():
    nomes = [caso["regra"] for caso in build_golden()["validacao"]]
    assert len(nomes) == len(set(nomes))


def test_nomes_de_variavel_e_pid_batem_verbatim_com_os_campos_do_mpcconfig():
    # `config` de cada caso precisa ser o dump verbatim de `MpcConfig` (mesmos nomes de campo
    # que `frontend/.../graph.ts` usa para `VariaveisMpc`/`ParModeloMpc`) — sem isso o TS não
    # consegue consumir o JSON direto como `variarei.mvs`/`.cvs`/etc.
    caso = next(iter(build_golden()["validacao"]))
    variaveis = caso["config"]["variables"]
    assert set(variaveis) == {"mvs", "cvs", "constraints", "dvs"}
    mv = variaveis["mvs"][0]
    assert set(mv) == {"id", "name", "eu", "limits", "du_max", "initial_value", "pid"}
    assert mv["pid"] is None
