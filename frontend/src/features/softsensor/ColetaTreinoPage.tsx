import { useEffect, useMemo, useRef, useState, type ChangeEvent, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router";

import { Button } from "../../components/ui/button";
import { Card } from "../../components/ui/card";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select } from "../../components/ui/select";
import { ApiError } from "../../lib/api";
import { useCanMutate } from "../auth/useAuth";
import { useConnections } from "../connections/useConnections";
import { paraIsoUtc } from "../events/eventos";
import { useActiveProject } from "../projects/useProjects";
import { referenciaPersistidaS } from "../trend/bordaViva";
import type { EscalaVar } from "../trend/escalas";
import { tagDoProjeto } from "../trend/tagsDoProjeto";
import { TrendChart } from "../trend/TrendChart";
import { LIMITE_PENAS } from "../trend/trendTheme";
import { montarMatriz, useHistory, useTags } from "../trend/useHistory";
import {
  agoraLocal,
  alternarEntrada,
  janelaAoVivoDefasada,
  janelaDoConjunto,
  PERIODOS_S,
  podeExcluir,
  podeFinalizar,
  podeRefazer,
  progressoDoJob,
  resumoPareamento,
  temJobAtivo,
  TETO_ENTRADAS,
} from "./coleta";
import type { DatasetCreated, DatasetOut, MlJobOut } from "./types";
import { useCreateDataset, useDatasets, useDeleteDataset, useFinalizeDataset } from "./useDatasets";
import { useCancelJob, useJobs } from "./useJobs";
import { useAddLabSample, useDeleteLabSample, useImportLabSamples, useLabSamples } from "./useLabSamples";
import { useCreateLabVariable, useLabVariables } from "./useLabVariables";

const ROTULO_STATUS: Record<string, string> = {
  collecting: "coletando",
  building: "montando",
  ready: "pronto",
  failed: "falhou",
};

const ROTULO_ORIGEM: Record<string, string> = { manual: "Manual", csv: "CSV" };

/** Sem escala fixada: o trend das entradas é visão geral, em autoescala. */
const ESCALAS_AUTO: Readonly<Record<string, EscalaVar>> = {};

function mensagem(erro: unknown): string {
  return erro instanceof ApiError ? erro.message : "Erro de comunicação com o servidor";
}

function quando(iso: string): string {
  return new Date(iso).toLocaleString("pt-BR");
}

// ------------------------------------------------------------------------- novo conjunto

interface NovoConjuntoProps {
  projectId: number;
  onCriado: (conjunto: DatasetCreated) => void;
  onFechar: () => void;
}

