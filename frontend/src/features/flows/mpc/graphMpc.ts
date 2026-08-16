import { inteiroSimples, numero, objeto, texto } from "../graph";
import type {
  AcaoFalhaLinha,
  AcaoFalhaMv,
  FaixaMpc,
  LimitesMpc,
  ObjetivoCv,
  ObjetivoMv,
  ObjetivoRestricao,
  ParModeloMpc,
  PidMv,
  TipoLinhaMpc,
  ValoresModoPid,
  VariaveisMpc,
  VariavelCv,
  VariavelDv,
  VariavelMv,
  VariavelRestricao,
} from "../graph";

/**
 * Leitura do `graph_json` do config MPC (espelha o esqueleto normativo da spec F4 §2.1).
 * Movido de `graph.ts` (revisão final, Important — débito de tamanho, CLAUDE.md 800 linhas)
 * para um módulo irmão, mesma separação que `mpcLogic.ts` já faz para a lógica do formulário.
 * Move pura: nenhum comportamento mudou, só o arquivo. `graph.ts` continua a única chamadora
 * (`lerNo`, caso "mpc") e reexporta as duas funções que precisa (`lerVariaveisMpc`,
 * `lerModelosMpc`); as demais ficam privadas deste módulo.
 */

function lerLimitesMpc(bruto: unknown): LimitesMpc {
  const cru = objeto(bruto) ?? {};
  return { min: numero(cru.min, 0), max: numero(cru.max, 0) };
}

function lerFaixaMpc(bruto: unknown): FaixaMpc {
  const cru = objeto(bruto) ?? {};
  return { low: numero(cru.low, 0), high: numero(cru.high, 0) };
}

/** `range` da DV é opcional (spec §4.2-2), ao contrário do de Restrição: `null` explícito,
 *  ausente, ou qualquer valor que não seja objeto viram `null` — DV salva antes da F6 carrega
 *  sem faixa (compatibilidade retroativa), igual à leitura de `output_eu` em `graph.ts`. */
function lerFaixaMpcOuNull(bruto: unknown): FaixaMpc | null {
  const cru = objeto(bruto);
  return cru === null ? null : { low: numero(cru.low, 0), high: numero(cru.high, 0) };
}

function lerModoValoresMpc(bruto: unknown): ValoresModoPid {
  const cru = objeto(bruto) ?? {};
  return { auto: inteiroSimples(cru.auto, 0), target: inteiroSimples(cru.target, 0) };
}

function lerPidMv(bruto: unknown): PidMv | null {
  const cru = objeto(bruto);
  if (cru === null) return null;
  return {
    write_tag_id: inteiroSimples(cru.write_tag_id, 0),
    target_mode:
      cru.target_mode === "cas" || cru.target_mode === "rout" ? cru.target_mode : "rcas",
    mode_cmd_tag_id: inteiroSimples(cru.mode_cmd_tag_id, 0),
    mode_read_tag_id: Number.isInteger(cru.mode_read_tag_id) ? (cru.mode_read_tag_id as number) : null,
    readback_tag_id: inteiroSimples(cru.readback_tag_id, 0),
    mode_values: lerModoValoresMpc(cru.mode_values),
  };
}

/** `readback_tag_id` da MV direta é opcional (TD-003): ausente, não-inteiro, ou `0`
 *  (sentinela de "sem tag", mesmo valor que os campos de tag do `pid` usam quando não há
 *  seleção) viram `null` — MV salva antes desta tarefa carrega sem readback, mesmo padrão
 *  retroativo documentado em `lerFaixaMpcOuNull`. */
function lerReadbackTagIdMv(bruto: unknown): number | null {
  const valor = inteiroSimples(bruto, 0);
  return valor === 0 ? null : valor;
}

function lerTipoLinhaMpc(bruto: unknown): TipoLinhaMpc {
  return bruto === "integrating" ? "integrating" : "selfreg";
}

/** Whitelist + default `"none"` (mesmo padrão de `lerTipoLinhaMpc`): config salvo antes da
 *  feature não tem a chave, e um valor fora do vocabulário nunca deve atravessar para o
 *  formulário — `"none"` reproduz exatamente o comportamento de antes. */
function lerObjetivoMv(bruto: unknown): ObjetivoMv {
  return bruto === "maximize" || bruto === "minimize" || bruto === "psv" || bruto === "equalize"
    ? bruto
    : "none";
}

