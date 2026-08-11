import { expect, type APIRequestContext, type Page, request } from "@playwright/test";

export const ADMIN = {
  username: process.env.E2E_ADMIN_USERNAME ?? "admin",
  password: process.env.E2E_ADMIN_PASSWORD ?? "",
};

/** Operador de teste: nome fixo e recriação tolerante a 409 — o banco do stack é persistente. */
export const OPERATOR = { username: "operador-e2e", password: "operador-12345" };

/** Sufixo único por execução: nada criado por um run colide com o do run anterior. */
export const RUN_ID = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;

export async function adminToken(baseURL: string): Promise<string> {
  const ctx = await request.newContext({ baseURL });
  const res = await ctx.post("/api/auth/login", {
    data: { username: ADMIN.username, password: ADMIN.password },
  });
  if (!res.ok()) throw new Error(`login do admin falhou: HTTP ${res.status()}`);
  const body = (await res.json()) as { access_token: string };
  await ctx.dispose();
  return body.access_token;
}

/** Contexto REST já autenticado como admin — quem chama é responsável pelo `dispose()`. */
export async function adminApi(baseURL: string): Promise<APIRequestContext> {
  const token = await adminToken(baseURL);
  return request.newContext({
    baseURL,
    extraHTTPHeaders: { Authorization: `Bearer ${token}` },
  });
}

export async function ensureOperator(baseURL: string): Promise<void> {
  const ctx = await adminApi(baseURL);
  const res = await ctx.post("/api/users", {
    data: {
      username: OPERATOR.username,
      name: "Operador E2E",
      password: OPERATOR.password,
      role: "operator",
    },
  });
  if (!res.ok() && res.status() !== 409) {
    throw new Error(`criação do operador falhou: HTTP ${res.status()}`);
  }
  await ctx.dispose();
}

/** Login pela UI (o gate exige o caminho real do usuário, não injeção de token). */
export async function fazerLogin(page: Page, username: string, password: string): Promise<void> {
  await page.goto("/login");
  await page.getByTestId("login-username").fill(username);
  await page.getByTestId("login-password").fill(password);
  await page.getByTestId("login-submit").click();
}

/**
 * Login que só retorna com o shell no ar.
 *
 * `fazerLogin` clica em "Entrar" e volta na hora — E2E-06 depende disso para asseverar que
 * credencial errada NÃO navega. Quem faz `page.goto(...)` logo depois do login precisa desta
 * versão: sem esperar a navegação, o `goto` corre contra o guard de rota, que ainda não vê o
 * token e devolve tudo para `/login`.
 */
export async function entrarNoShell(
  page: Page,
  username: string = ADMIN.username,
  password: string = ADMIN.password,
): Promise<void> {
  await fazerLogin(page, username, password);
  await expect(page).toHaveURL(/\/$/);
}

/** Endpoint do opcsim de DENTRO da rede do compose — é o que vai no cadastro da conexão. */
export const OPCSIM_ENDPOINT = process.env.E2E_OPCSIM_URL ?? "opc.tcp://opcsim:4840";

/** Nodes do opcsim usados pelos specs (espelho de `tests/opcsim/src/opcsim/server.py`). */
export const NODES = {
  sine: "ns=2;s=sim.float.sine",
  static: "ns=2;s=sim.float.static",
  wFloat: "ns=2;s=sim.w.float",
  wInt: "ns=2;s=sim.w.int",
  mirrorFloat: "ns=2;s=sim.mirror.float",
  mirrorInt: "ns=2;s=sim.mirror.int",
  wdFrom: "ns=2;s=sim.watchdog.from_system",
  wdTo: "ns=2;s=sim.watchdog.to_system",
} as const;

/** A API não expõe "desativar" e excluir o projeto ativo dá 409: o teardown reativa esta
 *  sentinela estável quando não havia projeto ativo antes (precedente do E2E-16). */
export const SENTINELA = "E2E sentinela (não excluir)";

type Projeto = { id: number; name: string; is_active: boolean };

