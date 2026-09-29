# ADR-039 — Shell de bloco de controle no padrão Fieldbus Foundation

**Status:** Proposto · 2026-08-31 · **Emenda leve ao ADR-024/RF-302** (arestas de retorno para `bkcal_in` saem da detecção de ciclo e do aviso de inversão) · Relacionado: ADR-007, ADR-010, ADR-011, ADR-015, ADR-020, ADR-024, ADR-029/030, ADR-031, ADR-034 · Specs: `SPEC_FUZZY_with_SHELL.md`, `SPEC_PID_with_SHELL.md`

## 1. Contexto

A única máquina de modos do sistema vive hoje dentro do bloco MPC (`MpcBlock`, ADR-010): eixos LOCAL/REMOTO × MAN/AUTO, com tracking e bumpless implementados ali dentro. Os blocos de controle do canvas — `pid` (ADR-031) e `fuzzy` (ADR-029) — são deliberadamente sem modos: float entra, float sai. Isso produz três problemas concretos:

1. **Semântica divergente.** "Manual" do MPC não existe nos blocos do canvas; um operador treinado em DeltaV não transfere intuição entre eles.
2. **Bumpless não reaproveitável.** O trabalho de tracking/bumpless do MPC está preso dentro do `MpcBlock`, porque não existe um contrato comum de estado de saída.
3. **Cascata sem protocolo.** Sem back-calculation, montar cascata entre dois blocos do canvas exige condicionais à mão (bloco Script) em cada malha, e cada malha erra de um jeito diferente.

O padrão de bloco funcional da IEC 61804 / Foundation Fieldbus resolve exatamente esse conjunto, é o que DeltaV, 800xA e CENTUM VP implementam, e o vocabulário já circula na casa: RCAS/CAS/ROUT são hoje os modos que o MPC escreve nos PIDs de PLC (ADR-010, glossário).

O elemento habilitador: o algoritmo de controle e a máquina de modos são separáveis — o algoritmo é função do erro; modo/tracking/cascata são estado que envolve essa função.

## 2. Forças

| Força | Implicação |
|---|---|
| Ambiente industrial regulado, on-premise | Semântica de modo auditável e familiar, não inventada |
| MPC escreve em malhas subordinadas | Alvo com semântica RCas e shed definido |
| Sintonia alterada online (hot-swap de engenharia, ADR-011) | Mudança de ganhos não pode produzir degrau na saída |
| flow-runtime asyncio: overrun **pula** fronteiras de grade (`scheduler.py`) | `dt` real varia; o contrato não pode assumir o período nominal |
| Blocos `pid`/`fuzzy` existem e estão em uso | Zero quebra de compatibilidade |
| Prototipagem rápida no React Flow | A versão simples, sem cerimônia de modos, continua existindo |
| ADR-011: sem versionamento, hot-swap | O shell precisa conviver com edição online, não com revisões |
| Infra existente: pub/sub, `events` (ADR-020), recorder, rotas `/api/operate` | Nenhuma infraestrutura paralela; tudo é espelho de padrão auditado |

## 3. Decisão

Adotar um **shell de bloco de controle** genérico, agnóstico de algoritmo, que envolve um **kernel** puro. Normativamente:

### D1 — Separação kernel/shell

Todo estado de modo, saída, tracking e cascata reside no shell. O kernel não conhece modo, saturação de saída nem cascata — possui apenas histórico interno do próprio algoritmo (erro anterior, estados de filtro).

### D2 — O contrato do kernel é incremental

`ControlKernel.compute()` retorna **du/dt em % do span de OUT por segundo**, nunca posição absoluta. O shell integra.

Razão: a forma incremental faz bumpless transfer, anti-windup, tracking e override caírem como consequência da aritmética, sem código de caso especial. O integrador fica no shell; qualquer coisa que escreva `u` diretamente já deixa o controlador alinhado.

