"""Histórico colunar com downsampling automático (RF-802): bruto até 2 h, CAgg 1 min acima."""

import re
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Row, column, select, table
from sqlalchemy.ext.asyncio import AsyncSession

from ottima_api.deps import get_db, require_operator
from ottima_api.messages import MSG_FLOW_NAO_ENCONTRADO
from ottima_core.bus import SstoRun
from ottima_core.flowgraph import parse_graph
from ottima_core.models import Flow, mpc_samples_table, samples_table
from ottima_core.schemas.flows import MAX_BIGINT
from ottima_core.schemas.history import (
    MAX_FUZZY_VARS,
    MAX_MPC_VARS,
    MAX_TAGS,
    MAX_WINDOW_DAYS,
    RAW_WINDOW_HOURS,
    FuzzyHistoryResponse,
    FuzzyHistorySeries,
    HistoryResponse,
    HistorySeries,
    MpcHistoryResponse,
    MpcHistorySeries,
    SstoLastOut,
)

# O CAgg é view materializada criada em SQL cru na migration 0002 e não tem handle no core:
# um Table() em qualquer MetaData o exporia ao autogenerate do Alembic. Aqui basta o
# construto leve `table()/column()`, que só sabe emitir SELECT e não participa de DDL.
samples_1m = table(
    "samples_1m",
    column("bucket"),
    column("tag_id"),
    column("avg_value"),
    column("min_value"),
    column("max_value"),
    column("worst_quality"),
)

# Mesmo raciocínio acima, para o CAgg da migration 0003 (spec F5 §2.2-3).
mpc_samples_1m = table(
    "mpc_samples_1m",
    column("bucket"),
    column("flow_id"),
    column("block_id"),
    column("var_id"),
    column("v"),
    column("v_min"),
    column("v_max"),
    column("sp"),
    column("auto"),
)

# Hypertable `ssto_runs` (migration 0004, ADR-027 §11) — mesmo construto leve: só SELECT.
ssto_runs = table(
    "ssto_runs",
    column("ts"),
    column("flow_id"),
    column("block_id"),
    column("run_id"),
    column("config_hash"),
    column("model_hash"),
    column("status"),
    column("solver"),
    column("solve_ms"),
    column("objective"),
    column("mv"),
    column("cv_ss"),
    column("bias"),
    column("dv"),
    column("costs"),
    column("delta_mv"),
    column("mv_target"),
    column("cv_target"),
    column("given_up"),
    column("active_constraints"),
    column("duals"),
)

# Hypertable/CAgg do bloco Fuzzy (migration 0010, ADR-030) — mesmo raciocínio dos construtos
# acima: handle leve, só para SELECT (o INSERT é do flow-runtime).
fuzzy_samples = table(
    "fuzzy_samples",
    column("ts"),
    column("flow_id"),
    column("block_id"),
    column("var_id"),
    column("v"),
)

fuzzy_samples_1m = table(
    "fuzzy_samples_1m",
    column("bucket"),
    column("flow_id"),
    column("block_id"),
    column("var_id"),
    column("v"),
    column("v_min"),
    column("v_max"),
)

FlowIdFilter = Annotated[int, Query(ge=1, le=MAX_BIGINT)]

MAX_TAG_ID = 2**63 - 1  # tag_id é BIGINT no banco
MAX_TAG_ID_DIGITOS = len(str(MAX_TAG_ID))  # 19

ERRO_VAZIO = "tag_ids não pode ser vazio"
ERRO_NAO_INTEIRO = "tag_ids deve conter apenas inteiros separados por vírgula"

ERRO_VAR_IDS_VAZIO = "var_ids não pode ser vazio"
ERRO_VAR_IDS_MALFORMADO = "var_ids deve conter valores não vazios separados por vírgula"

ERRO_FUZZY_VAR_IDS_VAZIO = "var_ids não pode ser vazio"
ERRO_FUZZY_VAR_IDS_MALFORMADO = (
    "var_ids deve conter portas IN1..IN8/OUT1..OUT8 separadas por vírgula"
)

_FUZZY_VAR_ID_RE = re.compile(r"^(IN|OUT)[1-8]$")

router = APIRouter()


def _as_utc(value: datetime | None) -> datetime | None:
    """ISO-8601 sem offset vale como UTC; a coluna é timestamptz e não aceita naive."""
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


