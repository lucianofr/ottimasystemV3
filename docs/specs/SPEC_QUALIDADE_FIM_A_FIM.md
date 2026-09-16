# SPEC — Qualidade fim-a-fim (Signal como contrato de porta)

Data: 2026-09-16 · Status: aprovado em brainstorm, aguarda revisão final
Materializa em: ADR-043 (novo) + emendas (ADR-039 §4.1, ADR-042 D3/D4, PRD §5.17/§7.1, GLOSSARY)

## 1. Problema

A qualidade do dado nasce rica no opc-worker (`OpcValue.quality`, tri-state 0=good/1=uncertain/2=bad,
spec F1 §3.2) e morre na primeira porta: `opc_read` colapsa `quality != 0` em `ok=False` (decisão A-6,
spec F3), e daí em diante blocos, canvas, `/ws` e `flow.exchange` só enxergam um booleano. UNCERTAIN
e BAD são indistinguíveis a jusante; retenção ("último valor bom, inválido") é indistinguível de
falha total. Paralelamente, o ADR-039 já definiu `Signal` (quality/substatus/limites, convenção
Fieldbus) para os blocos de shell — dois vocabulários coexistem sem ponte documentada.

Requisito do usuário: valor + qualidade (+ campo de status para uso futuro) trafegando em TODA
comunicação de sinal — publicação no barramento, consumo, porta a porta — com documentação normativa
para que qualquer implementação futura obedeça.

## 2. Decisões (fechadas em brainstorm 2026-09-16)

| # | decisão |
|---|---|
| D1 | **`Signal` do ADR-039 é O contrato de porta do sistema inteiro.** `PortSample` e `Signal` fundem numa classe única (`Signal`, em `blocks/base.py`). Polaridade Fieldbus mantida: `Quality` BAD=0 / UNCERTAIN=1 / GOOD=2. |
| D2 | **`OpcValue` fica intocado** (0=good/1=uncertain/2=bad) na camada OPC/persistência: `opc.values.*`, `calc.values`, `flow.values`, recorder, `samples`, `/ws opc_values`, histórico. `opc_read` é o ÚNICO ponto de tradução entre os dois vocabulários. |
| D3 | **UNCERTAIN invalida atuação** — emenda formal ao ADR-039 §4.1: `is_good` passa de `quality is not BAD` para `quality is GOOD`. Preserva o comportamento vivo atual (hoje uncertain chega ao shell colapsado em BAD; a regra §4.1 v1 nunca executou). `STATUS_OPTS` (§9) permanece futuro. |
| D4 | **`Substatus` É o campo "status para uso futuro"** — nenhum campo novo. Códigos novos entram por ADR quando houver necessidade real. O wire carrega o Signal completo: `{v, quality, substatus, hi_limited, lo_limited}`. |
| D5 | **`ok` vira propriedade derivada** (`quality is Quality.GOOD`) — sai do wire e do construtor; legado que lê `.ok` compila e mantém comportamento. `as_signal`/`make_signal` morrem (promoção desnecessária). |
| D6 | **Propagação default:** `quality_out` = pior (`min` na polaridade Fieldbus) das entradas **que alimentaram o cálculo daquela saída** — não "todas as conectadas". |
| D7 | **Retenção emite UNCERTAIN** (UncertainLastUsable): PID `_retido` (RF-553), retenção do fuzzy, lacuna/dt patológico do integrator, expiração do `bus_subscribe`. Comportamento de atuação idêntico (uncertain invalida como BAD); diagnóstico/histórico distinguem "valor retido" de "sem valor". |
| D8 | **Script e tag calculada não veem qualidade** — runtime carimba pior-das-entradas automaticamente. API do sandbox (ADR-018/033) inalterada. |

## 3. Contrato

```python
# blocks/base.py — substitui PortSample; shell/signal.py SOME (imports migram para cá)
class Quality(IntEnum):
    BAD = 0; UNCERTAIN = 1; GOOD = 2          # inalterado (ADR-039)

class Substatus(IntEnum):                      # inalterado (ADR-039)
    NON_SPECIFIC = 0; INIT_REQUEST = 1; NOT_INVITED = 2; LOCAL_OVERRIDE = 3
    SENSOR_FAILURE = 4; CONFIG_ERROR = 5; DEVICE_FAILURE = 6

@dataclass(frozen=True, slots=True)
class Signal:
    v: float | bool | None
    quality: Quality = Quality.BAD
    substatus: Substatus = Substatus.NON_SPECIFIC
    hi_limited: bool = False
    lo_limited: bool = False

    @property
    def ok(self) -> bool:                      # emenda ADR-039 §4.1 embutida no tipo
        return self.quality is Quality.GOOD

COLD = Signal(None)                            # BAD / NON_SPECIFIC — cold start (§3.0 F3)
```

Invariantes:
- `v is None` ⇒ cold start; continua o gatilho de `has_cold_input` (inalterado).
- `ok` não é campo em lugar nenhum (memória ou wire); é sempre derivado.
- Semente de realimentação (ADR-040 D4): `Signal(seed, Quality.GOOD)`.

## 4. Tradução nas bordas (as duas únicas)

| ponto | direção | mapa |
|---|---|---|
| `opc_read` | `OpcValue.quality` → `Quality` | 0→GOOD · 1→UNCERTAIN · 2→BAD · tag fora do espelho→`Signal(None)` |
| `scheduler._historized_value` (`flow.values`, RF-804) | `Quality` → `OpcValue.quality` | GOOD→0 · UNCERTAIN→1 · BAD→2 · `v=None`→`(0.0, 2)` |

