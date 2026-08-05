import { expect, test } from "@playwright/test";

import type { TagOut } from "../../../lib/api";
import type { ParModeloMpc, VariavelCv, VariavelMv, VariavelRestricao, VariaveisMpc } from "../graph";
import {
  arredondarBankers,
  derivarHorizontes,
  dimensaoEstado,
  gerarIdVariavel,
  nomeCampoModelo,
  nomeCampoVar,
  parModeloDoFormulario,
  paramsPadraoLinha,
  rotuloVariavel,
  tagsPorDirecao,
  tsMpcDerivado,
  validarConfigMpc,
  variavelCvDoFormulario,
  variavelDvDoFormulario,
  variavelMvDoFormulario,
  variavelRestricaoDoFormulario,
} from "./mpcLogic";

test("gerarIdVariavel prefixa por tipo e segue o formato <prefixo>_<4 chars base-36>", () => {
  expect(gerarIdVariavel("mv")).toMatch(/^mv_[a-z0-9]{4}$/);
  expect(gerarIdVariavel("cv")).toMatch(/^cv_[a-z0-9]{4}$/);
  expect(gerarIdVariavel("co")).toMatch(/^co_[a-z0-9]{4}$/);
  expect(gerarIdVariavel("dv")).toMatch(/^dv_[a-z0-9]{4}$/);
});

// O sufixo vem de `Math.random()` (default) — testar unicidade por amostragem estatística
// seria flaky (1000 sorteios em 36^4 colidem ~26% das vezes). Em vez disso, o RNG é
// injetável: o teste prova determinismo (mesma entrada -> mesma saída, entradas distintas ->
// saídas distintas), sem depender de estatística.
test("gerarIdVariavel é determinístico dado o RNG injetado", () => {
  const fixo = (): number => 0.123456789;
  expect(gerarIdVariavel("mv", fixo)).toBe(`mv_${fixo().toString(36).slice(2, 6)}`);
  expect(gerarIdVariavel("cv", fixo)).toBe(`cv_${fixo().toString(36).slice(2, 6)}`);
  expect(gerarIdVariavel("mv", () => 0.1)).not.toBe(gerarIdVariavel("mv", () => 0.9));
});

test("Ts_mpc deriva de multiplier × Ts_flow (spec F4 §2.2-5)", () => {
  expect(tsMpcDerivado(5, 2)).toBe(10);
  expect(tsMpcDerivado(1, 0.5)).toBe(0.5);
  expect(tsMpcDerivado(0, 2)).toBe(0);
});

test("nomes de campo casam formulário e id/par, sem colisão entre variáveis distintas", () => {
  expect(nomeCampoVar("mv_x7k2", "limits_min")).toBe("var_mv_x7k2_limits_min");
  expect(nomeCampoVar("mv_x7k2", "limits_min")).not.toBe(nomeCampoVar("mv_9999", "limits_min"));
  expect(nomeCampoModelo("cv_a1b2", "mv_x7k2", "K")).toBe("mdl_cv_a1b2_mv_x7k2_K");
});

function formulario(pares: Record<string, string>): FormData {
  const dados = new FormData();
  for (const [chave, valor] of Object.entries(pares)) dados.set(chave, valor);
  return dados;
}

test("variavelDvDoFormulario lê nome/eu pelo id e cai no padrão quando ausente", () => {
  const atual = { id: "dv_e5f6", name: "Vazão de carga", eu: "m3/h" };
  const dados = formulario({ [nomeCampoVar("dv_e5f6", "name")]: "Nova DV" });
  const nova = variavelDvDoFormulario(atual, dados);
  expect(nova).toEqual({ id: "dv_e5f6", name: "Nova DV", eu: "m3/h" });
});

