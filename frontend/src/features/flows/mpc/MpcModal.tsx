import { useEffect, useRef, useState, type FormEvent } from "react";

import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import type { TagOut } from "../../../lib/api";
import { inteiroDoCampo } from "../config/campos";
import type { DadosMpc, NoMpc, ParModeloMpc, VariaveisMpc } from "../graph";
import { TabGeneral } from "./TabGeneral";
import { TabModels } from "./TabModels";
import { TabVariables } from "./TabVariables";
import {
  parModeloDoFormulario,
  variavelCvDoFormulario,
  variavelDvDoFormulario,
  variavelMvDoFormulario,
  variavelRestricaoDoFormulario,
} from "./mpcLogic";

/** 7 abas do modal MPC, verbatim RF-607 (spec F4 §7.3): as 3 primeiras são a tarefa 4.2; as
 *  4 últimas nascem placeholder aqui e ganham conteúdo na 4.3 — a navegação já cobre as 7. */
const ABAS = [
  { slug: "geral", rotulo: "Geral" },
  { slug: "variaveis", rotulo: "Variáveis" },
  { slug: "modelos", rotulo: "Modelos" },
  { slug: "horizontes", rotulo: "Horizontes" },
  { slug: "restricoes-limites", rotulo: "Restrições & Limites" },
  { slug: "pesos", rotulo: "Pesos" },
  { slug: "resumo", rotulo: "Resumo" },
] as const;
type SlugAba = (typeof ABAS)[number]["slug"];

function AbaPlaceholder({ rotulo }: { rotulo: string }) {
  return (
    <p className="text-xs text-fg-muted">
      Aba {rotulo}: conteúdo entra na tarefa 4.3 (spec F4 §7.3).
    </p>
  );
}

/** Reconstrói a matriz `models` a partir do formulário: cada par habilitado lê seus params
 *  pela forma do `kind` vigente da linha; pares não citados nas listas atuais são descartados
 *  (variável removida na aba Variáveis não deixa lixo na matriz). */
function modelosDoFormulario(
  variaveis: VariaveisMpc,
  modelos: Record<string, Record<string, ParModeloMpc>>,
  dados: FormData,
): Record<string, Record<string, ParModeloMpc>> {
  const linhas = [...variaveis.cvs, ...variaveis.constraints];
  const colunas = [...variaveis.mvs, ...variaveis.dvs];
  const resultado: Record<string, Record<string, ParModeloMpc>> = {};
  for (const linha of linhas) {
    const porColuna: Record<string, ParModeloMpc> = {};
    for (const coluna of colunas) {
      const atual = modelos[linha.id]?.[coluna.id] ?? { enabled: false, params: {} };
      porColuna[coluna.id] = parModeloDoFormulario(
        atual,
        linha.id,
        coluna.id,
        linha.kind,
        dados,
      );
    }
    resultado[linha.id] = porColuna;
  }
  return resultado;
}

function variaveisDoFormulario(variaveis: VariaveisMpc, dados: FormData): VariaveisMpc {
  return {
    mvs: variaveis.mvs.map((mv) => variavelMvDoFormulario(mv, dados, mv.pid !== null)),
    cvs: variaveis.cvs.map((cv) => variavelCvDoFormulario(cv, dados)),
    constraints: variaveis.constraints.map((co) => variavelRestricaoDoFormulario(co, dados)),
    dvs: variaveis.dvs.map((dv) => variavelDvDoFormulario(dv, dados)),
  };
}

interface Props {
  no: NoMpc;
  totalBlocos: number;
  tags: readonly TagOut[];
  tsFlowSegundos: number;
  podeMutar: boolean;
  onAplicar: (no: NoMpc, execOrder: number) => void;
  onFechar: () => void;
}

/**
 * Modal de config do bloco MPC (RF-607, spec F4 §7.3), aberto pelo mesmo mecanismo do modal
 * genérico (dblclique — FlowEditorPage roteia por `no.type`). Estrutura (listas de variáveis,
 * `kind`, presença do `pid`, habilitação da matriz) vive em estado controlado — decide o que
 * renderiza entre abas; nome/EU/números ficam não-controlados, lidos no Aplicar (mesmo padrão
 * do TFS existente, `config/ModalConfigBloco.tsx`).
 */
