import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";

import { Button } from "../../components/ui/button";
import { Card } from "../../components/ui/card";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select } from "../../components/ui/select";
import { SOFT_SENSOR_HYPERPARAMS } from "../../lib/contracts.gen";
import { useCanMutate } from "../auth/useAuth";
import { mensagem, temJobAtivo } from "./coleta";
import { TabelaModelos } from "./TabelaModelos";
import {
  conjuntosCompativeis,
  hiperparametrosIniciais,
  METODOS,
  progressoDoTreino,
  validarHiperparametros,
  type MetodoSensor,
} from "./treino";
import type { DatasetOut, MlJobOut } from "./types";
import { useCancelJob, useEnqueueTrain } from "./useJobs";
import { CHAVE_MODELOS } from "./useModels";

type Textos = Record<MetodoSensor, Record<string, string>>;

/** Cada método guarda os seus campos: trocar de método e voltar não perde o que foi editado. */
function textosIniciais(): Textos {
  const dosCampos = (metodo: MetodoSensor) =>
    Object.fromEntries(
      Object.entries(hiperparametrosIniciais(metodo)).map(([campo, valor]) => [campo, String(valor)]),
    );
  return { pls: dosCampos("pls"), esn: dosCampos("esn"), lstm: dosCampos("lstm") };
}

interface GerarModeloProps {
  conjunto: DatasetOut;
  conjuntos: readonly DatasetOut[];
  jobs: readonly MlJobOut[] | undefined;
}

