import type { ConnectionOut } from "../../lib/api";

/**
 * `conexoesAfetadasPorRegeracao` — tarefa 3.1 do plano F6b (spec §6.2-1, SEC-06).
 *
 * Regenerar o certificado de aplicação troca a identidade do worker perante os servidores
 * OPC-UA: as conexões que usam segurança de transporte (`security_policy !== "none"`) OU
 * autenticam por certificado (`auth_mode === "certificate"`, possível mesmo com política
 * "none" — os dois campos são independentes no schema) exigirão re-trust manual depois da
 * troca. Mesma fórmula de `pendencias.ts:35-38` para o terceiro predicado — um só lugar de
 * verdade para "esta conexão depende do certificado de aplicação".
 *
 * Pura, computada no cliente sobre a lista de conexões já carregada por `ConnectionsPage`
 * (SEC-06: nenhuma requisição nova só para listar o impacto).
 */
type ConexaoRelevante = Pick<ConnectionOut, "id" | "name" | "security_policy" | "auth_mode">;

export function conexoesAfetadasPorRegeracao<T extends ConexaoRelevante>(
  conexoes: readonly T[],
): T[] {
  return conexoes.filter((c) => c.security_policy !== "none" || c.auth_mode === "certificate");
}
