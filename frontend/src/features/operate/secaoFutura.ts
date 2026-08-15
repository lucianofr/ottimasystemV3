import type uPlot from "uplot";

import type { TemaTrend } from "../trend/trendTheme";

/**
 * Seção futura do trend de operação (spec F5 §7.4-6; plano de melhorias Fase 2 tarefa 2.2):
 * o eixo de tempo sempre reserva espaço para o horizonte de predição (Np × Ts_mpc) quando a
 * vista está ao vivo — a seção existe MESMO fora de AUTO (é o ponto da entrega: o operador vê
 * onde a predição apareceria assim que o bloco for para AUTO; a predição em si já é publicada
 * e desenhada pelo overlay existente, `trendOperacao.ts::montarOverlayPrevisao` — aqui é só
 * apresentação). Pausado/deslizado no tempo, a vista é só histórica: não faz sentido projetar
 * um futuro a partir de um instante que não é "agora".
 *
 * Lógica pura (`calcularRangeXOperacao`, testada em `secaoFutura.check.ts`, regra global 3:
 * asserts leem dados, nunca pixel) + um plugin de desenho no molde de `pluginLinhaAgora`
 * (`TrendOperacao.tsx`): lê de refs para atualizar a cada redesenho sem recriar a instância
 * do uPlot.
 */

export interface ParametrosRangeXOperacao {
  /** `null` = ao vivo (`useJanelaDeslizante`). */
  readonly fimEpochS: number | null;
  readonly agoraEpochS: number;
  readonly janelaSegundos: number;
  /** `Np × Ts_mpc` (segundos) — tamanho da seção futura quando ao vivo. */
  readonly horizonteFuturoS: number;
}

/**
 * Extremos do eixo x das duas seções. Ao vivo, o eixo sempre reserva o horizonte futuro
 * (mesmo sem predição — a seção existe, só fica vazia até o bloco ir para AUTO). Pausado, a
 * vista termina exatamente no fim escolhido pelo operador, sem seção futura.
 */
export function calcularRangeXOperacao(
  parametros: ParametrosRangeXOperacao,
): readonly [number, number] {
  const { fimEpochS, agoraEpochS, janelaSegundos, horizonteFuturoS } = parametros;
  if (fimEpochS === null) {
    return [agoraEpochS - janelaSegundos, agoraEpochS + horizonteFuturoS];
  }
  return [fimEpochS - janelaSegundos, fimEpochS];
}

/**
 * Âncora do divisor "agora" (linha-cursor + sombreamento da seção futura). Política única, com
 * dois escritores no componente (o render e o tique de 1 s): duas cópias divergiam — o render
 * reescrevia o relógio a cada quadro novo enquanto o tique se recusava a andar sob zoom manual,
 * e qualquer redesenho (dado novo, `setSize`) teleportava a linha e a sombra "Previsão" para o
 * relógio de agora sobre um eixo deliberadamente congelado, chegando a empurrar o divisor para
 * fora da vista.
 *
 * - Fora do ao vivo (janela deslizada): não existe "agora" na vista — `null`.
 * - Com zoom manual: a âncora é a que estava valendo quando o operador congelou a vista. O
 *   recorte não segue o relógio (é o que o aviso da tela diz), então o divisor também não.
 * - Ao vivo e sem recorte: o relógio de parede (B-5) — a linha anda a cada tique, mesmo sem
 *   dado novo chegando.
 */
export function ancoraDivisorAgora(
  anterior: number | null,
  aoVivo: boolean,
  zoomAtivo: boolean,
  agoraEpochS: number,
): number | null {
  if (!aoVivo) return null;
  if (zoomAtivo) return anterior;
  return agoraEpochS;
}

const TEXTO_SEM_PREDICAO = "Sem predição — MPC fora de AUTO";

/**
 * Plugin de desenho: sombreia `x ∈ [agora, x_max]`, rotula "Histórico"/"Previsão" e, sem
 * predição em vista ao vivo, escreve o placeholder centrado na região futura. Não é série —
 * não compete por espaço no teto de penas nem precisa de Y-range próprio (mesmo racional de
 * `pluginLinhaAgora`). `agoraRef` é a mesma âncora do divisor "agora" (`TrendOperacao.tsx`):
 * quando não há predição, o chamador já a substitui pelo relógio (requisito 5 do plano) — este
 * plugin só desenha o que a ref disser.
 */
export function pluginSecaoFutura(
  agoraRef: { readonly current: number | null },
  semPredicaoRef: { readonly current: boolean },
  tema: TemaTrend,
): uPlot.Plugin {
  return {
    hooks: {
      drawClear: (u: uPlot) => {
        const agora = agoraRef.current;
        if (agora === null) return;
        const x0 = u.valToPos(agora, "x", true);
        const x1 = u.bbox.left + u.bbox.width;
        if (!Number.isFinite(x0) || !Number.isFinite(x1) || x1 <= x0) return;
        const { ctx } = u;
        ctx.save();
        ctx.fillStyle = tema.secaoFutura;
        ctx.fillRect(x0, u.bbox.top, x1 - x0, u.bbox.height);
        ctx.restore();
      },
      draw: (u: uPlot) => {
        const agora = agoraRef.current;
        if (agora === null) return;
        const x0 = u.valToPos(agora, "x", true);
        const x1 = u.bbox.left + u.bbox.width;
        if (!Number.isFinite(x0) || !Number.isFinite(x1)) return;
        const { ctx } = u;
        ctx.save();
        ctx.fillStyle = tema.texto;
        ctx.font = `11px ${tema.mono}`;
        ctx.textBaseline = "top";
        ctx.textAlign = "left";
        ctx.fillText("Histórico", u.bbox.left + 4, u.bbox.top + 4);
        if (x1 > x0) {
          ctx.textAlign = "right";
          ctx.fillText("Previsão", x1 - 4, u.bbox.top + 4);
        }
        if (semPredicaoRef.current && x1 > x0) {
          ctx.textAlign = "center";
          ctx.fillText(TEXTO_SEM_PREDICAO, (x0 + x1) / 2, u.bbox.top + u.bbox.height / 2);
        }
        ctx.restore();
      },
    },
  };
}
