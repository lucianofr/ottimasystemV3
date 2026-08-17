import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { Tooltip } from "../../../components/ui/tooltip";
import type { ParModeloMpc, TipoLinhaMpc, VariaveisMpc } from "../graph";
import { AJUDA_MODELOS } from "./ajudaMpc";
import { nomeCampoModelo, parModeloDoFormulario, paramsPadraoLinha } from "./mpcLogic";

const ROTULO_PARAM: Record<string, string> = {
  K: "K (ganho)",
  tau1: "τ1",
  tau2: "τ2",
  theta: "θ (tempo morto)",
  Ki: "Ki (ganho integrador)",
};

type LinhaModelo = { id: string; nome: string; kind: TipoLinhaMpc };
type ColunaModelo = { id: string; nome: string };

function parAtual(
  modelos: Record<string, Record<string, ParModeloMpc>>,
  linha: string,
  coluna: string,
): ParModeloMpc {
  return modelos[linha]?.[coluna] ?? { enabled: false, params: {} };
}

interface Props {
  variaveis: VariaveisMpc;
  modelos: Record<string, Record<string, ParModeloMpc>>;
  aoMudar: (modelos: Record<string, Record<string, ParModeloMpc>>) => void;
}

/** Aba Modelos (spec F4 §7.3, §2.1-2): matriz linhas (CVs+Restrições) × colunas (MVs+DVs).
 *  `enabled` é controlado (decide se os params aparecem, como o `enabled` do TFS); os params
 *  em si ficam não-controlados — a forma exata (`K/tau1/tau2/theta` ou `Ki/theta`) segue o
 *  `kind` vigente da LINHA (definido na aba Variáveis) e é lida pelo par linha/coluna no
 *  Aplicar (`parModeloDoFormulario`). */
export function TabModels({ variaveis, modelos, aoMudar }: Props) {
  const linhas: LinhaModelo[] = [
    ...variaveis.cvs.map((cv) => ({ id: cv.id, nome: cv.name || cv.id, kind: cv.kind })),
    ...variaveis.constraints.map((co) => ({ id: co.id, nome: co.name || co.id, kind: co.kind })),
  ];
  const colunas: ColunaModelo[] = [
    ...variaveis.mvs.map((mv) => ({ id: mv.id, nome: mv.name || mv.id })),
    ...variaveis.dvs.map((dv) => ({ id: dv.id, nome: dv.name || dv.id })),
  ];

  if (linhas.length === 0 || colunas.length === 0) {
    return (
      <div data-testid="mpc-tab-modelos" className="text-xs text-fg-muted">
        Cadastre ao menos 1 MV e 1 CV/Restrição na aba Variáveis para montar a matriz.
      </div>
    );
  }

  function mudarPar(
    linha: string,
    coluna: string,
    mudanca: Partial<ParModeloMpc>,
  ): void {
    const par = parAtual(modelos, linha, coluna);
    aoMudar({
      ...modelos,
      [linha]: { ...modelos[linha], [coluna]: { ...par, ...mudanca } },
    });
  }

  return (
    <div data-testid="mpc-tab-modelos" className="overflow-auto">
      <table className="w-full border-collapse text-xs">
        <thead>
          <tr>
            <th className="plaqueta px-2 py-1 text-left text-fg-muted">Linha \ Coluna</th>
            {colunas.map((coluna) => (
              <th key={coluna.id} className="plaqueta px-2 py-1 text-left text-fg-muted">
                {coluna.nome}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {linhas.map((linha) => (
            <tr key={linha.id} className="border-t border-border align-top">
              <th className="plaqueta px-2 py-2 text-left text-fg-muted">
                {linha.nome}
                <span className="ml-1 text-[10px] normal-case text-fg-muted">
                  ({linha.kind === "integrating" ? "IOPDT" : "SOPDT"})
                </span>
              </th>
              {colunas.map((coluna) => {
                const par = parAtual(modelos, linha.id, coluna.id);
                const nomesParam = Object.keys(paramsPadraoLinha(linha.kind));
                return (
                  <td
                    key={coluna.id}
                    data-testid={`mpc-cell-${linha.id}-${coluna.id}`}
                    className="space-y-1 px-2 py-2"
                  >
                    <label className="flex items-center gap-1.5">
                      <input
                        type="checkbox"
                        data-testid={`mpc-cell-enabled-${linha.id}-${coluna.id}`}
                        checked={par.enabled}
                        onChange={(evento) => {
                          const habilitado = evento.target.checked;
                          const formulario = evento.target.form;
                          if (!habilitado && par.enabled && formulario !== null) {
                            // Captura os params ainda montados no DOM neste instante —
                            // antes do React desmontar os campos — para o recheck não cair
                            // nos defaults do `kind` (fix final, Important; mesma classe de
                            // bug da revisão 4.3, aqui via checkbox em vez de troca de aba).
                            const capturado = parModeloDoFormulario(
                              par,
                              linha.id,
                              coluna.id,
                              linha.kind,
                              new FormData(formulario),
                            );
                            mudarPar(linha.id, coluna.id, { enabled: false, params: capturado.params });
                          } else {
                            mudarPar(linha.id, coluna.id, { enabled: habilitado });
                          }
                        }}
                        className="h-3.5 w-3.5 accent-[var(--color-accent)]"
                      />
                      <Tooltip content={AJUDA_MODELOS.habilitado} stopClick>Habilitado</Tooltip>
                    </label>
                    {par.enabled &&
                      nomesParam.map((param) => (
                        <div key={param} className="space-y-0.5">
                          <Label htmlFor={`${linha.id}-${coluna.id}-${param}`} tooltip={AJUDA_MODELOS[param]}>
                            {ROTULO_PARAM[param] ?? param}
                          </Label>
                          <Input
                            id={`${linha.id}-${coluna.id}-${param}`}
                            name={nomeCampoModelo(linha.id, coluna.id, param)}
                            type="text"
                            inputMode="decimal"
                            className="process-value h-7"
                            defaultValue={String(
                              par.params[param] ?? paramsPadraoLinha(linha.kind)[param],
                            )}
                          />
                        </div>
                      ))}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
