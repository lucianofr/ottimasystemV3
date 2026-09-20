# Blocos `lead_lag` e `dead_time` — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adicionar dois blocos utilitários à paleta do canvas — `lead_lag` (compensação dinâmica `gain·(τ_lead·s+1)/(τ_lag·s+1)`) e `dead_time` (atraso puro de `theta` segundos) — irmãos de `scaler`/`integrator`, para montar cadeias de feedforward `opc_read → dead_time → lead_lag → bias_in`.

**Arquitetura:** Cada bloco atravessa quatro camadas já estabelecidas: config tipada em `ottima-core` (modelo Pydantic + `_parse_loop_config`), portas no validador do grafo, classe de runtime em `flow-runtime/blocks/`, e registro no frontend (tipos, paleta, nó, formulário). O `lead_lag` não implementa equação de diferenças nova: reusa `FirstOrderLag` de `blocks/lag.py` pela identidade `K(τ_l s+1)/(τ_g s+1) = K[r + (1−r)/(τ_g s+1)]`, `r = τ_l/τ_g`. O `dead_time` reusa o padrão de fila de atraso do `_Element` do TFS, porém com `deque[Signal]` (transporta qualidade) e preenchimento pela primeira amostra válida (nunca zero-fill).

**Tech Stack:** Python 3.12, Pydantic v2 (`strict=True`, `allow_inf_nan=False`), SQLAlchemy 2.0 async, pytest + pytest-asyncio, ruff · TypeScript strict, React, React Flow, Playwright como runner dos `*.check.ts`.

**Spec:** `docs/specs/SPEC_LEAD_LAG_E_DEAD_TIME.md` (commits `b54516c`, `c1bb18a`)

## Global Constraints

