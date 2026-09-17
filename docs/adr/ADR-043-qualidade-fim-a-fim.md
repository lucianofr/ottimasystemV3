# ADR-043 — Qualidade fim-a-fim (Signal como contrato de porta)

**Status:** Aceito · 2026-09-16 · **Emenda ao ADR-039 §4.1** (`is_good` passa de `quality is not BAD` para `quality is GOOD`; as regras 5–8 de shed passam a disparar também em UNCERTAIN) **e ao ADR-042 D3/D4** (payload de `flow.exchange` e regra de expiração) · Relacionado: ADR-002, ADR-033, ADR-037, ADR-041 · Spec: `docs/specs/SPEC_QUALIDADE_FIM_A_FIM.md`

## 1. Contexto

A qualidade do dado nasce rica no `opc-worker` (`OpcValue.quality`, tri-state 0=good/1=uncertain/2=bad,
spec F1 §3.2) e morre na primeira porta: `opc_read` colapsa `quality != 0` em `ok=False` (decisão A-6,
spec F3), e daí em diante blocos, canvas, `/ws` e `flow.exchange` só enxergam um booleano. UNCERTAIN
e BAD são indistinguíveis a jusante; retenção ("último valor bom, inválido") é indistinguível de
falha total. Paralelamente, o ADR-039 já definiu `Signal` (quality/substatus/limites, convenção
Fieldbus) para os blocos de shell — dois vocabulários coexistiam sem ponte documentada: `PortSample`
(`v`, `ok`) na maioria dos blocos e `Signal` (`value`, `quality`, `substatus`, `hi_limited`,
`lo_limited`) só no shell (ADR-039 §4.1).

Requisito do usuário: valor + qualidade (+ campo de status para uso futuro) trafegando em TODA
comunicação de sinal — publicação no barramento, consumo, porta a porta — com documentação normativa
para que qualquer implementação futura obedeça. Este ADR registra as nove decisões fechadas em
brainstorm (2026-09-16) e materializadas pelas Tasks 1–5 desta entrega.

## 2. Decisão

### D1 — `Signal` é o contrato de porta do sistema inteiro

`PortSample` e `Signal` fundem numa classe única (`Signal`). Polaridade Fieldbus mantida: `Quality`
BAD=0 / UNCERTAIN=1 / GOOD=2. `Quality`/`Substatus` nascem em `ottima-core` (`PortValue`/
`ExchangeValue`/`contracts_export` dependem deles); o dataclass `Signal` fica em `blocks/base.py`
importando de lá. `services/flow-runtime/src/ottima_flow_runtime/blocks/shell/signal.py` (ADR-039)
some — substituído pela classe única.

### D2 — `OpcValue` fica intocado

`OpcValue` (0=good/1=uncertain/2=bad) permanece intocado na camada OPC/persistência:
`opc.values.*`, `calc.values`, `flow.values`, recorder, `samples`, `/ws opc_values`, histórico.
`opc_read` é o ÚNICO ponto de tradução entre os dois vocabulários.

### D3 — UNCERTAIN invalida atuação

Emenda formal ao ADR-039 §4.1: `is_good` passa de `quality is not BAD` para `quality is GOOD`.
Preserva o comportamento vivo atual (hoje uncertain chega ao shell colapsado em BAD; a regra §4.1
v1 nunca executou de fato, porque `opc_read` já entregava só GOOD/BAD antes desta entrega).
`STATUS_OPTS` (ADR-039 §9) permanece trabalho futuro.

### D4 — `Substatus` é o campo "status para uso futuro"

Nenhum campo novo. Códigos novos entram por ADR quando houver necessidade real. O wire carrega o
`Signal` completo: `{v, quality, substatus, hi_limited, lo_limited}`.

### D5 — `ok` vira propriedade derivada

`ok` (`quality is Quality.GOOD`) sai do wire e do construtor; legado que lê `.ok` compila e mantém
comportamento. `as_signal`/`make_signal` (promoção explícita ADR-039) morrem — promoção desnecessária
com o tipo único.

### D6 — Propagação default: pior das entradas consumidas

`quality_out` = pior (`min` na polaridade Fieldbus) das entradas **que alimentaram o cálculo daquela
saída** — não "todas as conectadas".

### D7 — Retenção emite `min(UNCERTAIN, pior das entradas consumidas)`

UncertainLastUsable, nos quatro caminhos: PID `_retido` (RF-553), retenção do fuzzy, lacuna/dt
patológico do integrator, expiração do `bus_subscribe`. **NUNCA eleva qualidade** — entrada BAD
retida sai BAD (monotonicidade: lavar um sensor ruim em "apenas retido" seria acionável no dia em
que `STATUS_OPTS` tornar UNCERTAIN usável). UNCERTAIN genuíno = entrada boa + valor não-finito/lacuna
interna. Atuação idêntica hoje (uncertain invalida como BAD, D3); diagnóstico/UI (`flow.status`/WS/
exchange) distinguem "valor retido" de "sem valor" — o histórico NÃO (§4/§8).