Consequência aceita: kernels puramente posicionais precisam ser expressos em forma incremental ou envolvidos por adaptador.

### D3 — O kernel expõe `align()`

O shell chama `kernel.align(u, sp, pv)` **em todo scan em que não calcula** (modos forçados, tracking, saída inválida, scan perdido). Sem isso, sair de Manual após minutos produz pico derivativo de histórico obsoleto — o defeito clássico que separa implementação de laboratório da de produção.

### D4 — Valor e status trafegam juntos

Toda porta analógica de bloco malha é um `Signal` — extensão do `PortSample` existente com qualidade, substatus e bits de limitação. Bumpless de cascata e anti-windup encadeado são propriedades emergentes da propagação de status.

Interoperabilidade com o resto da paleta é **promoção implícita nas arestas** (§4.1), sem blocos conversores. `opc_write` continua suprimindo `ok=False` — saída BAD nunca vira escrita válida no PLC.

### D5 — Modo alvo e modo real são distintos

`MODE_BLK` contém `TARGET`, `ACTUAL`, `PERMITTED` e `NORMAL`. O operador escreve `TARGET`; o shell calcula `ACTUAL` a cada scan por rebaixamento em cascata de prioridade. A codificação de bits segue o FF: peso numérico maior = prioridade maior — máscara `PERMITTED` e ordem de prioridade saem da mesma representação.

### D6 — BKCAL é protocolo, com atraso de um scan — e aresta de retorno no editor

O caminho direto (`cas_in`) lê o valor do scan corrente e exige que o bloco a montante execute antes (`exec_order`, ADR-024). O caminho de retorno (`bkcal_in`) lê o valor do scan anterior do bloco a jusante. Um atraso de um scan no handshake é imperceptível e evita dependência circular na ordenação — é o comportamento dos sistemas comerciais.

**Emenda ao ADR-024/RF-302:** toda cascata fecha ciclo no grafo (`out→cas_in` + `bkcal_out→bkcal_in`), hoje vetado pelo editor. Aresta cujo **destino é porta `bkcal_in`** passa a ser classe **retorno**: excluída da detecção de ciclo e do aviso de inversão, renderizada tracejada. Sem isso o protocolo é inconstruível no canvas.

### D7 — `dt` é o intervalo medido, derivado pelo próprio shell

O scheduler já passa `ts` (fronteira real, relógio de parede) em `step()`; o shell deriva `dt = ts − ts_anterior` sozinho — **sem mudança no scheduler nem na base class**. Primeiro scan = inicialização (sem dt). O shell rejeita `dt ≤ 0` e `dt > MAX_DT` (padrão 10× o Ts nominal) como `SCAN_LOST`: alinha o kernel e mantém a saída.

Divergência deliberada do ADR-031 (dt nominal): as razões de lá valem para bloco posicional sem filtro derivativo. Na forma incremental, um scan pulado vira `dt = 2·Ts` integrado corretamente, e ruído de relógio no termo D é tratado pelo filtro `Tf` do kernel. Blocos kernel continuam com Ts nominal; o ADR-031 não é alterado.

### D8 — Dois blocos por algoritmo na paleta

- **Bloco kernel** (`pid`, `fuzzy`): como estão hoje, sem nenhuma alteração. Prototipagem, estudo, composição.
- **Bloco malha** (`pid_loop` — "PID Malha"; `fuzzy_loop` — "Fuzzy Malha"): o kernel envolvido pelo shell. Malhas de produção.

"Shell" é termo de arquitetura interna (`BlockShell`); o usuário vê "malha".

### D9 — O shell é único e compartilhado

Uma implementação (`ottima_flow_runtime.blocks.shell.BlockShell`). PID e Fuzzy diferem só no kernel injetado; um novo algoritmo ganha a semântica completa implementando o protocol `ControlKernel`.

### D10 — `BIAS_IN` somado após o integrador

