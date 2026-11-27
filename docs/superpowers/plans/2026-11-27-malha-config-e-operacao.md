# Blocos malha: config completa no editor e tela MALHA — Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** tornar o PID Malha (`pid_loop`) inteiramente configurável no editor de flow, estender os campos de shell ao Fuzzy Malha, parar a perda silenciosa de config dos blocos malha no editor e entregar a tela MALHA utilizável (seletor, escalas reais, sintonia, tendência PV/SP/OUT).

**Architecture:** entrega de frontend. O editor passa a tipar a config dos blocos malha pelo contrato gerado inteiro e a normalizar todos os campos, com os defaults do servidor espelhados à mão em `registro.ts` (ADR-034) e travados por um teste Python e um teste TS. O formulário são seções não-controladas dentro do `ModalConfigBloco` existente, lidas por funções puras. A tela MALHA é decomposta em seletor + faceplate + sintonia + tendência, com toda decisão ("ao vivo", escala, seleção, ids de pena) em um módulo puro testado.

**Tech Stack:** React + Vite + TypeScript strict, shadcn/ui, react-router, @tanstack/react-query, uPlot (via `features/trend/`), checks puros com o runner do Playwright (`*.check.ts`); Python 3.12 + pytest só para o teste de trava.

**Spec:** `docs/specs/SPEC_MALHA_CONFIG_E_OPERACAO.md` — requisitos em `docs/PRD.md` §5.20 (RF-641…RF-646). Leia a spec inteira antes da Tarefa 1; este plano não a repete.

## Global Constraints

- **Nenhuma** mudança em `services/`, em `packages/ottima-core/src/`, em migrations, em canais ou em `frontend/scripts/generate-contracts.mjs`. `npm run generate:contracts && git diff --exit-code` tem de sair limpo.
- Frontend nunca valida faixa nem executa lógica de controle (ADR-005): o modal coleta, o servidor valida no Salvar (422).
- Defaults de config de bloco são **espelhados à mão**, nunca gerados (ADR-034).
- Campos de formulário **não-controlados**, lidos por `FormData` no Aplicar; numéricos pelo `Campo` de `config/CamposComuns.tsx` (`type="text"` + `inputMode="decimal"`, aceita vírgula).
- `id`/`name` de cada input = nome do campo no contrato; `data-testid="config-<id com _ trocado por ->"` (convenção do `Campo`).
- Identificadores em inglês ou no padrão pt-BR já usado no arquivo; strings de UI em pt-BR com o vocabulário de `docs/GLOSSARY.md`.
- TypeScript strict; nenhuma dependência nova.
- Commits em Conventional Commits, mensagem em pt-BR, terminando com `Co-Authored-By: Claude Fable 5.2 <noreply@anthropic.com>`.
- **Worktree:** uma worktree para esta entrega, branch `feat/malha-config-operacao` criada a partir de `docs/pid-malha-config` (onde estão a spec, o PRD 3.5 e este plano). Subagente em worktree usa **caminho absoluto** em todo read/write/edit, `cwd` explícito em todo comando, confirma cada escrita por shell e termina com `git status --porcelain` do checkout principal vazio (CLAUDE.md, "Subagente em worktree").
- Rodar um check isolado: `cd frontend && npx playwright test -c playwright.unit.config.ts <caminho do .check.ts>`.

## Contratos do PRD §7 usados (verbatim — nenhum é alterado)

Canal (§7.1), entregue pelo `/ws` na chave `loop_state`, uma mensagem por canal de controle:

| Canal | Produtor | Consumidores | Payload (JSON) |
|---|---|---|---|
| `loop.state.<flow_id>.<block_id>` | flow-runtime | api(WS), recorder | {ts, target, actual, permitted[], pv, pv_ok, sp, out, u_pct, man_out, hi_limited, lo_limited, diag{}, channel} |

Rotas (§7.3, todas `require_operator`):

- `GET /api/operate/loop` → `LoopNodeOut[]` `{flow_id, flow_name, block_id, label, type, n_loops}`
- `GET /api/operate/loop/{flow_id}/{block_id}` → `LoopDetailOut` `{flow_id, flow_name, block_id, label, type, permitted[], sp_lo_lim, sp_hi_lim, out_lo_lim, out_hi_lim, out_scale_lo, out_scale_hi, n_loops, tuning}`; `tuning` é `{kc, ti_seconds, td_seconds, n, beta, gamma, gap_band, gap_gain, direct_acting}` (PID) ou `{ke, kde, ku, tf_de, direct_acting}` (fuzzy)
- `POST /api/operate/{flow_id}/{block_id}/mode` `{target}` · `/sp` `{value, channel}` · `/out` `{value, channel}` → 202 (comandado ≠ confirmado)
- `GET /api/history/loop?flow_id=&block_id=&var_ids=&start=&end=` → `{mode: "raw"|"1m", start, end, series[{var_id, t[], v[], v_min?, v_max?}]}`; `var_ids` ∈ `pv|sp|out|mode` com sufixo `:<canal>` para canal ≥ 1; `v` pode ser `null`

## Review Focus

Condições que a spec implica e que mordem quem usa; cada uma tem teste na tarefa dona do código.

1. **Texto ilegível num campo de rampa** ("1,5" / "abc" / vazio): vírgula vira número, vazio vira `null` (sem rampa), lixo mantém o valor anterior — nunca apaga a rampa em silêncio. → Tarefa 3.
2. **Grafo gravado com valor torto num campo de malha** (`permitted` com item não-string, `shed_opt` desconhecido, booleano como string): o editor carrega com o default do servidor, sem lançar. → Tarefa 2.
3. **URL da MALHA apontando para bloco que não existe mais** (bloco apagado, projeto ativo trocado): cai na primeira malha; lista vazia mantém o estado vazio. → Tarefa 5.
4. **Faixa degenerada** (`sp_lo_lim >= sp_hi_lim` ou valor fora da faixa): barra em 0 % ou presa em 0–100 %, nunca `NaN`/largura negativa. → Tarefa 5.
5. **Série de histórico com `v` nulo** (PV sem valor grava `NULL`) e bloco com 3+ canais: nulos não viram zero nem quebram o gráfico; a pré-seleção respeita o teto de 6 penas. → Tarefa 5.

---

## Estrutura de arquivos

| Arquivo | Responsabilidade | Tarefa |
|---|---|---|
| `packages/ottima-core/tests/test_loop_config_defaults.py` (novo) | Trava: default do Pydantic mudou ⇒ vermelho apontando `registro.ts` | 1 |
| `frontend/src/features/flows/registro.ts` | `DEFAULT_SERVIDOR_*` (espelho) e `PADRAO_*` (bloco novo) | 1 |
| `frontend/src/features/flows/graph.ts` | Tipos completos e normalizador sem perda | 2 |
| `frontend/src/features/flows/config/campos.ts` | `montarDadosShellMalha`, `montarDadosPidLoop`, regra das caixas de modo | 3 |
| `frontend/src/features/flows/config/CamposComuns.tsx` | recebe `CampoBooleano` (sai de `CamposBlocoPid.tsx`) | 4 |
| `frontend/src/features/flows/config/CamposShellMalha.tsx` (novo) | Seções Setpoint, Saída, Modos, Tracking e override, Feedforward | 4 |
| `frontend/src/features/flows/config/CamposPidMalha.tsx` (novo) | Seção Sintonia do PID + shell completo | 4 |
| `frontend/src/features/flows/config/CamposMalhaFuzzy.tsx` | passa a usar `CamposShellMalha` no recorte fuzzy | 4 |
| `frontend/src/features/flows/config/ModalConfigBloco.tsx` | ramos `pid_loop`/`fuzzy_loop` | 4 |
| `frontend/src/features/flows/nodes/index.tsx` | linha "Ação" no `NoPidLoop` | 4 |
| `frontend/src/features/loop/malhaLogica.ts` (novo) | Toda decisão pura da tela MALHA | 5 |
| `frontend/src/features/loop/LoopOperatePage.tsx` | Página: seletor + layout | 6 |
| `frontend/src/features/loop/FaceplateMalha.tsx` (novo) | Badges, botoeira, barras, escritas, heatmap | 6 |
| `frontend/src/features/loop/SintoniaVigente.tsx` (novo) | Cartão de sintonia somente leitura | 6 |
| `frontend/src/app/CanalAoVivo.tsx` | exporta o tipo `EstadoConexaoCanal` (só o tipo) | 6 |
| `frontend/src/features/loop/useHistoryLoop.ts` (novo) | Hook de `GET /api/history/loop` | 7 |
| `frontend/src/features/loop/TrendMalha.tsx` (novo) | Tendência PV/SP/OUT | 7 |
| `docs/specs/SPEC_PID_with_SHELL.md`, `SPEC_FUZZY_with_SHELL.md`, `CLAUDE.md` | ponteiros e nota da tela | 8 |