**Mudança observável única de persistência:** porta historiada UNCERTAIN passa a gravar
valor+`quality=1` em `samples` onde hoje grava NULL+2 (o NULL do ADR-037 continua exclusivo de
BAD). Trend mostra o valor retido, marcado incerto. Emenda no texto do RF-804.

## 5. Propagação por bloco

| bloco | regra |
|---|---|
| opc_read | tradução da borda (§4); substatus NON_SPECIFIC |
| constant | GOOD sempre (gerador) |
| scaler, lag, first_order, kalman, filtros | default D6 (pior das entradas consumidas) |
| integrator | qualidade sai SÓ de `in`; `reset` fica fora (decisão documentada no módulo). Lacuna/dt patológico → saída UNCERTAIN (D7) |
| TFS | POR LINHA de saída: `min()` dos elementos habilitados da linha (forma quality do AND atual, ADR-022); linha toda desabilitada → GOOD |
| PID (shell) | ADR-039 vigente + emenda §4.1; `_retido` (RF-553) → UNCERTAIN (D7); saídas OUT/BKCAL_OUT mantêm semântica própria (OOS→BAD etc.) |
| fuzzy | retenção → UNCERTAIN (D7); execução ok → default D6 |
| MPC | portas de saída mantêm semântica atual; disponibilidade de MV (RF-626/ADR-028) INTOCADA — `mpc/availability.py` lê `tag.quality` do `ValueSnapshot`, não de porta |
| script | default D6 automático; sandbox cego a qualidade (D8) |
| opc_write | consumidor: suprime escrita se `not ok` (= `quality is not GOOD`) — comportamento atual |
| bus_publish | cold (`v is None`) não publica (como hoje); senão publica Signal completo no payload |
| bus_subscribe | nunca-publicada → `Signal(None)`; fresca → quality/substatus/limites publicados; expirada (idade > 3×period_s) → `min(quality publicado, UNCERTAIN)` (D7) |
| calc-worker (tag calculada) | INTOCADO — já publica `max(quality)` das entradas na polaridade OpcValue (`runner.py`) |

## 6. Payloads (PRD §7.1 — linhas alteradas)

| canal | de | para |
|---|---|---|
| `flow.exchange` | `{key, ts, v, ok, period_s}` | `{key, ts, v, quality, substatus, hi_limited, lo_limited, period_s}` |
| `flow.status.<id>` (`ports`) | `{porta: {v, ok}}` | `{porta: {v, quality, substatus, hi_limited, lo_limited}}` |

`quality`/`substatus` nos payloads acima usam a polaridade Fieldbus (BAD=0/UNCERTAIN=1/GOOD=2) —
o vocabulário do domínio "porta". `opc.values.*`/`calc.values`/`flow.values` seguem `OpcValue`
inalterado. Payloads pub/sub são transientes: deploy da stack inteira junto, sem janela de
compatibilidade dupla. Nenhuma DDL.

## 7. Frontend

- `npm run generate:contracts` regenera `PortValue`/payloads; TypeScript strict pega todos os consumidores.
- Validade visual: `quality !== GOOD` → dessaturação/rótulo atuais (sem terceiro estado visual nesta entrega).
- Tooltip/inspeção da porta: mostra quality (GOOD/UNCERTAIN/BAD) e substatus quando ≠ NON_SPECIFIC.
- Faceplates: idem — sem redesenho.

## 8. Documentação normativa (processo CLAUDE.md item 4 — aprovada pelo usuário neste brainstorm)

1. **ADR-043-qualidade-fim-a-fim.md** (novo): decisões D1–D8; tabela de tradução (§4); registra
   as emendas: ADR-039 §4.1 (`is_good`), ADR-042 D3/D4 (payload + regra de expiração do
   exchange), decisão A-6 da F3 (flag booleana → tri-state), RF-804/ADR-037 (UNCERTAIN persiste
   valor).
2. **ADR-039**: nota de emenda no §4.1 apontando ADR-043 (texto original preservado, marcado emendado).
3. **ADR-042**: nota de emenda em D3/D4 apontando ADR-043.
4. **PRD**: §7.1 tabela (duas linhas do §6 acima) + nota `flow.values` + texto do RF-804.
5. **GLOSSARY**: `qualidade` (tri-state Fieldbus em porta; tri-state OpcValue na borda OPC),
   `substatus` (campo de uso futuro, códigos por ADR), `status` (termo guarda-chuva FF =
   quality+substatus+limites; DISTINTO do status de MV do RF-626 `rcas_ok|...`).

## 9. Verificação (gate da entrega)

- `uv run pytest` (workspace) — inclui: unit dos 15 blocos, scheduler, snapshot, bus blocks,
  shell S1–S12, contracts_export.
- **Aceitação MPC↔TFS (RNF-09) verde sem alterar nenhuma asserção comportamental** — é a prova
  do "comportamento de atuação congelado". Asserções de payload/tipo mudam; de comportamento, não.
- `ruff check` + `format` · `npm run test:unit` + `typecheck` + `build` ·
  `generate:contracts` + `git diff --exit-code`.
- E2E: L1 smoke; L2 cenários que assertam `ports` (F3/F5); L3 visual das superfícies tocadas
  (canvas ONLINE, faceplate, /operacao).

## 10. Fora de escopo (explícito)

- `STATUS_OPTS` (política configurável de UNCERTAIN) — segue ADR-039 §9.
- Códigos novos de `Substatus`; semântica futura entra por ADR próprio.
- Mudança de payload em `opc.values`/`calc.values`/`flow.values` (substatus NÃO atravessa a
  borda OpcValue; perda documentada no ADR-043).
- Terceiro estado visual (uncertain) no frontend.
- RF-626/ADR-028 (disponibilidade de MV) — já lê qualidade da fonte certa.
- Persistência de substatus/limites; DDL de qualquer espécie.
