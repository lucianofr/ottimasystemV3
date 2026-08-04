"""API de certificados (RF-202, ADR-021): app cert de instância e trust por conexão."""

import hashlib

import pytest
from cryptography import x509
from sqlalchemy import event, select

from ottima_api.routers.connections import _excede_o_declarado
from ottima_core.certs import APPLICATION_URI, app_cert_paths, generate_app_certificate
from ottima_core.certs import trusted_cert_path as caminho_confiado
from ottima_core.models import OpcConnection

GERAR = "/api/certificates/app/generate"
APP = "/api/certificates/app"
EXPORT = "/api/certificates/app/export"
LIMITE = 64 * 1024


@pytest.fixture
def certs_dir(test_settings):
    """Mesmo diretório temporário que o app enxerga (conftest aponta certs_dir p/ tmp_path)."""
    return test_settings.certs_dir


@pytest.fixture
async def updates_na_conexao(db_session):
    """Statements UPDATE emitidos em `opc_connections` na sessão do teste.

    É o observável que importa para o watermark: o `onupdate` do `updated_at` só dispara se o
    ORM de fato emitir um UPDATE para a linha.
    """
    sync_conn = (await db_session.connection()).sync_connection
    vistos: list[str] = []

    def _spy(conn, cursor, statement, parameters, context, executemany):
        if "UPDATE opc_connections" in statement:
            vistos.append(statement)

    event.listen(sync_conn, "before_cursor_execute", _spy)
    yield vistos
    event.remove(sync_conn, "before_cursor_execute", _spy)


async def _admin_id(client, headers) -> int:
    return (await client.get("/api/auth/me", headers=headers)).json()["id"]


async def _projeto_da(client, headers, conn_id: int) -> int:
    r = await client.get(f"/api/connections/{conn_id}", headers=headers)
    return r.json()["project_id"]


@pytest.fixture
def cert_servidor(tmp_path):
    """PEM e DER de um certificado real, gerado fora do certs_dir: faz papel do servidor."""
    origem = tmp_path / "origem-servidor"
    generate_app_certificate(origem)
    paths = app_cert_paths(origem)
    return paths.pem.read_bytes(), paths.der.read_bytes()


async def _conexao(client, headers, name: str) -> int:
    r = await client.post("/api/projects", json={"name": f"Proj {name}"}, headers=headers)
    pid = r.json()["id"]
    r = await client.post(
        "/api/connections",
        json={"project_id": pid, "name": name, "endpoint": "opc.tcp://10.0.0.9:4840"},
        headers=headers,
    )
    assert r.status_code == 201
    return r.json()["id"]


def _bruto(headers: dict) -> dict:
    return {**headers, "Content-Type": "application/octet-stream"}


async def _coluna(db_session, conn_id: int) -> str | None:
    conn = await db_session.scalar(select(OpcConnection).where(OpcConnection.id == conn_id))
    return conn.server_cert_file


def _digest(caminho) -> str:
    return hashlib.sha256(caminho.read_bytes()).hexdigest()


async def test_generate_cria_os_tres_arquivos_no_layout(client, admin_headers, certs_dir):
    r = await client.post(GERAR, headers=admin_headers)  # sem corpo: force default é false
    assert r.status_code == 201
    body = r.json()
    assert body["exists"] is True
    assert body["warning"] is None
    assert body["application_uri"] == APPLICATION_URI
    assert body["not_before"] < body["not_after"]  # janela de validade coerente
    paths = app_cert_paths(certs_dir)
    assert (paths.pem, paths.key, paths.der) == (
        certs_dir / "app" / "ottima.pem",
        certs_dir / "app" / "ottima.key",
        certs_dir / "app" / "ottima.der",
    )
    assert paths.pem.exists() and paths.key.exists() and paths.der.exists()
    assert body["fingerprint_sha256"] == _digest(paths.der)


async def test_get_app_reflete_o_certificado_gerado(client, admin_headers):
    gerado = (await client.post(GERAR, headers=admin_headers)).json()
    r = await client.get(APP, headers=admin_headers)
    assert r.status_code == 200
    assert r.json() == {k: v for k, v in gerado.items() if k != "warning"}


async def test_get_app_sem_certificado_nao_e_erro(client, admin_headers):
    r = await client.get(APP, headers=admin_headers)
    assert r.status_code == 200
    assert r.json() == {
        "exists": False,
        "subject": None,
        "fingerprint_sha256": None,
        "not_before": None,
        "not_after": None,
        "application_uri": None,
    }


