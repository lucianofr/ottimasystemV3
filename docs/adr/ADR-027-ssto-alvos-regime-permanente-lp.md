# ADR-027 — SSTO: camada de alvos de regime permanente por LP acima do MPC

**Status:** Aceito · 2026-08-10 (estende ADR-008/013/019; consome ADR-014; escreve por ADR-002/003)

## Contexto

O MPC da F4 rastreia SP de CV escrito pelo operador (`MpcBlock._sp`, PV-tracking fora de AUTO) e
protege Restrições por faixa com slack dominante (ADR-019). Não existe camada econômica: quem decide
"para onde a planta deve ir" é o operador, variável por variável. APC industrial resolve isso com uma
camada de otimização em regime permanente (SSTO/LP) que roda no mesmo ciclo do controlador e entrega
alvos consistentes com o modelo e com todos os limites simultaneamente.

O sistema tem hoje: matriz de modelos por par linha×coluna (ADR-013), discretizada em `PairSS`
(`mpc/discretize.py`); rank inteiro por Restrição (`ConstraintVar.priority`, ADR-019); orçamento de
tempo de solve por bloco (ADR-014); e um único escritor de hypertable (o `recorder`).

## Decisão

### 1. Camada e localização

Módulo novo `services/flow-runtime/src/ottima_flow_runtime/target_calculation/`, independente de
`mpc/builder.py` e `mpc/worker.py`. O SSTO roda **dentro do processo worker do MPC**, imediatamente
antes do `make_step`, no mesmo `SolveRequest` — mesmo ciclo, mesmo processo, fora do event loop
(ADR-004). O orçamento de tempo do ADR-014 (~70% do Ts efetivo) passa a cobrir LP + NLP; estouro
continua sendo overrun (mantém última MV, alarme).

**Nada em `mpc/builder.py` muda.** O SSTO só substitui a origem do valor escrito em
`built.tvp_template[..., sp_{cv_id}]`.

### 2. Formulação

Decisão: `ΔMV` (desvio do valor de MV vigente). Predição: `ΔCVˢˢ = G·ΔMV + Gd·ΔDV`.

```
min_{ΔMV, s}   cᵀ·ΔMV + wᵀ·s   [+ ρ‖ΔMV − ΔMV_ant‖²  quando detuning ligado]
s.a.  ΔCVˢˢ_L − s ≤ G·ΔMV + Gd·ΔDV ≤ ΔCVˢˢ_U + s
      ΔMV_L ≤ ΔMV ≤ ΔMV_U      (HARD, nunca relaxado)
      s ≥ 0
```

### 3. G e Gd reutilizam o modelo existente — não há segundo modelo de ganho

`G[i][j]` é o ganho DC do `PairSS` **já discretizado** do par (linha i × MV j):
`c·(I − a)⁻¹·b` para `n > 0`, ou `direct_gain` no caso degenerado `n = 0`. Para SOPDT isso vale
exatamente `K`; derivar do `PairSS` em vez de ler `params["K"]` garante que ganho de LP e ganho do
controlador nunca divirjam. `Gd` idem, para as colunas DV. Par `enabled=False` ⇒ entrada 0.

### 4. Linhas integradoras (`kind="integrating"`)

Não têm ganho estático finito — não existe `ΔCVˢˢ` para elas. Entram no LP como **condição de taxa
nula em regime**: `Σ_j Ki_ij·ΔMV_j + Σ_k Kdi_ik·ΔDV_k ∈ [−ε, +ε]`, com o mesmo mecanismo de slack e
de rank das demais linhas. Sem essa linha, um integrador ficaria livre e o LP escolheria vértices que
rampam a planta indefinidamente.

### 5. Mapeamento das categorias existentes (ADR-019 preservado)

| Categoria | Papel no LP | Limite | Rank |
|---|---|---|---|
| **MV** (`MvVar`) | variável de decisão | `limits.min/max` em coordenada absoluta ⇒ `ΔMV_L = limits.min − u`, `ΔMV_U = limits.max − u`. **HARD** | — |
| **CV** (`CvVar`) | linha de `G` | `sp_limits.min/max` = faixa admissível do alvo. **SOFT** | `priority` (campo novo, default igual entre CVs) |
| **Restrição** (`ConstraintVar`) | linha de `G` | `range.low/high`. **SOFT** | `priority` já existente |
| **DV** (`DvVar`) | **nunca** decisão | entra só como `Gd·ΔDV` | — |

