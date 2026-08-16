import type { ReactNode } from "react";

import { Card } from "../../components/ui/card";
import { cn } from "../../lib/cn";
import { FORMATO_VALOR } from "./trendTheme";

/**
 * Module de apresentação da linha de legenda de tendência (ARCH-04): as três telas de trend
 * (engenharia — `TrendPage.tsx`, fuzzy — `TrendFuzzy.tsx`, operação — `LegendaOperacao.tsx`)
 * reescreviam a mesma forma de linha — swatch, rótulo, badges, valor+EU, slot de editor de
 * escala — cada uma a partir de um domínio diferente, com o par valor+EU divergindo por
 * acidente de reescrita (o próprio achado da auditoria). Aqui mora a parte genuinamente
 * idêntica entre as três: o Card/linha que as envolve, a lista de badges e — o centro da
 * decisão — o par valor+EU (mesma política de formatação `FORMATO_VALOR`, mesmo "—" para
 * ausência, mesmas larguras de coluna, mesmo toggle de cor apagada).
 *
 * O que NÃO mora aqui, de propósito: a identificação da linha (swatch + rótulo + qualquer
 * controle). Trend e fuzzy desenham um `<span>` estático escolhido por ciclo de 6 classes
 * Tailwind (`CLASSES_PENA`); operação desenha um `<button aria-current>` clicável (foca o
 * eixo Y), precedido de um checkbox, com cor explícita por variável (`atribuirCoresPenas`) e
 * um padrão pontilhado só na pena de SP (`faixaPontilhadaSp`) — inclusive a FORMA do swatch
 * difere (`h-1` reto nas duas primeiras, `h-1.5 rounded-pill` na de operação). Achatar
 * swatch+rótulo+interação num shape só exigiria props que só a legenda de operação usa
 * (checkbox, aria-current, indicador "Eixo Y") — o saco de flags que este achado pede para
 * evitar (deletion test: mover JSX sem concentrar decisão não é candidato). Cada tela continua
 * dona da própria identificação via o slot `identificacao`; este module só padroniza o que
 * sobra depois dela.
 */

export interface BadgeLegenda {
  readonly testId?: string;
  readonly texto: string;
  readonly className: string;
}

export interface ValorEuLegenda {
  readonly valor: number | null;
  readonly eu: string;
  readonly muted: boolean;
  readonly testIdValor?: string;
  readonly testIdEu?: string;
}

export interface LinhaLegenda {
  readonly chave: string;
  readonly testId: string;
  readonly dataAttrs?: Readonly<Record<string, string>>;
  readonly className: string;
  readonly identificacao: ReactNode;
  readonly badges?: readonly BadgeLegenda[];
  readonly valorEu?: ValorEuLegenda;
  readonly filhoEscala?: ReactNode;
}

export interface PainelLegendaTrendProps {
  readonly testId: string;
  readonly linhas: readonly LinhaLegenda[];
}

/** Valor da legenda (ARCH-04): as três telas escreviam o mesmo
 *  `valor === null ? "—" : FORMATO_VALOR.format(valor)` — fonte única aqui. */
export function formatarValorLegenda(valor: number | null): string {
  return valor === null ? "—" : FORMATO_VALOR.format(valor);
}

export function PainelLegendaTrend({ testId, linhas }: PainelLegendaTrendProps) {
  return (
    <Card data-testid={testId} className="divide-y divide-border">
      {linhas.map((linha) => (
        <div key={linha.chave} data-testid={linha.testId} {...linha.dataAttrs} className={linha.className}>
          {linha.identificacao}
          {linha.badges?.map((badge) => (
            <span key={badge.testId ?? badge.texto} data-testid={badge.testId} className={badge.className}>
              {badge.texto}
            </span>
          ))}
          {linha.valorEu && (
            <>
              <span
                data-testid={linha.valorEu.testIdValor}
                className={cn(
                  "process-value w-28 text-right text-sm",
                  linha.valorEu.muted ? "text-fg-muted" : "text-fg",
                )}
              >
                {formatarValorLegenda(linha.valorEu.valor)}
              </span>
              <span data-testid={linha.valorEu.testIdEu} className="w-12 text-xs text-fg-muted">
                {linha.valorEu.eu}
              </span>
            </>
          )}
          {linha.filhoEscala}
        </div>
      ))}
    </Card>
  );
}