function lerObjetivoCv(bruto: unknown): ObjetivoCv {
  return bruto === "maximize" ||
    bruto === "minimize" ||
    bruto === "observe_limit" ||
    bruto === "target" ||
    bruto === "psv"
    ? bruto
    : "none";
}

function lerObjetivoRestricao(bruto: unknown): ObjetivoRestricao {
  return bruto === "maximize" || bruto === "minimize" ? bruto : "none";
}

/** `psv` é opcional (`number | null`), mesmo padrão de `lerFaixaMpcOuNull`: ausente, `null`
 *  explícito, ou não-número finito viram `null` — config salvo antes da feature carrega sem
 *  valor preferido. */
function lerPsvMv(bruto: unknown): number | null {
  return typeof bruto === "number" && Number.isFinite(bruto) ? bruto : null;
}

/** Whitelist + default `"no_action"` (mesmo padrão de `lerObjetivoMv`): config salvo antes
 *  da feature não tem a chave, e um valor fora do vocabulário nunca atravessa para o form. */
function lerAcaoFalhaMv(bruto: unknown): AcaoFalhaMv {
  return bruto === "shed_local" || bruto === "manual" ? bruto : "no_action";
}

function lerAcaoFalhaLinha(bruto: unknown): AcaoFalhaLinha {
  return bruto === "shed_local" ||
    bruto === "manual" ||
    bruto === "simulate_manual" ||
    bruto === "simulate_shed_local"
    ? bruto
    : "no_action";
}

/** Inteiro positivo ou `null` (tags opcionais: `remote_sp_tag_id`, `local_shed_mode`) —
 *  mesmo padrão de `lerReadbackTagIdMv`: ausente/sentinela 0 vira `null`. */
function lerInteiroOpcional(bruto: unknown): number | null {
  return typeof bruto === "number" && Number.isInteger(bruto) && bruto > 0 ? bruto : null;
}

/** `number | null` livre (`sp_range_pct`): ausente/null/não-finito → `null`. */
function lerNumeroOpcional(bruto: unknown): number | null {
  return typeof bruto === "number" && Number.isFinite(bruto) ? bruto : null;
}

/** `track_sp` default `true` (RF-612): config salvo antes do campo rastreia PV — só o
 *  `false` explícito desliga. */
function lerTrackSp(bruto: unknown): boolean {
  return bruto !== false;
}

function lerVariavelMv(bruto: unknown): VariavelMv | null {
  const cru = objeto(bruto);
  if (cru === null) return null;
  const id = texto(cru.id, "");
  if (id === "") return null;
  return {
    id,
    name: texto(cru.name, ""),
    eu: texto(cru.eu, ""),
    // RF-609/613: defaults retrocompat (config salvo antes do lote não tem as chaves) —
    // os mesmos do `MvVar` do servidor: "" / 0 / 100 / "no_action" / null.
    description: texto(cru.description, ""),
    zero: numero(cru.zero, 0),
    span: numero(cru.span, 100),
    limits: lerLimitesMpc(cru.limits),
    // `max_rate` NÃO tem default no `MvVar` do servidor — é required. O `0` aqui é sentinela
    // deliberado de config INCOMPLETO, não espelho de default: `validarConfigMpc` recusa
    // (`max_rate > 0`) e `validate.py::_check_mpc_numbers` recusa igual no save, então o
    // sentinela nunca chega à planta. Fabricar uma taxa plausível esconderia o config
    // incompleto; `0` é justamente o valor de MV congelada, que o Resumo barra na cara.
    max_rate: numero(cru.max_rate, 0),
    // TD-007: `graph_json` salvo antes desta tarefa não tem os campos — `0`/`1` são os
    // mesmos defaults do `MvVar` do servidor (`du_min: 0.0`, `move_weight: 1.0`).
    du_min: numero(cru.du_min, 0),
    move_weight: numero(cru.move_weight, 1),
    initial_value: numero(cru.initial_value, 0),
    operating_point: numero(cru.operating_point, 0),
    readback_tag_id: lerReadbackTagIdMv(cru.readback_tag_id),
    pid: lerPidMv(cru.pid),
    objective: lerObjetivoMv(cru.objective),
    psv: lerPsvMv(cru.psv),
    fail_action: lerAcaoFalhaMv(cru.fail_action),
    local_shed_mode: lerInteiroOpcional(cru.local_shed_mode),
  };
}

