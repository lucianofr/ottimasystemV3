# ADR-031 — Bloco PID (simple-pid)

**Status:** Aceito · 2026-08-15

## Contexto
O controle regulatório do OttimaSystem normalmente permanece nos PIDs de campo, no PLC — esta
ADR não muda esse default. Existem, no entanto, malhas sem PID de campo: instrumentação nova sem
loop configurado no PLC, malhas auxiliares (pré-condicionamento de um setpoint, controle de uma
variável só existente dentro do canvas) ou malhas inteiramente computadas (TFS, script). Para
esses casos o engenheiro hoje só tem o bloco Python-Script (ADR-018) — código livre, sem
validação de ganhos no save e sem resumo legível no canvas, o mesmo problema que motivou os
blocos de filtro (ADR-026). Um bloco PID dedicado fecha essa lacuna com a mesma disciplina:
config declarativa validada, estado com hot-swap, contrato de portas fixo.

A frase de visão do §1 do PRD ("o controle regulatório permanece nos PIDs do PLC") foi escrita
antes deste bloco existir e passou a contradizê-lo ao pé da letra — um PID dentro do canvas
também é controle regulatório. A frase foi revisada na mesma mudança (PRD changelog, RF-301,
§5.13) para manter a postura fail-safe (PLC no comando por default, transferência bumpless)
enquanto reconhece a exceção coberta por este bloco.

## Decisão

### Config e portas
Bloco `pid` com 10 campos de config:

| campo | tipo | restrição |
|---|---|---|
| `kc` | float | finito, qualquer sinal (negativo = ação reversa) |
| `ti_seconds` | float | finito, `>= 0` (tempo integral; `0` = ação integral desligada) |
| `td_seconds` | float | finito, `>= 0` (tempo derivativo; `0` = ação derivativa desligada) |
| `setpoint` | float | finito, qualquer sinal |
| `output_min` | `float \| None` | `None` ou finito, qualquer sinal |
| `output_max` | `float \| None` | `None` ou finito, qualquer sinal |
| `auto_mode` | bool | — |
| `proportional_on_measurement` | bool | — |
| `differential_on_measurement` | bool | — |
| `starting_output` | float | finito, qualquer sinal |

Regras cruzadas: quando os dois limites de saída são informados, `output_min < output_max`
estrito — limites iguais travariam a saída num único valor, erro de config (422), não um caso
degenerado silencioso. Quando os dois limites são informados, `starting_output` precisa estar
dentro de `[output_min, output_max]` — erro explícito, nunca um clamp silencioso, a mesma postura
do mismatch de contagem de portas do Fuzzy (ADR-029).

Portas: `pv` (entrada, **obrigatória**), `sp` (entrada, **opcional** — quando conectada,
sobrepõe o `setpoint` da config; quando ausente, vale o valor da config), `out` (saída). Todas
numéricas. Ao contrário de Script e Fuzzy, o conjunto de portas do PID é **fixo**, como os
blocos de filtro (ADR-026) — não há contagem configurável de entradas/saídas.

### Forma ISA e conversão
O campo de processo especifica ganhos na **forma ISA**:

```
out = Kc * [ e + (1/Ti) * ∫e dt + Td * de/dt ]
```

`simple-pid` implementa a **forma paralela** (`out = Kp*e + Ki*∫e dt + Kd*de/dt`). A conversão
é feita uma única vez, na construção do bloco:

- `Kp = Kc`
- `Ki = Kc / Ti` quando `Ti > 0`, senão `0.0`
- `Kd = Kc * Td`

