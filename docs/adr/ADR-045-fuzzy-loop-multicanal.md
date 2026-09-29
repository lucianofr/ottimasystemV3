# ADR-045 — Fuzzy Malha multicanal (`fuzzy_loop` MIMO com contrato FLL posicional)

**Status:** Proposto · 2026-09-21 · **Emenda ao ADR-039 D8/D9** (o `fuzzy_loop` deixa de ter as mesmas portas do `pid_loop`) **e à `SPEC_FUZZY_with_SHELL.md` §3.2, §5.3, §6, §8 e §9** · Relacionado: ADR-002, ADR-011, ADR-024, ADR-029, ADR-034, ADR-040, ADR-043

## 1. Contexto

O `fuzzy_loop` do ADR-039 é SISO por contrato: o `.fll` precisa ter exatamente `e`, `de` e `du` (SPEC §3.2), e o bloco herda as portas do `pid_loop` (`in`, `cas_in`, `rcas_in`, `rout_in`, `bkcal_in/out`, `bias_in`, `trk_in_d`, `lo_in_d`, `out`). Isso gera três problemas:

1. **Diverge da filosofia do bloco `fuzzy` (ADR-029).** No `fuzzy`, a contagem de entradas/saídas é configurável, a base de regras é um texto FLL livre e o nome das variáveis não importa, só a posição. No `fuzzy_loop` o engenheiro não escolhe nada disso.
2. **Não controla processo acoplado.** Num processo MIMO (duas vazões num mesmo coletor, temperatura e nível num mesmo vaso), cada saída mexe em mais de uma PV. Com N blocos SISO independentes, cada base de regras só vê o próprio erro. Regras de desacoplamento, do tipo "se o erro 2 está grande e subindo, reduza a ação no canal 1", não têm onde morar.
3. **Não tem formulário no canvas.** Os ganhos (`KE`/`KDE`/`KU`/`TF_DE`), os limites e o FLL só são editáveis pelo JSON do grafo.

## 2. Decisão

### D1 — `n_loops` canais por bloco

`FuzzyLoopConfig.n_loops: int`, com valor entre 1 e `MAX_FUZZY_LOOPS = 4` e default 1. É chave **estrutural** (`LOOP_STRUCTURAL_KEYS`): mudar a contagem re-instancia o bloco, que aterrissa em MAN se estiver calculando (ADR-039 D11). O teto 4 limita o custo da superfície no save (D6) e o tamanho do faceplate. Subir o teto é uma mudança de constante, sem ADR.

### D2 — Contrato FLL posicional

Substitui a tabela da SPEC §3.2:

| Requisito | Valor |
|---|---|
| Variáveis de entrada | exatamente `2·n_loops`, **em ordem**: `e_1, de_1, e_2, de_2, …` (entrada `2c` = erro do canal `c`, entrada `2c+1` = derivada), com nomes livres |
| Variáveis de saída | exatamente `n_loops`, em ordem: `du_1 … du_n`, com nomes livres |
| Faixa, `lock-range`, `lock-previous: false`, `default: nan`, um RuleBlock | inalterados em relação à v2.0 |

- Os códigos de erro que dependiam de nome (`E`/`DE`/`DU`) saem. Entram `FLL_INPUT_COUNT_MUST_BE_2N_LOOPS` e `FLL_OUTPUT_COUNT_MUST_BE_N_LOOPS`.
- Com `n_loops = 1` o default continua sendo `FUZZY_LOOP_DEFAULT_FLL`, byte a byte. Para `n > 1`, `fuzzy_loop_default_fll(n)` gera N cópias diagonais da base padrão, sem regras cruzadas. Esses textos são exportados ao espelho TS (ADR-034, `default_fll_mimo`), porque o frontend nunca compõe FLL.

### D3 — Um motor, um `process()` por varredura

O kernel implementa o protocolo `MultiControlKernel` (`compute_all(sp, pv, dt) → du[]` e `align_all`). Todos os canais alimentam o mesmo `Engine` e são avaliados numa **única** chamada a `process()`. O custo por varredura continua o do SISO.

