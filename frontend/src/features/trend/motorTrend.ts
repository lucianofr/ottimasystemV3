import { useCallback, useEffect, useMemo, useRef, type RefObject } from "react";
import uPlot from "uplot";
import "uplot/dist/uPlot.min.css";

/**
 * Casca de instância do uPlot compartilhada pelas três telas de tendência (ADR-030: o trend
 * fuzzy e o de operação reusam a mesma máquina, não reimplementam). O motor é dono do ciclo
 * de vida — criação, `ResizeObserver`, `setData` sem recriar, destruição — e o consumidor
 * fornece só o que de fato varia: como montar as opções, o que conta como ESTRUTURA e quando
 * o dado novo pode re-ranger o eixo.
 *
 * A separação que o motor impõe é a mesma que as três telas já praticavam à mão:
 *
 * - **estrutura** (janela, penas ligadas, escalas manuais, tema, foco): muda ⇒ a instância é
 *   recriada, porque o uPlot pinta no canvas com o que leu na montagem;
 * - **dados vivos**: entram por `setData`, sem recriar — senão o gráfico pisca e o zoom do
 *   operador morre a cada poll.
 *
 * `montarOpcoes` é chamado só na (re)criação, e o motor guarda sempre a ÚLTIMA closure: os
 * valores reativos lidos lá dentro são os do render corrente, não os congelados na criação
 * anterior. Isso remove o pé-de-ouvido antigo ("nunca passe um valor reativo sem colocá-lo na
 * estrutura" fazia o valor congelar); a regra que sobra é a inevitável — para uma mudança
 * APARECER, ela precisa entrar na `estrutura`.
 */
export interface MotorTrendConfig {
  /** Assinatura da estrutura. Mudança recria a instância. */
  readonly estrutura: string;
  readonly altura: number;
  /** Dados vivos. `null` = ainda não há o que plotar; o motor não cria a instância. */
  readonly dados: uPlot.AlignedData | null;
  /**
   * Monta as opções com a largura medida do container. Chamado na (re)criação. Devolva `null`
   * quando o consumidor ainda não tem como montar (payload próprio ausente) — o motor então
   * não cria a instância, e o consumidor não precisa de cast para provar o contrário ao TS.
   */
  readonly montarOpcoes: (largura: number, altura: number) => uPlot.Options | null;
  /**
   * Decide se o `setData` do dado novo re-ranger o eixo. Falso preserva o recorte que o
   * usuário está olhando. As duas telas decidem por caminhos diferentes de propósito: a de
   * engenharia DERIVA o zoom das escalas da instância (`estaZoomadoEmX`), a de operação
   * RASTREIA o zoom num ref próprio, porque o `range` do eixo x roda dentro do `setScale` do
   * próprio arrasto e ler as escalas ali devolveria a janela velha.
   */
  readonly deveRerange: (instancia: uPlot) => boolean;
}

export interface MotorTrend {
  /** Vai no elemento que hospeda o canvas. */
  readonly container: RefObject<HTMLDivElement>;
  /** Instância viva, para quem precisa de imperativo (ex.: `setScale` do tique de 1 s). */
  readonly instancia: RefObject<uPlot | null>;
  /** Reaplica os últimos dados FORÇANDO re-range: é o "Reset layout" das telas. */
  readonly aplicarDadosComRerange: () => void;
}

export function useMotorTrend(config: MotorTrendConfig): MotorTrend {
  const container = useRef<HTMLDivElement>(null);
  const instancia = useRef<uPlot | null>(null);

  // Tudo o que o efeito de criação consome entra por ref: os deps dele são só a estrutura e a
  // altura, então nada além disso pode recriar a instância por acidente.
  const montarOpcoes = useRef(config.montarOpcoes);
  montarOpcoes.current = config.montarOpcoes;
  const dados = useRef(config.dados);
  dados.current = config.dados;
  const deveRerange = useRef(config.deveRerange);
  deveRerange.current = config.deveRerange;

  const { altura } = config;
  // `dados === null` entra na chave de criação porque o motor não cria instância sem dado: sem
  // isso, a tela que começa vazia (operação, antes do primeiro histórico) nunca montaria o
  // gráfico quando o dado chegasse. Regra do motor, não do consumidor — é fácil esquecer.
  const chaveCriacao = `${config.estrutura}|${config.dados === null ? "vazio" : "ok"}`;

  useEffect(() => {
    const alvo = container.current;
    const iniciais = dados.current;
    if (!alvo || iniciais === null) return;
    const opcoes = montarOpcoes.current(alvo.clientWidth, altura);
    if (opcoes === null) return;
    const grafico = new uPlot(opcoes, iniciais, alvo);
    instancia.current = grafico;
    const observador = new ResizeObserver(() => {
      grafico.setSize({ width: alvo.clientWidth, height: altura });
    });
    observador.observe(alvo);
    return () => {
      observador.disconnect();
      grafico.destroy();
      instancia.current = null;
    };
  }, [chaveCriacao, altura]);

  useEffect(() => {
    const grafico = instancia.current;
    if (!grafico || config.dados === null) return;
    grafico.setData(config.dados, deveRerange.current(grafico));
  }, [config.dados]);

  const aplicarDadosComRerange = useCallback(() => {
    const grafico = instancia.current;
    const ultimos = dados.current;
    if (!grafico || ultimos === null) return;
    grafico.setData(ultimos, true);
  }, []);

  return useMemo(
    () => ({ container, instancia, aplicarDadosComRerange }),
    [aplicarDadosComRerange],
  );
}