Feedforward soma **posição**, não taxa — colocá-lo no kernel exigiria derivar sinal medido, amplificando ruído onde é menos aceitável. O integrador guarda `u_int` (parcela de realimentação); `OUT = u_int + bias`. Modos forçados retrocalculam `u_int = clamp(forced) − bias`; mudança de config que altera o bias rebaseia `u_int = u − bias_novo` no mesmo scan — a saída total nunca dá degrau. Porta genérica (feedforward, bias de operador, termo de outro bloco), disponível em todo bloco malha.

### D11 — Config no `graph_json`, hot-swap em duas classes, sem versionamento

Compatível com o ADR-011: nenhuma tabela de revisão. A config do bloco malha divide-se em:

- **Classe de sintonia** (ganhos, limites, rates, filtros, opções): aplicada **in-place** no hot-swap, preservando modo, `u` e histórico do kernel. É o que torna sintonia online sem degrau um caminho real (hoje qualquer edição re-instancia o bloco e zera estado).
- **Classe estrutural** (`.fll`, `OUT_SCALE`): re-instancia o bloco; se `ACTUAL` era calculante, o bloco novo **aterrissa em `MAN`** com `u` mantido + evento. (O hot-swap de flow é atômico — não há como rejeitar um bloco isolado; "exigir Manual antes" vira aterrissagem forçada, bumpless.)

Auditoria: diff de config (autor, antes/depois) no log de eventos (ADR-020). Cada spec lista as classes campo a campo.

## 4. Contratos normativos

As specs de FUZZY e PID referenciam esta seção e não a redefinem.

### 4.1 Status

```python
# services/flow-runtime/src/ottima_flow_runtime/blocks/shell/signal.py

class Quality(IntEnum):
    BAD       = 0
    UNCERTAIN = 1
    GOOD      = 2

class Substatus(IntEnum):
    NON_SPECIFIC   = 0
    INIT_REQUEST   = 1   # IR: o bloco a jusante nao esta aceitando cascata
    NOT_INVITED    = 2   # reservado ao CONTROL_SELECTOR (secao 9)
    LOCAL_OVERRIDE = 3
    SENSOR_FAILURE = 4
    CONFIG_ERROR   = 5
    DEVICE_FAILURE = 6

@dataclass(slots=True)
class Signal:            # extensao do PortSample existente
    value:      float     = math.nan
    quality:    Quality   = Quality.BAD
    substatus:  Substatus = Substatus.NON_SPECIFIC
    hi_limited: bool      = False
    lo_limited: bool      = False

    @property
    def is_good(self) -> bool: ...
    @property
    def init_request(self) -> bool: ...
```

- v1: `UNCERTAIN` é tratado como `GOOD` em toda decisão do shell (`STATUS_OPTS`: §9).

> **Emendado pelo ADR-043:** UNCERTAIN invalida atuação (`is_good` ≡ `quality is GOOD`). Texto original mantido por histórico.
- Promoção implícita nas arestas, feita pelo runtime: `(v, ok)` → `Signal(v, GOOD|BAD)`; `Signal` → `(value, is_good)`.

### 4.2 Modos

```python
# services/flow-runtime/src/ottima_flow_runtime/blocks/shell/mode.py

class Mode(IntFlag):
    """Pesos FF. Valor numerico maior = prioridade maior."""
    OOS   = 0x80   # out of service
    IMAN  = 0x40   # initialization manual, imposto pelo bloco a jusante
    LO    = 0x20   # local override, imposto por intertravamento
    MAN   = 0x10   # operador escreve OUT
    AUTO  = 0x08   # SP local
    CAS   = 0x04   # SP de cas_in
    RCAS  = 0x02   # SP de rcas_in (supervisor, MPC)
    ROUT  = 0x01   # OUT de rout_in (supervisor)

@dataclass(slots=True)
class ModeBlock:
    target:    Mode = Mode.MAN
    actual:    Mode = Mode.OOS
    permitted: Mode = Mode.OOS | Mode.MAN | Mode.AUTO
    normal:    Mode = Mode.AUTO
```