test("variavelMvDoFormulario sem pid devolve pid null mesmo com campos de pid no formulário", () => {
  const atual = {
    id: "mv_x7k2",
    name: "Vazão de refluxo",
    eu: "m3/h",
    limits: { min: 0, max: 100 },
    du_max: 5,
    initial_value: 0,
    pid: null,
  };
  const dados = formulario({
    [nomeCampoVar("mv_x7k2", "limits_min")]: "1,5",
    [nomeCampoVar("mv_x7k2", "limits_max")]: "90",
    [nomeCampoVar("mv_x7k2", "pid_write_tag_id")]: "12",
  });
  const nova = variavelMvDoFormulario(atual, dados, false);
  expect(nova.limits).toEqual({ min: 1.5, max: 90 });
  expect(nova.pid).toBeNull();
});

test("variavelMvDoFormulario com pid reconstrói os campos obrigatórios do pid", () => {
  const atual = {
    id: "mv_x7k2",
    name: "Vazão de refluxo",
    eu: "m3/h",
    limits: { min: 0, max: 100 },
    du_max: 5,
    initial_value: 0,
    pid: null,
  };
  const dados = formulario({
    [nomeCampoVar("mv_x7k2", "pid_write_tag_id")]: "12",
    [nomeCampoVar("mv_x7k2", "pid_target_mode")]: "rcas",
    [nomeCampoVar("mv_x7k2", "pid_mode_cmd_tag_id")]: "13",
    [nomeCampoVar("mv_x7k2", "pid_readback_tag_id")]: "15",
    [nomeCampoVar("mv_x7k2", "pid_mode_auto")]: "1",
    [nomeCampoVar("mv_x7k2", "pid_mode_target")]: "3",
  });
  const nova = variavelMvDoFormulario(atual, dados, true);
  expect(nova.pid).toEqual({
    write_tag_id: 12,
    target_mode: "rcas",
    mode_cmd_tag_id: 13,
    mode_read_tag_id: null,
    readback_tag_id: 15,
    mode_values: { auto: 1, target: 3 },
  });
});

test("variavelCvDoFormulario e variavelRestricaoDoFormulario preservam kind (decidido na aba)", () => {
  const cv = {
    id: "cv_a1b2",
    name: "Temperatura de topo",
    eu: "C",
    kind: "selfreg" as const,
    tss: 600,
    weight: 1,
    sp_limits: { min: 80, max: 120 },
  };
  const novaCv = variavelCvDoFormulario(
    cv,
    formulario({ [nomeCampoVar("cv_a1b2", "tss")]: "700" }),
  );
  expect(novaCv.kind).toBe("selfreg");
  expect(novaCv.tss).toBe(700);

  const restricao = {
    id: "co_c3d4",
    name: "Nível do vaso",
    eu: "%",
    kind: "integrating" as const,
    tss: 900,
    range: { low: 20, high: 80 },
    priority: 1,
  };
  const novaRestricao = variavelRestricaoDoFormulario(
    restricao,
    formulario({ [nomeCampoVar("co_c3d4", "priority")]: "0,9" }),
  );
  // prioridade é inteiro >= 1 (spec F4 §2.2-4)
  expect(novaRestricao.priority).toBe(1);
});

test("parModeloDoFormulario troca a forma dos params quando o kind da linha muda", () => {
  const atual = { enabled: true, params: { K: 1.2, tau1: 120, tau2: 30, theta: 15 } };
  const dados = formulario({
    [nomeCampoModelo("cv_a1b2", "mv_x7k2", "Ki")]: "0,4",
    [nomeCampoModelo("cv_a1b2", "mv_x7k2", "theta")]: "2",
  });
  const novo = parModeloDoFormulario(atual, "cv_a1b2", "mv_x7k2", "integrating", dados);
  expect(Object.keys(novo.params).sort()).toEqual(["Ki", "theta"]);
  expect(novo.params).toEqual({ Ki: 0.4, theta: 2 });
});

test("paramsPadraoLinha devolve a forma SOPDT/IOPDT conforme kind", () => {
  expect(paramsPadraoLinha("selfreg")).toEqual({ K: 1, tau1: 1, tau2: 0, theta: 0 });
  expect(paramsPadraoLinha("integrating")).toEqual({ Ki: 1, theta: 0 });
});

