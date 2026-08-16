import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";

/**
 * Campo numérico compartilhado pelos formulários de bloco da janela de config.
 *
 * Vive aqui, e não em cada `Campos*.tsx`, porque o filtro 1ª ordem, o Kalman (ADR-026) e o
 * PID (ADR-031) precisavam do MESMO campo e a terceira cópia byte a byte foi a que pagou a
 * extração. A quarta cópia (MPC, `CampoNumero`) e o `<Input>` cru do TFS convergiram aqui
 * depois (ARCH-21/TD-024).
 *
 * `type="text"` com `inputMode="decimal"`, nunca `type="number"`: o engenheiro digita vírgula
 * decimal (pt-BR) e o `input type=number` a descartaria em silêncio, devolvendo string vazia.
 * A leitura no envio é de `campos.ts` (`numeroDoCampo`/`numeroOuNuloDoCampo`).
 *
 * O texto de apoio (`ajuda`) é parte do contrato de usabilidade da janela, não enfeite: os
 * parâmetros do Kalman só são "fáceis de configurar" porque estão na EU do próprio sinal e se
 * leem numa tendência; no PID a ajuda substitui a folha de dados do instrumento que o
 * engenheiro não tem em mãos. Sem a dica, o mesmo campo vira estatística. Opcional porque o
 * MPC e o TFS não têm essa cópia — não é regressão, eles nunca tiveram.
 */
export function Campo({
  id,
  nome,
  rotulo,
  valor,
  ajuda,
  placeholder,
  testid,
}: {
  id: string;
  /** `name` do input HTML quando diverge do `id` — a convenção `nomeCampoVar` do MPC decide
   *  o `name` pelo id da variável + campo, não pelo `id`/`htmlFor` do elemento na tela. */
  nome?: string;
  rotulo: string;
  /** `null` desenha o campo vazio — usado pelos limites de saída do PID, onde "em branco"
   *  é um valor legítimo (sem limite), e não ausência de configuração. */
  valor: number | null;
  ajuda?: string;
  placeholder?: string;
  /** testid explícito (convenção do MPC, por campo lógico). Sem `nome` (convenção antiga,
   *  onde o `id` já é o `name`) o padrão continua `config-<id>`, idêntico a antes. Com `nome`
   *  (convenção nova, desacoplada) e sem `testid` explícito, nenhum testid é desenhado — é o
   *  que o MPC já fazia em ~metade dos seus campos antes desta extração. */
  testid?: string;
}) {
  const testidFinal = testid ?? (nome === undefined ? `config-${id.replace(/_/g, "-")}` : undefined);
  return (
    <div className="space-y-1">
      <Label htmlFor={id}>{rotulo}</Label>
      <Input
        id={id}
        name={nome ?? id}
        data-testid={testidFinal}
        type="text"
        inputMode="decimal"
        className="process-value"
        defaultValue={valor === null ? "" : String(valor)}
        placeholder={placeholder}
      />
      {ajuda !== undefined && <p className="text-[10px] leading-tight text-fg-muted">{ajuda}</p>}
    </div>
  );
}
