import { expect, test } from "@playwright/test";

import { api, apiResposta, ApiError, getToken, setToken } from "./api";

/**
 * `api()`/`apiResposta()` (tarefa 1.1 do plano F6b, spec §6.0-1, F6R-10) — o helper de fetch
 * ganha uma segunda função que devolve a `Response` crua (para `blob()`/headers de download,
 * usados por `arquivos.ts` na tarefa 1.2) sem duplicar auth/401/`ApiError`, e o `Content-Type`
 * deixa de ser sobrescrito quando o chamador já definiu o header — condição para o upload
 * binário de certificado da tarefa 3.2.
 *
 * `api.ts` assume globais de browser (`localStorage`, `window.location`) que não existem no
 * Node puro deste runner (`playwright.unit.config.ts` não carrega jsdom). Os stubs abaixo são
 * o mínimo de "browser" necessário para exercitar o helper aqui; `fetch`/`Headers`/`Response`
 * já são nativos do Node 22 e não precisam de stub.
 */

type LocalStorageMinimo = {
  getItem: (chave: string) => string | null;
  setItem: (chave: string, valor: string) => void;
  removeItem: (chave: string) => void;
};

// api.ts referencia `localStorage`/`window`/`fetch` como globais de DOM; este runner é Node
// puro, então o teste precisa preencher esse mesmo globalThis com o mínimo exigido. Cast único,
// nomeado, reaproveitado por todos os stubs abaixo (nunca inline num acesso de propriedade).
const navegadorFalso = globalThis as unknown as {
  localStorage: LocalStorageMinimo;
  window: { location: { assign: (url: string) => void } };
  fetch: typeof fetch;
};

function instalarLocalStorageFalso() {
  const armazenamento = new Map<string, string>();
  navegadorFalso.localStorage = {
    getItem: (chave) => armazenamento.get(chave) ?? null,
    setItem: (chave, valor) => {
      armazenamento.set(chave, valor);
    },
    removeItem: (chave) => {
      armazenamento.delete(chave);
    },
  };
}

function instalarWindowFalso(): string[] {
  const urlsRedirecionadas: string[] = [];
  navegadorFalso.window = { location: { assign: (url) => urlsRedirecionadas.push(url) } };
  return urlsRedirecionadas;
}

function instalarFetchFalso(handler: (chamada: { path: string; headers: Headers }) => Response | Promise<Response>) {
  navegadorFalso.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = typeof input === "string" ? input : input.toString();
    return handler({ path, headers: new Headers(init?.headers) });
  }) as typeof fetch;
}

test.beforeEach(() => {
  instalarLocalStorageFalso();
  instalarWindowFalso();
});

test("sem header do chamador: Content-Type: application/json é aplicado quando há body", async () => {
  let headersRecebidos: Headers | undefined;
  instalarFetchFalso(({ headers }) => {
    headersRecebidos = headers;
    return new Response("{}", { status: 200 });
  });
  await api("/api/x", { method: "POST", body: JSON.stringify({ a: 1 }) });
  expect(headersRecebidos?.get("Content-Type")).toBe("application/json");
});

test("sem body: Content-Type não é forçado", async () => {
  let headersRecebidos: Headers | undefined;
  instalarFetchFalso(({ headers }) => {
    headersRecebidos = headers;
    return new Response("{}", { status: 200 });
  });
  await api("/api/x", { method: "GET" });
  expect(headersRecebidos?.has("Content-Type")).toBe(false);
});

test("Content-Type do chamador em maiúsculas (objeto literal) é preservado", async () => {
  let headersRecebidos: Headers | undefined;
  instalarFetchFalso(({ headers }) => {
    headersRecebidos = headers;
    return new Response(null, { status: 200 });
  });
  await api("/api/certificates/app/import", {
    method: "POST",
    headers: { "Content-Type": "application/x-pem-file" },
    body: new Uint8Array([1, 2, 3]),
  });
  expect(headersRecebidos?.get("Content-Type")).toBe("application/x-pem-file");
});

test("Content-Type do chamador em minúsculas (objeto literal) é preservado", async () => {
  let headersRecebidos: Headers | undefined;
  instalarFetchFalso(({ headers }) => {
    headersRecebidos = headers;
    return new Response(null, { status: 200 });
  });
  await api("/api/certificates/app/import", {
    method: "POST",
    headers: { "content-type": "application/octet-stream" },
    body: new Uint8Array([1, 2, 3]),
  });
  expect(headersRecebidos?.get("Content-Type")).toBe("application/octet-stream");
});

