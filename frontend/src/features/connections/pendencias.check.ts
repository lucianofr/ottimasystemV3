import { expect, test } from "@playwright/test";

import type { ConnectionOut } from "../../lib/api";
import type { components } from "../../lib/api-types";
import {
  EFEITO_PENDENCIA,
  ROTULO_PENDENCIA,
  pendenciasDaConexao,
  pendenciasDoResumo,
  type Pendencia,
} from "./pendencias";

/**
 * `pendencias.ts` — tarefa 1.4 do plano F6b (spec F6 §3.2-8/§6.3, decisão A-4, F6R-14).
 * Espelha `packages/ottima-core/src/ottima_core/portability/pendencias.py`; as fórmulas
 * abaixo são transcritas da spec, não do módulo sob teste (mesmo padrão de
 * `test_pendencias.py` no backend: fórmula independente, não round-trip tautológico).
 */

type ConexaoPendencia = Pick<
  ConnectionOut,
  "auth_mode" | "has_password" | "security_policy" | "server_cert_file"
>;
type PendingSecretOut = components["schemas"]["PendingSecretOut"];

const AUTH_MODES = ["anonymous", "user_password", "certificate"] as const;
const BOOLEANOS = [true, false] as const;
const POLICIES = ["none", "basic256sha256"] as const;
const SERVER_CERT_FILES = [null, "server.der"] as const;
const APP_CERT_EXISTE = [true, false, null] as const;

/** As 3 fórmulas de §3.2-8, transcritas literalmente da spec. */
function formula(
  authMode: (typeof AUTH_MODES)[number],
  hasPassword: boolean,
  securityPolicy: (typeof POLICIES)[number],
  serverCertFile: string | null,
  appCertExiste: boolean | null,
): Pendencia[] {
  const pendencias: Pendencia[] = [];
  if (authMode === "user_password" && !hasPassword) pendencias.push("senha");
  if (securityPolicy !== "none" && !serverCertFile) pendencias.push("certificado_servidor");
  if ((securityPolicy !== "none" || authMode === "certificate") && appCertExiste === false) {
    pendencias.push("certificado_aplicacao");
  }
  return pendencias;
}

test("tabela-verdade completa: 3(auth_mode) x 2(has_password) x 2(security_policy) x 2(server_cert_file) x 3(appCertExiste) = 72 casos batem com §3.2-8", () => {
  let casos = 0;
  for (const authMode of AUTH_MODES) {
    for (const hasPassword of BOOLEANOS) {
      for (const securityPolicy of POLICIES) {
        for (const serverCertFile of SERVER_CERT_FILES) {
          for (const appCertExiste of APP_CERT_EXISTE) {
            casos += 1;
            const conexao: ConexaoPendencia = {
              auth_mode: authMode,
              has_password: hasPassword,
              security_policy: securityPolicy,
              server_cert_file: serverCertFile,
            };
            expect(pendenciasDaConexao(conexao, appCertExiste)).toEqual(
              formula(authMode, hasPassword, securityPolicy, serverCertFile, appCertExiste),
            );
          }
        }
      }
    }
  }
  expect(casos).toBe(72);
});

test("server_cert_file vazio conta como ausente, igual ao backend (§3.2-8 fala 'ausente/vazio')", () => {
  const conexao: ConexaoPendencia = {
    auth_mode: "anonymous",
    has_password: false,
    security_policy: "basic256sha256",
    server_cert_file: "",
  };
  expect(pendenciasDaConexao(conexao, true)).toEqual(["certificado_servidor"]);
});

test("F6R-14: auth_mode certificate + security_policy none + appCertExiste false ⇒ exatamente [certificado_aplicacao]", () => {
  const conexao: ConexaoPendencia = {
    auth_mode: "certificate",
    has_password: false,
    security_policy: "none",
    server_cert_file: null,
  };
  expect(pendenciasDaConexao(conexao, false)).toEqual(["certificado_aplicacao"]);
});

test("appCertExiste null nunca inclui certificado_aplicacao, mesmo quando o predicado seria avaliável", () => {
  const conexao: ConexaoPendencia = {
    auth_mode: "certificate",
    has_password: false,
    security_policy: "basic256sha256",
    server_cert_file: "server.der",
  };
  expect(pendenciasDaConexao(conexao, null)).toEqual([]);
});

