import {
  Background,
  BackgroundVariant,
  Controls,
  ReactFlow,
  ReactFlowProvider,
  useEdgesState,
  useNodesState,
  useReactFlow,
  type Connection,
  type Edge,
  type EdgeChange,
  type FinalConnectionState,
  type NodeChange,
  type XYPosition,
} from "@xyflow/react";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type DragEvent,
  type ReactNode,
} from "react";
import { Link, useParams } from "react-router";

import { Button } from "../../components/ui/button";
import { Card } from "../../components/ui/card";
import { ApiError, type TagOut } from "../../lib/api";
import { cn } from "../../lib/cn";
import { useCanMutate } from "../auth/useAuth";
import { useConnections } from "../connections/useConnections";
import { useTags } from "../tags/useTags";
import { ModalConfigBloco } from "./config/ModalConfigBloco";
import { FlowPalette, MIME_BLOCO } from "./FlowPalette";
import { FlowPropsModal } from "./FlowPropsModal";
import {
  avisosInversao,
  compactarExecOrder,
  criarBloco,
  deGraphJson,
  definirExecOrder,
  motivoRecusa,
  paraGraphJson,
  podarArestasDoBloco,
  proximaPosicaoNaGrade,
  proximoExecOrder,
  TIPOS_BLOCO,
  type BlocoEdge,
  type BlocoNode,
  type GraphJson,
  type MapaTags,
  type TipoBloco,
} from "./graph";
import { impactoDoSave, type ImpactoMpc } from "./impactoSave";
import { MpcModal } from "./mpc/MpcModal";
import { TIPOS_DE_NO } from "./nodes";
import { ContextoTags, ContextoTsFlow, ContextoValores, type ValoresAoVivo } from "./nodes/contexto";
import { formatarTs, useComandarFlow, useFlow, useSaveFlow } from "./useFlows";
import {
  formatarNumero,
  ROTULO_ESTADO,
  useFlowStatus,
  type CanvasAoVivo,
  type EstadoConexao,
  type EstadoFlow,
} from "./useFlowStatus";

import "@xyflow/react/dist/base.css";
import "./flow-canvas.css";

/**
 * Ids legíveis: o `block_id` aparece nas mensagens 422 e é a chave de preservação de estado
 * no hot-swap (ADR-011).
 *
 * `crypto.randomUUID` é restrito a contexto seguro e o sistema roda em HTTP interno
 * (ADR-023): fora de `localhost` ele simplesmente não existe e inserir bloco quebraria na
 * planta. `getRandomValues` não tem essa restrição. Unicidade só precisa valer dentro de um
 * grafo, e o save reprova id duplicado.
 */
function novoId(tipo: TipoBloco): string {
  const bytes = crypto.getRandomValues(new Uint8Array(4));
  const sufixo = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
  return `${tipo}_${sufixo}`;
}

function erroLegivel(err: unknown): string {
  return err instanceof ApiError ? err.message : "Erro de comunicação com o servidor";
}

function Aviso({ texto, tom }: { texto: string; tom: "warn" | "alarm" }) {
  return (
    <li className={tom === "alarm" ? "text-alarm" : "text-warn-fg"}>
      <span className="plaqueta mr-2 text-[10px]">{tom === "alarm" ? "Erro" : "Aviso"}</span>
      {texto}
    </li>
  );
}

const COR_LAMPADA: Record<EstadoFlow, string> = {
  running: "text-success",
  stopped: "text-fg-muted",
  failed: "text-alarm",
};

/**
 * Lâmpada do estado publicado: cor **e** forma **e** rótulo textual (Regra do Canal
 * Redundante). O verde só aparece aqui — é a lâmpada "rodando/vivo" que o DESIGN.md
 * reserva, e não uma cor de dado.
 */
function LampadaEstado({ estado }: { estado: EstadoFlow }) {
  return (
    <span
      data-testid="canvas-estado"
      className={cn("inline-flex items-center gap-1.5", COR_LAMPADA[estado])}
    >
      <svg aria-hidden="true" width="10" height="10" viewBox="0 0 10 10" fill="currentColor">
        {estado === "running" && <circle cx="5" cy="5" r="4" />}
        {estado === "stopped" && (
          <rect x="1" y="1" width="8" height="8" fill="none" stroke="currentColor" />
        )}
        {estado === "failed" && <path d="M5 0 10 9H0L5 0Z" />}
      </svg>
      <span className="plaqueta text-[11px]">{ROTULO_ESTADO[estado]}</span>
    </span>
  );
}

