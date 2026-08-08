import { useRef, useState, type ChangeEvent } from "react";

import { Button } from "../../components/ui/button";
import { Card } from "../../components/ui/card";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { ApiError } from "../../lib/api";
import { lerJsonDeArquivo } from "../../lib/arquivos";
import {
  EFEITO_PENDENCIA,
  ROTULO_PENDENCIA,
  pendenciasDoResumo,
  type Pendencia,
} from "../connections/pendencias";
import {
  comoObjeto,
  contarBundle,
  extrairBlocosScript,
  nomeInicialDoBundle,
  particionarDetalhe,
  type BlocoScriptImport,
  type ContagemBundle,
} from "./importar";
import { useImportProject, type ProjectImportOut } from "./useProjects";

const CONTAGEM_VAZIA: ContagemBundle = { connections: 0, tags: 0, flows: 0 };

/** Ordem fixa de exibição das pendências no resumo — igual à de `pendencias.ts`, para a
 *  lista não mudar de forma entre renders. */
const ORDEM_PENDENCIAS: readonly Pendencia[] = [
  "senha",
  "certificado_servidor",
  "certificado_aplicacao",
];

type PendingSecretOut = ProjectImportOut["pending_secrets"][number];

/** Agrupa `pending_secrets` por tipo de pendência (brief da tarefa 2.4): cada tipo lista as
 *  conexões que precisam dele, em vez de uma linha por conexão repetindo os três rótulos.
 *  Reusa `pendenciasDoResumo` — não reimplementa os predicados (tarefa 1.4). */
function agruparPorTipo(pendingSecrets: readonly PendingSecretOut[]): Record<Pendencia, string[]> {
  const porTipo: Record<Pendencia, string[]> = {
    senha: [],
    certificado_servidor: [],
    certificado_aplicacao: [],
  };
  for (const p of pendingSecrets) {
    for (const pendencia of pendenciasDoResumo(p)) {
      porTipo[pendencia].push(p.connection_name);
    }
  }
  return porTipo;
}

/** Ícone neutro de pendência de configuração (não é severidade de processo: sem âmbar, sem
 *  vermelho — UX-01). Herda a cor do texto (`currentColor`), sempre com o rótulo ao lado
 *  (Regra do Canal Redundante nunca depende só do ícone). */
function IconePendencia() {
  return (
    <svg aria-hidden="true" width="10" height="10" viewBox="0 0 16 16" className="shrink-0">
      <circle cx="8" cy="8" r="6.5" fill="none" stroke="currentColor" strokeWidth="1.3" />
      <circle cx="8" cy="8" r="1" fill="currentColor" />
      <rect x="7.35" y="4" width="1.3" height="4.5" fill="currentColor" />
    </svg>
  );
}

interface Props {
  onFechar: () => void;
}

/**
 * Import de arquivo de projeto em três passos (spec §6.1-6, decisão A-6, F6R-03):
 *
 * 1. **Escolher arquivo** — leitura e `JSON.parse` no cliente (`lerJsonDeArquivo`), sem
 *    nenhuma requisição ao servidor. JSON inválido para aqui, com erro pt-BR na tela.
 * 2. **Prévia** — contagem de conexões/tags/flows, nome do projeto em campo editável
 *    (default: `bundle.project.name`) e a lista dos blocos Script com o código visível.
 *    Sem bloco Script, diz isso explicitamente. Havendo blocos Script, uma confirmação
 *    explícita de que o código vai executar no servidor é obrigatória para avançar — o
 *    admin nunca importa às cegas (F6R-03, o arquivo pode ter vindo de outra organização,
 *    ADR-012, e o código deixa de ter autor confiável, premissa do ADR-018).
 * 3. **Confirmação explícita** — recapitula o que será importado; o envio só acontece no
 *    clique do botão desta tela, nunca implícito ao avançar do passo 2. Sucesso mostra o
 *    resumo com `pending_secrets`; recusa parte o `detail` agregado (`particionarDetalhe`)
 *    e lista os problemas um por linha, sem reset — o admin corrige o nome (409) ou tenta
 *    de novo (413) sem reescolher o arquivo.
 */