test("tagsPorDirecao filtra por W (write/mode_cmd) e R (readback/mode_read)", () => {
  const tag = (id: number, direction: "r" | "w"): TagOut => ({
    id,
    connection_id: 1,
    name: `tag${String(id)}`,
    node_id: `ns=2;s=tag${String(id)}`,
    direction,
    data_type: "float",
    eu: "",
    description: "",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  });
  const tags = [tag(1, "w"), tag(2, "r"), tag(3, "w")];
  expect(tagsPorDirecao(tags, "w").map((t) => t.id)).toEqual([1, 3]);
  expect(tagsPorDirecao(tags, "r").map((t) => t.id)).toEqual([2]);
});

// --------------------------------------------------------------------------------------
// Tarefa 4.3 — espelho client-side de `derive_horizons`/`mpc_state_dimension`/validação
// semântica (spec F4 §2.2). Fábricas mínimas por variável — só os campos que cada teste
// precisa variam, o resto usa um default plausível e sem impacto na regra testada.
// --------------------------------------------------------------------------------------

function mv(id: string, parcial: Partial<VariavelMv> = {}): VariavelMv {
  return {
    id,
    name: "",
    eu: "",
    limits: { min: 0, max: 100 },
    du_max: 5,
    initial_value: 0,
    pid: null,
    ...parcial,
  };
}

function cv(id: string, parcial: Partial<VariavelCv> = {}): VariavelCv {
  return {
    id,
    name: "",
    eu: "",
    kind: "selfreg",
    tss: 600,
    weight: 1,
    sp_limits: { min: 0, max: 100 },
    ...parcial,
  };
}

function restricao(id: string, parcial: Partial<VariavelRestricao> = {}): VariavelRestricao {
  return {
    id,
    name: "",
    eu: "",
    kind: "selfreg",
    tss: 600,
    range: { low: 0, high: 100 },
    priority: 1,
    ...parcial,
  };
}

function parSelfreg(paramsParciais: Record<string, number> = {}): ParModeloMpc {
  return { enabled: true, params: { K: 1, tau1: 10, tau2: 0, theta: 0, ...paramsParciais } };
}

function parIntegrating(paramsParciais: Record<string, number> = {}): ParModeloMpc {
  return { enabled: true, params: { Ki: 1, theta: 0, ...paramsParciais } };
}

test("derivarHorizontes: (5, 1.0, [600]) -> ts_mpc 5.0 / Np 120 / Nc 30 (exemplo do brief)", () => {
  expect(derivarHorizontes(5, 1.0, [600])).toEqual({ tsMpc: 5, np: 120, nc: 30 });
});

test("derivarHorizontes: Np<2 quando o multiplicador é grande demais para o TSS", () => {
  expect(derivarHorizontes(1000, 1, [1])?.np).toBe(1);
});

test("derivarHorizontes: Np>120 quando o TSS é grande demais para o multiplicador", () => {
  expect(derivarHorizontes(1, 1, [200])?.np).toBe(200);
});

test("derivarHorizontes: Np=61, no limiar do aviso não-bloqueante (>60)", () => {
  expect(derivarHorizontes(10, 1, [610])?.np).toBe(61);
});

test("derivarHorizontes: sem CV/Restrição (TSS vazio) devolve null em vez de Infinity/NaN", () => {
  expect(derivarHorizontes(1, 1, [])).toBeNull();
});

test("arredondarBankers: arredonda para o par mais próximo, mesma convenção do round() do Python", () => {
  expect(arredondarBankers(0.5)).toBe(0);
  expect(arredondarBankers(1.5)).toBe(2);
  expect(arredondarBankers(2.5)).toBe(2);
  expect(arredondarBankers(3.5)).toBe(4);
  expect(arredondarBankers(0.4)).toBe(0);
  expect(arredondarBankers(0.6)).toBe(1);
});

