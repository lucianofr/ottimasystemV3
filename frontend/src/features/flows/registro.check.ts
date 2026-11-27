import { expect, test } from "@playwright/test";

import { PORT_CONTRACTS } from "../../lib/contracts.gen";
import { criarBloco, TIPOS_BLOCO } from "./graph";
import { TIPOS_DE_NO } from "./nodes";
import {
  DEFAULT_SERVIDOR_FUZZY_LOOP,
  DEFAULT_SERVIDOR_PID_LOOP,
  PADRAO_FUZZY_LOOP,
  PADRAO_PID_LOOP,
  REGISTRO_BLOCO,
  ROTULO_BLOCO,
} from "./registro";

/**
 * Completude do registro (ARCH-18/TD-021): antes, um tipo esquecido em `nodes/index.tsx`
 * (mapa `TIPOS_DE_NO`, tipado como `NodeTypes` — index signature solta, não `Record<TipoBloco,
 * ...>`) ou em algum `case` só aparecia em runtime/E2E. `REGISTRO_BLOCO[tipo]` já quebra o
 * BUILD se faltar (tipado `Record<TipoBloco, DefinicaoBloco>`); esta suite cobre o resto —
 * que os campos de cada entrada estão de fato preenchidos, e que os mapas derivados
 * (`ROTULO_BLOCO`, `TIPOS_DE_NO`) têm exatamente uma entrada por tipo, nem mais nem menos.
 */

for (const tipo of TIPOS_BLOCO) {
  test(`REGISTRO_BLOCO['${tipo}']: rótulo, descrição e defaults preenchidos`, () => {
    const definicao = REGISTRO_BLOCO[tipo];
    expect(definicao).toBeDefined();
    expect(definicao.rotulo.trim()).not.toBe("");
    expect(definicao.descricao.trim()).not.toBe("");

    const defaults = definicao.defaults();
    expect(defaults).not.toBeNull();
    expect(typeof defaults).toBe("object");
  });

  test(`criarBloco('${tipo}', ...) monta um nó com exec_order/label por cima dos defaults do registro`, () => {
    const no = criarBloco(tipo, "n1", { x: 0, y: 0 }, 1);
    expect(no.type).toBe(tipo);
    expect(no.data.exec_order).toBe(1);
    expect(no.data.label).toBe("");
    expect(no.data).toMatchObject(REGISTRO_BLOCO[tipo].defaults());
  });
}

test("ROTULO_BLOCO e TIPOS_DE_NO têm exatamente uma entrada por tipo de TIPOS_BLOCO — nem faltando, nem sobrando", () => {
  const tiposRotulo = Object.keys(ROTULO_BLOCO).sort();
  const tiposNo = Object.keys(TIPOS_DE_NO).sort();
  const esperado = [...TIPOS_BLOCO].sort();

  expect(tiposRotulo).toEqual(esperado);
  expect(tiposNo).toEqual(esperado);
});

test("TIPOS_BLOCO é exatamente o conjunto de PORT_CONTRACTS — bloco novo no servidor sem entrada na paleta (e vice-versa) quebra aqui", () => {
  // Último elo do ARCH-18: `portasFixas` indexa `PORT_CONTRACTS[tipo]` e `TipoBloco ⊂ keys`
  // typecheca mesmo faltando um tipo na lista manual de `TIPOS_BLOCO` — o bloco sumiria da
  // paleta em silêncio. Encadeia com `set(port_contracts) == set(NODE_TYPES)`
  // (`test_contracts_export.py`), fechando paleta ⇄ contrato ⇄ `NODE_TYPES` do servidor.
  expect([...TIPOS_BLOCO].sort()).toEqual(Object.keys(PORT_CONTRACTS).sort());
});

test("defaults() de tfs/script/fuzzy/mpc devolve objeto novo a cada chamada — dois blocos novos não compartilham matrix/output_eu/variables", () => {
  for (const tipo of ["tfs", "script", "fuzzy", "mpc"] as const) {
    const a = REGISTRO_BLOCO[tipo].defaults() as Record<string, unknown>;
    const b = REGISTRO_BLOCO[tipo].defaults() as Record<string, unknown>;
    expect(a).not.toBe(b);
    for (const chave of Object.keys(a)) {
      if (typeof a[chave] === "object" && a[chave] !== null) {
        expect(a[chave]).not.toBe(b[chave]);
      }
    }
  }
});

test("defaults do servidor do pid_loop: espelho de parse.py (ADR-034)", () => {
  expect(DEFAULT_SERVIDOR_PID_LOOP).toEqual({
    permitted: ["oos", "man", "auto"], normal: "auto",
    shed_opt: "shed_to_auto", shed_no_return: false,
    direct_acting: false, sp_pv_track_in_man: true, use_pv_for_bkcal: false,
    track_enable: false, track_in_manual: false,
    sp_rate_up: null, sp_rate_dn: null,
    out_hi_lim: 100, out_lo_lim: 0, out_rate_up: null, out_rate_dn: null,
    out_scale_lo: 0, out_scale_hi: 100, out_startup: 0, pv_ftime: 0,
    trk_val: 0, lo_val: 0, ff_scale_lo: 0, ff_scale_hi: 100, ff_gain: 1, ff_enable: false,
    ti_seconds: 0, td_seconds: 0, n: 8, beta: 1, gamma: 0, gap_band: 0, gap_gain: 1,
  });
});

test("bloco recém-arrastado ≠ default do servidor: PID novo nasce PI (TI = 60 s)", () => {
  expect(PADRAO_PID_LOOP).toEqual({
    ...DEFAULT_SERVIDOR_PID_LOOP, sp_lo_lim: 0, sp_hi_lim: 100, kc: 1, ti_seconds: 60,
  });
  expect(DEFAULT_SERVIDOR_PID_LOOP.ti_seconds).toBe(0);
});

test("defaults do fuzzy_loop: espelho do servidor e bloco novo com a sintonia de comissionamento", () => {
  expect(DEFAULT_SERVIDOR_FUZZY_LOOP.lut_enabled).toBe(false);
  expect(DEFAULT_SERVIDOR_FUZZY_LOOP.lut_resolution).toBe(65);
  expect(DEFAULT_SERVIDOR_FUZZY_LOOP.sp_pv_track_in_man).toBe(true);
  expect(PADRAO_FUZZY_LOOP).toEqual({
    ...DEFAULT_SERVIDOR_FUZZY_LOOP, sp_lo_lim: 0, sp_hi_lim: 100, ke: 0.05, ku: 2,
  });
});
