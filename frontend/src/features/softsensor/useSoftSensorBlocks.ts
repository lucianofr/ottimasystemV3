import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { api } from "../../lib/api";
import { precisaAcompanhar } from "./treino";
import type { SoftSensorBlockOut } from "./types";

export const CHAVE_BLOCOS_SENSOR_VIRTUAL = ["softsensor", "blocks"] as const;

/** Instante da última ativação bem-sucedida DESTE cliente (`useActivateModel`): abre a janela de
 *  polling rápido de `precisaAcompanhar`. Módulo, não estado de React: `/blocks` (AppShell) e
 *  `/models` (a página) leem o mesmo valor, e nenhum render depende dele. */
let ativadoEmMs: number | null = null;

export function registrarAtivacao(agoraMs: number = Date.now()): void {
  ativadoEmMs = agoraMs;
}

export function ultimaAtivacaoMs(): number | null {
  return ativadoEmMs;
}

/**
 * Blocos de sensor virtual do projeto ativo (SV-1, `GET /api/softsensor/blocks`). A lista
 * vazia é o que esconde o item "Coleta e treino" da navegação (`AppShell`). Atualiza a cada 2 s
 * só enquanto um candidato aquece ou logo após a ativação deste cliente (`precisaAcompanhar`): é
 * assim que "aquecendo" vira "em uso" na tela, sem depender do WebSocket. Pedido sem candidato
 * não mantém o polling — pode durar para sempre e este hook roda em toda página.
 */
export function useSoftSensorBlocks(): UseQueryResult<SoftSensorBlockOut[]> {
  return useQuery({
    queryKey: CHAVE_BLOCOS_SENSOR_VIRTUAL,
    queryFn: () => api<SoftSensorBlockOut[]>("/api/softsensor/blocks"),
    refetchInterval: (query) =>
      precisaAcompanhar(query.state.data, ativadoEmMs) ? 2000 : false,
  });
}
