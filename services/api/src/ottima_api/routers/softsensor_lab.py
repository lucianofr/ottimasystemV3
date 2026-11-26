"""Rotas `/api/softsensor` do laboratório: variáveis, análises e importação de CSV (RF-585;
spec SENSOR_VIRTUAL §7.1-7.2, §8.4), conjuntos de treino e fila de jobs (RF-586; §7.3, §7.5).

Leitura e lançamento de análises são do operador; criar, renomear e apagar VARIÁVEL é do admin.
Escopo é o projeto ativo: sem projeto ativo as listas são vazias e as escritas dão 409; variável de
outro projeto é 404. A análise guarda o instante da COLETA (`sampled_at`), nunca o da digitação, e
mesmo instante de uma análise existente substitui (é o que torna o import idempotente).

Conjunto e job: leitura é do operador, criar/finalizar/apagar conjunto e cancelar job são do admin.
A API só grava linhas em `ml_jobs`; quem as executa é o ml-worker (ADR-046).
"""

import asyncio
import math
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from redis.asyncio import Redis
from sqlalchemy import Select, delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ottima_api.deps import get_db, get_redis, require_admin, require_operator
from ottima_api.lab_csv import MAX_LAB_CSV_BYTES, LabCsvError, parse_lab_csv
from ottima_api.routers.calculated_tags import _validar_entradas
from ottima_core.bus import (
    KIND_LAB_SAMPLE_ADDED,
    KIND_LAB_SAMPLE_DELETED,
    KIND_LAB_SAMPLES_IMPORTED,
    KIND_LAB_VARIABLE_CREATED,
    KIND_LAB_VARIABLE_DELETED,
    KIND_LAB_VARIABLE_UPDATED,
    KIND_SOFT_SENSOR_DATASET_CREATED,
    KIND_SOFT_SENSOR_DATASET_DELETED,
    KIND_SOFT_SENSOR_DATASET_FINALIZED,
    publish_event,
)
from ottima_core.models import (
    HistoryRetentionSettings,
    LabSample,
    LabVariable,
    MlJob,
    Project,
    SoftSensorDataset,
    User,
)
from ottima_core.softsensor import PERIODS_S

router = APIRouter()

MAX_SAMPLES = 5000  # teto de GET .../samples
MAX_DATASET_TAGS = 32
MAX_JOBS = 100  # teto de GET /jobs
JOBS_ATIVOS = ("queued", "running")

# bigint do Postgres: id maior estoura no driver (500) em vez de virar 422
Id = Annotated[int, Field(ge=1, le=2**63 - 1)]

MSG_SEM_PROJETO = "Nenhum projeto ativo"
MSG_VARIAVEL_NAO_ENCONTRADA = "Variável de laboratório não encontrada"
MSG_ANALISE_NAO_ENCONTRADA = "Análise não encontrada"
MSG_NOME_REPETIDO = "Já existe uma variável de laboratório com esse nome"
MSG_NOME_VAZIO = "Nome não pode ser vazio"
MSG_NOME_INVALIDO = "Nome não pode conter ';' nem aspas"
MSG_COM_CONJUNTO = "Variável usada por um conjunto de treino"
MSG_FUTURO = "A data da coleta não pode estar no futuro"
MSG_SEM_FUSO = "A data precisa de fuso horário (ex.: 2025-03-01T10:00:00-03:00)"
MSG_VALOR = "Valor deve ser um número finito"
MSG_CSV_GRANDE = "Arquivo excede o limite de 5 MiB."
MSG_CSV_VAZIO = "Arquivo sem análises para importar"
MSG_CONJUNTO_NAO_ENCONTRADO = "Conjunto de treino não encontrado"
MSG_CONJUNTO_NOME_REPETIDO = "Já existe um conjunto com esse nome"
MSG_TAGS_QUANTIDADE = f"Informe de 1 a {MAX_DATASET_TAGS} tags de entrada"
MSG_TAGS_REPETIDAS = "Tags de entrada repetidas"
MSG_PERIODO = "Período inválido; use um de: " + ", ".join(str(p) for p in PERIODS_S) + " s"
MSG_INICIO_FUTURO = "O início do conjunto não pode estar no futuro"
MSG_JA_FINALIZADO = "Conjunto já finalizado"
MSG_EM_MONTAGEM = "Conjunto em montagem; cancele o job antes"
MSG_JOB_NAO_ENCONTRADO = "Job não encontrado"


