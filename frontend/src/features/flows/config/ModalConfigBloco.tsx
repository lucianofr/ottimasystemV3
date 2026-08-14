import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";

import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { Select } from "../../../components/ui/select";
import type { TagOut } from "../../../lib/api";
import { ROTULO_TIPO } from "../../tags/useTags";
import {
  MAX_FLL_LENGTH,
  MAX_PORTAS_FUZZY,
  MAX_PORTAS_SCRIPT,
  podarOutputEu,
  portasScript,
  ROTULO_BLOCO,
  type BlocoNode,
  type DadosTfs,
  type NoEscrita,
  type NoFuzzy,
  type NoLeitura,
  type NoMpc,
  type NoScript,
} from "../graph";
import { inteiroDoCampo, matrizDoFormulario, numeroDoCampo } from "./campos";
import { CamposFiltroKalman, CamposFiltroPrimeiraOrdem } from "./CamposFiltros";
import { CamposTfs } from "./CamposTfs";

const OPCOES_PORTAS = Array.from({ length: MAX_PORTAS_SCRIPT + 1 }, (_, i) => i);
const OPCOES_PORTAS_FUZZY = Array.from({ length: MAX_PORTAS_FUZZY }, (_, i) => i + 1);

function CamposTag({
  dados,
  direcao,
  tags,
}: {
  dados: NoLeitura["data"] | NoEscrita["data"];
  direcao: "r" | "w";
  tags: readonly TagOut[];
}) {
  // Seletor filtrado por direção e pelo projeto ativo (a lista já chega recortada por projeto).
  const disponiveis = tags.filter((tag) => tag.direction === direcao);
  return (
    <div className="space-y-1">
      <Label htmlFor="tag_id">Tag</Label>
      <Select id="tag_id" name="tag_id" data-testid="config-tag" defaultValue={dados.tag_id ?? ""}>
        <option value="">Selecione uma tag…</option>
        {disponiveis.map((tag) => (
          <option key={tag.id} value={tag.id}>
            {tag.name} · {ROTULO_TIPO[tag.data_type]}
            {tag.eu ? ` · ${tag.eu}` : ""}
          </option>
        ))}
      </Select>
      {disponiveis.length === 0 && (
        <p className="text-xs text-warn-fg">
          Nenhuma tag de {direcao === "r" ? "leitura" : "escrita"} cadastrada no projeto ativo.
        </p>
      )}
    </div>
  );
}

/** Tab indenta em vez de sair do campo (spec F3 §6.2: sem editor de código de terceiros). */
function indentarComTab(evento: KeyboardEvent<HTMLTextAreaElement>): void {
  if (evento.key !== "Tab" || evento.shiftKey || evento.ctrlKey || evento.altKey || evento.metaKey) {
    return;
  }
  evento.preventDefault();
  const campo = evento.currentTarget;
  campo.setRangeText("    ", campo.selectionStart, campo.selectionEnd, "end");
}

/** Lê o EU de cada porta do FormData; texto livre e opcional — porta ausente ou em branco
 *  não entra no objeto (spec §4.1-6: porta sem unidade fica sem chave, como `Tag.eu`). */
function outputEuDoFormulario(campos: FormData, portas: readonly string[]): Record<string, string> {
  const saida: Record<string, string> = {};
  for (const porta of portas) {
    const bruto = campos.get(`output_eu_${porta}`);
    if (typeof bruto === "string" && bruto.trim() !== "") saida[porta] = bruto.trim();
  }
  return saida;
}

