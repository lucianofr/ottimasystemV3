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
import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent } from "react";
import { Link, useParams } from "react-router";

import { Button } from "../../components/ui/button";
import { Card } from "../../components/ui/card";
import { ApiError, type TagOut } from "../../lib/api";
import { useCanMutate } from "../auth/useAuth";
import { useConnections } from "../connections/useConnections";
import { useTags } from "../tags/useTags";
import { ModalConfigBloco } from "./config/ModalConfigBloco";
import { FlowPalette, MIME_BLOCO } from "./FlowPalette";
import {
  avisosInversao,
  compactarExecOrder,
  criarBloco,
  deGraphJson,
  definirExecOrder,
  handlesEntrada,
  handlesSaida,
  motivoRecusa,
  paraGraphJson,
  proximoExecOrder,
  TIPOS_BLOCO,
  type BlocoEdge,
  type BlocoNode,
  type MapaTags,
  type TipoBloco,
} from "./graph";
import { TIPOS_DE_NO } from "./nodes";
import { ContextoTags } from "./nodes/contexto";
import { formatarTs, useFlow, useSaveFlow } from "./useFlows";

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
    <li className={tom === "alarm" ? "text-alarm" : "text-warn"}>
      <span className="plaqueta mr-2 text-[10px]">{tom === "alarm" ? "Erro" : "Aviso"}</span>
      {texto}
    </li>
  );
}

function Editor({ flowId }: { flowId: number }) {
  const flow = useFlow(flowId);
  const salvar = useSaveFlow(flowId);
  const podeMutar = useCanMutate();

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

  const areaRef = useRef<HTMLDivElement>(null);
  const carregado = useRef<number | null>(null);
  const motivoRef = useRef<string | null>(null);
  const { screenToFlowPosition } = useReactFlow();

  // Carga única por flow: um refetch de fundo não pode atropelar o desenho em andamento.
  useEffect(() => {
    const detalhe = flow.data;
    if (detalhe === undefined || carregado.current === detalhe.id) return;
    carregado.current = detalhe.id;
    const grafo = deGraphJson(detalhe.graph_json);
    setNodes(grafo.nodes);
    setEdges(grafo.edges);
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
      const indice = nodes.length;
      adicionar(tipo, {
        x: ancora.x + (indice % 4) * 250,
        y: ancora.y + Math.floor(indice / 4) * 170,
      });
    },
    [adicionar, nodes.length, screenToFlowPosition],
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
    const entradas = handlesEntrada(atualizado);
    const saidas = handlesSaida(atualizado);
    setNodes((atuais) =>
      definirExecOrder(
        atuais.map((no) => (no.id === atualizado.id ? atualizado : no)),
        atualizado.id,
        execOrder,
      ),
    );
    // Encolher o Script deixaria arestas em portas que não existem mais (422 no save).
    setEdges((atuais) =>
      atuais.filter((aresta) => {
        if (aresta.source === atualizado.id && !saidas.includes(aresta.sourceHandle)) return false;
        if (aresta.target === atualizado.id && !entradas.includes(aresta.targetHandle)) return false;
        return true;
      }),
    );
    setAvisosServidor(null);
  }

  async function salvarGrafo(): Promise<void> {
    setErroSave(null);
    setRecusa(null);
    try {
      const salvo = await salvar.mutateAsync(paraGraphJson(nodes, edges));
      setAvisosServidor(salvo.warnings ?? []);
    } catch (err) {
      setAvisosServidor(null);
      setErroSave(erroLegivel(err));
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
    <ContextoTags.Provider value={porId}>
      <section className="flex h-[calc(100vh-9rem)] flex-col gap-3">
        <header className="flex items-center justify-between gap-4">
          <div className="flex items-baseline gap-3">
            <Link to="/engenharia/flows" className="plaqueta text-xs text-accent hover:underline">
              Flows
            </Link>
            <h1 className="plaqueta text-sm text-fg">{flow.data.name}</h1>
            <span className="text-xs text-fg-muted">
              Ts <span className="process-value text-fg">{formatarTs(flow.data.ts_seconds)}</span> s
              · <span className="process-value text-fg">{nodes.length}</span> bloco(s)
            </span>
          </div>
          {podeMutar && (
            <Button data-testid="flow-salvar" disabled={salvar.isPending} onClick={() => void salvarGrafo()}>
              {salvar.isPending ? "Salvando…" : "Salvar"}
            </Button>
          )}
        </header>

        {(recusa !== null || erroSave !== null || inversoes.length > 0 || avisosServidor !== null) && (
          <Card className="px-3 py-2">
            <ul className="space-y-1 text-xs" data-testid="editor-mensagens">
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
          {podeMutar && <FlowPalette onAdicionar={adicionarNoCentro} />}
          <div
            ref={areaRef}
            className="min-h-0 flex-1 overflow-hidden rounded-panel border border-hairline"
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
                setEmConfig(no.id);
              }}
              nodesDraggable={podeMutar}
              nodesConnectable={podeMutar}
              edgesReconnectable={false}
              deleteKeyCode={podeMutar ? ["Backspace", "Delete"] : null}
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

        {noEmConfig !== null && (
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
      </section>
    </ContextoTags.Provider>
  );
}

/**
 * Editor de flow (RF-301..307, spec F3 §6.2). O canvas ao vivo (WS, valores nas portas,
 * lâmpada de estado) é da tarefa 4.3 e entra neste mesmo arquivo.
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