class LabVariableCreate(BaseModel):
    name: str
    eu: str = ""
    description: str = ""


class LabVariableUpdate(BaseModel):
    name: str | None = None
    eu: str | None = None
    description: str | None = None


class LabVariableOut(BaseModel):
    id: int
    name: str
    eu: str
    description: str
    sample_count: int
    last_sampled_at: datetime | None


class LabSampleIn(BaseModel):
    value: float
    sampled_at: datetime


class LabSampleOut(BaseModel):
    sampled_at: datetime
    value: float
    source: str


class LabImportOut(BaseModel):
    imported: int
    by_variable: dict[str, int]


class DatasetCreate(BaseModel):
    name: str
    lab_variable_id: Id
    input_tag_ids: list[Id]
    period_s: float
    start_ts: datetime


class DatasetOut(BaseModel):
    """Nunca traz `data`: o blob do conjunto (até 64 MiB) fica fora das listas."""

    id: int
    name: str
    lab_variable_id: int
    lab_variable_name: str
    input_tag_ids: list[int]
    inputs_meta: list
    period_s: float
    start_ts: datetime
    end_ts: datetime | None
    status: str
    stats: dict


class DatasetCreated(DatasetOut):
    warnings: list[str]


class JobAccepted(BaseModel):
    job_id: int


class MlJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    status: str
    params: dict
    progress: dict
    result: dict | None
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


# ------------------------------------------------------------------------------ helpers


def _nome_valido(name: str) -> str:
    """Aparado; `;` e `"` tornariam o nome ambíguo na primeira coluna do CSV."""
    nome = name.strip()
    if not nome:
        raise HTTPException(status_code=422, detail=MSG_NOME_VAZIO)
    if ";" in nome or '"' in nome:
        raise HTTPException(status_code=422, detail=MSG_NOME_INVALIDO)
    return nome


def _com_fuso(quando: datetime) -> datetime:
    """Data sem fuso é ambígua (instante da coleta): recusa em vez de assumir um. Devolve UTC."""
    if quando.tzinfo is None:
        raise HTTPException(status_code=422, detail=MSG_SEM_FUSO)
    return quando.astimezone(UTC)


async def _projeto_ativo(db: AsyncSession) -> int | None:
    return await db.scalar(select(Project.id).where(Project.is_active))


async def _exigir_projeto(db: AsyncSession) -> int:
    project_id = await _projeto_ativo(db)
    if project_id is None:
        raise HTTPException(status_code=409, detail=MSG_SEM_PROJETO)
    return project_id


async def _variavel(db: AsyncSession, project_id: int, var_id: int) -> LabVariable:
    var = await db.scalar(
        select(LabVariable).where(LabVariable.id == var_id, LabVariable.project_id == project_id)
    )
    if var is None:
        raise HTTPException(status_code=404, detail=MSG_VARIAVEL_NAO_ENCONTRADA)
    return var


def _com_contagem(project_id: int) -> Select:
    return (
        select(
            LabVariable.id,
            LabVariable.name,
            LabVariable.eu,
            LabVariable.description,
            func.count(LabSample.lab_variable_id).label("sample_count"),
            func.max(LabSample.sampled_at).label("last_sampled_at"),
        )
        .outerjoin(LabSample, LabSample.lab_variable_id == LabVariable.id)
        .where(LabVariable.project_id == project_id)
        .group_by(LabVariable.id)
    )


async def _saida(db: AsyncSession, project_id: int, var_id: int) -> LabVariableOut:
    row = (await db.execute(_com_contagem(project_id).where(LabVariable.id == var_id))).one()
    return LabVariableOut(**row._mapping)