**Sem valor retido anterior (`v is None`) ⇒ BAD**, nunca UNCERTAIN: ausência de dado não é
retenção, e anunciar "último valor utilizável" quando nunca houve um seria mentira de
diagnóstico. Vale para os três caminhos internos (`pid._retido`, os dois ramos do fuzzy) e é
o que mantém o cold start (`has_cold_input` olha `v is None`) coerente com a qualidade
publicada. O `bus_subscribe` já satisfaz a regra por construção: chave nunca publicada devolve
`Signal(None)`, que é BAD pelo default.

### D8 — Script e tag calculada não veem qualidade

O runtime carimba pior-das-entradas automaticamente. API do sandbox (ADR-018/033) inalterada.

### D9 — Bloco não-shell emite `substatus=NON_SPECIFIC` e limites `False`

Idêntico ao zeramento que `as_signal` fazia em toda aresta legada. Só o shell PRODUZ substatus/
limites (bits direcionais, ADR-039 §4.9); blocos de barramento TRANSPORTAM verbatim. Propagação real
por blocos de transformação exigiria regra de inversão por sinal de ganho (scaler reverso) — ADR
futuro (fora de escopo, §9).

## 3. Contrato

```python
# ottima_core: Quality/Substatus · blocks/base.py: Signal (substitui PortSample; shell/signal.py SOME)
class Quality(IntEnum):
    BAD = 0; UNCERTAIN = 1; GOOD = 2          # inalterado (ADR-039)

class Substatus(IntEnum):                      # inalterado (ADR-039)
    NON_SPECIFIC = 0; INIT_REQUEST = 1; NOT_INVITED = 2; LOCAL_OVERRIDE = 3
    SENSOR_FAILURE = 4; CONFIG_ERROR = 5; DEVICE_FAILURE = 6

@dataclass(frozen=True, slots=True)
class Signal:
    v: float | bool | None
    # `quality` KEYWORD-ONLY por segurança: o construtor antigo era posicional
    # `PortSample(v, ok: bool)` em 60+ call sites. Sem kw-only, um `Signal(x, True)`
    # sobrevivente guardaria `True` CRU no campo (dataclass não coage): `ok` viraria
    # False e o bool contaminaria `min()` e o payload JSON — e o CI não tem mypy
    # (ADR-035). Kw-only vira TypeError na coleta do pytest. Verificado em 3.12.9.
    _: KW_ONLY
    quality: Quality = Quality.BAD
    substatus: Substatus = Substatus.NON_SPECIFIC
    hi_limited: bool = False
    lo_limited: bool = False

    @property
    def ok(self) -> bool:                      # emenda ADR-039 §4.1 embutida no tipo
        return self.quality is Quality.GOOD

COLD = Signal(None)                            # BAD / NON_SPECIFIC — cold start
```

Invariantes:
- `v is None` ⇒ cold start; continua o gatilho de `has_cold_input` (inalterado).
- `ok` não é campo em lugar nenhum (memória ou wire); é sempre derivado.
- Semente de realimentação (ADR-040 D4): `Signal(seed, quality=Quality.GOOD)`.

## 4. Tradução nas bordas (as duas únicas)

| ponto | direção | mapa |
|---|---|---|
| `opc_read` | `OpcValue.quality` → `Quality` | 0→GOOD · 1→UNCERTAIN · 2→BAD · tag fora do espelho→`Signal(None)` |
| `scheduler._historized_value` (`flow.values`, RF-804) | `Quality` → `OpcValue.quality` | GOOD→0 · **não-GOOD→2** · `v=None`→`(0.0, 2)` |

**Persistência byte-idêntica à atual:** todo não-GOOD historiado vira `quality=2` → recorder grava
NULL (ADR-037 intacto, RF-804 intacto). UNCERTAIN persistido com valor injetaria o valor CONGELADO
da retenção em `avg`/`sum`/`samples_1m` — exatamente o dano que o ADR-037 escolheu NULL para evitar.
O tri-state vive em `flow.status`/WS/`flow.exchange` (diagnóstico), não no histórico. Tag OPC
uncertain (medição real) segue persistindo valor como hoje — a regra do recorder não muda.

## 5. Propagação por bloco

