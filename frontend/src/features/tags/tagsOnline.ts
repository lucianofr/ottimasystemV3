/**
 * Valor online e quality da tabela de Tags: tradução pura de `opc.values` (RF-204) para as
 * duas células da linha. Nada de estado nem de React aqui — a página só desenha o que sai.
 *
 * `direction` não entra na conta: o worker lê todo node que o servidor declara legível,
 * inclusive o de uma tag `w` (`polling.py::_declares_read_access`) — o valor dela é o
 * comando EM VIGOR, grandeza distinta do readback de posição real (RF-604). Quem não tem
 * série é o comando write-only, e isso se manifesta como ausência de leitura, não como
 * direção.
 */

import type { LeituraTag } from "../../app/CanalAoVivo";
import { formatarNumero } from "../flows/useFlowStatus";

/** Rótulos pt-BR da quality do barramento (`bus.py:39-40`: 0=good, 1=uncertain, 2=bad). */
const ROTULO_QUALITY: Record<number, string> = { 0: "Boa", 1: "Incerta", 2: "Ruim" };

/** Sem leitura no ar: comando write-only, tag que ainda não publicou, socket fora do ar. */
const SEM_DADO = "—";

export type ToneQuality = "success" | "warn" | "alarm" | "neutral";

/** Tom por quality. Fora de 0/1 é não-confiável: `status_to_quality`
 *  (`polling.py`) já fecha o contrato em 0/1/2 e manda reservado para 2, então
 *  inteiro estranho vem de worker fora do contrato — trata como alarme, não como novidade. */
const TONE_QUALITY: Record<number, ToneQuality> = { 0: "success", 1: "warn" };

export interface CelulaOnline {
  /** `null` = sem dado. A página desenha o travessão SEM a EU ao lado (a Regra do Número
   *  Tabular pede EU junto do número; travessão não é número). */
  valor: string | null;
  quality: string;
  tone: ToneQuality;
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
export function celulaOnline(leitura: LeituraTag | undefined, aoVivo: boolean): CelulaOnline {
  if (leitura === undefined || !aoVivo) {
    return { valor: null, quality: SEM_DADO, tone: "neutral" };
  }
  return {
    valor: leitura.v === null ? null : formatarNumero(leitura.v),
    quality: ROTULO_QUALITY[leitura.quality] ?? String(leitura.quality),
    tone: TONE_QUALITY[leitura.quality] ?? "alarm",
  };
}