async def _gravar(db: AsyncSession, linhas: list[dict]) -> None:
    """Upsert por `(lab_variable_id, sampled_at)`. Lista de dicts (executemany) deixa o SQLAlchemy
    paginar o INSERT: um VALUES único de um CSV grande passaria dos 32767 parâmetros do asyncpg."""
    stmt = pg_insert(LabSample)
    await db.execute(
        stmt.on_conflict_do_update(
            index_elements=["lab_variable_id", "sampled_at"],
            set_={
                "value": stmt.excluded.value,
                "source": stmt.excluded.source,
                "created_by": stmt.excluded.created_by,
                "created_at": func.now(),
            },
        ),
        linhas,
    )


async def _auditar(redis_client: Redis, user: User, kind: str, message: str, payload: dict) -> None:
    """Auditoria da mutação (ADR-020): sempre depois do commit, nunca antes."""
    await publish_event(
        redis_client,
        severity="info",
        origin=f"user:{user.id}",
        message=message,
        kind=kind,
        payload=payload,
    )


# ---------------------------------------------------------------------------- variáveis


@router.get(
    "/lab-variables", response_model=list[LabVariableOut], dependencies=[Depends(require_operator)]
)
async def list_lab_variables(db: AsyncSession = Depends(get_db)) -> list[LabVariableOut]:
    project_id = await _projeto_ativo(db)
    if project_id is None:
        return []
    rows = await db.execute(_com_contagem(project_id).order_by(LabVariable.name))
    return [LabVariableOut(**r._mapping) for r in rows]


@router.post("/lab-variables", response_model=LabVariableOut, status_code=201)
async def create_lab_variable(
    body: LabVariableCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
    redis_client: Redis = Depends(get_redis),
) -> LabVariableOut:
    nome = _nome_valido(body.name)
    project_id = await _exigir_projeto(db)
    var = LabVariable(project_id=project_id, name=nome, eu=body.eu, description=body.description)
    db.add(var)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail=MSG_NOME_REPETIDO) from None
    await _auditar(
        redis_client,
        user,
        KIND_LAB_VARIABLE_CREATED,
        f"Variável de laboratório '{nome}' criada",
        {"project_id": project_id, "lab_variable_id": var.id, "name": nome},
    )
    return await _saida(db, project_id, var.id)


@router.patch("/lab-variables/{var_id}", response_model=LabVariableOut)
async def update_lab_variable(
    var_id: int,
    body: LabVariableUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
    redis_client: Redis = Depends(get_redis),
) -> LabVariableOut:
    # exclude_none: as três colunas são NOT NULL, então `null` significa "não mexer"
    campos = body.model_dump(exclude_none=True)
    if "name" in campos:
        campos["name"] = _nome_valido(campos["name"])
    project_id = await _exigir_projeto(db)
    var = await _variavel(db, project_id, var_id)
    for campo, valor in campos.items():
        setattr(var, campo, valor)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail=MSG_NOME_REPETIDO) from None
    await _auditar(
        redis_client,
        user,
        KIND_LAB_VARIABLE_UPDATED,
        f"Variável de laboratório '{var.name}' atualizada",
        {"project_id": project_id, "lab_variable_id": var_id, "name": var.name},
    )
    return await _saida(db, project_id, var_id)


@router.delete("/lab-variables/{var_id}", status_code=204)
async def delete_lab_variable(
    var_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
    redis_client: Redis = Depends(get_redis),
) -> None:
    project_id = await _exigir_projeto(db)
    var = await _variavel(db, project_id, var_id)
    # A FK do conjunto não tem ON DELETE: checa antes para dizer QUAL conjunto segura a variável.
    conjunto = await db.scalar(
        select(SoftSensorDataset.name)
        .where(SoftSensorDataset.lab_variable_id == var_id)
        .order_by(SoftSensorDataset.name)
        .limit(1)
    )
    if conjunto is not None:
        raise HTTPException(status_code=409, detail=f"Variável usada pelo conjunto '{conjunto}'")
    nome = var.name  # depois do delete o objeto não é mais legível
    await db.delete(var)
    try:
        await db.commit()
    except IntegrityError:  # conjunto criado entre a checagem e o delete
        await db.rollback()
        raise HTTPException(status_code=409, detail=MSG_COM_CONJUNTO) from None
    await _auditar(
        redis_client,
        user,
        KIND_LAB_VARIABLE_DELETED,
        f"Variável de laboratório '{nome}' excluída",
        {"project_id": project_id, "lab_variable_id": var_id, "name": nome},
    )