É isso que permite regras cruzadas: a base enxerga todos os `e_i`/`de_i` ao mesmo tempo. Os filtros de derivada e o `e_prev` ficam por canal. `rule_fire_count` é do motor inteiro.

### D4 — Modo por bloco; SP, OUT e MAN_OUT por canal; sem cascata

- **Portas:** `pv_1..pv_n` (entradas, todas obrigatórias) e `out_1..out_n` (saídas). As portas são dinâmicas no contrato exportado (`dynamic: true`, `count_field: n_loops`).
- **Modo:** existe um `MODE_BLK` por bloco. Os canais entram e saem de AUTO juntos. Um processo acoplado com metade dos canais em MAN não é o processo para o qual a base de regras foi escrita.
- **Por canal:** SP, `MAN_OUT`, integrador, anti-windup e rate limit. Os comandos de operação ganham o campo `channel`; valor fora de `0..n_loops-1` retorna 422.
- **Sem portas remotas no v2:** `cas_in`, `rcas_in`, `rout_in`, `bkcal_in/out`, `bias_in`, `trk_in_d` e `lo_in_d` saem. Por isso `permitted ⊆ {oos, man, auto}` e `normal ∈ {man, auto}`. Para o `fuzzy_loop`, isso supersede as partes do ADR-039 §4.2/§4.3 que dependem de modo remoto (shed de CAS/RCAS/ROUT, IMAN por `bkcal_in`, LO por `lo_in_d`).
- **`pid_loop` não muda:** continua SISO, com todas as portas do ADR-039. O shell (`BlockShell`) continua único (D9). O comportamento multicanal liga pela flag `channel_ports` e, com um canal, degenera exatamente no caminho SISO.

### D5 — Falha segura é do bloco, não do canal

- PV não-GOOD (ADR-043) em **qualquer** canal rebaixa o **bloco inteiro** para MAN.
- `du` não-finito em qualquer canal **mantém todas** as saídas e levanta `KERNEL_INVALID_OUTPUT`. Nenhum canal escreve enquanto outro está inválido, porque, num processo acoplado, mexer num canal perturba o outro.

### D6 — Portões de superfície por canal

A fatia inspecionável é sempre 2D. `sample_surface(fll, res, n_loops, channel)` varre `(e_c, de_c)` e mantém as demais entradas em zero. Os portões da SPEC §5.3 rodam **em cada canal**, e a mensagem de erro cita o canal.

O custo do save fica em `n_loops × resolução²` avaliações. No pior caso (4 × 257²) isso dá cerca de 264 mil avaliações, a mesma ordem de grandeza do teto FUZZY-SEC.

### D7 — Barramento, persistência e histórico

- **Sem canal novo** (ADR-002). O `LoopState` ganha o campo `channel`, com default 0, e o bloco publica um `LoopState` por canal no **mesmo** canal do barramento.
- **Recorder:** o `var_id` do canal 0 continua `pv`/`sp`/`out`/`mode`. Os demais canais ganham sufixo: `pv:1`, `sp:1` e assim por diante. Histórico SISO existente não muda de nome, e `/api/history/loop` aceita o sufixo.
- **`loop_setpoints`:** a PK passa a ser `(flow_id, block_id, channel)`. A migration de dados sobre `flows.graph_json` (mesmo padrão da 0009) converte os `fuzzy_loop` SISO gravados:
  - `in` vira `pv_1` e `out` vira `out_1`;
  - os modos remotos saem de `permitted`/`normal`.

  Arestas em portas extintas **não são apagadas**. Um `lo_in_d` é intertravamento, e sumir com ele em silêncio é pior que o flow ser rejeitado na carga com erro de handle explícito (lado seguro: flow parado).

  O downgrade aborta com mensagem clara se existir bloco com `n_loops > 1`.

### D8 — Superfícies de UI

- **Canvas:** formulário próprio (`CamposMalhaFuzzy`) com canais, sentido de ação, KE/KDE/KU/TF_DE, limites e o texto FLL. Ao trocar `n_loops`, o FLL só é reescrito se ainda for uma base default; FLL autoral nunca é sobrescrito.
- **Página MALHA (`/operacao/loop`):** o seletor de modo continua único. Cada canal tem sua seção (`loop-canal-{i}`) com PV/SP/OUT, escrita de SP/OUT e heatmap da própria fatia (`surface?channel=`).

