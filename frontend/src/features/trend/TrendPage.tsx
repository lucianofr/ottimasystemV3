import { useMemo, useState } from "react";

import { Card } from "../../components/ui/card";
import { Select } from "../../components/ui/select";
import { cn } from "../../lib/cn";
import { TrendChart } from "./TrendChart";
import { FORMATO_VALOR, LIMITE_PENAS } from "./trendTheme";
import { montarMatriz, resumirSeries, useHistory, useTags } from "./useHistory";

const JANELAS = [
  { id: "30m", rotulo: "30 min", segundos: 1800 },
  { id: "2h", rotulo: "2 h", segundos: 7200 },
  { id: "8h", rotulo: "8 h", segundos: 28800 },
  { id: "24h", rotulo: "24 h", segundos: 86400 },
  { id: "7d", rotulo: "7 d", segundos: 604800 },
] as const;

type JanelaId = (typeof JANELAS)[number]["id"];

/** O engenheiro precisa saber quando está olhando agregado, não amostra bruta (spec F2 §9.2). */
const ROTULO_MODO: Record<"raw" | "1m", string> = { raw: "bruto", "1m": "1 min" };

/** Classes de cor das penas: referência aos mesmos tokens que o gráfico lê em runtime. */
const CLASSES_PENA = [
  "bg-pen-1",
  "bg-pen-2",
  "bg-pen-3",
  "bg-pen-4",
  "bg-pen-5",
  "bg-pen-6",
] as const;

export function TrendPage() {
  const [selecionadas, setSelecionadas] = useState<number[]>([]);
  const [janelaId, setJanelaId] = useState<JanelaId>("30m");
  const [aviso, setAviso] = useState<string | null>(null);

  const janela = JANELAS.find((item) => item.id === janelaId) ?? JANELAS[0];
  const tags = useTags();
  const historico = useHistory(selecionadas, janela.segundos);

  const chaveSelecao = selecionadas.join(",");
  // A seleção entra pela chave estável: o array `selecionadas` é recriado a cada render.
  const dados = useMemo(
    () => (historico.data ? montarMatriz(historico.data, selecionadas) : null),
    [historico.data, chaveSelecao],
  );
  const resumos = historico.data ? resumirSeries(historico.data, selecionadas) : [];

  const porId = new Map((tags.data ?? []).map((tag) => [tag.id, tag]));
  const rotulos = selecionadas.map((id) => porId.get(id)?.name ?? String(id));

  function alternar(tagId: number): void {
    if (selecionadas.includes(tagId)) {
      setSelecionadas(selecionadas.filter((id) => id !== tagId));
      setAviso(null);
      return;
    }
    if (selecionadas.length >= LIMITE_PENAS) {
      setAviso(`Máximo de ${String(LIMITE_PENAS)} penas por gráfico`);
      return;
    }
    setSelecionadas([...selecionadas, tagId]);
    setAviso(null);
  }

  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="plaqueta text-sm">Trend</h1>
        <div className="flex items-center gap-3">
          {historico.data && (
            <span
              data-testid="trend-mode"
              className="plaqueta rounded-panel border border-hairline bg-well px-2 py-1 text-xs text-fg-muted"
            >
              {ROTULO_MODO[historico.data.mode]}
            </span>
          )}
          <label className="flex items-center gap-2">
            <span className="plaqueta text-xs text-fg-muted">Janela</span>
            <Select
              data-testid="trend-window"
              className="w-28"
              value={janelaId}
              onChange={(evento) => setJanelaId(evento.target.value as JanelaId)}
            >
              {JANELAS.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.rotulo}
                </option>
              ))}
            </Select>
          </label>
        </div>
      </div>

      <div className="flex gap-4">
        <Card className="w-72 shrink-0 p-3">
          <p className="plaqueta text-xs text-fg-muted">
            Tags ({String(selecionadas.length)}/{String(LIMITE_PENAS)})
          </p>
          {tags.isPending && <p className="mt-2 text-sm text-fg-muted">Carregando…</p>}
          {tags.isError && (
            <p role="alert" className="mt-2 text-sm text-alarm">
              Falha ao consultar tags
            </p>
          )}
          {tags.isSuccess && tags.data.length === 0 && (
            <p className="mt-2 text-sm text-fg-muted">Nenhuma tag cadastrada</p>
          )}
          <div data-testid="trend-tag-selector" className="mt-2 max-h-96 overflow-y-auto">
            {(tags.data ?? []).map((tag) => (
              <label
                key={tag.id}
                data-testid="trend-tag-option"
                data-tag-id={tag.id}
                className="flex cursor-pointer items-center gap-2 border-b border-hairline py-1.5 last:border-b-0"
              >
                <input
                  type="checkbox"
                  className="accent-accent"
                  checked={selecionadas.includes(tag.id)}
                  onChange={() => {
                    alternar(tag.id);
                  }}
                />
                <span className="plaqueta grow text-xs">{tag.name}</span>
                <span className="text-xs text-fg-muted">{tag.eu}</span>
              </label>
            ))}
          </div>
          {aviso && (
            <p role="alert" className="mt-2 text-xs text-warn">
              {aviso}
            </p>
          )}
        </Card>

        <div className="grow space-y-3">
          {selecionadas.length === 0 && (
            <Card className="p-6">
              <p className="text-sm text-fg-muted">Selecione até 6 tags para exibir</p>
            </Card>
          )}

          {historico.isError && (
            <p role="alert" data-testid="trend-error" className="text-sm text-alarm">
              {historico.error.message}
            </p>
          )}

          {selecionadas.length > 0 && !dados && !historico.isError && (
            <Card className="p-6">
              <p className="text-sm text-fg-muted">Carregando…</p>
            </Card>
          )}

          {dados && (
            <TrendChart dados={dados} rotulos={rotulos} janelaSegundos={janela.segundos} />
          )}

          {resumos.length > 0 && (
            <Card data-testid="trend-legend" className="divide-y divide-hairline">
              {resumos.map((resumo, indice) => {
                const tag = porId.get(resumo.tagId);
                return (
                  <div
                    key={resumo.tagId}
                    data-testid="trend-legend-item"
                    className="flex items-center gap-3 px-3 py-2"
                  >
                    <span
                      aria-hidden="true"
                      className={cn("h-1 w-6 shrink-0", CLASSES_PENA[indice % CLASSES_PENA.length])}
                    />
                    <span className="plaqueta grow text-xs">
                      {tag?.name ?? String(resumo.tagId)}
                    </span>
                    {resumo.bad && (
                      <span
                        data-testid="trend-legend-bad"
                        className="plaqueta rounded-panel border border-warn px-1.5 text-xs text-warn"
                      >
                        BAD
                      </span>
                    )}
                    <span
                      className={cn(
                        "process-value w-28 text-right text-sm",
                        resumo.bad ? "text-fg-muted" : "text-fg",
                      )}
                    >
                      {resumo.valor === null ? "—" : FORMATO_VALOR.format(resumo.valor)}
                    </span>
                    <span className="w-12 text-xs text-fg-muted">{tag?.eu ?? ""}</span>
                  </div>
                );
              })}
            </Card>
          )}
        </div>
      </div>
    </section>
  );
}
