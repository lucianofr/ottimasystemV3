import { inteiroSimples, numero, objeto, texto } from "../graph";
import type {
  FaixaMpc,
  LimitesMpc,
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

function lerVariavelMv(bruto: unknown): VariavelMv | null {
  const cru = objeto(bruto);
  if (cru === null) return null;
  const id = texto(cru.id, "");
  if (id === "") return null;
  return {
    id,
    name: texto(cru.name, ""),
    eu: texto(cru.eu, ""),
    limits: lerLimitesMpc(cru.limits),
    du_max: numero(cru.du_max, 0),
    initial_value: numero(cru.initial_value, 0),
    operating_point: numero(cru.operating_point, 0),
    readback_tag_id: lerReadbackTagIdMv(cru.readback_tag_id),
    pid: lerPidMv(cru.pid),
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
    kind: lerTipoLinhaMpc(cru.kind),
    tss: numero(cru.tss, 0),
    weight: numero(cru.weight, 0),
    sp_limits: lerLimitesMpc(cru.sp_limits),
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
    kind: lerTipoLinhaMpc(cru.kind),
    tss: numero(cru.tss, 0),
    range: lerFaixaMpc(cru.range),
    priority: inteiroSimples(cru.priority, 1),
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