# ------------------------------------------------------------------------------ análises


@router.get(
    "/lab-variables/{var_id}/samples",
    response_model=list[LabSampleOut],
    dependencies=[Depends(require_operator)],
)
async def list_lab_samples(
    var_id: int,
    start: datetime | None = None,
    end: datetime | None = None,
    db: AsyncSession = Depends(get_db),
) -> list[LabSampleOut]:
    """Crescente por coleta. Acima de `MAX_SAMPLES` o corte descarta as MAIS ANTIGAS (quem quer
    olhar para trás estreita com `start`/`end`)."""
    project_id = await _projeto_ativo(db)
    if project_id is None:
        return []
    await _variavel(db, project_id, var_id)
    stmt = select(LabSample.sampled_at, LabSample.value, LabSample.source).where(
        LabSample.lab_variable_id == var_id
    )
    if start is not None:
        stmt = stmt.where(LabSample.sampled_at >= _com_fuso(start))
    if end is not None:
        stmt = stmt.where(LabSample.sampled_at <= _com_fuso(end))
    rows = await db.execute(stmt.order_by(LabSample.sampled_at.desc()).limit(MAX_SAMPLES))
    return [LabSampleOut(**r._mapping) for r in reversed(rows.all())]


@router.post("/lab-variables/{var_id}/samples", response_model=LabSampleOut, status_code=201)
async def add_lab_sample(
    var_id: int,
    body: LabSampleIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_operator),
    redis_client: Redis = Depends(get_redis),
) -> LabSampleOut:
    if not math.isfinite(body.value):
        raise HTTPException(status_code=422, detail=MSG_VALOR)
    coleta = _com_fuso(body.sampled_at)
    if coleta > datetime.now(UTC):
        raise HTTPException(status_code=422, detail=MSG_FUTURO)
    project_id = await _exigir_projeto(db)
    var = await _variavel(db, project_id, var_id)
    await _gravar(
        db,
        [
            {
                "lab_variable_id": var_id,
                "sampled_at": coleta,
                "value": body.value,
                "source": "manual",
                "created_by": f"user:{user.id}",
            }
        ],
    )
    await db.commit()
    await _auditar(
        redis_client,
        user,
        KIND_LAB_SAMPLE_ADDED,
        f"Análise de '{var.name}' lançada",
        {
            "project_id": project_id,
            "lab_variable_id": var_id,
            "name": var.name,
            "sampled_at": coleta.isoformat(),
            "value": body.value,
        },
    )
    return LabSampleOut(sampled_at=coleta, value=body.value, source="manual")


@router.delete("/lab-variables/{var_id}/samples", status_code=204)
async def delete_lab_sample(
    var_id: int,
    sampled_at: datetime,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_operator),
    redis_client: Redis = Depends(get_redis),
) -> None:
    coleta = _com_fuso(sampled_at)
    project_id = await _exigir_projeto(db)
    var = await _variavel(db, project_id, var_id)
    apagada = await db.scalar(
        delete(LabSample)
        .where(LabSample.lab_variable_id == var_id, LabSample.sampled_at == coleta)
        .returning(LabSample.lab_variable_id)
    )
    if apagada is None:
        raise HTTPException(status_code=404, detail=MSG_ANALISE_NAO_ENCONTRADA)
    await db.commit()
    await _auditar(
        redis_client,
        user,
        KIND_LAB_SAMPLE_DELETED,
        f"Análise de '{var.name}' excluída",
        {
            "project_id": project_id,
            "lab_variable_id": var_id,
            "name": var.name,
            "sampled_at": coleta.isoformat(),
        },
    )


# ---------------------------------------------------------------------------- importação


def _digitos_significativos(declarado: str) -> str:
    # isdecimal() antes de qualquer int(): header hostil não estoura o limite de dígitos do int()
    return declarado.lstrip("0") if declarado.isdecimal() else ""


