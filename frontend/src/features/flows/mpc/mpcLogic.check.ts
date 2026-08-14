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
  pidAoAlternar,
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
  const atual = { id: "dv_e5f6", name: "Vazão de carga", eu: "m3/h", zero: 0, span: 100, range: null, operating_point: 0 };
  const dados = formulario({ [nomeCampoVar("dv_e5f6", "name")]: "Nova DV" });
  const nova = variavelDvDoFormulario(atual, dados);
  expect(nova).toEqual({
    id: "dv_e5f6",
    name: "Nova DV",
    eu: "m3/h",
    zero: 0,
    span: 100,
    range: null,
    operating_point: 0,
  });
});

test("variavelDvDoFormulario: os dois campos de faixa preenchidos montam o range (spec §4.2-5)", () => {
  const atual = { id: "dv_e5f6", name: "Vazão de carga", eu: "m3/h", zero: 0, span: 100, range: null, operating_point: 0 };
  const dados = formulario({
    [nomeCampoVar("dv_e5f6", "range_low")]: "0",
    [nomeCampoVar("dv_e5f6", "range_high")]: "100",
  });
  expect(variavelDvDoFormulario(atual, dados).range).toEqual({ low: 0, high: 100 });
});

test("variavelDvDoFormulario: os dois campos de faixa vazios (ou ausentes) devolvem range null", () => {
  const comFaixa = { id: "dv_e5f6", name: "", eu: "", zero: 0, span: 100, range: { low: 0, high: 100 }, operating_point: 0 };
  const dados = formulario({
    [nomeCampoVar("dv_e5f6", "range_low")]: "  ",
    [nomeCampoVar("dv_e5f6", "range_high")]: "",
  });
  expect(variavelDvDoFormulario(comFaixa, dados).range).toBeNull();
});

test("variavelDvDoFormulario: só um campo de faixa preenchido não deixa a faixa pela metade — o vazio cai no valor anterior (decisão desta tarefa, servidor recusaria faixa parcial)", () => {
  const semFaixaAinda = { id: "dv_novo", name: "", eu: "", zero: 0, span: 100, range: null, operating_point: 0 };
  const soLow = variavelDvDoFormulario(
    semFaixaAinda,
    formulario({ [nomeCampoVar("dv_novo", "range_low")]: "10" }),
  );
  expect(soLow.range).toEqual({ low: 10, high: 0 }); // sem faixa anterior, o vazio cai em 0

  const comFaixaAnterior = { id: "dv_e5f6", name: "", eu: "", zero: 0, span: 100, range: { low: 5, high: 50 }, operating_point: 0 };
  const soHigh = variavelDvDoFormulario(
    comFaixaAnterior,
    formulario({ [nomeCampoVar("dv_e5f6", "range_high")]: "80" }),
  );
  expect(soHigh.range).toEqual({ low: 5, high: 80 }); // low vazio preserva o low anterior
});

test("variavelDvDoFormulario: operating_point faz round-trip pelo formulário (TD-003, ponto de linearização)", () => {
  const atual = { id: "dv_e5f6", name: "", eu: "", zero: 0, span: 100, range: null, operating_point: 0 };
  const dados = formulario({ [nomeCampoVar("dv_e5f6", "operating_point")]: "12,3" });
  expect(variavelDvDoFormulario(atual, dados).operating_point).toBe(12.3);
});

