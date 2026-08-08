import { useState } from "react";

import { Button } from "../../components/ui/button";
import { Card } from "../../components/ui/card";
import { ApiError, type ConnectionOut } from "../../lib/api";
import { baixarArquivo } from "../../lib/arquivos";
import { useCanMutate } from "../auth/useAuth";
import { conexoesAfetadasPorRegeracao } from "./certificados";
import { useAppCertificate, useGenerateAppCertificate } from "./useAppCertificate";

/** Triângulo de alerta — mesmo path visual de `ConnectionsPage.tsx`/`AnnunciatorBar.tsx`
 *  (Regra do Canal Redundante: cor + ícone + texto, DESIGN.md §Colors). */
function IconeAlerta() {
  return (
    <svg
      aria-hidden="true"
      width="12"
      height="12"
      viewBox="0 0 16 16"
      fill="currentColor"
      className="shrink-0"
    >
      <path d="M8 1 15 14H1L8 1Zm-.75 5v4h1.5V6h-1.5Zm0 5.5V13h1.5v-1.5h-1.5Z" />
    </svg>
  );
}

function mensagemErro(err: unknown): string {
  return err instanceof ApiError ? err.message : "Erro de comunicação com o servidor";
}

interface Props {
  /** Conexões do projeto ativo, já carregadas por `ConnectionsPage` — a lista usada para
   *  calcular o impacto de regenerar é a mesma da tabela, sem requisição extra (SEC-06). */
  conexoes: ConnectionOut[];
}

/**
 * Chapa "Certificado da aplicação" no topo de `/engenharia/conexoes` (spec §6.2-1, RF-202,
 * ADR-021, tarefa 3.1). `GET /api/certificates/app` é `require_admin` no router inteiro
 * (`certificates.py:25`) — decisão de RBAC do preâmbulo do plano F6b, não reaberta aqui: a
 * chapa inteira, e a query por trás dela, só existem para admin.
 *
 * Separada da tabela de conexões por um degrau tonal (não só posição, UX-04/SEC-06): o
 * invólucro externo usa `bg-well` (o mesmo tom rebaixado de inputs/áreas de destaque), a
 * chapa em si continua `bg-panel` — dois tons de distância do fundo `bg-field` da página,
 * contra um só tom da tabela abaixo.
 */
