import { expect, test } from "@playwright/test";

import { faixaDaEscala, type FaceplateVariavelProps, type VariavelTipo } from "./FaceplateVariavel";
import { gradeDeVariaveis } from "./gradeVariaveis";
import type { MpcNodeOut } from "./useMpcs";

/**
 * `faixaDaEscala` — RF-609 (lote zero/span): a escala da barra de TODOS os tipos é a faixa
 * de instrumento `[zero, zero+span]` — os ganhos do modelo são %/% sobre essa faixa, então a
 * barra do faceplate fala a mesma língua do operador. `limits`/`sp_limits`/`range` seguem na
 * definição (clamp dos comandos, RF-704), mas não alimentam mais a escala. Ausentes
 * (projeções antigas/testes), os defaults 0/100 reproduzem a faixa percentual de sempre.
 * `span <= 0` ou não-finito ⇒ null (sem barra) — a guarda vive aqui porque o cliente não
 * confia na projeção.
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

test("sem zero/span publicados, os 4 tipos caem na faixa default 0..100", () => {
  for (const tipo of ["mv", "cv", "constraint", "dv"] as const) {
    expect(faixaDaEscala(props(tipo))).toEqual({ min: 0, max: 100 });
  }
});

test("zero/span definem a faixa [zero, zero+span] para os 4 tipos", () => {
  for (const tipo of ["mv", "cv", "constraint", "dv"] as const) {
    expect(faixaDaEscala(props(tipo, { zero: 20, span: 50 }))).toEqual({ min: 20, max: 70 });
  }
});

test("a faixa do instrumento ignora limits/sp_limits/range (eles não alimentam a escala)", () => {
  const faixa = faixaDaEscala(
    props("mv", {
      zero: 10,
      span: 40,
      limits: { min: -10, max: 10 },
      range: { low: 999, high: -999 },
    }),
  );
  expect(faixa).toEqual({ min: 10, max: 50 });
});

test("span zero, negativo ou não finito devolve null (sem barra)", () => {
  expect(faixaDaEscala(props("mv", { span: 0 }))).toBeNull();
  expect(faixaDaEscala(props("mv", { span: -5 }))).toBeNull();
  expect(faixaDaEscala(props("mv", { span: Number.NaN }))).toBeNull();
  expect(faixaDaEscala(props("mv", { zero: Number.NaN }))).toBeNull();
});

/**
 * Travessia projeção → props (regressão do gate L3, cenário B-F6-10): `gradeDeVariaveis`
 * repassa `range`/zero/span da DV publicada por `GET /api/operate/mpcs` até o faceplate.
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
      dvs: [{ id: "dv_1", name: "DV constante", eu: "m3/h", zero: 0, span: 100, range }],
    },
    horizons: { ts_mpc: 1, np: 1, nc: 1 },
  };
}

test("gradeDeVariaveis repassa o range publicado da DV até a definição do faceplate", () => {
  const grade = gradeDeVariaveis(mpcComDv({ low: 0, high: 100 }), undefined, 1, "mpc1");
  const dv = grade.find((item) => item.tipo === "dv");
  expect(dv?.definicao.range).toEqual({ low: 0, high: 100 });
  // A escala da barra é a faixa de instrumento (RF-609), não mais o range.
  expect(faixaDaEscala(dv as FaceplateVariavelProps)).toEqual({ min: 0, max: 100 });
});

test("gradeDeVariaveis sem range na DV: definição null, barra na faixa do instrumento", () => {
  const grade = gradeDeVariaveis(mpcComDv(null), undefined, 1, "mpc1");
  const dv = grade.find((item) => item.tipo === "dv");
  expect(dv?.definicao.range).toBeNull();
  expect(faixaDaEscala(dv as FaceplateVariavelProps)).toEqual({ min: 0, max: 100 });
});