async def test_segundo_generate_sem_force_conflita_e_preserva_o_certificado(
    client, admin_headers, certs_dir
):
    await client.post(GERAR, headers=admin_headers)
    antes = _digest(app_cert_paths(certs_dir).der)
    r = await client.post(GERAR, json={"force": False}, headers=admin_headers)
    assert r.status_code == 409
    assert "force" in r.json()["detail"]
    assert _digest(app_cert_paths(certs_dir).der) == antes


async def test_force_substitui_o_certificado_e_avisa_sobre_re_trust(
    client, admin_headers, certs_dir
):
    primeiro = (await client.post(GERAR, headers=admin_headers)).json()
    r = await client.post(GERAR, json={"force": True}, headers=admin_headers)
    assert r.status_code == 201
    body = r.json()
    assert body["fingerprint_sha256"] != primeiro["fingerprint_sha256"]
    assert body["fingerprint_sha256"] == _digest(app_cert_paths(certs_dir).der)
    assert "re-trust" in body["warning"]
    assert "servidores OPC-UA" in body["warning"]


async def test_export_devolve_der_parseavel_com_header_de_download(client, admin_headers):
    gerado = (await client.post(GERAR, headers=admin_headers)).json()
    r = await client.get(EXPORT, headers=admin_headers)
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pkix-cert"
    assert r.headers["content-disposition"] == 'attachment; filename="ottima.der"'
    cert = x509.load_der_x509_certificate(r.content)
    assert cert.subject.rfc4514_string() == gerado["subject"]
    assert hashlib.sha256(r.content).hexdigest() == gerado["fingerprint_sha256"]


async def test_export_sem_certificado_404(client, admin_headers):
    r = await client.get(EXPORT, headers=admin_headers)
    assert r.status_code == 404
    assert "não foi gerado" in r.json()["detail"]


@pytest.mark.parametrize("formato", ["pem", "der"])
async def test_upload_pem_e_der_gravam_sempre_der(
    client, admin_headers, db_session, certs_dir, cert_servidor, formato
):
    pem, der = cert_servidor
    cid = await _conexao(client, admin_headers, f"plc-{formato}")
    r = await client.post(
        f"/api/connections/{cid}/server-certificate",
        content=pem if formato == "pem" else der,
        headers=_bruto(admin_headers),
    )
    assert r.status_code == 200
    assert r.json() == {
        "conn_id": cid,
        "server_cert_file": f"conn-{cid}.der",
        "fingerprint_sha256": hashlib.sha256(der).hexdigest(),
    }
    caminho = caminho_confiado(certs_dir, cid)
    assert caminho == certs_dir / "trusted" / f"conn-{cid}.der"
    assert caminho.read_bytes() == der  # PEM entrou, DER ficou no disco
    assert await _coluna(db_session, cid) == f"conn-{cid}.der"


async def test_upload_de_conteudo_que_nao_e_certificado_422_e_nao_grava(
    client, admin_headers, db_session, certs_dir
):
    cid = await _conexao(client, admin_headers, "plc-invalido")
    r = await client.post(
        f"/api/connections/{cid}/server-certificate",
        content=b"isto nao e um certificado X.509",
        headers=_bruto(admin_headers),
    )
    assert r.status_code == 422
    assert not caminho_confiado(certs_dir, cid).exists()
    assert await _coluna(db_session, cid) is None


async def test_upload_de_pem_com_dois_certificados_422(
    client, admin_headers, db_session, certs_dir, cert_servidor, tmp_path
):
    pem, _ = cert_servidor
    generate_app_certificate(tmp_path / "segundo")
    pem2 = app_cert_paths(tmp_path / "segundo").pem.read_bytes()
    cid = await _conexao(client, admin_headers, "plc-dois")
    r = await client.post(
        f"/api/connections/{cid}/server-certificate",
        content=pem + pem2,
        headers=_bruto(admin_headers),
    )
    assert r.status_code == 422
    assert "único certificado" in r.json()["detail"]
    assert not caminho_confiado(certs_dir, cid).exists()
    assert await _coluna(db_session, cid) is None