export function ImportarProjeto({ onFechar }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const importar = useImportProject();

  const [passo, setPasso] = useState<"escolher" | "previa" | "confirmar" | "resumo">("escolher");
  const [bundle, setBundle] = useState<Record<string, unknown> | null>(null);
  const [nome, setNome] = useState("");
  const [contagem, setContagem] = useState<ContagemBundle>(CONTAGEM_VAZIA);
  const [scripts, setScripts] = useState<BlocoScriptImport[]>([]);
  const [cienteScripts, setCienteScripts] = useState(false);
  const [erroArquivo, setErroArquivo] = useState<string | null>(null);
  const [erroEnvio, setErroEnvio] = useState<string[] | null>(null);
  const [resumo, setResumo] = useState<ProjectImportOut | null>(null);

  async function onArquivoEscolhido(e: ChangeEvent<HTMLInputElement>): Promise<void> {
    const arquivo = e.target.files?.[0] ?? null;
    e.target.value = ""; // permite escolher o mesmo arquivo de novo após corrigir um erro
    if (!arquivo) return;
    setErroArquivo(null);
    try {
      const lido = await lerJsonDeArquivo(arquivo);
      const obj = comoObjeto(lido);
      if (!obj) {
        setErroArquivo("O arquivo selecionado não descreve um projeto (esperado um objeto JSON).");
        return;
      }
      setBundle(obj);
      setNome(nomeInicialDoBundle(obj));
      setContagem(contarBundle(obj));
      setScripts(extrairBlocosScript(obj));
      setCienteScripts(false);
      setErroEnvio(null);
      setResumo(null);
      setPasso("previa");
    } catch (err) {
      setErroArquivo(err instanceof Error ? err.message : "Falha ao ler o arquivo selecionado");
    }
  }

  async function confirmarImportacao(): Promise<void> {
    if (!bundle) return;
    setErroEnvio(null);
    try {
      const resultado = await importar.mutateAsync({ name: nome.trim() || null, bundle });
      setResumo(resultado);
      setPasso("resumo");
    } catch (err) {
      const mensagem = err instanceof ApiError ? err.message : "Erro de comunicação com o servidor";
      setErroEnvio(particionarDetalhe(mensagem));
    }
  }

  function fechar(): void {
    setPasso("escolher");
    setBundle(null);
    setNome("");
    setContagem(CONTAGEM_VAZIA);
    setScripts([]);
    setCienteScripts(false);
    setErroArquivo(null);
    setErroEnvio(null);
    setResumo(null);
    onFechar();
  }

  const semScripts = scripts.length === 0;
  const podeAvancar = semScripts || cienteScripts;

  return (
    <Card data-testid="import-painel" className="space-y-4 p-6">
      {passo === "escolher" && (
        <div className="space-y-3">
          <p className="plaqueta text-xs text-fg-muted">Passo 1 de 3 — Escolher arquivo</p>
          <p className="text-sm text-fg-muted">
            Selecione um arquivo de projeto (.json) exportado de outra instalação.
          </p>
          {erroArquivo && (
            <p role="alert" data-testid="import-arquivo-error" className="text-xs text-alarm">
              {erroArquivo}
            </p>
          )}
          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              data-testid="import-selecionar"
              onClick={() => inputRef.current?.click()}
            >
              Selecionar arquivo de projeto
            </Button>
            <Button type="button" variant="outline" size="sm" onClick={fechar}>
              Cancelar
            </Button>
          </div>
          <input
            ref={inputRef}
            type="file"
            accept="application/json,.json"
            data-testid="import-arquivo-input"
            className="sr-only"
            onChange={(e) => void onArquivoEscolhido(e)}
          />
        </div>
      )}

      {passo === "previa" && (
        <div className="space-y-4" data-testid="import-previa">
          <p className="plaqueta text-xs text-fg-muted">Passo 2 de 3 — Prévia</p>

          <div className="flex flex-wrap gap-6" data-testid="import-contagens">
            <div data-testid="import-contagem-conexoes">
              <p className="plaqueta text-xs text-fg-muted">Conexões</p>
              <p className="process-value text-lg text-fg">{contagem.connections}</p>
            </div>
            <div data-testid="import-contagem-tags">
              <p className="plaqueta text-xs text-fg-muted">Tags</p>
              <p className="process-value text-lg text-fg">{contagem.tags}</p>
            </div>
            <div data-testid="import-contagem-flows">
              <p className="plaqueta text-xs text-fg-muted">Flows</p>
              <p className="process-value text-lg text-fg">{contagem.flows}</p>
            </div>
          </div>

          <div className="space-y-1">
            <Label htmlFor="import-nome-campo">Nome do projeto</Label>
            <Input
              id="import-nome-campo"
              data-testid="import-nome"
              value={nome}
              onChange={(e) => setNome(e.target.value)}
            />
          </div>

          <div className="space-y-2">
            <Label>Blocos Script</Label>
            {semScripts ? (
              <p data-testid="import-scripts-vazio" className="text-sm text-fg-muted">
                Nenhum bloco Script neste arquivo.
              </p>
            ) : (
              <>
                <ul data-testid="import-scripts" className="space-y-2">
                  {scripts.map((bloco, i) => (
                    <li
                      key={i}
                      data-testid="import-script-item"
                      className="rounded-panel border border-hairline bg-well p-2"
                    >
                      <p className="plaqueta text-xs text-fg-muted">
                        {bloco.flow} · {bloco.label}
                      </p>
                      <pre
                        data-testid="import-script-code"
                        className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap font-mono text-xs text-fg"
                      >
                        {bloco.code}
                      </pre>
                    </li>
                  ))}
                </ul>
                <label className="flex items-start gap-2 text-xs text-fg-muted">
                  <input
                    type="checkbox"
                    data-testid="import-confirmar-scripts"
                    checked={cienteScripts}
                    onChange={(e) => setCienteScripts(e.target.checked)}
                    className="mt-0.5"
                  />
                  Revisei o código acima e autorizo sua execução no servidor.
                </label>
              </>
            )}
          </div>

          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" size="sm" onClick={fechar}>
              Cancelar
            </Button>
            <Button
              type="button"
              size="sm"
              data-testid="import-avancar"
              disabled={!podeAvancar}
              onClick={() => setPasso("confirmar")}
            >
              Avançar
            </Button>
          </div>
        </div>
      )}

      {passo === "confirmar" && (
        <div className="space-y-4">
          <p className="plaqueta text-xs text-fg-muted">Passo 3 de 3 — Confirmação</p>
          <p className="text-sm text-fg">
            Importar &quot;{nome.trim() || "(sem nome)"}&quot; com {contagem.connections} conexões,{" "}
            {contagem.tags} tags e {contagem.flows} flows
            {semScripts ? "" : `, incluindo ${String(scripts.length)} bloco(s) Script`}.
          </p>
          {erroEnvio && (
            <ul role="alert" data-testid="import-error" className="space-y-1 text-xs text-alarm">
              {erroEnvio.map((linha, i) => (
                <li key={i}>{linha}</li>
              ))}
            </ul>
          )}
          <div className="flex justify-end gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              data-testid="import-voltar"
              onClick={() => {
                setErroEnvio(null);
                setPasso("previa");
              }}
            >
              Voltar
            </Button>
            <Button
              type="button"
              size="sm"
              data-testid="import-confirmar"
              disabled={importar.isPending}
              onClick={() => void confirmarImportacao()}
            >
              Confirmar e importar
            </Button>
          </div>
        </div>
      )}

      {passo === "resumo" && resumo && (
        <div className="space-y-4" data-testid="import-resumo">
          <p className="text-sm text-fg">Projeto &quot;{resumo.project.name}&quot; importado com sucesso.</p>
          <ul className="space-y-1.5" data-testid="import-pendencias">
            {resumo.pending_secrets.length === 0 && (
              <li className="text-xs text-fg-muted">Nenhuma pendência de segredo.</li>
            )}
            {(() => {
              const porTipo = agruparPorTipo(resumo.pending_secrets);
              return ORDEM_PENDENCIAS.map((pendencia) => {
                const conexoes = porTipo[pendencia];
                if (conexoes.length === 0) return null;
                return (
                  <li
                    key={pendencia}
                    data-testid="import-pendencia-row"
                    title={EFEITO_PENDENCIA[pendencia]}
                    className="flex items-center gap-1.5 text-xs text-fg-muted"
                  >
                    <IconePendencia />
                    <span className="plaqueta">{ROTULO_PENDENCIA[pendencia]}</span>
                    <span className="process-value">{conexoes.join(", ")}</span>
                  </li>
                );
              });
            })()}
          </ul>
          <div className="flex items-center justify-between">
            <a href="/engenharia/conexoes" data-testid="import-resumo-link" className="text-xs text-accent">
              Ir para Conexões
            </a>
            <Button type="button" size="sm" data-testid="import-fechar" onClick={fechar}>
              Fechar
            </Button>
          </div>
        </div>
      )}
    </Card>
  );
}