---

### Task 1: Espelho dos defaults do servidor e trava (RF-643)

**Files:**
- Create: `packages/ottima-core/tests/test_loop_config_defaults.py`
- Modify: `frontend/src/features/flows/registro.ts:131-166` (`PADRAO_PID_LOOP`, `PADRAO_FUZZY_LOOP`)
- Test: `frontend/src/features/flows/registro.check.ts`

**Interfaces:**
- Produces (em `registro.ts`):
  - `DEFAULT_SERVIDOR_PID_LOOP: Omit<PidLoopConfig, "sp_hi_lim" | "sp_lo_lim" | "kc">`
  - `DEFAULT_SERVIDOR_FUZZY_LOOP: Omit<FuzzyLoopConfig, "sp_hi_lim" | "sp_lo_lim" | "ke" | "ku" | "fll">`
  - `PADRAO_PID_LOOP: PidLoopConfig`
  - `PADRAO_FUZZY_LOOP: Omit<FuzzyLoopConfig, "fll">`
  - (`PidLoopConfig`/`FuzzyLoopConfig` são `import type` de `../../lib/contracts.gen`; a anotação `Omit<…>` é o que faz o `tsc` acusar campo esquecido.)

- [ ] **Step 1: Escrever o teste Python de trava**

```python
"""Trava do espelho manual de defaults dos blocos malha (ADR-034, "teste próprio").

Se este teste ficar vermelho, um default de `LoopBaseConfig`/`PidLoopConfig`/`FuzzyLoopConfig`
mudou: atualize ESTA tabela e o espelho em `frontend/src/features/flows/registro.ts`
(`DEFAULT_SERVIDOR_PID_LOOP` / `DEFAULT_SERVIDOR_FUZZY_LOOP`) no mesmo commit.
"""

from pydantic_core import PydanticUndefined

from ottima_core.flowgraph.parse import FuzzyLoopConfig, PidLoopConfig

_SHELL = {
    "permitted": ["oos", "man", "auto"], "normal": "auto",
    "shed_opt": "shed_to_auto", "shed_no_return": False,
    "direct_acting": False, "sp_pv_track_in_man": True, "use_pv_for_bkcal": False,
    "track_enable": False, "track_in_manual": False,
    "sp_rate_up": None, "sp_rate_dn": None,
    "out_hi_lim": 100.0, "out_lo_lim": 0.0, "out_rate_up": None, "out_rate_dn": None,
    "out_scale_lo": 0.0, "out_scale_hi": 100.0, "out_startup": 0.0, "pv_ftime": 0.0,
    "trk_val": 0.0, "lo_val": 0.0,
    "ff_scale_lo": 0.0, "ff_scale_hi": 100.0, "ff_gain": 1.0, "ff_enable": False,
}
_PID = {**_SHELL, "ti_seconds": 0.0, "td_seconds": 0.0, "n": 8.0, "beta": 1.0,
        "gamma": 0.0, "gap_band": 0.0, "gap_gain": 1.0}
_FUZZY = {**_SHELL, "n_loops": 1, "kde": 0.0, "tf_de": 1.0,
          "lut_enabled": False, "lut_resolution": 65}


def _defaults(model) -> dict:
    saida = {}
    for nome, campo in model.model_fields.items():
        if campo.default_factory is not None:
            saida[nome] = campo.default_factory()
        elif campo.default is not PydanticUndefined:
            saida[nome] = campo.default
    return saida


def test_defaults_do_pid_loop_batem_com_o_espelho_do_editor() -> None:
    assert _defaults(PidLoopConfig) == _PID


def test_defaults_do_fuzzy_loop_batem_com_o_espelho_do_editor() -> None:
    reais = _defaults(FuzzyLoopConfig)
    reais.pop("fll")  # exportado em PORT_CONTRACTS.fuzzy_loop.default_fll
    assert reais == _FUZZY
```

- [ ] **Step 2: Rodar — tem de PASSAR de primeira**

Run: `uv run pytest packages/ottima-core/tests/test_loop_config_defaults.py -v`
Expected: 2 passed. (É teste de caracterização: a tabela acima foi lida de `parse.py:540-620`. Se falhar, o servidor diverge do que a spec assumiu — PARE e reporte a diferença, não ajuste a tabela às cegas.)

- [ ] **Step 3: Escrever o check TS que falha**

Acrescentar em `registro.check.ts` (importando as 4 constantes de `./registro`):

```ts
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
```

- [ ] **Step 4: Rodar e ver falhar**

Run: `cd frontend && npx playwright test -c playwright.unit.config.ts src/features/flows/registro.check.ts`
Expected: FAIL — `DEFAULT_SERVIDOR_PID_LOOP` não exportado.

- [ ] **Step 5: Implementar as 4 constantes em `registro.ts`**

`DEFAULT_SERVIDOR_FUZZY_LOOP` = os 25 campos de shell + `n_loops: 1, kde: 0, tf_de: 1, lut_enabled: false, lut_resolution: 65`. `PADRAO_*` por spread, exatamente como os testes. O `fll` continua fora (thunk de `defaults` em `REGISTRO_BLOCO.fuzzy_loop`, como hoje). Atualizar o comentário de `PADRAO_PID_LOOP` (não diz mais "os demais campos ficam nos defaults do servidor").

- [ ] **Step 6: Rodar os dois checks e o typecheck**

Run: `cd frontend && npx playwright test -c playwright.unit.config.ts src/features/flows/registro.check.ts && npm run typecheck`
Expected: check PASS. O typecheck **pode** falhar em `graph.ts`/`graph.check.ts` (tipos `DadosPidLoop` ainda estreitos) — isso é resolvido na Tarefa 2; se falhar em outro arquivo, corrija aqui.

- [ ] **Step 7: Commit**

```bash
git add packages/ottima-core/tests/test_loop_config_defaults.py frontend/src/features/flows/registro.ts frontend/src/features/flows/registro.check.ts
git commit -m "feat(flows): espelho dos defaults do servidor dos blocos malha, travado por teste (RF-643)"
```

---

### Task 2: Tipos completos e normalizador sem perda (RF-643)

**Files:**
- Modify: `frontend/src/features/flows/graph.ts:259-298` (tipos), `:1316-1366` (casos `pid_loop`/`fuzzy_loop` de `lerNo`)
- Test: `frontend/src/features/flows/graph.check.ts` (inclui o helper `pidLoop` em `:205-225`)

