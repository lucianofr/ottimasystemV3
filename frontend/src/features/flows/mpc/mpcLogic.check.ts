import { expect, test } from "@playwright/test";

import type { TagOut } from "../../../lib/api";
import {
  gerarIdVariavel,
  nomeCampoModelo,
  nomeCampoVar,
  parModeloDoFormulario,
  paramsPadraoLinha,
  tagsPorDirecao,
  tsMpcDerivado,
  variavelCvDoFormulario,
  variavelDvDoFormulario,
  variavelMvDoFormulario,
  variavelRestricaoDoFormulario,
} from "./mpcLogic";

test("gerarIdVariavel prefixa por tipo e nunca repete em 1000 gerações", () => {
  expect(gerarIdVariavel("mv")).toMatch(/^mv_[a-z0-9]{4}$/);
  expect(gerarIdVariavel("cv")).toMatch(/^cv_[a-z0-9]{4}$/);
  expect(gerarIdVariavel("co")).toMatch(/^co_[a-z0-9]{4}$/);
  expect(gerarIdVariavel("dv")).toMatch(/^dv_[a-z0-9]{4}$/);

  const ids = new Set(Array.from({ length: 1000 }, () => gerarIdVariavel("mv")));
  expect(ids.size).toBe(1000);
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