async def test_upload_em_conexao_inexistente_404(client, admin_headers, certs_dir, cert_servidor):
    _, der = cert_servidor
    r = await client.post(
        "/api/connections/999999/server-certificate",
        content=der,
        headers=_bruto(admin_headers),
    )
    assert r.status_code == 404
    assert not caminho_confiado(certs_dir, 999999).exists()


async def test_upload_acima_de_64_kib_413_e_nao_grava(client, admin_headers, db_session, certs_dir):
    cid = await _conexao(client, admin_headers, "plc-grande")
    r = await client.post(
        f"/api/connections/{cid}/server-certificate",
        content=b"x" * (LIMITE + 1),
        headers=_bruto(admin_headers),
    )
    assert r.status_code == 413
    assert not caminho_confiado(certs_dir, cid).exists()
    assert await _coluna(db_session, cid) is None
    # Exatamente no teto ainda passa pelo tamanho e só então falha pelo conteúdo
    r = await client.post(
        f"/api/connections/{cid}/server-certificate",
        content=b"x" * LIMITE,
        headers=_bruto(admin_headers),
    )
    assert r.status_code == 422


async def test_delete_remove_arquivo_zera_coluna_e_repete_sem_erro(
    client, admin_headers, db_session, certs_dir, cert_servidor
):
    _, der = cert_servidor
    cid = await _conexao(client, admin_headers, "plc-del")
    await client.post(
        f"/api/connections/{cid}/server-certificate", content=der, headers=_bruto(admin_headers)
    )
    assert caminho_confiado(certs_dir, cid).exists()
    r = await client.delete(f"/api/connections/{cid}/server-certificate", headers=admin_headers)
    assert r.status_code == 204
    assert not caminho_confiado(certs_dir, cid).exists()
    assert await _coluna(db_session, cid) is None
    r = await client.delete(f"/api/connections/{cid}/server-certificate", headers=admin_headers)
    assert r.status_code == 204  # idempotente


async def test_delete_em_conexao_inexistente_404(client, admin_headers):
    r = await client.delete("/api/connections/999999/server-certificate", headers=admin_headers)
    assert r.status_code == 404


async def test_operador_recebe_403_em_todos_os_endpoints(
    client, admin_headers, operator_headers, certs_dir, cert_servidor
):
    _, der = cert_servidor
    cid = await _conexao(client, admin_headers, "plc-rbac")
    codigos = [
        (await client.post(GERAR, json={"force": True}, headers=operator_headers)).status_code,
        (await client.get(APP, headers=operator_headers)).status_code,
        (await client.get(EXPORT, headers=operator_headers)).status_code,
        (
            await client.post(
                f"/api/connections/{cid}/server-certificate",
                content=der,
                headers=_bruto(operator_headers),
            )
        ).status_code,
        (
            await client.delete(
                f"/api/connections/{cid}/server-certificate", headers=operator_headers
            )
        ).status_code,
    ]
    assert codigos == [403] * 5
    assert not app_cert_paths(certs_dir).pem.exists()
    assert not caminho_confiado(certs_dir, cid).exists()


async def test_sem_token_recebe_401_em_todos_os_endpoints(
    client, admin_headers, certs_dir, cert_servidor
):
    _, der = cert_servidor
    cid = await _conexao(client, admin_headers, "plc-anon")
    codigos = [
        (await client.post(GERAR, json={"force": True})).status_code,
        (await client.get(APP)).status_code,
        (await client.get(EXPORT)).status_code,
        (
            await client.post(
                f"/api/connections/{cid}/server-certificate",
                content=der,
                headers={"Content-Type": "application/octet-stream"},
            )
        ).status_code,
        (await client.delete(f"/api/connections/{cid}/server-certificate")).status_code,
    ]
    assert codigos == [401] * 5
    assert not app_cert_paths(certs_dir).pem.exists()
    assert not caminho_confiado(certs_dir, cid).exists()


async def test_upload_emite_connection_updated(client, admin_headers, eventos, cert_servidor):
    """`server_cert_file` também é campo do PATCH: as duas rotas têm de auditar igual."""
    _, der = cert_servidor
    uid = await _admin_id(client, admin_headers)
    cid = await _conexao(client, admin_headers, "plc-evento")
    pid = await _projeto_da(client, admin_headers, cid)
    await eventos()  # descarta o connection_created do setup

    r = await client.post(
        f"/api/connections/{cid}/server-certificate", content=der, headers=_bruto(admin_headers)
    )
    assert r.status_code == 200
    (evento,) = await eventos()
    assert evento["severity"] == "info"
    assert evento["origin"] == f"user:{uid}"
    assert evento["payload"] == {
        "kind": "connection_updated",
        "conn_id": cid,
        "project_id": pid,
        "name": "plc-evento",
    }