**Semântica do rank:** mantém a do ADR-019 — **`priority` maior = mais importante**. A desistência é
em ordem **crescente** de `priority` (a menos importante primeiro). Não se inverte o significado de um
campo já em produção; o brief pedia "maior rank = menor prioridade", o que aqui é a mesma ordenação
lida ao contrário.

### 6. Inviabilidade — duas linhas de defesa

1. **Slack penalizado** em toda linha soft (`w_i = w_base × priority_i`), primeira defesa. O LP com
   slack irrestrito é sempre viável se os limites de MV forem consistentes.
2. **Desistência por rank** quando o solver devolve inviável (limites de MV cruzados/erro numérico) ou
   quando algum slack excede a tolerância: remove as linhas do menor `priority` vigente, re-resolve,
   repete. MV **nunca** é relaxada — se o LP for inviável só por bounds de MV, o SSTO devolve
   `infeasible`, o MPC cai no fallback (SP do operador) e um evento de alarme é emitido.
3. Toda desistência é registrada na auditoria com a ordem em que ocorreu.

### 7. Solver plugável

`SolverBackend` (`Protocol`) com `solve(problem) -> SolverResult`. `SolverResult`: status
(`optimal|infeasible|relaxed|error`), `delta_mv`, `objective`, `active_constraints`, `duals` (shadow
prices de `ineqlin`/`upper`/`lower`), `solver`, `solve_ms`.

- `HiGHSBackend` — default, `scipy.optimize.linprog(method="highs")`. **scipy passa a ser dependência
  declarada** de `ottima-flow-runtime` (hoje entra transitivamente por do-mpc: 1.18.0 instalado).
- `OSQPBackend` — QP do detuning. **`osqp` é dependência NOVA** (não está no ambiente) — exige
  aprovação explícita.
- `GurobiBackend` — stub, `NotImplementedError`.

### 8. Anti-flipping (detuning)

`economics.detuning_weight = ρ > 0` acrescenta `ρ‖ΔMV − ΔMV_anterior‖²` ao objetivo e roteia para o
`OSQPBackend`. É mitigação de **LP flipping** (salto entre vértices por ruído/mudança marginal de
limite), não suavização genérica: `ρ = 0` mantém LP puro e o comportamento de vértice.

### 9. Configuração (pronta para UI futura, sem UI nesta fase)

`MpcConfig` ganha `economics: EconomicsConfig | None = None`:

```python
class EconomicsConfig(BaseModel):
    enabled: bool = False
    costs: dict[str, float] = {}        # var_id (MV/CV/Restrição) -> preço; negativo = maximizar
    slack_weight: float = 1e3
    detuning_weight: float = 0.0        # ρ; > 0 ⇒ QP/OSQP
    solver: Literal["highs", "osqp", "gurobi"] = "highs"
    integrating_tolerance: float = 0.0  # ε da linha de taxa nula
```

Custo em linha (CV/Restrição) é projetado no espaço de decisão: `c_total = c_mv + c_row·G` — a
variável de decisão continua sendo só `ΔMV`. `CvVar` ganha `priority: int = 1`.

`config_hash` = SHA-256 do JSON canônico de `economics` + limites + priorities de todas as variáveis.

### 10. Integração com o MPC dinâmico e fallback

- `economics.enabled = False` (default) ⇒ **caminho de hoje, bit a bit**: `request.sp` do operador.
- `enabled = True` e SSTO `optimal|relaxed` ⇒ `sp_cv := clamp(CVˢˢ*, sp_limits)`.
- SSTO `infeasible|error` ⇒ fallback para o SP vigente do operador + evento `ssto_infeasible`
  (deduplicado por episódio; relaxamento por rank **não** gera evento — fica em `given_up`).
- **CV `integrating` mantém o SP do operador**: ali o LP decide TAXA, não nível (§4); usar a
  taxa como SP seria erro de unidade. O alvo dela existe só na auditoria.
- Só roda em REMOTO+AUTO (é o único modo em que há solve).
- Exceção inesperada na camada econômica ⇒ log + SP do operador. O controlador dinâmico
  nunca para por falha do otimizador.
- **MVˢˢ\* não entra no objetivo dinâmico na v1**: o MPC não tem termo de *ideal resting value*
  (ADR-019 adiou explicitamente) e criar um mexeria no cálculo do move plan. MVˢˢ\* é publicado e
  auditado; o MPC chega nele por consequência dos alvos de CV. **Ponto de decisão do usuário.**

### 11. Auditoria — sem canal de barramento novo

