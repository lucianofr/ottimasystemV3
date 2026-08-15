/**
 * Valor online e quality da tabela de Tags: tradução pura de `opc.values` (RF-204) para as
 * duas células da linha. Nada de estado nem de React aqui — a página só desenha o que sai.
 */

import type { LeituraTag } from "../../app/CanalAoVivo";
import { formatarNumero } from "../flows/useFlowStatus";
import type { Direcao } from "./useTags";

/** Rótulos pt-BR da quality do barramento (`bus.py:39-40`: 0=good, 1=uncertain, 2=bad). */
const ROTULO_QUALITY: Record<number, string> = { 0: "Boa", 1: "Incerta", 2: "Ruim" };

/** Sem leitura no ar: tag de escrita, tag que nunca publicou, socket fora do ar. */
const SEM_DADO = "—";

export type ToneQuality = "success" | "warn" | "alarm" | "neutral";

/** Tom por quality. Fora de 0/1 é não-confiável: `status_to_quality`
 *  (`subscriptions.py:45-55`) já fecha o contrato em 0/1/2 e manda reservado para 2, então
 *  inteiro estranho vem de worker fora do contrato — trata como alarme, não como novidade. */
const TONE_QUALITY: Record<number, ToneQuality> = { 0: "success", 1: "warn" };

export interface CelulaOnline {
  /** `null` = sem dado. A página desenha o travessão SEM a EU ao lado (a Regra do Número
   *  Tabular pede EU junto do número; travessão não é número). */
  valor: string | null;
  quality: string;
  tone: ToneQuality;
}

/** Tags a assinar em `opc_values`: só `direction === "r"` publica no barramento — monitored
 *  item é leitura (`subscriptions.py:147-150`) e o heartbeat só republica tag `r`
 *  (`heartbeat.py:108-109`). Assinar uma tag `w` gastaria slot da fila do `/ws` (8,
 *  drop-oldest) esperando um valor que nunca vem. */
export function tagIdsDeLeitura(
  linhas: readonly { id: number; direction: Direcao }[],
): number[] {
  return linhas.filter((linha) => linha.direction === "r").map((linha) => linha.id);
}

/**
 * Célula de valor + célula de quality de uma linha.
 *
 * `aoVivo === false` (socket em `conectando`/`reconectando`) descarta a leitura em mão de
 * propósito: `tagValues` congela no último lote recebido e exibir aquele número como se fosse
 * a leitura de agora é a falha perigosa desta tela. Quality ruim, ao contrário, NÃO apaga o
 * número — o heartbeat republica o último valor conhecido sob `quality=2`
 * (`heartbeat.py:92-105`), e a severidade vai ao lado do valor (Regra do Canal Redundante).
 */
export function celulaOnline(
  direction: Direcao,
  leitura: LeituraTag | undefined,
  aoVivo: boolean,
): CelulaOnline {
  if (direction !== "r" || leitura === undefined || !aoVivo) {
    return { valor: null, quality: SEM_DADO, tone: "neutral" };
  }
  return {
    valor: leitura.v === null ? null : formatarNumero(leitura.v),
    quality: ROTULO_QUALITY[leitura.quality] ?? String(leitura.quality),
    tone: TONE_QUALITY[leitura.quality] ?? "alarm",
  };
}