**Interfaces:**
- Consumes: `DEFAULT_SERVIDOR_PID_LOOP`, `DEFAULT_SERVIDOR_FUZZY_LOOP`, `PADRAO_PID_LOOP`, `PADRAO_FUZZY_LOOP` (Tarefa 1).
- Produces:
  - `export type DadosPidLoop = DadosBase & PidLoopConfig;`
  - `export type DadosFuzzyLoop = DadosBase & FuzzyLoopConfig;`
  - `export type DadosShellMalha = Pick<PidLoopConfig, …os 27 campos de LoopBaseConfig…>` (os 25 de `_SHELL` da Tarefa 1 + `sp_hi_lim`, `sp_lo_lim`) — `DadosPidLoop` e `DadosFuzzyLoop` são ambos atribuíveis a ele.
  - `deGraphJson`/`paraGraphJson` inalterados na assinatura.

- [ ] **Step 1: Escrever os testes que falham** (em `graph.check.ts`)

```ts
const SHELL_FORA_DO_DEFAULT = {
  permitted: ["oos", "man", "auto", "iman"], normal: "man",
  shed_opt: "shed_to_man", shed_no_return: true,
  direct_acting: true, sp_pv_track_in_man: false, use_pv_for_bkcal: true,
  track_enable: true, track_in_manual: true,
  sp_hi_lim: 250, sp_lo_lim: 50, sp_rate_up: 1.5, sp_rate_dn: 2.5,
  out_hi_lim: 80, out_lo_lim: 10, out_rate_up: 3, out_rate_dn: 4,
  out_scale_lo: 4, out_scale_hi: 20, out_startup: 15, pv_ftime: 2,
  trk_val: 33, lo_val: 44, ff_scale_lo: 1, ff_scale_hi: 9, ff_gain: 0.5, ff_enable: true,
};
const PID_FORA_DO_DEFAULT = {
  ...SHELL_FORA_DO_DEFAULT,
  kc: 2.5, ti_seconds: 12, td_seconds: 3, n: 10, beta: 0.4, gamma: 0.2, gap_band: 0.7, gap_gain: 0.3,
};

function noMalha(type: "pid_loop" | "fuzzy_loop", data: Record<string, unknown>) {
  return { nodes: [{ id: "m", type, position: { x: 0, y: 0 }, data: { exec_order: 1, label: "", ...data } }], edges: [] };
}
/** `data` do nó como sai para o servidor — `Record` solto porque a união de `data` não expõe
 *  os campos de malha sem estreitar por tipo. */
function dadosDoNo(grafo: ReturnType<typeof deGraphJson>): Record<string, unknown> {
  return paraGraphJson(grafo.nodes, grafo.edges).nodes[0].data as unknown as Record<string, unknown>;
}

test("pid_loop: os 35 campos fora do default sobrevivem a carregar e salvar (RF-643)", () => {
  expect(dadosDoNo(deGraphJson(noMalha("pid_loop", PID_FORA_DO_DEFAULT)))).toEqual({
    exec_order: 1, label: "", ...PID_FORA_DO_DEFAULT,
  });
});

test("pid_loop só com os obrigatórios carrega com o default do SERVIDOR (TI = 0, não 60)", () => {
  const dados = dadosDoNo(deGraphJson(noMalha("pid_loop", { sp_hi_lim: 100, sp_lo_lim: 0, kc: 2 })));
  expect(dados).toEqual({
    exec_order: 1, label: "", ...DEFAULT_SERVIDOR_PID_LOOP, sp_hi_lim: 100, sp_lo_lim: 0, kc: 2,
  });
});

test("fuzzy_loop: campos de shell e LUT fora do default sobrevivem a carregar e salvar", () => {
  const data = {
    ...SHELL_FORA_DO_DEFAULT, permitted: ["oos", "man"], normal: "man",
    n_loops: 2, ke: 0.1, kde: 0.3, ku: 4, tf_de: 2.5, fll: fllDefaultMalha(2),
    lut_enabled: true, lut_resolution: 129,
  };
  expect(dadosDoNo(deGraphJson(noMalha("fuzzy_loop", data)))).toEqual({ exec_order: 1, label: "", ...data });
});

// Review Focus 2: valor torto no grafo gravado não derruba o editor.
test("campo de malha com tipo errado cai no default do servidor, sem lançar", () => {
  const dados = dadosDoNo(deGraphJson(noMalha("pid_loop", {
    sp_hi_lim: 100, sp_lo_lim: 0, kc: 2,
    permitted: ["auto", 7, null], shed_opt: "desconhecido", ff_enable: "true", sp_rate_up: "rápido",
  })));
  expect(dados.permitted).toEqual(["auto"]);
  expect(dados.shed_opt).toBe("shed_to_auto");
  expect(dados.ff_enable).toBe(false);
  expect(dados.sp_rate_up).toBeNull();
});
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd frontend && npx playwright test -c playwright.unit.config.ts src/features/flows/graph.check.ts -g "pid_loop|fuzzy_loop|campo de malha"`
Expected: FAIL — campos fora do `Pick` atual ausentes no resultado.

- [ ] **Step 3: Alargar os tipos em `graph.ts`**

Substituir os dois `Pick<…>` por `DadosBase & PidLoopConfig` / `DadosBase & FuzzyLoopConfig`, exportar `DadosShellMalha` e reescrever os dois comentários de doc (não dizem mais "o editor conhece só os campos que expõe").

- [ ] **Step 4: Reescrever os dois casos do normalizador**

Em `lerNo`: uma função privada `lerShellMalha(dados: Record<string, unknown>, padraoObrigatorios: { sp_hi_lim: number; sp_lo_lim: number }): DadosShellMalha` lê os 27 campos de shell com fallback em `DEFAULT_SERVIDOR_PID_LOOP` (os defaults de shell são idênticos nos dois blocos) e é usada pelos dois `case`. Regras por tipo de campo:
- número: `numero(valor, padrao)` (já existe em `:1036`);
- booleano: só `typeof === "boolean"` vale, senão padrão;
- nulável (`sp_rate_*`, `out_rate_*`): número finito ⇒ número; qualquer outra coisa ⇒ `null`;
- `shed_opt`: um dos três literais do contrato, senão `"shed_to_auto"`;
- `permitted`: array ⇒ só os itens string; não-array ⇒ default;
- `normal`: string ⇒ ela; senão default.

Campos de kernel: PID com fallback `DEFAULT_SERVIDOR_PID_LOOP` (e `PADRAO_PID_LOOP.kc` para o obrigatório `kc`); fuzzy mantém os fallbacks atuais de `n_loops`/`ke`/`kde`/`ku`/`tf_de`/`fll` e ganha `lut_enabled`/`lut_resolution` (`inteiro(valor, 65, 33, 257)`).

- [ ] **Step 5: Atualizar o helper `pidLoop` de `graph.check.ts`**

`data: { exec_order: ordem, label: "", ...PADRAO_PID_LOOP, permitted: [...permitted] }`.

- [ ] **Step 6: Rodar tudo**

Run: `cd frontend && npx playwright test -c playwright.unit.config.ts src/features/flows && npm run typecheck`
Expected: todos os checks de `flows/` PASS. Typecheck pode acusar só o `case "fuzzy_loop"` de `ModalConfigBloco.tsx` — se acusar, o motivo é tipo de literal; deixe o `case` compilando com a menor mudança possível (a Tarefa 4 o reescreve).

- [ ] **Step 7: Commit**

```bash
git add frontend/src/features/flows/graph.ts frontend/src/features/flows/graph.check.ts frontend/src/features/flows/config/ModalConfigBloco.tsx
git commit -m "fix(flows): editor preserva toda a config dos blocos malha ao carregar e salvar (RF-643)"
```

---

### Task 3: Leitura pura do formulário de malha (RF-641, RF-642)

**Files:**
- Modify: `frontend/src/features/flows/config/campos.ts`
- Test: `frontend/src/features/flows/config/campos.check.ts`

