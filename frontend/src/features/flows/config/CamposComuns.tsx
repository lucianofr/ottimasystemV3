import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";

/**
 * Campo numérico compartilhado pelos formulários de bloco da janela de config.
 *
 * Vive aqui, e não em cada `Campos*.tsx`, porque o filtro 1ª ordem, o Kalman (ADR-026) e o
 * PID (ADR-031) precisavam do MESMO campo e a terceira cópia byte a byte foi a que pagou a
 * extração.
 *
 * `type="text"` com `inputMode="decimal"`, nunca `type="number"`: o engenheiro digita vírgula
 * decimal (pt-BR) e o `input type=number` a descartaria em silêncio, devolvendo string vazia.
 * A leitura no envio é de `campos.ts` (`numeroDoCampo`/`numeroOuNuloDoCampo`).
 *
 * O texto de apoio (`ajuda`) é parte do contrato de usabilidade da janela, não enfeite: os
 * parâmetros do Kalman só são "fáceis de configurar" porque estão na EU do próprio sinal e se
 * leem numa tendência; no PID a ajuda substitui a folha de dados do instrumento que o
 * engenheiro não tem em mãos. Sem a dica, o mesmo campo vira estatística.
 */
export function Campo({
  id,
  rotulo,
  valor,
  ajuda,
  placeholder,
}: {
  id: string;
  rotulo: string;
  /** `null` desenha o campo vazio — usado pelos limites de saída do PID, onde "em branco"
   *  é um valor legítimo (sem limite), e não ausência de configuração. */
  valor: number | null;
  ajuda: string;
  placeholder?: string;
}) {
  return (
    <div className="space-y-1">
      <Label htmlFor={id}>{rotulo}</Label>
      <Input
        id={id}
        name={id}
        data-testid={`config-${id.replace(/_/g, "-")}`}
        type="text"
        inputMode="decimal"
        className="process-value"
        defaultValue={valor === null ? "" : String(valor)}
        placeholder={placeholder}
      />
      <p className="text-[10px] leading-tight text-fg-muted">{ajuda}</p>
    </div>
  );
}