/** Sem replay (§5.3): entre assinar e a varredura seguinte não há valor nenhum a mostrar. */
const AGUARDO: Record<Exclude<EstadoConexao, "sessao_invalida">, string> = {
  conectando: "Conectando ao canal ao vivo…",
  aberta: "Aguardando dado da varredura",
  reconectando: "Reconectando ao canal ao vivo…",
};

/** Cabeçalho ao vivo (RF-305, spec §6.2): estado publicado, varredura e overruns. */
function CabecalhoAoVivo({ aoVivo }: { aoVivo: CanvasAoVivo }) {
  if (aoVivo.conexao === "sessao_invalida") {
    return (
      <p role="alert" data-testid="canvas-vivo" className="text-xs text-alarm">
        Sessão inválida ou expirada: entre novamente para ver o canvas ao vivo.
      </p>
    );
  }
  if (aoVivo.status === null) {
    return (
      <p data-testid="canvas-vivo" className="text-xs text-fg-muted">
        {AGUARDO[aoVivo.conexao]}
      </p>
    );
  }
  return (
    <div data-testid="canvas-vivo" className="flex items-center gap-3 text-xs text-fg-muted">
      <LampadaEstado estado={aoVivo.status.state} />
      <span>
        Duração de execução{" "}
        <span className="process-value text-fg">{formatarNumero(aoVivo.status.scan_ms)}</span> ms
      </span>
      <span>
        Overruns <span className="process-value text-fg">{aoVivo.status.overruns}</span>
      </span>
      {aoVivo.conexao !== "aberta" && (
        <span className="text-warn-fg">{AGUARDO[aoVivo.conexao]}</span>
      )}
    </div>
  );
}

/**
 * O que os nós leem de fora de `data`: tags do projeto e valores ao vivo. Nada disso pode
 * morar em `data` — o servidor recusa chave desconhecida ali com 422.
 */
function ContextosDoEditor({
  tags,
  valores,
  tsFlowSegundos,
  children,
}: {
  tags: ReadonlyMap<number, TagOut>;
  valores: ValoresAoVivo;
  tsFlowSegundos: number;
  children: ReactNode;
}) {
  return (
    <ContextoTags.Provider value={tags}>
      <ContextoValores.Provider value={valores}>
        <ContextoTsFlow.Provider value={tsFlowSegundos}>{children}</ContextoTsFlow.Provider>
      </ContextoValores.Provider>
    </ContextoTags.Provider>
  );
}

/**
 * Comutador EDIT/ONLINE do editor (tarefa 3.2, spec F3 §6.2): EDIT desliga os valores ao
 * vivo e libera paleta/arraste; ONLINE mostra os valores publicados por varredura (já
 * expostos por `BlocoChapa.tsx`/`ContextoValores`, nada novo para buscar) e trava a tela em
 * somente leitura. Mesmo comutador de posição (variante primária/discreta + `aria-pressed`)
 * de `BotaoComando` em `FlowsPage.tsx` — cor nunca é o único canal.
 */
function BotaoModo({
  modo,
  onMudar,
}: {
  modo: "edit" | "online";
  onMudar: (modo: "edit" | "online") => void;
}) {
  return (
    <div className="flex items-center gap-1.5" role="group" aria-label="Modo do editor">
      <Button
        variant={modo === "edit" ? "outline" : "primary"}
        size="sm"
        data-testid="flow-modo-edit"
        aria-pressed={modo === "edit"}
        title={modo === "edit" ? "Modo atual" : undefined}
        onClick={() => onMudar("edit")}
      >
        Edit
      </Button>
      <Button
        variant={modo === "online" ? "outline" : "primary"}
        size="sm"
        data-testid="flow-modo-online"
        aria-pressed={modo === "online"}
        title={modo === "online" ? "Modo atual" : undefined}
        onClick={() => onMudar("online")}
      >
        Online
      </Button>
    </div>
  );
}

