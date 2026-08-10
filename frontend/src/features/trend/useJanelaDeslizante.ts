import { useCallback, useState } from "react";

/**
 * Janela deslizante dos trends (`<` / `>` / Reset) — compartilhada pelas duas telas.
 *
 * `fimEpochS === null` significa AO VIVO: a janela termina em "agora" e o polling continua.
 * Qualquer outro valor congela a vista naquele instante final; quem consome desliga o
 * polling e passa `start = fim − janela` para a API.
 *
 * A lógica de passo é pura e exportada para ser testada sem React.
 */

/** Retenção do histórico no servidor (RF-801): pedir além disso só renderia 422. */
export const RETENCAO_PADRAO_S = 31 * 24 * 3600;

/** Meia janela por clique: o operador continua vendo metade do que já via, então não perde
 *  a referência entre um clique e o próximo. */
export function passoDeslocamento(janelaSegundos: number): number {
  return janelaSegundos / 2;
}

/**
 * Novo fim ao voltar no tempo. Nunca passa do início da retenção (o começo da janela precisa
 * caber dentro dela) nem do presente — com retenção menor que a janela, o piso ficaria à
 * frente de "agora" e o botão de voltar jogaria a vista para o futuro.
 */
export function fimAoVoltar(
  fimAtual: number | null,
  agoraEpochS: number,
  janelaSegundos: number,
  retencaoSegundos: number,
): number {
  const alvo = (fimAtual ?? agoraEpochS) - passoDeslocamento(janelaSegundos);
  const piso = agoraEpochS - retencaoSegundos + janelaSegundos;
  return Math.min(Math.max(alvo, piso), agoraEpochS);
}

/**
 * Novo fim ao avançar. Alcançar (ou ultrapassar) o presente devolve `null`: a vista retoma
 * ao vivo em vez de ficar parada num "agora" que envelhece a cada segundo.
 */
export function fimAoAvancar(
  fimAtual: number | null,
  agoraEpochS: number,
  janelaSegundos: number,
): number | null {
  if (fimAtual === null) return null;
  const alvo = fimAtual + passoDeslocamento(janelaSegundos);
  return alvo >= agoraEpochS ? null : alvo;
}

export interface JanelaDeslizante {
  /** `null` = ao vivo. */
  readonly fimEpochS: number | null;
  readonly aoVivo: boolean;
  readonly voltar: () => void;
  readonly avancar: () => void;
  /** Volta ao vivo. O zoom do uPlot é do chamador: `u.setData(dados, true)` no mesmo clique. */
  readonly reset: () => void;
}

export function useJanelaDeslizante(
  janelaSegundos: number,
  retencaoSegundos: number = RETENCAO_PADRAO_S,
): JanelaDeslizante {
  const [fimEpochS, setFim] = useState<number | null>(null);

  const voltar = useCallback(() => {
    const agora = Date.now() / 1000;
    setFim((fim) => fimAoVoltar(fim, agora, janelaSegundos, retencaoSegundos));
  }, [janelaSegundos, retencaoSegundos]);

  const avancar = useCallback(() => {
    const agora = Date.now() / 1000;
    setFim((fim) => fimAoAvancar(fim, agora, janelaSegundos));
  }, [janelaSegundos]);

  const reset = useCallback(() => {
    setFim(null);
  }, []);

  return { fimEpochS, aoVivo: fimEpochS === null, voltar, avancar, reset };
}
