import { useState, type FormEvent } from "react";

import { Button } from "../../components/ui/button";
import { Card } from "../../components/ui/card";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select } from "../../components/ui/select";
import {
  ApiError,
  type ConnectionCreate,
  type ConnectionOut,
  type ConnectionUpdate,
} from "../../lib/api";
import { useCreateConnection, useUpdateConnection } from "./useConnections";

type SecurityPolicy = ConnectionOut["security_policy"];
type SecurityMode = ConnectionOut["security_mode"];
type AuthMode = ConnectionOut["auth_mode"];

interface Valores {
  name: string;
  endpoint: string;
  security_policy: SecurityPolicy;
  security_mode: SecurityMode;
  auth_mode: AuthMode;
  auth_username: string;
  auth_password: string;
  watchdog_read_node_id: string;
  watchdog_write_node_id: string;
  watchdog_period_ms: string;
}

const PERIODO_PADRAO_MS = 1500; // ADR-009

function valoresIniciais(conexao: ConnectionOut | null): Valores {
  return {
    name: conexao?.name ?? "",
    endpoint: conexao?.endpoint ?? "",
    security_policy: conexao?.security_policy ?? "none",
    security_mode: conexao?.security_mode ?? "none",
    auth_mode: conexao?.auth_mode ?? "anonymous",
    auth_username: conexao?.auth_username ?? "",
    auth_password: "",
    watchdog_read_node_id: conexao?.watchdog_read_node_id ?? "",
    watchdog_write_node_id: conexao?.watchdog_write_node_id ?? "",
    watchdog_period_ms: String(conexao?.watchdog_period_ms ?? PERIODO_PADRAO_MS),
  };
}

/** Espelho das regras de `schemas/connections.py` e das `CheckConstraint` de
 *  `models/connection.py` (F1). Conveniência: o 422/409 do backend continua sendo exibido. */
function validar(v: Valores, senhaJaDefinida: boolean): string[] {
  const erros: string[] = [];
  if (!v.name.trim()) erros.push("Nome é obrigatório");
  if (!v.endpoint.trim()) erros.push("Endpoint é obrigatório");
  if ((v.security_policy === "none") !== (v.security_mode === "none")) {
    erros.push("SecurityPolicy None exige modo None; Basic256Sha256 exige Sign ou SignAndEncrypt");
  }
  if (v.auth_mode === "user_password") {
    const temSenha = v.auth_password.length > 0 || senhaJaDefinida;
    if (!v.auth_username.trim() || !temSenha) {
      erros.push("Autenticação usuário/senha exige usuário e senha");
    }
  }
  const leitura = v.watchdog_read_node_id.trim();
  const escrita = v.watchdog_write_node_id.trim();
  if (Boolean(leitura) !== Boolean(escrita)) {
    erros.push("Watchdog exige os dois node_ids (leitura e escrita) ou nenhum");
  }
  const periodo = Number(v.watchdog_period_ms);
  if (!Number.isInteger(periodo) || periodo < 500 || periodo > 5000) {
    erros.push("Período do watchdog deve ser um número inteiro entre 500 e 5000 ms");
  }
  return erros;
}

/** Campos comuns a criação e atualização; a senha entra separada (write-only, spec §5.4). */
function corpoComum(v: Valores) {
  return {
    name: v.name.trim(),
    endpoint: v.endpoint.trim(),
    security_policy: v.security_policy,
    security_mode: v.security_mode,
    auth_mode: v.auth_mode,
    auth_username: v.auth_mode === "user_password" ? v.auth_username.trim() : null,
    watchdog_read_node_id: v.watchdog_read_node_id.trim() || null,
    watchdog_write_node_id: v.watchdog_write_node_id.trim() || null,
    watchdog_period_ms: Number(v.watchdog_period_ms),
  };
}

interface Props {
  /** `null` = criar; caso contrário, edita a conexão. */
  conexao: ConnectionOut | null;
  projectId: number;
  onClose: () => void;
}

