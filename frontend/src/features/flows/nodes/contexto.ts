import { createContext, useContext } from "react";

import type { TagOut } from "../../../lib/api";
import type { PortValue, PortsPorBloco } from "../useFlowStatus";

/**
 * Tags do projeto ativo, para os nós mostrarem nome/EU da tag configurada.
 *
 * Vive em contexto e nunca em `data`: o servidor rejeita chave desconhecida dentro de `data`
 * (422), então nada derivado ou de interface pode ser guardado ali.
 */
export const ContextoTags = createContext<ReadonlyMap<number, TagOut>>(new Map());

export function useTagsDoEditor(): ReadonlyMap<number, TagOut> {
  return useContext(ContextoTags);
}

export type PortasDoBloco = Readonly<Record<string, PortValue>>;

/**
 * Valores ao vivo das portas (RF-305). Mesmo motivo do contexto de tags para não morarem em
 * `data`, e mais um: `data` é o que o save envia, e valor de processo não é config.
 *
 * `ativo` só liga depois da primeira varredura recebida — sem replay (§5.3), flow parado
 * nunca publica, e um canvas de edição não deve encher de "aguardando dado" por isso.
 */
export interface ValoresAoVivo {
  ativo: boolean;
  ports: PortsPorBloco;
}

const SEM_VALORES: ValoresAoVivo = { ativo: false, ports: {} };

export const ContextoValores = createContext<ValoresAoVivo>(SEM_VALORES);

/** `Ts` do flow (segundos), para os nós de filtro decidirem se `tau` caiu abaixo do limiar de
 *  passagem direta sem o engenheiro precisar dividir de cabeça (TD-011). Mesmo motivo do
 *  contexto de tags: é derivado do flow, nunca guardado em `data` do nó. */
export const ContextoTsFlow = createContext<number>(0);

export function useTsFlowDoEditor(): number {
  return useContext(ContextoTsFlow);
}

/** `null` = canvas sem dado ao vivo; `{}` = ao vivo, mas este bloco ainda não publicou. */
export function useValoresDoBloco(blockId: string): PortasDoBloco | null {
  const vivo = useContext(ContextoValores);
  return vivo.ativo ? (vivo.ports[blockId] ?? {}) : null;
}
