import type { NoFirstOrder, NoKalman } from "../graph";
import { Campo } from "./CamposComuns";

/**
 * Formulários dos dois blocos de filtro (RF-532/533, ADR-026).
 *
 * Campos não-controlados, lidos no envio por `numeroDoCampo` (aceita vírgula decimal, como
 * o resto do canvas). Nenhum dos dois tem controle discreto que remonte o formulário, então
 * não há estado de modal aqui — ao contrário do TFS, onde `enabled`/`kind` decidem quais
 * parâmetros existem.
 *
 * O campo em si (e o porquê do texto de apoio) mora em `CamposComuns.tsx`, compartilhado
 * com o formulário do PID.
 */

export function CamposFiltroPrimeiraOrdem({ dados }: { dados: NoFirstOrder["data"] }) {
  return (
    <Campo
      id="tau"
      rotulo="Constante de tempo τ (s)"
      valor={dados.tau}
      ajuda="Tempo para a saída alcançar 63% de um degrau na entrada. Maior filtra mais e atrasa mais. Zero (ou abaixo de Ts/10) desliga o filtro: a entrada passa direto."
    />
  );
}

export function CamposFiltroKalman({ dados }: { dados: NoKalman["data"] }) {
  return (
    <div className="grid grid-cols-2 gap-3">
      <Campo
        id="measurement_noise"
        rotulo="Ruído da medição (EU)"
        valor={dados.measurement_noise}
        ajuda="Desvio padrão do ruído de medição, na unidade da tag — a amplitude típica do chiado em torno do valor real (leia num trecho estável do trend). Não pode ser zero: entra no divisor do ganho do filtro. Maior ⇒ filtro confia menos na medição e suaviza mais; menor ⇒ acompanha a medição mais de perto, com mais ruído residual na saída."
      />
      <Campo
        id="process_noise"
        rotulo="Variação por varredura (EU)"
        valor={dados.process_noise}
        ajuda="Desvio padrão da variação esperada do valor real entre duas varreduras, na unidade da tag. Zero assume um valor real constante (só filtra ruído, nunca acompanha mudança). Maior ⇒ acompanha degraus/rampas reais mais rápido, mas suaviza menos; menor ⇒ resposta mais lenta e mais suave."
      />
    </div>
  );
}