`Ti` (tempo integral) é informado em **segundos por repetição** e `Td` (tempo derivativo) em
**segundos** — os dois são tempos, não taxas. O reset, em repetições por segundo, é simplesmente
`1/Ti`; a interface mostra essa conversão no texto de ajuda do campo, para o engenheiro que
pensa em reset e não em tempo integral. **`Ti = 0` significa ação integral desligada** —
convenção explícita e documentada que evita divisão por zero e permite controle P ou PD puro, o
mesmo tratamento que ADR-026 dá a `tau = 0` no Filtro 1ª ordem ("0 é caso degenerado
documentado").

**Teto dos ganhos derivados (PID-SEC).** `kc`, `ti_seconds` e `td_seconds` são validados
individualmente como finitos, mas `Ki = Kc/Ti` e `Kd = Kc*Td` ainda podem estourar para `inf`
por overflow IEEE-754 — `ti_seconds = 1e-320` com `kc = 1.0` basta. O save valida os ganhos
**derivados** (422), e não só os campos, porque a consequência em runtime não é uma escrita
errada no PLC — o guard de finitude do `step()` barra o valor — e sim uma **perda silenciosa e
permanente de controle**: `_integral += Ki*e*dt` com `Ki = inf` envenena o acumulador com
`inf`/`nan` para sempre, e o `_clamp` da própria lib não resgata `nan` (comparação com `nan` é
sempre falsa, mesmo com `output_min`/`output_max` definidos). A malha ficaria presa em
`ok=False` até um reset, com **um único** `write_suppressed` no histórico (o dedupe do
`opc_write` nunca rearma, porque nenhuma escrita volta a ter sucesso) e silêncio depois. Falhar
no save troca esse silêncio por um erro em pt-BR na tela. O teto é o overflow, não um mínimo
arbitrário: `Ki` grande porém finito continua sendo decisão de sintonia do engenheiro.

### Parâmetros não expostos
Três parâmetros do `simple-pid` são deliberadamente excluídos da config, por decisão do Gate:

| parâmetro | motivo da exclusão |
|---|---|
| `sample_time` | forçado a `None` na construção — o scheduler do scan cycle é a **única** autoridade de tempo do bloco; um valor acima de Ts faria o bloco devolver silenciosamente uma saída obsoleta enquanto a varredura acredita ter executado. |
| `error_map` | callable Python, não serializável em JSON. |
| `time_fn` | callable Python, não serializável em JSON; código arbitrário do usuário é território do bloco Script (ADR-018), não do PID. |

### dt = Ts nominal
O bloco sempre chama `pid(pv, dt=ts_seconds)`, com `sample_time=None` fixado na construção — o
`dt` passado é sempre o **Ts nominal do flow**, nunca tempo decorrido medido. Três fatos
sustentam essa decisão:

1. Em overrun, o scheduler **pula** fronteiras de grade sem compensação (`scheduler.py:240-286`)
   — o tempo decorrido real entre duas chamadas é, portanto, um múltiplo desconhecido de Ts.
2. Nenhum outro bloco do repositório mede tempo decorrido de parede: TFS, Filtro 1ª ordem e
   `lag.py` embutem todos um Ts constante na sua discretização.
3. Um `dt` com jitter injetaria ruído diretamente no termo derivativo — o pior lugar do
   controlador para receber uma medida de tempo imprecisa.

### Semântica de execução e segurança (RF-552)
Cold start ⇒ saída nula e inválida (`None`, `ok=False`), antes da primeira execução válida.
Amostra finita com `ok=False` é processada normalmente e a flag propagada para a saída — a
mesma decisão A-6 já adotada pelos blocos de filtro (ADR-026).

**Um PV ou SP não-finito nunca chega ao controlador.** `simple-pid` acumula
`_integral += Ki*e*dt` a cada chamada; se `e` (ou `pv`) for `nan`, o integral fica envenenado
**permanentemente** — a saída continuaria `nan` para sempre, mesmo depois de o sinal de entrada
se recuperar. O bloco guarda essa checagem de finitude **antes** de chamar `pid()`: PV ou SP
não-finito não avança o controlador; a saída mantém o último valor bom com `ok=False`.

Saída não-finita, saída `None` (`auto_mode=False` antes da primeira execução) e qualquer exceção
levantada pelo `simple-pid` retêm o **último valor bom** com `ok=False`, sem nunca relançar a
exceção para o flow. A razão concreta: `opc_write` só suprime a escrita quando `v is None` ou
`ok is False` (`opc_write.py:88-95`) — **não faz checagem de finitude própria**. Um `nan`
marcado `ok=True` chegaria ao PLC como escrita válida, corrompendo a malha silenciosamente — a
mesma garantia que ADR-029 já estabeleceu para o bloco Fuzzy.

### Reset e hot-swap (RF-553)
`reset()` do bloco **reconstrói** o controlador (nova instância de `PID`), em vez de chamar
`PID.reset()` da biblioteca. Motivo: `reset()` do `simple-pid` zera o integral mas **não**
restaura `starting_output` — esse valor só é aplicado uma vez, dentro do `__init__`. Chamar
`PID.reset()` descartaria silenciosamente a semente bumpless a cada deploy/stop. Reconstruir o
controlador reaplica `starting_output` corretamente.

Hot-swap preserva o termo integral enquanto a config não muda, seguindo ADR-011/RF-304 — mesma
regra dos demais blocos com estado (Script, TFS, filtros, Fuzzy).

### Relação com ADR-010
Este bloco **não tem máquina de modos**. Os eixos LOCAL/REMOTO e MAN/AUTO do ADR-010 são,
pelo próprio texto daquela ADR, escopados estritamente ao bloco MPC. O bloco PID é um bloco
escalar simples cuja saída o engenheiro conecta a um `opc_write` se e quando quiser — ADR-010
não é alterada nem superada por esta decisão. A segurança de escrita de MV (flow em deploy +
watchdog vivo + modo REMOTO) continua sendo aplicada onde já é hoje, no caminho de escrita
(`opc_write`), não neste bloco.

### Dependência
`simple-pid>=2.0,<3`, declarada **apenas** em `services/flow-runtime/pyproject.toml`. Dois
pontos contrastam com a dependência do bloco Fuzzy (ADR-029): a licença é **MIT** — sem a
ressalva GPLv3/comercial que `pyfuzzylite` exige em caso de distribuição fechada — e a biblioteca
declara **zero dependências de runtime** (sem `numpy`, portanto sem entrada em
`[tool.uv] override-dependencies`). O `ottima-core` **não** recebe a dependência: a validação
de config do PID é Pydantic puro + checagens escalares manuais, e nunca precisa instanciar um
controlador para validar no save — diferente do parser FLL, que genuinamente precisava de
`pyfuzzylite` na camada da API.

## Consequências
- (+) Malhas sem PID de campo (ou auxiliares/computadas) ganham um bloco de controle regulatório
  dedicado, validado no save, sem precisar de código livre no bloco Script.
- (+) A conversão ISA → paralela roda uma única vez na construção do bloco; o engenheiro
  configura em `Kc`/`Ti`/`Td` (forma industrial padrão), não nos ganhos internos do `simple-pid`.
- (+) `nan`/`inf` nunca vazam para o PLC como escrita "válida" — mesma garantia de segurança dos
  demais blocos numéricos (filtros, Fuzzy).
- (+) `Ti = 0`/`Td = 0` documentados como casos degenerados válidos permitem P, PI, PD ou PID
  completo com o mesmo bloco, sem campo separado de "tipo de controlador".
- (-) `dt` fixo em Ts nominal (não tempo de parede) significa que o termo integral/derivativo
  do bloco assume que o scan cycle nunca atrasa de forma não compensada — mesma premissa que
  TFS e Filtro 1ª ordem já fazem, não uma limitação nova.
- Este bloco não substitui nem interage com os eixos de modo do MPC (ADR-010); é responsabilidade
  do engenheiro decidir se uma malha usa PID de campo, PID interno ou MPC.
- Paleta da v1 cresce de 8 para 9 blocos (RF-301).
