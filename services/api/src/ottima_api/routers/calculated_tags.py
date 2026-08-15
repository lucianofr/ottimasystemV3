"""CRUD de tags calculadas (RF-208, ADR-033): script Python do usuário em cadência fixa,
leitura para operador e escrita para admin (ADR-015).

Uma tag calculada é sempre TRÊS linhas na mesma transação: `tags` (id compartilhado com o
resto do sistema, ADR-033 D1), `calculated_tags` (script + período) e `calculated_tag_inputs`
(IN1..INn ordenados por posição). As checagens de conteúdo do script rodam antes de
qualquer INSERT — sintaxe inválida ou `IN<n>` fora do alcance só apareceriam depois como
alarme periódico no calc-worker, sem o contexto de quem salvou (TD-001/ADR-033 §3).
"""

from fastapi import APIRouter, Depends, HTTPException
from redis.asyncio import Redis
from sqlalchemy import delete, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ottima_api.deps import get_db, get_redis, require_admin, require_operator
from ottima_api.messages import MSG_PROJETO_NAO_ENCONTRADO
from ottima_core.bus import (
    KIND_CALC_TAG_CREATED,
    KIND_CALC_TAG_DELETED,
    KIND_CALC_TAG_UPDATED,
    publish_event,
)
from ottima_core.calc_script import problemas_do_script
from ottima_core.models import CalculatedTag, CalculatedTagInput, OpcConnection, Project, Tag, User
from ottima_core.schemas.calculated_tags import (
    CalculatedTagCreate,
    CalculatedTagOut,
    CalculatedTagUpdate,
)

# Sem dependência no router: os papéis variam por rota (ADR-015)
router = APIRouter()

MSG_NAO_ENCONTRADA = "Tag calculada não encontrada"
MSG_NOME_EM_USO = "Nome de tag já em uso neste projeto"
MSG_ENTRADA_DEPENDENTE = "Tag calculada é entrada de outra tag calculada e não pode ser removida"
MSG_AUTO_REFERENCIA = "Tag calculada não pode ter a si mesma como entrada"


async def _carregar(db: AsyncSession, tag_id: int) -> tuple[Tag, CalculatedTag]:
    """As duas linhas juntas — mesmo `id` em `tags` e `calculated_tags` (ADR-033 D1).
    Sem `CalculatedTag` correspondente, ou não existe ou é tag OPC: 404 de qualquer jeito."""
    tag = await db.get(Tag, tag_id)
    calc = await db.get(CalculatedTag, tag_id)
    if tag is None or calc is None:
        raise HTTPException(status_code=404, detail=MSG_NAO_ENCONTRADA)
    return tag, calc


async def _entradas(db: AsyncSession, tag_id: int) -> list[int]:
    stmt = (
        select(CalculatedTagInput.source_tag_id)
        .where(CalculatedTagInput.calc_tag_id == tag_id)
        .order_by(CalculatedTagInput.position)
    )
    return list(await db.scalars(stmt))


async def _validar_entradas(
    db: AsyncSession, project_id: int, input_tag_ids: list[int], *, tag_id: int | None = None
) -> None:
    """Cada entrada precisa existir e pertencer ao MESMO projeto: uma tag OPC entra via
    `opc_connections.project_id`, uma tag calculada via `tags.project_id` direto — uma tag
    de outro projeto nunca publicaria valor para este worker.

    `tag_id` só existe no PATCH (a tag já tem id): auto-referência aqui vira um 422
    específico, em vez do 409 genérico de nome duplicado que `IntegrityError` de
    `ck_calculated_tag_inputs_not_self` produziria no commit (achado da revisão de fase 5).
    """
    if tag_id is not None and tag_id in input_tag_ids:
        raise HTTPException(status_code=422, detail=MSG_AUTO_REFERENCIA)
    if not input_tag_ids:
        return
    stmt = (
        select(Tag.id)
        .outerjoin(OpcConnection, OpcConnection.id == Tag.connection_id)
        .where(Tag.id.in_(input_tag_ids))
        .where(or_(OpcConnection.project_id == project_id, Tag.project_id == project_id))
    )
    validos = set(await db.scalars(stmt))
    invalidos = [tid for tid in input_tag_ids if tid not in validos]
    if invalidos:
        nomes = ", ".join(str(tid) for tid in invalidos)
        raise HTTPException(
            status_code=422,
            detail=f"Tag(s) de entrada inexistente(s) ou de outro projeto: {nomes}",
        )


