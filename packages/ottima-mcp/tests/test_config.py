"""Config.do_ambiente: sem defaults mágicos, falta de qualquer variável é erro de partida."""

import pytest

from ottima_mcp.config import Config, ConfiguracaoAusente

_ENVS = {
    "OTTIMA_URL": "http://localhost:8080",
    "OTTIMA_MCP_USERNAME": "agente",
    "OTTIMA_MCP_PASSWORD": "segredo",
}


def _setar(monkeypatch: pytest.MonkeyPatch, **overrides: str | None) -> None:
    valores = {**_ENVS, **overrides}
    for nome, valor in valores.items():
        if valor is None:
            monkeypatch.delenv(nome, raising=False)
        else:
            monkeypatch.setenv(nome, valor)


def test_le_as_tres_variaveis_do_ambiente(monkeypatch: pytest.MonkeyPatch) -> None:
    _setar(monkeypatch)
    config = Config.do_ambiente()
    assert config == Config(url="http://localhost:8080", username="agente", password="segredo")


def test_normaliza_url_removendo_barra_final(monkeypatch: pytest.MonkeyPatch) -> None:
    _setar(monkeypatch, OTTIMA_URL="http://localhost:8080/")
    assert Config.do_ambiente().url == "http://localhost:8080"


@pytest.mark.parametrize(
    "nome_ausente", ["OTTIMA_URL", "OTTIMA_MCP_USERNAME", "OTTIMA_MCP_PASSWORD"]
)
def test_falta_de_qualquer_variavel_e_erro_de_partida(
    monkeypatch: pytest.MonkeyPatch, nome_ausente: str
) -> None:
    _setar(monkeypatch, **{nome_ausente: None})
    with pytest.raises(ConfiguracaoAusente, match=nome_ausente):
        Config.do_ambiente()


def test_variavel_vazia_conta_como_ausente(monkeypatch: pytest.MonkeyPatch) -> None:
    _setar(monkeypatch, OTTIMA_MCP_PASSWORD="")
    with pytest.raises(ConfiguracaoAusente, match="OTTIMA_MCP_PASSWORD"):
        Config.do_ambiente()
