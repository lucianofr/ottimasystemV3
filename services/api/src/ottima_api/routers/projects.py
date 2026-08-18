"""CRUD de projetos (RF-101, ADR-017): leitura para operador, escrita e ativação para admin."""

import asyncio
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import ValidationError
from redis.asyncio import Redis
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ottima_api.deps import get_app_settings, get_db, get_redis, require_admin, require_operator
from ottima_api.messages import MSG_PROJETO_NAO_ENCONTRADO, MSG_PROJETO_NOME_EM_USO
from ottima_api.validacao import formatar_problemas, problemas_de_validacao
from ottima_core.bus import (
    KIND_PROJECT_ACTIVATED,
    KIND_PROJECT_EXPORTED,
    KIND_PROJECT_IMPORTED,
    publish_event,
)
from ottima_core.certs import read_app_certificate
from ottima_core.config import Settings
from ottima_core.flowgraph import (
    GraphParseError,
    TagRef,
    ValidationResult,
    parse_graph,
    validate_graph,
)
from ottima_core.models import (
    CalculatedTag,
    CalculatedTagInput,
    Flow,
    OpcConnection,
    Project,
    Tag,
    User,
)
from ottima_core.portability import (
    SCHEMA_VERSION,
    ProjectBundle,
    ReferenciaTagInvalida,
    grafo_para_banco,
    montar_bundle,
    problemas_de_coerencia_interna,
)
from ottima_core.portability.pendencias import pendencias_da_conexao
from ottima_core.schemas.projects import (
    ProjectCreate,
    ProjectImportIn,
    ProjectImportOut,
    ProjectOut,
    ProjectUpdate,
)

# Sem dependência no router: os papéis variam por rota (ADR-015)
router = APIRouter()

_SLUG_SEP = re.compile(r"[^a-z0-9]+")


def _slug(name: str) -> str:
    """Reduz o nome do projeto a `[a-z0-9-]` para o filename do export (spec §3.1-2):
    minúsculas, sequências fora de a-z0-9 colapsadas num único hífen, hífens das pontas
    removidos. Nome que reduz a vazio cai em `projeto`."""
    slug = _SLUG_SEP.sub("-", name.lower()).strip("-")
    return slug or "projeto"


async def _carregar(db: AsyncSession, project_id: int) -> Project:
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=MSG_PROJETO_NAO_ENCONTRADO)
    return project


def _parse_e_validar(
    graph_banco: dict, tags: Mapping[int, TagRef], ts_seconds: float
) -> ValidationResult:
    """Parse + validação num passo só (mesmo padrão de `routers.flows._validar_grafo`), para
    rodar inteiro dentro de um `asyncio.to_thread` sem reentrar no event loop no meio do
    parse (TD-002).
    """
    return validate_graph(parse_graph(graph_banco), tags, ts_seconds)


@router.get("", response_model=list[ProjectOut], dependencies=[Depends(require_operator)])
async def list_projects(db: AsyncSession = Depends(get_db)) -> list[Project]:
    return list(await db.scalars(select(Project).order_by(Project.name)))


@router.post("", response_model=ProjectOut, status_code=201, dependencies=[Depends(require_admin)])
async def create_project(body: ProjectCreate, db: AsyncSession = Depends(get_db)) -> Project:
    """Projetos nascem inativos (ADR-017): a ativação é um passo explícito."""
    project = Project(name=body.name, description=body.description)
    db.add(project)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail=MSG_PROJETO_NOME_EM_USO) from None
    await db.refresh(project)
    return project


@router.get("/{project_id}", response_model=ProjectOut, dependencies=[Depends(require_operator)])
async def get_project(project_id: int, db: AsyncSession = Depends(get_db)) -> Project:
    return await _carregar(db, project_id)