function lerVariavelCv(bruto: unknown): VariavelCv | null {
  const cru = objeto(bruto);
  if (cru === null) return null;
  const id = texto(cru.id, "");
  if (id === "") return null;
  return {
    id,
    name: texto(cru.name, ""),
    eu: texto(cru.eu, ""),
    description: texto(cru.description, ""),
    zero: numero(cru.zero, 0),
    span: numero(cru.span, 100),
    kind: lerTipoLinhaMpc(cru.kind),
    tss: numero(cru.tss, 0),
    weight: numero(cru.weight, 0),
    sp_limits: lerLimitesMpc(cru.sp_limits),
    priority: inteiroSimples(cru.priority, 1),
    objective: lerObjetivoCv(cru.objective),
    // RF-611..615: defaults retrocompat — 0 (degrau) / true (rastreia) / no_action / 60 s /
    // null (livre) / null (SP local) reproduzem o comportamento anterior bit a bit.
    traj_tau_s: numero(cru.traj_tau_s, 0),
    track_sp: lerTrackSp(cru.track_sp),
    fail_action: lerAcaoFalhaLinha(cru.fail_action),
    fail_timeout_s: numero(cru.fail_timeout_s, 60),
    sp_range_pct: lerNumeroOpcional(cru.sp_range_pct),
    remote_sp_tag_id: lerInteiroOpcional(cru.remote_sp_tag_id),
  };
}

function lerVariavelRestricao(bruto: unknown): VariavelRestricao | null {
  const cru = objeto(bruto);
  if (cru === null) return null;
  const id = texto(cru.id, "");
  if (id === "") return null;
  return {
    id,
    name: texto(cru.name, ""),
    eu: texto(cru.eu, ""),
    description: texto(cru.description, ""),
    zero: numero(cru.zero, 0),
    span: numero(cru.span, 100),
    kind: lerTipoLinhaMpc(cru.kind),
    tss: numero(cru.tss, 0),
    range: lerFaixaMpc(cru.range),
    priority: inteiroSimples(cru.priority, 1),
    objective: lerObjetivoRestricao(cru.objective),
    fail_action: lerAcaoFalhaLinha(cru.fail_action),
    fail_timeout_s: numero(cru.fail_timeout_s, 60),
  };
}

function lerVariavelDv(bruto: unknown): VariavelDv | null {
  const cru = objeto(bruto);
  if (cru === null) return null;
  const id = texto(cru.id, "");
  if (id === "") return null;
  return {
    id,
    name: texto(cru.name, ""),
    eu: texto(cru.eu, ""),
    zero: numero(cru.zero, 0),
    span: numero(cru.span, 100),
    range: lerFaixaMpcOuNull(cru.range),
    operating_point: numero(cru.operating_point, 0),
  };
}

function lerListaMpc<T>(bruto: unknown, ler: (item: unknown) => T | null): T[] {
  const itens: unknown[] = Array.isArray(bruto) ? bruto : [];
  return itens.map(ler).filter((item): item is T => item !== null);
}

export function lerVariaveisMpc(bruto: unknown): VariaveisMpc {
  const cru = objeto(bruto) ?? {};
  return {
    mvs: lerListaMpc(cru.mvs, lerVariavelMv),
    cvs: lerListaMpc(cru.cvs, lerVariavelCv),
    constraints: lerListaMpc(cru.constraints, lerVariavelRestricao),
    dvs: lerListaMpc(cru.dvs, lerVariavelDv),
  };
}

function lerParModeloMpc(bruto: unknown): ParModeloMpc {
  const cru = objeto(bruto) ?? {};
  const paramsBrutos = objeto(cru.params) ?? {};
  const params: Record<string, number> = {};
  for (const [chave, valor] of Object.entries(paramsBrutos)) {
    if (typeof valor === "number" && Number.isFinite(valor)) params[chave] = valor;
  }
  return { enabled: cru.enabled === true, params };
}

export function lerModelosMpc(bruto: unknown): Record<string, Record<string, ParModeloMpc>> {
  const linhas = objeto(bruto) ?? {};
  const modelos: Record<string, Record<string, ParModeloMpc>> = {};
  for (const [idLinha, colunasBrutas] of Object.entries(linhas)) {
    const colunas = objeto(colunasBrutas) ?? {};
    const lidas: Record<string, ParModeloMpc> = {};
    for (const [idColuna, par] of Object.entries(colunas)) lidas[idColuna] = lerParModeloMpc(par);
    modelos[idLinha] = lidas;
  }
  return modelos;
}