`CALCULATING_MODES = {AUTO, CAS, RCAS}` — só nesses modos o kernel executa; os demais são forçados.

### 4.3 Rebaixamento de modo

Avaliado na ordem; a primeira condição verdadeira vence. Regras 3, 6, 7 e 8 pressupõem a porta correspondente **ligada** — a validação de save exige porta ligada para cada modo remoto presente em `PERMITTED` (`bkcal_in` desconectado ⇒ nunca `IMAN`).

| Ordem | Condição | ACTUAL resultante |
|---|---|---|
| 1 | Bloco desabilitado, `TARGET == OOS`, ou `kernel.validate()` com erros | `OOS` |
| 2 | `TARGET` fora de `PERMITTED` | `NORMAL` + evento `mode.rejected` |
| 3 | `bkcal_in.init_request` e `TARGET != OOS` | `IMAN` |
| 4 | `lo_in_d` ativo | `LO` |
| 5 | `PV.quality == BAD` e `TARGET ∈ CALCULATING_MODES` | `MAN` + substatus `SENSOR_FAILURE` |
| 6 | `TARGET == CAS` e `cas_in` não é GOOD | conforme `SHED_OPT` |
| 7 | `TARGET == RCAS` e `rcas_in` não é GOOD | conforme `SHED_OPT` |
| 8 | `TARGET == ROUT` e `rout_in` não é GOOD | conforme `SHED_OPT` |
| — | nenhuma acima | `TARGET` |

`SHED_OPT ∈ {SHED_TO_AUTO (padrão), SHED_TO_MAN, SHED_TO_NORMAL}` + flag `SHED_NO_RETURN` (padrão `false`).

Semântica: shed muda **só `ACTUAL`**, com **retorno automático** quando a condição limpa — coerente com a retomada automática do ADR-025. Com `SHED_NO_RETURN`, o `TARGET` é reescrito para o destino do shed e o re-engajamento vira ato explícito do operador/supervisor. Não há verificação de idade de `rcas_in`/`rout_in` na v1: portas ligadas degradam por quality (fonte morta ⇒ `ok=False` ⇒ regra 7/8); o caminho escrito supervisório, com `SHED_RCAS` por idade, fica no §9.

Toda transição de `ACTUAL` gera evento (§4.10) e vira série de estado em `loop_samples`.

### 4.4 Saída forçada

Em modos não calculantes o shell escreve `u` diretamente e chama `kernel.align()`. Avaliado na ordem:

| Modo / condição | `u` recebe |
|---|---|
| `OOS` | mantém o valor; OUT sai com quality `BAD` (escrita a jusante suprimida — fail-safe físico é papel do PLC + watchdog, ADR-009) |
| `IMAN` | `unscale(bkcal_in.value)` |
| `LO` | `LO_VAL` |
| `MAN` | `MAN_OUT` |
| `ROUT` | `unscale(rout_in.value)` (`rout_in` em EU de OUT) |
| Modo calculante + `trk_in_d` + `TRACK_ENABLE` | `TRK_VAL` |
| `MAN` + `trk_in_d` + `TRACK_IN_MANUAL` | `TRK_VAL` |

Na entrada em `MAN`, `MAN_OUT` é inicializado com o `u` corrente — a escrita do operador passa a valer depois; a transição nunca salta. Valores forçados internos (`MAN_OUT`, `TRK_VAL`, `LO_VAL`, `OUT_STARTUP`) são em % do span de OUT. `FSTATE_*` e `BYPASS` não existem na v1 (cortados: `FSTATE_VAL` nunca chegaria ao PLC — a escrita é suprimida em BAD; `BYPASS` é nicho sem demanda).

### 4.5 Protocolo do kernel

