"""fuzzy_loop v2 multicanal: `loop_setpoints.channel` + migração dos grafos SISO gravados

Esquema: `channel` entra na PK de `loop_setpoints` (um SP/MAN_OUT por canal); linhas SISO
existentes ficam no canal 0 via server_default.

Dados sobre `flows.graph_json` (mesmo padrão da 0009): todo nó `fuzzy_loop` SISO passa a ser
um bloco de 1 canal — arestas nas portas `in`/`out` viram `pv_1`/`out_1`, e `permitted`/
`normal` perdem os modos remotos (o v2 não tem cascata; `extra="forbid"` + o validador de
modos rejeitariam o config). `n_loops` não é escrito: o default do Pydantic (1) cobre.

Arestas nas portas que deixaram de existir (`cas_in`, `rcas_in`, `rout_in`, `bkcal_in`,
`bias_in`, `trk_in_d`, `lo_in_d`, `bkcal_out`) NÃO são apagadas de propósito: `lo_in_d` e
`trk_in_d` são intertravamento/tracking, e sumir com eles em silêncio seria pior que o flow
ser rejeitado na carga (fica parado, erro explícito de handle — lado seguro).
"""

import json
from typing import Any

import sqlalchemy as sa
from alembic import op

revision = "0016_loop_setpoints_channel"
down_revision = "0015_loop_tables"
branch_labels = None
depends_on = None

_MODOS_V2 = ("oos", "man", "auto")
# (porta SISO, porta do canal 1) — lado da aresta: source para saídas, target para entradas.
_SAIDAS = {"out": "out_1"}
_ENTRADAS = {"in": "pv_1"}


_FLOWS = sa.table("flows", sa.column("id", sa.BigInteger), sa.column("graph_json", sa.JSON))


def _grafos(conn: sa.engine.Connection) -> list[tuple[int, dict[str, Any]]]:
    rows = conn.execute(sa.select(_FLOWS.c.id, _FLOWS.c.graph_json)).fetchall()
    return [(fid, json.loads(g) if isinstance(g, str) else g) for fid, g in rows]


def _renomear_portas(
    graph: dict[str, Any], ids: set[str], saidas: dict[str, str], entradas: dict[str, str]
) -> bool:
    sujo = False
    for edge in graph.get("edges", []):
        if edge.get("source") in ids and edge.get("sourceHandle") in saidas:
            edge["sourceHandle"] = saidas[edge["sourceHandle"]]
            sujo = True
        if edge.get("target") in ids and edge.get("targetHandle") in entradas:
            edge["targetHandle"] = entradas[edge["targetHandle"]]
            sujo = True
    return sujo


def _gravar(conn: sa.engine.Connection, flow_id: int, graph: dict[str, Any]) -> None:
    # Coluna é JSONB: passa o dict — string aqui gravaria um JSON-string, não o objeto.
    conn.execute(_FLOWS.update().where(_FLOWS.c.id == flow_id).values(graph_json=graph))


def _nos_fuzzy_loop(graph: dict[str, Any]) -> list[dict[str, Any]]:
    return [n for n in graph.get("nodes", []) if n.get("type") == "fuzzy_loop"]


def upgrade() -> None:
    op.add_column(
        "loop_setpoints",
        sa.Column("channel", sa.Integer, nullable=False, server_default="0"),
    )
    # A 0015 declarou a PK inline, sem naming_convention: o Postgres a nomeia `<tabela>_pkey`.
    op.drop_constraint("loop_setpoints_pkey", "loop_setpoints", type_="primary")
    op.create_primary_key(
        "loop_setpoints_pkey", "loop_setpoints", ["flow_id", "block_id", "channel"]
    )

    conn = op.get_bind()
    for flow_id, graph in _grafos(conn):
        nos = _nos_fuzzy_loop(graph)
        if not nos:
            continue
        sujo = False
        for node in nos:
            config = node.get("data")
            if not isinstance(config, dict):
                continue
            permitted = config.get("permitted")
            if isinstance(permitted, list):
                filtrado = [m for m in permitted if m in _MODOS_V2]
                if filtrado != permitted:
                    config["permitted"] = filtrado
                    sujo = True
            if "normal" in config and config["normal"] not in ("man", "auto"):
                config["normal"] = "auto"
                sujo = True
        ids = {n["id"] for n in nos if isinstance(n.get("id"), str)}
        sujo = _renomear_portas(graph, ids, _SAIDAS, _ENTRADAS) or sujo
        if sujo:
            _gravar(conn, flow_id, graph)


def downgrade() -> None:
    conn = op.get_bind()
    grafos = _grafos(conn)
    # Checa ANTES de mutar: bloco multicanal não tem representação SISO — abortar com
    # mensagem clara é melhor que um grafo meio convertido ou erro de chave duplicada na PK.
    multicanal = [
        f"flow {fid} / bloco {n.get('id')}"
        for fid, graph in grafos
        for n in _nos_fuzzy_loop(graph)
        if isinstance(n.get("data"), dict) and int(n["data"].get("n_loops", 1)) > 1
    ]
    if multicanal:
        raise RuntimeError(
            "downgrade da 0016 impossível: fuzzy_loop com n_loops > 1 em "
            + ", ".join(multicanal)
            + ". Reduza esses blocos para 1 canal antes de voltar a revisão."
        )
    for flow_id, graph in grafos:
        nos = _nos_fuzzy_loop(graph)
        if not nos:
            continue
        sujo = False
        for node in nos:
            if isinstance(node.get("data"), dict) and "n_loops" in node["data"]:
                del node["data"]["n_loops"]  # a 0015 tem extra="forbid" no config
                sujo = True
        ids = {n["id"] for n in nos if isinstance(n.get("id"), str)}
        inverso_saidas = {v: k for k, v in _SAIDAS.items()}
        inverso_entradas = {v: k for k, v in _ENTRADAS.items()}
        sujo = _renomear_portas(graph, ids, inverso_saidas, inverso_entradas) or sujo
        if sujo:
            _gravar(conn, flow_id, graph)

    # Sem blocos multicanal, linhas com channel > 0 são órfãs; sem apagá-las a PK
    # (flow_id, block_id) recriada abaixo colidiria com chave duplicada.
    op.execute("DELETE FROM loop_setpoints WHERE channel <> 0")
    op.drop_constraint("loop_setpoints_pkey", "loop_setpoints", type_="primary")
    op.drop_column("loop_setpoints", "channel")
    op.create_primary_key("loop_setpoints_pkey", "loop_setpoints", ["flow_id", "block_id"])