def _validar_script(code: str, n_inputs: int) -> None:
    """Delega a `problemas_do_script` (compartilhado com o import, achado crítico da
    revisão de fase 5) — só o primeiro problema vira 422, exatamente como antes desta
    extração (mesmas mensagens, mesmo status)."""
    problemas = problemas_do_script(code, n_inputs)
    if problemas:
        raise HTTPException(status_code=422, detail=problemas[0])


def _saida(tag: Tag, calc: CalculatedTag, input_tag_ids: list[int]) -> CalculatedTagOut:
    return CalculatedTagOut(
        id=tag.id,
        project_id=tag.project_id,
        name=tag.name,
        eu=tag.eu,
        description=tag.description,
        data_type="float",
        period_seconds=calc.period_seconds,
        code=calc.code,
        input_tag_ids=input_tag_ids,
        created_at=tag.created_at,
        # PATCH pode tocar só a linha de `tags` ou só a de `calculated_tags`: o timestamp
        # exibido é o mais recente das duas, não uma escolhida arbitrariamente.
        updated_at=max(tag.updated_at, calc.updated_at),
    )


async def _publicar(
    redis_client: Redis, user: User, saida: CalculatedTagOut, kind: str, acao: str
) -> None:
    """Auditoria da mutação (ADR-020) — sempre depois do commit, nunca antes."""
    await publish_event(
        redis_client,
        severity="info",
        origin=f"user:{user.id}",
        message=f"Tag calculada '{saida.name}' {acao}",
        kind=kind,
        payload={"tag_id": saida.id, "project_id": saida.project_id, "name": saida.name},
    )


@router.get("", response_model=list[CalculatedTagOut], dependencies=[Depends(require_operator)])
async def list_calculated_tags(
    project_id: int | None = None, db: AsyncSession = Depends(get_db)
) -> list[CalculatedTagOut]:
    stmt = select(Tag).where(Tag.connection_id.is_(None)).order_by(Tag.name)
    if project_id is not None:
        stmt = stmt.where(Tag.project_id == project_id)
    tags = list(await db.scalars(stmt))
    if not tags:
        return []
    tag_ids = [t.id for t in tags]
    calcs = {
        c.tag_id: c
        for c in await db.scalars(select(CalculatedTag).where(CalculatedTag.tag_id.in_(tag_ids)))
    }
    entradas: dict[int, list[int]] = {tid: [] for tid in tag_ids}
    stmt_entradas = (
        select(CalculatedTagInput)
        .where(CalculatedTagInput.calc_tag_id.in_(tag_ids))
        .order_by(CalculatedTagInput.calc_tag_id, CalculatedTagInput.position)
    )
    for row in await db.scalars(stmt_entradas):
        entradas[row.calc_tag_id].append(row.source_tag_id)
    return [_saida(t, calcs[t.id], entradas[t.id]) for t in tags]