test("dimensaoEstado: par SOPDT soma 2 estados + atraso banker's + 1 por MV (espelho de mpc_state_dimension)", () => {
  const variaveis: VariaveisMpc = { mvs: [mv("mv_1")], cvs: [cv("cv_1")], constraints: [], dvs: [] };
  const modelos = { cv_1: { mv_1: parSelfreg({ theta: 15 }) } };
  expect(dimensaoEstado(variaveis, modelos, 5)).toBe(1 + 2 + 3); // round(15/5) = 3
});

test("dimensaoEstado: par IOPDT soma 1 estado, ignora par desabilitado e linha órfã", () => {
  const variaveis: VariaveisMpc = {
    mvs: [mv("mv_1")],
    cvs: [],
    constraints: [restricao("co_1", { kind: "integrating" })],
    dvs: [],
  };
  const modelos = {
    co_1: { mv_1: parIntegrating({ theta: 2.5 }), mv_2: { enabled: false, params: {} } },
    linha_removida: { mv_1: parSelfreg({ theta: 999 }) },
  };
  // linha_removida não corresponde a nenhuma CV/Restrição (matriz já podada em
  // `modelosDoFormulario`) e o par mv_2 está desabilitado — nenhum dos dois soma estado.
  expect(dimensaoEstado(variaveis, modelos, 1)).toBe(1 + 1 + 2); // round(2.5) = 2 (par banker's)
});

test("rotuloVariavel: usa o nome quando preenchido, senão cai no id estável", () => {
  expect(rotuloVariavel({ id: "mv_x7k2", name: "Vazão de refluxo" })).toBe("Vazão de refluxo");
  expect(rotuloVariavel({ id: "mv_x7k2", name: "   " })).toBe("mv_x7k2");
});

test("validarConfigMpc: config mínima válida não gera erro nem aviso", () => {
  const variaveis: VariaveisMpc = {
    mvs: [mv("mv_1")],
    cvs: [cv("cv_1", { tss: 600 })],
    constraints: [],
    dvs: [],
  };
  const modelos = { cv_1: { mv_1: parSelfreg({ theta: 5 }) } };
  const { erros, avisos } = validarConfigMpc(variaveis, modelos, 10, 1);
  expect(erros).toEqual([]);
  expect(avisos).toEqual([]);
});

test("validarConfigMpc: teto de MVs (spec §2.2-2) vira erro bloqueante quando 0 MVs", () => {
  const variaveis: VariaveisMpc = { mvs: [], cvs: [cv("cv_1")], constraints: [], dvs: [] };
  const { erros } = validarConfigMpc(variaveis, {}, 1, 1);
  expect(erros.some((erro) => erro.includes("MV(s)"))).toBe(true);
});

test("validarConfigMpc: MV sem nenhum par habilitado na matriz vira erro (spec §2.2-3)", () => {
  const variaveis: VariaveisMpc = { mvs: [mv("mv_1")], cvs: [cv("cv_1")], constraints: [], dvs: [] };
  const modelos = { cv_1: { mv_1: { enabled: false, params: {} } } };
  const { erros } = validarConfigMpc(variaveis, modelos, 1, 1);
  expect(
    erros.some((erro) => erro.includes("mv_1") && erro.includes("não tem nenhum par habilitado")),
  ).toBe(true);
});

test("validarConfigMpc: pisos numéricos de weight/du_max/tss/faixas bloqueiam (harmonização da revisão 4.2)", () => {
  const variaveis: VariaveisMpc = {
    mvs: [mv("mv_1", { limits: { min: 10, max: 5 }, du_max: 0 })],
    cvs: [cv("cv_1", { tss: 0, weight: 0, sp_limits: { min: 10, max: 5 } })],
    constraints: [restricao("co_1", { tss: 0, range: { low: 10, high: 5 } })],
    dvs: [],
  };
  const { erros } = validarConfigMpc(variaveis, {}, 1, 1);
  expect(erros.some((e) => e.includes("limite mínimo menor que o máximo"))).toBe(true);
  expect(erros.some((e) => e.includes("Δu máx."))).toBe(true);
  expect(erros.some((e) => e.includes("CV") && e.includes("TSS maior que zero"))).toBe(true);
  expect(erros.some((e) => e.includes("SP mínimo menor que o máximo"))).toBe(true);
  expect(erros.some((e) => e.includes("peso maior que zero"))).toBe(true);
  expect(erros.some((e) => e.includes("Restrição") && e.includes("TSS maior que zero"))).toBe(true);
  expect(erros.some((e) => e.includes("faixa mínima menor que a máxima"))).toBe(true);
});

