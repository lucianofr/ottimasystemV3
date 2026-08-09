import { api, apiResposta } from "./api";

/**
 * Primitivos de arquivo (tarefa 1.2 do plano F6b, spec §6.0-2/3, F6R-10).
 *
 * `apiResposta` (tarefa 1.1) é a única porta de entrada para `fetch`: carrega auth, trata 401
 * e devolve a `Response` crua. `baixarArquivo` e `enviarBinario` são construídos em cima dela e
 * nunca chamam `fetch` diretamente — o app autentica por header `Authorization`, e uma navegação
 * de `<a href>` simples ou um upload por `fetch` avulso não carregaria esse header.
 */

/**
 * Extrai o nome de arquivo de um cabeçalho `Content-Disposition` (RFC 6266).
 *
 * Regras (decisão desta tarefa):
 * - `filename*=` (RFC 5987, notação estendida com charset) tem precedência sobre `filename=`
 *   simples quando os dois estão presentes — é o que servidores usam para nomes fora de ASCII.
 * - `filename=` aceita com ou sem aspas, com espaços extras ao redor do `=`.
 * - Sanitização contra path traversal: qualquer `/` ou `\` no valor extraído reduz o nome ao
 *   último segmento (nome base) — nunca um caminho. Se o resultado for vazio, `"."` ou `".."`,
 *   devolve `null`.
 * - Header ausente, ou presente sem `filename` utilizável: `null`.
 */
export function nomeDoContentDisposition(header: string | null): string | null {
  if (!header) return null;
  const estendido = header.match(/filename\*\s*=\s*[^;']*''([^;]+)/i);
  if (estendido) {
    let valorDecodificado = estendido[1].trim();
    try {
      valorDecodificado = decodeURIComponent(valorDecodificado);
    } catch {
      // percent-encoding malformado: usa o valor bruto, ainda sanitizado abaixo
    }
    const nome = nomeBaseSeguro(valorDecodificado);
    if (nome) return nome;
  }

  const simples = header.match(/filename\s*=\s*("([^"]*)"|[^;]+)/i);
  if (!simples) return null;
  const bruto = (simples[2] ?? simples[1]).trim();
  return nomeBaseSeguro(bruto);
}

function nomeBaseSeguro(bruto: string): string | null {
  const segmentos = bruto.split(/[/\\]+/);
  const base = (segmentos.at(-1) ?? "").trim();
  if (!base || base === "." || base === "..") return null;
  return base;
}

/**
 * Download autenticado (spec §6.0-3): `apiResposta` já carrega o header `Authorization`, então
 * `res.blob()` chega autenticado. O nome vem do `Content-Disposition` da resposta, com
 * `nomePadrao` como fallback. O object URL é sempre revogado e o nó de ancora sempre removido,
 * mesmo se `click()` lançar — vazamento de object URL é defeito.
 */
export async function baixarArquivo(path: string, nomePadrao: string): Promise<void> {
  const res = await apiResposta(path);
  const blob = await res.blob();
  const nome = nomeDoContentDisposition(res.headers.get("Content-Disposition")) ?? nomePadrao;
  const url = URL.createObjectURL(blob);
  const ancora = document.createElement("a");
  ancora.href = url;
  ancora.download = nome;
  document.body.appendChild(ancora);
  try {
    ancora.click();
  } finally {
    document.body.removeChild(ancora);
    URL.revokeObjectURL(url);
  }
}

/**
 * Upload binário cru (spec §6.0-2): o endpoint de trust lê o corpo bruto, não multipart, então
 * nunca usa `FormData`. `File.arrayBuffer()` vira um `Blob` com o `Content-Type` explícito
 * recebido em `tipo` — o tipo nativo do `File` (muitas vezes vazio para `.der`/`.pem`) é
 * ignorado de propósito. `api()` preserva esse header porque só aplica `application/json`
 * quando o chamador não definiu `Content-Type` (tarefa 1.1).
 */
export async function enviarBinario<T>(path: string, arquivo: File, tipo: string): Promise<T> {
  const bytes = await arquivo.arrayBuffer();
  const corpo = new Blob([bytes], { type: tipo });
  return api<T>(path, {
    method: "POST",
    headers: { "Content-Type": tipo },
    body: corpo,
  });
}

/**
 * Leitura de arquivo de texto (spec §6.0-2): `JSON.parse` roda no cliente, antes de qualquer
 * requisição. Erro de parse nunca escapa como `SyntaxError` cru — é embrulhado numa mensagem
 * pt-BR utilizável pelo chamador (tarefa 2.4 mostra o texto ao usuário).
 */
export async function lerJsonDeArquivo(arquivo: File): Promise<unknown> {
  const texto = await arquivo.text();
  try {
    return JSON.parse(texto);
  } catch {
    throw new Error("O arquivo selecionado não contém JSON válido.");
  }
}