function CamposScript({
  dados,
  nOutputs,
  aoMudarNOutputs,
}: {
  dados: NoScript["data"];
  nOutputs: number;
  aoMudarNOutputs: (n_outputs: number) => void;
}) {
  const portasEu = portasScript("OUT", nOutputs);
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-1">
          <Label htmlFor="n_inputs">Entradas (IN1..INn)</Label>
          <Select id="n_inputs" name="n_inputs" data-testid="config-n-inputs" defaultValue={dados.n_inputs}>
            {OPCOES_PORTAS.map((quantidade) => (
              <option key={quantidade} value={quantidade}>
                {quantidade}
              </option>
            ))}
          </Select>
        </div>
        <div className="space-y-1">
          <Label htmlFor="n_outputs">Saídas (OUT1..OUTn)</Label>
          <Select
            id="n_outputs"
            name="n_outputs"
            data-testid="config-n-outputs"
            value={nOutputs}
            onChange={(evento) => aoMudarNOutputs(Number(evento.target.value))}
          >
            {OPCOES_PORTAS.map((quantidade) => (
              <option key={quantidade} value={quantidade}>
                {quantidade}
              </option>
            ))}
          </Select>
        </div>
      </div>

      {portasEu.length > 0 && (
        <div className="grid grid-cols-2 gap-3">
          {portasEu.map((porta) => (
            <div key={porta} className="space-y-1">
              <Label htmlFor={`output_eu_${porta}`}>{porta} · EU</Label>
              <Input
                id={`output_eu_${porta}`}
                name={`output_eu_${porta}`}
                data-testid={`config-output-eu-${porta}`}
                defaultValue={dados.output_eu[porta] ?? ""}
                placeholder="ex.: t/h"
              />
            </div>
          ))}
        </div>
      )}

      <div className="space-y-1">
        <Label htmlFor="code">Código</Label>
        <textarea
          id="code"
          name="code"
          data-testid="config-code"
          rows={12}
          spellCheck={false}
          defaultValue={dados.code}
          onKeyDown={indentarComTab}
          className="w-full rounded-sm border border-border bg-well p-2 font-mono text-xs leading-relaxed text-fg focus-visible:outline-2 focus-visible:outline-accent"
        />
        <p className="text-[10px] text-fg-muted">
          Escopo disponível: IN1..INn, state, math, numpy (np). Tab insere quatro espaços; Esc
          fecha o modal.
        </p>
      </div>
    </div>
  );
}

function CamposFuzzy({
  dados,
  nOutputs,
  aoMudarNOutputs,
}: {
  dados: NoFuzzy["data"];
  nOutputs: number;
  aoMudarNOutputs: (n_outputs: number) => void;
}) {
  const portasEu = portasScript("OUT", nOutputs);
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-1">
          <Label htmlFor="n_inputs">Entradas (IN1..INn)</Label>
          <Select id="n_inputs" name="n_inputs" data-testid="config-n-inputs" defaultValue={dados.n_inputs}>
            {OPCOES_PORTAS_FUZZY.map((quantidade) => (
              <option key={quantidade} value={quantidade}>
                {quantidade}
              </option>
            ))}
          </Select>
        </div>
        <div className="space-y-1">
          <Label htmlFor="n_outputs">Saídas (OUT1..OUTn)</Label>
          <Select
            id="n_outputs"
            name="n_outputs"
            data-testid="config-n-outputs"
            value={nOutputs}
            onChange={(evento) => aoMudarNOutputs(Number(evento.target.value))}
          >
            {OPCOES_PORTAS_FUZZY.map((quantidade) => (
              <option key={quantidade} value={quantidade}>
                {quantidade}
              </option>
            ))}
          </Select>
        </div>
      </div>

      {portasEu.length > 0 && (
        <div className="grid grid-cols-2 gap-3">
          {portasEu.map((porta) => (
            <div key={porta} className="space-y-1">
              <Label htmlFor={`output_eu_${porta}`}>{porta} · EU</Label>
              <Input
                id={`output_eu_${porta}`}
                name={`output_eu_${porta}`}
                data-testid={`config-output-eu-${porta}`}
                defaultValue={dados.output_eu[porta] ?? ""}
                placeholder="ex.: t/h"
              />
            </div>
          ))}
        </div>
      )}

      <div className="space-y-1">
        <Label htmlFor="fll">FLL (FuzzyLite Language)</Label>
        <textarea
          id="fll"
          name="fll"
          data-testid="config-fll"
          rows={12}
          spellCheck={false}
          maxLength={MAX_FLL_LENGTH}
          defaultValue={dados.fll}
          onKeyDown={indentarComTab}
          className="w-full rounded-sm border border-border bg-well p-2 font-mono text-xs leading-relaxed text-fg focus-visible:outline-2 focus-visible:outline-accent"
        />
        <p className="text-[10px] text-fg-muted">
          Motor FuzzyLite (Mamdani ou Tsukamoto). O número de InputVariable/OutputVariable
          declarados no FLL deve casar com Entradas/Saídas, na mesma ordem de declaração. Tab
          insere quatro espaços; Esc fecha o modal.
        </p>
      </div>
    </div>
  );
}