@router.patch("/{project_id}", response_model=ProjectOut, dependencies=[Depends(require_admin)])
async def update_project(
    project_id: int, body: ProjectUpdate, db: AsyncSession = Depends(get_db)
) -> Project:
    project = await _carregar(db, project_id)
    if body.name is not None:
        project.name = body.name
    if body.description is not None:
        project.description = body.description
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail=MSG_PROJETO_NOME_EM_USO) from None
    await db.refresh(project)
    return project


@router.delete("/{project_id}", status_code=204, dependencies=[Depends(require_admin)])
async def delete_project(project_id: int, db: AsyncSession = Depends(get_db)) -> None:
    project = await _carregar(db, project_id)
    if project.is_active:
        # CASCADE removeria conexões/tags/flows do projeto em operação (spec §6.2)
        raise HTTPException(status_code=409, detail="Desative o projeto antes de excluí-lo")
    # Ordem importa: `calculated_tag_inputs.source_tag_id -> tags.id` é RESTRICT de
    # propósito (impede apagar uma tag que alimenta um script). A API garante que toda
    # entrada pertence ao MESMO projeto (_validar_entradas), então remover as arestas de
    # input do projeto antes do DELETE desobstrui o cascade do banco.
    await db.execute(
        delete(CalculatedTagInput).where(
            CalculatedTagInput.calc_tag_id.in_(select(Tag.id).where(Tag.project_id == project_id))
        )
    )
    await db.delete(project)
    await db.commit()


@router.post("/{project_id}/activate", response_model=ProjectOut)
async def activate_project(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
    redis_client: Redis = Depends(get_redis),
) -> Project:
    """Transação única: desativa o atual e ativa o alvo (ADR-017; índice parcial garante 1 ativo).

    F1 apenas persiste; a partir da F3 este endpoint também encerra a execução do projeto
    anterior via `flow.commands` (gancho registrado no spec §6.2). Reativar o projeto que já
    é o ativo continua respondendo 200 com o projeto, mas **não** republica o evento.
    """
    project = await _carregar(db, project_id)
    # Lido antes do UPDATE em massa abaixo, que apaga a informação. Reativar quem já é o ativo
    # não é transição, e desde a F3 o evento é destrutivo: o supervisor do flow-runtime para
    # TODOS os flows rodando ao recebê-lo (spec §2.2-8, gancho RF-101). Sem esta guarda, um
    # clique em "ativar" no projeto vigente derrubaria a planta em silêncio.
    ja_era_o_ativo = project.is_active
    # Um único commit no fim: o índice parcial rejeitaria o estado intermediário com 2 ativos
    await db.execute(update(Project).where(Project.is_active).values(is_active=False))
    project.is_active = True
    # Transição real: o runtime para toda execução na troca (§2.2-8, RF-101); aqui o
    # desejado é alinhado ao efeito na mesma transação — após ativar, nenhum flow fica
    # "Rodando — aguardando confirmação" de projeto que não é o ativo, nem pode ser
    # auto-ativado por retomada a partir de um `desired_state` órfão (ADR-017). Reativar o
    # ativo não é transição (sem evento, o runtime não para nada) e não toca o desejado:
    # um clique redundante não desarma a retomada automática (TD-005/ADR-025) nem mente
    # "parado" para a planta em operação.
    if not ja_era_o_ativo:
        await db.execute(
            update(Flow).where(Flow.desired_state == "running").values(desired_state="stopped")
        )
    await db.commit()
    await db.refresh(project)
    if ja_era_o_ativo:
        return project
    # Depois do commit: evento sobre ativação que falhou envenenaria a reconciliação do worker
    await publish_event(
        redis_client,
        severity="info",
        origin=f"user:{user.id}",
        message=f"Projeto '{project.name}' ativado",
        kind=KIND_PROJECT_ACTIVATED,
        payload={"project_id": project.id, "name": project.name},
    )
    return project