test("pendenciasDaConexao e pendenciasDoResumo concordam para a mesma conexão — 3x2x2x2x2 = 48 casos (domínio do backend, sem o null do cliente)", () => {
  let casos = 0;
  for (const authMode of AUTH_MODES) {
    for (const hasPassword of BOOLEANOS) {
      for (const securityPolicy of POLICIES) {
        for (const serverCertFile of SERVER_CERT_FILES) {
          for (const appCertExiste of BOOLEANOS) {
            casos += 1;
            const conexao: ConexaoPendencia = {
              auth_mode: authMode,
              has_password: hasPassword,
              security_policy: securityPolicy,
              server_cert_file: serverCertFile,
            };
            const resumo: PendingSecretOut = {
              connection_name: "conexao-teste",
              needs_password: authMode === "user_password" && !hasPassword,
              needs_server_certificate: securityPolicy !== "none" && !serverCertFile,
              needs_app_certificate:
                (securityPolicy !== "none" || authMode === "certificate") && !appCertExiste,
            };
            expect(pendenciasDoResumo(resumo)).toEqual(
              pendenciasDaConexao(conexao, appCertExiste),
            );
          }
        }
      }
    }
  }
  expect(casos).toBe(48);
});

test("ordem de saída é estável: senha, depois certificado_servidor, depois certificado_aplicacao — nunca muda de forma entre renders", () => {
  const todasTres: ConexaoPendencia = {
    auth_mode: "user_password",
    has_password: false,
    security_policy: "basic256sha256",
    server_cert_file: null,
  };
  expect(pendenciasDaConexao(todasTres, false)).toEqual([
    "senha",
    "certificado_servidor",
    "certificado_aplicacao",
  ]);

  const duasSemSenha: ConexaoPendencia = {
    auth_mode: "certificate",
    has_password: false,
    security_policy: "basic256sha256",
    server_cert_file: null,
  };
  expect(pendenciasDaConexao(duasSemSenha, false)).toEqual([
    "certificado_servidor",
    "certificado_aplicacao",
  ]);

  expect(
    pendenciasDoResumo({
      connection_name: "conexao-teste",
      needs_password: true,
      needs_server_certificate: true,
      needs_app_certificate: true,
    }),
  ).toEqual(["senha", "certificado_servidor", "certificado_aplicacao"]);
});

test("EFEITO_PENDENCIA bate, por igualdade exata, com o texto verbatim do plano F6b tarefa 1.4 (docs/plans/F6b-superficies.md:88)", () => {
  // Verbatim do plano: "a conexão falhará em `cert_missing` até confiar no certificado do
  // servidor" / "…até gerar o certificado de aplicação da instalação" / "a conexão falhará
  // na autenticação até a senha ser reinformada" — capitalização inicial e ponto final são
  // normalização de sentença de UI, não paráfrase; o conteúdo é idêntico palavra por palavra.
  expect(EFEITO_PENDENCIA.senha).toBe(
    "A conexão falhará na autenticação até a senha ser reinformada.",
  );
  expect(EFEITO_PENDENCIA.certificado_servidor).toBe(
    "A conexão falhará em `cert_missing` até confiar no certificado do servidor.",
  );
  expect(EFEITO_PENDENCIA.certificado_aplicacao).toBe(
    "A conexão falhará em `cert_missing` até gerar o certificado de aplicação da instalação.",
  );
});

test("ROTULO_PENDENCIA bate, por igualdade exata, com os rótulos curtos definidos em pendencias.ts (não fixados verbatim pelo plano, mas travados aqui como contrato do módulo)", () => {
  expect(ROTULO_PENDENCIA.senha).toBe("Senha");
  expect(ROTULO_PENDENCIA.certificado_servidor).toBe("Certificado do servidor");
  expect(ROTULO_PENDENCIA.certificado_aplicacao).toBe("Certificado de aplicação");
});

test("ROTULO_PENDENCIA e EFEITO_PENDENCIA cobrem as 3 pendências, pt-BR, sem a palavra 'bundle' e sem emoji", () => {
  const pendencias: Pendencia[] = ["senha", "certificado_servidor", "certificado_aplicacao"];
  const emoji = /\p{Extended_Pictographic}/u;
  for (const p of pendencias) {
    expect(ROTULO_PENDENCIA[p].length).toBeGreaterThan(0);
    expect(EFEITO_PENDENCIA[p].length).toBeGreaterThan(0);
    expect(ROTULO_PENDENCIA[p].toLowerCase()).not.toContain("bundle");
    expect(EFEITO_PENDENCIA[p].toLowerCase()).not.toContain("bundle");
    expect(emoji.test(ROTULO_PENDENCIA[p])).toBe(false);
    expect(emoji.test(EFEITO_PENDENCIA[p])).toBe(false);
  }
});