**Interfaces:**
- Consumes: `DadosShellMalha`, `DadosPidLoop` (Tarefa 2); `numeroDoCampo`, `numeroOuNuloDoCampo` (já em `campos.ts`).
- Produces:
  - `export const MODOS_COM_CAIXA = ["oos", "man", "auto", "cas", "rcas", "rout"] as const;`
  - `export const PORTA_DO_MODO_REMOTO: Readonly<Record<string, string>> = { cas: "cas_in", rcas: "rcas_in", rout: "rout_in" };`
  - `export function caixaDeModoDesabilitada(modo: string, portasLigadas: ReadonlySet<string>, marcado: boolean): boolean`
  - `export function montarDadosShellMalha<T extends DadosShellMalha>(atual: T, campos: FormData, tipo: "pid_loop" | "fuzzy_loop"): T`
  - `export function montarDadosPidLoop(atual: DadosPidLoop, campos: FormData): DadosPidLoop`
- Contrato do `FormData` (o que a Tarefa 4 tem de desenhar):
  - numéricos e nuláveis: `name` = nome do campo;
  - booleanos: checkbox `name` = nome do campo, marcado ⇒ `"on"`;
  - `direct_acting`: `<select name="direct_acting">` com valores `"true"`/`"false"` (padrão já usado no Fuzzy Malha);
  - `normal` e `shed_opt`: `<select>` com o literal do contrato;
  - `permitted`: uma checkbox por modo, `name="permitted_<modo>"`.

- [ ] **Step 1: Escrever os testes que falham**

```ts
function formulario(campos: Record<string, string>): FormData {
  const dados = new FormData();
  for (const [nome, valor] of Object.entries(campos)) dados.set(nome, valor);
  return dados;
}
const ATUAL: DadosPidLoop = { exec_order: 1, label: "", ...PADRAO_PID_LOOP, sp_rate_up: 2, ff_enable: true };

test("modo remoto só fica desabilitado se a porta não está ligada E a caixa não está marcada", () => {
  const semArestas = new Set<string>();
  expect(caixaDeModoDesabilitada("cas", semArestas, false)).toBe(true);
  expect(caixaDeModoDesabilitada("cas", semArestas, true)).toBe(false); // nunca desmarca sozinho
  expect(caixaDeModoDesabilitada("cas", new Set(["cas_in"]), false)).toBe(false);
  expect(caixaDeModoDesabilitada("rout", new Set(["cas_in"]), false)).toBe(true);
  expect(caixaDeModoDesabilitada("auto", semArestas, false)).toBe(false);
});

test("montarDadosPidLoop lê sintonia, ação e campos de shell", () => {
  const novo = montarDadosPidLoop(ATUAL, formulario({
    direct_acting: "true", kc: "2,5", ti_seconds: "0", n: "10", beta: "0,5",
    sp_hi_lim: "250", out_hi_lim: "80", pv_ftime: "1,5", normal: "man", shed_opt: "shed_to_man",
    permitted_oos: "on", permitted_man: "on",
  }));
  expect(novo).toMatchObject({
    direct_acting: true, kc: 2.5, ti_seconds: 0, n: 10, beta: 0.5,
    sp_hi_lim: 250, out_hi_lim: 80, pv_ftime: 1.5, normal: "man", shed_opt: "shed_to_man",
    permitted: ["oos", "man"],
  });
});

test("caixa desmarcada (ausente do FormData) vira false", () => {
  const novo = montarDadosPidLoop(ATUAL, formulario({ permitted_auto: "on" }));
  expect(novo.ff_enable).toBe(false);
  expect(novo.sp_pv_track_in_man).toBe(false);
});

// Review Focus 1
test("rampa: vírgula vira número, vazio vira null, texto ilegível mantém o valor anterior", () => {
  expect(montarDadosPidLoop(ATUAL, formulario({ sp_rate_up: "1,5" })).sp_rate_up).toBe(1.5);
  expect(montarDadosPidLoop(ATUAL, formulario({ sp_rate_up: "" })).sp_rate_up).toBeNull();
  expect(montarDadosPidLoop(ATUAL, formulario({ sp_rate_up: "abc" })).sp_rate_up).toBe(2);
});

test("permitted: ordem canônica das caixas e modo sem caixa preservado", () => {
  const atual = { ...ATUAL, permitted: ["auto", "iman", "oos"] };
  const novo = montarDadosPidLoop(atual, formulario({ permitted_auto: "on", permitted_oos: "on", permitted_cas: "on" }));
  expect(novo.permitted).toEqual(["oos", "auto", "cas", "iman"]);
});

test("recorte fuzzy: shed, tracking e feedforward não são tocados", () => {
  const atual = { ...ATUAL, shed_opt: "shed_to_man" as const, track_enable: true, trk_val: 33, ff_gain: 0.5 };
  const novo = montarDadosShellMalha(atual, formulario({ sp_hi_lim: "300", permitted_man: "on" }), "fuzzy_loop");
  expect(novo).toMatchObject({ sp_hi_lim: 300, shed_opt: "shed_to_man", track_enable: true, trk_val: 33, ff_gain: 0.5, ff_enable: true });
  expect(novo.permitted).toEqual(["man"]);
});
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd frontend && npx playwright test -c playwright.unit.config.ts src/features/flows/config/campos.check.ts`
Expected: FAIL — funções não exportadas.

- [ ] **Step 3: Implementar em `campos.ts`**

- `montarDadosShellMalha`: parte de `{ ...atual }`. Para os dois tipos lê `direct_acting`, `sp_lo_lim`, `sp_hi_lim`, `sp_rate_up/dn`, `sp_pv_track_in_man`, `out_scale_lo/hi`, `out_lo_lim/hi`, `out_rate_up/dn`, `out_startup`, `pv_ftime`, `permitted`, `normal`. Só para `"pid_loop"` lê também `shed_opt`, `shed_no_return`, `track_enable`, `track_in_manual`, `trk_val`, `lo_val`, `use_pv_for_bkcal`, `ff_enable`, `ff_gain`, `ff_scale_lo/hi`.
- Numérico: `numeroDoCampo(campos.get(x), atual.x)`. Nulável: `numeroOuNuloDoCampo(campos.get(x), atual.x)`. Booleano: `campos.get(x) === "on"`. `direct_acting`: `=== "true"`. `normal`/`shed_opt`: string do campo quando presente, senão `atual`.
- `permitted` = modos de `MODOS_COM_CAIXA` cuja `permitted_<modo>` é `"on"`, nessa ordem, seguidos dos itens de `atual.permitted` que não estão em `MODOS_COM_CAIXA`.
- `montarDadosPidLoop` = `montarDadosShellMalha(atual, campos, "pid_loop")` + os 8 campos de sintonia por `numeroDoCampo`.
- `caixaDeModoDesabilitada`: `false` para modo sem entrada em `PORTA_DO_MODO_REMOTO`; senão `!portasLigadas.has(porta) && !marcado`.

- [ ] **Step 4: Rodar e ver passar**

Run: `cd frontend && npx playwright test -c playwright.unit.config.ts src/features/flows/config/campos.check.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/flows/config/campos.ts frontend/src/features/flows/config/campos.check.ts
git commit -m "feat(flows): leitura pura do formulário dos blocos malha (RF-641, RF-642)"
```

---

### Task 4: Formulário no modal e resumo no nó (RF-641, RF-642, RF-644)

**Files:**
- Modify: `frontend/src/features/flows/config/CamposComuns.tsx` (recebe `CampoBooleano`), `CamposBlocoPid.tsx:21-47` (passa a importá-lo)
- Create: `frontend/src/features/flows/config/CamposShellMalha.tsx`, `frontend/src/features/flows/config/CamposPidMalha.tsx`
- Modify: `frontend/src/features/flows/config/CamposMalhaFuzzy.tsx:91-105`, `ModalConfigBloco.tsx:533-562` e `:674-675`, `frontend/src/features/flows/nodes/index.tsx:495-518`