@router.get("/{project_id}/export")
async def export_project(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
    redis_client: Redis = Depends(get_redis),
) -> Response:
    """Arquivo de projeto (bundle) para portabilidade entre instalações (spec §3.1).

    `require_admin`: mesmo sem segredos, o bundle revela a topologia OPC completa da
    planta (RF-102, PRD §2). Exporta **qualquer** projeto por id, não só o ativo.
    """
    project = await _carregar(db, project_id)
    connections = list(
        await db.scalars(select(OpcConnection).where(OpcConnection.project_id == project_id))
    )
    # Tags OPC pelas conexões do projeto, nunca por uma consulta independente: `ref_por_id`
    # (ottima_core.portability.bundle) indexa por `connection.id` e propaga `KeyError` se
    # alguma tag carregada apontar para uma conexão fora deste conjunto (revisão da 1.3) —
    # o join garante que toda tag aqui pertence a uma das `connections` acima.
    tags_opc = list(
        await db.scalars(
            select(Tag)
            .join(OpcConnection, Tag.connection_id == OpcConnection.id)
            .where(OpcConnection.project_id == project_id)
        )
    )
    # Tag calculada não corre o mesmo risco (revisão da 1.3, comentário acima): sua dona é o
    # próprio projeto (`project_id`, `ck_tags_owner`), não uma conexão — filtrar direto por
    # `Tag.project_id` já é o mesmo isolamento que o join acima dá às OPC. Quatro consultas
    # fixas (tags calculadas, `calculated_tags`, `calculated_tag_inputs`), nunca uma por tag.
    tags_calculadas = list(await db.scalars(select(Tag).where(Tag.project_id == project_id)))
    calculated_tags = list(
        await db.scalars(
            select(CalculatedTag)
            .join(Tag, CalculatedTag.tag_id == Tag.id)
            .where(Tag.project_id == project_id)
        )
    )
    calculated_tag_inputs = list(
        await db.scalars(
            select(CalculatedTagInput)
            .join(Tag, CalculatedTagInput.calc_tag_id == Tag.id)
            .where(Tag.project_id == project_id)
        )
    )
    flows = list(await db.scalars(select(Flow).where(Flow.project_id == project_id)))
    try:
        bundle = montar_bundle(
            project=project,
            connections=connections,
            tags=[*tags_opc, *tags_calculadas],
            calculated_tags=calculated_tags,
            calculated_tag_inputs=calculated_tag_inputs,
            flows=flows,
            exported_at=datetime.now(UTC),
        )
    except ReferenciaTagInvalida as exc:
        # Referência que não resolve aborta com 422, nunca exporta bundle quebrado (§2.2-5).
        raise HTTPException(
            status_code=422,
            detail=formatar_problemas(exc.problemas, cabecalho="Export recusado"),
        ) from None

    # Depois de montar o bundle: evento sobre export que falhou (422 acima) poluiria a
    # auditoria com uma ação que não aconteceu. A própria justificativa do RBAC é a
    # sensibilidade da topologia — export sem evento seria exfiltração silenciosa (SEC-05).
    await publish_event(
        redis_client,
        severity="info",
        origin=f"user:{user.id}",
        message=f"Projeto '{project.name}' exportado",
        kind=KIND_PROJECT_EXPORTED,
        payload={"project_id": project.id, "name": project.name},
    )
    return Response(
        content=bundle.model_dump_json(),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{_slug(project.name)}.ottima.json"'
        },
    )


MAX_IMPORT_BUNDLE_BYTES = 4 * 1024 * 1024  # 4 MiB (spec §3.2-1)
_MAX_DIGITOS_TETO_IMPORT = len(str(MAX_IMPORT_BUNDLE_BYTES))
_MSG_IMPORT_GRANDE = "Corpo do import excede o limite de 4 MiB."
_MSG_JSON_INVALIDO = "Corpo não é JSON válido"


