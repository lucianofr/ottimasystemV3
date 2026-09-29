"""Schemas de variável historiada (RF-308, ADR-041): porta de bloco gravada em `samples`.

Validação de existência (flow, bloco, porta e a regra de porta de entrada sem aresta, D7)
fica fora daqui — é responsabilidade do router (`ottima_api/routers/historized_vars.py`),
que tem o grafo do flow já parseado.
"""

from pydantic import BaseModel, Field


class HistorizedVarCreate(BaseModel):
    flow_id: int
    block_id: str = Field(min_length=1)
    port: str = Field(min_length=1)
    eu: str = ""


class HistorizedVarOut(BaseModel):
    """Montado pelo router a partir de `HistorizedVar` + `Tag` — não é `from_attributes`
    porque `name`/`eu` vêm da linha de `tags`, não da própria `historized_vars` (D1)."""

    tag_id: int
    flow_id: int
    block_id: str
    port: str
    name: str
    eu: str