/** Toda criação da API responde com o recurso; aqui só o id importa. */
type RecursoCriado = { id: number };

export interface TagDesejada {
  readonly chave: string;
  readonly nodeId: string;
  readonly direcao: "r" | "w";
  readonly tipo?: "float" | "int" | "bool";
}

export interface AmbienteE2E {
  readonly api: APIRequestContext;
  readonly projectId: number;
  readonly connId: number;
  /** `chave` da `TagDesejada` -> id da tag criada. */
  readonly tags: Readonly<Record<string, number>>;
  readonly encerrar: () => Promise<void>;
}

async function listarProjetos(api: APIRequestContext): Promise<Projeto[]> {
  const res = await api.get("/api/projects");
  if (!res.ok()) throw new Error(`listagem de projetos: HTTP ${res.status()}`);
  return (await res.json()) as Projeto[];
}

async function garantirSentinela(api: APIRequestContext): Promise<Projeto> {
  const res = await api.post("/api/projects", { data: { name: SENTINELA } });
  if (res.ok()) return (await res.json()) as Projeto;
  if (res.status() !== 409) throw new Error(`criação da sentinela: HTTP ${res.status()}`);
  const existente = (await listarProjetos(api)).find((p) => p.name === SENTINELA);
  if (!existente) throw new Error("sentinela duplicada mas ausente na listagem");
  return existente;
}

/**
 * Projeto ATIVO com uma conexão ao opcsim e as tags pedidas, montado por API no `beforeAll`.
 *
 * `encerrar()` devolve o sistema ao estado inicial: reativa o projeto que estava ativo (ou a
 * sentinela) e só então exclui o que este spec criou — excluir o ativo é 409.
 */
export async function criarAmbiente(
  baseURL: string,
  opts: { readonly sufixo: string; readonly tags: readonly TagDesejada[] },
): Promise<AmbienteE2E> {
  const api = await adminApi(baseURL);
  const anterior = (await listarProjetos(api)).find((p) => p.is_active) ?? null;
  const nome = `E2E ${opts.sufixo} ${RUN_ID}`;
  const criado = await api.post("/api/projects", { data: { name: nome } });
  if (!criado.ok()) throw new Error(`criação do projeto: HTTP ${criado.status()}`);
  const projeto = (await criado.json()) as Projeto;

  const ativou = await api.post(`/api/projects/${projeto.id}/activate`);
  if (!ativou.ok()) throw new Error(`ativação do projeto: HTTP ${ativou.status()}`);

  const conexao = await api.post("/api/connections", {
    data: {
      project_id: projeto.id,
      name: `opcsim-${opts.sufixo}-${RUN_ID}`,
      endpoint: OPCSIM_ENDPOINT,
      security_policy: "none",
      security_mode: "none",
      auth_mode: "anonymous",
    },
  });
  if (!conexao.ok()) throw new Error(`criação da conexão: HTTP ${conexao.status()}`);
  const conexaoCriada = (await conexao.json()) as RecursoCriado;
  const connId = conexaoCriada.id;

  const tags: Record<string, number> = {};
  for (const tag of opts.tags) {
    const criada = await api.post("/api/tags", {
      data: {
        connection_id: connId,
        name: `${tag.chave}-${opts.sufixo}-${RUN_ID}`,
        node_id: tag.nodeId,
        direction: tag.direcao,
        data_type: tag.tipo ?? "float",
      },
    });
    if (!criada.ok()) throw new Error(`criação da tag ${tag.chave}: HTTP ${criada.status()}`);
    const tagCriada = (await criada.json()) as RecursoCriado;
    tags[tag.chave] = tagCriada.id;
  }

  return {
    api,
    projectId: projeto.id,
    connId,
    tags,
    encerrar: async () => {
      const restaurar = anterior ?? (await garantirSentinela(api));
      await api.post(`/api/projects/${restaurar.id}/activate`);
      await api.delete(`/api/projects/${projeto.id}`);
      await api.dispose();
    },
  };
}