def _e_tag_id(bruto: str) -> bool:
    """Nenhuma entrada de tag_ids pode virar 5xx: o que o banco não aceitaria é 422 aqui.

    Três guardas, nesta ordem, porque cada uma protege a seguinte:

    1. `isdecimal` e não `isdigit`: "²"/"①" são isdigit mas `int()` os rejeita (ValueError).
    2. Comprimento **antes** de converter: o CPython recusa str→int acima de
       `sys.get_int_max_str_digits()` (4300), também com ValueError. Como o BIGINT tem 19
       dígitos, cortar em 19 já é exigido pelo domínio e torna o limite do interpretador
       inalcançável por construção, em vez de depender de capturar a exceção.
    3. Faixa do BIGINT: acima do teto o `int()` do Python passa e o estouro só apareceria no
       bind do asyncpg. O piso é 1 porque a coluna é BIGSERIAL.
    """
    return bruto.isdecimal() and len(bruto) <= MAX_TAG_ID_DIGITOS and 1 <= int(bruto) <= MAX_TAG_ID


def _parse_tag_ids(bruto: str) -> list[int]:
    """Lista separada por vírgula, deduplicada preservando a ordem de entrada."""
    if not bruto.strip():
        raise HTTPException(status_code=422, detail=ERRO_VAZIO)
    # sem descartar itens vazios: "1," e "1,,2" são entrada malformada, não lista de um id
    itens = [p.strip() for p in bruto.split(",")]
    if any(not _e_tag_id(p) for p in itens):
        raise HTTPException(status_code=422, detail=ERRO_NAO_INTEIRO)
    ids = list(dict.fromkeys(int(p) for p in itens))
    if len(ids) > MAX_TAGS:
        raise HTTPException(status_code=422, detail=f"no máximo {MAX_TAGS} tags por consulta")
    return ids


def _parse_mpc_var_ids(bruto: str) -> list[str]:
    """Lista separada por vírgula, deduplicada preservando a ordem de entrada.

    `var_id` é texto livre (BIGINT não se aplica; sem faixa a validar) — a única forma
    inválida é estrutural: vazio ou item vazio entre vírgulas, mesma regra de `_parse_tag_ids`.
    `var_id` desconhecido no bloco não é erro aqui, vira série vazia (spec F5 §2.4).
    """
    if not bruto.strip():
        raise HTTPException(status_code=422, detail=ERRO_VAR_IDS_VAZIO)
    itens = [p.strip() for p in bruto.split(",")]
    if any(not item for item in itens):
        raise HTTPException(status_code=422, detail=ERRO_VAR_IDS_MALFORMADO)
    ids = list(dict.fromkeys(itens))
    if len(ids) > MAX_MPC_VARS:
        raise HTTPException(
            status_code=422, detail=f"no máximo {MAX_MPC_VARS} variáveis por consulta"
        )
    return ids


def _parse_fuzzy_var_ids(bruto: str) -> list[str]:
    """Lista separada por vírgula, deduplicada preservando a ordem de entrada — cada item tem
    de casar `^(IN|OUT)[1-8]$` (portas posicionais do bloco Fuzzy, ADR-029): fora do padrão é
    422, nunca 5xx. Mais estrito que `_parse_mpc_var_ids` porque a porta é finita e conhecida,
    ao contrário do var_id livre do MPC.
    """
    if not bruto.strip():
        raise HTTPException(status_code=422, detail=ERRO_FUZZY_VAR_IDS_VAZIO)
    itens = [p.strip() for p in bruto.split(",")]
    if any(not _FUZZY_VAR_ID_RE.fullmatch(item) for item in itens):
        raise HTTPException(status_code=422, detail=ERRO_FUZZY_VAR_IDS_MALFORMADO)
    ids = list(dict.fromkeys(itens))
    if len(ids) > MAX_FUZZY_VARS:
        raise HTTPException(
            status_code=422, detail=f"no máximo {MAX_FUZZY_VARS} variáveis por consulta"
        )
    return ids