/** MPC tem modal dedicado (`mpc/MpcModal.tsx`, tarefa 4.2); FlowEditorPage nunca passa um
 *  nó MPC para cá. */
type NoGenerico = Exclude<BlocoNode, NoMpc>;

interface Props {
  no: NoGenerico;
  /** Total de blocos no canvas: teto do `exec_order` (contíguo 1..N, ADR-024). */
  totalBlocos: number;
  tags: readonly TagOut[];
  podeMutar: boolean;
  onAplicar: (no: NoGenerico, execOrder: number) => void;
  onFechar: () => void;
}

/**
 * Modal de config por duplo-clique (RF-301), um formulário por tipo de bloco.
 *
 * Os campos são não-controlados e lidos no envio; `enabled`/`kind` da matriz do TFS e o
 * `n_outputs` do Script vivem em estado — o primeiro par decide quais parâmetros existem,
 * o segundo decide quantos campos de EU por porta aparecem (spec §4.1-4). Para o operador o
 * `fieldset` inteiro entra desabilitado (contrato de RBAC, PRD §2).
 */
export function ModalConfigBloco({
  no,
  totalBlocos,
  tags,
  podeMutar,
  onAplicar,
  onFechar,
}: Props) {
  const dialogo = useRef<HTMLDialogElement>(null);
  const [matrizTfs, setMatrizTfs] = useState<DadosTfs | null>(no.type === "tfs" ? no.data : null);
  const [nOutputsScript, setNOutputsScript] = useState(no.type === "script" ? no.data.n_outputs : 0);
  const [nOutputsFuzzy, setNOutputsFuzzy] = useState(no.type === "fuzzy" ? no.data.n_outputs : 0);

  // `main.tsx` monta sob <StrictMode>: em dev o efeito roda duas vezes e `showModal()` num
  // <dialog> já aberto levanta InvalidStateError, que sem error boundary derruba a árvore.
  useEffect(() => {
    const elemento = dialogo.current;
    if (elemento !== null && !elemento.open) elemento.showModal();
  }, []);

  function aplicar(evento: FormEvent<HTMLFormElement>): void {
    evento.preventDefault();
    const campos = new FormData(evento.currentTarget);
    const label = String(campos.get("label") ?? "").trim();
    const execOrder = inteiroDoCampo(campos.get("exec_order"), no.data.exec_order, 1, totalBlocos);

    switch (no.type) {
      case "opc_read":
      case "opc_write": {
        const bruto = String(campos.get("tag_id") ?? "");
        const tag_id = bruto === "" ? null : Number(bruto);
        onAplicar({ ...no, data: { ...no.data, label, tag_id } }, execOrder);
        break;
      }
      case "script": {
        const n_outputs = inteiroDoCampo(campos.get("n_outputs"), 0, 0, MAX_PORTAS_SCRIPT);
        onAplicar(
          {
            ...no,
            data: {
              ...no.data,
              label,
              n_inputs: inteiroDoCampo(campos.get("n_inputs"), 0, 0, MAX_PORTAS_SCRIPT),
              n_outputs,
              code: String(campos.get("code") ?? ""),
              output_eu: podarOutputEu(
                "OUT",
                outputEuDoFormulario(campos, portasScript("OUT", MAX_PORTAS_SCRIPT)),
                n_outputs,
              ),
            },
          },
          execOrder,
        );
        break;
      }
      case "fuzzy": {
        const n_outputs = inteiroDoCampo(campos.get("n_outputs"), 0, 1, MAX_PORTAS_FUZZY);
        onAplicar(
          {
            ...no,
            data: {
              ...no.data,
              label,
              n_inputs: inteiroDoCampo(campos.get("n_inputs"), 0, 1, MAX_PORTAS_FUZZY),
              n_outputs,
              fll: String(campos.get("fll") ?? ""),
              output_eu: podarOutputEu(
                "OUT",
                outputEuDoFormulario(campos, portasScript("OUT", MAX_PORTAS_FUZZY)),
                n_outputs,
              ),
            },
          },
          execOrder,
        );
        break;
      }
      case "tfs":
        onAplicar(
          {
            ...no,
            data: {
              ...no.data,
              label,
              matrix: matrizDoFormulario((matrizTfs ?? no.data).matrix, campos),
              output_eu: outputEuDoFormulario(campos, ["y1", "y2"]),
            },
          },
          execOrder,
        );
        break;
      case "first_order":
        onAplicar(
          { ...no, data: { ...no.data, label, tau: numeroDoCampo(campos.get("tau"), no.data.tau) } },
          execOrder,
        );
        break;
      case "kalman":
        onAplicar(
          {
            ...no,
            data: {
              ...no.data,
              label,
              measurement_noise: numeroDoCampo(
                campos.get("measurement_noise"),
                no.data.measurement_noise,
              ),
              process_noise: numeroDoCampo(campos.get("process_noise"), no.data.process_noise),
            },
          },
          execOrder,
        );
        break;
    }
    // `onClose` (linha do <dialog>) chama `onFechar`; fechar via `close()` explícito em vez
    // de chamar `onFechar()` direto evita que o desmonte (estado -> null) derrube o <dialog>
    // do DOM ainda marcado como aberto (mesmo caminho que o botão Cancelar já usa).
    dialogo.current?.close();
  }

  return (
    <dialog
      ref={dialogo}
      onClose={onFechar}
      data-testid="config-modal"
      className="modal-bloco max-h-[85vh] w-[min(760px,92vw)] overflow-auto rounded-sm border border-border bg-surface p-0 text-fg"
    >
      <form onSubmit={aplicar}>
        <header className="flex items-center justify-between border-b border-border bg-well px-4 py-3">
          <h2 className="plaqueta text-sm text-fg">Configurar {ROTULO_BLOCO[no.type]}</h2>
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
              <Label htmlFor="label">Rótulo</Label>
              <Input
                id="label"
                name="label"
                data-testid="config-label"
                maxLength={60}
                defaultValue={no.data.label}
                placeholder={ROTULO_BLOCO[no.type]}
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="exec_order">Ordem de execução</Label>
              <Input
                id="exec_order"
                name="exec_order"
                data-testid="config-exec-order"
                type="number"
                min={1}
                max={totalBlocos}
                className="process-value"
                defaultValue={no.data.exec_order}
              />
              <p className="text-[10px] text-fg-muted">
                Contígua de 1 a {totalBlocos}; os demais blocos deslizam para acomodar.
              </p>
            </div>
          </div>

          {no.type === "opc_read" && <CamposTag dados={no.data} direcao="r" tags={tags} />}
          {no.type === "opc_write" && <CamposTag dados={no.data} direcao="w" tags={tags} />}
          {no.type === "script" && (
            <CamposScript dados={no.data} nOutputs={nOutputsScript} aoMudarNOutputs={setNOutputsScript} />
          )}
          {no.type === "tfs" && matrizTfs !== null && (
            <CamposTfs dados={matrizTfs} aoMudar={setMatrizTfs} />
          )}
          {no.type === "first_order" && <CamposFiltroPrimeiraOrdem dados={no.data} />}
          {no.type === "kalman" && <CamposFiltroKalman dados={no.data} />}
          {no.type === "fuzzy" && (
            <CamposFuzzy dados={no.data} nOutputs={nOutputsFuzzy} aoMudarNOutputs={setNOutputsFuzzy} />
          )}
        </fieldset>

        <footer className="flex justify-end gap-2 border-t border-border px-4 py-3">
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