```python
# services/flow-runtime/src/ottima_flow_runtime/blocks/shell/kernel.py

class ControlKernel(Protocol):

    def compute(self, sp: float, pv: float, dt: float) -> float:
        """Retorna du/dt em % do span de OUT por segundo.

        Pode retornar NaN para sinalizar que o algoritmo nao produziu
        resultado valido neste scan. O shell trata NaN mantendo a saida
        e levantando alarme; nunca propaga NaN para OUT.
        """

    def align(self, u: float, sp: float, pv: float) -> None:
        """Realinha o historico interno para o estado corrente.

        Chamado pelo shell a cada scan em que compute() nao executa.
        Apos align(), a proxima chamada a compute() nao pode produzir
        transiente derivado de historico obsoleto.
        """

    def reset(self) -> None:
        """Descarta todo historico interno."""

    def validate(self) -> list[str]:
        """Lista de erros de configuracao. Vazia = kernel apto a operar."""
```

O sentido de ação (direto/reverso) é **configuração do kernel**, não do shell — `CONTROL_OPTS.DIRECT_ACTING` é encaminhado na construção. Para o PID a inversão é troca de sinal do erro; para o Fuzzy depende da simetria da base de regras, e só o kernel sabe aplicá-la.

### 4.6 Escala de OUT

`u` interno é sempre em % (entre `OUT_LO_LIM` e `OUT_HI_LIM`, default 0–100). A porta `out` emite `scale(u, OUT_SCALE)`; `OUT_SCALE = (lo, hi)` em EU, default `(0, 100)` (identidade). Cascata: `OUT_SCALE` do primário = faixa de SP (EU de PV) do secundário — sem isso as unidades da cascata não fecham. Entradas que carregam posição de OUT (`bkcal_in`, `rout_in`) passam por `unscale` na chegada.

### 4.7 Shell de referência

```python
# services/flow-runtime/src/ottima_flow_runtime/blocks/shell/block.py

class BlockShell:

    def execute(self, io: BlockIO, ts: datetime) -> BlockIO:
        dt = self._measure_dt(ts)                    # D7: derivado de ts
        if dt is None or not (0.0 < dt <= self.cfg.max_dt):
            if dt is not None:
                self.alarm("SCAN_LOST", dt=dt)
            self.kernel.align(self.u, self.sp, self.pv)
            return self._emit()

        # 1. PV filtrado (PV_FTIME)
        self.pv = self._filter_pv(io.in_, dt)

        # 2. TARGET -> ACTUAL  (secao 4.3)
        self.mode.actual = self._resolve_mode(io)
        m = self.mode.actual

        # 3. resolucao e limitacao de SP  (secao 4.8)
        self.sp = self._resolve_sp(m, io, dt)

        # 4. bias (D10); 0.0 com a porta desligada
        bias = self._resolve_bias(io.bias_in)

        # 5. modos forcados: escreve u, alinha o kernel, sai  (secao 4.4)
        forced = self._forced_output(m, io)
        if forced is not None:
            self.u = clamp(forced, self.cfg.out_lo_lim, self.cfg.out_hi_lim)
            self.u_int = self.u - bias
            self.kernel.align(self.u, self.sp, self.pv)
            self.u_prev = self.u              # zera o rate limiter de OUT
            return self._emit()

        # 6. kernel
        du_dt = self.kernel.compute(self.sp, self.pv, dt)
        if not math.isfinite(du_dt):
            self.alarm("KERNEL_INVALID_OUTPUT", reason=self.kernel_reason())
            self.kernel.align(self.u, self.sp, self.pv)
            return self._emit()               # segura OUT, nunca propaga NaN

        # 7. integracao, rate limit, saturacao (= anti-windup)
        u = self._apply_out_rate_limit(self.u_int + du_dt * dt + bias, dt)
        self.u = clamp(u, self.cfg.out_lo_lim, self.cfg.out_hi_lim)
        self.u_int = self.u - bias            # o integrador nunca passa do limite
        self.u_prev = self.u
        return self._emit()

    def _emit(self) -> BlockIO:
        cfg, m = self.cfg, self.mode.actual
        hi = self.u >= cfg.out_hi_lim
        lo = self.u <= cfg.out_lo_lim

        out = Signal(
            value      = scale(self.u, cfg.out_scale),
            quality    = Quality.BAD if m is Mode.OOS else Quality.GOOD,
            substatus  = Substatus.LOCAL_OVERRIDE if m is Mode.LO
                         else Substatus.NON_SPECIFIC,
            hi_limited = hi,
            lo_limited = lo,
        )

        # BKCAL_OUT carrega o SP de trabalho para o bloco a montante.
        # Bits de limitacao invertem sob acao direta: saturar OUT limita
        # o SP no sentido oposto.
        d = cfg.direct_acting
        bkcal = Signal(
            value      = self.pv if cfg.use_pv_for_bkcal else self.sp,
            quality    = Quality.GOOD,
            substatus  = Substatus.NON_SPECIFIC if m is Mode.CAS
                         else Substatus.INIT_REQUEST,
            hi_limited = lo if d else hi,
            lo_limited = hi if d else lo,
        )
        return BlockIO(out=out, bkcal_out=bkcal)
```