test("validarConfigMpc: Np<2 e Np>120 usam as strings verbatim do 422 do servidor (spec §2.2-5)", () => {
  const baseVariaveis = (tss: number): VariaveisMpc => ({
    mvs: [mv("mv_1")],
    cvs: [cv("cv_1", { tss })],
    constraints: [],
    dvs: [],
  });
  const modelos = { cv_1: { mv_1: parSelfreg({ theta: 0 }) } };

  const baixo = validarConfigMpc(baseVariaveis(1), modelos, 1000, 1);
  expect(baixo.erros).toContain("multiplicador grande demais para o TSS");

  const alto = validarConfigMpc(baseVariaveis(200), modelos, 1, 1);
  expect(alto.erros).toContain("aumente o multiplicador ou reduza o TSS");
});

test("validarConfigMpc: Np=61 é aviso não-bloqueante (>60, referência de carga RNF-02)", () => {
  const variaveis: VariaveisMpc = {
    mvs: [mv("mv_1")],
    cvs: [cv("cv_1", { tss: 610 })],
    constraints: [],
    dvs: [],
  };
  const modelos = { cv_1: { mv_1: parSelfreg({ theta: 0 }) } };
  const { erros, avisos } = validarConfigMpc(variaveis, modelos, 10, 1);
  expect(erros).toEqual([]);
  expect(avisos.some((aviso) => aviso.startsWith("Np = 61"))).toBe(true);
});

test("validarConfigMpc: dimensão de estados > 120 é aviso, pulado quando um par habilitado tem params inválidos (RF-608, espelha matrix_intact)", () => {
  const variaveis: VariaveisMpc = {
    mvs: [mv("mv_1")],
    cvs: [cv("cv_1", { tss: 100 })],
    constraints: [],
    dvs: [],
  };
  const modelosIntactos = { cv_1: { mv_1: parSelfreg({ theta: 200 }) } };
  const intacta = validarConfigMpc(variaveis, modelosIntactos, 1, 1);
  expect(intacta.erros).toEqual([]);
  expect(intacta.avisos.some((aviso) => aviso.includes("Dimensão de estados agregada"))).toBe(true);

  // K=0 é inválido para selfreg (spec §2.2-3) — é isso, e só isso, que o servidor
  // (`_valid_pair_params`) usa para derrubar `matrix_intact`.
  const modelosQuebrados = {
    cv_1: { mv_1: { enabled: true, params: { K: 0, tau1: 10, tau2: 0, theta: 200 } } },
  };
  const quebrada = validarConfigMpc(variaveis, modelosQuebrados, 1, 1);
  expect(quebrada.erros.some((erro) => erro.includes("parâmetros inválidos"))).toBe(true);
  expect(quebrada.avisos.some((aviso) => aviso.includes("Dimensão de estados agregada"))).toBe(
    false,
  );
});

test("validarConfigMpc: MV sem nenhum par habilitado é erro, mas não suprime o aviso de dimensão (matrix_intact do servidor não olha isso)", () => {
  const variaveis: VariaveisMpc = {
    mvs: [mv("mv_1"), mv("mv_2")],
    cvs: [cv("cv_1", { tss: 100 })],
    constraints: [],
    dvs: [],
  };
  // mv_2 não tem nenhum par na matriz — órfã, mas o par cv_1/mv_1 é válido e íntegro.
  const modelos = { cv_1: { mv_1: parSelfreg({ theta: 200 }) } };
  const { erros, avisos } = validarConfigMpc(variaveis, modelos, 1, 1);
  expect(erros.some((erro) => erro.includes("mv_2"))).toBe(true);
  expect(avisos.some((aviso) => aviso.includes("Dimensão de estados agregada"))).toBe(true);
});

