# ADR-030 — Página FUZZY OPERATE (telemetria e introspecção do bloco Fuzzy)

**Status:** Aceito · 2026-08-14 · **Requisito:** RF-544 (PRD §5.12, v2.3)

## Contexto
O bloco Fuzzy (ADR-029) executa FLL por varredura, mas o operador não enxerga NADA do que
acontece dentro do motor: só o valor crisp final de cada porta em `flow.status`. A página
FUZZY OPERATE precisa mostrar, ao vivo, o ciclo completo de inferência — fuzzificação (μ por
termo de entrada), regra ativada com grau, agregação e defuzzificação — no estilo do
QtFuzzyLite, mais um trend histórico das variáveis do bloco com os mesmos recursos dos
gráficos existentes. Nenhuma infraestrutura para isso existia: sem canal de estado dedicado,
sem tabela de histórico, sem endpoint de introspecção.

## Decisão

### Espelho do padrão MPC em todas as camadas
O bloco MPC já resolveu esse problema inteiro: `mpc.state.<flow_id>.<block_id>` (bus) →
recorder → `mpc_samples`/CAgg → `GET /api/history/mpc` → chave `mpc_state` no `/ws` →
faceplate. A feature replica o desenho, camada por camada, sem inventar segunda convenção:
- **Canal** `fuzzy.state.<flow_id>.<block_id>` com payload `FuzzyState` (bus.py), exportado
  em `contracts_export._WS_MODELS`.
- **Persistência** hypertable `fuzzy_samples` (ts, flow_id, block_id, var_id, v) + CAgg
  `fuzzy_samples_1m`, gravada pelo recorder a partir do canal; `var_id` é a PORTA
  (`IN1..OUT8`), nunca o nome da variável FLL — o nome é rótulo de UI, a porta é o contrato
  (ADR-029).
- **API** `GET /api/operate/fuzzy` (discovery), `GET /api/operate/fuzzy/{flow_id}/{block_id}`
  (introspecção) e `GET /api/history/fuzzy` (trend), todas `require_operator`; `/ws` ganha a
  chave `fuzzy_state` (itens `"<flow_id>/<block_id>"`, quarto `PatternListener`).

### Introspecção server-side (`flowgraph/introspect.py`)
O frontend nunca parseia FLL (ADR-005/ADR-029). Nomes de variáveis, curvas de pertinência,
normas (conjunction/disjunction/implication/activation/aggregation), defuzzificador e texto
das regras nascem em `introspect_fll(fll)`: o servidor amostra cada termo em `N_PONTOS = 101`
pontos (`term.membership(linspace)` vetorizado) numa grade `x` única por variável. A
resolução é constante de servidor — nunca vem do cliente (FUZZY-SEC): o custo é
O(101 × termos), limitado pelo teto de 200k chars do FLL já aplicado no save. FLL que não
parseia levanta `ValueError` → 422; a introspecção roda em `asyncio.to_thread`, como a
validação de save.

### Telemetria por execução com throttle na origem
`FuzzyBlock` ganha uma closure `publish` opcional (injetada em `definition.py`, espelho do
MPC). Após `engine.process()` bem-sucedido, o bloco monta `FuzzyState`:
- `inputs[]`: valor crisp + μ de cada termo (`term.membership(variable.value)`);
- `rules[]`: grau de ativação por regra (`rule.activation_degree`), na ordem de declaração do
  FLL com rule blocks concatenados — alinhado por índice com
  `FuzzyIntrospection.rule_blocks[].rules` achatado;
- `outputs[]`: valor defuzzificado + grau agregado por termo
  (`variable.fuzzy.activation_degree(term)`).

**Throttle mínimo de 0.25s** (`FUZZY_STATE_MIN_INTERVAL_S`) entre publicações por bloco: a
animação não precisa de mais que ~4 Hz, e o custo por varredura precisa continuar sub-ms no
event loop compartilhado (ADR-029). Cold input e exceção do `process()` não publicam (o
estado interno do engine fica stale); entrada não-finita publica com `ok=False` — a página
mostra o estado inválido em vez de congelar. Sanitização na origem: grau não-finito vira 0.0
e valor crisp não-finito vira `None` — `NaN` nunca entra no JSON do canal (RF-542 aplicado ao
barramento; `JSON.parse` do browser rejeita `NaN`).

### Silhueta agregada desenhada no cliente
Mandar a curva agregada do fuzzy set de saída pelo canal (101 pontos × saídas × 4 Hz) seria
desperdício: o cliente já tem as curvas dos termos (introspecção) e os graus por termo
(estado). O frontend recompõe a silhueta com as normas declaradas — implication `Minimum`/
`AlgebraicProduct`, aggregation `Maximum`/`AlgebraicSum`/`BoundedSum`/`UnboundedSum` — e, para
norma fora desse conjunto (ou `aggregation: none`, caso dos engines Takagi-Sugeno/Tsukamoto de
`WeightedAverage`), degrada com honestidade: sombreia cada termo com opacidade proporcional ao
grau, sem silhueta exata. As funções são puras (`fuzzyMath.ts`) e cobertas por checks.

### Trend com a infraestrutura existente
O gráfico da página reusa `TrendChart` (uPlot) e o desenho do trend de operação do MPC:
mesma janela deslizante, mesmos controles, mesmo downsample raw/1m no servidor, teto de 6
penas no cliente e `MAX_FUZZY_VARS = 16` (8+8) no endpoint. Nenhuma dependência nova em
nenhuma camada — SVG puro desenha as funções de pertinência.

## Consequências
- (+) Operador vê fuzzificação, regra ativa e defuzzificação por execução, ao vivo, sem abrir
  o QtFuzzyLite — e com histórico persistido das variáveis do bloco.
- (+) Zero dependência nova; cada camada é o espelho de um padrão já auditado (MPC).
- (+) Throttle + amostragem server-side fixa mantêm os tetos FUZZY-SEC fechados: nenhum
  caminho novo deixa o cliente ditar custo de CPU do backend.
- (-) `fuzzy_samples` cresce com flows rápidos (pior caso ~4 Hz × 16 vars/bloco); mitigado
  pelo throttle na origem, CAgg de 1 min e o mesmo regime de retenção do `mpc_samples`.
- (-) A silhueta agregada é reconstrução do cliente: norma exótica não desenha a forma exata
  (degrade documentado), embora graus e valores continuem corretos.
- Reordenar variáveis no FLL continua mudando o mapeamento de portas (risco aceito na
  ADR-029) — a página exibe o NOME da variável ao lado da porta justamente para tornar isso
  visível ao operador.
