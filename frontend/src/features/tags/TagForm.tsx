import { useState, type FormEvent } from "react";

import { Button } from "../../components/ui/button";
import { Card } from "../../components/ui/card";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select } from "../../components/ui/select";
import {
  ApiError,
  type ConnectionOut,
  type TagCreate,
  type TagOut,
  type TagUpdate,
} from "../../lib/api";
import {
  ROTULO_DIRECAO,
  ROTULO_TIPO,
  useCreateTag,
  useUpdateTag,
  type Direcao,
  type TipoDado,
} from "./useTags";

interface Valores {
  /** String porque vem do `<select>`; `""` = nenhuma conexão escolhida. */
  connection_id: string;
  name: string;
  node_id: string;
  direction: Direcao;
  data_type: TipoDado;
  eu: string;
  description: string;
}

interface Props {
  /** `null` = criar; caso contrário, edita a tag. */
  tag: TagOut | null;
  conexoes: ConnectionOut[];
  onClose: () => void;
}

export function TagForm({ tag, conexoes, onClose }: Props) {
  const [v, setV] = useState<Valores>(() => ({
    connection_id: String(tag?.connection_id ?? conexoes[0]?.id ?? ""),
    name: tag?.name ?? "",
    node_id: tag?.node_id ?? "",
    direction: tag?.direction ?? "r",
    data_type: tag?.data_type ?? "float",
    eu: tag?.eu ?? "",
    description: tag?.description ?? "",
  }));
  const [erros, setErros] = useState<string[]>([]);
  const criar = useCreateTag();
  const atualizar = useUpdateTag();
  const editando = tag !== null;
  const enviando = criar.isPending || atualizar.isPending;

  function mudar<K extends keyof Valores>(campo: K, valor: Valores[K]): void {
    setV((atual) => ({ ...atual, [campo]: valor }));
  }

  async function onSubmit(e: FormEvent): Promise<void> {
    e.preventDefault();
    // Espelho de `schemas/tags.py` (min_length=1); o 409/422 pt-BR do backend continua sendo
    // exibido. Direção e tipo saem de `<select>`, portanto já estão nos Literal permitidos.
    const locais: string[] = [];
    if (!v.connection_id) locais.push("Conexão é obrigatória");
    if (!v.name.trim()) locais.push("Nome é obrigatório");
    if (!v.node_id.trim()) locais.push("Node ID é obrigatório");
    setErros(locais);
    if (locais.length > 0) return;

    const comum = {
      name: v.name.trim(),
      node_id: v.node_id.trim(),
      direction: v.direction,
      data_type: v.data_type,
      eu: v.eu.trim(),
      description: v.description.trim(),
    };
    try {
      if (editando) {
        // `TagUpdate` não tem `connection_id`: mover a tag de conexão não é operação da API.
        const corpo: TagUpdate = comum;
        await atualizar.mutateAsync({ id: tag.id, body: corpo });
      } else {
        const corpo: TagCreate = { ...comum, connection_id: Number(v.connection_id) };
        await criar.mutateAsync(corpo);
      }
      onClose();
    } catch (err) {
      setErros([err instanceof ApiError ? err.message : "Erro de comunicação com o servidor"]);
    }
  }

  return (
    <Card className="p-6">
      <h2 className="plaqueta text-xs text-fg-muted">{editando ? "Editar tag" : "Nova tag"}</h2>
      <form
        data-testid="tag-form"
        onSubmit={(e) => void onSubmit(e)}
        className="mt-4 space-y-6"
        noValidate
      >
        <div className="grid grid-cols-3 gap-4">
          <div className="space-y-1.5">
            <Label htmlFor="tag-connection">Conexão</Label>
            <Select
              id="tag-connection"
              data-testid="tag-connection"
              disabled={editando}
              value={v.connection_id}
              onChange={(e) => mudar("connection_id", e.target.value)}
            >
              <option value="">Selecione</option>
              {conexoes.map((conexao) => (
                <option key={conexao.id} value={String(conexao.id)}>
                  {conexao.name}
                </option>
              ))}
            </Select>
            {editando && (
              <p className="text-xs text-fg-muted">
                A conexão de uma tag não muda; crie outra tag na conexão desejada.
              </p>
            )}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="tag-name">Nome</Label>
            <Input
              id="tag-name"
              data-testid="tag-name"
              value={v.name}
              onChange={(e) => mudar("name", e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="tag-node-id">Node ID</Label>
            <Input
              id="tag-node-id"
              data-testid="tag-node-id"
              className="process-value"
              placeholder="ns=2;s=..."
              value={v.node_id}
              onChange={(e) => mudar("node_id", e.target.value)}
            />
          </div>
        </div>

        <div className="grid grid-cols-3 gap-4">
          <div className="space-y-1.5">
            <Label htmlFor="tag-direction">Direção</Label>
            <Select
              id="tag-direction"
              data-testid="tag-direction"
              value={v.direction}
              onChange={(e) => mudar("direction", e.target.value as Direcao)}
            >
              <option value="r">{ROTULO_DIRECAO.r}</option>
              <option value="w">{ROTULO_DIRECAO.w}</option>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="tag-data-type">Tipo</Label>
            <Select
              id="tag-data-type"
              data-testid="tag-data-type"
              value={v.data_type}
              onChange={(e) => mudar("data_type", e.target.value as TipoDado)}
            >
              <option value="float">{ROTULO_TIPO.float}</option>
              <option value="int">{ROTULO_TIPO.int}</option>
              <option value="bool">{ROTULO_TIPO.bool}</option>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="tag-eu">EU</Label>
            <Input
              id="tag-eu"
              data-testid="tag-eu"
              placeholder="degC, %, m3/h"
              value={v.eu}
              onChange={(e) => mudar("eu", e.target.value)}
            />
          </div>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="tag-description">Descrição</Label>
          <Input
            id="tag-description"
            data-testid="tag-description"
            value={v.description}
            onChange={(e) => mudar("description", e.target.value)}
          />
        </div>

        {erros.length > 0 && (
          // Regra do Canal Redundante: cor + ícone + texto (DESIGN.md §Colors)
          <ul role="alert" data-testid="tag-form-error" className="space-y-1 text-sm text-alarm">
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
          <Button type="submit" data-testid="tag-submit" disabled={enviando}>
            {enviando ? "Salvando…" : "Salvar"}
          </Button>
          <Button type="button" variant="outline" data-testid="tag-cancel" onClick={onClose}>
            Cancelar
          </Button>
        </div>
      </form>
    </Card>
  );
}
