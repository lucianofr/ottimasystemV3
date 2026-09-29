import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useSearchParams } from "react-router";

import { useAssinatura, useCanalAoVivo } from "../../app/CanalAoVivo";
import { Badge } from "../../components/ui/badge";
import { Card } from "../../components/ui/card";
import { Select } from "../../components/ui/select";
import { ApiError, apiResposta } from "../../lib/api";
import { cn } from "../../lib/cn";
import { useActiveProject } from "../projects/useProjects";
import { PainelRegras } from "./PainelRegras";
import { PainelVariavelFuzzy } from "./PainelVariavelFuzzy";
import { TrendFuzzy } from "./TrendFuzzy";
import type { FuzzyNodeOut, FuzzyRuleBlockOut, FuzzyVarState } from "./types";
import { rotuloFuzzy, useFuzzyBlocks } from "./useFuzzyBlocks";
import { useFuzzyDetail } from "./useFuzzyDetail";

/**
 * FUZZY OPERATE (ADR-030) — combobox "Bloco fuzzy" do projeto ativo (seleção em query string
 * `?flow=&bloco=`, não path: ao contrário do MPC o bloco fuzzy não tem "sala de controle" por
 * URL própria a preservar — a query string já sobrevive ao F5), badges das normas do rule
 * block e por saída, grade de painéis SVG (entradas à esquerda, saídas à direita), tabela de
 * regras e trend embaixo. Espelha a casca de `OperatePage.tsx` sem reusar o código dela.
 *
 * O bloco é somente leitura EXCETO o SP (RF-541 revisado): com `setpoint` configurado no
 * bloco, o FLL declara uma variável de entrada a mais — a última, rotulada `SP` na
 * introspecção — e é ela que recebe o valor escrito aqui. Nada de lógica de controle no
 * cliente: o desvio mostrado é `sp − pv`, leitura de conveniência, não cálculo de malha
 * (ADR-005).
 */

function chaveNo(no: FuzzyNodeOut): string {
  return `${String(no.flow_id)}/${no.block_id}`;
}

function BadgesRuleBlock({ bloco }: { bloco: FuzzyRuleBlockOut }) {
  const itens = [
    ...(bloco.conjunction !== null ? [{ rotulo: "E", valor: bloco.conjunction }] : []),
    ...(bloco.disjunction !== null ? [{ rotulo: "OU", valor: bloco.disjunction }] : []),
    ...(bloco.implication !== null ? [{ rotulo: "Implicação", valor: bloco.implication }] : []),
    ...(bloco.activation !== null ? [{ rotulo: "Ativação", valor: bloco.activation }] : []),
  ];
  if (itens.length === 0) return null;
  return (
    <div className="flex flex-wrap items-center gap-1.5" data-testid="fuzzy-badges-rule-block">
      {itens.map((item) => (
        <Badge key={item.rotulo} tone="neutral" data-testid="fuzzy-badge-norma">
          {item.rotulo}: {item.valor}
        </Badge>
      ))}
    </div>
  );
}

/** Número em pt-BR com 2 casas fixas — mesma Regra do Número Tabular do resto da HMI. */
function formatarSp(valor: number | null): string {
  return valor === null ? "—" : valor.toFixed(2).replace(".", ",");
}

/**
 * Barra de SP do bloco fuzzy (RF-541 revisado). Mostra o SP **publicado** pelo runtime (não o
 * eco do comando — Regra do Estado Publicado), a medida da porta `IN1` e o desvio `sp − pv`,
 * e escreve o SP pela rota `/api/operate/{flow}/{block}/sp`. A faixa do campo vem da própria
 * variável do FLL, via introspecção do servidor (o cliente nunca parseia FLL).
 */