export function ConnectionForm({ conexao, projectId, onClose }: Props) {
  const [v, setV] = useState<Valores>(() => valoresIniciais(conexao));
  const [erros, setErros] = useState<string[]>([]);
  const criar = useCreateConnection();
  const atualizar = useUpdateConnection();
  const editando = conexao !== null;
  const enviando = criar.isPending || atualizar.isPending;

  function mudar<K extends keyof Valores>(campo: K, valor: Valores[K]): void {
    setV((atual) => ({ ...atual, [campo]: valor }));
  }

  /** Policy None força modo None (`ck_opc_connections_policy_mode`); o inverso não é
   *  automático de propósito — quem escolhe Basic256Sha256 precisa escolher o modo. */
  function mudarPolicy(policy: SecurityPolicy): void {
    setV((atual) => ({
      ...atual,
      security_policy: policy,
      security_mode: policy === "none" ? "none" : atual.security_mode,
    }));
  }

  async function onSubmit(e: FormEvent): Promise<void> {
    e.preventDefault();
    const locais = validar(v, editando && conexao.has_password);
    setErros(locais);
    if (locais.length > 0) return;
    const senha = v.auth_password;
    try {
      if (editando) {
        // senha ausente do corpo = manter a atual (router: `exclude_unset`)
        const corpo: ConnectionUpdate = senha
          ? { ...corpoComum(v), auth_password: senha }
          : corpoComum(v);
        await atualizar.mutateAsync({ id: conexao.id, body: corpo });
      } else {
        const corpo: ConnectionCreate = senha
          ? { ...corpoComum(v), project_id: projectId, auth_password: senha }
          : { ...corpoComum(v), project_id: projectId };
        await criar.mutateAsync(corpo);
      }
      onClose();
    } catch (err) {
      setErros([err instanceof ApiError ? err.message : "Erro de comunicação com o servidor"]);
    }
  }

  return (
    <Card className="p-6">
      <h2 className="plaqueta text-xs text-fg-muted">
        {editando ? "Editar conexão" : "Nova conexão"}
      </h2>
      <form
        data-testid="conn-form"
        onSubmit={(e) => void onSubmit(e)}
        className="mt-4 space-y-6"
        noValidate
      >
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-1.5">
            <Label htmlFor="conn-name">Nome</Label>
            <Input
              id="conn-name"
              data-testid="conn-name"
              value={v.name}
              onChange={(e) => mudar("name", e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="conn-endpoint">Endpoint</Label>
            <Input
              id="conn-endpoint"
              data-testid="conn-endpoint"
              className="process-value"
              placeholder="opc.tcp://servidor:4840"
              value={v.endpoint}
              onChange={(e) => mudar("endpoint", e.target.value)}
            />
          </div>
        </div>

        <fieldset className="grid grid-cols-2 gap-4 border-t border-hairline pt-4">
          <legend className="plaqueta text-xs text-fg-muted">Segurança</legend>
          <div className="space-y-1.5">
            <Label htmlFor="conn-policy">Política</Label>
            <Select
              id="conn-policy"
              data-testid="conn-policy"
              value={v.security_policy}
              onChange={(e) => mudarPolicy(e.target.value as SecurityPolicy)}
            >
              <option value="none">Nenhuma</option>
              <option value="basic256sha256">Basic256Sha256</option>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="conn-mode">Modo</Label>
            <Select
              id="conn-mode"
              data-testid="conn-mode"
              disabled={v.security_policy === "none"}
              value={v.security_mode}
              onChange={(e) => mudar("security_mode", e.target.value as SecurityMode)}
            >
              <option value="none">Nenhum</option>
              <option value="sign">Assinar</option>
              <option value="sign_and_encrypt">Assinar e cifrar</option>
            </Select>
          </div>
        </fieldset>

        <fieldset className="grid grid-cols-2 gap-4 border-t border-hairline pt-4">
          <legend className="plaqueta text-xs text-fg-muted">Autenticação</legend>
          <div className="space-y-1.5">
            <Label htmlFor="conn-auth-mode">Modo</Label>
            <Select
              id="conn-auth-mode"
              data-testid="conn-auth-mode"
              value={v.auth_mode}
              onChange={(e) => mudar("auth_mode", e.target.value as AuthMode)}
            >
              <option value="anonymous">Anônima</option>
              <option value="user_password">Usuário/senha</option>
              <option value="certificate">Certificado</option>
            </Select>
          </div>
          {v.auth_mode === "user_password" && (
            <>
              <div className="space-y-1.5">
                <Label htmlFor="conn-username">Usuário</Label>
                <Input
                  id="conn-username"
                  data-testid="conn-username"
                  autoComplete="off"
                  value={v.auth_username}
                  onChange={(e) => mudar("auth_username", e.target.value)}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="conn-password">Senha</Label>
                <Input
                  id="conn-password"
                  data-testid="conn-password"
                  type="password"
                  autoComplete="new-password"
                  value={v.auth_password}
                  onChange={(e) => mudar("auth_password", e.target.value)}
                />
                {editando && (
                  <p className="text-xs text-fg-muted">
                    Deixe em branco para manter a senha atual.
                  </p>
                )}
              </div>
            </>
          )}
          {v.auth_mode === "certificate" && (
            <p className="self-end text-xs text-fg-muted">
              A identidade por certificado reusa o par do certificado de aplicação do
              OttimaSystem; nada a informar aqui.
            </p>
          )}
        </fieldset>

        <fieldset className="space-y-4 border-t border-hairline pt-4">
          <legend className="plaqueta text-xs text-fg-muted">Watchdog</legend>
          <div className="grid grid-cols-3 gap-4">
            <div className="space-y-1.5">
              <Label htmlFor="conn-wd-read">Node de leitura</Label>
              <Input
                id="conn-wd-read"
                data-testid="conn-wd-read"
                className="process-value"
                placeholder="ns=2;s=..."
                value={v.watchdog_read_node_id}
                onChange={(e) => mudar("watchdog_read_node_id", e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="conn-wd-write">Node de escrita</Label>
              <Input
                id="conn-wd-write"
                data-testid="conn-wd-write"
                className="process-value"
                placeholder="ns=2;s=..."
                value={v.watchdog_write_node_id}
                onChange={(e) => mudar("watchdog_write_node_id", e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="conn-wd-period">Período (ms)</Label>
              <Input
                id="conn-wd-period"
                data-testid="conn-wd-period"
                className="process-value"
                type="number"
                min={500}
                max={5000}
                step={100}
                value={v.watchdog_period_ms}
                onChange={(e) => mudar("watchdog_period_ms", e.target.value)}
              />
            </div>
          </div>
          {/* Aviso fixo, sempre visível (spec F2 §3.5) */}
          <p data-testid="conn-wd-aviso" className="text-xs text-warn">
            Sem watchdog, a conexão fica somente leitura: nenhuma escrita será executada.
          </p>
        </fieldset>

        {erros.length > 0 && (
          // Regra do Canal Redundante: cor + ícone + texto (DESIGN.md §Colors)
          <ul role="alert" data-testid="conn-form-error" className="space-y-1 text-sm text-alarm">
            {erros.map((erro) => (
              <li key={erro} className="flex items-center gap-2">
                <svg
                  aria-hidden="true"
                  width="14"
                  height="14"
                  viewBox="0 0 16 16"
                  fill="currentColor"
                  className="shrink-0"
                >
                  <path d="M8 1 15 14H1L8 1Zm-.75 5v4h1.5V6h-1.5Zm0 5.5V13h1.5v-1.5h-1.5Z" />
                </svg>
                {erro}
              </li>
            ))}
          </ul>
        )}

        <div className="flex gap-3">
          <Button type="submit" data-testid="conn-submit" disabled={enviando}>
            {enviando ? "Salvando…" : "Salvar"}
          </Button>
          <Button type="button" variant="outline" data-testid="conn-cancel" onClick={onClose}>
            Cancelar
          </Button>
        </div>
      </form>
    </Card>
  );
}