`MpcState` (canal `mpc.state.<flow_id>.<block_id>`, já existente) ganha campo opcional
`ssto: SstoRun | None`. O `recorder` — único escritor de hypertable — persiste em `ssto_runs`
(migration `0004`, hypertable por `ts`, retenção 1 mês, ADR-003), com: `run_id`, `flow_id`,
`block_id`, `config_hash`, snapshot de entrada (`mv`, `cv_ss`, `bias`, `dv`), `costs`, `delta_mv`,
`mv_target`, `cv_target`, `objective`, `status`, `given_up` (ordem), `active_constraints`, `duals`,
`solver`, `solve_ms`. Colunas escalares + JSONB para os vetores; sem UPDATE/DELETE (imutável).

## Consequências

- (+) Alvos consistentes com modelo e limites; operador passa a editar preços e faixas, não SPs.
- (+) Zero mudança na matemática do move plan: builder e `make_step` intocados.
- (−) Orçamento de tempo do ADR-014 passa a ser dividido; LP de porte típico (< 20×20) custa ~1 ms,
  mas o teto de overrun não muda.
- (−) `MpcConfig` cresce; export/import de projeto (ADR-012) precisa carregar `economics` — config
  antiga continua carregando (campo opcional com default).
- (−) `MpcState` cresce em quadros com SSTO ligado (o campo é omitido quando desligado).

## Decisões do gate (2026-08-10, aprovadas pelo usuário)

1. **`osqp` aprovado** como dependência de `ottima-flow-runtime` (junto com `scipy`, que já
   vinha transitivo por do-mpc e passa a ser declarado).
2. **MVˢˢ\* não é rastreado pelo dinâmico na v1** (§10): sem *ideal resting value*, o move
   plan segue intocado. MVˢˢ\* é publicado e auditado.
3. **PRD**: família **RF-901..RF-906** e fase **F7 — Otimização econômica (SSTO)** no §8;
   nota de contrato do `MpcState` no §7.1 (campo `ssto`, opcional).
4. **`CvVar.priority`** criado, com a MESMA semântica de rank do ADR-019 (maior = mais
   importante) e default `1` (retrocompatível).

## Fora de escopo desta fase

- UI do canvas/faceplate para editar `economics` (a estrutura de config já está pronta).
- `GurobiBackend` (stub).
- Termo de *ideal resting value* no objetivo dinâmico (exigiria ADR próprio: mexe no move plan).

## Emenda — banda de SP por linha integradora (2026-08-17)

**Contexto:** §4 fixou a linha integradora como condição de taxa nula `[−ε, +ε]`, com `ε` =
`economics.integrating_tolerance` — um único valor por bloco, sem UI (§"Fora de escopo"), e
sem jeito de uma CV integradora ceder espaço pros outros objetivos do SSTO a não ser via
`priority` (a mesma folga/rank de qualquer linha soft, §6) ou baixando o `integrating_tolerance`
global — o que afeta TODAS as linhas integradoras do bloco de uma vez, não uma só.

**Decisão:** `sp_range_pct` (RF-615 — CV only, `ConstraintVar` não tem o campo) passa a valer
também para `kind="integrating"`, reaproveitando o MESMO campo/UX da banda de nível da CV
`selfreg` — nenhum campo novo, nenhuma mudança de schema. Reinterpretado por `kind` da linha:

- `selfreg` (inalterado): trava o alvo em `SP ± pct/100 × span` (nível).
- `integrating`: vira `ε_linha = pct/100 × span / tss` (taxa, EU/s) — o drift tolerado (`pct`%
  do span) ao longo do horizonte de regime da própria linha (`tss`, já obrigatório e > 0 por
  validação de grafo — nenhum "horizonte de projeção" novo). Essa `ε_linha` substitui, só para
  essa CV, o `economics.integrating_tolerance` do bloco no MESMO dicionário de limites por
  linha que já alimenta o mecanismo de slack/priority (§6) — nada na formulação do LP muda.
  Sem `sp_range_pct` na CV, cai no `integrating_tolerance` do bloco: comportamento de antes
  desta emenda, bit a bit.

**Explicitamente NÃO decidido nesta emenda** (lacuna registrada, não relitigada):

1. `ConstraintVar` (Restrição) não ganhou o campo — criar um exigiria mudança de schema (ao
   contrário da CV, que só reinterpretou o campo existente). Restrição integradora continua
   só no `integrating_tolerance` do bloco.
2. `ε_linha` é aplicado por-ciclo, a cada solve do SSTO — não cumulativo. Nada impede deriva
   sustentada além do `pct`% "pretendido" se o LP escolher a mesma direção em ciclos
   consecutivos; um teto cumulativo desde o deploy exigiria termo de memória/acumulador,
   fora do escopo desta emenda.