function BarraSp({
  sp,
  pv,
  minimo,
  maximo,
  escrevivel,
  aoEnviar,
}: {
  sp: number | null;
  pv: number | null;
  minimo: number;
  maximo: number;
  /** `false` no modo `sp_source='entrada'`: o SP vem do fio, a página só lê (o POST é 422). */
  escrevivel: boolean;
  aoEnviar: (valor: number) => Promise<string | null>;
}) {
  const [valor, setValor] = useState("");
  const [erro, setErro] = useState<string | null>(null);
  const desvio = sp !== null && pv !== null ? sp - pv : null;

  async function enviar(evento: FormEvent<HTMLFormElement>): Promise<void> {
    evento.preventDefault();
    const numero = Number(valor);
    if (!Number.isFinite(numero)) return;
    const problema = await aoEnviar(numero);
    setErro(problema);
    if (problema === null) setValor("");
  }

  return (
    <div
      data-testid="fuzzy-sp"
      className="flex flex-wrap items-end gap-x-4 gap-y-2 rounded-sm border border-border bg-surface-2 px-3 py-2"
    >
      <div className="flex items-baseline gap-1.5">
        <span className="text-xs text-fg-muted">SP</span>
        <span className="process-value text-sm" data-testid="fuzzy-sp-vigente">
          {formatarSp(sp)}
        </span>
      </div>
      <div className="flex items-baseline gap-1.5">
        <span className="text-xs text-fg-muted">PV (IN1)</span>
        <span className="process-value text-sm" data-testid="fuzzy-sp-pv">
          {formatarSp(pv)}
        </span>
      </div>
      <div className="flex items-baseline gap-1.5">
        <span className="text-xs text-fg-muted">desvio</span>
        <span
          className={cn(
            "process-value text-sm",
            desvio !== null && Math.abs(desvio) > 0.5 && "text-warn-fg",
          )}
          data-testid="fuzzy-sp-desvio"
        >
          {desvio === null ? "—" : `${desvio >= 0 ? "+" : "−"}${formatarSp(Math.abs(desvio))}`}
        </span>
      </div>
      {escrevivel ? (
        <form onSubmit={(e) => void enviar(e)} className="flex items-end gap-2">
          <label className="text-xs text-fg-muted" htmlFor="fuzzy-sp-input">
            Escrever SP
          </label>
          <input
            id="fuzzy-sp-input"
            data-testid="fuzzy-sp-input"
            type="number"
            step="any"
            min={minimo}
            max={maximo}
            value={valor}
            onChange={(e) => setValor(e.target.value)}
            className="process-value w-24 rounded-sm border border-border bg-surface px-2 py-1 text-xs"
          />
          <button
            type="submit"
            data-testid="fuzzy-sp-enviar"
            className="rounded-sm border border-border px-2 py-1 text-xs hover:bg-surface-2"
          >
            Enviar
          </button>
        </form>
      ) : (
        <p className="text-xs text-fg-muted" data-testid="fuzzy-sp-so-leitura">
          SP vem da entrada `sp` do flow (sp_source=&quot;entrada&quot;) — somente leitura aqui.
        </p>
      )}
      {erro !== null && (
        <p role="alert" data-testid="fuzzy-sp-erro" className="text-xs text-alarm">
          {erro}
        </p>
      )}
    </div>
  );
}

/** Bloco fuzzy resolvido: assina `fuzzy_state` do bloco (canal ao vivo) e busca a
 *  introspecção do FLL. `key` no componente pai força remonte ao trocar de bloco (mesmo
 *  padrão de `OperacaoDoMpc`/`OperatePage.tsx`): `useAssinatura` só lê o interesse do
 *  primeiro render. */
function FuzzyResolvido({ no }: { no: FuzzyNodeOut }) {
  const flowId = no.flow_id;
  const blockId = no.block_id;
  useAssinatura({ fuzzy_state: [`${String(flowId)}/${blockId}`] });
  const canal = useCanalAoVivo();
  const estado = canal.fuzzyStates.get(`${String(flowId)}/${blockId}`);
  const detalhe = useFuzzyDetail(flowId, blockId);

  /** POST do SP; devolve a mensagem de erro (ou `null` no sucesso) para a barra exibir. */
  async function enviarSp(valor: number): Promise<string | null> {
    try {
      await apiResposta(`/api/operate/${String(flowId)}/${blockId}/sp`, {
        method: "POST",
        body: JSON.stringify({ value: valor }),
      });
      return null;
    } catch (erro) {
      return erro instanceof ApiError ? erro.message : "Falha ao enviar o SP";
    }
  }

  const estadosPorPorta = useMemo(() => {
    const mapa = new Map<string, FuzzyVarState>();
    if (estado) {
      for (const v of estado.inputs) mapa.set(v.port, v);
      for (const v of estado.outputs) mapa.set(v.port, v);
    }
    return mapa;
  }, [estado]);

  if (detalhe.isPending) {
    return (
      <Card className="max-w-lg p-6" data-testid="fuzzy-carregando">
        <p className="text-sm text-fg-muted">Carregando…</p>
      </Card>
    );
  }

  if (detalhe.isError) {
    return (
      <Card className="max-w-lg p-6">
        <p role="alert" data-testid="fuzzy-erro-detalhe" className="text-sm text-alarm">
          Falha ao consultar o bloco fuzzy
        </p>
      </Card>
    );
  }

  const { introspection, output_eu: outputEu } = detalhe.data;
  const implicacao = introspection.rule_blocks[0]?.implication ?? null;
  const invalido = estado !== undefined && !estado.ok;
  // Com SP configurado, a introspecção rotula a última variável de entrada como `SP` — é o
  // mesmo server-side que alimenta o bloco, então a faixa do campo não vem do cliente.
  const varSp = introspection.inputs.find((variavel) => variavel.port === "SP") ?? null;
  const pv = estadosPorPorta.get("IN1")?.v ?? null;
  // Legado: `setpoint` cheio sem `sp_source` = operador. Sem nenhum dos dois, sem barra.
  const fonteSp =
    detalhe.data.sp_source ?? (detalhe.data.setpoint !== null ? "operador" : null);

  return (
    <div className="space-y-6">
      {introspection.rule_blocks.map((bloco) => (
        <BadgesRuleBlock key={bloco.name} bloco={bloco} />
      ))}

      {varSp !== null && (
        <BarraSp
          sp={estado?.sp ?? no.setpoint ?? null}
          pv={pv}
          minimo={varSp.minimum}
          maximo={varSp.maximum}
          escrevivel={fonteSp !== "entrada"}
          aoEnviar={enviarSp}
        />
      )}

      {invalido && (
        <p
          role="status"
          data-testid="fuzzy-aviso-invalido"
          className="rounded-md bg-warn-soft px-3 py-2 text-sm text-warn-fg"
        >
          Entradas inválidas
        </p>
      )}

      <div data-testid="fuzzy-paineis" className={cn("space-y-6", invalido && "opacity-40")}>
        <div data-testid="fuzzy-grade-variaveis" className="grid grid-cols-2 gap-4">
          <div className="space-y-4">
            {introspection.inputs.map((variavel) => (
              <PainelVariavelFuzzy
                key={variavel.port}
                variavel={variavel}
                estado={estadosPorPorta.get(variavel.port)}
                ehSaida={false}
                eu={null}
                implicacao={implicacao}
              />
            ))}
          </div>
          <div className="space-y-4">
            {introspection.outputs.map((variavel) => (
              <PainelVariavelFuzzy
                key={variavel.port}
                variavel={variavel}
                estado={estadosPorPorta.get(variavel.port)}
                ehSaida={true}
                eu={outputEu[variavel.port] ?? null}
                implicacao={implicacao}
              />
            ))}
          </div>
        </div>

        <PainelRegras ruleBlocks={introspection.rule_blocks} graus={estado?.rules} />
      </div>

      <TrendFuzzy flowId={flowId} blockId={blockId} no={no} estado={estado} />
    </div>
  );
}