async def test_delete_emite_connection_updated_so_quando_muda_estado(
    client, admin_headers, eventos, cert_servidor
):
    _, der = cert_servidor
    uid = await _admin_id(client, admin_headers)
    cid = await _conexao(client, admin_headers, "plc-evento-del")
    pid = await _projeto_da(client, admin_headers, cid)
    await client.post(
        f"/api/connections/{cid}/server-certificate", content=der, headers=_bruto(admin_headers)
    )
    await eventos()  # descarta created + updated do setup

    r = await client.delete(f"/api/connections/{cid}/server-certificate", headers=admin_headers)
    assert r.status_code == 204
    (evento,) = await eventos()
    assert evento["severity"] == "info"
    assert evento["origin"] == f"user:{uid}"
    assert evento["payload"] == {
        "kind": "connection_updated",
        "conn_id": cid,
        "project_id": pid,
        "name": "plc-evento-del",
    }

    # Segundo DELETE não muda nem arquivo nem coluna: 204, mas no-op não é evento
    r = await client.delete(f"/api/connections/{cid}/server-certificate", headers=admin_headers)
    assert r.status_code == 204
    assert await eventos() == []


async def test_upload_que_falha_nao_emite(client, admin_headers, eventos):
    cid = await _conexao(client, admin_headers, "plc-falha-ev")
    await eventos()
    r = await client.post(
        f"/api/connections/{cid}/server-certificate",
        content=b"isto nao e um certificado",
        headers=_bruto(admin_headers),
    )
    assert r.status_code == 422
    assert await eventos() == []


async def test_substituir_certificado_emite_update_de_updated_at(
    client, admin_headers, cert_servidor, tmp_path, updates_na_conexao
):
    """Regressão (achado da 1.4): o nome do arquivo é sempre `conn-<id>.der`.

    Substituir o certificado deixa a coluna com valor idêntico. Sem o `flag_modified` o ORM
    não marca o objeto sujo, nenhum UPDATE é emitido, o `onupdate` do TimestampMixin não
    dispara e o watermark do supervisor (spec §2.2-1) fica parado — a sessão OPC seguiria com
    o certificado antigo em memória para sempre.

    O que se afirma aqui é o UPDATE com `updated_at` no SET, e não o valor do timestamp: o
    `now()` do Postgres é fixo dentro de uma transação, e a fixture de teste roda tudo em uma
    só (SAVEPOINT), então o valor não teria como avançar nem com o código correto.
    """
    _, der_a = cert_servidor
    generate_app_certificate(tmp_path / "servidor-b")
    der_b = app_cert_paths(tmp_path / "servidor-b").der.read_bytes()
    assert der_a != der_b

    cid = await _conexao(client, admin_headers, "plc-retrust")
    url = f"/api/connections/{cid}/server-certificate"

    primeiro = await client.post(url, content=der_a, headers=_bruto(admin_headers))
    assert primeiro.status_code == 200

    updates_na_conexao.clear()  # só interessa o que a SUBSTITUIÇÃO emite
    segundo = await client.post(url, content=der_b, headers=_bruto(admin_headers))
    assert segundo.status_code == 200

    # Mesmo nome de arquivo, certificado diferente no disco...
    depois = (await client.get(f"/api/connections/{cid}", headers=admin_headers)).json()
    assert depois["server_cert_file"] == f"conn-{cid}.der"
    assert primeiro.json()["fingerprint_sha256"] != segundo.json()["fingerprint_sha256"]
    assert segundo.json()["fingerprint_sha256"] == hashlib.sha256(der_b).hexdigest()
    # ...e ainda assim o UPDATE sai, carregando o updated_at que move o watermark
    assert len(updates_na_conexao) == 1
    assert "updated_at" in updates_na_conexao[0]