Nenhuma transição de modo aparece como condicional explícito. Critério de revisão: **um `if` que testa uma transição específica de modo no shell é defeito de projeto.**

### 4.8 Resolução de SP

| Modo | Fonte do SP | Limitação |
|---|---|---|
| `AUTO` | SP do operador (persistido em `loop_setpoints`) | `SP_HI/LO_LIM` + `SP_RATE_UP/DN` |
| `CAS` | `cas_in.value` | `SP_HI/LO_LIM` (sem rate) |
| `RCAS` | `rcas_in.value` | `SP_HI/LO_LIM` (sem rate) |
| Forçados | mantém; com `SP_PV_TRACK_IN_MAN` (default ON), SP segue PV | — |

### 4.9 CONTROL_OPTS

`{DIRECT_ACTING, SP_PV_TRACK_IN_MAN (default ON), USE_PV_FOR_BKCAL, TRACK_ENABLE, TRACK_IN_MANUAL}`.

### 4.10 Eventos, telemetria, operação e partida

Tudo é espelho de padrão existente — nenhum mecanismo novo:

- **Eventos** no pipeline `events` (ADR-020, pub/sub — não existem Redis Streams na casa) via `publish_event`, kinds novos: `KIND_LOOP_MODE_CHANGED` (`from`, `to`, `reason`), `KIND_LOOP_SHED` (`target`, `actual`, `shed_opt`), `KIND_LOOP_MODE_REJECTED`, `KIND_LOOP_ALARM` (`code`, `payload`), `KIND_LOOP_LIMITED` (`hi`, `lo`).
- **Estado vivo** em `loop.state.<flow_id>.<block_id>` (`LoopState` Pydantic em `_WS_MODELS`, throttle ~4 Hz), chave `loop_state` no `/ws` — espelho do ADR-030.
- **Histórico**: `PatternListener` em `loop.state.*` no recorder → hypertable `loop_samples` (ts, flow_id, block_id, var_id, v) + CAgg 1 min; `var_id ∈ {pv, sp, out, mode}`, `mode` gravado na transição.
- **Persistência de operação**: upsert `loop_setpoints` (flow_id, block_id → `target`, `sp`, `man_out`) — espelho de `mpc_setpoints`. No deploy, `sp` e `man_out` são restaurados; **`TARGET` sempre nasce `MAN`** (re-engajar é ato do operador) e `u = OUT_STARTUP` (default 0 %). Hot-swap preserva estado por id (ADR-011); stop→deploy é partida fria.
- **Operação**: `POST /api/operate/{flow_id}/{block_id}/mode|sp|out` (`out` é novo; `mode`/`sp` reusam o padrão MPC), `require_operator`, 202-async via `FlowCommand` — o runtime materializa e audita ("Comandado ≠ confirmado", RNF-05). A API valida `PERMITTED` estaticamente contra a config (422); o runtime se defende (regra 2 da §4.3). **Sintonia é edição de flow** (`PUT /api/flows/{id}`, admin) na classe de sintonia do D11.
- A escrita física continua por `opc_write` + watchdog (ADR-009); o shell nunca escreve OPC diretamente.