test("variavelMvDoFormulario sem pid devolve pid null mesmo com campos de pid no formulário", () => {
  const atual = {
    id: "mv_x7k2",
    name: "Vazão de refluxo",
    eu: "m3/h",
    description: "",
    zero: 0,
    span: 100,
    limits: { min: 0, max: 100 },
    max_rate: 5,
    du_min: 0,
    move_weight: 1,
    initial_value: 0,
    operating_point: 0,
    readback_tag_id: null,
    pid: null,
    objective: "none" as const,
    psv: null,
    fail_action: "no_action" as const,
    local_shed_mode: null,
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
    description: "",
    zero: 0,
    span: 100,
    limits: { min: 0, max: 100 },
    max_rate: 5,
    du_min: 0,
    move_weight: 1,
    initial_value: 0,
    operating_point: 0,
    readback_tag_id: null,
    pid: null,
    objective: "none" as const,
    psv: null,
    fail_action: "no_action" as const,
    local_shed_mode: null,
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

test("variavelMvDoFormulario: operating_point e readback_tag_id da MV direta fazem round-trip pelo formulário (TD-003)", () => {
  const atual = {
    id: "mv_x7k2",
    name: "Vazão de refluxo",
    eu: "m3/h",
    description: "",
    zero: 0,
    span: 100,
    limits: { min: 0, max: 100 },
    max_rate: 5,
    du_min: 0,
    move_weight: 1,
    initial_value: 0,
    operating_point: 0,
    readback_tag_id: null,
    pid: null,
    objective: "none" as const,
    psv: null,
    fail_action: "no_action" as const,
    local_shed_mode: null,
  };
  const dados = formulario({
    [nomeCampoVar("mv_x7k2", "operating_point")]: "42,5",
    [nomeCampoVar("mv_x7k2", "readback_tag_id")]: "7",
  });
  const nova = variavelMvDoFormulario(atual, dados, false);
  expect(nova.operating_point).toBe(42.5);
  expect(nova.readback_tag_id).toBe(7);
});

test("variavelMvDoFormulario: readback_tag_id vazio cai no valor anterior, mesma forma do pid_mode_read_tag_id (MV direta sem tag continua null)", () => {
  const comReadback = {
    id: "mv_x7k2",
    name: "",
    eu: "",
    description: "",
    zero: 0,
    span: 100,
    limits: { min: 0, max: 100 },
    max_rate: 5,
    du_min: 0,
    move_weight: 1,
    initial_value: 0,
    operating_point: 0,
    readback_tag_id: 9,
    pid: null,
    objective: "none" as const,
    psv: null,
    fail_action: "no_action" as const,
    local_shed_mode: null,
  };
  const semCampo = variavelMvDoFormulario(comReadback, formulario({}), false);
  expect(semCampo.readback_tag_id).toBe(9); // campo ausente do FormData preserva o anterior

  const semReadbackAinda = { ...comReadback, readback_tag_id: null };
  const vazio = variavelMvDoFormulario(
    semReadbackAinda,
    formulario({ [nomeCampoVar("mv_x7k2", "readback_tag_id")]: "" }),
    false,
  );
  expect(vazio.readback_tag_id).toBeNull();
});

test("variavelCvDoFormulario e variavelRestricaoDoFormulario preservam kind (decidido na aba)", () => {
  const cv = {
    id: "cv_a1b2",
    name: "Temperatura de topo",
    eu: "C",
    description: "",
    zero: 0,
    span: 100,
    kind: "selfreg" as const,
    tss: 600,
    weight: 1,
    sp_limits: { min: 80, max: 120 },
    priority: 1,
    objective: "none" as const,
    traj_tau_s: 0,
    track_sp: true,
    fail_action: "no_action" as const,
    fail_timeout_s: 60,
    sp_range_pct: null,
    remote_sp_tag_id: null,
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
    description: "",
    zero: 0,
    span: 100,
    kind: "integrating" as const,
    tss: 900,
    range: { low: 20, high: 80 },
    priority: 1,
    objective: "none" as const,
    fail_action: "no_action" as const,
    fail_timeout_s: 60,
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
    description: "",
    zero: 0,
    span: 100,
    limits: { min: 0, max: 100 },
    max_rate: 5,
    du_min: 0,
    move_weight: 1,
    initial_value: 0,
    operating_point: 0,
    readback_tag_id: null,
    pid: null,
    objective: "none",
    psv: null,
    fail_action: "no_action",
    local_shed_mode: null,
    ...parcial,
  };
}

function cv(id: string, parcial: Partial<VariavelCv> = {}): VariavelCv {
  return {
    id,
    name: "",
    eu: "",
    description: "",
    zero: 0,
    span: 100,
    kind: "selfreg",
    tss: 600,
    weight: 1,
    sp_limits: { min: 0, max: 100 },
    priority: 1,
    objective: "none",
    traj_tau_s: 0,
    track_sp: true,
    fail_action: "no_action",
    fail_timeout_s: 60,
    sp_range_pct: null,
    remote_sp_tag_id: null,
    ...parcial,
  };
}

function restricao(id: string, parcial: Partial<VariavelRestricao> = {}): VariavelRestricao {
  return {
    id,
    name: "",
    eu: "",
    description: "",
    zero: 0,
    span: 100,
    kind: "selfreg",
    tss: 600,
    range: { low: 0, high: 100 },
    priority: 1,
    objective: "none",
    fail_action: "no_action",
    fail_timeout_s: 60,
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

test("validarConfigMpc: pisos numéricos de weight/max_rate/tss/faixas bloqueiam (harmonização da revisão 4.2)", () => {
  const variaveis: VariaveisMpc = {
    mvs: [mv("mv_1", { limits: { min: 10, max: 5 }, max_rate: 0 })],
    cvs: [cv("cv_1", { tss: 0, weight: 0, sp_limits: { min: 10, max: 5 } })],
    constraints: [restricao("co_1", { tss: 0, range: { low: 10, high: 5 } })],
    dvs: [],
  };
  const { erros } = validarConfigMpc(variaveis, {}, 1, 1);
  expect(erros.some((e) => e.includes("limite mínimo menor que o máximo"))).toBe(true);
  expect(erros.some((e) => e.includes("taxa máxima maior que zero"))).toBe(true);
  expect(erros.some((e) => e.includes("CV") && e.includes("TSS maior que zero"))).toBe(true);
  expect(erros.some((e) => e.includes("SP mínimo menor que o máximo"))).toBe(true);
  expect(erros.some((e) => e.includes("peso maior que zero"))).toBe(true);
  expect(erros.some((e) => e.includes("Restrição") && e.includes("TSS maior que zero"))).toBe(true);
  expect(erros.some((e) => e.includes("faixa mínima menor que a máxima"))).toBe(true);
});

test("validarConfigMpc: du_min negativo e move_weight não positivo bloqueiam (TD-007)", () => {
  // `du_min <= max_rate x Ts_mpc` NÃO é mais espelho: depende do Ts_mpc e virou erro de
  // build do bloco no servidor (ValueError pt-BR) — fora do alcance desta validação.
  const variaveis: VariaveisMpc = {
    mvs: [mv("mv_neg", { du_min: -1 }), mv("mv_peso", { move_weight: 0 })],
    cvs: [cv("cv_1")],
    constraints: [],
    dvs: [],
  };
  const { erros } = validarConfigMpc(variaveis, {}, 1, 1);
  expect(erros.some((e) => e.includes("Δu mínimo maior ou igual a zero"))).toBe(true);
  expect(erros.some((e) => e.includes("peso de movimento maior que zero"))).toBe(true);
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
    description: "",
    zero: 0,
    span: 100,
    limits: { min: 5, max: 95 },
    max_rate: 3.5,
    du_min: 0,
    move_weight: 1,
    initial_value: 10,
    operating_point: 0,
    readback_tag_id: null,
    pid: null,
    objective: "none" as const,
    psv: null,
    fail_action: "no_action" as const,
    local_shed_mode: null,
  };
  // Aba Resumo montada (nenhum campo `var_mv_1_*` no FormData) — a reconstrução deve
  // preservar o valor já sincronizado no estado, não cair nos campos padrão.
  const camposResumo = formulario({});
  const resultado = variavelMvDoFormulario(mvDigitada, camposResumo, false);
  expect(resultado).toEqual(mvDigitada);
});

// --------------------------------------------------------------------------------------
// Fix final (revisão de branch completo, Important) — mesma classe de bug da revisão 4.3
// (perda silenciosa por desmontagem sem captura prévia), aqui via dois checkboxes que
// desmontam campos-folha DENTRO da mesma aba (sem troca de aba): "MV com PID" (TabVariables)
// e "Habilitado" da matriz (TabModels). `pidAoAlternar` é o helper puro extraído para o
// primeiro caso (o segundo reusa o `parModeloDoFormulario` já testado acima). Os testes
// abaixo provam, em lógica pura, que desmarcar+marcar de novo sem trocar de aba preserva o
// que foi digitado — a mesma propriedade que os testes de troca de aba provam para o
// mecanismo do `mudarAba`.
// --------------------------------------------------------------------------------------

test("pidAoAlternar: desligar sempre devolve null, mesmo com um pid conhecido em cache", () => {
  const pidConhecido: VariavelMv["pid"] = {
    write_tag_id: 5,
    target_mode: "cas",
    mode_cmd_tag_id: 6,
    mode_read_tag_id: 7,
    readback_tag_id: 8,
    mode_values: { auto: 1, target: 2 },
  };
  expect(pidAoAlternar(false, pidConhecido)).toBeNull();
});

test("pidAoAlternar: ligar pela primeira vez (sem cache) cai nos defaults hard-coded", () => {
  expect(pidAoAlternar(true, null)).toEqual({
    write_tag_id: 0,
    target_mode: "rcas",
    mode_cmd_tag_id: 0,
    mode_read_tag_id: null,
    readback_tag_id: 0,
    mode_values: { auto: 0, target: 1 },
  });
});

test("pidAoAlternar: ligar de novo restaura o último pid capturado, não os defaults hard-coded", () => {
  const pidDigitado: VariavelMv["pid"] = {
    write_tag_id: 12,
    target_mode: "cas",
    mode_cmd_tag_id: 13,
    mode_read_tag_id: 14,
    readback_tag_id: 15,
    mode_values: { auto: 3, target: 4 },
  };
  expect(pidAoAlternar(true, pidDigitado)).toEqual(pidDigitado);
  expect(pidAoAlternar(true, pidDigitado)).not.toEqual({
    write_tag_id: 0,
    target_mode: "rcas",
    mode_cmd_tag_id: 0,
    mode_read_tag_id: null,
    readback_tag_id: 0,
    mode_values: { auto: 0, target: 1 },
  });
});

test("cenário do checkbox 'com PID': campos digitados sobrevivem a desmarcar+marcar de novo sem trocar de aba", () => {
  const mvComPid: VariavelMv = {
    id: "mv_1",
    name: "Vazão",
    eu: "m3/h",
    description: "",
    zero: 0,
    span: 100,
    limits: { min: 0, max: 100 },
    max_rate: 1,
    du_min: 0,
    move_weight: 1,
    initial_value: 0,
    operating_point: 0,
    readback_tag_id: null,
    pid: {
      write_tag_id: 0,
      target_mode: "rcas",
      mode_cmd_tag_id: 0,
      mode_read_tag_id: null,
      readback_tag_id: 0,
      mode_values: { auto: 0, target: 1 },
    },
    objective: "none" as const,
    psv: null,
    fail_action: "no_action" as const,
    local_shed_mode: null,
  };
  // Passo 1 — checkbox ligado, engenheiro digita os campos do pid, sem trocar de aba.
  const camposDigitados = formulario({
    [nomeCampoVar("mv_1", "pid_write_tag_id")]: "42",
    [nomeCampoVar("mv_1", "pid_readback_tag_id")]: "43",
    [nomeCampoVar("mv_1", "pid_mode_cmd_tag_id")]: "44",
  });
  // Passo 2 — desmarca: o handler captura o DOM (ainda montado) antes de desmontar.
  const capturado = variavelMvDoFormulario(mvComPid, camposDigitados, true).pid;
  expect(capturado).not.toBeNull();
  // Passo 3 — remarca: sem o fix cairia nos defaults hard-coded; com o fix restaura o
  // capturado no passo 2.
  const restaurado = pidAoAlternar(true, capturado);
  expect(restaurado).toEqual(capturado);
  expect(restaurado?.write_tag_id).toBe(42);
  expect(restaurado?.readback_tag_id).toBe(43);
  expect(restaurado?.mode_cmd_tag_id).toBe(44);
});

test("cenário do checkbox 'Habilitado' na matriz: params digitados sobrevivem a desmarcar+marcar de novo sem trocar de aba", () => {
  const linha = "cv_1";
  const coluna = "mv_1";
  const parAntesDoUncheck: ParModeloMpc = { enabled: true, params: {} };
  const camposDigitados = formulario({
    [nomeCampoModelo(linha, coluna, "K")]: "3",
    [nomeCampoModelo(linha, coluna, "tau1")]: "40",
    [nomeCampoModelo(linha, coluna, "tau2")]: "5",
    [nomeCampoModelo(linha, coluna, "theta")]: "2",
  });
  // Uncheck: o handler captura o DOM (ainda montado) antes de desmontar os campos.
  const capturado = parModeloDoFormulario(parAntesDoUncheck, linha, coluna, "selfreg", camposDigitados);
  const parAposUncheck: ParModeloMpc = { enabled: false, params: capturado.params };
  expect(parAposUncheck.params).toEqual({ K: 3, tau1: 40, tau2: 5, theta: 2 });
  // Recheck: campos desmontados (FormData vazio) — sem o fix `parAntesDoUncheck.params`
  // (`{}`) teria sido usado como `atual`, caindo em `paramsPadraoLinha`; com o fix o `atual`
  // já é `parAposUncheck`, que carrega o digitado.
  const restaurado = parModeloDoFormulario(parAposUncheck, linha, coluna, "selfreg", formulario({}));
  expect(restaurado.params).toEqual({ K: 3, tau1: 40, tau2: 5, theta: 2 });
  expect(restaurado.params).not.toEqual(paramsPadraoLinha("selfreg"));
});

// --------------------------------------------------------------------------------------
// Função objetivo por variável (ADR-027 §9 estendido) — formulário + espelho das 3 regras
// de `mpc_config.py` (`_valida_objetivo_selfreg`, `_valida_psv`, `_valida_equalize`), com
// as MESMAS mensagens pt-BR: o servidor devolve 422 com elas se o espelho deixar passar.
// --------------------------------------------------------------------------------------

test("variavelMvDoFormulario: objective é estado controlado e psv só existe com objective psv", () => {
  const comPsv = mv("mv_1", { objective: "psv", psv: 30 });
  const dados = formulario({ [nomeCampoVar("mv_1", "psv")]: "42,5" });
  const nova = variavelMvDoFormulario(comPsv, dados, false);
  expect(nova.objective).toBe("psv");
  expect(nova.psv).toBe(42.5);

  // Fora do PSV o campo não existe no DOM — qualquer resquício volta a null (o servidor
  // rejeita "psv só vale com objetivo PSV").
  const maximizando = mv("mv_1", { objective: "maximize", psv: null });
  const deVolta = variavelMvDoFormulario(maximizando, formulario({}), false);
  expect(deVolta.objective).toBe("maximize");
  expect(deVolta.psv).toBeNull();
});

test("validarConfigMpc: equalize com uma MV só bloqueia com a mensagem verbatim do servidor", () => {
  const variaveis: VariaveisMpc = {
    mvs: [mv("mv_1", { objective: "equalize" })],
    cvs: [cv("cv_1")],
    constraints: [],
    dvs: [],
  };
  const { erros } = validarConfigMpc(variaveis, {}, 1, 1);
  expect(erros).toContain("Equalize exige pelo menos duas MVs com esse objetivo");
});

test("validarConfigMpc: equalize com duas MVs passa", () => {
  const variaveis: VariaveisMpc = {
    mvs: [mv("mv_1", { objective: "equalize" }), mv("mv_2", { objective: "equalize" })],
    cvs: [cv("cv_1")],
    constraints: [],
    dvs: [],
  };
  const { erros } = validarConfigMpc(variaveis, {}, 1, 1);
  expect(erros.some((e) => e.includes("Equalize"))).toBe(false);
});

test("validarConfigMpc: psv ausente ou fora dos limites bloqueia; dentro passa", () => {
  const semValor: VariaveisMpc = {
    mvs: [mv("mv_1", { objective: "psv", psv: null })],
    cvs: [cv("cv_1")],
    constraints: [],
    dvs: [],
  };
  expect(validarConfigMpc(semValor, {}, 1, 1).erros).toContain(
    "PSV exige um valor preferido dentro dos limites da MV",
  );

  const fora: VariaveisMpc = {
    mvs: [mv("mv_1", { objective: "psv", psv: 150 })],
    cvs: [cv("cv_1")],
    constraints: [],
    dvs: [],
  };
  expect(validarConfigMpc(fora, {}, 1, 1).erros).toContain(
    "PSV exige um valor preferido dentro dos limites da MV",
  );

  const dentro: VariaveisMpc = {
    mvs: [mv("mv_1", { objective: "psv", psv: 42 })],
    cvs: [cv("cv_1")],
    constraints: [],
    dvs: [],
  };
  expect(
    validarConfigMpc(dentro, {}, 1, 1).erros.some((e) => e.includes("PSV")),
  ).toBe(false);
});

test("validarConfigMpc: psv preenchido com objective diferente de psv bloqueia", () => {
  const variaveis: VariaveisMpc = {
    mvs: [mv("mv_1", { objective: "maximize", psv: 50 })],
    cvs: [cv("cv_1")],
    constraints: [],
    dvs: [],
  };
  expect(validarConfigMpc(variaveis, {}, 1, 1).erros).toContain(
    "psv só vale com objetivo PSV",
  );
});

test("validarConfigMpc: objetivo em linha integradora bloqueia (CV e Restrição)", () => {
  const variaveis: VariaveisMpc = {
    mvs: [mv("mv_1")],
    cvs: [cv("cv_1", { kind: "integrating", objective: "maximize" })],
    constraints: [restricao("co_1", { kind: "integrating", objective: "minimize" })],
    dvs: [],
  };
  const { erros } = validarConfigMpc(variaveis, {}, 1, 1);
  const ocorrencias = erros.filter(
    (e) => e === "Objetivo econômico exige linha autorregulável (selfreg)",
  );
  expect(ocorrencias).toHaveLength(2);
});
