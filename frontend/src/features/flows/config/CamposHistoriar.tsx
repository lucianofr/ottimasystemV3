import { useMemo, useState } from "react";

import { ApiError, type HistorizedVarOut } from "../../../lib/api";
import {
  handlesEntrada,
  handlesSaida,
  type BlocoEdge,
  type BlocoNode,
} from "../graph";
import {
  useCriarHistorizedVar,
  useHistorizedVars,
  useRemoverHistorizedVar,
} from "../useHistorizedVars";

interface PropsCamposHistoriar {
  no: BlocoNode;
  flowId: number;
  podeMutar: boolean;
  /** `no.id` ainda não existe no grafo salvo no servidor (bloco novo, sem Salvar): o backend
   *  recusa o cadastro com 422 — a seção inteira fica desabilitada até o próximo save. */
  blocoSalvo: boolean;
  /** Arestas do editor, recebidas por prop (o componente nunca refaz fetch do grafo). */
  arestas: readonly BlocoEdge[];
  /** EU da porta resolvida pelo editor (saída declarada ou herdada pela aresta): o cadastro
   *  congela nome E unidade (ADR-041 D6), e é essa unidade que o Trend mostra na legenda. */
  euDaPorta: (noId: string, porta: string) => string;
}

/** Registros de historização do bloco, indexados por porta — lógica pura testada em
 *  `historiar.check.ts`: um bug aqui é a diferença entre um checkbox mostrar o estado real do
 *  servidor ou mentir sobre ele. */
export function registroDoBloco(
  registros: readonly HistorizedVarOut[],
  blockId: string,
): ReadonlyMap<string, HistorizedVarOut> {
  const mapa = new Map<string, HistorizedVarOut>();
  for (const registro of registros) {
    if (registro.block_id === blockId) mapa.set(registro.port, registro);
  }
  return mapa;
}

/** Portas de ENTRADA do bloco que têm aresta chegando — lógica pura testada em
 *  `historiar.check.ts`. Porta de entrada SEM aresta fica COLD para sempre no runtime
 *  (ADR-041 D7): o backend recusa o cadastro com 422, então o checkbox correspondente
 *  precisa nascer desabilitado em vez de deixar o operador bater nele. */
export function portasComAresta(
  arestas: readonly BlocoEdge[],
  blockId: string,
): ReadonlySet<string> {
  const conjunto = new Set<string>();
  for (const aresta of arestas) {
    if (aresta.target === blockId) conjunto.add(aresta.targetHandle);
  }
  return conjunto;
}

/**
 * Seção "Historiar portas" do modal de config (ADR-041): marca/desmarca portas de
 * entrada/saída do bloco para gravação cíclica em `samples`. Estado e mutations PRÓPRIOS, fora
 * do `switch`/`onAplicar` do `ModalConfigBloco` — o flag não pode viajar em `node.data` (o
 * servidor rejeita chave desconhecida em `data` com 422, mesmo motivo de `nodes/contexto.ts`
 * manter tags/valores ao vivo fora de `data`).
 */
export function CamposHistoriar({
  no,
  flowId,
  podeMutar,
  blocoSalvo,
  arestas,
  euDaPorta,
}: PropsCamposHistoriar) {
  const historizadas = useHistorizedVars(flowId);
  const criar = useCriarHistorizedVar();
  const remover = useRemoverHistorizedVar();
  const [erro, setErro] = useState<string | null>(null);
  const [pendentes, setPendentes] = useState<ReadonlySet<string>>(new Set());

  const portasEntrada = handlesEntrada(no);
  const portasSaida = handlesSaida(no);

  const registroPorPorta = useMemo(
    () => registroDoBloco(historizadas.data ?? [], no.id),
    [historizadas.data, no.id],
  );
  const portasEntradaComAresta = useMemo(
    () => portasComAresta(arestas, no.id),
    [arestas, no.id],
  );

  async function alternar(
    porta: string,
    registro: HistorizedVarOut | undefined,
  ): Promise<void> {
    setErro(null);
    setPendentes((atuais) => new Set(atuais).add(porta));
    try {
      if (registro === undefined) {
        await criar.mutateAsync({
          flow_id: flowId,
          block_id: no.id,
          port: porta,
          eu: euDaPorta(no.id, porta),
        });
      } else {
        await remover.mutateAsync(registro.tag_id);
      }
    } catch (err) {
      setErro(
        err instanceof ApiError
          ? err.message
          : "Erro de comunicação com o servidor",
      );
    } finally {
      setPendentes((atuais) => {
        const proximo = new Set(atuais);
        proximo.delete(porta);
        return proximo;
      });
    }
  }

  function linha(porta: string, semAresta: boolean) {
    const registro = registroPorPorta.get(porta);
    const marcada = registro !== undefined;
    const fria = semAresta && !marcada;
    const travada = historizadas.isPending || pendentes.has(porta) || fria;
    const id = `historiar-${no.id}-${porta}`;
    const idMotivo = `${id}-motivo`;
    return (
      <label
        key={porta}
        className="flex items-center gap-2 text-xs text-fg"
        htmlFor={id}
      >
        <input
          type="checkbox"
          id={id}
          data-testid={`config-historiar-${porta}`}
          checked={marcada}
          disabled={travada}
          // `title` é tooltip de mouse; o motivo do travamento também precisa chegar a quem
          // navega por teclado/leitor de tela, daí o texto referenciado por aria-describedby.
          aria-describedby={fria ? idMotivo : undefined}
          onChange={() => void alternar(porta, registro)}
          className="h-3.5 w-3.5 accent-[var(--color-accent)]"
        />
        {porta}
        {marcada && <span className="text-fg-muted">· {registro.name}</span>}
        {fria && (
          <span id={idMotivo} className="text-[10px] text-fg-muted">
            (entrada sem aresta: conecte uma origem antes de historiar)
          </span>
        )}
      </label>
    );
  }

  return (
    <fieldset
      disabled={!podeMutar || !blocoSalvo}
      data-testid="config-historiar"
      className="space-y-2 border-t border-border pt-3"
    >
      <legend className="plaqueta text-xs text-fg-muted">
        Historiar portas
      </legend>
      <p className="text-[10px] leading-tight text-fg-muted">
        A porta marcada grava um valor a cada Ts do flow (no mínimo 1 s) e passa
        a aparecer na tela Trend.
      </p>
      {!blocoSalvo && (
        <p className="text-xs text-warn-fg">
          Salve o flow para historiar as portas deste bloco.
        </p>
      )}
      {erro !== null && (
        <p
          role="alert"
          data-testid="config-historiar-erro"
          className="text-xs text-alarm"
        >
          {erro}
        </p>
      )}
      {portasEntrada.length > 0 && (
        <div className="space-y-1">
          <p className="text-[10px] text-fg-muted">Entradas</p>
          <div className="grid grid-cols-2 gap-x-4 gap-y-1">
            {portasEntrada.map((porta) =>
              linha(porta, !portasEntradaComAresta.has(porta)),
            )}
          </div>
        </div>
      )}
      {portasSaida.length > 0 && (
        <div className="space-y-1">
          <p className="text-[10px] text-fg-muted">Saídas</p>
          <div className="grid grid-cols-2 gap-x-4 gap-y-1">
            {portasSaida.map((porta) => linha(porta, false))}
          </div>
        </div>
      )}
    </fieldset>
  );
}