async def _ler_corpo_csv(request: Request) -> bytes:
    """Corpo bruto com teto de `MAX_LAB_CSV_BYTES` (molde: `projects._ler_corpo_import`): recusa
    pelo `Content-Length` quando há e, de todo modo, aborta no primeiro chunk que cruza o teto,
    sem bufferizar o resto."""
    sig = _digitos_significativos(request.headers.get("content-length", ""))
    if len(sig) > 15 or int(sig or 0) > MAX_LAB_CSV_BYTES:
        raise HTTPException(status_code=413, detail=MSG_CSV_GRANDE)
    partes: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > MAX_LAB_CSV_BYTES:
            raise HTTPException(status_code=413, detail=MSG_CSV_GRANDE)
        partes.append(chunk)
    return b"".join(partes)


@router.post(
    "/lab-samples/import",
    response_model=LabImportOut,
    # Corpo lido em stream (teto antes de materializar): sem parâmetro `body:`, o FastAPI não
    # documentaria o requestBody sozinho. Mesmo padrão de `projects.import_project`.
    openapi_extra={
        "requestBody": {
            "content": {"text/csv": {"schema": {"type": "string"}}},
            "required": True,
        },
    },
)
async def import_lab_samples(
    request: Request,
    tz: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_operator),
    redis_client: Redis = Depends(get_redis),
) -> LabImportOut:
    """Importa o CSV `nome;data/hora;valor` de uma vez só: qualquer problema recusa o arquivo
    inteiro (422, nada gravado). `tz` é o fuso IANA do navegador para datas sem fuso no texto."""
    corpo = await _ler_corpo_csv(request)
    project_id = await _exigir_projeto(db)
    known = {
        nome: id_
        for id_, nome in await db.execute(
            select(LabVariable.id, LabVariable.name).where(LabVariable.project_id == project_id)
        )
    }
    try:
        # ~2 s de CPU no teto de 5 MiB: fora do event loop
        rows = await asyncio.to_thread(
            parse_lab_csv, corpo, tz=tz, known=known, now=datetime.now(UTC)
        )
    except LabCsvError as e:
        raise HTTPException(status_code=422, detail="; ".join(e.problems)) from None
    if not rows:
        raise HTTPException(status_code=422, detail=MSG_CSV_VAZIO)

    autor = f"user:{user.id}"
    await _gravar(
        db,
        [
            {
                "lab_variable_id": r.variable_id,
                "sampled_at": r.sampled_at,
                "value": r.value,
                "source": "csv",
                "created_by": autor,
            }
            for r in rows
        ],
    )
    await db.commit()

    nomes = {id_: nome for nome, id_ in known.items()}
    por_variavel = dict(Counter(nomes[r.variable_id] for r in rows))
    await _auditar(
        redis_client,
        user,
        KIND_LAB_SAMPLES_IMPORTED,
        f"{len(rows)} análises de laboratório importadas",
        {"project_id": project_id, "imported": len(rows), "by_variable": por_variavel},
    )
    return LabImportOut(imported=len(rows), by_variable=por_variavel)


# --------------------------------------------------------------------- conjuntos de treino


def _conjuntos(project_id: int) -> Select:
    return (
        select(
            SoftSensorDataset.id,
            SoftSensorDataset.name,
            SoftSensorDataset.lab_variable_id,
            LabVariable.name.label("lab_variable_name"),
            SoftSensorDataset.input_tag_ids,
            SoftSensorDataset.inputs_meta,
            SoftSensorDataset.period_s,
            SoftSensorDataset.start_ts,
            SoftSensorDataset.end_ts,
            SoftSensorDataset.status,
            SoftSensorDataset.stats,
        )
        .join(LabVariable, LabVariable.id == SoftSensorDataset.lab_variable_id)
        .where(SoftSensorDataset.project_id == project_id)
    )


async def _nome_do_conjunto(db: AsyncSession, project_id: int, dataset_id: int) -> str:
    nome = await db.scalar(
        select(SoftSensorDataset.name).where(
            SoftSensorDataset.id == dataset_id, SoftSensorDataset.project_id == project_id
        )
    )
    if nome is None:
        raise HTTPException(status_code=404, detail=MSG_CONJUNTO_NAO_ENCONTRADO)
    return nome


