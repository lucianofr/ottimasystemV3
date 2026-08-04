import hashlib
import logging
import os
import stat
from datetime import timedelta
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID

from ottima_core import certs
from ottima_core.certs import (
    APP_CERT_COMMON_NAME,
    APP_CERT_KEY_SIZE,
    APP_CERT_VALIDITY_DAYS,
    APPLICATION_URI,
    app_cert_paths,
    generate_app_certificate,
    read_app_certificate,
    remove_server_certificate,
    store_server_certificate,
    trusted_cert_path,
)
from ottima_core.config import Settings


def _load_cert(certs_dir: Path) -> x509.Certificate:
    return x509.load_pem_x509_certificate(app_cert_paths(certs_dir).pem.read_bytes())


def test_geracao_cria_layout_do_volume(tmp_path):
    generate_app_certificate(tmp_path)
    paths = app_cert_paths(tmp_path)
    assert paths.pem == tmp_path / "app" / "ottima.pem"
    assert paths.key == tmp_path / "app" / "ottima.key"
    assert paths.der == tmp_path / "app" / "ottima.der"
    assert paths.pem.is_file()
    assert paths.key.is_file()
    assert paths.der.is_file()
    assert (tmp_path / "trusted").is_dir()


def test_parametros_do_certificado(tmp_path):
    generate_app_certificate(tmp_path)
    cert = _load_cert(tmp_path)
    public_key = cert.public_key()
    assert isinstance(public_key, rsa.RSAPublicKey)
    assert public_key.key_size == APP_CERT_KEY_SIZE
    assert cert.signature_hash_algorithm is not None
    assert cert.signature_hash_algorithm.name == "sha256"
    esperado = f"CN={APP_CERT_COMMON_NAME}"
    assert cert.subject.rfc4514_string() == esperado
    assert cert.issuer.rfc4514_string() == esperado
    assert cert.not_valid_after_utc - cert.not_valid_before_utc == timedelta(
        days=APP_CERT_VALIDITY_DAYS
    )


def test_san_uri_e_o_application_uri_do_client(tmp_path):
    generate_app_certificate(tmp_path)
    san = _load_cert(tmp_path).extensions.get_extension_for_class(x509.SubjectAlternativeName)
    assert san.value.get_values_for_type(x509.UniformResourceIdentifier) == [APPLICATION_URI]
    assert APPLICATION_URI == "urn:ottima:opc-worker"


def test_key_usage_critico_com_os_quatro_bits_da_spec(tmp_path):
    generate_app_certificate(tmp_path)
    ext = _load_cert(tmp_path).extensions.get_extension_for_class(x509.KeyUsage)
    assert ext.critical is True
    ku = ext.value
    assert ku.digital_signature is True
    assert ku.content_commitment is True  # nonRepudiation
    assert ku.key_encipherment is True
    assert ku.data_encipherment is True
    assert ku.key_agreement is False
    assert ku.key_cert_sign is False
    assert ku.crl_sign is False


def test_extended_key_usage_com_client_e_server_auth(tmp_path):
    generate_app_certificate(tmp_path)
    eku = _load_cert(tmp_path).extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
    assert set(eku) == {ExtendedKeyUsageOID.CLIENT_AUTH, ExtendedKeyUsageOID.SERVER_AUTH}


def test_basic_constraints_nao_ca_e_critico(tmp_path):
    generate_app_certificate(tmp_path)
    ext = _load_cert(tmp_path).extensions.get_extension_for_class(x509.BasicConstraints)
    assert ext.critical is True
    assert ext.value.ca is False


def test_segunda_geracao_sem_force_falha_e_preserva_os_arquivos(tmp_path):
    antes = generate_app_certificate(tmp_path)
    paths = app_cert_paths(tmp_path)
    chave_antes = paths.key.read_bytes()

    with pytest.raises(FileExistsError):
        generate_app_certificate(tmp_path)

    assert read_app_certificate(tmp_path).fingerprint_sha256 == antes.fingerprint_sha256
    assert paths.key.read_bytes() == chave_antes


def test_force_regenera_o_certificado(tmp_path):
    antes = generate_app_certificate(tmp_path)
    depois = generate_app_certificate(tmp_path, force=True)
    assert depois.fingerprint_sha256 != antes.fingerprint_sha256
    assert read_app_certificate(tmp_path).fingerprint_sha256 == depois.fingerprint_sha256


