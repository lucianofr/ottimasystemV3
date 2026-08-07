import type { ConnectionOut, EventOut, FlowOut } from "../../lib/api";
import type { components } from "../../lib/api-types";

/** Projeção do bloco `mpc` (`GET /api/operate/mpcs`, spec §4.1-1) — só o necessário para
 *  compor o rótulo de origem; sem tipo próprio em `lib/api.ts` porque só esta página consome. */
export type MpcNodeOut = components["schemas"]["MpcNodeOut"];

/** Filtros combináveis da página (spec F5 §7.5): `start`/`end` chegam crus do
 *  `<input type="datetime-local">` (sem timezone — mesma convenção "sem offset vale UTC" do
 *  backend, `routers/events.py:_as_utc`). Vazio = sem filtro naquele campo. */
export interface FiltrosEventos {
  severity: EventOut["severity"] | null;
  origin: string | null;
  start: string | null;
  end: string | null;
}

/** Só severidade/origem entram no casamento client-side: período não filtra evento ao vivo
 *  individualmente, ele desliga o prepend inteiro (`temPeriodo`) — a consulta histórica já
 *  aplica `start`/`end` no servidor. */
export function casaFiltros(
  evento: EventOut,
  filtros: Pick<FiltrosEventos, "severity" | "origin">,
): boolean {
  if (filtros.severity !== null && evento.severity !== filtros.severity) return false;
  if (filtros.origin !== null && evento.origin !== filtros.origin) return false;
  return true;
}

/** Qualquer borda de período preenchida vira consulta histórica pura (spec §7.5-2, decisão
 *  A-13): não precisa das duas, uma só já é "não é mais ao vivo". */
export function temPeriodo(filtros: Pick<FiltrosEventos, "start" | "end">): boolean {
  return filtros.start !== null || filtros.end !== null;
}

/** `EventOut` não tem id (schemas/events.py) — chave de dedupe entre o resultado REST e o
 *  buffer ao vivo do WS (mesmo evento chega nos dois quando a página monta com o socket já
 *  aberto). Colisão exigiria ts+origin+mensagem idênticos, que o produtor nunca repete. */
export function chaveEvento(evento: EventOut): string {
  return `${evento.ts}|${evento.origin}|${evento.message}`;
}

export interface EventosVisiveis {
  /** ts desc — recentes (se houver) primeiro, depois o histórico da REST. */
  eventos: readonly EventOut[];
  /** Chaves (`chaveEvento`) que vieram do prepend ao vivo desta função — a UI usa para
   *  desenhar a marca de recém-chegado (spec §7.5-2). */
  recentes: ReadonlySet<string>;
}

/** Combina o histórico paginado (REST, já filtrado no servidor) com o buffer ao vivo do WS
 *  (`CanalAoVivo.eventos`, sempre assinado, mais novo primeiro, sem filtro nenhum aplicado
 *  nele). Com período ativo é consulta histórica pura — sem prepend. Sem período, todo
 *  evento ao vivo que casa severidade/origem e ainda não está no histórico entra no topo. */
export function calcularEventosVisiveis(
  historico: readonly EventOut[],
  aoVivo: readonly EventOut[],
  filtros: FiltrosEventos,
): EventosVisiveis {
  if (temPeriodo(filtros)) return { eventos: historico, recentes: new Set() };

  const chavesHistorico = new Set(historico.map(chaveEvento));
  const recentes = new Set<string>();
  const novos: EventOut[] = [];
  for (const evento of aoVivo) {
    if (!casaFiltros(evento, filtros)) continue;
    const chave = chaveEvento(evento);
    if (chavesHistorico.has(chave) || recentes.has(chave)) continue;
    recentes.add(chave);
    novos.push(evento);
  }
  return { eventos: [...novos, ...historico], recentes };
}

export interface OpcaoOrigem {
  value: string;
  rotulo: string;
}

/** Popula o `<select>` de origem (F5R-24 — a API filtra por igualdade exata, então a UI
 *  nunca pede texto livre): rótulo amigável para flow/mpc/conexão conhecidos, e as origens
 *  distintas do resultado carregado que não caem em nenhuma das 3 fontes (ex. `user:<id>`,
 *  `api`, `recorder`) entram com o próprio valor de origem como rótulo — melhor que
 *  esconder um filtro válido. Ordenado por rótulo (pt-BR) para o operador achar rápido.
 *
 *  Formatos de `origin` replicados aqui (backend é a fonte): `flow:<id>` (`flow_origin`,
 *  `flow-runtime/events.py:70-72`), `flow:<id>/block:<id>` (`mpc_block_origin`, mesmo
 *  arquivo `:75-78`), `conn:<id>` (ex. `opc-worker/connection.py`). */
export function origensConhecidas(
  flows: readonly FlowOut[],
  mpcs: readonly MpcNodeOut[],
  conexoes: readonly ConnectionOut[],
  eventosCarregados: readonly EventOut[],
): OpcaoOrigem[] {
  const rotuloPorValor = new Map<string, string>();
  for (const flow of flows) rotuloPorValor.set(`flow:${String(flow.id)}`, flow.name);
  for (const mpc of mpcs) {
    rotuloPorValor.set(
      `flow:${String(mpc.flow_id)}/block:${mpc.block_id}`,
      `${mpc.flow_name} - ${mpc.name}`,
    );
  }
  for (const conexao of conexoes) {
    rotuloPorValor.set(`conn:${String(conexao.id)}`, conexao.name);
  }
  for (const evento of eventosCarregados) {
    if (!rotuloPorValor.has(evento.origin)) rotuloPorValor.set(evento.origin, evento.origin);
  }
  return Array.from(rotuloPorValor, ([value, rotulo]) => ({ value, rotulo })).sort((a, b) =>
    a.rotulo.localeCompare(b.rotulo, "pt-BR"),
  );
}
