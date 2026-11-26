import { useState } from "react";

import { Button } from "../../components/ui/button";
import { Card } from "../../components/ui/card";
import { Select } from "../../components/ui/select";
import { useCanMutate } from "../auth/useAuth";
import { mensagem } from "./coleta";
import {
  blocosCompativeis,
  estadoDoModelo,
  formatarAquecimento,
  formatarMetrica,
} from "./treino";
import type { SoftSensorBlockOut, SoftSensorModelOut } from "./types";
import { useActivateModel, useDeleteModel, useModels } from "./useModels";
import { useSoftSensorBlocks } from "./useSoftSensorBlocks";

const CABECALHO = "plaqueta px-4 py-3 text-left text-xs text-fg-muted";

function chaveDoBloco(bloco: Pick<SoftSensorBlockOut, "flow_id" | "block_id">): string {
  return `${String(bloco.flow_id)}/${bloco.block_id}`;
}

interface LinhaProps {
  modelo: SoftSensorModelOut;
  blocos: readonly SoftSensorBlockOut[];
  podeMutar: boolean;
}

function LinhaModelo({ modelo, blocos, podeMutar }: LinhaProps) {
  const ativar = useActivateModel();
  const apagar = useDeleteModel();
  const compativeis = blocosCompativeis(modelo, blocos);
  const [escolhido, setEscolhido] = useState("");
  const [apagando, setApagando] = useState(false);
  // O 409 do DELETE (e o 422 da ativação) aparecem como vieram: o servidor sabe de bloco em
  // `desired` ou em aquecimento que `in_use` ainda não mostra, então "Apagar" nunca é escondido.
  const [erro, setErro] = useState<string | null>(null);

  const bloco = compativeis.find((candidato) => chaveDoBloco(candidato) === escolhido);

  async function confirmarAtivacao(): Promise<void> {
    if (bloco === undefined) return;
    setErro(null);
    try {
      await ativar.mutateAsync({
        flowId: bloco.flow_id,
        blockId: bloco.block_id,
        modelId: modelo.id,
      });
      setEscolhido("");
    } catch (err) {
      setErro(mensagem(err));
    }
  }

  async function confirmarExclusao(): Promise<void> {
    setErro(null);
    try {
      await apagar.mutateAsync(modelo.id);
    } catch (err) {
      setErro(mensagem(err));
      setApagando(false);
    }
  }

  return (
    <tr
      data-testid="sv-coleta-modelo-row"
      data-modelo-id={modelo.id}
      className="border-b border-border align-top transition-colors duration-[var(--duration-fast)] hover:bg-surface-2"
    >
      <td className="px-4 py-2">{modelo.name}</td>
      <td className="plaqueta px-4 py-2 text-xs">{modelo.method.toUpperCase()}</td>
      <td className="process-value px-4 py-2">{formatarMetrica(modelo.metrics.r2)}</td>
      <td className="process-value px-4 py-2">{formatarMetrica(modelo.metrics.rmse)}</td>
      <td className="process-value px-4 py-2">{formatarMetrica(modelo.metrics.mae)}</td>
      <td className="px-4 py-2">{formatarAquecimento(modelo.warmup_s)}</td>
      <td data-testid="sv-coleta-modelo-estado" className="px-4 py-2">
        {estadoDoModelo(modelo)}
      </td>
      {podeMutar && (
        <td className="px-3 py-2">
          {apagando ? (
            <div className="flex items-center justify-end gap-2">
              <span className="text-xs text-fg-muted">Apagar este modelo?</span>
              <Button
                variant="destructive"
                size="sm"
                data-testid="sv-coleta-modelo-apagar-confirmar"
                disabled={apagar.isPending}
                onClick={() => void confirmarExclusao()}
              >
                Confirmar
              </Button>
              <Button
                variant="outline"
                size="sm"
                data-testid="sv-coleta-modelo-apagar-voltar"
                onClick={() => setApagando(false)}
              >
                Voltar
              </Button>
            </div>
          ) : (
            <div className="flex items-center justify-end gap-2">
              <Select
                aria-label={`Ativar o modelo ${modelo.name} em`}
                data-testid="sv-coleta-modelo-ativar-select"
                className="h-8 w-56"
                value={escolhido}
                disabled={compativeis.length === 0}
                onChange={(evento) => setEscolhido(evento.target.value)}
              >
                <option value="">
                  {compativeis.length === 0 ? "Nenhum bloco compatível" : "Ativar em…"}
                </option>
                {compativeis.map((candidato) => (
                  <option key={chaveDoBloco(candidato)} value={chaveDoBloco(candidato)}>
                    {candidato.flow_name} / {candidato.block_id}
                  </option>
                ))}
              </Select>
              {bloco !== undefined && (
                <Button
                  size="sm"
                  data-testid="sv-coleta-modelo-ativar-confirmar"
                  disabled={ativar.isPending}
                  onClick={() => void confirmarAtivacao()}
                >
                  Ativar
                </Button>
              )}
              <Button
                variant="ghost"
                size="sm"
                data-testid="sv-coleta-modelo-apagar"
                onClick={() => {
                  setErro(null);
                  setApagando(true);
                }}
              >
                Apagar
              </Button>
            </div>
          )}
          {erro && (
            <p
              role="alert"
              data-testid="sv-coleta-modelo-erro"
              className="mt-1 text-right text-xs text-alarm"
            >
              {erro}
            </p>
          )}
        </td>
      )}
    </tr>
  );
}

/** Modelos do projeto, com as métricas do teste (últimos 20%) lado a lado para comparar, e as
 *  ações de admin: ativar num bloco compatível e apagar (RF-584, RF-589). */
export function TabelaModelos() {
  const podeMutar = useCanMutate();
  const modelos = useModels();
  const blocos = useSoftSensorBlocks();
  const colunas = podeMutar ? 8 : 7;
  const linhas = modelos.data ?? [];

  return (
    <div data-testid="sv-coleta-modelos" className="space-y-3">
      <h2 className="plaqueta text-xs text-fg-muted">Modelos</h2>
      <Card className="max-h-[32rem] overflow-auto">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="border-b border-border bg-surface-2">
              <th className={CABECALHO}>Nome</th>
              <th className={CABECALHO}>Método</th>
              <th className={CABECALHO}>R²</th>
              <th className={CABECALHO}>RMSE</th>
              <th className={CABECALHO}>MAE</th>
              <th className={CABECALHO}>Aquecimento</th>
              <th className={CABECALHO}>Estado</th>
              {podeMutar && (
                <th className="px-3 py-2">
                  <span className="sr-only">Ações</span>
                </th>
              )}
            </tr>
          </thead>
          <tbody>
            {modelos.isPending && (
              <tr>
                <td colSpan={colunas} className="px-4 py-4 text-fg-muted">
                  Carregando…
                </td>
              </tr>
            )}
            {modelos.isError && (
              <tr>
                <td colSpan={colunas} className="px-4 py-4 text-alarm" role="alert">
                  Falha ao consultar modelos
                </td>
              </tr>
            )}
            {modelos.isSuccess && linhas.length === 0 && (
              <tr>
                <td
                  colSpan={colunas}
                  data-testid="sv-coleta-modelos-vazio"
                  className="px-4 py-4 text-fg-muted"
                >
                  Nenhum modelo gerado
                </td>
              </tr>
            )}
            {linhas.map((modelo) => (
              <LinhaModelo
                key={modelo.id}
                modelo={modelo}
                blocos={blocos.data ?? []}
                podeMutar={podeMutar}
              />
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}
