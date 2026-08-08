import type { ConnectionOut } from "../../lib/api";
import type { components } from "../../lib/api-types";

/**
 * Predicados de pendência de segredo pós-import (spec F6 §3.2-8, decisão A-4, achado
 * F6R-14). Espelha `ottima_core.portability.pendencias.pendencias_da_conexao`
 * (packages/ottima-core/src/ottima_core/portability/pendencias.py) byte a byte na
 * semântica das 3 fórmulas — único lugar de verdade no cliente; nenhuma outra tela
 * reimplementa os predicados. Puro: sem I/O.
 *
 * Ordem fixa de exibição, igual nas duas funções abaixo, para a coluna de pendências
 * (spec §6.3-2) não mudar de forma entre renders: senha, certificado_servidor,
 * certificado_aplicacao.
 */
export type Pendencia = "senha" | "certificado_servidor" | "certificado_aplicacao";

type PendingSecretOut = components["schemas"]["PendingSecretOut"];

/**
 * `appCertExiste: null` significa "não avaliável" — o papel operador não lê
 * `GET /api/certificates/app` (`require_admin`, plano F6b decisão de RBAC), então o
 * terceiro predicado simplesmente não aparece; `null` nunca é tratado como `false`.
 */
export function pendenciasDaConexao(
  conexao: Pick<ConnectionOut, "auth_mode" | "has_password" | "security_policy" | "server_cert_file">,
  appCertExiste: boolean | null,
): Pendencia[] {
  const pendencias: Pendencia[] = [];
  if (conexao.auth_mode === "user_password" && !conexao.has_password) {
    pendencias.push("senha");
  }
  if (conexao.security_policy !== "none" && !conexao.server_cert_file) {
    pendencias.push("certificado_servidor");
  }
  if (
    (conexao.security_policy !== "none" || conexao.auth_mode === "certificate") &&
    appCertExiste === false
  ) {
    pendencias.push("certificado_aplicacao");
  }
  return pendencias;
}

/** Traduz o `PendingSecretOut` da resposta de import (tarefa 2.3/3.2-8) para o mesmo
 *  vocabulário — precisa concordar com `pendenciasDaConexao` para a mesma conexão. */
export function pendenciasDoResumo(p: PendingSecretOut): Pendencia[] {
  const pendencias: Pendencia[] = [];
  if (p.needs_password) pendencias.push("senha");
  if (p.needs_server_certificate) pendencias.push("certificado_servidor");
  if (p.needs_app_certificate) pendencias.push("certificado_aplicacao");
  return pendencias;
}

export const ROTULO_PENDENCIA: Record<Pendencia, string> = {
  senha: "Senha",
  certificado_servidor: "Certificado do servidor",
  certificado_aplicacao: "Certificado de aplicação",
};

/** Texto do `title` por pendência (spec §6.3-3): o efeito exato, não um rótulo
 *  genérico. Códigos entre crases são os de `FailureReason`
 *  (`services/opc-worker/src/ottima_opc_worker/security.py`). */
export const EFEITO_PENDENCIA: Record<Pendencia, string> = {
  senha: "A conexão falhará em `connect_failed` até a senha ser informada novamente.",
  certificado_servidor:
    "A conexão falhará em `cert_missing` até confiar no certificado do servidor.",
  certificado_aplicacao:
    "A conexão falhará em `cert_missing` até gerar o certificado de aplicação da instalação.",
};
