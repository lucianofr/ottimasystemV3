"""Serviço compartilhado de variável historiada (RF-308, ADR-041).

Quatro operações reusadas pelos caminhos que tocam a cascata (`POST`/`DELETE` de
`routers/historized_vars.py`, `PUT`/`DELETE`/`deploy`/`stop` de `routers/flows.py`): nome
derivado (D6), remoção pela linha de `tags` (D5), poda por grafo (D7 reaplicado no save) e
o publisher de `flow.commands` — promovido de `routers/flows.py::_publicar_comando`
(privado do módulo) porque o cadastro/exclusão de porta historiada também dispara `reload`
em flow rodando e não podia importar um símbolo privado de outro router.
"""

import logging
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

from redis.asyncio import Redis
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ottima_core.bus import CHANNEL_FLOW_COMMANDS, FlowCommand
from ottima_core.flowgraph import FlowGraph, NodePorts, graph_ports
from ottima_core.models import HistorizedVar, Tag, User

logger = logging.getLogger(__name__)


def derivar_nomes(flow_name: str, label: str, block_id: str, port: str) -> tuple[str, str]:
    """Nome congela no cadastro (ADR-041 D6): preferido usa o label do bloco (rótulo do
    editor) — ou o `block_id` bruto, sem label —, alternativo é sempre `block_id` bruto,
    tentado só se o preferido colidir com `uq_tags_project_name`. Renomear o flow ou o label
    depois NÃO renomeia a variável: isso quebraria a rastreabilidade do histórico e do CSV.
    """
    preferido = f"{flow_name}.{label or block_id}.{port}"
    alternativo = f"{flow_name}.{block_id}.{port}"
    return preferido, alternativo


def porta_tem_aresta_de_entrada(grafo: FlowGraph, block_id: str, port: str) -> bool:
    """Só importa para porta de ENTRADA (D7): uma saída nunca precisa de aresta para valer."""
    return any(edge.target == block_id and edge.target_handle == port for edge in grafo.edges)


MSG_BLOCO_INEXISTENTE = "Bloco não existe no grafo salvo do flow"
MSG_PORTA_INEXISTENTE = "Porta não existe neste bloco"
MSG_ENTRADA_SEM_ARESTA = (
    "Porta de entrada sem aresta conectada nunca produz valor e não pode ser historiada"
)


def problema_de_porta(
    grafo: FlowGraph,
    block_id: str,
    port: str,
    portas: Mapping[str, NodePorts] | None = None,
) -> str | None:
    """Regra ÚNICA de "esta porta pode ser historiada" (ADR-041 D7); `None` = pode.

    Três consumidores com três formas de reagir ao mesmo veredito: o cadastro interativo
    levanta 422, a poda do save apaga o registro, e o import de projeto acumula o problema
    na lista de recusa do bundle. Uma réplica da regra por consumidor divergiria na primeira
    porta dinâmica nova (`mpc`/`script`/`fuzzy`) — `graph_ports` é a única fonte de verdade.

    `portas` é o `graph_ports(grafo)` já calculado: quem chama em laço (poda, import) passa
    o mapa uma vez, senão cada porta pagaria um `MpcConfig.model_validate` por nó `mpc` do
    grafo inteiro de novo.
    """
    node_ports = (graph_ports(grafo) if portas is None else portas).get(block_id)
    if node_ports is None:
        return MSG_BLOCO_INEXISTENTE
    if port not in (*node_ports.inputs, *node_ports.outputs):
        return MSG_PORTA_INEXISTENTE
    if port in node_ports.inputs and not porta_tem_aresta_de_entrada(grafo, block_id, port):
        return MSG_ENTRADA_SEM_ARESTA
    return None


async def publicar_comando(redis_client: Redis, user: User, flow_id: int, cmd: str) -> None:
    """Publica em `flow.commands` depois do commit; falha de publicação não derruba a rota
    (mesmo padrão de `routers/flows.py`, agora compartilhado com `routers/historized_vars.py`).

    Comando é intenção (spec §5.1) e não gera evento aqui: quem audita o efeito é o runtime,
    ao materializá-lo (§2.2-7). Comando perdido = nada aconteceu: o `desired_state`/registro
    já gravado fica divergente do estado publicado até alguém recomandar — nem o watermark
    deploya sozinho. O `reload` é a exceção coberta: o watermark de 10 s pega o `updated_at`
    novo do flow rodando (§2.2-9).
    """
    comando = FlowCommand(
        flow_id=flow_id, cmd=cmd, args={}, user=f"user:{user.id}", ts=datetime.now(UTC)
    )
    try:
        await redis_client.publish(CHANNEL_FLOW_COMMANDS, comando.model_dump_json())
    except Exception:
        logger.exception("Falha ao publicar comando '%s' do flow %s", cmd, flow_id)


async def remover_variaveis_historiadas(db: AsyncSession, tag_ids: Sequence[int]) -> None:
    """Apaga as linhas de `tags` — NUNCA `historized_vars` isolada (ADR-041 D5).

    A cascata só corre de `tags.id` para `historized_vars.tag_id` (`ondelete="CASCADE"`);
    apagar só o registro de `historized_vars` deixaria a tag órfã, eterna no seletor do
    TREND e fatal no export do projeto. No-op com sequência vazia: nem toda poda ou exclusão
    de flow tem variável historiada para remover.
    """
    if not tag_ids:
        return
    await db.execute(delete(Tag).where(Tag.id.in_(tag_ids)))


async def podar_variaveis_historiadas(
    db: AsyncSession, flow_id: int, grafo: FlowGraph
) -> list[str]:
    """Remove, do grafo recém-salvo, todo registro cujo bloco sumiu, cuja porta deixou de
    existir, ou cuja porta de ENTRADA perdeu a aresta (D7 reaplicado no save: um save que
    desconecta uma entrada historiada não pode deixá-la COLD para sempre).

    Devolve os NOMES removidos (não os ids) — o chamador usa a lista no evento de
    auditoria do save do flow (`historized_var_pruned`), a única pista que sobra para quem
    perdeu a série.
    """
    portas = graph_ports(grafo)  # uma vez para o flow, não uma por registro
    stmt = (
        select(HistorizedVar, Tag.name)
        .join(Tag, Tag.id == HistorizedVar.tag_id)
        .where(HistorizedVar.flow_id == flow_id)
    )
    mortos: list[int] = []
    nomes: list[str] = []
    for hv, name in (await db.execute(stmt)).all():
        if problema_de_porta(grafo, hv.block_id, hv.port, portas) is not None:
            mortos.append(hv.tag_id)
            nomes.append(name)
    await remover_variaveis_historiadas(db, mortos)
    return nomes
