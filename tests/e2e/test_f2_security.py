"""Camada L2 da F2 (spec §11.2): canal seguro Basic256Sha256 com pinning obrigatório.

Cenário E2E-F2-07 contra o compose real (RF-201/202, ADR-021).
"""

import httpx
import pytest

from ottima_core.bus import KIND_COMM_FAILURE

from .conftest import (
    OPCSIM_CERT,
    Ambiente,
    EventStream,
    esperar_conexao,
    evento_de,
)

pytestmark = pytest.mark.e2e


def _garantir_certificado_de_aplicacao(admin: httpx.Client) -> None:
    """O canal seguro exige a identidade do worker (spec §5.3); 409 = já existe."""
    r = admin.post("/api/certificates/app/generate")
    assert r.status_code in (201, 409), f"geração do cert do app falhou: HTTP {r.status_code}"


def test_e2e_f2_07_canal_seguro_exige_pinning(
    admin: httpx.Client, projeto_com_conexao: Ambiente, eventos: EventStream
) -> None:
    """Sem o certificado do servidor a conexão falha com `cert_missing`; com ele, sobe."""
    conn_id = projeto_com_conexao.conn_id
    _garantir_certificado_de_aplicacao(admin)
    esperar_conexao(conn_id)

    r = admin.patch(
        f"/api/connections/{conn_id}",
        json={"security_policy": "basic256sha256", "security_mode": "sign"},
    )
    assert r.status_code == 200, f"PATCH para sign falhou: HTTP {r.status_code} {r.text}"
    falha = eventos.esperar(
        evento_de(KIND_COMM_FAILURE, conn_id),
        timeout=90.0,
        descricao="comm_failure ao subir canal seguro sem o certificado do servidor",
    )
    assert falha["payload"]["reason"] == "cert_missing"

    assert OPCSIM_CERT.exists(), f"certificado do opcsim ausente em {OPCSIM_CERT}"
    r = admin.post(
        f"/api/connections/{conn_id}/server-certificate",
        content=OPCSIM_CERT.read_bytes(),
        headers={"Content-Type": "application/pkix-cert"},
    )
    assert r.status_code == 200, f"upload do certificado falhou: HTTP {r.status_code} {r.text}"
    em_sign = esperar_conexao(conn_id, timeout=120.0)

    r = admin.patch(f"/api/connections/{conn_id}", json={"security_mode": "sign_and_encrypt"})
    assert r.status_code == 200, f"PATCH para sign_and_encrypt falhou: HTTP {r.status_code}"
    esperar_conexao(
        conn_id,
        session_up_since_diferente_de=em_sign["session_up_since"],
        timeout=120.0,
    )

    # O arquivo pinado vive no volume `certs` e não sai pelo CASCADE do projeto.
    assert admin.delete(f"/api/connections/{conn_id}/server-certificate").status_code == 204
