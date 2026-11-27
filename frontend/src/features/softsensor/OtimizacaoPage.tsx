import { useState, type FormEvent } from "react";
import { Link } from "react-router";

import { Button } from "../../components/ui/button";
import { Card } from "../../components/ui/card";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select } from "../../components/ui/select";
import { SOFT_SENSOR_SEARCH_SPACE } from "../../lib/contracts.gen";
import { useCanMutate } from "../auth/useAuth";
import { mensagem, temJobAtivo } from "./coleta";
import {
  conjuntosCompativeis,
  descricaoDaFaixa,
  formatarMetrica,
  linhasDeTentativas,
  METODOS,
  progressoDaBusca,
  resultadoDaBusca,
  type MetodoSensor,
} from "./treino";
import type { DatasetOut, MlJobOut } from "./types";
import { useDatasets } from "./useDatasets";
import { useCancelJob, useEnqueueTrain, useJobsDoConjunto } from "./useJobs";

const CABECALHO = "plaqueta px-3 py-2 text-left text-xs text-fg-muted";

/** Limites de `TuneJobIn` (RF-588): o servidor reconfere e devolve o 422 em pt-BR. */
const TENTATIVAS_MIN = 10;
const TENTATIVAS_MAX = 500;

/** Texto digitado -> número dentro de `[minimo, maximo]`, ou `null` (vazio, texto ou fora). */
function numeroEntre(texto: string, minimo: number, maximo: number): number | null {
  const valor = texto.trim() === "" ? Number.NaN : Number(texto);
  return valor >= minimo && valor <= maximo ? valor : null;
}

// ------------------------------------------------------------------------------ formulário

interface FormularioBuscaProps {
  base: DatasetOut;
  conjuntos: readonly DatasetOut[];
  /** O job `tune` mais novo do conjunto base: é o que "Cancelar" cancela. */
  job: MlJobOut | undefined;
}