## 5. Mapeamento com o MPC (ADR-010)

Dois vocabulários coexistem: o MPC mantém LOCAL/REMOTO × MAN/AUTO; malhas usam o modelo FF. Unificar o MPC fica fora deste ADR.

| Situação | Lado MPC | Lado da malha interna |
|---|---|---|
| MPC comanda malha interna | REMOTO+AUTO | `TARGET = RCAS`; MV → `rcas_in` (aresta comum do grafo) |
| Operador escreve MV do MPC | REMOTO+MAN | permanece `RCAS` — o valor manual flui pela mesma porta |
| MPC indisponível / erro | — | `rcas_in` não-GOOD ⇒ shed (regra 7) |
| MPC em LOCAL | PID de PLC comanda | coreografia completa de assunção/devolução para malha **interna** (readback via `bkcal_out`, análogo ao MV-tracking do ADR-010) é trabalho futuro (§9); a v1 cobre o shed por quality |

## 6. Consequências

**Positivas**

- Uma implementação de bumpless, anti-windup e cascata serve PID, Fuzzy e qualquer kernel futuro.
- Cascata entre blocos do canvas = duas arestas (`out→cas_in`, `bkcal_out→bkcal_in`), sem configuração adicional.
- O MPC ganha um alvo com contrato definido (`rcas_in` + shed por quality).
- Sintonia online sem degrau **por construção** (D2 + D11), exercida pelo hot-swap de engenharia.
- Vocabulário de faceplate idêntico a DeltaV/800xA/CENTUM: treinamento de operador transferível.
- Anti-windup atravessa a cascata inteira pelos bits de limitação.
- Zero infraestrutura nova: eventos, recorder, rotas e WS reusam padrões auditados.

**Negativas**

- O shell é substancialmente mais complexo que os blocos atuais; sem os testes da §7, regressões serão sutis.
- Bloco malha tem ~25 parâmetros contra 5–10 dos kernels — a UI precisa de agrupamento e bons defaults.
- Atraso de 1 scan no caminho BKCAL: handshakes de cascata estabilizam em 2–3 scans. Aceito.
- Kernels precisam ser reescritos em forma incremental.
- Dois blocos por algoritmo dobram superfície de documentação e teste.
- A emenda ao ADR-024 (arestas de retorno) toca a validação do editor.

**Neutras**

- `PERMITTED` validado na API; o runtime apenas se defende.
- Bits de `Mode` = FF: interoperar com host FF real um dia é mapeamento identidade.
- Retenção de auditoria = 1 mês (ADR-020) vale também para diffs de sintonia. Aceito.

## 7. Critérios de aceitação do shell

Executados contra um **kernel stub determinístico** e depois contra cada kernel real. `ε = 0.01 %` do span de OUT.

