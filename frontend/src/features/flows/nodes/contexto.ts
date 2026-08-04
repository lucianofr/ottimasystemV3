import { createContext, useContext } from "react";

import type { TagOut } from "../../../lib/api";

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