export function MpcModal({
  no,
  totalBlocos,
  tags,
  tsFlowSegundos,
  podeMutar,
  onAplicar,
  onFechar,
}: Props) {
  const dialogo = useRef<HTMLDialogElement>(null);
  const [aba, setAba] = useState<SlugAba>("geral");
  const [multiplier, setMultiplier] = useState(no.data.multiplier);
  const [variaveis, setVariaveis] = useState<VariaveisMpc>(no.data.variables);
  const [modelos, setModelos] = useState(no.data.models);

  // `main.tsx` monta sob <StrictMode>: em dev o efeito roda duas vezes e `showModal()` num
  // <dialog> já aberto levanta InvalidStateError (mesma nota do modal genérico).
  useEffect(() => {
    const elemento = dialogo.current;
    if (elemento !== null && !elemento.open) elemento.showModal();
  }, []);

  function aplicar(evento: FormEvent<HTMLFormElement>): void {
    evento.preventDefault();
    const campos = new FormData(evento.currentTarget);
    const label = String(campos.get("label") ?? "").trim();
    const execOrder = inteiroDoCampo(campos.get("exec_order"), no.data.exec_order, 1, totalBlocos);
    const name = String(campos.get("mpc_name") ?? "").trim();
    const novasVariaveis = variaveisDoFormulario(variaveis, campos);

    const dados: DadosMpc = {
      exec_order: no.data.exec_order,
      label,
      name,
      multiplier,
      variables: novasVariaveis,
      models: modelosDoFormulario(novasVariaveis, modelos, campos),
    };
    onAplicar({ ...no, data: dados }, execOrder);
    // `close()` explícito (débito m4, spec F4 §8): `onClose` dispara `onFechar`.
    dialogo.current?.close();
  }

  return (
    <dialog
      ref={dialogo}
      onClose={onFechar}
      data-testid="mpc-modal"
      className="modal-bloco max-h-[90vh] w-[min(960px,96vw)] overflow-auto rounded-panel border border-hairline bg-panel p-0 text-fg"
    >
      <form onSubmit={aplicar}>
        <header className="flex items-center justify-between border-b border-hairline bg-well px-4 py-3">
          <h2 className="plaqueta text-sm text-fg">Configurar MPC</h2>
          <span className="process-value text-xs text-fg-muted">{no.id}</span>
        </header>

        <fieldset disabled={!podeMutar} className="space-y-4 p-4">
          {!podeMutar && (
            <p className="text-xs text-fg-muted">
              Somente leitura: a edição do flow é do papel admin.
            </p>
          )}

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label htmlFor="mpc-label">Rótulo</Label>
              <Input
                id="mpc-label"
                name="label"
                data-testid="config-label"
                maxLength={60}
                defaultValue={no.data.label}
                placeholder="MPC"
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="mpc-exec-order">Ordem de execução</Label>
              <Input
                id="mpc-exec-order"
                name="exec_order"
                data-testid="config-exec-order"
                type="number"
                min={1}
                max={totalBlocos}
                className="process-value"
                defaultValue={no.data.exec_order}
              />
            </div>
          </div>

          {/* Navegação das 7 abas em botões (comutador de posição, não iOS toggle —
              DESIGN.md §Shapes/§Don'ts): a aba ativa vira chapa "pressionada". */}
          <nav className="flex flex-wrap gap-1 border-b border-hairline pb-2" aria-label="Abas MPC">
            {ABAS.map((item) => (
              <button
                key={item.slug}
                type="button"
                data-testid={`mpc-tab-${item.slug}`}
                onClick={() => {
                  setAba(item.slug);
                }}
                className={`plaqueta rounded-panel border px-3 py-1.5 text-[11px] transition-colors ${
                  aba === item.slug
                    ? "border-accent bg-well text-fg"
                    : "border-hairline bg-panel text-fg-muted hover:border-accent"
                }`}
              >
                {item.rotulo}
              </button>
            ))}
          </nav>

          <div className="min-h-[280px]">
            {aba === "geral" && (
              <TabGeneral
                nome={no.data.name}
                multiplier={multiplier}
                tsFlowSegundos={tsFlowSegundos}
                aoMudarMultiplier={setMultiplier}
              />
            )}
            {aba === "variaveis" && (
              <TabVariables variaveis={variaveis} aoMudar={setVariaveis} tags={tags} />
            )}
            {aba === "modelos" && (
              <TabModels variaveis={variaveis} modelos={modelos} aoMudar={setModelos} />
            )}
            {aba !== "geral" &&
              aba !== "variaveis" &&
              aba !== "modelos" &&
              (() => {
                const item = ABAS.find((candidata) => candidata.slug === aba);
                return item !== undefined && <AbaPlaceholder rotulo={item.rotulo} />;
              })()}
          </div>
        </fieldset>

        <footer className="flex justify-end gap-2 border-t border-hairline px-4 py-3">
          <Button
            type="button"
            variant="outline"
            data-testid="config-cancelar"
            onClick={() => dialogo.current?.close()}
          >
            {podeMutar ? "Cancelar" : "Fechar"}
          </Button>
          {podeMutar && (
            <Button type="submit" data-testid="config-aplicar">
              Aplicar
            </Button>
          )}
        </footer>
      </form>
    </dialog>
  );
}
