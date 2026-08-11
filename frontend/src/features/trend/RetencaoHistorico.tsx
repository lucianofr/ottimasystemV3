import { useEffect, useState } from "react";

import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { ApiError } from "../../lib/api";
import { useCanMutate } from "../auth/useAuth";
import {
  MAX_RETENTION_DAYS,
  MIN_RETENTION_DAYS,
  retencaoEhValida,
  useHistoryRetention,
  useUpdateHistoryRetention,
} from "./useHistoryRetention";

function mensagemErro(err: unknown): string {
  return err instanceof ApiError ? err.message : "Erro de comunicação com o servidor";
}

/**
 * Janela de retenção do histórico de variáveis, na tela Trends (ADR-003 revisado). Visível a
 * todos (`GET` é `require_operator`); só admin edita (`PUT` é `require_admin` — mesma
 * decisão de RBAC de `ChapaCertificadoApp`: `useCanMutate()` no chamador escolhe o modo).
 */
export function RetencaoHistorico() {
  const podeMutar = useCanMutate();
  const retencao = useHistoryRetention();
  const atualizar = useUpdateHistoryRetention();
  const [dias, setDias] = useState("");
  const [erro, setErro] = useState<string | null>(null);

  // Sincroniza o campo com o valor persistido (carga inicial e após salvar). Sem estado
  // "sujo" próprio: o campo sempre reflete a última leitura do servidor.
  useEffect(() => {
    if (retencao.data) setDias(String(retencao.data.retention_days));
  }, [retencao.data]);

  if (retencao.isPending || retencao.isError) return null; // trend segue útil sem o controle

  if (!podeMutar) {
    return (
      <span className="plaqueta text-xs text-fg-muted" data-testid="trend-retencao-leitura">
        Retenção: {String(retencao.data.retention_days)} d
      </span>
    );
  }

  const valor = Number(dias);
  const valido = retencaoEhValida(valor);
  const alterado = valor !== retencao.data.retention_days;

  async function salvar(): Promise<void> {
    setErro(null);
    try {
      await atualizar.mutateAsync(valor);
    } catch (err) {
      setErro(mensagemErro(err));
    }
  }

  return (
    <span className="flex items-center gap-1.5">
      <label className="flex items-center gap-1.5">
        <span className="plaqueta text-xs text-fg-muted">Retenção (dias)</span>
        <Input
          type="number"
          min={MIN_RETENTION_DAYS}
          max={MAX_RETENTION_DAYS}
          aria-label="Retenção do histórico em dias"
          data-testid="trend-retencao-input"
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
        data-testid="trend-retencao-salvar"
        disabled={!valido || !alterado || atualizar.isPending}
        onClick={salvar}
      >
        Salvar
      </Button>
      {erro && (
        <span role="alert" data-testid="trend-retencao-erro" className="text-xs text-alarm">
          {erro}
        </span>
      )}
    </span>
  );
}
