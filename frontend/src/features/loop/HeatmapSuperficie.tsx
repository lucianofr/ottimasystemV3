/**
 * Heatmap da superfície de controle de um `fuzzy_loop` (SPEC_FUZZY §5/§8).
 *
 * A principal ferramenta de comissionamento: a grade `(e_n, de_n) -> du_n` é amostrada no
 * SERVIDOR (resolução constante, FUZZY-SEC) e o ponto de operação ao vivo vem do
 * `loop_state.diag` — ver a superfície e ver onde a malha está operando nela, juntos, é o
 * que responde "por que essa malha não sobe" sem instrumentar nada.
 *
 * Célula com `null` (região sem regra) é desenhada em cinza, nunca em cor de valor: é
 * exatamente a região onde o kernel devolve NaN e o shell segura o OUT.
 */

import { useEffect, useRef } from "react";

import { Card } from "../../components/ui/card";
import type { LoopState } from "./types";
import { useLoopSurface } from "./useLoops";

/** Azul (du_n = −1) → branco (0) → vermelho (+1); cinza para região sem regra. */
export function cor(valor: number | null): [number, number, number] {
  if (valor === null) return [64, 64, 64];
  const v = Math.max(-1, Math.min(1, valor));
  if (v >= 0) return [255, Math.round(255 * (1 - v)), Math.round(255 * (1 - v))];
  return [Math.round(255 * (1 + v)), Math.round(255 * (1 + v)), 255];
}

/** Converte um valor normalizado [-1,1] em índice de célula da grade. */
export function celula(n: number, resolution: number): number {
  const bruto = Math.round(((n + 1) / 2) * (resolution - 1));
  return Math.max(0, Math.min(resolution - 1, bruto));
}

export function HeatmapSuperficie({
  flowId,
  blockId,
  estado,
}: {
  flowId: number;
  blockId: string;
  estado: LoopState | undefined;
}) {
  const superficie = useLoopSurface(flowId, blockId);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const dados = superficie.data;

  useEffect(() => {
    const canvas = canvasRef.current;
    if (canvas === null || dados === undefined) return;
    const ctx = canvas.getContext("2d");
    if (ctx === null) return;
    const { resolution, values } = dados;
    canvas.width = resolution;
    canvas.height = resolution;
    const imagem = ctx.createImageData(resolution, resolution);
    for (let linha = 0; linha < resolution; linha += 1) {
      // eixo 0 do payload é `de_n` e cresce para cima; o canvas cresce para baixo
      const y = resolution - 1 - linha;
      for (let coluna = 0; coluna < resolution; coluna += 1) {
        const [r, g, b] = cor(values[linha][coluna]);
        const base = (y * resolution + coluna) * 4;
        imagem.data[base] = r;
        imagem.data[base + 1] = g;
        imagem.data[base + 2] = b;
        imagem.data[base + 3] = 255;
      }
    }
    ctx.putImageData(imagem, 0, 0);
  }, [dados]);

  if (superficie.isPending) {
    return (
      <Card className="max-w-md p-4" data-testid="loop-superficie-carregando">
        <p className="text-xs text-fg-muted">Amostrando a superfície…</p>
      </Card>
    );
  }
  if (superficie.isError || dados === undefined) {
    return (
      <Card className="max-w-md p-4" data-testid="loop-superficie-erro">
        <p className="text-xs text-alarm">Não foi possível amostrar a superfície de controle.</p>
      </Card>
    );
  }

  const e_n = estado?.diag.e_n;
  const de_n = estado?.diag.de_n;
  const temPonto = e_n !== undefined && de_n !== undefined;

  return (
    <Card className="max-w-md space-y-2 p-4" data-testid="loop-superficie">
      <h3 className="text-xs text-fg-muted">
        Superfície de controle — eixo X: erro normalizado, eixo Y: derivada do erro
      </h3>
      <div className="relative aspect-square w-full">
        <canvas
          ref={canvasRef}
          data-testid="loop-superficie-canvas"
          className="h-full w-full [image-rendering:pixelated]"
        />
        {temPonto && (
          <div
            data-testid="loop-superficie-ponto"
            title={`e_n ${e_n.toFixed(3)} · de_n ${de_n.toFixed(3)}`}
            className="pointer-events-none absolute h-2 w-2 -translate-x-1/2 -translate-y-1/2 rounded-full border border-fg bg-fg"
            style={{
              left: `${String((celula(e_n, dados.resolution) / (dados.resolution - 1)) * 100)}%`,
              top: `${String(100 - (celula(de_n, dados.resolution) / (dados.resolution - 1)) * 100)}%`,
            }}
          />
        )}
      </div>
      <dl className="grid grid-cols-2 gap-x-4 text-xs">
        <dt>Ponto de operação</dt>
        <dd className="process-value">
          {temPonto ? `${e_n.toFixed(3)} · ${de_n.toFixed(3)}` : "—"}
        </dd>
        <dt>Regras disparadas</dt>
        <dd className="process-value">{estado?.diag.rule_fire_count ?? "—"}</dd>
      </dl>
    </Card>
  );
}