def _excede_o_declarado_import(declarado: str | None) -> bool:
    """Mesmo raciocínio de `connections._excede_o_declarado`, com o teto de 4 MiB do import
    (spec §3.2-1): `isdecimal()` filtra o alfabeto do header antes de qualquer `int()`, e a
    contagem de dígitos resolve sozinha o caso "grande demais" sem estourar
    `sys.get_int_max_str_digits()`."""
    if declarado is None or not declarado.isdecimal():
        return False
    significativos = declarado.lstrip("0")
    if len(significativos) > _MAX_DIGITOS_TETO_IMPORT:
        return True
    return int(significativos or "0") > MAX_IMPORT_BUNDLE_BYTES


async def _ler_corpo_import(request: Request) -> bytes:
    """Corpo bruto do arquivo de projeto (bundle), com teto de 4 MiB — molde exato de
    `connections._ler_certificado`: um parâmetro `body:` tipado só materializa o payload
    inteiro no momento em que dá para medi-lo (API-06), então a leitura é em fluxo e aborta
    no primeiro chunk que cruza o teto, nunca depois de bufferizar tudo (spec §3.2-1).
    """
    if _excede_o_declarado_import(request.headers.get("content-length")):
        raise HTTPException(status_code=413, detail=_MSG_IMPORT_GRANDE)
    partes: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > MAX_IMPORT_BUNDLE_BYTES:
            raise HTTPException(status_code=413, detail=_MSG_IMPORT_GRANDE)
        partes.append(chunk)
    return b"".join(partes)


