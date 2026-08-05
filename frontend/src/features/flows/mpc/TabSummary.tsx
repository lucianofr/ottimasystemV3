import type { ParModeloMpc, VariaveisMpc } from "../graph";
import { validarConfigMpc } from "./mpcLogic";

interface Props {
  variaveis: VariaveisMpc;
  modelos: Record<string, Record<string, ParModeloMpc>>;
  multiplier: number;
  tsFlowSegundos: number;
}

/**
 * Aba Resumo (spec F4 §7.3): espelho client-side das regras §2.2 aplicáveis sem a tabela de
 * tags do servidor. Lista erros bloqueantes e avisos em prosa pt-BR — nunca código — a partir
 * do mesmo `variaveis`/`modelos`/`multiplier` que o `aplicar()` do `MpcModal` usa para montar
 * o `DadosMpc`: uma tentativa de Aplicar com erro te traz para cá com o estado já sincronizado
 * (`variaveisDoFormulario`/`modelosDoFormulario` rodaram antes do bloqueio), então o que esta
 * aba mostra é exatamente o que impediu o salvar.
 */
export function TabSummary({ variaveis, modelos, multiplier, tsFlowSegundos }: Props) {
  const { erros, avisos } = validarConfigMpc(variaveis, modelos, multiplier, tsFlowSegundos);

  return (
    <div data-testid="mpc-tab-resumo" className="space-y-4">
      <section className="space-y-2">
        <h3 className="plaqueta text-xs text-fg-muted">Erros bloqueantes ({erros.length})</h3>
        {erros.length === 0 ? (
          <p data-testid="mpc-resumo-sem-erros" className="text-xs text-fg">
            Nenhum erro — a configuração pode ser salva.
          </p>
        ) : (
          <ul data-testid="mpc-resumo-erros" className="space-y-1 text-xs">
            {erros.map((erro) => (
              <li key={erro} className="text-alarm">
                <span className="plaqueta mr-2 text-[10px]">Erro</span>
                {erro}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="space-y-2">
        <h3 className="plaqueta text-xs text-fg-muted">Avisos ({avisos.length})</h3>
        {avisos.length === 0 ? (
          <p className="text-xs text-fg-muted">Nenhum aviso.</p>
        ) : (
          <ul data-testid="mpc-resumo-avisos" className="space-y-1 text-xs">
            {avisos.map((aviso) => (
              <li key={aviso} className="text-warn">
                <span className="plaqueta mr-2 text-[10px]">Aviso</span>
                {aviso}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