**Interfaces:**
- Consumes: contrato de `FormData` e funções da Tarefa 3; `portasComAresta(arestas, blockId): ReadonlySet<string>` de `config/CamposHistoriar.tsx:48`; tabela de seções/campos/rótulos/unidades da spec §5.3.
- Produces:
  - `export function CampoBooleano(props: { id: string; rotulo: string; valor: boolean; ajuda: string })` em `CamposComuns.tsx` (movido sem mudar markup).
  - `export function CamposShellMalha(props: { dados: DadosShellMalha; tipo: "pid_loop" | "fuzzy_loop"; portasLigadas: ReadonlySet<string> })`
  - `export function CamposPidMalha(props: { dados: NoPidLoop["data"]; portasLigadas: ReadonlySet<string> })`
  - `CamposMalhaFuzzy` ganha a prop `portasLigadas: ReadonlySet<string>`.

Esta tarefa é JSX sem lógica própria (a lógica é a da Tarefa 3, já testada); a casa não tem teste de componente. A prova é typecheck + build + o roteiro de navegador da Tarefa 8.

- [ ] **Step 1: Mover `CampoBooleano` para `CamposComuns.tsx`** e importar em `CamposBlocoPid.tsx`.

Run: `cd frontend && npm run typecheck` → sem erro novo.

- [ ] **Step 2: Criar `CamposShellMalha.tsx`**

Seções, nesta ordem, cada uma `<fieldset>` com `<legend className="plaqueta text-[10px] text-fg-muted">` (padrão de `CamposBlocoPid.tsx:110`), campos e unidades **exatamente** da tabela da spec §5.3:
- **Setpoint**, **Saída**, **Modos** — sempre abertas, para os dois tipos.
- **Tracking e override**, **Feedforward** — só `tipo === "pid_loop"`, dentro de `<details>` **sem** o atributo `open` (o `<summary>` é o título). Nunca renderização condicional por estado: os inputs têm de ficar no DOM para entrarem no `FormData`.
- Rampas (`sp_rate_*`, `out_rate_*`): `Campo` com `valor` possivelmente `null` e `placeholder="sem rampa"`.
- **Aviso estrutural (RF-644)** logo abaixo de `out_scale_lo/hi`, texto: "Atenção: a escala de OUT é ESTRUTURAL — a troca re-instancia o bloco no próximo deploy e a malha aterrissa em MAN com a saída mantida (bumpless)."
- **Modos permitidos:** uma checkbox por modo de `MODOS_COM_CAIXA` no `pid_loop`, e só `oos`/`man`/`auto` no `fuzzy_loop`; `name="permitted_<modo>"`, `data-testid="config-permitted-<modo>"`, `defaultChecked={dados.permitted.includes(modo)}`, `disabled={caixaDeModoDesabilitada(modo, portasLigadas, dados.permitted.includes(modo))}`. Caixa desabilitada ganha `aria-describedby` apontando para o texto "ligue a porta `<porta>` para permitir este modo" (padrão de `CamposHistoriar.tsx:143-155`).
- **Modo normal:** `<Select name="normal">` com MAN/AUTO/CAS/RCAS no `pid_loop` e MAN/AUTO no `fuzzy_loop`.
- **Shed** (`pid_loop`): `<Select name="shed_opt">` com rótulos "ir para AUTO" / "ir para MAN" / "ir para o modo normal"; `shed_no_return` como `CampoBooleano`.
- Todo campo tem texto de ajuda curto em pt-BR. `kc`/ação ficam fora deste componente.

- [ ] **Step 3: Criar `CamposPidMalha.tsx`**

Seção **Sintonia** (aberta) com os 9 campos da spec §5.3 e depois `<CamposShellMalha tipo="pid_loop" …/>`. `direct_acting` é o mesmo `<Select>` de `CamposMalhaFuzzy.tsx:80-90` (valores `"false"`/`"true"`, rótulos "Reversa (erro = SP − PV)" / "Direta (erro = PV − SP)"). A ajuda de `kc` diz que o ganho é sempre positivo e que o sentido vem do campo Ação — **não** copiar o texto "Negativo inverte a ação" de `CamposBlocoPid.tsx:59`.

- [ ] **Step 4: `CamposMalhaFuzzy.tsx`** — remover a grade de `sp_lo_lim/sp_hi_lim/out_scale_lo/out_scale_hi` (`:99-104`) e renderizar `<CamposShellMalha tipo="fuzzy_loop" …/>` no lugar. O select de Ação e os ganhos do kernel ficam onde estão.

- [ ] **Step 5: `ModalConfigBloco.tsx`**

- Calcular uma vez `const portasLigadas = portasComAresta(edges, no.id)` (memoizado por `edges`/`no.id`).
- `case "pid_loop"`: `onAplicar({ ...no, data: { ...montarDadosPidLoop(no.data, campos), label } }, execOrder);` — apagar o comentário "o modal v1 aplica só rótulo e ordem".
- `case "fuzzy_loop"`: partir de `montarDadosShellMalha(no.data, campos, "fuzzy_loop")` e aplicar por cima `label`, `n_loops`, `ke`, `kde`, `ku`, `tf_de`, `fll` como hoje; remover as leituras inline de `direct_acting`, `sp_*_lim` e `out_scale_*` (agora vêm do shell) e o comentário "`permitted`/`normal` seguem nos defaults do servidor".
- Render: `{no.type === "pid_loop" && <CamposPidMalha dados={no.data} portasLigadas={portasLigadas} />}` e passar `portasLigadas` a `CamposMalhaFuzzy`.

- [ ] **Step 6: `nodes/index.tsx`** — em `NoPidLoop`, acrescentar `<LinhaResumo rotulo="Ação" valor={data.direct_acting ? "direta" : "reversa"} />` como primeira linha e atualizar o comentário de doc do componente.

- [ ] **Step 7: Verificar**