// --------------------------------------------------------------------------------------
// Fix round 1 (revisão 4.3) — Critical: perda silenciosa de dados ao trocar de aba antes de
// Aplicar. `TabModels`/`TabVariables` têm campos não-controlados (só `name=`/`defaultValue=`,
// lidos apenas do `FormData` do formulário no submit); como cada aba é desmontada ao trocar
// (`{aba === "x" && (<TabX/>)}`), digitar em uma aba e ir para outra sem passar pelo Aplicar
// apagava a edição do DOM antes de qualquer leitura. Correção em `MpcModal.tsx`: a troca de
// aba (`mudarAba`) agora lê o `FormData` da aba que está SENDO deixada e o reconstrói no
// estado (`variaveisDoFormulario`/`modelosDoFormulario` — as mesmas funções do Aplicar) antes
// de desmontar. Os dois testes abaixo provam, no nível de lógica pura (sem infra de
// component-rendering), que a reconstrução preserva o valor já commitado no estado quando o
// `FormData` da aba atualmente montada não tem mais aquele campo — é essa propriedade que
// torna `mudarAba` suficiente para fechar a classe inteira do bug.
// --------------------------------------------------------------------------------------

test("cenário B-F4-03 passos 9-11: params digitados na aba Modelos sobrevivem à troca para o Resumo antes do Aplicar", () => {
  const linha = "cv_1";
  const coluna = "mv_1";

  // Passo 9 — aba Modelos montada: usuário habilita o par e digita K/tau1/tau2/theta.
  const camposModelos = formulario({
    [nomeCampoModelo(linha, coluna, "K")]: "2,5",
    [nomeCampoModelo(linha, coluna, "tau1")]: "120",
    [nomeCampoModelo(linha, coluna, "tau2")]: "30",
    [nomeCampoModelo(linha, coluna, "theta")]: "15",
  });
  const parHabilitado: ParModeloMpc = { enabled: true, params: {} };
  const sincronizadoAoTrocarDeAba = parModeloDoFormulario(
    parHabilitado,
    linha,
    coluna,
    "selfreg",
    camposModelos,
  );
  expect(sincronizadoAoTrocarDeAba.params).toEqual({ K: 2.5, tau1: 120, tau2: 30, theta: 15 });

  // Passos 10-11 — aba Resumo montada (nenhum campo `mdl_cv_1_mv_1_*` no FormData): o Aplicar
  // reconstrói de novo, agora a partir do estado já sincronizado no passo anterior. Sem o fix
  // (sem a sincronização na troca de aba), `atual` aqui seria `parHabilitado` (`params: {}`)
  // e o resultado cairia em `paramsPadraoLinha("selfreg")` — os defaults, não o digitado.
  const camposResumo = formulario({});
  const resultadoNoAplicar = parModeloDoFormulario(
    sincronizadoAoTrocarDeAba,
    linha,
    coluna,
    "selfreg",
    camposResumo,
  );
  expect(resultadoNoAplicar.params).toEqual({ K: 2.5, tau1: 120, tau2: 30, theta: 15 });
  expect(resultadoNoAplicar.params).not.toEqual(paramsPadraoLinha("selfreg"));
});

test("mesmo mecanismo em TabVariables: limites/Δu digitados numa MV sobrevivem à troca de aba antes do Aplicar", () => {
  const mvDigitada: VariavelMv = {
    id: "mv_1",
    name: "Vazão de refluxo",
    eu: "m3/h",
    limits: { min: 5, max: 95 },
    du_max: 3.5,
    initial_value: 10,
    pid: null,
  };
  // Aba Resumo montada (nenhum campo `var_mv_1_*` no FormData) — a reconstrução deve
  // preservar o valor já sincronizado no estado, não cair nos campos padrão.
  const camposResumo = formulario({});
  const resultado = variavelMvDoFormulario(mvDigitada, camposResumo, false);
  expect(resultado).toEqual(mvDigitada);
});