| bloco | regra |
|---|---|
| opc_read | tradução da borda (§4); substatus NON_SPECIFIC |
| constant | GOOD sempre (gerador) |
| scaler, lag, first_order, kalman, filtros | default D6 (pior das entradas consumidas); emissão D9 (substatus/limites zerados) |
| integrator | qualidade sai SÓ de `in`; `reset` fica fora (decisão documentada no módulo). Lacuna/dt patológico → `min(UNCERTAIN, q_in)` (D7) |
| TFS | POR LINHA de saída: `min()` dos elementos habilitados da linha (forma quality do AND atual, ADR-022); linha toda desabilitada → GOOD |
| PID (kernel standalone, `services/flow-runtime/.../blocks/pid.py`) | `_retido` (RF-553) → `min(UNCERTAIN, q_entradas)`, e **BAD quando não há valor retido anterior** (`v is None`, D7); execução ok → default D6 |
| PID (shell, `blocks/shell/block.py::_emit`) | ADR-039 vigente + emenda §4.1 (§7.1 abaixo); saídas OUT/BKCAL_OUT com semântica PRÓPRIA e BINÁRIA (OOS→BAD, senão GOOD; `bkcal_out` sempre GOOD) — mecanismo distinto do `_retido` do kernel, nunca `min(UNCERTAIN, ...)` |
| fuzzy | retenção (exceção ou saída não-finita) → `min(UNCERTAIN, q_entradas)`, e **BAD quando a porta nunca teve valor bom** (`v is None`, D7); execução ok → default D6 |
| MPC | portas de saída mantêm semântica atual; disponibilidade de MV (RF-626/ADR-028) INTOCADA — `mpc/availability.py` lê `tag.quality` do `ValueSnapshot`, não de porta |
| script | default D6 automático; sandbox cego a qualidade (D8) |
| opc_write | consumidor: suprime escrita se `not ok` (= `quality is not GOOD`) — comportamento atual |
| bus_publish | cold (`v is None`) não publica (como hoje); senão TRANSPORTA o Signal completo da entrada no payload (D9) |
| bus_subscribe | nunca-publicada → `Signal(None)`; fresca → quality/substatus/limites publicados; expirada (idade > 3×period_s) → `min(quality publicado, UNCERTAIN)` (D7; emenda ADR-042 D4, §7.2 abaixo) |
| calc-worker (tag calculada) | INTOCADO — já publica `max(quality)` das entradas na polaridade OpcValue (`runner.py`) |

## 6. Payloads (PRD §7.1 — linhas alteradas)

| canal | de | para |
|---|---|---|
| `flow.exchange` | `{key, ts, v, ok, period_s}` | `{key, ts, v, quality, substatus, hi_limited, lo_limited, period_s}` |
| `flow.status.<id>` (`ports`) | `{porta: {v, ok}}` | `{porta: {v, quality, substatus, hi_limited, lo_limited}}` |

`quality`/`substatus` nos payloads acima usam a polaridade Fieldbus (BAD=0/UNCERTAIN=1/GOOD=2) —
o vocabulário do domínio "porta". `opc.values.*`/`calc.values`/`flow.values` seguem `OpcValue`
inalterado (§2). Payloads pub/sub são transientes: deploy da stack inteira junto, sem janela de
compatibilidade dupla (ADR-002). Nenhuma DDL.

## 7. Emendas a decisões anteriores

### 7.1 ADR-039 §4.1 — `is_good`

O texto v1 ("`UNCERTAIN` é tratado como `GOOD` em toda decisão do shell") é substituído por
`is_good ≡ quality is Quality.GOOD` (D3, §3). Consequência direta: as regras 5–8 da tabela de
rebaixamento de modo (ADR-039 §4.3) passam a disparar de fato também em UNCERTAIN — antes desta
entrega isso nunca acontecia na prática, porque `opc_read` colapsava `quality != 0` em BAD antes do
valor alcançar o shell (§1); a regra v1 do §4.1 nunca executou. O comportamento de atuação do shell
está, portanto, **preservado** (uncertain já invalidava como BAD antes; continua invalidando agora,
só que pelo caminho correto). Nota de emenda cravada em `docs/adr/ADR-039-block-shell.md` §4.1, texto
original mantido por histórico.

### 7.2 ADR-042 D3/D4 — payload e expiração do `flow.exchange`

- **D3** (payload): o campo `ok` do `ExchangeValue` é substituído pelo `Signal` completo
  (`quality`, `substatus`, `hi_limited`, `lo_limited` — §6). Cold continua sem publicar; entrada
  com qualidade não-GOOD continua publicando, agora carregando o tri-state real em vez do booleano.
