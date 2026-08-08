import { expect, test } from "@playwright/test";

import { baixarArquivo, enviarBinario, lerJsonDeArquivo, nomeDoContentDisposition } from "./arquivos";

/**
 * Primitivos de arquivo (tarefa 1.2 do plano F6b, spec §6.0-2/3, F6R-10).
 *
 * `arquivos.ts` reusa `apiResposta`/`api` de `./api.ts` (tarefa 1.1) — nenhum destes testes
 * chama `fetch` diretamente sem passar pelo helper. `api.ts`/`arquivos.ts` referenciam globais
 * de browser (`localStorage`, `window.location`, `document`, `URL.createObjectURL`) que não
 * existem no Node puro deste runner; os stubs abaixo são o mínimo de "browser" necessário.
 * `fetch`/`Headers`/`Response`/`Blob`/`File`/`URL` já são nativos do Node 22.
 */

type LocalStorageMinimo = {
  getItem: (chave: string) => string | null;
  setItem: (chave: string, valor: string) => void;
  removeItem: (chave: string) => void;
};

type AncoraFalsa = { href: string; download: string; cliques: number; click: () => void };

const navegadorFalso = globalThis as unknown as {
  localStorage: LocalStorageMinimo;
  window: { location: { assign: (url: string) => void } };
  fetch: typeof fetch;
  document: { createElement: (tag: string) => AncoraFalsa; body: { appendChild: (n: unknown) => void; removeChild: (n: unknown) => void } };
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

function instalarWindowFalso() {
  navegadorFalso.window = { location: { assign: () => {} } };
}

function instalarFetchFalso(
  handler: (chamada: { path: string; headers: Headers; body: unknown }) => Response | Promise<Response>,
) {
  navegadorFalso.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = typeof input === "string" ? input : input.toString();
    return handler({ path, headers: new Headers(init?.headers), body: init?.body });
  }) as typeof fetch;
}

/** Nós do DOM que `document.body.appendChild`/`removeChild` recebem, na ordem das chamadas. */
function instalarDocumentFalso() {
  const nosNoBody: AncoraFalsa[] = [];
  const removidos: AncoraFalsa[] = [];
  navegadorFalso.document = {
    createElement: (tag: string): AncoraFalsa => {
      if (tag !== "a") throw new Error(`elemento inesperado: ${tag}`);
      const ancora: AncoraFalsa = { href: "", download: "", cliques: 0, click: () => {} };
      ancora.click = () => {
        ancora.cliques += 1;
      };
      return ancora;
    },
    body: {
      appendChild: (n) => nosNoBody.push(n as AncoraFalsa),
      removeChild: (n) => removidos.push(n as AncoraFalsa),
    },
  };
  return { nosNoBody, removidos };
}

test.beforeEach(() => {
  instalarLocalStorageFalso();
  instalarWindowFalso();
});

// --- nomeDoContentDisposition -----------------------------------------------------------

test("filename simples entre aspas", () => {
  expect(nomeDoContentDisposition('attachment; filename="planta-c-101.ottima.json"')).toBe(
    "planta-c-101.ottima.json",
  );
});

test("filename sem aspas", () => {
  expect(nomeDoContentDisposition("attachment; filename=planta.json")).toBe("planta.json");
});

test("filename com espacos extras ao redor do =", () => {
  expect(nomeDoContentDisposition('attachment;   filename  =   "planta.json"')).toBe("planta.json");
});

test("filename* (RFC 5987) tem precedencia sobre filename simples quando os dois estao presentes", () => {
  expect(
    nomeDoContentDisposition(
      "attachment; filename=\"fallback.json\"; filename*=UTF-8''especial.json",
    ),
  ).toBe("especial.json");
});

test("filename* decodifica percent-encoding UTF-8", () => {
  expect(nomeDoContentDisposition("attachment; filename*=UTF-8''plantas%20%E2%82%AC.json")).toBe(
    "plantas €.json",
  );
});

test("header ausente (null) devolve null", () => {
  expect(nomeDoContentDisposition(null)).toBeNull();
});

test("header presente sem filename devolve null", () => {
  expect(nomeDoContentDisposition("attachment")).toBeNull();
});

test("path traversal em filename e reduzido ao nome base, nunca um caminho", () => {
  expect(nomeDoContentDisposition('attachment; filename="../../etc/passwd"')).toBe("passwd");
  expect(nomeDoContentDisposition('attachment; filename="..\\..\\evil.json"')).toBe("evil.json");
});

test("filename que colapsa para '..' apos sanitizacao devolve null, nunca um caminho", () => {
  expect(nomeDoContentDisposition('attachment; filename="../.."')).toBeNull();
});

// --- baixarArquivo -----------------------------------------------------------------------