Run: `cd frontend && npm run typecheck && npm run test:unit && npm run build`
Expected: tudo verde.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/features/flows/config frontend/src/features/flows/nodes/index.tsx
git commit -m "feat(flows): modal do PID Malha com todos os parâmetros e campos de shell no Fuzzy Malha (RF-641, RF-642, RF-644)"
```

---

### Task 5: Lógica pura da tela MALHA (RF-645, RF-646)

**Files:**
- Create: `frontend/src/features/loop/malhaLogica.ts`
- Test: `frontend/src/features/loop/malhaLogica.check.ts`

**Interfaces:**
- Consumes: `LoopNodeOut`, `LoopState` de `./types`; `LoopHistoryResponse` = `components["schemas"]["LoopHistoryResponse"]` (acrescentar o re-export em `./types.ts`); `FuzzyHistoryResponse` de `../fuzzy/types`; `LeituraViva` de `../trend/bordaViva`; `LIMITE_PENAS` de `../trend/trendTheme`.
- Produces:
  - `export type EstadoCanal = "conectando" | "aberto" | "reconectando" | "sessao_invalida";` (a Tarefa 6 troca por `import type { EstadoConexaoCanal }` de `CanalAoVivo`)
  - `export function resolverSelecao(loops: readonly LoopNodeOut[], flow: string | null, bloco: string | null): LoopNodeOut | null` — a malha que casa com a URL; sem casar, a primeira; lista vazia ⇒ `null`.
  - `export interface CondicaoMalha { readonly canal: EstadoCanal; readonly estadoFlow: string | undefined; readonly estado: LoopState | undefined; readonly tsBase: string | undefined }` — `tsBase` é o `ts` do `LoopState` que estava retido quando a página montou ou o canal reabriu (`undefined` se não havia).
  - `export function malhaAoVivo(c: CondicaoMalha): boolean` — os quatro termos da spec §6.
  - `export function motivoSemEstado(canal: EstadoCanal, estadoFlow: string | undefined, desejado: "running" | "stopped" | undefined): string` — texto do aviso quando não está ao vivo; `desejado` é o `desired_state` REST do flow e **só** escolhe o texto (pode estar velho; por isso fica fora do predicado).
  - `export function percentualBarra(valor: number | null, minimo: number, maximo: number): number` — 0…100.
  - `export interface VarMalha { readonly id: string; readonly rotulo: string }`
  - `export function varsMalha(nLoops: number): VarMalha[]` — ids da API, canal 0 sem sufixo.
  - `export function penasIniciais(vars: readonly VarMalha[]): string[]` — PV/SP/OUT do canal 0.
  - `export function leiturasVivasMalha(estados: readonly (LoopState | undefined)[]): ReadonlyMap<string, LeituraViva>`
  - `export function semNulos(resposta: LoopHistoryResponse): FuzzyHistoryResponse`

- [ ] **Step 1: Escrever os testes que falham**

```ts
const A: LoopNodeOut = { flow_id: 1, flow_name: "F", block_id: "a", label: "A", type: "pid_loop", n_loops: 1 };
const B: LoopNodeOut = { ...A, flow_id: 2, block_id: "b", label: "B" };
const ESTADO: LoopState = {
  ts: "2026-11-27T12:00:00Z", target: "auto", actual: "auto", permitted: ["oos", "man", "auto"],
  pv: 152.3, pv_ok: true, sp: 150, out: 37.5, u_pct: 37.5, man_out: 0,
  hi_limited: false, lo_limited: false, diag: {}, channel: 0,
};

test("seleção: casa com a URL; sem casar cai na primeira; lista vazia é null", () => {
  expect(resolverSelecao([A, B], "2", "b")).toBe(B);
  expect(resolverSelecao([A, B], null, null)).toBe(A);
  expect(resolverSelecao([A, B], "9", "apagado")).toBe(A); // Review Focus 3
  expect(resolverSelecao([A, B], "1", "b")).toBe(A);       // flow e bloco de malhas diferentes
  expect(resolverSelecao([], "1", "a")).toBeNull();
});

const VIVO: CondicaoMalha = { canal: "aberto", estadoFlow: "running", estado: ESTADO, tsBase: undefined };

test("ao vivo: cada um dos quatro termos derruba sozinho", () => {
  expect(malhaAoVivo(VIVO)).toBe(true);
  expect(malhaAoVivo({ ...VIVO, canal: "reconectando" })).toBe(false); // socket caiu
  expect(malhaAoVivo({ ...VIVO, estadoFlow: "stopped" })).toBe(false);
  expect(malhaAoVivo({ ...VIVO, estadoFlow: undefined })).toBe(false);
  expect(malhaAoVivo({ ...VIVO, estado: undefined })).toBe(false);
});

test("quadro retido de antes da montagem ou da reconexão não é ao vivo; o seguinte é", () => {
  expect(malhaAoVivo({ ...VIVO, tsBase: ESTADO.ts })).toBe(false);
  const novo = { ...ESTADO, ts: "2026-11-27T12:00:01Z" };
  expect(malhaAoVivo({ ...VIVO, estado: novo, tsBase: ESTADO.ts })).toBe(true);
});

test("aviso de sem-estado diz a causa: canal, flow parado, falha ou espera do primeiro quadro", () => {
  expect(motivoSemEstado("reconectando", "running", "running")).toBe(ROTULO_CONEXAO.reconectando);
  expect(motivoSemEstado("conectando", "running", "running")).toBe(ROTULO_CONEXAO.conectando);
  expect(motivoSemEstado("sessao_invalida", "running", "running")).toBe("Sessão expirada — entre novamente");
  expect(motivoSemEstado("aberto", "running", "stopped")).toBe("Flow parado — sem estado ao vivo");
  expect(motivoSemEstado("aberto", "stopped", "running")).toBe("Flow parado — sem estado ao vivo");
  expect(motivoSemEstado("aberto", "failed", "running")).toBe("Flow em falha — sem estado ao vivo");
  expect(motivoSemEstado("aberto", "running", "running")).toBe("Aguardando estado ao vivo da malha…");
  expect(motivoSemEstado("aberto", undefined, undefined)).toBe("Aguardando estado ao vivo da malha…");
});

test("barra usa a faixa do bloco, não 0–100", () => {
  expect(percentualBarra(150, 50, 250)).toBe(50);
  expect(percentualBarra(12, 4, 20)).toBe(50);
});

// Review Focus 4
test("barra nunca sai de 0–100 nem vira NaN", () => {
  expect(percentualBarra(300, 50, 250)).toBe(100);
  expect(percentualBarra(-5, 50, 250)).toBe(0);
  expect(percentualBarra(null, 50, 250)).toBe(0);
  expect(percentualBarra(10, 100, 100)).toBe(0);
  expect(percentualBarra(10, 100, 0)).toBe(0);
  expect(percentualBarra(Number.NaN, 0, 100)).toBe(0);
});

test("penas: ids da API por canal e pré-seleção do canal 0", () => {
  expect(varsMalha(1)).toEqual([
    { id: "pv", rotulo: "PV" }, { id: "sp", rotulo: "SP" }, { id: "out", rotulo: "OUT" },
  ]);
  const tres = varsMalha(3);
  expect(tres.map((v) => v.id)).toEqual(["pv", "sp", "out", "pv:1", "sp:1", "out:1", "pv:2", "sp:2", "out:2"]);
  expect(tres[3].rotulo).toBe("PV · canal 2");
  expect(tres[0].rotulo).toBe("PV · canal 1");
  // Review Focus 5: 9 variáveis, teto de 6 penas — só o canal 0 nasce marcado
  expect(penasIniciais(tres)).toEqual(["pv", "sp", "out"]);
});

test("ponta viva: uma leitura por pena e canal; PV nula fica de fora, PV sem qualidade entra", () => {
  const c1 = { ...ESTADO, channel: 1, pv: null, sp: 10, out: 20 };
  const vivas = leiturasVivasMalha([{ ...ESTADO, pv_ok: false }, undefined, c1]);
  expect(vivas.get("pv")).toEqual({ ts: ESTADO.ts, v: 152.3 });
  expect(vivas.get("sp:1")).toEqual({ ts: ESTADO.ts, v: 10 });
  expect(vivas.has("pv:1")).toBe(false);
});