@router.post("", response_model=CalculatedTagOut, status_code=201)
async def create_calculated_tag(
    body: CalculatedTagCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
    redis_client: Redis = Depends(get_redis),
) -> CalculatedTagOut:
    if await db.get(Project, body.project_id) is None:
        raise HTTPException(status_code=404, detail=MSG_PROJETO_NAO_ENCONTRADO)
    await _validar_entradas(db, body.project_id, body.input_tag_ids)
    _validar_script(body.code, len(body.input_tag_ids))

    tag = Tag(
        project_id=body.project_id,
        name=body.name,
        eu=body.eu,
        description=body.description,
        direction="r",
        data_type="float",
    )
    db.add(tag)
    try:
        # O flush já pode estourar o índice único de nome (RETURNING do INSERT), então a
        # captura do 409 precisa envolver o flush junto do commit, não só o commit.
        await db.flush()  # id da tag nova precisa existir antes das linhas filhas
        calc = CalculatedTag(tag_id=tag.id, code=body.code, period_seconds=body.period_seconds)
        db.add(calc)
        for posicao, source_id in enumerate(body.input_tag_ids, start=1):
            db.add(
                CalculatedTagInput(calc_tag_id=tag.id, position=posicao, source_tag_id=source_id)
            )
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail=MSG_NOME_EM_USO) from None
    await db.refresh(tag)
    await db.refresh(calc)
    saida = _saida(tag, calc, body.input_tag_ids)
    await _publicar(redis_client, user, saida, KIND_CALC_TAG_CREATED, "criada")
    return saida


@router.get("/{tag_id}", response_model=CalculatedTagOut, dependencies=[Depends(require_operator)])
async def get_calculated_tag(tag_id: int, db: AsyncSession = Depends(get_db)) -> CalculatedTagOut:
    tag, calc = await _carregar(db, tag_id)
    return _saida(tag, calc, await _entradas(db, tag_id))


@router.patch("/{tag_id}", response_model=CalculatedTagOut)
async def update_calculated_tag(
    tag_id: int,
    body: CalculatedTagUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
    redis_client: Redis = Depends(get_redis),
) -> CalculatedTagOut:
    tag, calc = await _carregar(db, tag_id)
    entradas_atuais = await _entradas(db, tag_id)
    novos_input_ids = entradas_atuais if body.input_tag_ids is None else body.input_tag_ids
    novo_code = calc.code if body.code is None else body.code

    # Revalida contra o estado MESCLADO (pós-patch), nunca só o body isolado.
    await _validar_entradas(db, tag.project_id, novos_input_ids, tag_id=tag.id)
    _validar_script(novo_code, len(novos_input_ids))

    dados = body.model_dump(exclude_unset=True)
    for campo in ("name", "eu", "description"):
        if campo in dados:
            setattr(tag, campo, dados[campo])
    for campo in ("code", "period_seconds"):
        if campo in dados:
            setattr(calc, campo, dados[campo])
    if body.input_tag_ids is not None:
        # Posição É o índice IN — troca parcial não tem sentido: apaga tudo e regrava.
        await db.execute(delete(CalculatedTagInput).where(CalculatedTagInput.calc_tag_id == tag_id))
        for posicao, source_id in enumerate(body.input_tag_ids, start=1):
            db.add(
                CalculatedTagInput(calc_tag_id=tag_id, position=posicao, source_tag_id=source_id)
            )

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail=MSG_NOME_EM_USO) from None
    await db.refresh(tag)
    await db.refresh(calc)
    saida = _saida(tag, calc, novos_input_ids)
    await _publicar(redis_client, user, saida, KIND_CALC_TAG_UPDATED, "atualizada")
    return saida


@router.delete("/{tag_id}", status_code=204)
async def delete_calculated_tag(
    tag_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
    redis_client: Redis = Depends(get_redis),
) -> None:
    tag, _ = await _carregar(db, tag_id)
    project_id, name = tag.project_id, tag.name
    await db.delete(tag)  # cascata cuida de calculated_tags/calculated_tag_inputs (ADR-033)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail=MSG_ENTRADA_DEPENDENTE) from None
    await publish_event(
        redis_client,
        severity="info",
        origin=f"user:{user.id}",
        message=f"Tag calculada '{name}' excluída",
        kind=KIND_CALC_TAG_DELETED,
        payload={"tag_id": tag_id, "project_id": project_id, "name": name},
    )