test("Content-Type do chamador passado como instância de Headers é preservado", async () => {
  let headersRecebidos: Headers | undefined;
  instalarFetchFalso(({ headers }) => {
    headersRecebidos = headers;
    return new Response(null, { status: 200 });
  });
  const headersDoChamador = new Headers();
  headersDoChamador.set("Content-Type", "application/pkix-cert");
  await api("/api/certificates/app/import", {
    method: "POST",
    headers: headersDoChamador,
    body: new Uint8Array([1, 2, 3]),
  });
  expect(headersRecebidos?.get("Content-Type")).toBe("application/pkix-cert");
});

test("Content-Type do chamador passado como array de pares é preservado", async () => {
  let headersRecebidos: Headers | undefined;
  instalarFetchFalso(({ headers }) => {
    headersRecebidos = headers;
    return new Response(null, { status: 200 });
  });
  await api("/api/certificates/app/import", {
    method: "POST",
    headers: [["Content-Type", "application/x-pem-file"]],
    body: new Uint8Array([1, 2, 3]),
  });
  expect(headersRecebidos?.get("Content-Type")).toBe("application/x-pem-file");
});

test("apiResposta devolve a Response crua com headers legíveis (Content-Disposition)", async () => {
  instalarFetchFalso(
    () =>
      new Response("conteudo binario", {
        status: 200,
        headers: { "Content-Disposition": 'attachment; filename="projeto.ottima.json"' },
      }),
  );
  const res = await apiResposta("/api/projects/1/export");
  expect(res.headers.get("Content-Disposition")).toBe('attachment; filename="projeto.ottima.json"');
  expect(await res.text()).toBe("conteudo binario");
});

test("401 fora de /auth/login dispara o interceptor em api(): limpa token, redireciona e lança ApiError", async () => {
  setToken("token-antigo");
  const urlsRedirecionadas = instalarWindowFalso();
  instalarFetchFalso(() => new Response(null, { status: 401 }));
  await expect(api("/api/projects")).rejects.toThrow(ApiError);
  expect(getToken()).toBeNull();
  expect(urlsRedirecionadas).toEqual(["/login"]);
});

test("401 fora de /auth/login dispara o interceptor em apiResposta(): limpa token, redireciona e lança ApiError", async () => {
  setToken("token-antigo");
  const urlsRedirecionadas = instalarWindowFalso();
  instalarFetchFalso(() => new Response(null, { status: 401 }));
  await expect(apiResposta("/api/projects")).rejects.toThrow(ApiError);
  expect(getToken()).toBeNull();
  expect(urlsRedirecionadas).toEqual(["/login"]);
});

test("401 em /auth/login não dispara o interceptor (login errado é erro normal)", async () => {
  const urlsRedirecionadas = instalarWindowFalso();
  instalarFetchFalso(() => new Response(JSON.stringify({ detail: "Credenciais inválidas" }), { status: 401 }));
  await expect(api("/api/auth/login", { method: "POST" })).rejects.toThrow(ApiError);
  expect(urlsRedirecionadas).toEqual([]);
});

test("corpo vazio (204) continua tratado: api() devolve undefined", async () => {
  instalarFetchFalso(() => new Response(null, { status: 204 }));
  const resultado = await api("/api/connections/1");
  expect(resultado).toBeUndefined();
});

test("corpo JSON não vazio continua parseado normalmente", async () => {
  instalarFetchFalso(() => new Response(JSON.stringify({ id: 1, nome: "x" }), { status: 200 }));
  const resultado = await api<{ id: number; nome: string }>("/api/projects/1");
  expect(resultado).toEqual({ id: 1, nome: "x" });
});

test("ApiError continua carregando status e detail do backend", async () => {
  instalarFetchFalso(() => new Response(JSON.stringify({ detail: "Nome em uso" }), { status: 409 }));
  try {
    await api("/api/projects", { method: "POST", body: JSON.stringify({ name: "x" }) });
    throw new Error("deveria ter lançado ApiError");
  } catch (erro) {
    if (!(erro instanceof ApiError)) throw erro;
    expect(erro.status).toBe(409);
    expect(erro.message).toBe("Nome em uso");
  }
});

test("ApiError usa mensagem padrão quando o corpo de erro não tem detail string", async () => {
  instalarFetchFalso(() => new Response("não é json", { status: 500 }));
  try {
    await api("/api/projects");
    throw new Error("deveria ter lançado ApiError");
  } catch (erro) {
    if (!(erro instanceof ApiError)) throw erro;
    expect(erro.status).toBe(500);
    expect(erro.message).toBe("Erro inesperado");
  }
});