@router.get("/datasets", response_model=list[DatasetOut], dependencies=[Depends(require_operator)])
async def list_datasets(db: AsyncSession = Depends(get_db)) -> list[DatasetOut]:
    project_id = await _projeto_ativo(db)
    if project_id is None:
        return []
    rows = await db.execute(_conjuntos(project_id).order_by(SoftSensorDataset.id.desc()))
    return [DatasetOut(**r._mapping) for r in rows]


@router.post("/datasets", response_model=DatasetCreated, status_code=201)
async def create_dataset(
    body: DatasetCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
    redis_client: Redis = Depends(get_redis),
) -> DatasetCreated:
    nome = body.name.strip()
    if not nome:
        raise HTTPException(status_code=422, detail=MSG_NOME_VAZIO)
    if not 1 <= len(body.input_tag_ids) <= MAX_DATASET_TAGS:
        raise HTTPException(status_code=422, detail=MSG_TAGS_QUANTIDADE)
    if len(set(body.input_tag_ids)) != len(body.input_tag_ids):
        raise HTTPException(status_code=422, detail=MSG_TAGS_REPETIDAS)
    if body.period_s not in PERIODS_S:
        raise HTTPException(status_code=422, detail=MSG_PERIODO)
    inicio = _com_fuso(body.start_ts)
    if inicio > datetime.now(UTC):
        raise HTTPException(status_code=422, detail=MSG_INICIO_FUTURO)

    project_id = await _exigir_projeto(db)
    # O handler do ml-worker só checa existência da tag: a guarda de projeto é esta.
    await _validar_entradas(db, project_id, body.input_tag_ids)
    try:
        await _variavel(db, project_id, body.lab_variable_id)
    except HTTPException:  # referência no corpo, não na URL: 422 e não 404
        raise HTTPException(status_code=422, detail=MSG_VARIAVEL_NAO_ENCONTRADA) from None

    ds = SoftSensorDataset(
        project_id=project_id,
        name=nome,
        lab_variable_id=body.lab_variable_id,
        input_tag_ids=body.input_tag_ids,
        period_s=body.period_s,
        start_ts=inicio,
        created_by=f"user:{user.id}",
    )
    db.add(ds)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail=MSG_CONJUNTO_NOME_REPETIDO) from None
    await _auditar(
        redis_client,
        user,
        KIND_SOFT_SENSOR_DATASET_CREATED,
        f"Conjunto de treino '{nome}' criado",
        {"project_id": project_id, "dataset_id": ds.id, "name": nome},
    )

    dias = await db.scalar(select(HistoryRetentionSettings.retention_days))
    avisos = []
    if inicio < datetime.now(UTC) - timedelta(days=dias):
        avisos.append(
            f"O início é anterior à retenção do histórico ({dias} dias): "
            "parte do período não terá dado de processo"
        )
    row = (await db.execute(_conjuntos(project_id).where(SoftSensorDataset.id == ds.id))).one()
    return DatasetCreated(**row._mapping, warnings=avisos)


@router.post("/datasets/{dataset_id}/finalize", response_model=JobAccepted, status_code=202)
async def finalize_dataset(
    dataset_id: Id,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
    redis_client: Redis = Depends(get_redis),
) -> JobAccepted:
    project_id = await _exigir_projeto(db)
    nome = await _nome_do_conjunto(db, project_id, dataset_id)
    # Transição guardada no UPDATE (duas finalizações simultâneas não enfileiram dois jobs).
    # coalesce: `collecting` nunca tem end_ts (grava agora); `failed` já tem, e a nova tentativa
    # mantém o período.
    movido = await db.scalar(
        update(SoftSensorDataset)
        .where(
            SoftSensorDataset.id == dataset_id,
            SoftSensorDataset.status.in_(("collecting", "failed")),
        )
        .values(status="building", end_ts=func.coalesce(SoftSensorDataset.end_ts, func.now()))
        .returning(SoftSensorDataset.id)
    )
    if movido is None:
        raise HTTPException(status_code=409, detail=MSG_JA_FINALIZADO)
    job = MlJob(
        project_id=project_id,
        kind="dataset_build",
        params={"dataset_id": dataset_id},
        created_by=f"user:{user.id}",
    )
    db.add(job)
    await db.commit()
    await _auditar(
        redis_client,
        user,
        KIND_SOFT_SENSOR_DATASET_FINALIZED,
        f"Conjunto de treino '{nome}' finalizado",
        {"project_id": project_id, "dataset_id": dataset_id, "name": nome, "job_id": job.id},
    )
    return JobAccepted(job_id=job.id)