export function FuzzyOperatePage() {
  const blocos = useFuzzyBlocks();
  const projeto = useActiveProject();
  const projectId = projeto.data?.id ?? null;
  const [searchParams, setSearchParams] = useSearchParams();
  const flowParam = searchParams.get("flow");
  const blocoParam = searchParams.get("bloco");

  const selecionado = useMemo(() => {
    if (!blocos.data || flowParam === null || blocoParam === null) return null;
    return blocos.data.find((no) => String(no.flow_id) === flowParam && no.block_id === blocoParam) ?? null;
  }, [blocos.data, flowParam, blocoParam]);

  // Sem seleção válida na URL (primeiro acesso, link sem parâmetros, bloco removido/trocou
  // de projeto): cai no primeiro bloco disponível — nunca a página em branco com blocos no ar.
  useEffect(() => {
    if (!blocos.isSuccess || blocos.data.length === 0) return;
    if (selecionado !== null) return;
    const primeiro = blocos.data[0];
    setSearchParams({ flow: String(primeiro.flow_id), bloco: primeiro.block_id }, { replace: true });
  }, [blocos.isSuccess, blocos.data, selecionado, setSearchParams]);

  return (
    <section className="space-y-4" data-testid="fuzzy-operate-page">
      <div className="flex items-center gap-3">
        <h1 className="plaqueta text-sm">Fuzzy</h1>
        <Select
          aria-label="Bloco fuzzy"
          data-testid="fuzzy-select-bloco"
          className="h-8 w-72"
          value={selecionado ? chaveNo(selecionado) : ""}
          onChange={(evento) => {
            const [flowId, blockId] = evento.target.value.split("/", 2);
            if (flowId && blockId) setSearchParams({ flow: flowId, bloco: blockId });
          }}
        >
          {selecionado === null && <option value="">Selecione um bloco</option>}
          {(blocos.data ?? []).map((no) => (
            <option key={chaveNo(no)} value={chaveNo(no)}>
              {rotuloFuzzy(no)}
            </option>
          ))}
        </Select>
      </div>

      {blocos.isPending && <p className="text-sm text-fg-muted">Carregando…</p>}
      {blocos.isError && (
        <p role="alert" data-testid="fuzzy-erro-blocos" className="text-sm text-alarm">
          Falha ao consultar blocos fuzzy
        </p>
      )}
      {blocos.isSuccess &&
        blocos.data.length === 0 &&
        projeto.isSuccess &&
        (projectId === null ? (
          <p data-testid="fuzzy-sem-projeto" className="text-sm text-fg-muted">
            Nenhum projeto ativo
          </p>
        ) : (
          <p data-testid="fuzzy-empty" className="text-sm text-fg-muted">
            Nenhum bloco fuzzy configurado no projeto ativo.
          </p>
        ))}

      {selecionado !== null && <FuzzyResolvido key={chaveNo(selecionado)} no={selecionado} />}
    </section>
  );
}
