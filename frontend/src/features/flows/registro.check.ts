import { expect, test } from "@playwright/test";

import { PORT_CONTRACTS } from "../../lib/contracts.gen";
import { criarBloco, TIPOS_BLOCO } from "./graph";
import { TIPOS_DE_NO } from "./nodes";
import { REGISTRO_BLOCO, ROTULO_BLOCO } from "./registro";

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
