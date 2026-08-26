"""Regressão: o simulador OPC-UA não pode voltar para a stack de deploy.

O opc-worker é só cliente OPC-UA (spec F2 §2.2); o simulador que alimentava os
testes é dev-only e saiu da stack — quando um simulador for necessário, ele roda
fora do ottima (processo standalone no host, como a suíte e2e já faz), nunca como
serviço do compose.
"""

import re
from pathlib import Path

DEPLOY = Path(__file__).resolve().parents[1] / "deploy"
_SERVICO = re.compile(r"^  opcsim:$")


def _arquivos_compose() -> list[Path]:
    return sorted(DEPLOY.glob("docker-compose*.yml"))


def test_compose_sem_servico_opcsim() -> None:
    """Nenhum arquivo de compose do deploy pode declarar o serviço `opcsim`."""
    arquivos = _arquivos_compose()
    assert arquivos, "nenhum docker-compose*.yml em deploy/"
    for arquivo in arquivos:
        for numero, linha in enumerate(arquivo.read_text().splitlines(), start=1):
            assert not _SERVICO.match(linha), (
                f"{arquivo.relative_to(DEPLOY.parent)}:{numero}: serviço 'opcsim' "
                "voltou para a stack — simulador é dev-only, fora do compose"
            )
