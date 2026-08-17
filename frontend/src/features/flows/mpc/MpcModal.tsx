import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";

import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import type { TagOut } from "../../../lib/api";
import { inteiroDoCampo } from "../config/campos";
import type { DadosMpc, NoMpc, ParModeloMpc, VariaveisMpc } from "../graph";
import { TabGeneral } from "./TabGeneral";
import { TabHorizons } from "./TabHorizons";
import { TabLimits } from "./TabLimits";
import { TabModels } from "./TabModels";
import { TabSummary } from "./TabSummary";
import { TabVariables } from "./TabVariables";
import { TabWeights } from "./TabWeights";
import { AJUDA_GERAL } from "./ajudaMpc";
import {
  parModeloDoFormulario,
  validarConfigMpc,
  variavelCvDoFormulario,
  variavelDvDoFormulario,
  variavelMvDoFormulario,
  variavelRestricaoDoFormulario,
} from "./mpcLogic";

/** 7 abas do modal MPC, verbatim RF-607 (spec F4 §7.3). */
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
  const rotuloInput = useRef<HTMLInputElement>(null);
  const fecharBotao = useRef<HTMLButtonElement>(null);
  const formulario = useRef<HTMLFormElement>(null);
  const [aba, setAba] = useState<SlugAba>("geral");
  const [multiplier, setMultiplier] = useState(no.data.multiplier);
  const [variaveis, setVariaveis] = useState<VariaveisMpc>(no.data.variables);
  const [modelos, setModelos] = useState(no.data.models);

  // `main.tsx` monta sob <StrictMode>: em dev o efeito roda duas vezes e `showModal()` num
  // <dialog> já aberto levanta InvalidStateError (mesma nota do modal genérico).
  //
  // Foco inicial explícito: o gatilho do tooltip (`Label` com `tooltip`, tarefa de tooltips
  // do modal) precede o `<Input>` do Rótulo na ordem do DOM (o texto do rótulo em si é o
  // gatilho, span com tabIndex=0) — sem isto, o algoritmo nativo de `showModal()` ("primeiro
  // descendente focável") passaria a focar o gatilho do tooltip em vez do campo, abrindo um
  // tooltip indesejado ao abrir o modal (achado no smoke test manual desta tarefa).
  //
  // `podeMutar=false` (papel operador, somente leitura — RF-003/RBAC): o `<fieldset
  // disabled>` (linha abaixo) desabilita o `<input>` do Rótulo, e `.focus()` num elemento
  // desabilitado é no-op — o gatilho do tooltip, que NÃO é elemento form-associado
  // (`fieldset[disabled]` só cobre button/fieldset/input/object/select/textarea), continua
  // focável e voltaria a ser o alvo do `showModal()`, reproduzindo a mesma regressão só no
  // caminho somente-leitura (gap pego na revisão desta tarefa). Foca o botão Fechar em vez
  // disso — sempre focável, sempre presente, mesmo padrão de "foco cai numa ação segura" de
  // diálogo somente-leitura.
  useEffect(() => {
    const elemento = dialogo.current;
    if (elemento !== null && !elemento.open) {
      elemento.showModal();
      if (podeMutar) rotuloInput.current?.focus();
      else fecharBotao.current?.focus();
    }
  }, [podeMutar]);

  function aplicar(evento: FormEvent<HTMLFormElement>): void {
    evento.preventDefault();
    const campos = new FormData(evento.currentTarget);
    // Campo AUSENTE do FormData ≠ campo vazio: `mpc_name` mora na aba Geral, que é desmontada
    // ao trocar de aba (nota abaixo), então Aplicar a partir de Variáveis/Modelos/… mandava
    // `name: ""` e apagava o nome do MPC no grafo. `exec_order` já tratava isso pelo padrão do
    // `inteiroDoCampo`; texto passa a seguir a mesma regra — só o campo montado pode limpar.
    const texto = (campo: string, atual: string): string =>
      campos.has(campo) ? String(campos.get(campo) ?? "").trim() : atual;
    const label = texto("label", no.data.label);
    const execOrder = inteiroDoCampo(campos.get("exec_order"), no.data.exec_order, 1, totalBlocos);
    const name = texto("mpc_name", no.data.name);
    const novasVariaveis = variaveisDoFormulario(variaveis, campos);
    const novosModelos = modelosDoFormulario(novasVariaveis, modelos, campos);

    // Aba Resumo (spec F4 §7.3-7): erro bloqueante impede o Aplicar — sincroniza o estado com
    // o que acabou de sair do formulário (para a aba Resumo mostrar exatamente o que bloqueou,
    // mesmo que os campos numéricos editados não estejam mais montados) e navega para lá em
    // vez de fechar. Aviso não bloqueia.
    const { erros } = validarConfigMpc(novasVariaveis, novosModelos, multiplier, tsFlowSegundos);
    if (erros.length > 0) {
      setVariaveis(novasVariaveis);
      setModelos(novosModelos);
      setAba("resumo");
      return;
    }

    const dados: DadosMpc = {
      exec_order: no.data.exec_order,
      label,
      name,
      multiplier,
      variables: novasVariaveis,
      models: novosModelos,
    };
    onAplicar({ ...no, data: dados }, execOrder);
    // `close()` explícito (débito m4, spec F4 §8): `onClose` dispara `onFechar`.
    dialogo.current?.close();
  }

  // Fix round 1 (revisão 4.3, Critical): cada aba é DESMONTADA ao trocar (`{aba === "x" &&
  // (<TabX/>)}`), e a maioria dos campos folha (nome/EU/limites/Δu/params da matriz/pid) é
  // não-controlada — só existe no DOM, lida apenas no Aplicar (mesmo padrão do TFS). Sem
  // isso, digitar numa aba e trocar para outra sem passar pelo Aplicar apagava a edição antes
  // de qualquer leitura (cenário B-F4-03 passos 9-11: params digitados em Modelos, trocar
  // para Resumo, Aplicar via Resumo devolvia os defaults do `kind`, não o digitado).
  // `mudarAba` lê o `FormData` da aba que está sendo deixada e reconstrói `variaveis`/
  // `modelos` com as mesmas funções do Aplicar antes de desmontar — a aba nova sempre parte
  // de um estado atualizado, e o Aplicar (de qualquer aba) já opera sobre esse estado.
  function mudarAba(novaAba: SlugAba): void {
    const elemento = formulario.current;
    if (elemento !== null) {
      const campos = new FormData(elemento);
      const novasVariaveis = variaveisDoFormulario(variaveis, campos);
      setVariaveis(novasVariaveis);
      setModelos(modelosDoFormulario(novasVariaveis, modelos, campos));
    }
    setAba(novaAba);
  }

  // Minor 3 (revisão final): fecha a semântica ARIA de tabs deixada pela metade na revisão
  // 4.2 (`role`/`aria-selected` sem ligação `id`/`aria-controls`/`aria-labelledby` nem
  // navegação por seta com tabindex circulante — WAI-ARIA APG). `abaRefs` guarda o botão de
  // cada aba para o foco seguir a ativação em vez de só o `aria-selected`.
  const abaRefs = useRef<Partial<Record<SlugAba, HTMLButtonElement>>>({});

  function focarEAtivarAba(indice: number): void {
    const alvo = ABAS[(indice + ABAS.length) % ABAS.length];
    mudarAba(alvo.slug);
    abaRefs.current[alvo.slug]?.focus();
  }

  function aoNavegarAbas(evento: KeyboardEvent<HTMLButtonElement>, indiceAtual: number): void {
    switch (evento.key) {
      case "ArrowRight":
        evento.preventDefault();
        focarEAtivarAba(indiceAtual + 1);
        break;
      case "ArrowLeft":
        evento.preventDefault();
        focarEAtivarAba(indiceAtual - 1);
        break;
      case "Home":
        evento.preventDefault();
        focarEAtivarAba(0);
        break;
      case "End":
        evento.preventDefault();
        focarEAtivarAba(ABAS.length - 1);
        break;
    }
  }

  return (
    <dialog
      ref={dialogo}
      onClose={onFechar}
      data-testid="mpc-modal"
      className="modal-bloco max-h-[90vh] w-[min(960px,96vw)] overflow-auto rounded-sm border border-border bg-surface p-0 text-fg"
    >
      <form ref={formulario} onSubmit={aplicar}>
        <header className="flex items-center justify-between border-b border-border bg-well px-4 py-3">
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
              <Label htmlFor="mpc-label" tooltip={AJUDA_GERAL.rotulo}>Rótulo</Label>
              <Input
                ref={rotuloInput}
                id="mpc-label"
                name="label"
                data-testid="config-label"
                maxLength={60}
                defaultValue={no.data.label}
                placeholder="MPC"
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="mpc-exec-order" tooltip={AJUDA_GERAL.execOrder}>Ordem de execução</Label>
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
              DESIGN.md §Shapes/§Don'ts): a aba ativa vira chapa "pressionada". `role="tablist"`/
              `role="tab"`/`aria-selected` + `id`/`aria-controls` linkando ao painel + tabindex
              circulante com seta esquerda/direita/Home/End fecham o minor 3 da revisão final
              (WAI-ARIA APG tabs pattern). */}
          <nav
            role="tablist"
            className="flex flex-wrap gap-1 border-b border-border pb-2"
            aria-label="Abas MPC"
          >
            {ABAS.map((item, indice) => (
              <button
                key={item.slug}
                ref={(elemento) => {
                  if (elemento !== null) abaRefs.current[item.slug] = elemento;
                }}
                type="button"
                role="tab"
                id={`mpc-tab-${item.slug}`}
                aria-controls={`mpc-tabpanel-${item.slug}`}
                aria-selected={aba === item.slug}
                tabIndex={aba === item.slug ? 0 : -1}
                data-testid={`mpc-tab-${item.slug}`}
                onClick={() => {
                  mudarAba(item.slug);
                }}
                onKeyDown={(evento) => {
                  aoNavegarAbas(evento, indice);
                }}
                className={`plaqueta rounded-sm border px-3 py-1.5 text-[11px] transition-colors ${
                  aba === item.slug
                    ? "border-accent bg-well text-fg"
                    : "border-border bg-surface text-fg-muted hover:border-accent"
                }`}
              >
                {item.rotulo}
              </button>
            ))}
          </nav>

          <div
            role="tabpanel"
            id={`mpc-tabpanel-${aba}`}
            aria-labelledby={`mpc-tab-${aba}`}
            className="min-h-[280px]"
          >
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
            {aba === "horizontes" && (
              <TabHorizons
                variaveis={variaveis}
                aoMudarVariaveis={setVariaveis}
                modelos={modelos}
                multiplier={multiplier}
                tsFlowSegundos={tsFlowSegundos}
              />
            )}
            {aba === "restricoes-limites" && <TabLimits variaveis={variaveis} />}
            {aba === "pesos" && <TabWeights variaveis={variaveis} />}
            {aba === "resumo" && (
              <TabSummary
                variaveis={variaveis}
                modelos={modelos}
                multiplier={multiplier}
                tsFlowSegundos={tsFlowSegundos}
              />
            )}
          </div>
        </fieldset>

        <footer className="flex justify-end gap-2 border-t border-border px-4 py-3">
          <Button
            ref={fecharBotao}
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