- **D4** (expiração): a saída do `bus_subscribe`, quando `idade > 3 × period_s`, deixa de ser
  "último valor com `ok=false`" e passa a ser **rebaixada por teto** — `min(quality publicado,
  UNCERTAIN)` — mantendo o último valor. Como `ok ≡ quality is GOOD` (D3/D5), uma saída expirada
  continua inválida para atuação (UNCERTAIN não é GOOD): o efeito prático em `opc_write`/MPC é
  idêntico ao anterior. A diferença é que uma origem que já publicava BAD antes de expirar continua
  BAD depois de expirar (teto, nunca elevação) em vez de colapsar em um `ok=false` indistinto —
  coerente com a monotonicidade de D7. Notas de emenda cravadas em
  `docs/adr/ADR-042-troca-de-variaveis-entre-flows.md` D3 e D4.

### 7.3 Spec F3 decisão A-6 — flag booleana → tri-state

A decisão A-6 da spec F3 ("motor executa com o valor e propaga a flag `ok`") passa a propagar o
`Signal` com tri-state completo em vez da flag booleana isolada. A semântica de "executa mesmo com
entrada inválida, e propaga o estado adiante" não muda — muda a granularidade do estado propagado.

## 8. Fora de escopo (explícito)

- `STATUS_OPTS` (política configurável de UNCERTAIN) — segue ADR-039 §9.
- Códigos novos de `Substatus`; semântica futura entra por ADR próprio.
- Mudança de payload em `opc.values`/`calc.values`/`flow.values` (substatus NÃO atravessa a
  borda OpcValue; perda documentada acima, §4/§6).
- Terceiro estado visual (uncertain) no frontend.
- RF-626/ADR-028 (disponibilidade de MV) — já lê qualidade da fonte certa (§5).
- Propagação de `substatus`/`hi_limited`/`lo_limited` por blocos de transformação (D9) — ADR
  futuro com regra de inversão por sinal de ganho.
- Emenda a RF-804/ADR-037 — persistência não muda (§4).
- Histórico NÃO distingue UNCERTAIN de BAD (ambos → `quality=2` → NULL): o tri-state vive
  só em porta, `flow.status`/WS e `flow.exchange`. Retirada parcial e consciente do que a
  pergunta de retenção do brainstorm oferecia ("valor retido historiado com quality=1"):
  persistir o valor congelado o injetaria em `avg`/`sum`/`samples_1m` (dano que o ADR-037
  escolheu NULL para evitar). Distinguir no histórico exigiria emendar ADR-037 para
  `quality != 0 → NULL` — ADR futuro, se algum dia for pedido.
- Persistência de substatus/limites; DDL de qualquer espécie.

## 9. Consequências

**Positivas**

- Um único tipo de porta (`Signal`) em todo o sistema: fim da bifurcação `PortSample`/`Signal` do
  ADR-039, sem promoção implícita nas arestas.
- UNCERTAIN e BAD tornam-se distinguíveis em `flow.status`/WS/`flow.exchange` — diagnóstico ganha
  granularidade sem tocar atuação nem persistência.
- Retenção deixa de ser "válido ou inválido": vira "válido, retido (UNCERTAIN) ou morto (BAD)",
  visível no canvas e no faceplate.
- Zero mudança de comportamento de atuação (`ok ≡ quality is GOOD` já era o efeito prático de
  `opc_read` colapsando uncertain em BAD) e zero mudança de persistência (§4) — a superfície de
  regressão da entrega é o payload/tipo, não a lógica de controle.
- `ottima-core` como único dono de `Quality`/`Substatus`: `blocks/shell/signal.py` (ADR-039) e a
  duplicação de enums somem.

**Negativas**

- Toda a superfície de código que lia `.ok`/`PortSample(v, ok)` precisou revisão (Tasks 1–5),
  ainda que o comportamento final seja idêntico — risco de regressão mecânica em ~60 call sites
  (D1), mitigado por `Signal` manter `ok` como propriedade derivada compatível.
- Payload de dois canais cresce de 2 para 5 campos (`flow.exchange`) e de `{v, ok}` para
  `{v, quality, substatus, hi_limited, lo_limited}` por porta (`flow.status`): mais bytes por
  varredura no barramento e no `/ws`, sem uso ainda pelo frontend além do que a spec F3 já previa
  (dessaturação em `quality !== GOOD`).
- Dois vocabulários de qualidade continuam coexistindo no sistema (`Quality` de porta vs.
  `OpcValue.quality` de campo) — a tradução nas bordas (§4) é o único lugar que precisa saber
  disso, mas um novo desenvolvedor pode confundi-los sem ler este ADR e o GLOSSARY.

**Neutras**

- `is_good`/`ok` continuam derivados, nunca campo — decisão D5 fecha a discussão sobre onde
  guardar o booleano de conveniência.
- A emenda ao ADR-039 §4.1 não altera nenhuma linha de código do shell além do tipo do campo
  `quality`: a lógica de comparação (`is_good`) já existia, só a definição muda.