| ID | Cenário | Critério |
|---|---|---|
| S1 | Man → Auto com `PV ≠ SP` | `\|OUT(k) − OUT(k−1)\| ≤ ε` no primeiro scan |
| S2 | Auto → Man → Auto, 120 s em Man | Sem degrau nas duas transições |
| S3 | `trk_in_d` ativado e liberado | `OUT == TRK_VAL` durante; sem degrau ao liberar |
| S4 | Erro sustentado até saturar, depois invertido | `OUT` deixa o limite em ≤ 1 scan |
| S5 | Bloco a jusante em Man | Montante em `IMAN` em ≤ 2 scans, `OUT == unscale(bkcal_in.value)` |
| S6 | Bloco a jusante volta para Cas | Montante volta para `CAS` sem degrau no SP a jusante |
| S7 | `cas_in` degrada para BAD | Shed em ≤ 1 scan, `OUT` contínuo; retorno automático ao limpar |
| S8 | `rcas_in` degrada para BAD | Shed conforme `SHED_OPT`, `OUT` contínuo |
| S9 | `lo_in_d` ativado e liberado | `OUT == LO_VAL` durante; retoma sem degrau |
| S10 | `PV.quality → BAD` e retorno | `ACTUAL == MAN`, `OUT` mantido, retomada bumpless |
| S11 | Jitter de `dt` de ±30 % por 300 s | Regime idêntico ao caso sem jitter dentro de 0.5 % |
| S12 | Kernel retorna NaN | `OUT` mantido, alarme emitido, `ACTUAL` inalterado |
| S13 | *(adiado — requer `CONTROL_SELECTOR`, §9)* | — |
| S14 | `dt = 0` e `dt > MAX_DT` | `SCAN_LOST`, `OUT` mantido, sem exceção |
| S15 | Hot-swap de classe de sintonia em Auto, erro ≠ 0 | Sem degrau; modo e estado preservados |
| S16 | Hot-swap estrutural com `ACTUAL == AUTO` | Aterrissa em `MAN`, `u` mantido, evento emitido |
| S17 | `SHED_NO_RETURN = true`, `cas_in` BAD e retorna | `TARGET` reescrito; sem retorno automático a `CAS` |

## 8. Alternativas consideradas

**A. Manter lógica de modo dentro de cada algoritmo.** Rejeitada — estado atual, origem dos três problemas da §1; custo cresce com algoritmos × recursos.

**B. Só o modelo de bloco da IEC 61131-3.** Rejeitada — define encapsulamento, não semântica de modo, status nem back-calculation.

**C. Pilha FF completa (link objects, dicionário).** Rejeitada por escopo — precisamos da semântica de bloco, não de interoperar como dispositivo FF.

**D. Kernel posicional com bias de bumpless.** Rejeitada — funciona para Manual/Auto e falha em tracking, override e cascata; produz degrau na alteração online de ganhos.

**E. Substituir os blocos existentes.** Rejeitada — quebraria projetos em campo e a ergonomia de prototipagem.

## 9. Escopo excluído (trabalho subsequente)

- Bloco `CONTROL_SELECTOR` com `bkcal_out` múltiplo (necessário para S13 e override real; `Substatus.NOT_INVITED` reservado para ele).
- Blocos discretos (DI/DO) e sua semântica de modo.
- Kernel de MPC dentro do shell — o contrato du/dt não descreve um controlador de trajetória; exigirá segundo protocolo de kernel.
- Coreografia completa MPC ↔ malha interna (assunção/devolução com readback via `bkcal_out`).
- Caminho **escrito** (supervisório externo) para `rcas_in`/`rout_in`, com `SHED_RCAS` por idade.
- Cascata multirate (entre flows com Ts distintos).
- `STATUS_OPTS` (política configurável para `UNCERTAIN`).
- Alarmes de processo (PV HI/LO) no shell.
- Agente externo de sintonia adaptativa e seus guardrails (enable, limites, rate-limit, monitor de oscilação, rollback).
- Redundância e sincronização de estado entre instâncias do flow-runtime.
- Interoperabilidade com hosts FF ou HART reais.

## 10. Referências

- IEC 61804-2, *Function Blocks for Process Control*
- Fieldbus Foundation FF-891, *Function Block Application Process, Part 2*
- ISA-5.1 e ISA-51.1 (formas de PID e sentido de ação)
- ADR-010 (modos MPC), ADR-011 (hot-swap sem versionamento), ADR-020 (log de eventos), ADR-024 (exec_order), ADR-029/030 (bloco fuzzy), ADR-031 (bloco pid), ADR-034 (espelho de contratos)
- `SPEC_FUZZY_with_SHELL.md`, `SPEC_PID_with_SHELL.md`