def test_export_der_corresponde_ao_pem(tmp_path):
    generate_app_certificate(tmp_path)
    paths = app_cert_paths(tmp_path)
    der_cert = x509.load_der_x509_certificate(paths.der.read_bytes())
    assert der_cert == _load_cert(tmp_path)


def test_read_app_certificate_em_diretorio_vazio(tmp_path):
    info = read_app_certificate(tmp_path)
    assert info.exists is False
    assert info.subject is None
    assert info.fingerprint_sha256 is None
    assert info.not_before is None
    assert info.not_after is None
    assert info.application_uri is None


def test_read_app_certificate_reflete_o_certificado_em_disco(tmp_path):
    generate_app_certificate(tmp_path)
    info = read_app_certificate(tmp_path)
    cert = _load_cert(tmp_path)
    assert info.exists is True
    assert info.subject == f"CN={APP_CERT_COMMON_NAME}"
    assert info.application_uri == APPLICATION_URI
    assert info.not_before is not None and info.not_after is not None
    assert info.not_before == cert.not_valid_before_utc
    assert info.not_after == cert.not_valid_after_utc
    assert info.not_before.utcoffset() == timedelta(0)
    assert info.not_after.utcoffset() == timedelta(0)


def test_read_app_certificate_rejeita_arquivo_corrompido(tmp_path):
    generate_app_certificate(tmp_path)
    app_cert_paths(tmp_path).pem.write_bytes(b"nao sou um certificado")
    with pytest.raises(ValueError, match="corrompido"):
        read_app_certificate(tmp_path)


def test_fingerprint_e_sha256_do_der_em_hex_minusculo(tmp_path):
    info = generate_app_certificate(tmp_path)
    der = app_cert_paths(tmp_path).der.read_bytes()
    assert info.fingerprint_sha256 == hashlib.sha256(der).hexdigest()


def test_chave_privada_tem_permissao_0600(tmp_path):
    generate_app_certificate(tmp_path)
    modo = stat.S_IMODE(app_cert_paths(tmp_path).key.stat().st_mode)
    assert modo == 0o600


def test_store_server_certificate_aceita_pem_e_der_e_grava_der(tmp_path):
    origem = tmp_path / "origem"
    generate_app_certificate(origem)
    pem_bytes = app_cert_paths(origem).pem.read_bytes()
    der_bytes = app_cert_paths(origem).der.read_bytes()
    destino = tmp_path / "certs"

    assert store_server_certificate(destino, 7, pem_bytes) == "conn-7.der"
    assert trusted_cert_path(destino, 7).read_bytes() == der_bytes

    assert store_server_certificate(destino, 8, der_bytes) == "conn-8.der"
    assert trusted_cert_path(destino, 8).read_bytes() == der_bytes


def test_store_server_certificate_rejeita_conteudo_invalido(tmp_path):
    with pytest.raises(ValueError, match="certificado"):
        store_server_certificate(tmp_path, 1, b"isto nao e um certificado")


def test_remove_server_certificate_indica_se_havia_arquivo(tmp_path):
    generate_app_certificate(tmp_path)
    der_bytes = app_cert_paths(tmp_path).der.read_bytes()
    store_server_certificate(tmp_path, 3, der_bytes)
    assert remove_server_certificate(tmp_path, 3) is True
    assert remove_server_certificate(tmp_path, 3) is False


def test_settings_certs_dir_default_e_override(monkeypatch):
    monkeypatch.delenv("OTTIMA_CERTS_DIR", raising=False)
    assert Settings(_env_file=None).certs_dir == Path("/certs")
    monkeypatch.setenv("OTTIMA_CERTS_DIR", "/tmp/ottima-certs")
    assert Settings(_env_file=None).certs_dir == Path("/tmp/ottima-certs")


def _falha_na_gravacao(_path, _data, _mode):
    raise OSError("disco cheio")


def test_falha_na_gravacao_preserva_o_certificado_anterior(tmp_path, monkeypatch):
    antes = generate_app_certificate(tmp_path)
    paths = app_cert_paths(tmp_path)
    conteudo_antes = {p: p.read_bytes() for p in (paths.pem, paths.key, paths.der)}
    original = certs._write_file
    chamadas = {"n": 0}

    def falha_na_terceira(path, data, mode):
        chamadas["n"] += 1
        if chamadas["n"] == 3:
            raise OSError("disco cheio")
        original(path, data, mode)

    monkeypatch.setattr(certs, "_write_file", falha_na_terceira)
    with pytest.raises(OSError):
        generate_app_certificate(tmp_path, force=True)

    assert {p: p.read_bytes() for p in conteudo_antes} == conteudo_antes
    assert read_app_certificate(tmp_path).fingerprint_sha256 == antes.fingerprint_sha256
    # Nenhum temporário sobrou no diretório.
    assert sorted(p.name for p in (tmp_path / "app").iterdir()) == [
        "ottima.der",
        "ottima.key",
        "ottima.pem",
    ]