/** Formulário inline (admin) do treino manual (RF-587, spec §8.1) e o andamento do job. */
function GerarModelo({ conjunto, conjuntos, jobs }: GerarModeloProps) {
  const queryClient = useQueryClient();
  const enfileirar = useEnqueueTrain();
  const cancelar = useCancelJob();
  const [metodo, setMetodo] = useState<MetodoSensor>("pls");
  const [nome, setNome] = useState("");
  const [textos, setTextos] = useState(textosIniciais);
  const [outros, setOutros] = useState<readonly number[]>([]);
  const [erro, setErro] = useState<string | null>(null);

  // O job de treino mais novo deste conjunto (a lista vem do mais novo para o mais antigo).
  const job = jobs?.find((candidato) => candidato.kind === "train");
  const ativo = job !== undefined && temJobAtivo([job]);
  const progresso = job === undefined ? null : progressoDoTreino(job.progress);
  const etapa =
    job?.status === "queued"
      ? "Na fila"
      : job?.progress.stage === "saving"
        ? "Gravando o modelo"
        : "Treinando o modelo";
  const { hiperparametros, problemas } = validarHiperparametros(metodo, textos[metodo]);
  const compativeis = conjuntosCompativeis(conjunto, conjuntos);
  const podeGerar =
    nome.trim() !== "" && Object.keys(problemas).length === 0 && !ativo && !enfileirar.isPending;

  // O modelo novo só aparece na tabela depois do `done`, e a tabela só se atualiza sozinha
  // durante troca de bloco: o fim do treino precisa pedir a lista de novo.
  useEffect(() => {
    if (job?.status === "done") void queryClient.invalidateQueries({ queryKey: CHAVE_MODELOS });
  }, [job?.id, job?.status, queryClient]);

  function editar(campo: string, valor: string): void {
    setTextos((atual) => ({ ...atual, [metodo]: { ...atual[metodo], [campo]: valor } }));
  }

  function alternarOutro(id: number): void {
    setOutros((atual) => (atual.includes(id) ? atual.filter((x) => x !== id) : [...atual, id]));
  }

  async function enviar(evento: FormEvent): Promise<void> {
    evento.preventDefault();
    if (!podeGerar) return;
    setErro(null);
    try {
      await enfileirar.mutateAsync({
        kind: "train",
        method: metodo,
        dataset_ids: [conjunto.id, ...outros],
        name: nome.trim(),
        hyperparams: hiperparametros,
      });
      setNome(""); // o nome é único no projeto: o próximo treino pede outro
    } catch (err) {
      setErro(mensagem(err));
    }
  }

  async function cancelarTreino(): Promise<void> {
    if (job === undefined) return;
    setErro(null);
    try {
      await cancelar.mutateAsync(job.id);
    } catch (err) {
      setErro(mensagem(err));
    }
  }

  return (
    <Card data-testid="sv-coleta-gerar-modelo" className="space-y-4 p-4">
      <h2 className="plaqueta text-xs text-fg-muted">Gerar modelo</h2>
      <form className="space-y-4" onSubmit={(evento) => void enviar(evento)}>
        <div className="flex flex-wrap items-end gap-4">
          <div className="space-y-1.5">
            <Label htmlFor="sv-coleta-metodo">Método</Label>
            <Select
              id="sv-coleta-metodo"
              data-testid="sv-coleta-metodo"
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
            <Label htmlFor="sv-coleta-modelo-nome">Nome do modelo</Label>
            <Input
              id="sv-coleta-modelo-nome"
              data-testid="sv-coleta-modelo-nome"
              className="w-64"
              value={nome}
              onChange={(evento) => setNome(evento.target.value)}
            />
          </div>
        </div>

        <div className="grid grid-cols-[repeat(auto-fill,minmax(10rem,1fr))] gap-4">
          {Object.entries(SOFT_SENSOR_HYPERPARAMS[metodo]).map(([campo, spec]) => {
            const id = `sv-coleta-hp-${campo}`;
            const problema = problemas[campo];
            const valor = textos[metodo][campo] ?? "";
            return (
              <div key={`${metodo}-${campo}`} className="space-y-1.5">
                <Label htmlFor={id}>{campo}</Label>
                {"choices" in spec ? (
                  <Select
                    id={id}
                    data-testid={id}
                    value={valor}
                    onChange={(evento) => editar(campo, evento.target.value)}
                  >
                    {spec.choices.map((opcao) => (
                      <option key={opcao} value={String(opcao)}>
                        {opcao}
                      </option>
                    ))}
                  </Select>
                ) : (
                  <Input
                    id={id}
                    data-testid={id}
                    type="number"
                    step="any"
                    value={valor}
                    aria-invalid={problema !== undefined}
                    aria-describedby={problema === undefined ? undefined : `${id}-erro`}
                    onChange={(evento) => editar(campo, evento.target.value)}
                  />
                )}
                {problema !== undefined && (
                  <p id={`${id}-erro`} data-testid={`${id}-erro`} className="text-xs text-alarm">
                    {problema}
                  </p>
                )}
              </div>
            );
          })}
        </div>

        {compativeis.length > 0 && (
          <div data-testid="sv-coleta-outros-conjuntos" className="space-y-1.5">
            <Label>Treinar junto com outros conjuntos compatíveis</Label>
            {compativeis.map((outro) => (
              <label
                key={outro.id}
                data-testid="sv-coleta-outro-conjunto"
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

        <div className="flex flex-wrap items-center gap-3">
          <Button type="submit" data-testid="sv-coleta-gerar" disabled={!podeGerar}>
            Gerar modelo
          </Button>
          {ativo && (
            <div data-testid="sv-coleta-treino-andamento" className="flex items-center gap-3 text-sm">
              <span data-testid="sv-coleta-treino-etapa">{etapa}</span>
              <progress
                data-testid="sv-coleta-treino-progresso"
                aria-label="Progresso do treino"
                className="w-64"
                value={progresso?.feito}
                max={progresso?.total}
              />
              {progresso && (
                <span className="process-value text-xs text-fg-muted">
                  época {String(progresso.feito)} de {String(progresso.total)}
                </span>
              )}
              <Button
                type="button"
                variant="outline"
                size="sm"
                data-testid="sv-coleta-treino-cancelar"
                disabled={cancelar.isPending}
                onClick={() => void cancelarTreino()}
              >
                Cancelar
              </Button>
            </div>
          )}
        </div>
      </form>

      {erro && (
        <p role="alert" data-testid="sv-coleta-gerar-erro" className="text-sm text-alarm">
          {erro}
        </p>
      )}
      {job?.status === "failed" && (
        <p role="alert" data-testid="sv-coleta-treino-erro" className="text-sm text-alarm">
          {job.error ?? "Falha no treino"}
        </p>
      )}
    </Card>
  );
}

interface SecaoTreinoProps {
  /** Conjunto `ready` selecionado: é o que o treino usa, junto dos compatíveis marcados. */
  conjunto: DatasetOut;
  conjuntos: readonly DatasetOut[];
  /** Jobs DESTE conjunto (`useJobsDoConjunto`), mais novos primeiro. */
  jobs: readonly MlJobOut[] | undefined;
}

/** Treino e modelos (RF-589, RF-584): "Gerar modelo" é de admin; a tabela de modelos o operador
 *  também vê, sem as ações. */
export function SecaoTreino({ conjunto, conjuntos, jobs }: SecaoTreinoProps) {
  const podeMutar = useCanMutate();

  return (
    <div data-testid="sv-coleta-treino" className="space-y-4">
      {podeMutar && <GerarModelo conjunto={conjunto} conjuntos={conjuntos} jobs={jobs} />}
      <TabelaModelos />
    </div>
  );
}