@router.get(
    "",
    response_model=HistoryResponse,
    response_model_exclude_none=True,  # v_min/v_max somem do JSON no modo raw
    dependencies=[Depends(require_operator)],
)
async def get_history(
    tag_ids: str,
    start: datetime | None = None,
    end: datetime | None = None,
    db: AsyncSession = Depends(get_db),
) -> HistoryResponse:
    """Uma série por tag pedida, sempre; ordem temporal crescente (uPlot exige x monotônico)."""
    ids = _parse_tag_ids(tag_ids)
    end = _as_utc(end) or datetime.now(UTC)
    start = _as_utc(start) or end - timedelta(hours=1)
    if start >= end:
        raise HTTPException(status_code=422, detail="start deve ser anterior a end")
    if end - start > timedelta(days=MAX_WINDOW_DAYS):
        raise HTTPException(
            status_code=422, detail=f"janela não pode exceder {MAX_WINDOW_DAYS} dias"
        )

    downsample = end - start > timedelta(hours=RAW_WINDOW_HOURS)
    if downsample:
        tag_col, ts_col = samples_1m.c.tag_id, samples_1m.c.bucket
        colunas = [
            tag_col,
            ts_col.label("ts"),  # "t" colidiria com Row.t (acessor de tupla do SQLAlchemy)
            samples_1m.c.avg_value.label("v"),
            samples_1m.c.worst_quality.label("q"),
            samples_1m.c.min_value.label("v_min"),
            samples_1m.c.max_value.label("v_max"),
        ]
    else:
        tag_col, ts_col = samples_table.c.tag_id, samples_table.c.ts
        colunas = [
            tag_col,
            ts_col.label("ts"),
            samples_table.c.value.label("v"),
            samples_table.c.quality.label("q"),
        ]

    # Uma única query para todas as tags; o agrupamento por tag é feito em memória.
    stmt = (
        select(*colunas)
        .where(tag_col.in_(ids), ts_col >= start, ts_col <= end)
        .order_by(tag_col, ts_col)
    )
    por_tag: dict[int, list[Row[Any]]] = {tag_id: [] for tag_id in ids}
    for linha in (await db.execute(stmt)).all():
        por_tag[linha.tag_id].append(linha)

    return HistoryResponse(
        mode="1m" if downsample else "raw",
        start=start,
        end=end,
        series=[
            HistorySeries(
                tag_id=tag_id,
                t=[linha.ts for linha in linhas],
                v=[linha.v for linha in linhas],
                q=[linha.q for linha in linhas],
                v_min=[linha.v_min for linha in linhas] if downsample else None,
                v_max=[linha.v_max for linha in linhas] if downsample else None,
            )
            for tag_id, linhas in por_tag.items()
        ],
    )


