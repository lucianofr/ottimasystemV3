"""Tradução pt-BR de erros de validação do Pydantic (spec F5 §4.3-1, decisão A-9).

Módulo próprio (tarefa 0.5) porque a tarefa 2.1 (import de projeto) precisa da mesma
tradução num router, e um router importando de `app.py` fecharia ciclo (`app.py`
importa `ottima_api.ws` no topo).
"""

from collections.abc import Sequence
from typing import Any

from pydantic import ValidationError

# Motivo pt-BR por `type` de erro do Pydantic v2 (spec F5 §4.3-1, decisão A-9, dívida F4).
# Cobre os tipos que aparecem nos schemas do serviço (Literal, Field(min_length=...),
# Field(ge=/le=...), campo obrigatório, `model_validator` com `ValueError` pt-BR já pronto)
# e `json_invalid`, do corpo malformado antes mesmo de chegar ao schema.
_MOTIVO_POR_TIPO = {
    "missing": lambda erro: "campo obrigatório",
    "string_too_short": lambda erro: f"mínimo de {erro['ctx']['min_length']} caractere(s)",
    "string_too_long": lambda erro: f"máximo de {erro['ctx']['max_length']} caractere(s)",
    "greater_than_equal": lambda erro: f"deve ser maior ou igual a {erro['ctx']['ge']}",
    "less_than_equal": lambda erro: f"deve ser menor ou igual a {erro['ctx']['le']}",
    "greater_than": lambda erro: f"deve ser maior que {erro['ctx']['gt']}",
    "less_than": lambda erro: f"deve ser menor que {erro['ctx']['lt']}",
    "int_parsing": lambda erro: "deve ser um número inteiro",
    "int_type": lambda erro: "deve ser um número inteiro",
    "float_parsing": lambda erro: "deve ser um número",
    "float_type": lambda erro: "deve ser um número",
    "bool_parsing": lambda erro: "deve ser verdadeiro ou falso",
    "bool_type": lambda erro: "deve ser verdadeiro ou falso",
    "string_type": lambda erro: "deve ser um texto",
    "json_invalid": lambda erro: "corpo JSON inválido",
}


def traduzir_erro_de_validacao(erro: dict[str, Any]) -> str:
    """`{loc, msg, type, ctx}` do Pydantic vira `"<campo>: <motivo pt-BR>"` (formato exato
    da spec F5 §4.3-1). `value_error` (de `model_validator`) já é pt-BR: só remove o prefixo
    "Value error, " que o Pydantic adiciona. `literal_error` (Literal/enum) traduz a lista de
    opções. Tipo desconhecido cai na mensagem original do Pydantic (defensivo; nenhum schema
    do serviço produz outro tipo hoje)."""
    campo = ".".join(str(parte) for parte in erro["loc"])
    if erro["type"] == "value_error":
        motivo = str(erro["ctx"]["error"])
    elif erro["type"] == "literal_error":
        opcoes = erro["ctx"]["expected"].replace("'", "").replace(" or ", ", ")
        motivo = f"valor inválido; esperado um de: {opcoes}"
    else:
        motivo = _MOTIVO_POR_TIPO.get(erro["type"], lambda e: e["msg"])(erro)
    return f"{campo}: {motivo}"


def problemas_de_validacao(exc: ValidationError, *, prefixo: str = "") -> list[str]:
    """Todos os erros de `exc.errors()` traduzidos e formatados como `"<caminho>:
    <motivo pt-BR>"` (reusa `traduzir_erro_de_validacao`, não reimplementa a tradução).
    `prefixo` antepõe o caminho quando o erro vem de um schema validado isoladamente
    dentro de uma estrutura maior (ex.: `"connections[2]."` no import de bundle, tarefa
    2.3) — a função só concatena, quem chama decide o separador."""
    return [f"{prefixo}{traduzir_erro_de_validacao(erro)}" for erro in exc.errors()]


def formatar_problemas(problemas: Sequence[str], *, cabecalho: str) -> str:
    """Agrega uma lista de problemas na string única do 422 (spec §3.2-5, decisão A-5):
    `"<cabecalho> (N problemas) | p1 | p2 | … | e mais N"`. Separador ` | ` (nunca `;`,
    que aparece dentro de `node_id` OPC-UA como `ns=2;s=TT101`, UX-06); teto de 10
    problemas exibidos, com o total real sempre no cabeçalho. `cabecalho` não é fixado
    aqui porque `"Import recusado"` é normativo (§3.2-5) e `"Export recusado"` não."""
    exibidos = problemas[:10]
    excedente = len(problemas) - len(exibidos)
    sufixo = f" | e mais {excedente}" if excedente > 0 else ""
    return f"{cabecalho} ({len(problemas)} problemas) | {' | '.join(exibidos)}{sufixo}"
