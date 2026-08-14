import { useEffect, useState } from "react";

import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { ApiError } from "../../lib/api";
import {
  MAX_EVENTS_RETENTION_DAYS,
  MAX_RETENTION_DAYS,
  MIN_RETENTION_DAYS,
  retencaoEhValida,
  retencaoEventosEhValida,
  useHistoryRetention,
  useUpdateHistoryRetention,
} from "./useHistoryRetention";

function mensagemErro(err: unknown): string {
  return err instanceof ApiError ? err.message : "Erro de comunicação com o servidor";
}

/**
 * Janelas de retenção na página Configurações (ADR-003/020 revisados): variáveis de processo
 * (1–120 d) e log de eventos (1–90 d), em seções independentes — cada salvar manda só o
 * próprio campo (ausente mantém o gravado, contrato do PUT). Página admin-only: sem modo
 * somente-leitura aqui.
 */
export function RetencaoHistorico() {
  const retencao = useHistoryRetention();
  const atualizar = useUpdateHistoryRetention();
  const [dias, setDias] = useState("");
  const [diasEventos, setDiasEventos] = useState("");
  const [erro, setErro] = useState<string | null>(null);
  const [erroEventos, setErroEventos] = useState<string | null>(null);

  // Sincroniza os campos com o valor persistido (carga inicial e após salvar). Sem estado
  // "sujo" próprio: o campo sempre reflete a última leitura do servidor.
  useEffect(() => {
    if (retencao.data) {
      setDias(String(retencao.data.retention_days));
      setDiasEventos(String(retencao.data.events_retention_days));
    }
  }, [retencao.data]);

  if (retencao.isPending || retencao.isError) return null; // página segue útil sem o controle

  const valor = Number(dias);
  const valido = retencaoEhValida(valor);
  const alterado = valor !== retencao.data.retention_days;
  const valorEventos = Number(diasEventos);
  const validoEventos = retencaoEventosEhValida(valorEventos);
  const alteradoEventos = valorEventos !== retencao.data.events_retention_days;

  async function salvarAmostras(): Promise<void> {
    setErro(null);
    try {
      await atualizar.mutateAsync({ retention_days: valor });
    } catch (err) {
      setErro(mensagemErro(err));
    }
  }

  async function salvarEventos(): Promise<void> {
    setErroEventos(null);
    try {
      await atualizar.mutateAsync({ events_retention_days: valorEventos });
    } catch (err) {
      setErroEventos(mensagemErro(err));
    }
  }

  return (
    <section className="space-y-3 rounded-sm border border-border bg-surface p-4">
      <h2 className="plaqueta text-sm text-fg">Retenção de histórico</h2>
      <div className="flex items-center gap-2">
        <label className="flex items-center gap-1.5">
          <span className="plaqueta text-xs text-fg-muted">Variáveis (dias)</span>
          <Input
            type="number"
            min={MIN_RETENTION_DAYS}
            max={MAX_RETENTION_DAYS}
            aria-label="Retenção do histórico de variáveis em dias"
            data-testid="config-retencao-amostras"
            className="h-7 w-16 px-2 text-xs"
            value={dias}
            onChange={(evento) => {
              setDias(evento.target.value);
            }}
          />
        </label>
        <Button
          type="button"
          variant="outline"
          size="sm"
          data-testid="config-retencao-amostras-salvar"
          disabled={!valido || !alterado || atualizar.isPending}
          onClick={salvarAmostras}
        >
          Salvar
        </Button>
        {erro && (
          <span role="alert" data-testid="config-retencao-amostras-erro" className="text-xs text-alarm">
            {erro}
          </span>
        )}
      </div>
      <div className="flex items-center gap-2">
        <label className="flex items-center gap-1.5">
          <span className="plaqueta text-xs text-fg-muted">Eventos (dias)</span>
          <Input
            type="number"
            min={MIN_RETENTION_DAYS}
            max={MAX_EVENTS_RETENTION_DAYS}
            aria-label="Retenção do log de eventos em dias"
            data-testid="config-retencao-eventos"
            className="h-7 w-16 px-2 text-xs"
            value={diasEventos}
            onChange={(evento) => {
              setDiasEventos(evento.target.value);
            }}
          />
        </label>
        <Button
          type="button"
          variant="outline"
          size="sm"
          data-testid="config-retencao-eventos-salvar"
          disabled={!validoEventos || !alteradoEventos || atualizar.isPending}
          onClick={salvarEventos}
        >
          Salvar
        </Button>
        {erroEventos && (
          <span role="alert" data-testid="config-retencao-eventos-erro" className="text-xs text-alarm">
            {erroEventos}
          </span>
        )}
      </div>
    </section>
  );
}