@router.delete("/datasets/{dataset_id}", status_code=204)
async def delete_dataset(
    dataset_id: Id,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
    redis_client: Redis = Depends(get_redis),
) -> None:
    project_id = await _exigir_projeto(db)
    nome = await _nome_do_conjunto(db, project_id, dataset_id)
    apagado = await db.scalar(
        delete(SoftSensorDataset)
        .where(SoftSensorDataset.id == dataset_id, SoftSensorDataset.status != "building")
        .returning(SoftSensorDataset.id)
    )
    if apagado is None:
        raise HTTPException(status_code=409, detail=MSG_EM_MONTAGEM)
    await db.commit()
    await _auditar(
        redis_client,
        user,
        KIND_SOFT_SENSOR_DATASET_DELETED,
        f"Conjunto de treino '{nome}' excluído",
        {"project_id": project_id, "dataset_id": dataset_id, "name": nome},
    )


# ------------------------------------------------------------------------------------ jobs


async def _job(db: AsyncSession, project_id: int, job_id: int) -> MlJob:
    job = await db.scalar(select(MlJob).where(MlJob.id == job_id, MlJob.project_id == project_id))
    if job is None:
        raise HTTPException(status_code=404, detail=MSG_JOB_NAO_ENCONTRADO)
    return job


@router.get("/jobs", response_model=list[MlJobOut], dependencies=[Depends(require_operator)])
async def list_jobs(active: bool | None = None, db: AsyncSession = Depends(get_db)) -> list[MlJob]:
    """Mais novos primeiro; `active` separa fila e andamento (true) do histórico (false)."""
    project_id = await _projeto_ativo(db)
    if project_id is None:
        return []
    stmt = select(MlJob).where(MlJob.project_id == project_id)
    if active is not None:
        stmt = stmt.where(
            MlJob.status.in_(JOBS_ATIVOS) if active else MlJob.status.notin_(JOBS_ATIVOS)
        )
    return list(await db.scalars(stmt.order_by(MlJob.id.desc()).limit(MAX_JOBS)))


@router.get("/jobs/{job_id}", response_model=MlJobOut, dependencies=[Depends(require_operator)])
async def get_job(job_id: Id, db: AsyncSession = Depends(get_db)) -> MlJob:
    return await _job(db, await _exigir_projeto(db), job_id)


@router.post("/jobs/{job_id}/cancel", status_code=202, dependencies=[Depends(require_admin)])
async def cancel_job(job_id: Id, db: AsyncSession = Depends(get_db)) -> Response:
    """Job `queued` vira `cancelled` aqui mesmo: o ml-worker nunca o verá, então o efeito colateral
    de `jobs.finish` (conjunto `building` -> `failed`) tem de sair desta transação. `running` só
    recebe a flag (o worker a honra). Job já terminado não muda."""
    await _job(db, await _exigir_projeto(db), job_id)
    # Guarda no UPDATE: o worker pode reivindicar o job entre a leitura e a escrita.
    na_fila = (
        await db.execute(
            update(MlJob)
            .where(MlJob.id == job_id, MlJob.status == "queued")
            .values(status="cancelled", cancel_requested=True, finished_at=func.now())
            .returning(MlJob.kind, MlJob.params)
        )
    ).first()
    if na_fila is None:
        await db.execute(
            update(MlJob)
            .where(MlJob.id == job_id, MlJob.status == "running")
            .values(cancel_requested=True)
        )
    elif na_fila.kind == "dataset_build":
        await db.execute(
            update(SoftSensorDataset)
            .where(
                SoftSensorDataset.id == na_fila.params["dataset_id"],
                SoftSensorDataset.status == "building",
            )
            .values(status="failed")
        )
    await db.commit()
    return Response(status_code=202)