export function ChapaCertificadoApp({ conexoes }: Props) {
  const podeMutar = useCanMutate();
  const certificado = useAppCertificate(podeMutar);
  const gerar = useGenerateAppCertificate();
  const [confirmando, setConfirmando] = useState(false);
  const [erroGerar, setErroGerar] = useState<string | null>(null);
  const [erroBaixar, setErroBaixar] = useState<string | null>(null);
  const [avisoRetrust, setAvisoRetrust] = useState<string | null>(null);

  if (!podeMutar) return null;

  const afetadas = conexoesAfetadasPorRegeracao(conexoes);

  async function gerarCertificado(force: boolean): Promise<void> {
    setErroGerar(null);
    try {
      const resultado = await gerar.mutateAsync({ force });
      setAvisoRetrust(resultado.warning ?? null);
      setConfirmando(false);
    } catch (err) {
      setErroGerar(mensagemErro(err));
    }
  }

  async function baixar(): Promise<void> {
    setErroBaixar(null);
    try {
      await baixarArquivo("/api/certificates/app/export", "ottima.der");
    } catch (err) {
      setErroBaixar(mensagemErro(err));
    }
  }

  return (
    <div className="rounded-panel border border-hairline bg-well p-3">
      <Card data-testid="cert-app-chapa" className="space-y-3 p-4">
        <div>
          <h2 className="plaqueta text-sm">Certificado da aplicação</h2>
          <p className="text-xs text-fg-muted">
            Vale para todas as conexões de todos os projetos desta instalação.
          </p>
        </div>

        {certificado.isPending && <p className="text-sm text-fg-muted">Carregando…</p>}

        {certificado.isError && (
          <p
            role="alert"
            data-testid="cert-app-erro"
            className="flex items-center gap-1.5 text-sm text-alarm"
          >
            <IconeAlerta />
            {mensagemErro(certificado.error)}
          </p>
        )}

        {certificado.isSuccess && !certificado.data.exists && (
          <div className="flex items-center justify-between gap-3">
            <p className="text-sm text-fg-muted">
              Nenhum certificado de aplicação gerado nesta instalação.
            </p>
            <Button
              data-testid="cert-app-gerar"
              disabled={gerar.isPending}
              onClick={() => void gerarCertificado(false)}
            >
              Gerar
            </Button>
          </div>
        )}

        {certificado.isSuccess && certificado.data.exists && (
          <div className="space-y-3">
            <dl className="grid grid-cols-[auto,1fr] items-baseline gap-x-3 gap-y-1 text-xs">
              <dt className="text-fg-muted">Impressão digital (SHA-256)</dt>
              <dd className="process-value break-all">{certificado.data.fingerprint_sha256}</dd>
              <dt className="text-fg-muted">Válido de</dt>
              <dd className="process-value">{certificado.data.not_before}</dd>
              <dt className="text-fg-muted">Válido até</dt>
              <dd className="process-value">{certificado.data.not_after}</dd>
              <dt className="text-fg-muted">URI da aplicação</dt>
              <dd className="process-value">{certificado.data.application_uri}</dd>
            </dl>
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                data-testid="cert-app-baixar"
                onClick={() => void baixar()}
              >
                Baixar
              </Button>
              <Button
                variant="outline"
                size="sm"
                data-testid="cert-app-regerar"
                onClick={() => {
                  setErroGerar(null);
                  setAvisoRetrust(null);
                  setConfirmando(true);
                }}
              >
                Regerar
              </Button>
            </div>
            {erroBaixar && (
              <p
                role="alert"
                data-testid="cert-app-baixar-erro"
                className="flex items-center gap-1.5 text-xs text-alarm"
              >
                <IconeAlerta />
                {erroBaixar}
              </p>
            )}
          </div>
        )}

        {erroGerar && (
          <p
            role="alert"
            data-testid="cert-app-gerar-erro"
            className="flex items-center gap-1.5 text-xs text-alarm"
          >
            <IconeAlerta />
            {erroGerar}
          </p>
        )}

        {avisoRetrust && (
          <p
            role="status"
            data-testid="cert-app-retrust-aviso"
            className="flex items-center gap-1.5 text-xs text-warn"
          >
            <IconeAlerta />
            {avisoRetrust}
          </p>
        )}

        {confirmando && (
          <div
            data-testid="cert-app-regerar-dialog"
            className="space-y-2 rounded-panel border border-hairline bg-well p-3"
          >
            <p className="text-xs text-fg-muted">
              Regerar substitui o certificado atual. As conexões abaixo exigirão novo trust
              manual nos servidores OPC-UA depois da troca:
            </p>
            {afetadas.length === 0 ? (
              <p data-testid="cert-app-regerar-sem-afetadas" className="text-xs text-fg-muted">
                Nenhuma conexão cadastrada usa segurança de transporte ou autenticação por
                certificado hoje.
              </p>
            ) : (
              <ul data-testid="cert-app-regerar-afetadas" className="space-y-1 text-xs">
                {afetadas.map((c) => (
                  <li key={c.id} data-testid="cert-app-regerar-afetada-item">
                    {c.name}
                  </li>
                ))}
              </ul>
            )}
            <div className="flex items-center justify-end gap-2">
              <Button
                variant="destructive"
                size="sm"
                data-testid="cert-app-regerar-confirm"
                disabled={gerar.isPending}
                onClick={() => void gerarCertificado(true)}
              >
                Regerar
              </Button>
              <Button
                variant="outline"
                size="sm"
                data-testid="cert-app-regerar-cancel"
                onClick={() => setConfirmando(false)}
              >
                Cancelar
              </Button>
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}