// Review Focus 5
test("histórico: amostra nula some com o seu carimbo, nunca vira zero", () => {
  const limpo = semNulos({
    mode: "raw", start: "2026-11-27T11:00:00Z", end: "2026-11-27T12:00:00Z",
    series: [
      { var_id: "pv", t: ["t1", "t2", "t3"], v: [1, null, 3] },
      { var_id: "sp", t: ["t1"], v: [null] },
    ],
  });
  expect(limpo.series).toEqual([
    { var_id: "pv", t: ["t1", "t3"], v: [1, 3] },
    { var_id: "sp", t: [], v: [] },
  ]);
  expect(limpo.mode).toBe("raw");
});
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd frontend && npx playwright test -c playwright.unit.config.ts src/features/loop/malhaLogica.check.ts`
Expected: FAIL — módulo inexistente.

- [ ] **Step 3: Implementar `malhaLogica.ts`**

Funções puras, sem React. Notas que os testes não determinam sozinhos:
- `ROTULO_CONEXAO` vem de `../flows/useFlowStatus` (`:46`) — reusar os textos, não reescrever. Ele é chaveado por `"aberta"` (feminino), e o canal usa `"aberto"`: por isso `motivoSemEstado` mapeia caso a caso em vez de indexar direto. Ordem de precedência do aviso: canal fora → falha (`estadoFlow === "failed"`) → flow parado (`desejado` ou `estadoFlow` em `stopped`) → espera.
- `varsMalha`: canal `i` (0-based) tem sufixo `""` se `i === 0`, senão `":" + i`; rótulo sem canal quando `nLoops === 1`, senão `"<VAR> · canal <i+1>"`.
- `leiturasVivasMalha`: indexa pelo `channel` do próprio `LoopState` (não pela posição no array).
- `semNulos` descarta `v_min`/`v_max` (o gráfico não os usa) e devolve objeto atribuível a `FuzzyHistoryResponse`, o que permite reusar `montarMatrizFuzzy`/`resumirSeriesFuzzy`/`mesclarHistoricoFuzzyVivo` de `../fuzzy/historicoFuzzy` na Tarefa 7 sem duplicá-los.

- [ ] **Step 4: Rodar e ver passar**

Run: `cd frontend && npx playwright test -c playwright.unit.config.ts src/features/loop && npm run typecheck`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/loop/malhaLogica.ts frontend/src/features/loop/malhaLogica.check.ts frontend/src/features/loop/types.ts
git commit -m "feat(loop): decisões puras da tela MALHA — seleção, ao vivo, escala e penas (RF-645, RF-646)"
```

---

### Task 6: Tela MALHA — seletor, faceplate e sintonia (RF-645)

**Files:**
- Modify: `frontend/src/app/CanalAoVivo.tsx:80` (`export type EstadoConexaoCanal`)
- Modify: `frontend/src/features/loop/LoopOperatePage.tsx` (vira página: seletor + layout)
- Create: `frontend/src/features/loop/FaceplateMalha.tsx`, `frontend/src/features/loop/SintoniaVigente.tsx`
- Modify: `frontend/src/features/loop/malhaLogica.ts` (trocar `EstadoCanal` local por `import type { EstadoConexaoCanal }`)

**Interfaces:**
- Consumes: `resolverSelecao`, `malhaAoVivo`, `motivoSemEstado`, `percentualBarra` (Tarefa 5); `useLoops`, `useLoopConfig`, `rotuloLoop` (`./useLoops`); `useAssinatura`, `useCanalAoVivo` (`canal.estado`, `canal.flowStatus: ReadonlyMap<number, FlowStatus>`, `canal.loopStates`); molde de seleção em `features/fuzzy/FuzzyOperatePage.tsx:288-330`.
- Produces:
  - `export function FaceplateMalha(props: { flowId: number; blockId: string; config: LoopDetailOut | undefined; estados: readonly (LoopState | undefined)[]; aoVivo: boolean; motivoSemEstado: string })`
  - `export function SintoniaVigente(props: { config: LoopDetailOut })`
  - `LoopOperatePage` continua sendo o export usado por `app/router.tsx:11`.
  - `MODOS_LOOP`, `ModoLoop`, `podeComandar` mudam para `malhaLogica.ts` (ninguém fora de `features/loop` os importa).

Sem teste de componente (política da casa); as decisões já estão cobertas na Tarefa 5. Prova: typecheck + build + roteiro B-ML-03…05 da Tarefa 8.

- [ ] **Step 1: Exportar o tipo** em `CanalAoVivo.tsx:80` (só a palavra `export`) e usá-lo em `malhaLogica.ts`.

Run: `cd frontend && npm run typecheck && npx playwright test -c playwright.unit.config.ts src/features/loop`
Expected: verde. Se exportar o tipo criar ciclo de import que quebre o build, PARE e reporte (mesma condição de parada do plano advisor/013).

- [ ] **Step 2: `LoopOperatePage.tsx` — seleção que funciona (defeitos D3, D4)**

- `const [searchParams, setSearchParams] = useSearchParams();`
- `const selecionada = resolverSelecao(loops.data ?? [], searchParams.get("flow"), searchParams.get("bloco"));`
- Efeito: quando `loops.isSuccess`, há malhas e a URL não aponta exatamente para `selecionada`, `setSearchParams({ flow, bloco }, { replace: true })`.
- Cabeçalho sempre visível: título "Malha" + `<Select data-testid="loop-combobox" aria-label="Malha" value={chave da selecionada} onChange={… setSearchParams({ flow, bloco })}>` com uma `<option>` por malha (`rotuloLoop`). O ramo `loop-selecao` e a `<option value="">Escolha a malha…` desaparecem.
- Estados carregando/erro/vazio mantidos como hoje.
- Corpo, com `key={chave}` na malha selecionada: `useAssinatura({ loop_state: [chave], flow_status: [flowId] })`, `useLoopConfig`, `useFlow(flowId)` (de `../flows/useFlows`, para `desired_state`) e `estados` por canal (como hoje, `canal.loopStates.get("<flow>/<bloco>:<i>")`).
- `tsBase`: um `useRef<string | undefined>` que guarda o `ts` do primeiro estado definido **no momento** em que o corpo monta e, por um efeito dependente de `canal.estado`, de novo a cada vez que o canal passa a `"aberto"`. É só captura — a decisão é de `malhaAoVivo`.
- `const estadoFlow = canal.flowStatus.get(flowId)?.state`; `aoVivo = malhaAoVivo({ canal: canal.estado, estadoFlow, estado: primeiro estado definido, tsBase })`; `motivo = motivoSemEstado(canal.estado, estadoFlow, flow.data?.desired_state)`. O array `estados` é montado com `useMemo` sobre `canal.loopStates` — ele é dependência da ponta viva da tendência (Tarefa 7) e não pode ser recriado a cada render.
- Layout: `FaceplateMalha` em cima; abaixo, lado a lado, `SintoniaVigente` (quando `config.data` existe) e o espaço da tendência (Tarefa 7).

- [ ] **Step 3: `FaceplateMalha.tsx` (defeitos D5, D6)**

Recebe o JSX do atual `LoopResolvido` (badges, botoeira, seções por canal com `Barra`/`EscritaValor`, heatmap, erro de comando), com estas mudanças:
- `!aoVivo`: aviso `<p data-testid="loop-sem-estado">{motivoSemEstado}</p>`; badges ALVO/REAL e valores das barras mostram "—"; botoeira e `EscritaValor` com `disabled`. Nenhum valor de `estados` é renderizado. O texto vem da página (`motivoSemEstado`, Tarefa 5).
- Com `!aoVivo` e sem nenhum estado, desenha uma seção de canal por `config.n_loops` (ou 1) com barras vazias — a tela não fica em branco. O ramo `loop-aguardando` desaparece.
- `Barra` passa a calcular a largura com `percentualBarra`; PV e SP com `config.sp_lo_lim`/`sp_hi_lim`, OUT com `config.out_scale_lo`/`out_scale_hi` (fallback 0/100 enquanto `config` carrega).
- `EscritaValor` de SP: `min/max` = limites de SP; de OUT (%): `min/max` = `config.out_lo_lim`/`out_hi_lim`.
- `data-testid` existentes preservados (`loop-faceplate`, `loop-badge-*`, `loop-botoeira`, `loop-modo-*`, `loop-canal-*`, `loop-barra-*`, `loop-escrita-*`, `loop-erro-comando`).

- [ ] **Step 4: `SintoniaVigente.tsx` (defeito D7)**

Cartão `data-testid="loop-sintonia"`, título "Sintonia vigente (leitura)", `<dl>` com:
- PID (`"kc" in config.tuning`): KC, TI, TD (0 ⇒ "desligada"), N, BETA, GAMMA, GAP_BAND (0 ⇒ "desligada"), GAP_GAIN.
- Fuzzy: KE, KDE (0 ⇒ "desligada"), KU (%/s), TF_DE (s).
- Ambos: Ação (direta/reversa), Limites de SP (`sp_lo_lim … sp_hi_lim`), Limites de saída (`out_lo_lim … out_hi_lim` %), Escala de OUT (`out_scale_lo … out_scale_hi`).