const ROTULO_EFEITO: Record<ImpactoMpc["efeito"], string> = {
  preservado: "Preservado: modo e valores continuam iguais.",
  rearme_bumpless: "modo preservado; MV segura o último valor por ~1 ciclo",
  reset_local: "O controle atual será colocado em LOCAL",
};

const TOM_EFEITO: Record<ImpactoMpc["efeito"], string> = {
  preservado: "text-fg-muted",
  rearme_bumpless: "text-warn-fg",
  reset_local: "text-alarm",
};

/**
 * Diálogo de impacto no MPC (tarefa 3.3, spec F3, TD-006): abre quando Salvar/Deploy muda a
 * config funcional de algum bloco MPC com o flow rodando. Decisão registrada: dispara mesmo
 * com o bloco em LOCAL — o editor não assina `mpc_state`, e ser conservador aqui é mais
 * simples do que preciso. Confirmar/Cancelar limpam o estado do chamador diretamente (sem
 * `dialogo.current?.close()`): o desmonte pelo React já basta, e evita o duplo disparo que
 * fechar-e-depois-notificar teria via `onClose`.
 */
function DialogoImpacto({
  impacto,
  onConfirmar,
  onCancelar,
}: {
  impacto: readonly ImpactoMpc[];
  onConfirmar: () => void;
  onCancelar: () => void;
}) {
  const dialogo = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const elemento = dialogo.current;
    if (elemento !== null && !elemento.open) elemento.showModal();
  }, []);

  return (
    <dialog
      ref={dialogo}
      onClose={onCancelar}
      data-testid="flow-impacto-dialog"
      className="modal-bloco w-[min(520px,92vw)] overflow-auto rounded-sm border border-border bg-surface p-0 text-fg"
    >
      <header className="flex items-center justify-between border-b border-border bg-well px-4 py-3">
        <h2 className="plaqueta text-sm text-fg">Impacto no MPC</h2>
      </header>
      <div className="p-4">
        <ul className="space-y-2 text-xs">
          {impacto.map((item) => (
            <li key={item.blockId}>
              <span className="plaqueta text-fg">{item.label}</span>
              <p className={TOM_EFEITO[item.efeito]}>{ROTULO_EFEITO[item.efeito]}</p>
            </li>
          ))}
        </ul>
      </div>
      <footer className="flex justify-end gap-2 border-t border-border px-4 py-3">
        <Button variant="outline" data-testid="flow-impacto-cancelar" onClick={onCancelar}>
          Cancelar
        </Button>
        <Button data-testid="flow-impacto-confirmar" onClick={onConfirmar}>
          Confirmar
        </Button>
      </footer>
    </dialog>
  );
}