@router.post(
    "/import",
    response_model=ProjectImportOut,
    status_code=201,
    # O corpo é lido em stream via `_ler_corpo_import` (teto de 4 MiB antes de materializar,
    # API-06) — sem parâmetro `body: ProjectImportIn`, o FastAPI não teria como documentar o
    # requestBody sozinho. `openapi_extra` publica o schema (derivado do próprio modelo, não
    # reescrito à mão) sem amarrar a leitura em stream (tarefa 6.1, fix round 1).
    openapi_extra={
        "requestBody": {
            "content": {"application/json": {"schema": ProjectImportIn.model_json_schema()}},
            "required": True,
        },
    },
)
async def import_project(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
    redis_client: Redis = Depends(get_redis),
    settings: Settings = Depends(get_app_settings),
) -> ProjectImportOut:
    """Import de projeto (spec §3.2, RF-103): quatro camadas de validação, a maioria em
    memória e antes de qualquer insert. As duas exceções — nome de projeto duplicado (só o
    banco responde) e a camada 4 (que precisa dos ids gerados pelo insert de conexões/tags
    para traduzir o grafo) — inserem via `flush()` e desfazem com `rollback()` se falharem;
    o `commit()` só acontece depois que as quatro camadas passam.
    """
    corpo = await _ler_corpo_import(request)

    try:
        bruto = json.loads(corpo)
    except json.JSONDecodeError:
        raise HTTPException(status_code=422, detail=_MSG_JSON_INVALIDO) from None

    try:
        body = ProjectImportIn.model_validate(bruto)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=formatar_problemas(problemas_de_validacao(exc), cabecalho="Import recusado"),
        ) from None

    # Camada 1 (§3.2-2): schema_version diferente de 1 é 422 imediato, nunca migração.
    versao = body.bundle.get("schema_version")
    if versao != SCHEMA_VERSION:
        raise HTTPException(
            status_code=422,
            detail=formatar_problemas(
                [f"schema_version {versao!r} não suportado; esperado {SCHEMA_VERSION}"],
                cabecalho="Import recusado",
            ),
        )

    # Camada 2 (§3.2-4): forma do bundle — todos os modelos são `extra="forbid"`.
    try:
        bundle = ProjectBundle.model_validate(body.bundle)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=formatar_problemas(problemas_de_validacao(exc), cabecalho="Import recusado"),
        ) from None

    # Camada 3 (§3.2-4): referências internas, em memória, antes de qualquer insert.
    problemas = problemas_de_coerencia_interna(bundle)
    if problemas:
        raise HTTPException(
            status_code=422, detail=formatar_problemas(problemas, cabecalho="Import recusado")
        )

    nome_final = body.name if body.name is not None else bundle.project.name

    project = Project(name=nome_final, description=bundle.project.description, is_active=False)
    db.add(project)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail=MSG_PROJETO_NOME_EM_USO) from None

    conexoes_por_nome: dict[str, OpcConnection] = {}
    for bc in bundle.connections:
        conn = OpcConnection(
            project_id=project.id,
            name=bc.name,
            endpoint=bc.endpoint,
            security_policy=bc.security_policy,
            security_mode=bc.security_mode,
            auth_mode=bc.auth_mode,
            auth_username=bc.auth_username,
            polling_period_ms=bc.polling_period_ms,
        )
        db.add(conn)
        conexoes_por_nome[bc.name] = conn
    await db.flush()  # ids das conexões, para o `connection_id` das tags abaixo

    tags_por_ref: dict[tuple[str | None, str], Tag] = {}
    for bt in bundle.tags:
        if bt.connection is None:
            continue  # tag calculada: bloco abaixo, depois que toda tag OPC já tem id
        tag = Tag(
            connection_id=conexoes_por_nome[bt.connection].id,
            name=bt.name,
            node_id=bt.node_id,
            direction=bt.direction,
            data_type=bt.data_type,
            eu=bt.eu,
            description=bt.description,
        )
        db.add(tag)
        tags_por_ref[(bt.connection, bt.name)] = tag
    await db.flush()  # ids das tags OPC — o mapa (connection, tag) -> id existe para elas

    # Tags calculadas (RF-208, ADR-033 D6): `Tag` de todas primeiro (nenhuma depende de outra
    # calculada para existir), só então `CalculatedTag` (FK em `tag.id`, já conhecido nesse
    # ponto) e por último `CalculatedTagInput` — dessa forma uma calculada pode referenciar
    # outra calculada em `input_tags` em qualquer ordem dentro do bundle, sem topological
    # sort: quando o terceiro bloco roda, toda tag (OPC ou calculada) já está em
    # `tags_por_ref` com id definitivo. A camada 3 (`problemas_de_coerencia_interna`, já
    # rodada acima) garantiu que toda referência resolve e que não há ciclo — nenhuma das
    # duas falhas é alcançável aqui.
    tags_calculadas_bundle = [bt for bt in bundle.tags if bt.connection is None]
    for bt in tags_calculadas_bundle:
        tag = Tag(
            project_id=project.id,
            name=bt.name,
            direction=bt.direction,
            data_type=bt.data_type,
            eu=bt.eu,
            description=bt.description,
        )
        db.add(tag)
        tags_por_ref[(None, bt.name)] = tag
    if tags_calculadas_bundle:
        await db.flush()  # ids das tags calculadas, para o `tag_id` de CalculatedTag abaixo

    for bt in tags_calculadas_bundle:
        db.add(
            CalculatedTag(
                tag_id=tags_por_ref[(None, bt.name)].id,
                code=bt.code,
                period_seconds=bt.period_seconds,
            )
        )
    if tags_calculadas_bundle:
        await db.flush()  # ids de CalculatedTag, para o `calc_tag_id` de CalculatedTagInput

    for bt in tags_calculadas_bundle:
        for posicao, ref in enumerate(bt.input_tags or [], start=1):
            db.add(
                CalculatedTagInput(
                    calc_tag_id=tags_por_ref[(None, bt.name)].id,
                    position=posicao,
                    source_tag_id=tags_por_ref[(ref.connection, ref.tag)].id,
                )
            )
    if tags_calculadas_bundle:
        await db.flush()

    id_por_ref = {ref: tag.id for ref, tag in tags_por_ref.items()}
    # Tag calculada nunca aparece num grafo (D5, ADR-033): `validate_graph` só precisa saber
    # das OPC, e `TagRef.conn_id` é `int` obrigatório — incluir as calculadas aqui quebraria
    # a construção (`connection_id` delas é sempre `None`).
    tags_para_validacao = {
        tag.id: TagRef(
            id=tag.id, conn_id=tag.connection_id, direction=tag.direction, data_type=tag.data_type
        )
        for tag in tags_por_ref.values()
        if tag.connection_id is not None
    }

    # Camada 4 (§3.2-4): `parse_graph` + `validate_graph` por flow, com o mapa de tags
    # materializado pelo `flush()` acima. `grafo_para_banco` nunca levanta aqui: toda
    # `tag_ref` já foi conferida contra o próprio bundle na camada 3.
    #
    # `parse_graph`/`validate_graph` são CPU-bound sobre dados já materializados (funções
    # puras, thread-safe); `await asyncio.to_thread(...)` por flow (não um só para o bundle
    # inteiro) devolve o event loop entre flows — uvicorn é single-worker e o nginx roteia
    # `/api` e `/ws` para o mesmo processo, então um bundle grande sem isso congelava a IHM
    # inteira durante o import (TD-002).
    problemas_grafo: list[str] = []
    flows_novos: list[Flow] = []
    for bf in bundle.flows:
        graph_banco = grafo_para_banco(bf.graph, id_por_ref)
        try:
            resultado = await asyncio.to_thread(
                _parse_e_validar, graph_banco, tags_para_validacao, float(bf.ts_seconds)
            )
        except GraphParseError as exc:
            problemas_grafo.extend(f"fluxo '{bf.name}': {p}" for p in exc.errors)
            continue
        if resultado.errors:
            problemas_grafo.extend(f"fluxo '{bf.name}': {p}" for p in resultado.errors)
            continue
        flow = Flow(
            project_id=project.id,
            name=bf.name,
            ts_seconds=bf.ts_seconds,
            desired_state=bf.desired_state,
            graph_json=graph_banco,
            watchdog_enabled=bf.watchdog_enabled,
            watchdog_connection_id=(
                conexoes_por_nome[bf.watchdog_connection].id if bf.watchdog_connection else None
            ),
            watchdog_read_node_id=bf.watchdog_read_node_id,
            watchdog_write_node_id=bf.watchdog_write_node_id,
            watchdog_period_ms=bf.watchdog_period_ms,
            watchdog_timeout_s=bf.watchdog_timeout_s,
        )
        db.add(flow)
        flows_novos.append(flow)

    if problemas_grafo:
        await db.rollback()
        raise HTTPException(
            status_code=422,
            detail=formatar_problemas(problemas_grafo, cabecalho="Import recusado"),
        )

    await db.commit()
    await db.refresh(project)

    try:
        app_cert_exists = read_app_certificate(settings.certs_dir).exists
    except ValueError:
        # Certificado presente mas ilegível: para a pendência dá no mesmo que não existir —
        # o operador ainda precisa agir antes de confiar na conexão (não é o 500 de infra de
        # `GET /api/certificates/app`, que é sobre o certificado em si, não sobre o import).
        app_cert_exists = False

    pending_secrets = [
        pendencias_da_conexao(
            connection_name=bc.name,
            auth_mode=bc.auth_mode,
            has_password=False,  # senha nunca atravessa a fronteira (spec §2.3)
            security_policy=bc.security_policy,
            server_cert_file=None,  # idem — certificado do servidor nunca atravessa
            app_cert_exists=app_cert_exists,
        )
        for bc in bundle.connections
    ]

    # Depois do commit: evento sobre import que falhou (422/409 acima) poluiria a auditoria
    # com uma ação que não aconteceu (mesmo padrão de `export_project`).
    await publish_event(
        redis_client,
        severity="info",
        origin=f"user:{user.id}",
        message=f"Projeto '{project.name}' importado",
        kind=KIND_PROJECT_IMPORTED,
        payload={
            "project_id": project.id,
            "name": project.name,
            "connections": len(bundle.connections),
            "tags": len(bundle.tags),
            "flows": len(flows_novos),
        },
    )

    return ProjectImportOut(
        project=ProjectOut.model_validate(project), pending_secrets=pending_secrets
    )