test("baixarArquivo: usa o nome do Content-Disposition, cria e clica a ancora, e revoga o object URL no finally", async () => {
  const { nosNoBody, removidos } = instalarDocumentFalso();
  instalarFetchFalso(
    () =>
      new Response("conteudo do arquivo", {
        status: 200,
        headers: { "Content-Disposition": 'attachment; filename="projeto-x.ottima.json"' },
      }),
  );
  const urlsRevogadas: string[] = [];
  const revokeOriginal = URL.revokeObjectURL;
  URL.revokeObjectURL = (url: string) => {
    urlsRevogadas.push(url);
  };
  try {
    await baixarArquivo("/api/projects/1/export", "fallback.ottima.json");
  } finally {
    URL.revokeObjectURL = revokeOriginal;
  }

  expect(nosNoBody).toHaveLength(1);
  expect(nosNoBody[0].download).toBe("projeto-x.ottima.json");
  expect(nosNoBody[0].href.startsWith("blob:")).toBe(true);
  expect(nosNoBody[0].cliques).toBe(1);
  expect(removidos).toHaveLength(1);
  // prova, não afirma: o object URL revogado é exatamente o href atribuído à ancora.
  expect(urlsRevogadas).toEqual([nosNoBody[0].href]);
});

test("baixarArquivo: sem Content-Disposition usavel, usa nomePadrao", async () => {
  const { nosNoBody } = instalarDocumentFalso();
  instalarFetchFalso(() => new Response("dados", { status: 200 }));
  const revokeOriginal = URL.revokeObjectURL;
  URL.revokeObjectURL = () => {};
  try {
    await baixarArquivo("/api/certificates/app/export", "fallback.der");
  } finally {
    URL.revokeObjectURL = revokeOriginal;
  }
  expect(nosNoBody[0].download).toBe("fallback.der");
});

test("baixarArquivo: revoga o object URL mesmo se click() lancar", async () => {
  navegadorFalso.document = {
    createElement: () => {
      const ancora: AncoraFalsa = {
        href: "",
        download: "",
        cliques: 0,
        click: () => {
          throw new Error("falha simulada no click");
        },
      };
      return ancora;
    },
    body: { appendChild: () => {}, removeChild: () => {} },
  };
  instalarFetchFalso(() => new Response("dados", { status: 200 }));
  const urlsRevogadas: string[] = [];
  const revokeOriginal = URL.revokeObjectURL;
  URL.revokeObjectURL = (url: string) => {
    urlsRevogadas.push(url);
  };
  try {
    await expect(baixarArquivo("/api/x", "fallback.json")).rejects.toThrow("falha simulada no click");
  } finally {
    URL.revokeObjectURL = revokeOriginal;
  }
  expect(urlsRevogadas).toHaveLength(1);
});

// --- enviarBinario -------------------------------------------------------------------------

test("enviarBinario: preserva o Content-Type do chamador ate a chamada de fetch, e nunca usa FormData", async () => {
  let corposCapturados: { headers: Headers; body: unknown } | undefined;
  instalarFetchFalso((chamada) => {
    corposCapturados = chamada;
    return new Response(JSON.stringify({ ok: true }), { status: 200 });
  });
  const arquivo = new File([new Uint8Array([1, 2, 3])], "app.der", { type: "" });

  const resultado = await enviarBinario<{ ok: boolean }>(
    "/api/connections/1/server-certificate",
    arquivo,
    "application/pkix-cert",
  );

  expect(resultado).toEqual({ ok: true });
  expect(corposCapturados?.headers.get("Content-Type")).toBe("application/pkix-cert");
  expect(corposCapturados?.body instanceof FormData).toBe(false);
  expect(corposCapturados?.body instanceof Blob).toBe(true);
  expect(await (corposCapturados?.body as Blob).arrayBuffer()).toEqual(new Uint8Array([1, 2, 3]).buffer);
});

// --- lerJsonDeArquivo -----------------------------------------------------------------------

test("lerJsonDeArquivo: JSON valido e parseado", async () => {
  const arquivo = new File([JSON.stringify({ schema_version: 1 })], "projeto.ottima.json", {
    type: "application/json",
  });
  await expect(lerJsonDeArquivo(arquivo)).resolves.toEqual({ schema_version: 1 });
});

test("lerJsonDeArquivo: JSON invalido rejeita com mensagem pt-BR, nunca SyntaxError cru", async () => {
  const arquivo = new File(["{ isto nao e json"], "projeto.ottima.json", { type: "application/json" });
  await expect(lerJsonDeArquivo(arquivo)).rejects.toThrow("não contém JSON válido");
  try {
    await lerJsonDeArquivo(arquivo);
    throw new Error("nao deveria chegar aqui");
  } catch (erro) {
    expect(erro).toBeInstanceOf(Error);
    expect(erro).not.toBeInstanceOf(SyntaxError);
  }
});