/** Formulário inline (admin): sem modal, no padrão do `ConnectionForm`. */
function NovoConjunto({ projectId, onCriado, onFechar }: NovoConjuntoProps) {
  const variaveis = useLabVariables();
  const criarVariavel = useCreateLabVariable();
  const criarConjunto = useCreateDataset();
  const conexoes = useConnections(projectId);
  const tags = useTags();

  const [nome, setNome] = useState("");
  const [variavelId, setVariavelId] = useState<number | null>(null);
  const [entradas, setEntradas] = useState<readonly number[]>([]);
  const [periodo, setPeriodo] = useState<number>(60);
  const [inicio, setInicio] = useState(agoraLocal);
  const [erro, setErro] = useState<string | null>(null);
  const [avisoTeto, setAvisoTeto] = useState(false);

  const [nova, setNova] = useState<{ nome: string; eu: string; descricao: string } | null>(null);
  const [erroNova, setErroNova] = useState<string | null>(null);

  // Mesmo recorte do seletor do Trend: tag OPC pertence ao projeto pela conexão, calculada direto.
  const idsConexao = new Set((conexoes.data ?? []).map((conexao) => conexao.id));
  const listaTags = (tags.data ?? []).filter((tag) => tagDoProjeto(tag, idsConexao, projectId));

  function alternar(tagId: number): void {
    const proximas = alternarEntrada(entradas, tagId);
    setAvisoTeto(proximas === entradas);
    setEntradas(proximas);
  }

  async function enviar(evento: FormEvent): Promise<void> {
    evento.preventDefault();
    const startTs = inicio === "" ? null : paraIsoUtc(inicio);
    if (variavelId === null || startTs === null) return;
    setErro(null);
    try {
      const criado = await criarConjunto.mutateAsync({
        name: nome.trim(),
        lab_variable_id: variavelId,
        input_tag_ids: [...entradas],
        period_s: periodo,
        start_ts: startTs,
      });
      onCriado(criado);
    } catch (err) {
      setErro(mensagem(err));
    }
  }

  async function enviarNova(evento: FormEvent): Promise<void> {
    evento.preventDefault();
    if (nova === null) return;
    setErroNova(null);
    try {
      const criada = await criarVariavel.mutateAsync({
        name: nova.nome,
        eu: nova.eu,
        description: nova.descricao,
      });
      setVariavelId(criada.id);
      setNova(null);
    } catch (err) {
      setErroNova(mensagem(err));
    }
  }

  const completo = nome.trim() !== "" && variavelId !== null && entradas.length > 0 && inicio !== "";

  return (
    <Card data-testid="sv-coleta-form" className="space-y-4 p-6">
      <form className="space-y-4" onSubmit={(evento) => void enviar(evento)}>
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-1.5">
            <Label htmlFor="sv-coleta-nome">Nome</Label>
            <Input
              id="sv-coleta-nome"
              data-testid="sv-coleta-nome"
              value={nome}
              onChange={(e) => setNome(e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="sv-coleta-variavel">Variável de laboratório</Label>
            <div className="flex items-center gap-2">
              <Select
                id="sv-coleta-variavel"
                data-testid="sv-coleta-variavel"
                value={variavelId === null ? "" : String(variavelId)}
                onChange={(e) => setVariavelId(e.target.value === "" ? null : Number(e.target.value))}
              >
                <option value="">Selecione a variável</option>
                {(variaveis.data ?? []).map((variavel) => (
                  <option key={variavel.id} value={String(variavel.id)}>
                    {variavel.eu === "" ? variavel.name : `${variavel.name} (${variavel.eu})`}
                  </option>
                ))}
              </Select>
              <Button
                type="button"
                variant="outline"
                size="sm"
                data-testid="sv-coleta-nova-variavel"
                className="shrink-0"
                onClick={() => setNova(nova === null ? { nome: "", eu: "", descricao: "" } : null)}
              >
                Nova variável
              </Button>
            </div>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="sv-coleta-periodo">Período do modelo</Label>
            <Select
              id="sv-coleta-periodo"
              data-testid="sv-coleta-periodo"
              value={String(periodo)}
              onChange={(e) => setPeriodo(Number(e.target.value))}
            >
              {PERIODOS_S.map((segundos) => (
                <option key={segundos} value={String(segundos)}>
                  {String(segundos)} s
                </option>
              ))}
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="sv-coleta-inicio">Início</Label>
            <div className="flex items-center gap-2">
              <Input
                id="sv-coleta-inicio"
                data-testid="sv-coleta-inicio"
                type="datetime-local"
                value={inicio}
                onChange={(e) => setInicio(e.target.value)}
              />
              <Button
                type="button"
                variant="outline"
                size="sm"
                data-testid="sv-coleta-inicio-agora"
                className="shrink-0"
                onClick={() => setInicio(agoraLocal())}
              >
                Agora
              </Button>
            </div>
          </div>
        </div>

        <div className="space-y-1.5">
          <Label>
            Entradas ({String(entradas.length)}/{String(TETO_ENTRADAS)}) — na ordem em que forem
            marcadas
          </Label>
          {tags.isError && (
            <p role="alert" className="text-sm text-alarm">
              Falha ao consultar tags
            </p>
          )}
          {tags.isSuccess && conexoes.isSuccess && listaTags.length === 0 && (
            <p className="text-sm text-fg-muted">Nenhuma tag cadastrada</p>
          )}
          <div data-testid="sv-coleta-entradas" className="max-h-64 overflow-y-auto rounded-md border border-border px-3">
            {listaTags.map((tag) => {
              const posicao = entradas.indexOf(tag.id);
              return (
                <label
                  key={tag.id}
                  data-testid="sv-coleta-entrada"
                  data-tag-id={tag.id}
                  className="flex cursor-pointer items-center gap-2 border-b border-border py-1.5 last:border-b-0"
                >
                  <input
                    type="checkbox"
                    className="accent-accent"
                    checked={posicao >= 0}
                    onChange={() => alternar(tag.id)}
                  />
                  <span className="plaqueta grow text-xs">{tag.name}</span>
                  {posicao >= 0 && (
                    <span className="process-value text-xs text-accent">#{String(posicao + 1)}</span>
                  )}
                  <span className="text-xs text-fg-muted">{tag.eu}</span>
                </label>
              );
            })}
          </div>
          {avisoTeto && (
            <p role="alert" className="text-xs text-warn-fg">
              Máximo de {String(TETO_ENTRADAS)} entradas por conjunto
            </p>
          )}
        </div>

        {erro && (
          <p role="alert" data-testid="sv-coleta-form-erro" className="text-sm text-alarm">
            {erro}
          </p>
        )}
        <div className="flex items-center gap-2">
          <Button
            type="submit"
            data-testid="sv-coleta-iniciar"
            disabled={!completo || criarConjunto.isPending}
          >
            Iniciar coleta
          </Button>
          <Button type="button" variant="outline" onClick={onFechar}>
            Fechar
          </Button>
        </div>
      </form>

      {/* Fora do <form> acima: formulário aninhado é HTML inválido. */}
      {nova !== null && (
        <form
          data-testid="sv-coleta-nova-variavel-form"
          className="space-y-3 border-t border-border pt-4"
          onSubmit={(evento) => void enviarNova(evento)}
        >
          <p className="plaqueta text-xs text-fg-muted">Nova variável de laboratório</p>
          <div className="grid grid-cols-3 gap-4">
            <div className="space-y-1.5">
              <Label htmlFor="sv-coleta-nova-nome">Nome</Label>
              <Input
                id="sv-coleta-nova-nome"
                data-testid="sv-coleta-nova-nome"
                value={nova.nome}
                onChange={(e) => setNova({ ...nova, nome: e.target.value })}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="sv-coleta-nova-eu">Unidade</Label>
              <Input
                id="sv-coleta-nova-eu"
                data-testid="sv-coleta-nova-eu"
                value={nova.eu}
                onChange={(e) => setNova({ ...nova, eu: e.target.value })}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="sv-coleta-nova-descricao">Descrição</Label>
              <Input
                id="sv-coleta-nova-descricao"
                data-testid="sv-coleta-nova-descricao"
                value={nova.descricao}
                onChange={(e) => setNova({ ...nova, descricao: e.target.value })}
              />
            </div>
          </div>
          {erroNova && (
            <p role="alert" data-testid="sv-coleta-nova-erro" className="text-sm text-alarm">
              {erroNova}
            </p>
          )}
          <Button
            type="submit"
            size="sm"
            data-testid="sv-coleta-nova-criar"
            disabled={nova.nome.trim() === "" || criarVariavel.isPending}
          >
            Criar variável
          </Button>
        </form>
      )}
    </Card>
  );
}

// ------------------------------------------------------------------ tendência das entradas

function TendenciaEntradas({ conjunto }: { conjunto: DatasetOut }) {
  const tags = useTags();
  const ids = conjunto.input_tag_ids.slice(0, LIMITE_PENAS);
  const chaveIds = ids.join(",");
  const { start_ts: inicio, end_ts: fim } = conjunto;
  // A largura da janela é chave de cache e de estrutura do gráfico: só muda quando `calculadaEm`
  // muda, e isso só acontece no tique grosso abaixo (`janelaAoVivoDefasada`), nunca por render.
  const [calculadaEm, setCalculadaEm] = useState(() => Date.now());
  const { janelaSegundos, fimEpochS } = useMemo(
    () => janelaDoConjunto({ start_ts: inicio, end_ts: fim }, calculadaEm),
    [inicio, fim, calculadaEm],
  );
  useEffect(() => {
    if (fim !== null) return;
    const id = setInterval(() => {
      const agora = Date.now();
      setCalculadaEm((atual) =>
        janelaAoVivoDefasada({ start_ts: inicio, end_ts: fim }, janelaSegundos, atual, agora)
          ? agora
          : atual,
      );
    }, 30_000);
    return () => clearInterval(id);
  }, [inicio, fim, janelaSegundos]);
  const historico = useHistory(ids, janelaSegundos, fimEpochS);
  const dados = useMemo(
    () =>
      historico.data
        ? montarMatriz(historico.data, ids, referenciaPersistidaS(historico.data.series))
        : null,
    // `ids` é recriado a cada render; a chave textual é a identidade real da seleção.
    [historico.data, chaveIds],
  );
  const porId = new Map((tags.data ?? []).map((tag) => [tag.id, tag]));
  const rotulos = ids.map((id) => porId.get(id)?.name ?? String(id));

  return (
    <div data-testid="sv-coleta-trend" className="space-y-2">
      <h2 className="plaqueta text-xs text-fg-muted">Tendência das entradas</h2>
      {conjunto.input_tag_ids.length > ids.length && (
        <p className="text-xs text-fg-muted">
          Exibindo as primeiras {String(ids.length)} de {String(conjunto.input_tag_ids.length)}{" "}
          entradas.
        </p>
      )}
      {historico.isError && (
        <p role="alert" className="text-sm text-alarm">
          {historico.error.message}
        </p>
      )}
      {dados === null && !historico.isError && (
        <p className="text-sm text-fg-muted">Carregando…</p>
      )}
      {dados !== null && (
        <TrendChart
          dados={dados}
          ids={ids}
          rotulos={rotulos}
          janelaSegundos={janelaSegundos}
          fimEpochS={fimEpochS}
          escalas={ESCALAS_AUTO}
          foco={ids[0] ?? null}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------- análises

interface AnalisesProps {
  variavelId: number;
  nome: string;
  eu: string;
}

function Analises({ variavelId, nome, eu }: AnalisesProps) {
  const amostras = useLabSamples(variavelId);
  const adicionar = useAddLabSample(variavelId);
  const apagar = useDeleteLabSample(variavelId);
  const importarCsv = useImportLabSamples();
  const inputRef = useRef<HTMLInputElement>(null);

  const [valor, setValor] = useState("");
  const [coleta, setColeta] = useState(agoraLocal);
  const [erro, setErro] = useState<string | null>(null);
  const [aApagar, setAApagar] = useState<string | null>(null);
  const [resumoImport, setResumoImport] = useState<string | null>(null);
  const [errosImport, setErrosImport] = useState<string[]>([]);

  async function enviar(evento: FormEvent): Promise<void> {
    evento.preventDefault();
    setErro(null);
    const numero = Number(valor);
    if (valor.trim() === "" || !Number.isFinite(numero)) {
      setErro("Informe um valor numérico");
      return;
    }
    const sampledAt = coleta === "" ? null : paraIsoUtc(coleta);
    if (sampledAt === null) {
      setErro("Informe a data da coleta");
      return;
    }
    try {
      await adicionar.mutateAsync({ value: numero, sampled_at: sampledAt });
      setValor("");
      setColeta(agoraLocal());
    } catch (err) {
      setErro(mensagem(err));
    }
  }

  async function confirmarExclusao(sampledAt: string): Promise<void> {
    setErro(null);
    try {
      await apagar.mutateAsync(sampledAt);
      setAApagar(null);
    } catch (err) {
      setErro(mensagem(err));
    }
  }

  async function aoEscolherArquivo(evento: ChangeEvent<HTMLInputElement>): Promise<void> {
    const arquivo = evento.target.files?.[0];
    evento.target.value = ""; // permite reenviar o mesmo arquivo depois de corrigi-lo
    if (arquivo === undefined) return;
    setResumoImport(null);
    setErrosImport([]);
    try {
      const resultado = await importarCsv.mutateAsync(arquivo);
      const porVariavel = Object.entries(resultado.by_variable)
        .map(([variavel, n]) => `${variavel}: ${String(n)}`)
        .join("; ");
      setResumoImport(
        `${String(resultado.imported)} ${resultado.imported === 1 ? "análise importada" : "análises importadas"}${porVariavel === "" ? "" : ` (${porVariavel})`}`,
      );
    } catch (err) {
      // O 422 lista TODOS os problemas do arquivo, separados por "; ": um por linha para ler.
      setErrosImport(mensagem(err).split("; "));
    }
  }

  const linhas = [...(amostras.data ?? [])].reverse(); // mais recentes primeiro

  return (
    <div data-testid="sv-coleta-analises" className="space-y-3">
      <h2 className="plaqueta text-xs text-fg-muted">Análises de {nome}</h2>

      <form className="flex flex-wrap items-end gap-3" onSubmit={(evento) => void enviar(evento)}>
        <div className="space-y-1.5">
          <Label htmlFor="sv-coleta-valor">Valor{eu === "" ? "" : ` (${eu})`}</Label>
          <Input
            id="sv-coleta-valor"
            data-testid="sv-coleta-valor"
            type="number"
            step="any"
            className="w-36"
            value={valor}
            onChange={(e) => setValor(e.target.value)}
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="sv-coleta-data">Data da coleta</Label>
          <Input
            id="sv-coleta-data"
            data-testid="sv-coleta-data"
            type="datetime-local"
            className="w-56"
            value={coleta}
            onChange={(e) => setColeta(e.target.value)}
          />
        </div>
        <Button
          type="submit"
          size="sm"
          data-testid="sv-coleta-add-analise"
          disabled={adicionar.isPending}
        >
          Adicionar
        </Button>
        <input
          ref={inputRef}
          type="file"
          accept=".csv,text/csv"
          data-testid="sv-coleta-csv-input"
          className="sr-only"
          onChange={(evento) => void aoEscolherArquivo(evento)}
        />
        <Button
          type="button"
          variant="outline"
          size="sm"
          data-testid="sv-coleta-importar"
          disabled={importarCsv.isPending}
          onClick={() => inputRef.current?.click()}
        >
          Importar CSV
        </Button>
      </form>

      {erro && (
        <p role="alert" data-testid="sv-coleta-analise-erro" className="text-sm text-alarm">
          {erro}
        </p>
      )}
      {resumoImport && (
        <p role="status" data-testid="sv-coleta-import-ok" className="text-sm text-fg-muted">
          {resumoImport}
        </p>
      )}
      {errosImport.length > 0 && (
        <ul role="alert" data-testid="sv-coleta-import-erro" className="space-y-0.5 text-sm text-alarm">
          {errosImport.map((problema, i) => (
            <li key={`${String(i)}-${problema}`}>{problema}</li>
          ))}
        </ul>
      )}

      <Card className="max-h-96 overflow-auto">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="border-b border-border bg-surface-2">
              <th className="plaqueta px-4 py-3 text-left text-xs text-fg-muted">Coleta</th>
              <th className="plaqueta px-4 py-3 text-left text-xs text-fg-muted">Valor</th>
              <th className="plaqueta px-4 py-3 text-left text-xs text-fg-muted">Origem</th>
              <th className="px-3 py-2">
                <span className="sr-only">Ações</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {amostras.isPending && (
              <tr>
                <td colSpan={4} className="px-3 py-4 text-fg-muted">
                  Carregando…
                </td>
              </tr>
            )}
            {amostras.isError && (
              <tr>
                <td colSpan={4} className="px-3 py-4 text-alarm" role="alert">
                  Falha ao consultar análises
                </td>
              </tr>
            )}
            {amostras.isSuccess && linhas.length === 0 && (
              <tr>
                <td colSpan={4} className="px-3 py-4 text-fg-muted">
                  Nenhuma análise lançada
                </td>
              </tr>
            )}
            {linhas.map((amostra) => (
              <tr
                key={amostra.sampled_at}
                data-testid="sv-coleta-analise-row"
                className="border-b border-border transition-colors duration-[var(--duration-fast)] hover:bg-surface-2"
              >
                <td className="px-3 py-2">{quando(amostra.sampled_at)}</td>
                <td className="process-value px-3 py-2">{String(amostra.value)}</td>
                <td className="px-3 py-2">{ROTULO_ORIGEM[amostra.source] ?? amostra.source}</td>
                <td className="px-3 py-2">
                  {aApagar === amostra.sampled_at ? (
                    <div className="flex items-center justify-end gap-2">
                      <span className="text-xs text-fg-muted">Apagar esta análise?</span>
                      <Button
                        variant="destructive"
                        size="sm"
                        data-testid="sv-coleta-apagar-confirmar"
                        disabled={apagar.isPending}
                        onClick={() => void confirmarExclusao(amostra.sampled_at)}
                      >
                        Confirmar
                      </Button>
                      <Button variant="outline" size="sm" onClick={() => setAApagar(null)}>
                        Cancelar
                      </Button>
                    </div>
                  ) : (
                    <div className="flex justify-end">
                      <Button
                        variant="ghost"
                        size="sm"
                        data-testid="sv-coleta-apagar"
                        onClick={() => setAApagar(amostra.sampled_at)}
                      >
                        Apagar
                      </Button>
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}

// --------------------------------------------------------------------------- rodapé

type Confirmacao = "finalizar" | "cancelar" | "excluir";

const PERGUNTA: Record<Confirmacao, string> = {
  finalizar: "Fechar o período agora e montar o conjunto?",
  cancelar: "Cancelar a montagem? O conjunto ficará como “falhou”; dá para tentar de novo.",
  excluir: "Excluir este conjunto de treino?",
};

interface RodapeProps {
  conjunto: DatasetOut;
  job: MlJobOut | undefined;
  /** Depois de excluir o conjunto o pai larga `?conjunto=` (a seleção apontaria para o nada). */
  onExcluido: () => void;
}

function RodapeConjunto({ conjunto, job, onExcluido }: RodapeProps) {
  const podeMutar = useCanMutate();
  const finalizar = useFinalizeDataset();
  const cancelar = useCancelJob();
  const excluir = useDeleteDataset();
  // Uma confirmação por vez: as três ações são destrutivas ou fecham o período.
  const [confirmando, setConfirmando] = useState<Confirmacao | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  async function executar(acao: () => Promise<unknown>): Promise<void> {
    setErro(null);
    try {
      await acao();
      setConfirmando(null);
    } catch (err) {
      setErro(mensagem(err));
    }
  }

  async function confirmar(): Promise<void> {
    if (confirmando === "finalizar") await executar(() => finalizar.mutateAsync(conjunto.id));
    if (confirmando === "cancelar" && job !== undefined) {
      await executar(() => cancelar.mutateAsync(job.id));
    }
    if (confirmando === "excluir") {
      await executar(async () => {
        await excluir.mutateAsync(conjunto.id);
        onExcluido();
      });
    }
  }

  const progresso = job === undefined ? null : progressoDoJob(job);
  const falha =
    job?.error ?? (job?.status === "cancelled" ? "Montagem cancelada" : "Falha na montagem do conjunto");
  const pendente = finalizar.isPending || cancelar.isPending || excluir.isPending;
  const jobAtivo = conjunto.status === "building" && job !== undefined && temJobAtivo([job]);

  return (
    <Card data-testid="sv-coleta-rodape" className="space-y-3 p-4">
      <div className="flex flex-wrap items-center gap-3">
        {conjunto.status === "collecting" && (
          <p data-testid="sv-coleta-estado" className="text-sm">
            Coletando desde {quando(conjunto.start_ts)}
          </p>
        )}
        {conjunto.status === "building" && (
          <div data-testid="sv-coleta-estado" className="flex items-center gap-3 text-sm">
            <span>Montando o conjunto</span>
            <progress
              data-testid="sv-coleta-progresso"
              aria-label="Progresso da montagem"
              className="w-64"
              value={progresso?.feito}
              max={progresso?.total}
            />
            {progresso && (
              <span className="process-value text-xs text-fg-muted">
                {String(progresso.feito)} de {String(progresso.total)}
              </span>
            )}
          </div>
        )}
        {conjunto.status === "ready" && (
          <p data-testid="sv-coleta-estado" className="text-sm">
            {resumoPareamento(conjunto.stats)}
          </p>
        )}
        {conjunto.status === "failed" && (
          <p data-testid="sv-coleta-estado" role="alert" className="text-sm text-alarm">
            {falha}
          </p>
        )}

        {podeMutar && confirmando !== null && (
          <div className="ml-auto flex items-center gap-2">
            <span className="text-xs text-fg-muted">{PERGUNTA[confirmando]}</span>
            <Button
              size="sm"
              variant={confirmando === "excluir" ? "destructive" : "primary"}
              data-testid={`sv-coleta-${confirmando}-confirmar`}
              disabled={pendente}
              onClick={() => void confirmar()}
            >
              Confirmar
            </Button>
            <Button
              variant="outline"
              size="sm"
              data-testid={`sv-coleta-${confirmando}-voltar`}
              onClick={() => setConfirmando(null)}
            >
              Voltar
            </Button>
          </div>
        )}
        {podeMutar && confirmando === null && (
          <div className="ml-auto flex items-center gap-2">
            {podeFinalizar(conjunto) && (
              <Button
                data-testid="sv-coleta-finalizar"
                size="sm"
                onClick={() => setConfirmando("finalizar")}
              >
                Finalizar
              </Button>
            )}
            {podeRefazer(conjunto) && (
              <Button
                data-testid="sv-coleta-refazer"
                size="sm"
                disabled={pendente}
                onClick={() => void executar(() => finalizar.mutateAsync(conjunto.id))}
              >
                Tentar de novo
              </Button>
            )}
            {jobAtivo && (
              <Button
                variant="outline"
                size="sm"
                data-testid="sv-coleta-cancelar"
                onClick={() => setConfirmando("cancelar")}
              >
                Cancelar
              </Button>
            )}
            {podeExcluir(conjunto) && (
              <Button
                variant="outline"
                size="sm"
                data-testid="sv-coleta-excluir"
                onClick={() => setConfirmando("excluir")}
              >
                Excluir conjunto
              </Button>
            )}
          </div>
        )}
      </div>
      {erro && (
        <p role="alert" data-testid="sv-coleta-rodape-erro" className="text-sm text-alarm">
          {erro}
        </p>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------------------- página

export function ColetaTreinoPage() {
  const projeto = useActiveProject();
  const projectId = projeto.data?.id ?? null;
  const podeMutar = useCanMutate();
  const conjuntos = useDatasets();
  const jobs = useJobs(false);
  const variaveis = useLabVariables();
  const [searchParams, setSearchParams] = useSearchParams();
  const [formAberto, setFormAberto] = useState(false);
  const [avisos, setAvisos] = useState<string[]>([]);

  const conjuntoParam = searchParams.get("conjunto");
  const lista = conjuntos.data ?? [];
  const selecionado = lista.find((conjunto) => String(conjunto.id) === conjuntoParam) ?? null;
  const primeiro = lista[0];

  // Sem seleção válida na URL (primeiro acesso, conjunto de outro projeto): cai no primeiro.
  useEffect(() => {
    if (!conjuntos.isSuccess || selecionado !== null || primeiro === undefined) return;
    setSearchParams({ conjunto: String(primeiro.id) }, { replace: true });
  }, [conjuntos.isSuccess, selecionado, primeiro, setSearchParams]);

  if (projeto.isSuccess && projectId === null) {
    return (
      <section className="space-y-4">
        <h1 className="plaqueta text-sm">Sensor virtual · Coleta e treino</h1>
        <p data-testid="sv-coleta-sem-projeto" className="text-sm text-fg-muted">
          Nenhum projeto ativo:{" "}
          <Link to="/engenharia/projetos" className="text-accent hover:underline">
            ative um projeto
          </Link>{" "}
          para coletar análises.
        </p>
      </section>
    );
  }

  // O job mais novo (a lista vem do mais novo para o mais antigo) que monta este conjunto.
  const job =
    selecionado === null
      ? undefined
      : jobs.data?.find(
          (candidato) =>
            candidato.kind === "dataset_build" && candidato.params.dataset_id === selecionado.id,
        );
  const eu = variaveis.data?.find((v) => v.id === selecionado?.lab_variable_id)?.eu ?? "";

  return (
    <section className="space-y-4" data-testid="sv-coleta-page">
      <div className="flex items-center gap-3">
        <h1 className="plaqueta text-sm">Sensor virtual · Coleta e treino</h1>
        <Select
          aria-label="Conjunto de treino"
          data-testid="sv-coleta-select-conjunto"
          className="h-8 w-72"
          value={selecionado === null ? "" : String(selecionado.id)}
          onChange={(evento) => setSearchParams({ conjunto: evento.target.value })}
        >
          {selecionado === null && (
            <option value="">{lista.length === 0 ? "Nenhum conjunto" : "Selecione um conjunto"}</option>
          )}
          {lista.map((conjunto) => (
            <option key={conjunto.id} value={String(conjunto.id)}>
              {conjunto.name} · {ROTULO_STATUS[conjunto.status] ?? conjunto.status}
            </option>
          ))}
        </Select>
        {podeMutar && (
          <Button
            data-testid="sv-coleta-novo"
            disabled={projectId === null}
            onClick={() => {
              setAvisos([]);
              setFormAberto(true);
            }}
          >
            Novo conjunto
          </Button>
        )}
      </div>

      {podeMutar && formAberto && projectId !== null && (
        <NovoConjunto
          projectId={projectId}
          onCriado={(criado) => {
            setSearchParams({ conjunto: String(criado.id) });
            setAvisos(criado.warnings);
            setFormAberto(false);
          }}
          onFechar={() => setFormAberto(false)}
        />
      )}
      {avisos.length > 0 && (
        <div role="status" data-testid="sv-coleta-avisos" className="space-y-0.5 text-sm text-warn-fg">
          {avisos.map((aviso) => (
            <p key={aviso}>{aviso}</p>
          ))}
        </div>
      )}

      {conjuntos.isError && (
        <p role="alert" className="text-sm text-alarm">
          Falha ao consultar conjuntos
        </p>
      )}
      {conjuntos.isSuccess && lista.length === 0 && (
        <Card className="p-6">
          <p data-testid="sv-coleta-vazio" className="text-sm text-fg-muted">
            {podeMutar
              ? "Nenhum conjunto de treino: use “Novo conjunto” para iniciar uma coleta."
              : "Nenhum conjunto de treino: peça a um administrador para iniciar uma coleta."}
          </p>
        </Card>
      )}

      {selecionado !== null && (
        <>
          <p className="text-xs text-fg-muted">
            Variável de laboratório: {selecionado.lab_variable_name} · período{" "}
            {String(selecionado.period_s)} s · {String(selecionado.input_tag_ids.length)} entradas
          </p>
          <TendenciaEntradas key={selecionado.id} conjunto={selecionado} />
          <Analises
            key={`analises-${String(selecionado.id)}`}
            variavelId={selecionado.lab_variable_id}
            nome={selecionado.lab_variable_name}
            eu={eu}
          />
          <RodapeConjunto
            key={`rodape-${String(selecionado.id)}`}
            conjunto={selecionado}
            job={job}
            onExcluido={() => setSearchParams({}, { replace: true })}
          />
        </>
      )}
    </section>
  );
}