## 3. Alternativas rejeitadas

- **N blocos `fuzzy_loop` SISO lado a lado.** Não há regra cruzada possível (cada motor vê só o seu erro), os modos ficam independentes e o operador pode pôr metade do processo acoplado em AUTO.
- **Multicanal com cascata por canal.** Exigiria multiplicar as portas remotas por canal (`cas_in_i`, `bkcal_out_i`…) e decidir se o modo CAS é por bloco ou por canal. Fica adiado até existir um caso de uso: cascata sobre MIMO é mestre de um conjunto de escravos, e o `pid_loop` SISO já cobre a cascata clássica.
- **Contrato por nome (`e1`, `de1`, `du1`…).** Contraria o ADR-029, em que o FLL do bloco `fuzzy` é posicional. Os dois blocos passariam a ter regras diferentes para o mesmo texto.

## 4. Consequências

**Positivas**
- O `fuzzy_loop` passa a controlar processos acoplados, com regras de desacoplamento escritas pelo engenheiro na própria base.
- O FLL e os parâmetros ficam editáveis no canvas.
- Contrato de FLL igual para `fuzzy` e `fuzzy_loop`.
- O custo por varredura não cresce com `n_loops`.

**Negativas**
- O `fuzzy_loop` perde cascata, feedforward (`bias_in`), tracking (`trk_in_d`) e intertravamento local (`lo_in_d`). Quem precisar desses recursos usa o `pid_loop`, ou um `fuzzy_loop` com `n_loops = 1` e a lógica equivalente fora do bloco. Isso é uma regressão de capacidade em relação ao ADR-039 D8 e é o principal ponto a validar na revisão desta ADR.
- Flows gravados com arestas nessas portas passam a ser rejeitados na carga (ficam parados, com erro explícito) até serem editados.
- Um canal com PV ruim tira o bloco inteiro de AUTO (D5). É a escolha conservadora para processo acoplado, mas é mais restritiva que N blocos SISO.

## 5. Emendas pendentes (aplicar junto com o aceite)

- **ADR-039 D8/D9:** registrar que o `fuzzy_loop` não espelha mais as portas do `pid_loop`. O teste `test_contrato_de_portas_espelha_o_pid_loop` foi removido.
- **SPEC_FUZZY:**
  - §3.2: substituir pela tabela do D2.
  - §5.3: portões por canal (D6).
  - §6.1: retirar as portas remotas e adicionar `N_LOOPS`.
  - §6.3: `N_LOOPS` passa a ser estrutural.
  - §8: a migration `0015_loop_tables` deixa de ser a única, porque esta ADR acrescenta a migration de canal (D7), e o nó ganha portas por canal.
  - §9: F1 cobre os códigos novos de contagem; incluir o cenário MIMO acoplado (`test_fuzzy_loop_mimo.py`).
- **Rebase no `main`:**
  - A migration desta branch nasceu como `0016_loop_setpoints_channel` e colide com a `0016_historized_vars` do `main`. Ela vira `0017_…` com `down_revision = "0016_historized_vars"`.
  - O shell precisa ser reconciliado com o `Signal` do ADR-043. Esta branch ainda tem `is_good = quality is not BAD` (UNCERTAIN tratado como GOOD); no `main`, `is_good` só é verdadeiro para GOOD e as regras de shed 5–8 disparam também em UNCERTAIN. O `pv_ok` por canal do D5 tem de ser re-derivado sobre essa regra.
  - A garantia "o `pid_loop` segue byte a byte no caminho SISO" foi conferida contra `bd1489c`, não contra o `block.py` atual do `main`: refazer essa conferência depois do rebase.
- **ADR-040:** com a aresta de realimentação, a demo MIMO (`scripts/setup-malha-fuzzy.py`) poderia fechar a malha no canvas em vez de pelo OPC. Ela continua fechando pelo OPC, que é o mesmo caminho da suíte RNF-09 e exercita watchdog e escrita.
