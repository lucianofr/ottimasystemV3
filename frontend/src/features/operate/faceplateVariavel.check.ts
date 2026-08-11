import { expect, test } from "@playwright/test";

import { faixaDaEscala, type FaceplateVariavelProps, type VariavelTipo } from "./FaceplateVariavel";
import { gradeDeVariaveis } from "./gradeVariaveis";
import type { MpcNodeOut } from "./useMpcs";

/**
 * `faixaDaEscala` — tarefa 5.4 do plano F6b-superficies (spec F6 §4.2/§6.5; RF-702; decisão
 * A-11). DV ganha barra vertical quando `definicao.range` vem preenchido de `GET
 * /api/operate/mpcs` (F6a tarefa 4.2), na mesma convenção visual de MV/CV/Restrição (DESIGN
 * §Shapes — "manter barras verticais PV/SP/OUT em todo faceplate de variável"). Sem `range`, ou
 * com `range` degenerado (`low >= high`, não-finito), a DV segue sem barra: o backend garante
 * `low < high` finito para Restrição (`validate.py:_less_than`) mas não cobre `DvVar.range`
 * (`_check_mpc_numbers` não varre `dvs`) — a guarda fica no cliente.
 */

function props(
  tipo: VariavelTipo,
  definicao: Partial<FaceplateVariavelProps["definicao"]> = {},
): FaceplateVariavelProps {
  return {
    tipo,
    definicao: { id: "x1", name: "X1", eu: "°C", ...definicao },
    valor: { v: 10 },
    modos: { local_remote: "local", man_auto: "man" },
    flowId: 1,
    blockId: "mpc1",
    tsMpcSegundos: 2,
  };
}

test("DV com range válido devolve a faixa normalizada min/max", () => {
  const faixa = faixaDaEscala(props("dv", { range: { low: 0, high: 100 } }));
  expect(faixa).toEqual({ min: 0, max: 100 });
});

test("DV sem range (campo ausente) devolve null", () => {
  expect(faixaDaEscala(props("dv"))).toBeNull();
});

test("DV com range null devolve null", () => {
  expect(faixaDaEscala(props("dv", { range: null }))).toBeNull();
});

test("DV com low > high (range invertido) devolve null", () => {
  expect(faixaDaEscala(props("dv", { range: { low: 100, high: 0 } }))).toBeNull();
});

test("DV com low === high (largura zero) devolve null", () => {
  expect(faixaDaEscala(props("dv", { range: { low: 50, high: 50 } }))).toBeNull();
});

test("DV com low não finito (NaN) devolve null", () => {
  expect(faixaDaEscala(props("dv", { range: { low: Number.NaN, high: 100 } }))).toBeNull();
});

test("DV com high não finito (Infinity) devolve null", () => {
  expect(faixaDaEscala(props("dv", { range: { low: 0, high: Number.POSITIVE_INFINITY } }))).toBeNull();
});

// Não-regressão: MV/CV/Restrição continuam se comportando como antes desta tarefa.
test("MV inalterado: devolve limits, ignora range mesmo se presente", () => {
  const faixa = faixaDaEscala(props("mv", { limits: { min: -10, max: 10 }, range: { low: 999, high: -999 } }));
  expect(faixa).toEqual({ min: -10, max: 10 });
});

test("MV sem limits devolve null", () => {
  expect(faixaDaEscala(props("mv"))).toBeNull();
});

test("CV inalterado: devolve sp_limits, ignora range mesmo se presente", () => {
  const faixa = faixaDaEscala(props("cv", { sp_limits: { min: 0, max: 200 } }));
  expect(faixa).toEqual({ min: 0, max: 200 });
});

test("CV sem sp_limits devolve null", () => {
  expect(faixaDaEscala(props("cv"))).toBeNull();
});

test("Restrição com range válido devolve a faixa normalizada (comportamento preexistente)", () => {
  const faixa = faixaDaEscala(props("constraint", { range: { low: 5, high: 15 } }));
  expect(faixa).toEqual({ min: 5, max: 15 });
});

test("Restrição sem range devolve null (comportamento preexistente)", () => {
  expect(faixaDaEscala(props("constraint"))).toBeNull();
});

test("Restrição com range degenerado (low === high) também devolve null (mesma guarda da DV)", () => {
  expect(faixaDaEscala(props("constraint", { range: { low: 5, high: 5 } }))).toBeNull();
});

/**
 * Regressão do gate L3 (cenário B-F6-10 passo 5): `faixaDaEscala` já sabia ler `range` da DV,
 * mas `gradeDeVariaveis` fixava `range: null` ao montar os props — a faixa publicada por
 * `GET /api/operate/mpcs` (F6a tarefa 4.2) morria antes de chegar à função, e a DV nunca
 * ganhava barra na tela por mais correta que estivesse a config. O teste puro acima não pega
 * isso: ele alimenta os props direto. A asserção aqui é sobre a travessia projeção → props.
 */
function mpcComDv(range: { low: number; high: number } | null): MpcNodeOut {
  return {
    flow_id: 1,
    flow_name: "f",
    flow_ts_seconds: 0.5,
    block_id: "mpc1",
    name: "MPC",
    multiplier: 2,
    variables: {
      mvs: [],
      cvs: [],
      constraints: [],
      dvs: [{ id: "dv_1", name: "DV constante", eu: "m3/h", range }],
    },
    horizons: { ts_mpc: 1, np: 1, nc: 1 },
  };
}

test("gradeDeVariaveis repassa o range publicado da DV até o faceplate", () => {
  const grade = gradeDeVariaveis(mpcComDv({ low: 0, high: 100 }), undefined, 1, "mpc1");
  const dv = grade.find((item) => item.tipo === "dv");
  expect(dv?.definicao.range).toEqual({ low: 0, high: 100 });
  expect(faixaDaEscala(dv as FaceplateVariavelProps)).toEqual({ min: 0, max: 100 });
});

test("gradeDeVariaveis mantém a DV sem faixa quando o servidor não publica range", () => {
  const grade = gradeDeVariaveis(mpcComDv(null), undefined, 1, "mpc1");
  const dv = grade.find((item) => item.tipo === "dv");
  expect(dv?.definicao.range).toBeNull();
  expect(faixaDaEscala(dv as FaceplateVariavelProps)).toBeNull();
});