function Editor({ flowId }: { flowId: number }) {
  const flow = useFlow(flowId);
  const salvar = useSaveFlow(flowId);
  const comandar = useComandarFlow("deploy");
  const podeMutar = useCanMutate();

  // Um socket por editor aberto, assinando só este flow e morrendo com a página (§5.3).
  const aoVivo = useFlowStatus(flowId);

  // Modo EDIT/ONLINE (tarefa 3.2): decidido UMA vez, na primeira varredura que o canal
  // publica — antes disso o editor não sabe se o flow está rodando. Depois de decidido, o
  // modo só muda pela mão do operador (o comutador do header), nunca sozinho.
  const [modo, setModo] = useState<"edit" | "online" | null>(null);
  useEffect(() => {
    if (modo !== null || aoVivo.status === null) return;
    setModo(aoVivo.status.state === "running" ? "online" : "edit");
  }, [modo, aoVivo.status]);
  const modoEfetivo = modo ?? "edit";

  const valores = useMemo<ValoresAoVivo>(
    () =>
      modoEfetivo === "edit"
        ? { ativo: false, ports: {} }
        : { ativo: aoVivo.status !== null, ports: aoVivo.ports },
    [modoEfetivo, aoVivo.status, aoVivo.ports],
  );

  const projectId = flow.data?.project_id ?? null;
  // Tags visíveis ao flow são as do projeto **do flow** — o mesmo recorte que o servidor faz
  // ao validar (`_tags_do_projeto`). `GET /api/tags` não aceita `project_id`, então o recorte
  // é por conexão, como na tela de tags.
  const conexoes = useConnections(projectId);
  const tags = useTags({ connectionId: null, direction: null });
  const tagsDoProjeto = useMemo<TagOut[]>(() => {
    const doProjeto = new Set((conexoes.data ?? []).map((conexao) => conexao.id));
    return (tags.data ?? []).filter((tag) => doProjeto.has(tag.connection_id));
  }, [conexoes.data, tags.data]);
  const porId = useMemo(
    () => new Map(tagsDoProjeto.map((tag) => [tag.id, tag])),
    [tagsDoProjeto],
  );
  const tiposDeTag = useMemo<MapaTags>(
    () => new Map(tagsDoProjeto.map((tag) => [tag.id, tag.data_type])),
    [tagsDoProjeto],
  );

  const [nodes, setNodes, onNodesChange] = useNodesState<BlocoNode>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<BlocoEdge>([]);
  const [emConfig, setEmConfig] = useState<string | null>(null);
  const [recusa, setRecusa] = useState<string | null>(null);
  const [erroSave, setErroSave] = useState<string | null>(null);
  const [avisosServidor, setAvisosServidor] = useState<string[] | null>(null);
  const [propsAbertas, setPropsAbertas] = useState(false);
  // `null` = diálogo fechado; lista completa dos blocos MPC do grafo atual quando aberto
  // (tarefa 3.3) — inclui os `preservado` também, para o operador ver que nada muda neles.
  const [impacto, setImpacto] = useState<ImpactoMpc[] | null>(null);

  const areaRef = useRef<HTMLDivElement>(null);
  const carregado = useRef<number | null>(null);
  const motivoRef = useRef<string | null>(null);
  // Grafo CARREGADO (ou do último save bem-sucedido) — base de comparação do diálogo de
  // impacto (tarefa 3.3); atualizado no load (efeito abaixo) e em `salvarGrafo`.
  const grafoOriginal = useRef<GraphJson | null>(null);
  const acaoPendente = useRef<"salvar" | "deploy" | null>(null);
  const { screenToFlowPosition } = useReactFlow();

  // Carga única por flow: um refetch de fundo não pode atropelar o desenho em andamento.
  useEffect(() => {
    const detalhe = flow.data;
    if (detalhe === undefined || carregado.current === detalhe.id) return;
    carregado.current = detalhe.id;
    const grafo = deGraphJson(detalhe.graph_json);
    setNodes(grafo.nodes);
    setEdges(grafo.edges);
    // Normalizado pelo mesmo par deGraphJson/paraGraphJson que o save usa: comparar contra
    // os bytes crus do servidor produziria diferença por formatação, não por edição real.
    grafoOriginal.current = paraGraphJson(grafo.nodes, grafo.edges);
  }, [flow.data, setNodes, setEdges]);

  const adicionar = useCallback(
    (tipo: TipoBloco, position: XYPosition) => {
      setNodes((atuais) => [
        ...atuais,
        criarBloco(tipo, novoId(tipo), position, proximoExecOrder(atuais)),
      ]);
    },
    [setNodes],
  );

  /**
   * Clique na paleta insere em grade a partir do canto visível do canvas.
   *
   * O passo é a pegada do bloco (212 px de chapa), não um deslocamento decorativo: com um
   * passo menor os blocos nascem empilhados e o de cima intercepta o duplo-clique do de
   * baixo. A âncora sai de `screenToFlowPosition` uma vez e a grade é montada em coordenadas
   * do canvas, para o espaçamento não depender do zoom.
   */
  const adicionarNoCentro = useCallback(
    (tipo: TipoBloco) => {
      const caixa = areaRef.current?.getBoundingClientRect();
      if (caixa === undefined) return;
      const ancora = screenToFlowPosition({ x: caixa.left + 48, y: caixa.top + 48 });
      adicionar(tipo, proximaPosicaoNaGrade(nodes, ancora));
    },
    [adicionar, nodes, screenToFlowPosition],
  );

  function aoSoltar(evento: DragEvent<HTMLDivElement>): void {
    const bruto = evento.dataTransfer.getData(MIME_BLOCO);
    const tipo = TIPOS_BLOCO.find((candidato) => candidato === bruto);
    if (tipo === undefined) return;
    evento.preventDefault();
    adicionar(tipo, screenToFlowPosition({ x: evento.clientX, y: evento.clientY }));
  }

  /**
   * Exclusão: o React Flow já remove as arestas ligadas, mas a compactação do `exec_order`
   * (ADR-024) é nossa — e o filtro de arestas fica como rede de segurança, porque aresta
   * pendurada em nó inexistente é 422 no save.
   */
  const aoMudarNos = useCallback(
    (mudancas: NodeChange<BlocoNode>[]) => {
      onNodesChange(mudancas);
      // Mexeu no conteúdo do grafo: o resultado do último save deixou de descrever a tela.
      if (mudancas.some((mudanca) => mudanca.type !== "select" && mudanca.type !== "dimensions")) {
        setAvisosServidor(null);
      }
      const removidos = mudancas
        .filter((mudanca) => mudanca.type === "remove")
        .map((mudanca) => mudanca.id);
      if (removidos.length === 0) return;
      setEdges((atuais) =>
        atuais.filter(
          (aresta) => !removidos.includes(aresta.source) && !removidos.includes(aresta.target),
        ),
      );
      // Forma funcional: a compactação enxerga a lista já sem os removidos, nunca a do closure.
      setNodes((atuais) => compactarExecOrder(atuais));
    },
    [onNodesChange, setEdges, setNodes],
  );

  const validarConexao = useCallback(
    (candidata: Connection | Edge) => {
      const motivo = motivoRecusa(
        {
          source: candidata.source,
          target: candidata.target,
          sourceHandle: candidata.sourceHandle ?? null,
          targetHandle: candidata.targetHandle ?? null,
        },
        nodes,
        edges,
        tiposDeTag,
      );
      motivoRef.current = motivo;
      return motivo === null;
    },
    [nodes, edges, tiposDeTag],
  );

  const aoMudarArestas = useCallback(
    (mudancas: EdgeChange<BlocoEdge>[]) => {
      onEdgesChange(mudancas);
      if (mudancas.some((mudanca) => mudanca.type !== "select")) setAvisosServidor(null);
    },
    [onEdgesChange],
  );

  function aoConectar({ source, target, sourceHandle, targetHandle }: Connection): void {
    if (sourceHandle === null || targetHandle === null) return;
    setRecusa(null);
    setAvisosServidor(null);
    setEdges((atuais) => [
      ...atuais,
      {
        id: `${source}.${sourceHandle}->${target}.${targetHandle}`,
        source,
        target,
        sourceHandle,
        targetHandle,
        type: "smoothstep",
      },
    ]);
  }

  /** Soltar sobre uma porta sem que a ligação nasça = recusa; o motivo vira texto. */
  function aoTerminarConexao(_evento: MouseEvent | TouchEvent, estado: FinalConnectionState): void {
    if (estado.toHandle !== null && motivoRef.current !== null) setRecusa(motivoRef.current);
    motivoRef.current = null;
  }

  function aplicarConfig(atualizado: BlocoNode, execOrder: number): void {
    setNodes((atuais) =>
      definirExecOrder(
        atuais.map((no) => (no.id === atualizado.id ? atualizado : no)),
        atualizado.id,
        execOrder,
      ),
    );
    // Encolher o Script deixaria arestas em portas que não existem mais (422 no save).
    setEdges((atuais) => podarArestasDoBloco(atuais, atualizado));
    setAvisosServidor(null);
  }

  async function salvarGrafo(): Promise<boolean> {
    setErroSave(null);
    setRecusa(null);
    const grafoParaSalvar = paraGraphJson(nodes, edges);
    try {
      const salvo = await salvar.mutateAsync(grafoParaSalvar);
      setAvisosServidor(salvo.warnings ?? []);
      grafoOriginal.current = grafoParaSalvar;
      return true;
    } catch (err) {
      setAvisosServidor(null);
      setErroSave(erroLegivel(err));
      return false;
    }
  }

  /**
   * Salvar/Deploy do editor (tarefa 3.3): com o flow rodando, um efeito diferente de
   * `preservado` em algum bloco MPC abre o diálogo de impacto ANTES do PUT — decisão
   * registrada: o diálogo dispara mesmo com o bloco em LOCAL, porque o editor não assina
   * `mpc_state` (conservador por simplicidade, não por precisão de estado). Flow parado não
   * tem MPC rodando para impactar — sem diálogo.
   */
  function abrirFluxoDeSalvar(acao: "salvar" | "deploy"): void {
    acaoPendente.current = acao;
    const impactos =
      grafoOriginal.current !== null && flow.data?.desired_state === "running"
        ? impactoDoSave(grafoOriginal.current, paraGraphJson(nodes, edges), false)
        : [];
    if (impactos.some((item) => item.efeito !== "preservado")) {
      setImpacto(impactos);
      return;
    }
    void executarAcaoPendente();
  }

  /** Deploy é save + comando: o PUT de um flow rodando já publica `reload` (o comando fica
   *  no-op no runtime); para flow parado/failed o deploy sobe o flow — cobre a retomada
   *  manual sem precisar ir até a lista de flows. */
  async function executarAcaoPendente(): Promise<void> {
    const acao = acaoPendente.current;
    acaoPendente.current = null;
    setImpacto(null);
    const salvouOk = await salvarGrafo();
    if (acao === "deploy" && salvouOk) {
      try {
        await comandar.mutateAsync(flowId);
      } catch (err) {
        setErroSave(erroLegivel(err));
      }
    }
  }

  const inversoes = avisosInversao(nodes, edges);
  const noEmConfig = nodes.find((no) => no.id === emConfig) ?? null;

  if (flow.isPending) {
    return <p className="text-sm text-fg-muted">Carregando flow…</p>;
  }
  if (flow.isError || flow.data === undefined) {
    return (
      <p role="alert" className="text-sm text-alarm">
        {flow.error instanceof ApiError ? flow.error.message : "Falha ao consultar o flow"}
      </p>
    );
  }

  return (
    <ContextosDoEditor tags={porId} valores={valores} tsFlowSegundos={flow.data.ts_seconds}>
      <section className="flex h-[calc(100vh-9rem)] flex-col gap-3">
        <header className="flex items-center justify-between gap-4">
          <div className="flex items-baseline gap-3">
            <Link to="/engenharia/flows" className="plaqueta text-xs text-accent hover:underline">
              Flows
            </Link>
            <h1 className="plaqueta text-sm text-fg">{flow.data.name}</h1>
            <span className="text-xs text-fg-muted">
              Ts{" "}
              <span data-testid="flow-header-ts" className="process-value text-fg">
                {formatarTs(flow.data.ts_seconds)}
              </span>{" "}
              s
              · <span className="process-value text-fg">{nodes.length}</span> bloco(s)
            </span>
            {podeMutar && (
              <Button
                variant="outline"
                size="sm"
                data-testid="flow-props-abrir"
                onClick={() => setPropsAbertas(true)}
              >
                Propriedades
              </Button>
            )}
          </div>
          <div className="flex items-center gap-3">
            <CabecalhoAoVivo aoVivo={aoVivo} />
            <BotaoModo modo={modoEfetivo} onMudar={setModo} />
            {podeMutar && modoEfetivo === "edit" && (
              <Button
                variant="outline"
                data-testid="flow-deploy-editor"
                disabled={salvar.isPending || comandar.isPending}
                onClick={() => abrirFluxoDeSalvar("deploy")}
              >
                {comandar.isPending ? "Publicando…" : "Deploy"}
              </Button>
            )}
            {podeMutar && modoEfetivo === "edit" && (
              <Button
                data-testid="flow-salvar"
                disabled={salvar.isPending}
                onClick={() => abrirFluxoDeSalvar("salvar")}
              >
                {salvar.isPending ? "Salvando…" : "Salvar"}
              </Button>
            )}
          </div>
        </header>

        {(recusa !== null || erroSave !== null || inversoes.length > 0 || avisosServidor !== null) && (
          <Card className="px-3 py-2">
            <ul className="space-y-1 text-xs" role="alert" data-testid="editor-mensagens">
              {erroSave !== null && <Aviso texto={erroSave} tom="alarm" />}
              {recusa !== null && <Aviso texto={recusa} tom="alarm" />}
              {/* Listas recriadas inteiras a cada render: índice é chave estável o bastante,
                  e dois blocos sem rótulo produzem textos iguais. */}
              {inversoes.map((aviso, indice) => (
                <Aviso key={`local-${String(indice)}`} texto={aviso} tom="warn" />
              ))}
              {avisosServidor !== null && avisosServidor.length === 0 && erroSave === null && (
                <li className="text-fg-muted">Grafo salvo sem avisos.</li>
              )}
              {(avisosServidor ?? []).map((aviso, indice) => (
                <Aviso key={`servidor-${String(indice)}`} texto={aviso} tom="warn" />
              ))}
            </ul>
          </Card>
        )}

        <div className="flex min-h-0 flex-1 gap-3">
          {podeMutar && modoEfetivo === "edit" && <FlowPalette onAdicionar={adicionarNoCentro} />}
          <div
            ref={areaRef}
            className="min-h-0 flex-1 overflow-hidden rounded-sm border border-border"
            onDrop={aoSoltar}
            onDragOver={(evento) => {
              evento.preventDefault();
              evento.dataTransfer.dropEffect = "copy";
            }}
          >
            <ReactFlow
              className="canvas-flow"
              nodes={nodes}
              edges={edges}
              nodeTypes={TIPOS_DE_NO}
              onNodesChange={aoMudarNos}
              onEdgesChange={aoMudarArestas}
              onConnect={aoConectar}
              onConnectStart={() => {
                motivoRef.current = null;
                setRecusa(null);
              }}
              onConnectEnd={aoTerminarConexao}
              isValidConnection={validarConexao}
              onNodeDoubleClick={(_evento, no) => {
                if (modoEfetivo === "edit") setEmConfig(no.id);
              }}
              nodesDraggable={podeMutar && modoEfetivo === "edit"}
              nodesConnectable={podeMutar && modoEfetivo === "edit"}
              edgesReconnectable={false}
              deleteKeyCode={podeMutar && modoEfetivo === "edit" ? ["Backspace", "Delete"] : null}
              fitView
              fitViewOptions={
                // Sem teto, o `fitView` de um grafo vazio abre o canvas no zoom máximo: a
                // chapa vira o dobro do tamanho e os blocos inseridos em seguida nascem fora
                // da área visível. Ajustar nunca amplia além de 100%.
                { maxZoom: 1, padding: 0.2 }
              }
              minZoom={0.3}
            >
              <Background variant={BackgroundVariant.Dots} gap={16} size={1} />
              <Controls showInteractive={false} />
            </ReactFlow>
          </div>
        </div>

        {noEmConfig !== null && noEmConfig.type === "mpc" && (
          <MpcModal
            key={noEmConfig.id}
            no={noEmConfig}
            totalBlocos={nodes.length}
            tags={tagsDoProjeto}
            tsFlowSegundos={flow.data.ts_seconds}
            podeMutar={podeMutar}
            onAplicar={aplicarConfig}
            onFechar={() => {
              setEmConfig(null);
            }}
          />
        )}
        {noEmConfig !== null && noEmConfig.type !== "mpc" && (
          <ModalConfigBloco
            key={noEmConfig.id}
            no={noEmConfig}
            totalBlocos={nodes.length}
            tags={tagsDoProjeto}
            podeMutar={podeMutar}
            onAplicar={aplicarConfig}
            onFechar={() => {
              setEmConfig(null);
            }}
          />
        )}
        {propsAbertas && (
          <FlowPropsModal flow={flow.data} onFechar={() => setPropsAbertas(false)} />
        )}
        {impacto !== null && (
          <DialogoImpacto
            impacto={impacto}
            onConfirmar={() => void executarAcaoPendente()}
            onCancelar={() => {
              acaoPendente.current = null;
              setImpacto(null);
            }}
          />
        )}
      </section>
    </ContextosDoEditor>
  );
}

/**
 * Editor de flow (RF-301..307, spec F3 §6.2), com o canvas ao vivo do RF-305: o socket
 * nasce e morre com esta página, e `key={id}` garante um por flow aberto.
 */
export function FlowEditorPage() {
  const { flowId } = useParams();
  const id = Number(flowId);
  if (!Number.isInteger(id) || id < 1) {
    return (
      <p role="alert" className="text-sm text-alarm">
        Flow inválido na URL.
      </p>
    );
  }
  return (
    <ReactFlowProvider>
      <Editor key={id} flowId={id} />
    </ReactFlowProvider>
  );
}
