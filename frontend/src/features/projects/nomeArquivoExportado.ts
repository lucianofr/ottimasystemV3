/**
 * Nome de fallback do download de export (spec §3.1-2, §6.0-3; tarefa 2.3 do plano F6b).
 *
 * `baixarArquivo` sempre prefere o `Content-Disposition` da resposta quando presente — a rota
 * `GET /api/projects/{id}/export` manda esse header em todo 200 (`projects.py:212-214`), então
 * este `nomePadrao` só é usado no caso raro de o header faltar ou ser inutilizável. Para não
 * degradar para um nome genérico nesse caso, a função espelha `_slug` do backend
 * (`services/api/src/ottima_api/routers/projects.py:47-55`) byte a byte: minúsculas,
 * sequências fora de `[a-z0-9]` colapsadas num único hífen, hífens das pontas removidos, nome
 * que reduz a vazio cai em `"projeto"`. Puro: sem I/O.
 */
export function nomeArquivoExportado(nomeProjeto: string): string {
  const slug = nomeProjeto
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return `${slug || "projeto"}.ottima.json`;
}