@router.get(
    "/mpc",
    response_model=MpcHistoryResponse,
    response_model_exclude_none=True,  # v_min/v_max somem do JSON no modo raw
    dependencies=[Depends(require_operator)],
)
async def get_history_mpc(
    flow_id: FlowIdFilter,
    block_id: str,
    var_ids: str,
    start: datetime | None = None,
    end: datetime | None = None,
    db: AsyncSession = Depends(get_db),
) -> MpcHistoryResponse:
    """Histórico do bloco MPC (spec F5 §2.4): uma série por var_id pedida, sempre.

    Validação de forma (`var_ids`/janela) roda antes de tocar o banco; só então o flow é
    carregado (404 se inexistente) e o bloco validado contra o `graph_json` (422 se
    inexistente ou não-`mpc`) — mesma ordem de `operate.py::_mpc_config`.
    """
    ids = _parse_mpc_var_ids(var_ids)
    end = _as_utc(end) or datetime.now(UTC)
    start = _as_utc(start) or end - timedelta(hours=1)
    if start >= end:
        raise HTTPException(status_code=422, detail="start deve ser anterior a end")
    if end - start > timedelta(days=MAX_WINDOW_DAYS):
        raise HTTPException(
            status_code=422, detail=f"janela não pode exceder {MAX_WINDOW_DAYS} dias"
        )

    flow = await db.get(Flow, flow_id)
    if flow is None:
        raise HTTPException(status_code=404, detail=MSG_FLOW_NAO_ENCONTRADO)
    graph = parse_graph(flow.graph_json)
    try:
        node = graph.node(block_id)
    except KeyError:
        raise HTTPException(
            status_code=422, detail=f"Bloco '{block_id}' não encontrado no flow"
        ) from None
    if node.type != "mpc":
        raise HTTPException(status_code=422, detail=f"Bloco '{block_id}' não é um bloco MPC")

    downsample = end - start > timedelta(hours=RAW_WINDOW_HOURS)
    if downsample:
        var_col, ts_col = mpc_samples_1m.c.var_id, mpc_samples_1m.c.bucket
        flow_col, block_col = mpc_samples_1m.c.flow_id, mpc_samples_1m.c.block_id
        colunas = [
            var_col,
            ts_col.label("ts"),  # "t" colidiria com Row.t (acessor de tupla do SQLAlchemy)
            mpc_samples_1m.c.v.label("v"),
            mpc_samples_1m.c.sp.label("sp"),
            mpc_samples_1m.c.auto.label("auto"),
            mpc_samples_1m.c.v_min.label("v_min"),
            mpc_samples_1m.c.v_max.label("v_max"),
        ]
    else:
        var_col, ts_col = mpc_samples_table.c.var_id, mpc_samples_table.c.ts
        flow_col, block_col = mpc_samples_table.c.flow_id, mpc_samples_table.c.block_id
        colunas = [
            var_col,
            ts_col.label("ts"),
            mpc_samples_table.c.v.label("v"),
            mpc_samples_table.c.sp.label("sp"),
            mpc_samples_table.c.auto.label("auto"),
        ]

    # Uma única query para todas as vars; o agrupamento por var_id é feito em memória.
    stmt = (
        select(*colunas)
        .where(
            flow_col == flow_id,
            block_col == block_id,
            var_col.in_(ids),
            ts_col >= start,
            ts_col <= end,
        )
        .order_by(var_col, ts_col)
    )
    por_var: dict[str, list[Row[Any]]] = {var_id: [] for var_id in ids}
    for linha in (await db.execute(stmt)).all():
        por_var[linha.var_id].append(linha)

    return MpcHistoryResponse(
        mode="1m" if downsample else "raw",
        start=start,
        end=end,
        series=[
            MpcHistorySeries(
                var_id=var_id,
                t=[linha.ts for linha in linhas],
                v=[linha.v for linha in linhas],
                sp=[linha.sp for linha in linhas],
                auto=[linha.auto for linha in linhas],
                v_min=[linha.v_min for linha in linhas] if downsample else None,
                v_max=[linha.v_max for linha in linhas] if downsample else None,
            )
            for var_id, linhas in por_var.items()
        ],
    )