/** Parâmetros da busca (RF-588). O operador vê tudo; só "Otimizar" e "Cancelar" são de admin. */
function FormularioBusca({ base, conjuntos, job }: FormularioBuscaProps) {
  const podeMutar = useCanMutate();
  const enfileirar = useEnqueueTrain();
  const cancelar = useCancelJob();
  const [metodo, setMetodo] = useState<MetodoSensor>("pls");
  const [nome, setNome] = useState("");
  const [textoTentativas, setTextoTentativas] = useState("20");
  const [textoR2, setTextoR2] = useState("0");
  const [outros, setOutros] = useState<readonly number[]>([]);
  const [erro, setErro] = useState<string | null>(null);
  // Cancelar pede confirmação inline, como o cancelar do treino (`SecaoTreino`).
  const [cancelando, setCancelando] = useState(false);

  const ativo = job !== undefined && temJobAtivo([job]);
  const tentativas = numeroEntre(textoTentativas, TENTATIVAS_MIN, TENTATIVAS_MAX);
  const tentativasValidas = tentativas !== null && Number.isInteger(tentativas);
  const r2Minimo = numeroEntre(textoR2, 0, 1);
  const compativeis = conjuntosCompativeis(base, conjuntos);
  const podeOtimizar =
    nome.trim() !== "" &&
    tentativasValidas &&
    r2Minimo !== null &&
    !ativo &&
    !enfileirar.isPending;

  function alternarOutro(id: number): void {
    setOutros((atual) => (atual.includes(id) ? atual.filter((x) => x !== id) : [...atual, id]));
  }

  async function enviar(evento: FormEvent): Promise<void> {
    evento.preventDefault();
    if (!podeOtimizar || tentativas === null || r2Minimo === null) return;
    setErro(null);
    setCancelando(false);
    try {
      await enfileirar.mutateAsync({
        kind: "tune",
        method: metodo,
        dataset_ids: [base.id, ...outros],
        name: nome.trim(),
        n_trials: tentativas,
        min_r2: r2Minimo,
      });
      setNome(""); // o nome é único no projeto: a próxima otimização pede outro
    } catch (err) {
      setErro(mensagem(err));
    }
  }

  async function cancelarBusca(): Promise<void> {
    if (job === undefined) return;
    setErro(null);
    try {
      await cancelar.mutateAsync(job.id);
    } catch (err) {
      setErro(mensagem(err));
    } finally {
      setCancelando(false);
    }
  }

  return (
    <Card data-testid="sv-otim-form" className="space-y-4 p-4">
      <h2 className="plaqueta text-xs text-fg-muted">Otimizar hiperparâmetros</h2>
      <form className="space-y-4" onSubmit={(evento) => void enviar(evento)}>
        <div className="flex flex-wrap items-start gap-4">
          <div className="space-y-1.5">
            <Label htmlFor="sv-otim-metodo" className="block">
              Método
            </Label>
            <Select
              id="sv-otim-metodo"
              data-testid="sv-otim-metodo"
              className="w-32"
              value={metodo}
              onChange={(evento) => setMetodo(evento.target.value as MetodoSensor)}
            >
              {METODOS.map((opcao) => (
                <option key={opcao} value={opcao}>
                  {opcao.toUpperCase()}
                </option>
              ))}
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="sv-otim-nome" className="block">
              Nome do modelo
            </Label>
            <Input
              id="sv-otim-nome"
              data-testid="sv-otim-nome"
              className="w-64"
              value={nome}
              onChange={(evento) => setNome(evento.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="sv-otim-tentativas" className="block">
              Tentativas
            </Label>
            <Input
              id="sv-otim-tentativas"
              data-testid="sv-otim-tentativas"
              className="w-28"
              type="number"
              step="1"
              min={TENTATIVAS_MIN}
              max={TENTATIVAS_MAX}
              value={textoTentativas}
              aria-invalid={!tentativasValidas}
              aria-describedby={tentativasValidas ? undefined : "sv-otim-tentativas-erro"}
              onChange={(evento) => setTextoTentativas(evento.target.value)}
            />
            {!tentativasValidas && (
              <p
                id="sv-otim-tentativas-erro"
                data-testid="sv-otim-tentativas-erro"
                className="text-xs text-alarm"
              >
                Deve ser um inteiro entre {TENTATIVAS_MIN} e {TENTATIVAS_MAX}
              </p>
            )}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="sv-otim-min-r2" className="block">
              R² mínimo
            </Label>
            <Input
              id="sv-otim-min-r2"
              data-testid="sv-otim-min-r2"
              className="w-28"
              type="number"
              step="any"
              min={0}
              max={1}
              value={textoR2}
              aria-invalid={r2Minimo === null}
              aria-describedby="sv-otim-min-r2-dica"
              onChange={(evento) => setTextoR2(evento.target.value)}
            />
            <p id="sv-otim-min-r2-dica" className="text-xs text-fg-muted">
              0 = não parar antes do fim
            </p>
            {r2Minimo === null && (
              <p data-testid="sv-otim-min-r2-erro" className="text-xs text-alarm">
                Deve estar entre 0 e 1
              </p>
            )}
          </div>
        </div>

        <div data-testid="sv-otim-faixas" className="space-y-1.5">
          <Label>Faixas de busca de {metodo.toUpperCase()}</Label>
          <table className="w-full max-w-xl border-collapse text-sm">
            <thead>
              <tr className="border-b border-border bg-surface-2">
                <th className={CABECALHO}>Parâmetro</th>
                <th className={CABECALHO}>Faixa</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(SOFT_SENSOR_SEARCH_SPACE[metodo]).map(([campo, faixa]) => (
                <tr key={campo} data-testid="sv-otim-faixa" className="border-b border-border">
                  <td className="px-3 py-1.5">{campo}</td>
                  <td className="process-value px-3 py-1.5">{descricaoDaFaixa(faixa)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {compativeis.length > 0 && (
          <div data-testid="sv-otim-outros-conjuntos" className="space-y-1.5">
            <Label>Otimizar junto com outros conjuntos compatíveis</Label>
            {compativeis.map((outro) => (
              <label
                key={outro.id}
                data-testid="sv-otim-outro-conjunto"
                data-conjunto-id={outro.id}
                className="flex cursor-pointer items-center gap-2 text-sm"
              >
                <input
                  type="checkbox"
                  className="accent-accent"
                  checked={outros.includes(outro.id)}
                  onChange={() => alternarOutro(outro.id)}
                />
                {outro.name}
              </label>
            ))}
          </div>
        )}

        {podeMutar && (
          <div className="flex flex-wrap items-center gap-3">
            <Button type="submit" data-testid="sv-otim-otimizar" disabled={!podeOtimizar}>
              Otimizar
            </Button>
            {ativo &&
              (cancelando ? (
                <>
                  <span className="text-xs text-fg-muted">
                    Cancelar a otimização? Nenhum modelo será gravado.
                  </span>
                  <Button
                    type="button"
                    size="sm"
                    data-testid="sv-otim-cancelar-confirmar"
                    disabled={cancelar.isPending}
                    onClick={() => void cancelarBusca()}
                  >
                    Confirmar
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    data-testid="sv-otim-cancelar-voltar"
                    onClick={() => setCancelando(false)}
                  >
                    Voltar
                  </Button>
                </>
              ) : (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  data-testid="sv-otim-cancelar"
                  onClick={() => setCancelando(true)}
                >
                  Cancelar
                </Button>
              ))}
          </div>
        )}
      </form>

      {erro && (
        <p role="alert" data-testid="sv-otim-erro" className="text-sm text-alarm">
          {erro}
        </p>
      )}
    </Card>
  );
}

// ------------------------------------------------------------------------------ andamento

/** `stage` de um `tune` em curso: depois do estudo o job segue `running` e o worker acrescenta a
 *  fase de treino e de gravação por cima do progresso da busca. */
function etapaDaBusca(job: MlJobOut): string {
  if (job.status === "queued") return "Na fila";
  if (job.progress.stage === "saving") return "Gravando o modelo";
  if (job.progress.stage === "training") return "Treinando o modelo com os melhores parâmetros";
  return "Buscando os hiperparâmetros";
}

/** O job `tune` mais novo do conjunto, visível a admin e operador: andamento enquanto ativo, a
 *  tabela de tentativas e, no `done`, o resultado e o caminho para ativar o modelo. */
function AndamentoDaBusca({ job, conjuntoId }: { job: MlJobOut; conjuntoId: number }) {
  const ativo = temJobAtivo([job]);
  const progresso = progressoDaBusca(job.progress);
  const tentativas = linhasDeTentativas(job.progress);
  const resultado = job.status === "done" ? resultadoDaBusca(job.result) : null;

  return (
    <Card data-testid="sv-otim-andamento" data-job-status={job.status} className="space-y-4 p-4">
      <h2 className="plaqueta text-xs text-fg-muted">Última otimização deste conjunto</h2>

      {ativo && (
        <div data-testid="sv-otim-ativo" className="flex flex-wrap items-center gap-3 text-sm">
          <span data-testid="sv-otim-etapa">{etapaDaBusca(job)}</span>
          <progress
            data-testid="sv-otim-progresso"
            aria-label="Progresso da otimização"
            className="w-64"
            value={progresso?.feito}
            max={progresso?.total}
          />
          {progresso && (
            <>
              <span data-testid="sv-otim-tentativa" className="process-value text-xs text-fg-muted">
                Tentativa {String(progresso.feito)} de {String(progresso.total)}
              </span>
              <span data-testid="sv-otim-melhor" className="text-xs text-fg-muted">
                Melhor R² até agora:{" "}
                <span className="process-value">{formatarMetrica(progresso.melhor ?? undefined)}</span>
              </span>
            </>
          )}
        </div>
      )}

      {job.status === "cancelled" && (
        <p data-testid="sv-otim-cancelada" className="text-sm text-fg-muted">
          Otimização cancelada
        </p>
      )}
      {job.status === "failed" && (
        <p role="alert" data-testid="sv-otim-job-erro" className="text-sm text-alarm">
          {job.error ?? "Falha na otimização"}
        </p>
      )}

      {resultado !== null && (
        <div data-testid="sv-otim-resultado" className="space-y-1.5 text-sm">
          <p>
            Melhores parâmetros:{" "}
            <span data-testid="sv-otim-melhores-parametros" className="process-value">
              {resultado.parametros}
            </span>
          </p>
          <p className="text-fg-muted">
            Modelo gerado · R²{" "}
            <span data-testid="sv-otim-r2" className="process-value text-fg">
              {resultado.r2}
            </span>{" "}
            · RMSE{" "}
            <span data-testid="sv-otim-rmse" className="process-value text-fg">
              {resultado.rmse}
            </span>{" "}
            · MAE{" "}
            <span data-testid="sv-otim-mae" className="process-value text-fg">
              {resultado.mae}
            </span>
          </p>
          <Link
            data-testid="sv-otim-ativar"
            to={`/engenharia/sensor-virtual/coleta?conjunto=${String(conjuntoId)}`}
            className="text-accent hover:underline"
          >
            Ativar na página Coleta e treino
          </Link>
        </div>
      )}

      {tentativas.length > 0 && (
        <div className="max-h-80 overflow-auto rounded-md border border-border">
          <table data-testid="sv-otim-tentativas-tabela" className="w-full border-collapse text-sm">
            <thead>
              <tr className="border-b border-border bg-surface-2">
                <th className={CABECALHO}>Tentativa</th>
                <th className={CABECALHO}>R²</th>
                <th className={CABECALHO}>Estado</th>
                <th className={CABECALHO}>Parâmetros</th>
              </tr>
            </thead>
            <tbody>
              {tentativas.map((linha) => (
                <tr
                  key={linha.numero}
                  data-testid="sv-otim-tentativa-linha"
                  className="border-b border-border"
                >
                  <td className="process-value px-3 py-1.5">{linha.numero}</td>
                  <td className="process-value px-3 py-1.5">{linha.r2}</td>
                  <td className="px-3 py-1.5">{linha.estado}</td>
                  <td className="process-value px-3 py-1.5 text-xs">{linha.parametros}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------------------------- página

/** Busca de hiperparâmetros com Optuna (RF-588, RF-589): job `tune` sobre um conjunto `ready`. */
export function OtimizacaoPage() {
  const conjuntos = useDatasets();
  const [escolhido, setEscolhido] = useState("");
  const prontos = (conjuntos.data ?? []).filter((conjunto) => conjunto.status === "ready");
  // Sem escolha válida (primeiro acesso, conjunto que deixou de estar pronto): o primeiro.
  const base = prontos.find((conjunto) => String(conjunto.id) === escolhido) ?? prontos[0] ?? null;
  // Polling de 2 s só enquanto um `tune` deste conjunto está na fila ou rodando.
  const jobs = useJobsDoConjunto(base?.id ?? null, "tune");
  const job = jobs.data?.find((candidato) => candidato.kind === "tune");

  return (
    <section className="space-y-4" data-testid="sv-otim-page">
      <div className="flex items-center gap-3">
        <h1 className="plaqueta text-sm">Sensor virtual · Otimização</h1>
        {base !== null && (
          <Select
            aria-label="Conjunto de treino"
            data-testid="sv-otim-conjunto"
            className="h-8 w-72"
            value={String(base.id)}
            onChange={(evento) => setEscolhido(evento.target.value)}
          >
            {prontos.map((conjunto) => (
              <option key={conjunto.id} value={String(conjunto.id)}>
                {conjunto.name}
              </option>
            ))}
          </Select>
        )}
      </div>

      {conjuntos.isError && (
        <p role="alert" className="text-sm text-alarm">
          Falha ao consultar conjuntos
        </p>
      )}
      {conjuntos.isSuccess && base === null && (
        <Card className="p-6">
          <p data-testid="sv-otim-vazio" className="text-sm text-fg-muted">
            Nenhum conjunto pronto: monte e finalize um conjunto na página{" "}
            <Link to="/engenharia/sensor-virtual/coleta" className="text-accent hover:underline">
              Coleta e treino
            </Link>{" "}
            para otimizar.
          </p>
        </Card>
      )}

      {base !== null && (
        <>
          <FormularioBusca key={base.id} base={base} conjuntos={conjuntos.data ?? []} job={job} />
          {job !== undefined && <AndamentoDaBusca job={job} conjuntoId={base.id} />}
        </>
      )}
    </section>
  );
}