- [ ] **Step 5: Verificar**

Run: `cd frontend && npm run typecheck && npm run test:unit && npm run build`
Expected: tudo verde.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/app/CanalAoVivo.tsx frontend/src/features/loop
git commit -m "fix(loop): tela MALHA com seletor que funciona, escalas reais do bloco e estado ao vivo honesto (RF-645)"
```

---

### Task 7: Tendência PV/SP/OUT (RF-646)

**Files:**
- Create: `frontend/src/features/loop/useHistoryLoop.ts`, `frontend/src/features/loop/TrendMalha.tsx`
- Modify: `frontend/src/features/loop/LoopOperatePage.tsx` (monta o `TrendMalha`)

**Interfaces:**
- Consumes: `varsMalha`, `penasIniciais`, `leiturasVivasMalha`, `semNulos` (Tarefa 5); `montarMatrizFuzzy`, `resumirSeriesFuzzy`, `mesclarHistoricoFuzzyVivo`, `escalasPorId` de `../fuzzy/historicoFuzzy`; peças de `../trend/` usadas por `features/fuzzy/TrendFuzzy.tsx`.
- Produces:
  - `export function useHistoryLoop(flowId: number, blockId: string, varIds: readonly string[], janelaSegundos: number, fimEpochS: number | null = null): UseQueryResult<LoopHistoryResponse>` — `GET /api/history/loop?flow_id=&block_id=&var_ids=&start=&end=`, `queryKey ["history-loop", …]`, polling de 5000 ms desligado com a janela congelada; cópia estrutural de `features/fuzzy/useHistoryFuzzy.ts`.
  - `export function TrendMalha(props: { flowId: number; blockId: string; nLoops: number; estados: readonly (LoopState | undefined)[]; aoVivo: boolean })`

- [ ] **Step 1: Criar `useHistoryLoop.ts`** (espelho de `useHistoryFuzzy.ts`, trocando rota, chave e tipo).

- [ ] **Step 2: Criar `TrendMalha.tsx`**

Mesma estrutura, controles e comportamento de `features/fuzzy/TrendFuzzy.tsx` (leia o arquivo inteiro e espelhe; **não** o edite), com estas substituições:
- variáveis = `varsMalha(nLoops)`; pré-seleção = `penasIniciais(...)`; identidade da pena = `VarMalha.id` (onde o fuzzy usa `port`); EU sempre vazia;
- histórico = `useHistoryLoop(...)`, passado por `semNulos` **antes** de mesclar/montar;
- ponta viva = `useBordaViva(leiturasVivasMalha(estados), janelaSegundos, deslizante.aoVivo && aoVivo)` — com o flow parado ou o canal fora, nada entra na borda;
- chave de escalas = `` `ottima.loop.escalas.v1:${flowId}/${blockId}` ``;
- todo `data-testid` com prefixo `loop-trend` no lugar de `fuzzy-trend` (`loop-trend`, `loop-trend-mode`, `loop-trend-selector`, `loop-trend-option`, `loop-trend-legend`, `loop-trend-legend-item`, `loop-trend-export-csv`, `loop-trend-janela-voltar|avancar|reset`); atributo `data-var-id` no lugar de `data-var-port`;
- janela default 1800 s; teto `LIMITE_PENAS`.

- [ ] **Step 3: Montar na página** — `<TrendMalha … />` ao lado de `SintoniaVigente`, **fora** de qualquer condição de `aoVivo` (o histórico aparece com o flow parado).

- [ ] **Step 4: Verificar**

Run: `cd frontend && npm run typecheck && npm run test:unit && npm run build`
Expected: tudo verde.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/loop
git commit -m "feat(loop): tendência PV/SP/OUT na tela MALHA (RF-646)"
```

---

### Task 8: Documentação, gates completos e roteiro de navegador

**Files:**
- Modify: `docs/specs/SPEC_PID_with_SHELL.md` (§8), `docs/specs/SPEC_FUZZY_with_SHELL.md` (§8), `CLAUDE.md` (seção Comandos), `docs/specs/SPEC_MALHA_CONFIG_E_OPERACAO.md` (linha de Status)

- [ ] **Step 1: Ponteiros nas specs** (autorizados pela spec §8)

- `SPEC_PID_with_SHELL.md` §8, item "Faceplate": acrescentar "Config completa no editor e tela MALHA: ver `SPEC_MALHA_CONFIG_E_OPERACAO.md` (RF-641…646)."
- `SPEC_FUZZY_with_SHELL.md` §8, item "Sintonia": a mesma frase.
- `SPEC_MALHA_CONFIG_E_OPERACAO.md`: Status → "implementada (plano `docs/superpowers/plans/2026-11-27-malha-config-e-operacao.md`)".

- [ ] **Step 2: `CLAUDE.md`** — no bloco de comentários das telas (junto de "Página MALHA: /operacao/loop?flow=<id>&bloco=fm"), uma nota: a tela MALHA (RF-645/646) tem seletor sempre visível (`loop-combobox`), abre na primeira malha, mostra sintonia e tendência com o flow parado e só comanda "ao vivo" (canal aberto + flow rodando); `data-testid`: `loop-*` e `loop-trend-*`; o modal do PID Malha/Fuzzy Malha edita a config inteira (RF-641/642) com `config-<campo>`.

- [ ] **Step 3: Gates herméticos, todos**

```bash
uv run ruff check . && uv run ruff format --check .
uv run pytest packages/ottima-core -q
cd frontend && npm run test:unit && npm run typecheck && npm run build
cd frontend && npm run generate:contracts && git diff --exit-code
```
Expected: tudo verde; o `git diff --exit-code` sem saída (nada gerado mudou).

- [ ] **Step 4: Roteiro de navegador B-ML-01…06** (spec §7)

Pré-requisitos: stack no ar com o bundle novo (`cd deploy && docker compose -f docker-compose.yml -f docker-compose.e2e.yml up -d --build --no-deps frontend`) e um projeto ativo com um flow contendo um PID Malha e um Fuzzy Malha (`scripts/setup-malha-fuzzy.py` cria o fuzzy; acrescentar um `pid_loop` pelo canvas). Executar com a ferramenta de browser, uma captura por passo, e registrar o resultado de cada um dos seis passos da spec. **Um passo que não pôde ser executado é relatado como não executado, nunca como aprovado.**

- [ ] **Step 5: Commit**

```bash
git add docs/specs CLAUDE.md
git commit -m "docs: ponteiros para a spec dos blocos malha e nota da tela MALHA no CLAUDE.md"
```

---

## Cobertura da spec

| Spec / RF | Tarefa |
|---|---|
| §5.1 espelho de defaults + trava · RF-643 | 1 |
| §5.2 tipos e normalizador · RF-643 · D2 | 2 |
| §5.3 regras do formulário (rampa, permitted, recorte fuzzy) | 3 |
| §5.3 seções e campos · §5.4 nó · RF-641, 642, 644 · D1 | 4 |
| §6 seleção, ao vivo, escalas · §6.1 ids e nulos | 5 |
| §6 tela · RF-645 · D3–D7 | 6 |
| §6.1 tendência · RF-646 | 7 |
| §7 gates e roteiro · §8 documentação | 8 |

Fora deste plano, por decisão da spec §3: sintonia pela tela de operação, `MAX_DT`, layout do nó por classe de porta, `mode` na tendência, refatoração de `TrendFuzzy`/`MpcModal`, spec Playwright nova. O plano advisor/013 segue dono do "ao vivo" das telas MPC e FUZZY.