- Identificadores de código em **inglês**; strings de UI e docs em **pt-BR** (CLAUDE.md).
- Sem emojis em código, comentários ou documentação.
- Commits em **Conventional Commits**, mensagem em pt-BR.
- `docs/adr/` e `docs/GLOSSARY.md` são **normativos**: nenhuma tarefa deste plano os edita sem aprovação humana explícita (Task 10).
- Nenhuma dependência nova. Nenhum canal de barramento novo. Nenhuma migration.
- `frontend/src/lib/contracts.gen.ts` é **gerado** — nunca editado à mão.
- Chave de config do atraso é **`theta`**, nunca `dead_time`: o GLOSSARY já fixa θ como tempo morto (SOPDT/IOPDT/IFOPDT) e o código usa `SopdtParams.theta`/`IopdtParams.theta`.
- Teto da razão lead/lag: **10**. Teto da fila do `dead_time`: **`MAX_DELAY_SAMPLES = 7200`**, a constante que já existe em `validate.py:31` — não criar um segundo número.
- Arredondamento de amostras: `round()` do Python (banker's, half-even), a mesma convenção do TFS e do modelo interno do MPC.
- Nenhuma tarefa roda o gate E2E de 3 camadas nem `docker compose`. Lint e build do projeto inteiro só na Task 9.

**Ordem é dependência real, não preferência.** `portasFixas()` do frontend indexa `PORT_CONTRACTS[tipo]` do arquivo GERADO (`graph.ts:471-475`); enquanto o contrato não for regenerado (Task 3), nenhum arquivo de frontend compila com os tipos novos. Por isso a geração vem antes do frontend, e não junto dos gates finais.

## Disciplina de worktree (LEIA ANTES DO PRIMEIRO `read`)

Este plano roda na worktree **`/home/luciano/orca/workspaces/ottimaSystemV3/new-lead-lag`**. O
checkout principal é outro: `~/Documentos/ProjetosClaudeCode/ottimaSystemV3`.

**Uma sessão de subagente resolve caminho RELATIVO contra a raiz do repositório principal, não
contra a worktree** — mesmo tendo lido o arquivo pelo caminho absoluto da worktree momentos
antes. O agente escreve de um lado, verifica do outro, conclui que "a edição foi revertida", e
o `main` amanhece sujo. O CLAUDE.md documenta o episódio duas vezes; na segunda, 5 de 7
agentes de um lote paralelo caíram nisso e um gastou ~20 min caçando um `git reset` que nunca
houve.

Portanto, em TODA tarefa deste plano:

1. Todo `read`/`write`/`edit` usa o caminho **absoluto**, do `/home/luciano/...` em diante.
   Nunca `packages/...`, nunca `./frontend/...`.
2. Todo comando de shell passa `cwd` explícito da worktree — nunca herda o diretório da sessão.
3. Depois de cada escrita, **confirme por shell** (`grep`/`wc -l`) que o conteúdo chegou ao
   arquivo certo. A resposta de sucesso da ferramenta de edição NÃO é prova.
4. Antes de relatar tarefa concluída, `git status --porcelain` no **checkout principal**
   (`git -C ~/Documentos/ProjetosClaudeCode/ottimaSystemV3 status --porcelain`) tem de estar
   vazio. Rodar `git status` dentro da worktree não revela vazamento: é outra árvore.

## Review Focus

Cinco entradas que a spec implica, que nenhum molde de teste existente cobre, e que morderiam quem usa o sistema. Cada linha tem o teste apontado na tarefa que possui o código.

1. **`tau_lead/tau_lag` exatamente 10** — é o teto, e teto é inclusivo: a razão 10 salva, 10,000001 dá 422. Sem isso, um engenheiro com r = 10 exato leva erro sem entender por quê. → Task 1, `test_lead_lag_aceita_a_razao_no_teto_exato`.
2. **`theta` que arredonda para zero** (`theta < Ts/2`, ex.: 0,4 s num flow de Ts = 1 s) — `d = 0` e o bloco vira passagem direta **em silêncio**, sem erro e sem aviso. É comportamento aceito, mas precisa estar pinado: quem configurar 0,4 s achando que atrasou vai ver o sinal passar direto. → Task 5, `test_dead_time_abaixo_de_meio_ts_vira_passagem_direta_em_silencio`.
3. **`gain = 0`** — desliga o feedforward sem apagar o bloco do canvas; a saída é `0.0` com qualidade GOOD, não nula. Válido e útil (comissionamento), mas só vale se estiver pinado que `0` não é tratado como config ausente. → Task 4, `test_lead_lag_com_ganho_zero_emite_zero_bom`.
4. **Entrada booleana ligada à porta `in`** — os dois blocos são numéricos; uma tag `bool` na entrada tem de ser recusada na validação do servidor E no canvas, antes do save. → Task 2 (`test_recusa_entrada_booleana`) e Task 7 (`recusa ligação com porta booleana`).
5. **`tau_lag < Ts/10` com `tau_lead > 0`** — a degradação para passagem direta tem de devolver `gain*u`, **não** ganho de alta frequência ilimitado. É a borda onde uma implementação ingênua explode. → Task 4, `test_lead_lag_degrada_para_ganho_puro_abaixo_do_limiar_do_ts`.

---

## File Structure

**Criados**
- `services/flow-runtime/src/ottima_flow_runtime/blocks/lead_lag.py` — `LeadLagBlock`: decomposição sobre `FirstOrderLag`, retenção em não-finito.
- `services/flow-runtime/src/ottima_flow_runtime/blocks/dead_time.py` — `DeadTimeBlock`: `deque[Signal]` de tamanho fixo, primada na primeira amostra válida.
- `services/flow-runtime/tests/test_lead_lag_dead_time.py` — contratos de runtime dos dois blocos.
- `packages/ottima-core/tests/test_flowgraph_compensacao.py` — mesa de casos de parse/validate dos dois tipos.
- `frontend/src/features/flows/config/CamposCompensacao.tsx` — formulários dos dois blocos.
- `frontend/src/features/flows/compensacao.check.ts` — checks puros do modelo do editor.
- `docs/adr/ADR-044-blocos-lead-lag-e-tempo-morto.md`.

**Modificados**
- `packages/ottima-core/src/ottima_core/flowgraph/parse.py` — `NodeType`/`NODE_TYPES`, `_CONFIG_KEYS`, `MAX_LEAD_LAG_RATIO`, `LeadLagConfig`, `DeadTimeConfig`, união `NodeConfig`, despacho.
- `packages/ottima-core/src/ottima_core/flowgraph/__init__.py` — reexport dos dois modelos.
- `packages/ottima-core/src/ottima_core/flowgraph/validate.py` — portas fixas, `_check_dead_time_delay`.
- `packages/ottima-core/src/ottima_core/contracts_export.py` — `PORT_CONTRACTS` e `_NODE_CONFIG_MODELS`.
- `services/flow-runtime/src/ottima_flow_runtime/definition.py` — imports e dois branches em `_instantiate`.
- `packages/ottima-mcp/src/ottima_mcp/server.py` + `packages/ottima-mcp/tests/test_server.py`.
- `frontend/src/features/flows/graph.ts`, `registro.ts`, `nodes/index.tsx`, `config/ModalConfigBloco.tsx`.
- `frontend/src/lib/contracts.gen.ts` — **gerado** na Task 3.

Por que arquivos de teste e formulário novos, em vez de estender os existentes: `test_flowgraph_utilitarios.py` e `utilitarios.check.ts` já nasceram separados de `graph.check.ts` porque ele está no teto de linhas do projeto, e `CamposUtilitarios.tsx` cobre Scaler/Integrator/Constante/Barramento. `lead_lag`/`dead_time` formam um terceiro grupo (compensação dinâmica) com mesa de casos própria — a mesma justificativa que `filtros.check.ts` registra no seu cabeçalho.

---

### Task 1: Config tipada e contrato de portas no `ottima-core`

**Files:**
- Modify: `packages/ottima-core/src/ottima_core/flowgraph/parse.py`
- Modify: `packages/ottima-core/src/ottima_core/flowgraph/__init__.py`
- Modify: `packages/ottima-core/src/ottima_core/contracts_export.py`
- Test: `packages/ottima-core/tests/test_flowgraph_compensacao.py` (criar)

**Interfaces:**
- Consumes: nada de tarefas anteriores.
- Produces: `LeadLagConfig(gain: float, tau_lead: float, tau_lag: float)` e `DeadTimeConfig(theta: float)`, exportados de `ottima_core.flowgraph`; os tipos `"lead_lag"` e `"dead_time"` ao FIM de `NODE_TYPES`, nesta ordem; `MAX_LEAD_LAG_RATIO = 10.0` em `parse.py`; entradas em `PORT_CONTRACTS` com portas `in`/`out` numéricas; as duas classes em `_NODE_CONFIG_MODELS` (é o que faz o JSON Schema chegar ao frontend na Task 3).

- [ ] **Step 1: Escrever o teste que falha**

Criar `packages/ottima-core/tests/test_flowgraph_compensacao.py`:

```python
"""Mesa de casos dos blocos de compensação dinâmica no `graph_json` (lead_lag, dead_time).

Arquivo próprio pelo mesmo motivo de `test_flowgraph_filtros.py`/`test_flowgraph_utilitarios.py`:
o grafo de referência de `test_flowgraph.py` não tem estes blocos, e cada mutação deles é um
caso de outra regra.
"""

import pytest

from ottima_core.flowgraph import (
    DeadTimeConfig,
    GraphParseError,
    LeadLagConfig,
    TagRef,
    parse_graph,
    validate_graph,
)

POS = {"x": 0, "y": 0}
TS = 1.0


def _node(node_id: str, tipo: str, exec_order: int, **data: object) -> dict:
    return {
        "id": node_id,
        "type": tipo,
        "position": POS,
        "data": {"exec_order": exec_order, "label": "", **data},
    }


def _leitura(node_id: str = "r1", exec_order: int = 1, tag_id: int = 10) -> dict:
    return _node(node_id, "opc_read", exec_order, tag_id=tag_id)


def _lead_lag(node_id: str = "c1", *, exec_order: int = 2, **config: object) -> dict:
    base: dict[str, object] = {"gain": 1.0, "tau_lead": 20.0, "tau_lag": 10.0}
    return _node(node_id, "lead_lag", exec_order, **(base | config))


def _dead_time(node_id: str = "d1", *, exec_order: int = 2, **config: object) -> dict:
    base: dict[str, object] = {"theta": 30.0}
    return _node(node_id, "dead_time", exec_order, **(base | config))


def _aresta(source: str, target: str, alvo: str = "in") -> dict:
    return {
        "id": f"e-{source}-{target}",
        "source": source,
        "target": target,
        "sourceHandle": "out",
        "targetHandle": alvo,
    }


def _graph(*nodes: dict, edges: list[dict] | None = None) -> dict:
    return {"nodes": list(nodes), "edges": edges or []}


def _ligado(bloco: dict) -> dict:
    """Entrada `in` é obrigatória nos dois blocos: o caso válido a liga."""
    return _graph(_leitura(), bloco, edges=[_aresta("r1", bloco["id"])])


def parse_errors(graph: dict) -> list[str]:
    with pytest.raises(GraphParseError) as exc:
        parse_graph(graph)
    return exc.value.errors


def has(errors: list[str], *trechos: str) -> bool:
    return any(all(trecho in erro for trecho in trechos) for erro in errors)


# --------------------------------------------------------------------------------------
# lead_lag — config
# --------------------------------------------------------------------------------------


def test_lead_lag_parseia_com_config_tipada():
    node = parse_graph(_ligado(_lead_lag())).node("c1")

    assert isinstance(node.config, LeadLagConfig)
    assert node.config.gain == 1.0
    assert node.config.tau_lead == 20.0
    assert node.config.tau_lag == 10.0


@pytest.mark.parametrize("gain", [-3.0, 0.0, 2.5])
def test_lead_lag_aceita_ganho_de_qualquer_sinal(gain: float):
    """Feedforward negativo é rotineiro: distúrbio que sobe a CV pede correção para baixo.
    `gain = 0` desliga o feedforward sem apagar o bloco (comissionamento) — não é config
    ausente."""
    node = parse_graph(_ligado(_lead_lag(gain=gain))).node("c1")

    assert node.config.gain == gain


def test_lead_lag_aceita_tau_lead_zero():
    """`tau_lead = 0` é lag puro — constante legítima, não erro."""
    assert parse_graph(_ligado(_lead_lag(tau_lead=0.0))).node("c1").config.tau_lead == 0.0


def test_lead_lag_aceita_a_razao_no_teto_exato():
    """O teto é inclusivo: r = 10 salva. Quem configurar exatamente 10 não pode levar 422."""
    node = parse_graph(_ligado(_lead_lag(tau_lead=100.0, tau_lag=10.0))).node("c1")

    assert node.config.tau_lead / node.config.tau_lag == 10.0


def test_lead_lag_reprova_razao_acima_do_teto():
    """A razão é o ganho de alta frequência; ligada a `bias_in` ela chega à válvula sem
    atenuação integral (ADR-039 D10 soma depois do integrador)."""
    erros = parse_errors(_ligado(_lead_lag(tau_lead=101.0, tau_lag=10.0)))

    assert has(erros, "tau_lead/tau_lag")


@pytest.mark.parametrize("tau_lag", [0.0, -1.0])
def test_lead_lag_reprova_tau_lag_nao_positivo(tau_lag: float):
    """`tau_lag` é divisor na razão e na discretização: zero é imprópria, não passagem
    direta (a convenção do ADR-026 para `tau` não vale aqui)."""
    assert has(parse_errors(_ligado(_lead_lag(tau_lag=tau_lag))), "tau_lag")


def test_lead_lag_reprova_tau_lead_negativo():
    assert has(parse_errors(_ligado(_lead_lag(tau_lead=-1.0))), "tau_lead")


@pytest.mark.parametrize("campo", ["gain", "tau_lead", "tau_lag"])
@pytest.mark.parametrize("valor", [float("inf"), float("nan"), "5", None, True])
def test_lead_lag_reprova_valor_invalido(campo: str, valor: object):
    assert has(parse_errors(_ligado(_lead_lag(**{campo: valor}))), campo)


def test_lead_lag_reprova_chave_desconhecida():
    assert has(parse_errors(_ligado(_lead_lag(tau=1.0))), "tau")


def test_lead_lag_reprova_campo_ausente():
    graph = _graph(_leitura(), _node("c1", "lead_lag", 2, gain=1.0, tau_lead=5.0))
    assert has(parse_errors(graph), "tau_lag")


# --------------------------------------------------------------------------------------
# dead_time — config
# --------------------------------------------------------------------------------------


def test_dead_time_parseia_com_config_tipada():
    node = parse_graph(_ligado(_dead_time())).node("d1")

    assert isinstance(node.config, DeadTimeConfig)
    assert node.config.theta == 30.0


def test_dead_time_aceita_theta_zero():
    """`theta = 0` é passagem direta — constante legítima."""
    assert parse_graph(_ligado(_dead_time(theta=0.0))).node("d1").config.theta == 0.0


@pytest.mark.parametrize("valor", [-1.0, float("inf"), float("nan"), "30", None, True])
def test_dead_time_reprova_theta_invalido(valor: object):
    assert has(parse_errors(_ligado(_dead_time(theta=valor))), "theta")


def test_dead_time_reprova_chave_desconhecida():
    """A chave é `theta`, o mesmo termo dos modelos SOPDT/IOPDT (GLOSSARY) — `dead_time`
    seria sinônimo inventado para um termo que a casa já fixou."""
    assert has(parse_errors(_ligado(_dead_time(dead_time=30.0))), "dead_time")
```

- [ ] **Step 2: Rodar o teste para confirmar que falha**

```bash
cd /home/luciano/orca/workspaces/ottimaSystemV3/new-lead-lag
uv run pytest packages/ottima-core/tests/test_flowgraph_compensacao.py -x -q
```
Esperado: FAIL na coleta — `ImportError: cannot import name 'LeadLagConfig' from 'ottima_core.flowgraph'`.

- [ ] **Step 3: Registrar os dois tipos em `NodeType`/`NODE_TYPES`**

Em `packages/ottima-core/src/ottima_core/flowgraph/parse.py`, acrescentar as duas entradas ao FIM de cada uma das duas listas (linhas 16-33 e 34-51), depois de `"bus_subscribe"`:

```python
    "bus_subscribe",
    "lead_lag",
    "dead_time",
]
```
e, na tupla:
```python
    "bus_subscribe",
    "lead_lag",
    "dead_time",
)
```

- [ ] **Step 4: Declarar as chaves de config**

Em `parse.py`, dentro de `_CONFIG_KEYS`, logo depois de `"bus_subscribe": ("key",),` (linha 158):

```python
    "lead_lag": ("gain", "tau_lead", "tau_lag"),
    "dead_time": ("theta",),
```

- [ ] **Step 5: Escrever os dois modelos Pydantic**

Em `parse.py`, imediatamente depois de `IntegratorConfig` (que termina na linha 363):

```python
MAX_LEAD_LAG_RATIO = 10.0
"""Teto de `tau_lead/tau_lag`. A razão É o ganho de alta frequência do bloco, e a saída do
lead-lag tipicamente alimenta `bias_in`, somada DEPOIS do integrador (ADR-039 D10) — ruído no
distúrbio medido chega à válvula multiplicado por ela, sem atenuação integral. 10 é a ordem
de grandeza que o DeltaV pratica; acima disso a saída é cascatear dois blocos, como o ADR-026
já decidiu para filtro de ordem superior."""


class LeadLagConfig(BaseModel):
    """Bloco Lead-Lag: `gain * (tau_lead*s + 1)/(tau_lag*s + 1)`, discretizado no Ts do flow.

    `gain` aceita QUALQUER sinal: ganho de feedforward negativo é rotineiro (distúrbio que
    empurra a CV para cima pede correção para baixo na válvula), e `gain = 0` desliga o
    feedforward sem apagar o bloco do canvas.

    `tau_lag > 0` porque é divisor tanto na razão quanto na discretização — `tau_lag = 0` com
    `tau_lead > 0` é função de transferência imprópria (derivador puro), NÃO passagem direta:
    a convenção `tau = 0` do ADR-026 não vale aqui. `tau_lead = 0` é lag puro, legítimo.
    """

    model_config = ConfigDict(extra="forbid", strict=True)
    gain: float = Field(allow_inf_nan=False)
    tau_lead: float = Field(ge=0.0, allow_inf_nan=False)
    tau_lag: float = Field(gt=0.0, allow_inf_nan=False)

    @model_validator(mode="after")
    def _razao_lead_lag(self) -> "LeadLagConfig":
        if self.tau_lead / self.tau_lag > MAX_LEAD_LAG_RATIO:
            raise ValueError(
                f"tau_lead/tau_lag precisa ser no máximo {MAX_LEAD_LAG_RATIO:g} — a razão é o "
                "ganho de alta frequência do bloco; para mais, cascateie dois blocos"
            )
        return self


class DeadTimeConfig(BaseModel):
    """Bloco Tempo morto: atrasa `in` em `theta` segundos.

    `theta` é o mesmo termo dos modelos SOPDT/IOPDT (GLOSSARY) e vira `round(theta/Ts)`
    amostras, com o mesmo arredondamento half-even do TFS. O teto da fila depende do Ts, que
    o parse não conhece: mora em `validate.py`, ao lado do teto do TFS.
    """

    model_config = ConfigDict(extra="forbid", strict=True)
    theta: float = Field(ge=0.0, allow_inf_nan=False)
```

- [ ] **Step 6: Incluir na união e no despacho**

Em `parse.py`, na união `NodeConfig` (linhas 523-538), depois de `| BusKeyConfig`:

```python
    | LeadLagConfig
    | DeadTimeConfig
)
```

E no despacho de config por tipo, depois de `if node_type in BUS_TYPES:` (linhas 741-742):

```python
    if node_type == "lead_lag":
        return _parse_loop_config(where, node_type, LeadLagConfig, data, errors)
    if node_type == "dead_time":
        return _parse_loop_config(where, node_type, DeadTimeConfig, data, errors)
```

- [ ] **Step 7: Reexportar de `ottima_core.flowgraph`**

Em `packages/ottima-core/src/ottima_core/flowgraph/__init__.py`, acrescentar em ordem alfabética no bloco de import de `parse` (linhas 51-84) e no `__all__` (linhas 96-168):

- no import: `DeadTimeConfig,` (antes de `EconomicsConfig`) e `LeadLagConfig,` (depois de `KalmanConfig`)
- no `__all__`: `"DeadTimeConfig",` e `"LeadLagConfig",` nas posições alfabéticas equivalentes

- [ ] **Step 8: Declarar os contratos de porta e o schema de config**

Em `packages/ottima-core/src/ottima_core/contracts_export.py`, depois da entrada `integrator` de `PORT_CONTRACTS` (termina na linha 226):

```python
    # Blocos de compensação dinâmica: Lead-Lag e Tempo morto. Uma entrada, uma saída,
    # numéricas; a config (gain/tau_lead/tau_lag, theta) não muda porta nenhuma.
    "lead_lag": {
        "dynamic": False,
        "ports": [
            {"name": "in", "direction": "input", "type": "num"},
            {"name": "out", "direction": "output", "type": "num"},
        ],
    },
    "dead_time": {
        "dynamic": False,
        "ports": [
            {"name": "in", "direction": "input", "type": "num"},
            {"name": "out", "direction": "output", "type": "num"},
        ],
    },
```

No import de `ottima_core.flowgraph` do topo, acrescentar `DeadTimeConfig` e `LeadLagConfig` em ordem alfabética; e em `_NODE_CONFIG_MODELS` (linhas 326-343), depois de `BusKeyConfig`:

```python
    LeadLagConfig,
    DeadTimeConfig,
)
```

Sem esta última parte o frontend não recebe as interfaces `LeadLagConfig`/`DeadTimeConfig` na Task 3, e a Task 7 não tem de onde derivar os tipos de dados.

- [ ] **Step 9: Rodar os testes até passarem**

```bash
cd /home/luciano/orca/workspaces/ottimaSystemV3/new-lead-lag
uv run pytest packages/ottima-core/tests/test_flowgraph_compensacao.py -q
```
Esperado: PASS em todos os casos do arquivo.

- [ ] **Step 10: Travar o contrato exportado com asserção, não com o gate**

Acrescentar a `packages/ottima-core/tests/test_flowgraph_compensacao.py`:

```python
def test_contrato_exportado_carrega_portas_e_schema_dos_dois_blocos():
    """`_NODE_CONFIG_MODELS` é fácil de esquecer e o gate do CI NÃO pega o esquecimento:
    sem a classe na tupla não há schema, logo o arquivo gerado não muda, logo
    `git diff --exit-code` passa VERDE com o contrato incompleto — e o frontend volta a
    tipar `DadosLeadLag` à mão, quebrando o espelho do ADR-034 em silêncio."""
    from ottima_core.contracts_export import build_contracts

    contratos = build_contracts()

    for tipo in ("lead_lag", "dead_time"):
        portas = contratos["port_contracts"][tipo]
        assert portas["dynamic"] is False
        assert [p["name"] for p in portas["ports"]] == ["in", "out"]
        assert all(p["type"] == "num" for p in portas["ports"])

    assert "LeadLagConfig" in contratos["node_configs"]
    assert "DeadTimeConfig" in contratos["node_configs"]
```

```bash
cd /home/luciano/orca/workspaces/ottimaSystemV3/new-lead-lag
uv run pytest packages/ottima-core/tests/test_flowgraph_compensacao.py -q
```
Esperado: PASS. Se a asserção de `node_configs` falhar, faltou acrescentar as classes a
`_NODE_CONFIG_MODELS` no Step 8.

- [ ] **Step 11: Commit**

```bash
cd /home/luciano/orca/workspaces/ottimaSystemV3/new-lead-lag
git add packages/ottima-core/src/ottima_core/flowgraph/parse.py \
        packages/ottima-core/src/ottima_core/flowgraph/__init__.py \
        packages/ottima-core/src/ottima_core/contracts_export.py \
        packages/ottima-core/tests/test_flowgraph_compensacao.py
git commit -m "feat(flowgraph): config tipada de lead_lag e dead_time

LeadLagConfig (gain de qualquer sinal, tau_lag > 0, razao lead/lag <= 10) e
DeadTimeConfig (theta >= 0) no padrao de ScalerConfig: modelo pydantic strict
despachado por _parse_loop_config. Contratos de porta in/out numericas."
```

---

### Task 2: Portas no validador e teto da fila do `dead_time`

**Files:**
- Modify: `packages/ottima-core/src/ottima_core/flowgraph/validate.py:99` (chamada), `:175` (saídas), `:227` (entradas), `:334` (fim de `_check_tfs_delay`)
- Test: `packages/ottima-core/tests/test_flowgraph_compensacao.py` (estender)

**Interfaces:**
- Consumes: `LeadLagConfig`/`DeadTimeConfig` e os tipos em `NODE_TYPES` (Task 1).
- Produces: portas `in` (obrigatória) e `out`, ambas `num`, para os dois tipos; `_check_dead_time_delay(nodes, ts_seconds, errors)` chamada de `validate_graph`.

- [ ] **Step 1: Escrever o teste que falha**

Acrescentar ao fim de `packages/ottima-core/tests/test_flowgraph_compensacao.py`:

```python
# --------------------------------------------------------------------------------------
# Portas no grafo validado
# --------------------------------------------------------------------------------------


def _tags(data_type: str = "float") -> dict[int, TagRef]:
    return {10: TagRef(id=10, conn_id=1, name="TT101", data_type=data_type, direction="r")}


@pytest.mark.parametrize("bloco", [_lead_lag, _dead_time])
def test_grafo_valido_nao_tem_erro(bloco):
    resultado = validate_graph(parse_graph(_ligado(bloco())), _tags(), TS)

    assert resultado.errors == []


@pytest.mark.parametrize("bloco", [_lead_lag, _dead_time])
def test_entrada_obrigatoria(bloco):
    """RF-302: `in` desligada é erro de validação, como nos filtros."""
    no = bloco()
    resultado = validate_graph(parse_graph(_graph(_leitura(), no)), _tags(), TS)

    assert any(no["id"] in erro for erro in resultado.errors)


@pytest.mark.parametrize("bloco", [_lead_lag, _dead_time])
def test_recusa_entrada_booleana(bloco):
    """Portas dos dois blocos são numéricas: tag `bool` na entrada não passa no save."""
    resultado = validate_graph(parse_graph(_ligado(bloco())), _tags("bool"), TS)

    assert resultado.errors


# --------------------------------------------------------------------------------------
# dead_time — teto da fila (depende do Ts, por isso vive no validate)
# --------------------------------------------------------------------------------------


def test_dead_time_reprova_fila_acima_do_teto():
    """Mesmo teto e mesma constante do TFS (`MAX_DELAY_SAMPLES`): 7201 amostras não passam."""
    resultado = validate_graph(parse_graph(_ligado(_dead_time(theta=7201.0))), _tags(), TS)

    assert any("7201" in erro and "7200" in erro for erro in resultado.errors)


def test_dead_time_aceita_a_fila_no_teto_exato():
    resultado = validate_graph(parse_graph(_ligado(_dead_time(theta=7200.0))), _tags(), TS)

    assert resultado.errors == []


def test_dead_time_conta_amostras_e_nao_segundos():
    """O teto é em AMOSTRAS: com Ts = 2 s, 7201 s cabe (3601 amostras)."""
    resultado = validate_graph(parse_graph(_ligado(_dead_time(theta=7201.0))), _tags(), 2.0)

    assert resultado.errors == []
```

- [ ] **Step 2: Rodar para verificar a falha**

```bash
cd /home/luciano/orca/workspaces/ottimaSystemV3/new-lead-lag
uv run pytest packages/ottima-core/tests/test_flowgraph_compensacao.py -q
```
Esperado: FAIL nos casos novos — os blocos ainda não declaram portas e a fila gigante não produz erro.

- [ ] **Step 3: Declarar as portas de saída**

Em `validate.py`, na linha 175 de `_output_handles`, acrescentar os dois tipos à tupla existente:

```python
    if node.type in _FILTER_TYPES or node.type in (
        "scaler",
        "integrator",
        "constant",
        "lead_lag",
        "dead_time",
    ):
        return ("out",)
```

- [ ] **Step 4: Declarar as portas de entrada**

Em `validate.py`, em `_input_handles`, imediatamente antes do branch `if node.type in _FILTER_TYPES:` (linha 227):

```python
    if node.type in ("lead_lag", "dead_time"):
        return ("in",)
```

`_required_input_handles` NÃO muda: sem branch dedicado, os dois caem no fallback (`return _input_handles(node, mpc_configs)`), que torna `in` obrigatória — exatamente como o `scaler`. `_port_kind` também NÃO muda: sem branch, caem no `return "num"` final.

- [ ] **Step 5: Escrever o teto da fila**

Em `validate.py`, imediatamente depois de `_check_tfs_delay` (que termina na linha 334):

```python
def _check_dead_time_delay(nodes: list[FlowNode], ts_seconds: float, errors: list[str]) -> None:
    """Teto da fila do bloco Tempo morto: mesma constante e mesmo arredondamento do TFS.

    O teto é em AMOSTRAS, não em segundos — por isso depende do Ts e não pode morar no parse
    (`validate_graph` já exige `ts_seconds > 0` justamente para esta classe de checagem).
    """
    for node in nodes:
        if node.type != "dead_time":
            continue
        # Banker's (half-even) do round() do Python: o mesmo theta precisa virar o mesmo
        # número de amostras aqui e em `ottima_flow_runtime.blocks.dead_time`.
        samples = round(node.config.theta / ts_seconds)
        if samples > MAX_DELAY_SAMPLES:
            errors.append(
                f"nó '{node.id}' (dead_time): precisa de {samples} amostras de tempo morto "
                f"(theta={node.config.theta} s, Ts={ts_seconds} s), acima do teto de "
                f"{MAX_DELAY_SAMPLES}"
            )
```

E chamar, em `validate_graph`, imediatamente depois da linha 99 (`_check_tfs_delay(graph.nodes, ts_seconds, errors)`):

```python
    _check_dead_time_delay(graph.nodes, ts_seconds, errors)
```

- [ ] **Step 6: Rodar até passar**

```bash
cd /home/luciano/orca/workspaces/ottimaSystemV3/new-lead-lag
uv run pytest packages/ottima-core/tests/test_flowgraph_compensacao.py -q
```
Esperado: PASS em todos os casos do arquivo.

- [ ] **Step 7: Confirmar que nada mais no `ottima-core` quebrou**

```bash
cd /home/luciano/orca/workspaces/ottimaSystemV3/new-lead-lag
uv run pytest packages/ottima-core/tests -q
```
Esperado: PASS. Se um golden de contrato ou `test_bundle.py` falhar, ele assevera a lista de tipos — atualize a lista no teste, nunca o código.

- [ ] **Step 8: Commit**

```bash
cd /home/luciano/orca/workspaces/ottimaSystemV3/new-lead-lag
git add packages/ottima-core/src/ottima_core/flowgraph/validate.py \
        packages/ottima-core/tests/test_flowgraph_compensacao.py
git commit -m "feat(flowgraph): portas fixas e teto de fila de lead_lag/dead_time

Portas in/out numericas com entrada obrigatoria pelo fallback de
_required_input_handles. _check_dead_time_delay reusa MAX_DELAY_SAMPLES e o
arredondamento half-even do TFS — teto em amostras, por isso no validate."
```

---

### Task 3: Contrato gerado para o frontend

**Files:**
- Modify: `frontend/src/lib/contracts.gen.ts` (**gerado — nunca editado à mão**)

**Interfaces:**
- Consumes: `PORT_CONTRACTS` e `_NODE_CONFIG_MODELS` de `ottima_core.contracts_export` (Task 1).
- Produces: `PORT_CONTRACTS["lead_lag"]`/`["dead_time"]` e as interfaces TS `LeadLagConfig`/`DeadTimeConfig` — sem isso `portasFixas()` (`graph.ts:471-475`) não indexa os tipos novos e NENHUM arquivo de frontend das Tasks 7-8 compila.

- [ ] **Step 1: Regenerar**

```bash
cd /home/luciano/orca/workspaces/ottimaSystemV3/new-lead-lag/frontend
npm run generate:contracts
```

- [ ] **Step 2: Conferir o que entrou**

```bash
cd /home/luciano/orca/workspaces/ottimaSystemV3/new-lead-lag
grep -n '"lead_lag"\|"dead_time"\|interface LeadLagConfig\|interface DeadTimeConfig' frontend/src/lib/contracts.gen.ts
```
Esperado: as duas entradas de `PORT_CONTRACTS` (cada uma com `in`/`out`) e as duas interfaces. A união de chaves de `PORT_CONTRACTS` no topo da tabela também passa a listar os dois tipos.

- [ ] **Step 3: Confirmar que o gate do CI fecha**

```bash
cd /home/luciano/orca/workspaces/ottimaSystemV3/new-lead-lag/frontend
npm run generate:contracts && cd .. && git diff --exit-code -- frontend/src/lib/contracts.gen.ts
```
Esperado: exit 0, sem diff — gerar duas vezes dá o mesmo arquivo. É exatamente o gate de `.github/workflows/gates.yml`.

- [ ] **Step 4: Commit**

```bash
cd /home/luciano/orca/workspaces/ottimaSystemV3/new-lead-lag
git add frontend/src/lib/contracts.gen.ts
git commit -m "chore(contracts): regenera contracts.gen.ts com lead_lag e dead_time"
```

---

### Task 4: Bloco de runtime `lead_lag`

**Files:**
- Create: `services/flow-runtime/src/ottima_flow_runtime/blocks/lead_lag.py`
- Modify: `services/flow-runtime/src/ottima_flow_runtime/definition.py` (import entre `.blocks.kernels.pid` e `.blocks.mpc`; branch em `_instantiate` depois de `first_order`, linha 340)
- Test: `services/flow-runtime/tests/test_lead_lag_dead_time.py` (criar)

**Interfaces:**
- Consumes: `LeadLagConfig` (Task 1); `FirstOrderLag` de `blocks/lag.py`; `Signal`/`Quality`/`has_cold_input`/`null_outputs` de `blocks/base.py`.
- Produces: `LeadLagBlock(block_id: str, *, gain: float, tau_lead: float, tau_lag: float, ts_seconds: float)`, com `INPUT_PORTS = ("in",)` e `OUTPUT_PORTS = ("out",)`.

- [ ] **Step 1: Escrever o teste que falha**

Criar `services/flow-runtime/tests/test_lead_lag_dead_time.py`:

```python
"""Contratos dos blocos de compensação dinâmica Lead-Lag e Tempo morto.

- **Lead-Lag**: `gain*(tau_lead*s+1)/(tau_lag*s+1)` realizado por decomposição sobre o
  estágio ZOH compartilhado (`lag.py`) — a resposta ao degrau bate com a analítica, ponto a
  ponto. Parte sem salto (prima na primeira amostra válida); não-finito não entra na
  recorrência (retém com `min(UNCERTAIN, q_in)`, BAD sem valor bom anterior).
- **Tempo morto**: fila de `round(theta/Ts)` amostras carregando `Signal`, primada na
  primeira amostra válida (nunca zero-fill), emitindo a qualidade histórica.
"""

import math

import pytest

from ottima_core.signal import Quality
from ottima_flow_runtime.blocks.base import Signal
from ottima_flow_runtime.blocks.lead_lag import LeadLagBlock

TS = 1.0


def lead_lag(**config: float) -> LeadLagBlock:
    base = {"gain": 1.0, "tau_lead": 20.0, "tau_lag": 10.0}
    return LeadLagBlock("c1", **(base | config), ts_seconds=TS)


async def alimenta(bloco, valor: float, *, quality: Quality = Quality.GOOD) -> Signal:
    return (await bloco.step({"in": Signal(valor, quality=quality)}))["out"]


def resposta_analitica(
    n: int, *, u0: float, u1: float, gain: float, tau_lead: float, tau_lag: float, ts: float
) -> float:
    """`y(t) = K[u1 + (u0-u1)(1-r)e^(-t/tau_lag)]`, com `t = n*Ts` e o bloco partindo de `u0`."""
    r = tau_lead / tau_lag
    return gain * (u1 + (u0 - u1) * (1.0 - r) * math.exp(-n * ts / tau_lag))


# --------------------------------------------------------------------------------------
# Lead-Lag — dinâmica
# --------------------------------------------------------------------------------------


async def test_lead_lag_reproduz_a_resposta_ao_degrau_analitica():
    """Atualiza-e-emite, como o TFS: na varredura n a saída é y(n*Ts), não y((n-1)*Ts)."""
    bloco = lead_lag()
    await alimenta(bloco, 10.0)  # prima em u0 = 10

    for n in range(1, 20):
        saida = await alimenta(bloco, 15.0)
        assert saida.v == pytest.approx(
            resposta_analitica(n, u0=10.0, u1=15.0, gain=1.0, tau_lead=20.0, tau_lag=10.0, ts=TS)
        )


async def test_lead_lag_parte_sem_salto():
    """Primeira amostra válida sai `gain*u`: o sinal está na EU absoluta da planta e partir
    de zero inventaria um transiente — ligado a `bias_in`, um degrau na válvula."""
    assert (await alimenta(lead_lag(gain=2.0), 150.0)).v == pytest.approx(300.0)


async def test_lead_lag_com_tau_lead_igual_ao_lag_e_ganho_puro():
    bloco = lead_lag(tau_lead=10.0, tau_lag=10.0, gain=3.0)
    await alimenta(bloco, 1.0)

    for valor in (2.0, 7.0, -4.0):
        assert (await alimenta(bloco, valor)).v == pytest.approx(3.0 * valor)


async def test_lead_lag_com_tau_lead_zero_e_filtro_de_primeira_ordem():
    """`tau_lead = 0` reduz a G(s) = K/(tau_lag*s+1) — mesma recorrência do `first_order`,
    porque os dois usam o MESMO estágio de `lag.py`."""
    from ottima_flow_runtime.blocks.first_order import FirstOrderBlock

    compensador = lead_lag(tau_lead=0.0, tau_lag=10.0, gain=1.0)
    filtro = FirstOrderBlock("f1", tau=10.0, ts_seconds=TS)

    await alimenta(compensador, 10.0)
    await alimenta(filtro, 10.0)
    for _ in range(10):
        do_compensador = await alimenta(compensador, 15.0)
        do_filtro = await alimenta(filtro, 15.0)
        assert do_compensador.v == pytest.approx(do_filtro.v)


async def test_lead_lag_com_ganho_zero_emite_zero_bom():
    """`gain = 0` desliga o feedforward sem apagar o bloco: saída 0.0 GOOD, não nula."""
    saida = await alimenta(lead_lag(gain=0.0), 42.0)

    assert saida.v == 0.0
    assert saida.quality is Quality.GOOD


async def test_lead_lag_degrada_para_ganho_puro_abaixo_do_limiar_do_ts():
    """`tau_lag < Ts/10`: nenhuma das duas dinâmicas é resolvível na amostragem (a razão está
    limitada a 10 no parse, então `tau_lead` também é sub-Ts). A saída honesta é `gain*u` —
    NUNCA ganho de alta frequência ilimitado."""
    bloco = lead_lag(gain=2.0, tau_lead=0.5, tau_lag=0.05)

    assert (await alimenta(bloco, 10.0)).v == pytest.approx(20.0)
    assert (await alimenta(bloco, 30.0)).v == pytest.approx(60.0)


# --------------------------------------------------------------------------------------
# Lead-Lag — qualidade
# --------------------------------------------------------------------------------------


async def test_lead_lag_com_cold_start_nao_executa():
    saida = (await lead_lag().step({"in": Signal(None)}))["out"]

    assert saida.v is None
    assert saida.ok is False


async def test_lead_lag_propaga_invalidez_com_valor_finito():
    """Decisão A-6, como o `first_order`: executa e propaga — o estado do lag se lava
    sozinho na amostra seguinte."""
    bloco = lead_lag()
    await alimenta(bloco, 10.0)

    saida = await alimenta(bloco, 12.0, quality=Quality.BAD)

    assert saida.v is not None
    assert saida.quality is Quality.BAD


async def test_lead_lag_propaga_uncertain_sem_elevar():
    bloco = lead_lag()
    await alimenta(bloco, 10.0)

    assert (await alimenta(bloco, 12.0, quality=Quality.UNCERTAIN)).quality is Quality.UNCERTAIN


@pytest.mark.parametrize("ruim", [float("nan"), float("inf"), float("-inf")])
async def test_lead_lag_nao_finito_nao_envenena_a_recorrencia(ruim: float):
    """Um nan no lag deixaria a saída nan para sempre, mesmo depois do sinal se recuperar —
    o argumento que `pid.py::_integral` e `integrator.py` já registram."""
    bloco = lead_lag()
    await alimenta(bloco, 10.0)
    boa = await alimenta(bloco, 10.0)

    suja = await alimenta(bloco, ruim)
    assert suja.v == pytest.approx(boa.v)
    assert suja.quality is Quality.UNCERTAIN

    # O estado se cura na amostra seguinte: nunca precisa de redeploy.
    assert (await alimenta(bloco, 10.0)).quality is Quality.GOOD


async def test_lead_lag_nao_finito_sem_valor_bom_anterior_sai_bad():
    """ADR-043 D7: ausência de dado não é retenção — sem valor bom anterior, BAD, não
    UNCERTAIN."""
    saida = await alimenta(lead_lag(), float("nan"))

    assert saida.v is None
    assert saida.quality is Quality.BAD


async def test_lead_lag_nao_finito_com_entrada_bad_permanece_bad():
    """Monotonicidade (D7): retenção nunca eleva qualidade."""
    bloco = lead_lag()
    await alimenta(bloco, 10.0)

    assert (await alimenta(bloco, float("nan"), quality=Quality.BAD)).quality is Quality.BAD


async def test_lead_lag_reset_volta_ao_nao_primado():
    bloco = lead_lag()
    await alimenta(bloco, 10.0)
    await alimenta(bloco, 50.0)

    bloco.reset()

    assert (await alimenta(bloco, 80.0)).v == pytest.approx(80.0)


def test_lead_lag_declara_uma_entrada_e_uma_saida():
    bloco = lead_lag()

    assert bloco.input_ports == ("in",)
    assert bloco.output_ports == ("out",)
```

- [ ] **Step 2: Rodar para verificar a falha**

```bash
cd /home/luciano/orca/workspaces/ottimaSystemV3/new-lead-lag
uv run pytest services/flow-runtime/tests/test_lead_lag_dead_time.py -x -q
```
Esperado: FAIL na coleta — `ModuleNotFoundError: No module named 'ottima_flow_runtime.blocks.lead_lag'`.

- [ ] **Step 3: Escrever o bloco**

Criar `services/flow-runtime/src/ottima_flow_runtime/blocks/lead_lag.py`:

```python
"""Bloco Lead-Lag: compensação dinâmica `gain*(tau_lead*s + 1)/(tau_lag*s + 1)`.

Uma entrada (`in`), uma saída (`out`), discretizado no Ts do flow pelo MESMO estágio ZOH do
TFS e do Filtro 1ª ordem (`lag.py`) — nenhuma equação de diferenças nova aqui. A identidade

    K*(tau_l*s + 1)/(tau_g*s + 1) = K*[ r + (1 - r)/(tau_g*s + 1) ],   r = tau_l/tau_g

decompõe o bloco em passagem direta ponderada por `r` mais um lag unitário ponderado por
`1 - r`. O denominador é, por construção, bit a bit o dos outros dois blocos — o mesmo pacto
que o docstring de `lag.py` registra.

**Partida sem salto:** a primeira amostra válida depois de deploy/reset prima o lag e a saída
é `gain*u`. Mesmo motivo do ADR-026: o sinal está na EU absoluta da planta, e arrancar de zero
inventaria um transiente que não existe no processo. Ligada a `bias_in` (ADR-039 D10), essa
invenção seria um degrau na válvula.

**Não-finito nunca entra na recorrência.** Um `nan` no estado do lag deixaria a saída `nan`
para sempre, mesmo depois de o sinal se recuperar: a varredura retém a última saída boa com
`min(UNCERTAIN, q_in)` e sai BAD quando nunca houve uma (ADR-043 D7) — é o `_retido` do
`pid.py`. A decisão A-6 do `first_order` ("executa e propaga") continua valendo para amostra
INVÁLIDA de valor finito, cujo efeito o lag lava sozinho na varredura seguinte.

**Degradação sub-Ts:** `tau_lag < Ts/10` faz o `FirstOrderLag` virar passagem direta, e a
saída colapsa em `gain*u`. Com a razão limitada a 10 no parse, `tau_lead` também é sub-Ts
nessa faixa: nenhuma das duas dinâmicas é resolvível na amostragem, e `gain*u` é a resposta
honesta — não um ganho de alta frequência ilimitado.
"""

import math
from collections.abc import Mapping
from datetime import datetime

from ottima_core.signal import Quality

from .base import Block, Signal, has_cold_input, null_outputs
from .lag import FirstOrderLag

INPUT_PORTS = ("in",)
OUTPUT_PORTS = ("out",)


class LeadLagBlock(Block):
    def __init__(
        self,
        block_id: str,
        *,
        gain: float,
        tau_lead: float,
        tau_lag: float,
        ts_seconds: float,
    ) -> None:
        super().__init__(block_id)
        # `Flow.ts_seconds` é Numeric(4,1) e chega como Decimal do SQLAlchemy: converte uma
        # vez na fronteira e o resto é float puro (mesmo cuidado do TfsBlock).
        self._gain = float(gain)
        # `tau_lag > 0` é garantido pelo parse: a divisão não precisa de guarda aqui.
        self._r = float(tau_lead) / float(tau_lag)
        self._lag = FirstOrderLag(float(tau_lag), float(ts_seconds))
        self._started = False
        self._ultima_boa: float | None = None

    @property
    def input_ports(self) -> tuple[str, ...]:
        return INPUT_PORTS

    @property
    def output_ports(self) -> tuple[str, ...]:
        return OUTPUT_PORTS

    async def step(
        self, inputs: Mapping[str, Signal], *, ts: datetime | None = None
    ) -> dict[str, Signal]:
        if has_cold_input(inputs):
            return null_outputs(OUTPUT_PORTS)

        sample = inputs["in"]
        valor = float(sample.v)
        if not math.isfinite(valor):
            if self._ultima_boa is None:
                # Sem valor retido anterior é BAD, nunca UNCERTAIN (ADR-043 D7): ausência de
                # dado não é retenção.
                return null_outputs(OUTPUT_PORTS)
            # Teto `min(UNCERTAIN, ...)`: entrada BAD retida permanece BAD (monotonicidade).
            return {
                "out": Signal(self._ultima_boa, quality=min(Quality.UNCERTAIN, sample.quality))
            }

        if not self._started:
            self._lag.prime(valor)
            self._started = True
        saida = self._gain * (self._r * valor + (1.0 - self._r) * self._lag.step(valor))
        self._ultima_boa = saida
        # Amostra inválida de valor finito executa e propaga a flag (decisão A-6, como o
        # `first_order`): descartá-la congelaria o compensador sem o consumidor saber.
        return {"out": Signal(saida, quality=sample.quality)}

    def reset(self) -> None:
        self._lag.reset()
        self._started = False
        self._ultima_boa = None
```

- [ ] **Step 4: Rodar os testes até passarem**

```bash
cd /home/luciano/orca/workspaces/ottimaSystemV3/new-lead-lag
uv run pytest services/flow-runtime/tests/test_lead_lag_dead_time.py -q
```
Esperado: PASS.

- [ ] **Step 5: Ligar no `definition.py`**

Import em ordem alfabética de módulo, entre `.blocks.kernels.pid` e `.blocks.mpc`:

```python
from .blocks.lead_lag import LeadLagBlock
```

Branch em `_instantiate`, logo depois de `if node.type == "first_order":` (linha 340):

```python
    if node.type == "lead_lag":
        return LeadLagBlock(
            node.id,
            gain=config.gain,
            tau_lead=config.tau_lead,
            tau_lag=config.tau_lag,
            ts_seconds=ts_seconds,
        )
```

- [ ] **Step 6: Escrever o teste de instanciação**

Acrescentar a `services/flow-runtime/tests/test_lead_lag_dead_time.py`. Chama `_instantiate` direto: o branch do `lead_lag` retorna antes de tocar qualquer serviço, então os demais parâmetros podem ser `None`.

```python
# --------------------------------------------------------------------------------------
# Instanciação pelo grafo
# --------------------------------------------------------------------------------------


def _no(tipo: str, **data: object):
    """Nó tipado a partir do JSON real, para não espelhar a forma do config à mão."""
    from ottima_core.flowgraph import parse_graph

    graph = {
        "nodes": [
            {
                "id": "r1",
                "type": "opc_read",
                "position": {"x": 0, "y": 0},
                "data": {"exec_order": 1, "label": "", "tag_id": 10},
            },
            {
                "id": "b1",
                "type": tipo,
                "position": {"x": 0, "y": 0},
                "data": {"exec_order": 2, "label": "", **data},
            },
        ],
        "edges": [
            {
                "id": "e1",
                "source": "r1",
                "target": "b1",
                "sourceHandle": "out",
                "targetHandle": "in",
            }
        ],
    }
    return parse_graph(graph).node("b1")


def _instancia(no, *, ts: float = TS):
    from ottima_flow_runtime.definition import _instantiate

    return _instantiate(
        no,
        flow_id=1,
        ts_seconds=ts,
        tags={},
        redis_client=None,
        pool=None,
        snapshot=None,
        exchange=None,
        write_opc=None,
        mpc_worker_target=None,
        watchdog_enabled=False,
    )


def test_lead_lag_instancia_com_o_ts_do_flow():
    """O bloco recebe o Ts pelo parâmetro de `build_definition`, nunca de `node.config` — o
    scheduler é a única autoridade de tempo do laço."""
    bloco = _instancia(_no("lead_lag", gain=2.0, tau_lead=20.0, tau_lag=10.0))

    assert isinstance(bloco, LeadLagBlock)
    assert bloco.input_ports == ("in",)
```

- [ ] **Step 7: Rodar até passar**

```bash
cd /home/luciano/orca/workspaces/ottimaSystemV3/new-lead-lag
uv run pytest services/flow-runtime/tests/test_lead_lag_dead_time.py -q
```
Esperado: PASS. Se `_instantiate` exigir algum parâmetro adicional que não tem default, acrescente-o como `None` na chamada de `_instancia` — o branch retorna antes de usá-los.

- [ ] **Step 8: Commit**

```bash
cd /home/luciano/orca/workspaces/ottimaSystemV3/new-lead-lag
git add services/flow-runtime/src/ottima_flow_runtime/blocks/lead_lag.py \
        services/flow-runtime/src/ottima_flow_runtime/definition.py \
        services/flow-runtime/tests/test_lead_lag_dead_time.py
git commit -m "feat(flow-runtime): bloco lead_lag por decomposicao sobre FirstOrderLag

G(s) = K*(tau_l*s+1)/(tau_g*s+1) = K*[r + (1-r)/(tau_g*s+1)]: reusa o estagio
ZOH compartilhado, sem equacao de diferencas nova. Parte primado (sem salto);
nao-finito retem com min(UNCERTAIN, q_in) em vez de envenenar a recorrencia."
```

---

### Task 5: Bloco de runtime `dead_time`

**Files:**
- Create: `services/flow-runtime/src/ottima_flow_runtime/blocks/dead_time.py`
- Modify: `services/flow-runtime/src/ottima_flow_runtime/definition.py` (import entre `.blocks.constant` e `.blocks.first_order`; branch depois do de `lead_lag`)
- Test: `services/flow-runtime/tests/test_lead_lag_dead_time.py` (estender)

**Interfaces:**
- Consumes: `DeadTimeConfig` (Task 1); `Signal`/`has_cold_input`/`null_outputs`; os helpers `_no`/`_instancia` da Task 4.
- Produces: `DeadTimeBlock(block_id: str, *, theta: float, ts_seconds: float)`, `INPUT_PORTS = ("in",)`, `OUTPUT_PORTS = ("out",)`.

- [ ] **Step 1: Escrever o teste que falha**

Acrescentar `from ottima_flow_runtime.blocks.dead_time import DeadTimeBlock` ao topo de `services/flow-runtime/tests/test_lead_lag_dead_time.py` e, ao fim:

```python
# --------------------------------------------------------------------------------------
# Tempo morto
# --------------------------------------------------------------------------------------


def dead_time(theta: float = 3.0, *, ts: float = TS) -> DeadTimeBlock:
    return DeadTimeBlock("d1", theta=theta, ts_seconds=ts)


async def test_dead_time_atrasa_exatamente_d_varreduras():
    bloco = dead_time(3.0)

    saidas = [(await alimenta(bloco, valor)).v for valor in (10.0, 11.0, 12.0, 13.0, 14.0, 15.0)]

    # A fila nasce cheia de 10.0: as 3 primeiras saídas repetem a partida e, a partir da
    # quarta, cada saída é a entrada de 3 varreduras atrás.
    assert saidas == [10.0, 10.0, 10.0, 11.0, 12.0, 13.0]


async def test_dead_time_zero_e_passagem_direta():
    bloco = dead_time(0.0)

    assert (await alimenta(bloco, 7.0)).v == 7.0
    assert (await alimenta(bloco, 9.0)).v == 9.0


async def test_dead_time_abaixo_de_meio_ts_vira_passagem_direta_em_silencio():
    """`round(0.4/1.0) == 0`: o bloco não atrasa e não reclama. Comportamento aceito — mas
    quem configurar 0,4 s achando que atrasou vê o sinal passar direto."""
    bloco = dead_time(0.4)

    assert (await alimenta(bloco, 7.0)).v == 7.0
    assert (await alimenta(bloco, 9.0)).v == 9.0


async def test_dead_time_arredonda_half_even_como_o_tfs():
    """`round(2.5) == 2` (banker's): a mesma convenção do TFS, do validate e do MPC."""
    bloco = dead_time(2.5)

    saidas = [(await alimenta(bloco, valor)).v for valor in (1.0, 2.0, 3.0, 4.0)]

    assert saidas == [1.0, 1.0, 1.0, 2.0]


async def test_dead_time_nao_injeta_zero_na_partida():
    """Zero-fill é correto no TFS (variável-desvio) e seria um degrau aqui, onde o sinal está
    na EU absoluta — ligado a `bias_in`, um degrau na válvula por `d` varreduras."""
    assert (await alimenta(dead_time(5.0), 150.0)).v == 150.0


async def test_dead_time_emite_a_qualidade_historica_da_amostra():
    """A saída é a amostra de `d` varreduras atrás: carrega a qualidade DAQUELA amostra, não
    a da entrada corrente."""
    bloco = dead_time(2.0)
    await alimenta(bloco, 1.0)
    await alimenta(bloco, 2.0, quality=Quality.BAD)
    await alimenta(bloco, 3.0)

    saida = await alimenta(bloco, 4.0)

    assert saida.v == 2.0
    assert saida.quality is Quality.BAD


async def test_dead_time_com_cold_start_nao_executa_nem_enche_a_fila():
    bloco = dead_time(2.0)

    nula = (await bloco.step({"in": Signal(None)}))["out"]
    assert nula.v is None
    assert nula.ok is False

    # A fila nasce da PRIMEIRA amostra válida, não da varredura fria.
    assert (await alimenta(bloco, 50.0)).v == 50.0


@pytest.mark.parametrize("ruim", [float("nan"), float("inf")])
async def test_dead_time_nao_finito_sai_nulo_e_invalido(ruim: float):
    """Convenção do `scaler`: nunca nan/inf com ok=True a jusante."""
    bloco = dead_time(1.0)
    await alimenta(bloco, 5.0)
    await alimenta(bloco, ruim)

    saida = await alimenta(bloco, 6.0)

    assert saida.v is None
    assert saida.ok is False


async def test_dead_time_reset_esvazia_a_fila():
    bloco = dead_time(2.0)
    for valor in (1.0, 2.0, 3.0):
        await alimenta(bloco, valor)

    bloco.reset()

    assert (await alimenta(bloco, 99.0)).v == 99.0


def test_dead_time_declara_uma_entrada_e_uma_saida():
    bloco = dead_time()

    assert bloco.input_ports == ("in",)
    assert bloco.output_ports == ("out",)


def test_dead_time_instancia_com_o_ts_do_flow():
    bloco = _instancia(_no("dead_time", theta=30.0))

    assert isinstance(bloco, DeadTimeBlock)
    assert bloco.input_ports == ("in",)
```

- [ ] **Step 2: Rodar para verificar a falha**

```bash
cd /home/luciano/orca/workspaces/ottimaSystemV3/new-lead-lag
uv run pytest services/flow-runtime/tests/test_lead_lag_dead_time.py -x -q
```
Esperado: FAIL na coleta — `ModuleNotFoundError: No module named 'ottima_flow_runtime.blocks.dead_time'`.

- [ ] **Step 3: Escrever o bloco**

Criar `services/flow-runtime/src/ottima_flow_runtime/blocks/dead_time.py`:

```python
"""Bloco Tempo morto: atrasa `in` em `theta` segundos.

Fila de `d = round(theta/Ts)` amostras, arredondamento banker's (half-even) — a MESMA
convenção do TFS (`blocks/tfs.py::_Element`) e do modelo interno do MPC, para que o mesmo
theta vire o mesmo número de amostras nos três códigos. `d = 0` é passagem direta pelo par
append/popleft, sem desvio no caminho quente.

**Relógio nominal, não medido.** A fila anda um slot por `step()`; em overrun o scheduler
pula fronteiras (`_settle_grid`) e `step()` NÃO é chamado nelas, de modo que o atraso efetivo
DILATA em tempo de parede. É assumido: todo bloco de dinâmica da casa embute Ts constante e o
scheduler é a única autoridade de tempo do laço (`pid.py`). O desvio é transitório e nada
acumula — diferente do `integrator.py`, cujo erro seria permanente na conciliação de massa, e
é por isso que só ele mede `dt` de parede. Fique registrada a direção que machuca: tempo morto
dilatado entrega o feedforward ATRASADO, e feedforward atrasado age como um segundo distúrbio
em vez de cancelar o primeiro.

**A fila transporta `Signal`, não `float`:** a saída é a amostra de `d` varreduras atrás e
carrega a qualidade DAQUELA amostra, não a da entrada corrente. É a diferença estrutural para
a fila do TFS, onde a qualidade da linha é resolvida por `min()` fora dela.

**Nunca zero-fill.** A fila nasce cheia da primeira amostra válida. O `deque([0.0] * d)` do
`_Element` é correto lá porque o TFS simula variável-desvio; num bloco autônomo sobre EU
absoluta seria um degrau por `d` varreduras — o próprio `_Element.prime()` já escreve a regra
("senão o atraso injetaria zeros e derrubaria a saída na partida").
"""

import math
from collections import deque
from collections.abc import Mapping
from datetime import datetime

from .base import Block, Signal, has_cold_input, null_outputs

INPUT_PORTS = ("in",)
OUTPUT_PORTS = ("out",)


class DeadTimeBlock(Block):
    def __init__(self, block_id: str, *, theta: float, ts_seconds: float) -> None:
        super().__init__(block_id)
        # `ts_seconds` chega como Decimal do SQLAlchemy: converte uma vez na fronteira
        # (mesmo cuidado do TfsBlock/FirstOrderBlock).
        self._samples = round(float(theta) / float(ts_seconds))
        self._queue: deque[Signal] = deque()

    @property
    def input_ports(self) -> tuple[str, ...]:
        return INPUT_PORTS

    @property
    def output_ports(self) -> tuple[str, ...]:
        return OUTPUT_PORTS

    async def step(
        self, inputs: Mapping[str, Signal], *, ts: datetime | None = None
    ) -> dict[str, Signal]:
        if has_cold_input(inputs):
            return null_outputs(OUTPUT_PORTS)

        sample = inputs["in"]
        if self._samples and not self._queue:
            self._queue.extend([sample] * self._samples)
        self._queue.append(sample)
        atrasada = self._queue.popleft()

        valor = float(atrasada.v)
        if not math.isfinite(valor):
            return null_outputs(OUTPUT_PORTS)
        return {"out": Signal(valor, quality=atrasada.quality)}

    def reset(self) -> None:
        self._queue.clear()
```

- [ ] **Step 4: Rodar os testes até passarem**

```bash
cd /home/luciano/orca/workspaces/ottimaSystemV3/new-lead-lag
uv run pytest services/flow-runtime/tests/test_lead_lag_dead_time.py -q
```
Esperado: PASS (o caso de instanciação ainda falha até o Step 5).

- [ ] **Step 5: Ligar no `definition.py`**

Import em ordem alfabética, entre `.blocks.constant` e `.blocks.first_order`:

```python
from .blocks.dead_time import DeadTimeBlock
```

Branch em `_instantiate`, logo depois do branch de `lead_lag` da Task 4:

```python
    if node.type == "dead_time":
        return DeadTimeBlock(node.id, theta=config.theta, ts_seconds=ts_seconds)
```

- [ ] **Step 6: Rodar a suíte do runtime**

```bash
cd /home/luciano/orca/workspaces/ottimaSystemV3/new-lead-lag
uv run pytest services/flow-runtime/tests -q
```
Esperado: PASS. Se um teste de `definition.py` asseverar a lista de tipos instanciáveis, atualize a lista no teste.

- [ ] **Step 7: Commit**

```bash
cd /home/luciano/orca/workspaces/ottimaSystemV3/new-lead-lag
git add services/flow-runtime/src/ottima_flow_runtime/blocks/dead_time.py \
        services/flow-runtime/src/ottima_flow_runtime/definition.py \
        services/flow-runtime/tests/test_lead_lag_dead_time.py
git commit -m "feat(flow-runtime): bloco dead_time com fila de Signal primada

d = round(theta/Ts) half-even, igual ao TFS. A fila carrega Signal (a saida
emite a qualidade historica da amostra) e nasce cheia da primeira amostra
valida — zero-fill seria degrau na valvula por d varreduras."
```

---

### Task 6: Catálogo do servidor MCP

**Files:**
- Modify: `packages/ottima-mcp/src/ottima_mcp/server.py:492-530`
- Test: `packages/ottima-mcp/tests/test_server.py:171-192`

**Interfaces:**
- Consumes: `NODE_TYPES` com os dois tipos ao fim (Task 1).
- Produces: `TipoBlocoLiteral` — alias de módulo em `server.py` com os 18 tipos — usado na anotação de `flow_add_block`.

- [ ] **Step 1: Atualizar o teste do catálogo (deve passar já)**

Em `packages/ottima-mcp/tests/test_server.py`, na lista de `test_block_catalog_expoe_node_types_e_contratos`, acrescentar depois de `"bus_subscribe",`:

```python
        "lead_lag",
        "dead_time",
    ]
```

```bash
cd /home/luciano/orca/workspaces/ottimaSystemV3/new-lead-lag
uv run pytest packages/ottima-mcp/tests/test_server.py::test_block_catalog_expoe_node_types_e_contratos -q
```
Esperado: **PASS** — `block_catalog` devolve `list(NODE_TYPES)`, que a Task 1 já atualizou. Este passo prova que o catálogo é derivado, não espelhado. Se falhar, a ordem no teste não bate com a de `parse.py`: alinhe o teste ao código.

- [ ] **Step 2: Escrever o teste do espelho manual (deve falhar)**

Acrescentar a `packages/ottima-mcp/tests/test_server.py`, logo depois do teste do catálogo:

```python
def test_literal_de_flow_add_block_cobre_todo_node_type() -> None:
    """O enum de `flow_add_block` é espelho MANUAL de `NODE_TYPES`: hoje está em dia, e é
    justamente por isso que vale travar agora. Um tipo novo registrado em `parse.py` e
    esquecido aqui nasce invisível para agente, sem nada quebrar."""
    from typing import get_args

    from ottima_core.flowgraph.parse import NODE_TYPES

    assert set(get_args(server.TipoBlocoLiteral)) == set(NODE_TYPES)
```

```bash
cd /home/luciano/orca/workspaces/ottimaSystemV3/new-lead-lag
uv run pytest packages/ottima-mcp/tests/test_server.py::test_literal_de_flow_add_block_cobre_todo_node_type -q
```
Esperado: FAIL — `AttributeError: module 'ottima_mcp.server' has no attribute 'TipoBlocoLiteral'`.

- [ ] **Step 3: Extrair o `Literal` para um alias de módulo, com os 18 tipos**

Em `packages/ottima-mcp/src/ottima_mcp/server.py`, acrescentar acima de `flow_add_block` (antes da linha 492):

```python
TipoBlocoLiteral = Literal[
    "opc_read",
    "opc_write",
    "constant",
    "script",
    "fuzzy",
    "tfs",
    "mpc",
    "first_order",
    "kalman",
    "pid",
    "pid_loop",
    "fuzzy_loop",
    "scaler",
    "integrator",
    "bus_publish",
    "bus_subscribe",
    "lead_lag",
    "dead_time",
]
"""Espelho MANUAL de `NODE_TYPES` — o enum precisa ser estático para aparecer no schema da
tool (`block_catalog` já devolve a lista dinâmica, mas o schema da tool não pode).
`test_literal_de_flow_add_block_cobre_todo_node_type` compara os dois; sem ele o espelho
deriva em silêncio."""
```

E substituir o bloco `Literal[...]` inline da anotação de `type` (linhas 495-515) por:

```python
    type: Annotated[
        TipoBlocoLiteral,
        Field(description="Tipo do bloco — ver block_catalog para os campos de config"),
    ],
```

- [ ] **Step 4: Rodar até passar**

```bash
cd /home/luciano/orca/workspaces/ottimaSystemV3/new-lead-lag
uv run pytest packages/ottima-mcp/tests -q
```
Esperado: PASS.

- [ ] **Step 5: Commit**

```bash
cd /home/luciano/orca/workspaces/ottimaSystemV3/new-lead-lag
git add packages/ottima-mcp/src/ottima_mcp/server.py packages/ottima-mcp/tests/test_server.py
git commit -m "feat(mcp): lead_lag e dead_time no enum de flow_add_block

O Literal inline vira o alias TipoBlocoLiteral e ganha os dois tipos novos.
Junto, um teste que o compara a NODE_TYPES: o espelho e manual e hoje esta em
dia — o teste e o que garante que continue."
```

---

### Task 7: Frontend — modelo do editor, paleta e defaults

**Files:**
- Modify: `frontend/src/features/flows/graph.ts` (import de `contracts.gen` no topo; import de defaults :33; `TIPOS_BLOCO` :48-66; tipos de dados depois de :177; uniões :339-391; `tipoPorta` :530-538; `criarBloco` depois de :1125)
- Modify: `frontend/src/features/flows/registro.ts` (:92 defaults; :233 registro)
- Test: `frontend/src/features/flows/compensacao.check.ts` (criar)

**Interfaces:**
- Consumes: as interfaces `LeadLagConfig`/`DeadTimeConfig` e `PORT_CONTRACTS` de `../../lib/contracts.gen` (Task 3).
- Produces: `PADRAO_LEAD_LAG`, `PADRAO_DEAD_TIME`, tipos `NoLeadLag`/`NoDeadTime`, entradas em `TIPOS_BLOCO` e `REGISTRO_BLOCO`.

- [ ] **Step 1: Escrever o teste que falha**

Criar `frontend/src/features/flows/compensacao.check.ts`:

```ts
import { expect, test } from "@playwright/test";

import {
  criarBloco,
  deGraphJson,
  handlesEntrada,
  handlesSaida,
  motivoRecusa,
  paraGraphJson,
  podarArestasDoBloco,
  ROTULO_BLOCO,
  TIPOS_BLOCO,
  tipoPorta,
  type BlocoEdge,
  type BlocoNode,
  type MapaTags,
} from "./graph";

/**
 * Blocos de compensação dinâmica Lead-Lag e Tempo morto no modelo do editor.
 *
 * Arquivo próprio, mesmo motivo de `filtros.check.ts`/`utilitarios.check.ts`:
 * `graph.check.ts` está no teto de linhas do projeto.
 */

const POS = { x: 0, y: 0 };

const TAGS: MapaTags = new Map([
  [10, "float"],
  [11, "bool"],
]);

function compensador(tipo: "lead_lag" | "dead_time", id = "c1", ordem = 2): BlocoNode {
  return criarBloco(tipo, id, POS, ordem);
}

function leitura(id: string, ordem: number, tag: number | null): BlocoNode {
  return { id, type: "opc_read", position: POS, data: { exec_order: ordem, label: "", tag_id: tag } };
}

function escrita(id: string, ordem: number, tag: number | null): BlocoNode {
  return { id, type: "opc_write", position: POS, data: { exec_order: ordem, label: "", tag_id: tag } };
}

function aresta(id: string, source: string, target: string, entrada = "in"): BlocoEdge {
  return { id, source, target, sourceHandle: "out", targetHandle: entrada };
}

test("os dois blocos estão na paleta com rótulo em pt-BR", () => {
  expect(TIPOS_BLOCO).toContain("lead_lag");
  expect(TIPOS_BLOCO).toContain("dead_time");
  expect(ROTULO_BLOCO.lead_lag).toBe("Lead-Lag");
  expect(ROTULO_BLOCO.dead_time).toBe("Tempo morto");
});

for (const tipo of ["lead_lag", "dead_time"] as const) {
  test(`${tipo} tem exatamente uma entrada e uma saída`, () => {
    const no = compensador(tipo);

    expect(handlesEntrada(no)).toEqual(["in"]);
    expect(handlesSaida(no)).toEqual(["out"]);
  });

  test(`${tipo} tem portas numéricas`, () => {
    expect(tipoPorta(compensador(tipo), TAGS)).toBe("num");
  });

  test(`${tipo} recusa ligação com porta booleana`, () => {
    const nos = [leitura("r1", 1, 11), compensador(tipo)];

    const motivo = motivoRecusa(
      { source: "r1", target: "c1", sourceHandle: "out", targetHandle: "in" },
      nos,
      [],
      TAGS,
    );

    expect(motivo).toContain("booleana");
  });

  test(`${tipo} aceita ligação com tag numérica`, () => {
    const nos = [leitura("r1", 1, 10), compensador(tipo)];

    const motivo = motivoRecusa(
      { source: "r1", target: "c1", sourceHandle: "out", targetHandle: "in" },
      nos,
      [],
      TAGS,
    );

    expect(motivo).toBeNull();
  });

  test(`aresta pendurada em porta que ${tipo} não tem é podada`, () => {
    const arestas = [aresta("e1", "r1", "c1", "pv")];

    expect(podarArestasDoBloco(arestas, compensador(tipo))).toEqual([]);
  });
}

test("lead_lag nasce neutro: ganho 1 e razão 1, sem alterar o sinal até ser configurado", () => {
  const no = compensador("lead_lag");
  if (no.type !== "lead_lag") throw new Error("tipo preservado");

  expect(no.data.gain).toBe(1);
  expect(no.data.tau_lead).toBe(10);
  expect(no.data.tau_lag).toBe(10);
});

test("dead_time nasce com theta 0 (passagem direta)", () => {
  const no = compensador("dead_time");
  if (no.type !== "dead_time") throw new Error("tipo preservado");

  expect(no.data.theta).toBe(0);
});

test("round-trip preserva a config dos dois blocos", () => {
  const leadLag = compensador("lead_lag", "c1", 2);
  const deadTime = compensador("dead_time", "d1", 3);
  if (leadLag.type !== "lead_lag" || deadTime.type !== "dead_time") {
    throw new Error("tipo preservado");
  }
  const nos: BlocoNode[] = [
    leitura("r1", 1, 10),
    {
      ...leadLag,
      data: { ...leadLag.data, gain: -2.5, tau_lead: 40, tau_lag: 8, label: "FF da carga" },
    },
    { ...deadTime, data: { ...deadTime.data, theta: 45 } },
    escrita("w1", 4, 10),
  ];
  const arestas = [aresta("e1", "r1", "d1"), aresta("e2", "d1", "c1"), aresta("e3", "c1", "w1")];

  const lido = deGraphJson(paraGraphJson(nos, arestas));

  expect(lido.nodes).toEqual(nos);
  expect(lido.edges).toEqual(arestas);
});

test("campo corrompido no graph_json cai no padrão em vez de virar NaN", () => {
  const bruto = {
    nodes: [
      {
        id: "c1",
        type: "lead_lag",
        position: POS,
        data: { exec_order: 1, label: "", gain: "dois", tau_lead: 40, tau_lag: 8 },
      },
      {
        id: "d1",
        type: "dead_time",
        position: POS,
        data: { exec_order: 2, label: "", theta: null },
      },
    ],
    edges: [],
  };

  const { nodes } = deGraphJson(bruto);

  const [leadLag, deadTime] = nodes;
  if (leadLag.type !== "lead_lag" || deadTime.type !== "dead_time") {
    throw new Error("tipo preservado");
  }
  expect(leadLag.data.gain).toBe(1);
  expect(deadTime.data.theta).toBe(0);
});

test("data serializado carrega só as chaves que o servidor aceita", () => {
  const { nodes } = paraGraphJson(
    [compensador("lead_lag", "c1", 1), compensador("dead_time", "d1", 2)],
    [],
  );

  expect(Object.keys(nodes[0].data).sort()).toEqual([
    "exec_order",
    "gain",
    "label",
    "tau_lag",
    "tau_lead",
  ]);
  expect(Object.keys(nodes[1].data).sort()).toEqual(["exec_order", "label", "theta"]);
});
```

- [ ] **Step 2: Rodar para verificar a falha**

```bash
cd /home/luciano/orca/workspaces/ottimaSystemV3/new-lead-lag/frontend
npm run test:unit -- compensacao
```
Esperado: FAIL — `criarBloco` não conhece os tipos novos.

- [ ] **Step 3: Defaults no registro**

Em `frontend/src/features/flows/registro.ts`, depois de `PADRAO_INTEGRATOR` (linha 92):

```ts
/** Lead-Lag nasce NEUTRO (`tau_lead == tau_lag`, ganho 1): o bloco recém-arrastado não altera
 *  o sinal até ser configurado. Um default que já compensasse alguma coisa seria surpresa na
 *  válvula. Razão 1 e `tau_lag > 0` passam no save. */
export const PADRAO_LEAD_LAG = { gain: 1, tau_lead: 10, tau_lag: 10 } as const;
/** Tempo morto nasce em 0 s: passagem direta até o engenheiro informar o θ. */
export const PADRAO_DEAD_TIME = { theta: 0 } as const;
```

E as entradas de `REGISTRO_BLOCO`, depois de `integrator` (linha 233):

```ts
  lead_lag: {
    rotulo: "Lead-Lag",
    descricao: "Compensação dinâmica: ganho, avanço (τ lead) e atraso (τ lag)",
    defaults: () => ({ ...PADRAO_LEAD_LAG }),
  },
  dead_time: {
    rotulo: "Tempo morto",
    descricao: "Atrasa o sinal em θ segundos",
    defaults: () => ({ ...PADRAO_DEAD_TIME }),
  },
```

- [ ] **Step 4: Tipos e paleta no `graph.ts`**

Acrescentar `DeadTimeConfig` e `LeadLagConfig` ao import de `../../lib/contracts.gen` (topo do arquivo, junto de `ScalerConfig`/`IntegratorConfig`) e `PADRAO_DEAD_TIME, PADRAO_LEAD_LAG` ao import de `./registro` (linha 33).

Em `TIPOS_BLOCO` (linhas 48-66), inserir logo depois de `"kalman",` — a paleta agrupa condicionamento de sinal:

```ts
  "lead_lag",
  "dead_time",
```

Depois de `DadosKalman` (linha 177):

```ts
/** Lead-Lag: compensação dinâmica `gain*(tau_lead*s+1)/(tau_lag*s+1)`. `gain` aceita
 *  qualquer sinal; `tau_lag > 0`; a razão `tau_lead/tau_lag` é limitada a 10 no save. */
export type DadosLeadLag = DadosBase & Pick<LeadLagConfig, keyof LeadLagConfig>;

/** Tempo morto: atrasa o sinal em `theta` segundos (`round(theta/Ts)` amostras). */
export type DadosDeadTime = DadosBase & Pick<DeadTimeConfig, keyof DeadTimeConfig>;
```

Acrescentar `| DadosLeadLag` e `| DadosDeadTime` à união `DadosBloco`; declarar os nós e acrescentá-los à união `BlocoNode`:

```ts
export type NoLeadLag = Bloco<DadosLeadLag, "lead_lag">;
export type NoDeadTime = Bloco<DadosDeadTime, "dead_time">;
```

Em `tipoPorta` (linhas 530-538), acrescentar os dois à condição que devolve `"num"`:

```ts
  if (
    no.type === "first_order" ||
    no.type === "kalman" ||
    no.type === "scaler" ||
    no.type === "integrator" ||
    no.type === "constant" ||
    no.type === "lead_lag" ||
    no.type === "dead_time"
  )
    return "num";
```

Em `criarBloco`, depois do `case "integrator":` (termina na linha 1125):

```ts
    case "lead_lag":
      return {
        id,
        type: tipo,
        position,
        data: {
          exec_order,
          label,
          gain: numero(dados.gain, PADRAO_LEAD_LAG.gain),
          tau_lead: numero(dados.tau_lead, PADRAO_LEAD_LAG.tau_lead),
          tau_lag: numero(dados.tau_lag, PADRAO_LEAD_LAG.tau_lag),
        },
      };
    case "dead_time":
      return {
        id,
        type: tipo,
        position,
        data: {
          exec_order,
          label,
          theta: numero(dados.theta, PADRAO_DEAD_TIME.theta),
        },
      };
```

- [ ] **Step 5: Rodar até passar**

```bash
cd /home/luciano/orca/workspaces/ottimaSystemV3/new-lead-lag/frontend
npm run test:unit -- compensacao
```
Esperado: PASS. O `npm run typecheck` do projeto inteiro ainda FALHA por `TIPOS_DE_NO` (`Record<TipoBloco, ...>`) sem as duas chaves — é o gancho da Task 8.

- [ ] **Step 6: Commit**

```bash
cd /home/luciano/orca/workspaces/ottimaSystemV3/new-lead-lag
git add frontend/src/features/flows/graph.ts frontend/src/features/flows/registro.ts \
        frontend/src/features/flows/compensacao.check.ts
git commit -m "feat(flows): lead_lag e dead_time no modelo do editor e na paleta

Defaults NEUTROS: lead_lag nasce com tau_lead == tau_lag e ganho 1, dead_time
com theta 0 — bloco recem-arrastado nao altera o sinal ate ser configurado."
```

---

### Task 8: Frontend — nó no canvas e formulário de config

**Files:**
- Create: `frontend/src/features/flows/config/CamposCompensacao.tsx`
- Modify: `frontend/src/features/flows/nodes/index.tsx` (imports de tipo :16-20; componentes depois de `NoIntegrator`, que termina em :317; `TIPOS_DE_NO` :513-532)
- Modify: `frontend/src/features/flows/config/ModalConfigBloco.tsx` (import :30; switch `aplicar()` depois do `case "integrator"`, que termina em :437; render condicional :532-533)

**Interfaces:**
- Consumes: `NoLeadLag`/`NoDeadTime` (Task 7); `Campo` de `./CamposComuns`; `numeroDoCampo`; `portasFixas`/`portas`/`LinhaResumo`/`FORMATO_PARAM`/`BlocoChapa` já usados por `NoScaler`.
- Produces: `CamposLeadLag`/`CamposDeadTime`; componentes `NoLeadLag`/`NoDeadTime`; entradas `lead_lag`/`dead_time` em `TIPOS_DE_NO`.

- [ ] **Step 1: Escrever o formulário**

Criar `frontend/src/features/flows/config/CamposCompensacao.tsx`:

```tsx
import { type NoDeadTime, type NoLeadLag } from "../graph";
import { Campo } from "./CamposComuns";

/**
 * Formulários dos blocos de compensação dinâmica Lead-Lag e Tempo morto.
 *
 * Mesma disciplina de `CamposUtilitarios.tsx`: campos não-controlados lidos no envio por
 * `numeroDoCampo` (vírgula decimal pt-BR).
 */

export function CamposLeadLag({ dados }: { dados: NoLeadLag["data"] }) {
  return (
    <div className="space-y-3">
      <Campo
        id="gain"
        rotulo="Ganho"
        valor={dados.gain}
        ajuda="Multiplica a saída. Aceita valor negativo: um distúrbio que empurra a variável controlada para cima costuma pedir correção para baixo. Zero desliga a compensação sem remover o bloco."
      />
      <div className="grid grid-cols-2 gap-3">
        <Campo
          id="tau_lead"
          rotulo="τ avanço (s)"
          valor={dados.tau_lead}
          ajuda="Constante de tempo do numerador. Zero reduz o bloco a um filtro de 1ª ordem."
        />
        <Campo
          id="tau_lag"
          rotulo="τ atraso (s)"
          valor={dados.tau_lag}
          ajuda="Constante de tempo do denominador; precisa ser maior que zero. A razão avanço/atraso é o ganho do bloco em alta frequência e está limitada a 10 — acima disso, ligue dois blocos em série."
        />
      </div>
    </div>
  );
}

export function CamposDeadTime({ dados }: { dados: NoDeadTime["data"] }) {
  return (
    <Campo
      id="theta"
      rotulo="Tempo morto θ (s)"
      valor={dados.theta}
      ajuda="Atraso puro de transporte, contado em varreduras do flow (θ dividido pelo Ts, arredondado). Abaixo de meio Ts o bloco vira passagem direta."
    />
  );
}
```

- [ ] **Step 2: Escrever os nós do canvas**

Em `frontend/src/features/flows/nodes/index.tsx`, acrescentar ao bloco de imports de tipo (ordem alfabética junto dos demais `type No* as No*Data`):

```ts
  type NoDeadTime as NoDeadTimeData,
  type NoLeadLag as NoLeadLagData,
```

E, depois de `NoIntegrator` (termina na linha 317):

```tsx
/** Lead-Lag: ganho e as duas constantes no resumo — o engenheiro lê a compensação inteira
 *  sem abrir o modal. */
export function NoLeadLag({ id, data, selected }: NodeProps<NoLeadLagData>) {
  return (
    <BlocoChapa
      tipo="lead_lag"
      label={data.label}
      execOrder={data.exec_order}
      selecionado={selected}
      entradas={portas(portasFixas("lead_lag", "input"))}
      saidas={portas(portasFixas("lead_lag", "output"))}
      blockId={id}
    >
      <div className="space-y-0.5">
        <LinhaResumo rotulo="Ganho" valor={FORMATO_PARAM.format(data.gain)} />
        <LinhaResumo
          rotulo="τ avanço / atraso"
          valor={`${FORMATO_PARAM.format(data.tau_lead)} / ${FORMATO_PARAM.format(data.tau_lag)} s`}
        />
      </div>
    </BlocoChapa>
  );
}

/** Tempo morto: o θ configurado no resumo. */
export function NoDeadTime({ id, data, selected }: NodeProps<NoDeadTimeData>) {
  return (
    <BlocoChapa
      tipo="dead_time"
      label={data.label}
      execOrder={data.exec_order}
      selecionado={selected}
      entradas={portas(portasFixas("dead_time", "input"))}
      saidas={portas(portasFixas("dead_time", "output"))}
      blockId={id}
    >
      <LinhaResumo rotulo="θ" valor={`${FORMATO_PARAM.format(data.theta)} s`} />
    </BlocoChapa>
  );
}
```

E em `TIPOS_DE_NO` (linhas 513-532), depois de `integrator: NoIntegrator,`:

```ts
  lead_lag: NoLeadLag,
  dead_time: NoDeadTime,
```

- [ ] **Step 3: Ligar no modal de config**

Em `frontend/src/features/flows/config/ModalConfigBloco.tsx`, acrescentar o import depois da linha 30:

```ts
import { CamposDeadTime, CamposLeadLag } from "./CamposCompensacao";
```

No switch de `aplicar()`, depois do `case "integrator": { ... }` (termina na linha 437):

```ts
      case "lead_lag":
        onAplicar(
          {
            ...no,
            data: {
              ...no.data,
              label,
              gain: numeroDoCampo(campos.get("gain"), no.data.gain),
              tau_lead: numeroDoCampo(campos.get("tau_lead"), no.data.tau_lead),
              tau_lag: numeroDoCampo(campos.get("tau_lag"), no.data.tau_lag),
            },
          },
          execOrder,
        );
        break;
      case "dead_time":
        onAplicar(
          {
            ...no,
            data: {
              ...no.data,
              label,
              theta: numeroDoCampo(campos.get("theta"), no.data.theta),
            },
          },
          execOrder,
        );
        break;
```

E no render condicional, depois da linha 533:

```tsx
          {no.type === "lead_lag" && <CamposLeadLag dados={no.data} />}
          {no.type === "dead_time" && <CamposDeadTime dados={no.data} />}
```

- [ ] **Step 4: Verificar que o `tsc` fecha**

```bash
cd /home/luciano/orca/workspaces/ottimaSystemV3/new-lead-lag/frontend
npm run typecheck
```
Esperado: PASS, limpo. Se sobrar erro em `TIPOS_DE_NO`, falta uma das duas chaves.

- [ ] **Step 5: Commit**

```bash
cd /home/luciano/orca/workspaces/ottimaSystemV3/new-lead-lag
git add frontend/src/features/flows/config/CamposCompensacao.tsx \
        frontend/src/features/flows/nodes/index.tsx \
        frontend/src/features/flows/config/ModalConfigBloco.tsx
git commit -m "feat(flows): no de canvas e formulario de lead_lag e dead_time

Resumo no chassis (ganho, tau avanco/atraso, theta) e campos no modal, no
molde de CamposUtilitarios."
```

---

### Task 9: Gates herméticos

**Files:** nenhum arquivo novo; correções pontuais se algum gate reclamar.

**Interfaces:**
- Consumes: Tasks 1-8.
- Produces: repositório com todos os gates de `.github/workflows/gates.yml` verdes.

- [ ] **Step 1: Gates de Python**

```bash
cd /home/luciano/orca/workspaces/ottimaSystemV3/new-lead-lag
uv run ruff check . && uv run ruff format --check .
```
Esperado: PASS. Se a formatação reclamar, rode `uv run ruff format .` e inclua o resultado no commit do Step 5.

- [ ] **Step 2: Suíte de Python**

```bash
cd /home/luciano/orca/workspaces/ottimaSystemV3/new-lead-lag
uv run pytest packages services -q
```
Esperado: PASS. (O run default já exclui `slow` e `e2e`; este plano não roda nenhum dos dois.)

- [ ] **Step 3: Gates de frontend**

```bash
cd /home/luciano/orca/workspaces/ottimaSystemV3/new-lead-lag/frontend
npm run test:unit && npm run typecheck && npm run build
```
Esperado: PASS nos três.

- [ ] **Step 4: Gate do contrato gerado**

```bash
cd /home/luciano/orca/workspaces/ottimaSystemV3/new-lead-lag/frontend
npm run generate:contracts && cd .. && git diff --exit-code -- frontend/src/lib/contracts.gen.ts
```
Esperado: exit 0.

- [ ] **Step 5: Commit apenas se algum gate exigiu correção**

```bash
cd /home/luciano/orca/workspaces/ottimaSystemV3/new-lead-lag
git status --porcelain
# se houver mudança:
git add -A && git commit -m "style: ruff format apos os blocos de compensacao"
```
Se `git status --porcelain` estiver limpo (ignorados `node_modules/`, `package.json` e `pnpm-lock.yaml`, que já eram untracked antes deste trabalho), não há o que commitar.

- [ ] **Step 6: Provar que nada vazou para o checkout principal**

```bash
git -C ~/Documentos/ProjetosClaudeCode/ottimaSystemV3 status --porcelain
```
Esperado: **vazio**. É o item 4 da Disciplina de worktree e o único check que revela o
vazamento de caminho relativo — o `git status` da worktree é outra árvore e não o veria.
Se houver saída, alguma escrita caiu no repositório errado: inspecione o diff, mova a mudança
para a worktree e limpe o principal ANTES de relatar a tarefa concluída.

---

### Task 10: ADR-044 e emendas a documento normativo

**Files:**
- Create: `docs/adr/ADR-044-blocos-lead-lag-e-tempo-morto.md`
- Modify (**somente após aprovação humana**): `docs/GLOSSARY.md`, `docs/adr/ADR-043-qualidade-fim-a-fim.md`

**Interfaces:**
- Consumes: o comportamento implementado nas Tasks 1-9.
- Produces: decisão registrada e vocabulário fixado.

- [ ] **Step 1: Escrever o ADR-044**

Criar `docs/adr/ADR-044-blocos-lead-lag-e-tempo-morto.md`, no formato dos demais (Contexto / Decisão / Consequências). Registra só o que sobrevive ao código; o resto mora nos docstrings dos módulos, como o `scaler` faz. Conteúdo obrigatório:

1. **Contexto** — compensação dinâmica de feedforward só era possível via bloco Script, uma instância de código livre por caso (a mesma motivação que o ADR-026 registrou para os filtros). O lado do PID já estava resolvido: `bias_in` do shell (ADR-039 D10) soma posição depois do integrador, de forma bumpless.
2. **Decisão** — dois blocos, uma entrada `in` / uma saída `out`, numéricas, entrada obrigatória. `lead_lag` com `gain` (qualquer sinal), `tau_lead ≥ 0`, `tau_lag > 0`, realizado por decomposição sobre o estágio ZOH compartilhado de `lag.py`. `dead_time` com `theta ≥ 0`, `d = round(theta/Ts)` half-even, teto `MAX_DELAY_SAMPLES`, fila de `Signal` primada na primeira amostra válida.
3. **Teto de razão `tau_lead/tau_lag ≤ 10`** — a razão é o ganho de alta frequência e a saída tipicamente cai em `bias_in`, somada depois do integrador: ruído chega à válvula sem atenuação integral. O `scaler` pôde escolher não saturar porque over-range é evidência que o operador precisa ver; razão alta não é evidência de nada. Acima do teto, cascatear dois blocos — a mesma saída que o ADR-026 deu para filtro de ordem superior.
4. **Relógio nominal sob overrun** — os dois blocos embutem Ts constante, como TFS, `lag.py` e o termo D do `pid.py`. O `integrator.py` é a exceção documentada porque o erro dele é permanente na conciliação de massa; aqui o desvio é transitório. Registrar a direção: overrun **dilata** o tempo morto (fronteira pulada ⇒ `step()` não chamado), e feedforward atrasado age como segundo distúrbio em vez de cancelar o primeiro.
5. **Hot-swap dá degrau** — reconfigurar um destes blocos alimentando `bias_in` com a malha em AUTO salta a válvula. A garantia do ADR-039 D10 não cobre: `_rebase_bias = True` só é escrito em `apply_tuning()` (`shell/block.py:193`), o hot-swap de sintonia do próprio shell. Consequência aceita e documentada; sem evento novo.
6. **Consequências** — a paleta cresce de 16 para 18 blocos; duas linhas novas na tabela do ADR-043 §5; dois verbetes novos no GLOSSARY; o enum de `flow_add_block` vira `TipoBlocoLiteral` com teste que o compara a `NODE_TYPES`; o `first_order` segue sem guarda de não-finito (dívida declarada, fora de escopo).

- [ ] **Step 2: Commit do ADR**

```bash
cd /home/luciano/orca/workspaces/ottimaSystemV3/new-lead-lag
git add docs/adr/ADR-044-blocos-lead-lag-e-tempo-morto.md
git commit -m "docs(adr): ADR-044 — blocos Lead-Lag e Tempo morto"
```

- [ ] **Step 3: PARAR e apresentar as duas emendas normativas**

**Não edite `docs/GLOSSARY.md` nem `docs/adr/ADR-043-qualidade-fim-a-fim.md` sem resposta explícita do dono.** É o item 4 do CLAUDE.md. Apresente os textos propostos na §5 da spec, verbatim:

- **GLOSSARY** — verbetes **Lead-Lag** e **Tempo morto (bloco)**, no molde das linhas de Scaler (:53) e Integrator (:54).
- **ADR-043 §5** — duas linhas na tabela de propagação de qualidade: `lead_lag` (D6 no caminho normal; retenção `min(UNCERTAIN, q_in)` em não-finito, BAD sem valor bom anterior) e `dead_time` (qualidade histórica da amostra desenfileirada; não-finito na emissão vira nulo + BAD).

- [ ] **Step 4: Aplicar as emendas aprovadas e commitar**

Somente depois do "sim". Se o dono recusar ou pedir outra redação, aplique a redação dele.

```bash
cd /home/luciano/orca/workspaces/ottimaSystemV3/new-lead-lag
git add docs/GLOSSARY.md docs/adr/ADR-043-qualidade-fim-a-fim.md
git commit -m "docs: verbetes de Lead-Lag/Tempo morto e regra de qualidade dos dois blocos"
```
