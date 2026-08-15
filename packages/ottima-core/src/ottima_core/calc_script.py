"""Validação de conteúdo de script de tag calculada (RF-208, ADR-033 §3): função única
compartilhada entre o CRUD (`services/api/.../routers/calculated_tags.py`) e o import de
projeto (`ottima_core.portability.bundle`).

Antes desta extração, o CRUD validava (`check_script_code`, `compile`, atribuição de `OUT`,
alcance de `IN<n>`) e o import não rodava NENHUMA das quatro checagens — um bundle podia
persistir código com a fuga clássica de sandbox (`().__class__.__base__.__subclasses__()`)
ou até sintaticamente inválido, sem o 422 que o CRUD sempre deu para o mesmo conteúdo
(achado crítico da revisão de fase 5, ADR-033).

Puro: nenhuma dependência de banco, Redis ou disco.
"""

from __future__ import annotations

import ast
import re

from ottima_core.flowgraph import check_script_code

_IN_NAME = re.compile(r"^IN(\d+)$")


def _atribui_out(tree: ast.AST) -> bool:
    """`OUT` como alvo de `Assign`/`AugAssign`/`AnnAssign`/`:=` — qualquer `ast.Name` 'OUT'
    em contexto `Store` cobre os quatro, inclusive dentro de um alvo em tupla."""
    return any(
        isinstance(node, ast.Name) and node.id == "OUT" and isinstance(node.ctx, ast.Store)
        for node in ast.walk(tree)
    )


def _posicoes_in_lidas(tree: ast.AST) -> set[int]:
    """Posições `IN<n>` referenciadas em contexto `Load` (o que o script LÊ) — é isso que
    estoura depois de remover uma entrada, não o que ele porventura atribui."""
    posicoes: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            m = _IN_NAME.match(node.id)
            if m:
                posicoes.add(int(m.group(1)))
    return posicoes


def problemas_do_script(code: str, n_inputs: int) -> list[str]:
    """Camada de conteúdo do script de uma tag calculada, nesta ordem: (1) `check_script_code`
    (recusa de nomes dunder, TD-001/ADR-018), (2) `compile()` (sintaxe), (3) atribuição de
    `OUT`, (4) alcance de `IN<n>`. A mesma ordem que o CRUD sempre impôs, preservada aqui
    para que a primeira mensagem devolvida seja idêntica à que o router sempre reportou —
    o contrato do lote exige que o comportamento das rotas de CRUD não mude.

    Nunca levanta por conteúdo patológico do script: o parser do CPython pode estourar
    `RecursionError`/`MemoryError` em entrada muito aninhada, não só `SyntaxError` — todas
    viram um problema pt-BR de lista, nunca um 500 (achado da revisão de fase 5).

    `[]` = script ok. Devolve no máximo UM problema (lista de 0 ou 1 item): mantém o import
    agregando um item por tag calculada, e o CRUD reportando o mesmo único 422 de sempre.
    """
    try:
        motivo = check_script_code(code)
        if motivo is not None:
            return [motivo]
        compile(code, "<tag calculada>", "exec")
        tree = ast.parse(code)
    except SyntaxError as exc:
        return [f"Erro de sintaxe no script (linha {exc.lineno}, coluna {exc.offset}): {exc.msg}"]
    except (ValueError, RecursionError, MemoryError):
        return ["Script excede o limite de aninhamento/tamanho suportado pelo analisador"]

    if not _atribui_out(tree):
        return ["O script precisa atribuir a variável OUT"]

    excedentes = sorted(p for p in _posicoes_in_lidas(tree) if p > n_inputs)
    if excedentes:
        nomes = ", ".join(f"IN{p}" for p in excedentes)
        return [f"Script lê {nomes}, mas a tag calculada tem {n_inputs} entrada(s) configurada(s)"]
    return []
