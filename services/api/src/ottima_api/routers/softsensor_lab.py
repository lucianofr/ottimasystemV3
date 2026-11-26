"""Rotas `/api/softsensor` do laboratório: variáveis, análises e importação de CSV (RF-585;
spec SENSOR_VIRTUAL §7.1-7.2, §8.4).

Leitura e lançamento de análises são do operador; criar, renomear e apagar VARIÁVEL é do admin.
Escopo é o projeto ativo: sem projeto ativo as listas são vazias e as escritas dão 409; variável de
outro projeto é 404. A análise guarda o instante da COLETA (`sampled_at`), nunca o da digitação, e
mesmo instante de uma análise existente substitui (é o que torna o import idempotente).
"""

import asyncio
import math
from collections import Counter
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import Select, delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ottima_api.deps import get_db, get_redis, require_admin, require_operator
from ottima_api.lab_csv import MAX_LAB_CSV_BYTES, LabCsvError, parse_lab_csv
from ottima_core.bus import (
    KIND_LAB_SAMPLE_ADDED,
    KIND_LAB_SAMPLE_DELETED,
    KIND_LAB_SAMPLES_IMPORTED,
    KIND_LAB_VARIABLE_CREATED,
    KIND_LAB_VARIABLE_DELETED,
    KIND_LAB_VARIABLE_UPDATED,
    publish_event,
)
from ottima_core.models import LabSample, LabVariable, Project, SoftSensorDataset, User

router = APIRouter()

MAX_SAMPLES = 5000  # teto de GET .../samples

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