async def test_delete_emite_update_de_updated_at(
    client, admin_headers, cert_servidor, updates_na_conexao
):
    """O DELETE muda o valor da coluna de fato, mas verificar é mais barato que assumir."""
    _, der = cert_servidor
    cid = await _conexao(client, admin_headers, "plc-del-bump")
    url = f"/api/connections/{cid}/server-certificate"
    await client.post(url, content=der, headers=_bruto(admin_headers))

    updates_na_conexao.clear()
    assert (await client.delete(url, headers=admin_headers)).status_code == 204
    depois = (await client.get(f"/api/connections/{cid}", headers=admin_headers)).json()
    assert depois["server_cert_file"] is None
    assert len(updates_na_conexao) == 1
    assert "updated_at" in updates_na_conexao[0]

    # DELETE que não muda estado não emite UPDATE nenhum (nem evento, nem watermark)
    updates_na_conexao.clear()
    assert (await client.delete(url, headers=admin_headers)).status_code == 204
    assert updates_na_conexao == []


async def test_get_app_com_pem_corrompido_devolve_500_em_pt_br(client, admin_headers, certs_dir):
    """Arquivo presente mas ilegível é falha de infra: 500, mas mapeado e em pt-BR.

    Sem o mapeamento o ValueError do core sobe cru e vira o 500 genérico do framework, em
    inglês e sem dizer o que fazer.
    """
    pem = app_cert_paths(certs_dir).pem
    pem.parent.mkdir(parents=True, exist_ok=True)
    pem.write_bytes(b"isto nao e um PEM")

    r = await client.get(APP, headers=admin_headers)
    assert r.status_code == 500
    detail = r.json()["detail"]
    assert "ilegível" in detail or "corrompido" in detail
    assert "force=true" in detail  # diz qual é a saída


async def test_upload_sem_content_length_confiavel_413_e_para_de_ler_cedo(
    client, admin_headers, db_session, certs_dir
):
    """Corpo grande sem Content-Length honesto: 413 sem materializar o corpo inteiro.

    O corpo vai por um gerador (httpx manda chunked, sem Content-Length), então a única
    barreira é a contagem dos bytes lidos. Provar o 413 não basta: `await request.body()`
    também daria 413, depois de bufferizar tudo. O que se afirma aqui é que o gerador NÃO foi
    drenado — a leitura parou no primeiro chunk que cruzou o teto.
    """
    cid = await _conexao(client, admin_headers, "plc-stream")
    chunk = 8192
    total_chunks = 64  # 512 KiB, oito vezes o teto
    enviados = 0

    async def corpo():
        nonlocal enviados
        for _ in range(total_chunks):
            enviados += 1
            yield b"x" * chunk

    r = await client.post(
        f"/api/connections/{cid}/server-certificate",
        content=corpo(),
        headers={**admin_headers, "Content-Type": "application/octet-stream"},
    )
    assert r.status_code == 413
    assert enviados < total_chunks  # não drenou o corpo
    assert enviados <= LIMITE // chunk + 1  # teto mais um chunk, nada além
    assert not caminho_confiado(certs_dir, cid).exists()
    assert await _coluna(db_session, cid) is None


async def test_content_length_com_digitos_demais_nao_vira_500(
    client, admin_headers, db_session, certs_dir, cert_servidor
):
    """Header é entrada de usuário: o CPython recusa int() acima de 4300 dígitos (achado da 4.3).

    Sem a contagem de dígitos antes da conversão, este header vira ValueError não tratado = 500.
    """
    _, der = cert_servidor
    cid = await _conexao(client, admin_headers, "plc-cl-absurdo")
    r = await client.post(
        f"/api/connections/{cid}/server-certificate",
        content=der,
        headers={
            **admin_headers,
            "Content-Type": "application/octet-stream",
            "Content-Length": "9" * 4301,
        },
    )
    assert r.status_code == 413
    assert not caminho_confiado(certs_dir, cid).exists()
    assert await _coluna(db_session, cid) is None


@pytest.mark.parametrize(
    ("declarado", "excede"),
    [
        ("1200", False),
        ("65536", False),  # exatamente o teto passa
        ("65537", True),
        ("0000065536", False),  # zeros à esquerda não inflam a contagem de dígitos
        ("0", False),
        ("999999", True),  # mais dígitos que o teto: barrado sem converter
        ("9" * 4301, True),  # acima do limite de 4300 dígitos do int()
        ("²", False),  # isdigit() é True, isdecimal() é False
        ("abc", False),
        ("", False),
        (None, False),
    ],
)
def test_guard_de_content_length_classifica_sem_nunca_levantar(declarado, excede):
    assert _excede_o_declarado(declarado) is excede
