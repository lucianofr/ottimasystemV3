import { Button } from "../../components/ui/button";
import { Card } from "../../components/ui/card";
import type { ConnectionOut } from "../../lib/api";
import { useServerCertificateInfo, type ServerCertificateInfoOut } from "./useServerCertificate";

function formatoData(iso: string): string {
  const data = new Date(iso);
  return Number.isNaN(data.getTime()) ? iso : data.toLocaleString("pt-BR");
}

function Secao({
  titulo,
  info,
  testid,
}: {
  titulo: string;
  info: ServerCertificateInfoOut;
  testid: string;
}) {
  const campos: readonly (readonly [string, string])[] = [
    ["Sujeito", info.subject],
    ["Emissor", info.issuer],
    ["Fingerprint (SHA-256)", info.fingerprint_sha256],
    ["Válido desde", formatoData(info.not_before)],
    ["Válido até", formatoData(info.not_after)],
  ];
  return (
    <section className="space-y-2" data-testid={testid}>
      <h3 className="plaqueta text-xs text-fg-muted">{titulo}</h3>
      <dl className="space-y-1 text-xs">
        {campos.map(([rotulo, valor]) => (
          <div key={rotulo} className="flex gap-2">
            <dt className="w-44 shrink-0 text-fg-muted">{rotulo}</dt>
            <dd className="process-value break-all">{valor}</dd>
          </div>
        ))}
      </dl>
      <pre className="max-h-44 overflow-auto rounded-sm border border-border bg-well p-2 font-mono text-[10px] leading-tight">
        {info.pem}
      </pre>
    </section>
  );
}

interface Props {
  conexao: ConnectionOut;
  onClose: () => void;
}

/**
 * Visualização do certificado do servidor (RF-202, ADR-021): chapa page-level no mesmo
 * padrão do `ConnectionForm` (regra global 2, FE-08 — sem `<dialog>`, sem componente de
 * modal novo). Mostra metadados e PEM do certificado ENVIADO pelo servidor (captura do
 * opc-worker em staging) e do certificado CONFIADO, e avisa quando os dois divergem —
 * rotação: confiar de novo substitui o pin pelo novo.
 */
export function ChapaCertificadoServidor({ conexao, onClose }: Props) {
  // Mesmo queryKey do hook da célula: cache compartilhado, nenhuma requisição extra.
  const certificados = useServerCertificateInfo(conexao.id, conexao.security_policy !== "none");
  const trusted = certificados.data?.trusted ?? null;
  const recebido = certificados.data?.received ?? null;
  const divergentes =
    trusted !== null &&
    recebido !== null &&
    trusted.fingerprint_sha256 !== recebido.fingerprint_sha256;

  return (
    <Card className="p-6">
      <div className="flex items-center justify-between">
        <h2 className="plaqueta text-xs text-fg-muted">
          Certificado do servidor — {conexao.name}
        </h2>
        <Button variant="ghost" size="sm" data-testid="cert-chapa-fechar" onClick={onClose}>
          Fechar
        </Button>
      </div>
      {certificados.isPending && (
        <p className="mt-4 text-xs text-fg-muted">Carregando certificado…</p>
      )}
      {!certificados.isPending && trusted === null && recebido === null && (
        <p className="mt-4 text-xs text-fg-muted" data-testid="cert-chapa-vazio">
          Nenhum certificado recebido deste servidor ainda e nenhum confiado. A captura
          acontece quando o opc-worker tenta conectar — confira se o servidor está acessível.
        </p>
      )}
      <div className="mt-4 grid grid-cols-1 gap-6 lg:grid-cols-2">
        {recebido && (
          <Secao titulo="Enviado pelo servidor" info={recebido} testid="cert-chapa-recebido" />
        )}
        {trusted && <Secao titulo="Confiado" info={trusted} testid="cert-chapa-trusted" />}
      </div>
      {divergentes && (
        <p className="mt-4 text-xs text-warn-fg" data-testid="cert-chapa-divergencia">
          O servidor está apresentando um certificado diferente do confiado (possível
          rotação). Para substituir o pin pelo novo: "Deixar de confiar" e depois "Confiar
          certificado" na linha da conexão.
        </p>
      )}
    </Card>
  );
}