def test_falha_na_gravacao_nao_deixa_arquivo_meio_gravado(tmp_path, monkeypatch):
    monkeypatch.setattr(certs, "_write_file", _falha_na_gravacao)
    with pytest.raises(OSError):
        generate_app_certificate(tmp_path)
    assert list((tmp_path / "app").iterdir()) == []
    assert read_app_certificate(tmp_path).exists is False


@pytest.mark.parametrize("conn_id", ["../../etc/x", -1, 1.0, True])
def test_conn_id_invalido_e_rejeitado_sem_escrever_nada(tmp_path, conn_id):
    with pytest.raises(ValueError, match="Identificador de conexão inválido"):
        trusted_cert_path(tmp_path, conn_id)
    with pytest.raises(ValueError, match="Identificador de conexão inválido"):
        store_server_certificate(tmp_path, conn_id, b"qualquer coisa")
    with pytest.raises(ValueError, match="Identificador de conexão inválido"):
        remove_server_certificate(tmp_path, conn_id)
    assert list(tmp_path.iterdir()) == []


def test_store_server_certificate_rejeita_pem_com_varios_certificados(tmp_path):
    origem = tmp_path / "origem"
    generate_app_certificate(origem)
    pem_bytes = app_cert_paths(origem).pem.read_bytes()
    generate_app_certificate(origem, force=True)
    outro_pem = app_cert_paths(origem).pem.read_bytes()

    destino = tmp_path / "certs"
    with pytest.raises(ValueError, match="um único certificado"):
        store_server_certificate(destino, 5, pem_bytes + outro_pem)
    assert not trusted_cert_path(destino, 5).exists()


def test_escrita_parcial_nao_deixa_temporario_orfao(tmp_path, monkeypatch):
    # ENOSPC real: o arquivo temporário chega a ser criado e fica pela metade.
    def cria_e_falha(path, data, mode):
        path.write_bytes(data[: len(data) // 2])
        raise OSError("disco cheio")

    monkeypatch.setattr(certs, "_write_file", cria_e_falha)
    with pytest.raises(OSError):
        generate_app_certificate(tmp_path)

    assert list((tmp_path / "app").iterdir()) == []
    assert read_app_certificate(tmp_path).exists is False


def test_escrita_parcial_no_ultimo_arquivo_limpa_todos_os_temporarios(tmp_path, monkeypatch):
    antes = generate_app_certificate(tmp_path)
    original = certs._write_file
    chamadas = {"n": 0}

    def falha_no_meio(path, data, mode):
        chamadas["n"] += 1
        if chamadas["n"] == 3:
            path.write_bytes(data[:10])
            raise OSError("disco cheio")
        original(path, data, mode)

    monkeypatch.setattr(certs, "_write_file", falha_no_meio)
    with pytest.raises(OSError):
        generate_app_certificate(tmp_path, force=True)

    assert sorted(p.name for p in (tmp_path / "app").iterdir()) == [
        "ottima.der",
        "ottima.key",
        "ottima.pem",
    ]
    assert read_app_certificate(tmp_path).fingerprint_sha256 == antes.fingerprint_sha256


def test_falha_na_promocao_registra_critico_com_remediacao(tmp_path, monkeypatch, caplog):
    generate_app_certificate(tmp_path)
    original = os.replace
    chamadas = {"n": 0}

    def falha_no_segundo_rename(src, dst):
        chamadas["n"] += 1
        if chamadas["n"] == 2:
            raise OSError("rename falhou")
        original(src, dst)

    monkeypatch.setattr(os, "replace", falha_no_segundo_rename)
    with caplog.at_level(logging.CRITICAL):
        with pytest.raises(OSError):
            generate_app_certificate(tmp_path, force=True)

    mensagem = next(r.getMessage() for r in caplog.records if r.levelno == logging.CRITICAL)
    assert "ottima.pem" in mensagem and "ottima.key" in mensagem
    assert "force=true" in mensagem
    # Sem rollback (decisão registrada), mas nada de temporário sobra no diretório.
    assert sorted(p.name for p in (tmp_path / "app").iterdir()) == [
        "ottima.der",
        "ottima.key",
        "ottima.pem",
    ]