@router.get(
    "/fuzzy",
    response_model=FuzzyHistoryResponse,
    response_model_exclude_none=True,  # v_min/v_max somem do JSON no modo raw
    dependencies=[Depends(require_operator)],
)
async def get_history_fuzzy(
    flow_id: FlowIdFilter,
    block_id: str,
    var_ids: str,
    start: datetime | None = None,
    end: datetime | None = None,
    db: AsyncSession = Depends(get_db),
) -> FuzzyHistoryResponse:
    """Histórico do bloco Fuzzy (ADR-030): uma série por var_id pedida, sempre.

    Validação de forma (`var_ids`/janela) roda antes de tocar o banco; só então o flow é
    carregado (404 se inexistente) e o bloco validado contra o `graph_json` (422 se
    inexistente ou não-`fuzzy`) — mesma ordem de `get_history_mpc`.
    """
    ids = _parse_fuzzy_var_ids(var_ids)
    end = _as_utc(end) or datetime.now(UTC)
    start = _as_utc(start) or end - timedelta(hours=1)
    if start >= end:
        raise HTTPException(status_code=422, detail="start deve ser anterior a end")
    if end - start > timedelta(days=MAX_WINDOW_DAYS):
        raise HTTPException(
            status_code=422, detail=f"janela não pode exceder {MAX_WINDOW_DAYS} dias"
        )

    flow = await db.get(Flow, flow_id)
    if flow is None:
        raise HTTPException(status_code=404, detail=MSG_FLOW_NAO_ENCONTRADO)
    graph = parse_graph(flow.graph_json)
    try:
        node = graph.node(block_id)
    except KeyError:
        raise HTTPException(
            status_code=422, detail=f"Bloco '{block_id}' não encontrado no flow"
        ) from None
    if node.type != "fuzzy":
        raise HTTPException(status_code=422, detail=f"Bloco '{block_id}' não é um bloco Fuzzy")

    downsample = end - start > timedelta(hours=RAW_WINDOW_HOURS)
    if downsample:
        var_col, ts_col = fuzzy_samples_1m.c.var_id, fuzzy_samples_1m.c.bucket
        flow_col, block_col = fuzzy_samples_1m.c.flow_id, fuzzy_samples_1m.c.block_id
        colunas = [
            var_col,
            ts_col.label("ts"),  # "t" colidiria com Row.t (acessor de tupla do SQLAlchemy)
            fuzzy_samples_1m.c.v.label("v"),
            fuzzy_samples_1m.c.v_min.label("v_min"),
            fuzzy_samples_1m.c.v_max.label("v_max"),
        ]
    else:
        var_col, ts_col = fuzzy_samples.c.var_id, fuzzy_samples.c.ts
        flow_col, block_col = fuzzy_samples.c.flow_id, fuzzy_samples.c.block_id
        colunas = [
            var_col,
            ts_col.label("ts"),
            fuzzy_samples.c.v.label("v"),
        ]

    # Uma única query para todas as vars; o agrupamento por var_id é feito em memória.
    stmt = (
        select(*colunas)
        .where(
            flow_col == flow_id,
            block_col == block_id,
            var_col.in_(ids),
            ts_col >= start,
            ts_col <= end,
        )
        .order_by(var_col, ts_col)
    )
    por_var: dict[str, list[Row[Any]]] = {var_id: [] for var_id in ids}
    for linha in (await db.execute(stmt)).all():
        por_var[linha.var_id].append(linha)

    return FuzzyHistoryResponse(
        mode="1m" if downsample else "raw",
        start=start,
        end=end,
        series=[
            FuzzyHistorySeries(
                var_id=var_id,
                t=[linha.ts for linha in linhas],
                v=[linha.v for linha in linhas],
                v_min=[linha.v_min for linha in linhas] if downsample else None,
                v_max=[linha.v_max for linha in linhas] if downsample else None,
            )
            for var_id, linhas in por_var.items()
        ],
    )


@router.get(
    "/ssto/last",
    response_model=SstoLastOut | None,
    dependencies=[Depends(require_operator)],
)
async def get_history_ssto_last(
    flow_id: FlowIdFilter,
    block_id: str,
    db: AsyncSession = Depends(get_db),
) -> SstoLastOut | None:
    """Última execução do SSTO do bloco (ADR-027 §11) — cold-start do sumário do otimizador
    na Operação: sem ela o card ficaria vazio até o próximo ciclo do MPC (Ts_mpc pode ser
    minutos). 200 com `null` quando o bloco nunca executou o SSTO — mesmo contrato dos
    campos opcionais existentes, não 404 (o recurso é a última execução, não o bloco)."""
    flow = await db.get(Flow, flow_id)
    if flow is None:
        raise HTTPException(status_code=404, detail=MSG_FLOW_NAO_ENCONTRADO)
    graph = parse_graph(flow.graph_json)
    try:
        node = graph.node(block_id)
    except KeyError:
        raise HTTPException(
            status_code=422, detail=f"Bloco '{block_id}' não encontrado no flow"
        ) from None
    if node.type != "mpc":
        raise HTTPException(status_code=422, detail=f"Bloco '{block_id}' não é um bloco MPC")

    stmt = (
        select(ssto_runs)
        .where(ssto_runs.c.flow_id == flow_id, ssto_runs.c.block_id == block_id)
        .order_by(ssto_runs.c.ts.desc())
        .limit(1)
    )
    linha = (await db.execute(stmt)).first()
    if linha is None:
        return None
    return SstoLastOut(
        ts=linha.ts,
        run=SstoRun(
            run_id=linha.run_id,
            config_hash=linha.config_hash,
            model_hash=linha.model_hash,
            status=linha.status,
            solver=linha.solver,
            solve_ms=linha.solve_ms,
            objective=linha.objective,
            mv=linha.mv,
            cv_ss=linha.cv_ss,
            bias=linha.bias,
            dv=linha.dv,
            costs=linha.costs,
            delta_mv=linha.delta_mv,
            mv_target=linha.mv_target,
            cv_target=linha.cv_target,
            given_up=linha.given_up,
            active_constraints=linha.active_constraints,
            duals=linha.duals,
        ),
    )
