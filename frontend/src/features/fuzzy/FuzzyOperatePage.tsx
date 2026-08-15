import { useEffect, useMemo } from "react";
import { useSearchParams } from "react-router";

import { useAssinatura, useCanalAoVivo } from "../../app/CanalAoVivo";
import { Badge } from "../../components/ui/badge";
import { Card } from "../../components/ui/card";
import { Select } from "../../components/ui/select";
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
 * `?flow=&bloco=`, não path: ao contrário do MPC o bloco fuzzy é somente leitura, então não
 * há "sala de controle" por URL própria a preservar — a query string já sobrevive ao F5),
 * badges das normas do rule block e por saída, grade de painéis SVG (entradas à esquerda,
 * saídas à direita), tabela de regras e trend embaixo. Espelha a casca de `OperatePage.tsx`
 * sem reusar o código dela: o MPC tem faceplates/comandos que o fuzzy não tem — o bloco é
 * somente leitura (ADR-029), sem `POST` nenhum nesta tela.
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

  return (
    <div className="space-y-6">
      {introspection.rule_blocks.map((bloco) => (
        <BadgesRuleBlock key={bloco.name} bloco={bloco} />
      ))}

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
