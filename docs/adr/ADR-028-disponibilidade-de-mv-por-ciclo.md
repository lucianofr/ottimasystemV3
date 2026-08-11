# ADR-028 — Disponibilidade de MV por ciclo e modo degradado do MPC (emenda o ADR-010 e o RF-604)

**Status:** Aceito · 2026-08-10 · **Emenda o ADR-010** (bumpless deixa de ser só uma regra de transição de modo e passa a valer por MV, a cada ciclo) e **o RF-604 / spec F4 §4.5** (o shed do bloco deixa de disparar por divergência de UMA MV)

## Contexto

O bloco MPC escreve o SP de cada MV no PID correspondente a cada varredura, em REMOTO, sem nenhuma evidência de que aquele PID esteja de fato ouvindo. O Foundation Fieldbus resolve isso com o par `BKCAL_IN`/`BKCAL_OUT`: o bloco a jusante devolve, por contrato, o valor que efetivamente usou e o estado em que está, e o bloco a montante inicializa a partir dali. **O OPC-UA não oferece equivalente** — não há handshake de cascata, só tags.

Sem esse retorno, três situações silenciosas produzem bump:

1. **O operador tira a malha de RCAS no painel** (ou um override do intertravamento a toma). O MPC continua otimizando aquela MV e escrevendo nela; o PID ignora. Quando a malha volta a RCAS, ela encontra no registrador um comando calculado contra uma planta que andou sozinha nesse meio-tempo — degrau instantâneo no atuador.
2. **A tag de readback passa a vir com qualidade ruim.** `MpcBlock._readback_value` já rejeitava a amostra (`quality != 0`, régua conservadora da spec F3 §3.1), mas o `_effective_value` caía no hold de `_mv_last` — que, em AUTO, é **o último valor que o próprio MPC calculou**. O controlador passava a realimentar a si mesmo exatamente no cenário em que menos podia.
3. **A malha simplesmente não é observável ainda** (tag configurada, nada publicado). Mesmo efeito do caso 2.

O mecanismo que existia para o caso 1 — o shed do RF-604 / spec F4 §4.5 (`mode_read` divergente por 2 execuções ⇒ bloco inteiro volta a LOCAL) — é tudo-ou-nada: **uma** MV fora de RCAS derruba o MPC inteiro, inclusive as MVs saudáveis. Num MPC 4×3, perder uma malha por manutenção significava perder o controle avançado das outras três. O casos 2 e 3 não tinham mecanismo nenhum.

Não confundir com o **watchdog de comunicação do ADR-009** (bit alternante por conexão, 10 s sem alternância ⇒ falha): aquele mede se o PLC está vivo e, em falha, para o flow inteiro. Este ADR mede se **uma malha** está sob comando do MPC. São camadas independentes, com gatilhos, escopos e reações distintas, e permanecem assim — o ADR-009 não é tocado.

## Decisão

**1. Toda MV tem um status de disponibilidade, reapurado a cada varredura**, numa camada de pré-processamento pura (`services/flow-runtime/src/ottima_flow_runtime/mpc/availability.py`), anterior a qualquer montagem de problema de otimização:

| Status | Condição | Efeito |
|---|---|---|
| `rcas_ok` | nada a objetar | variável manipulada normal |
| `local_override` | leituras boas, `mode_read` ≠ `mode_values.target` | congelada na **posição real medida** |
| `bad_quality` | readback ou `mode_read` com `quality != 0` | congelada na **última posição real confiável** |
| `out_of_service` | tag configurada e nada publicado no espelho | congelada na última posição real confiável |

Precedência: ausência de leitura vence qualidade ruim, que vence divergência de modo — do sinal mais grave para o mais brando. Ausência de *observabilidade* não é falha: MV sem `pid` e sem `readback_tag_id`, e MV com `pid` sem `mode_read_tag_id`, seguem `rcas_ok` (a spec F4 §4.4/§4.5 já diz "sem `mode_read`, sem shed" — este ADR não inventa um dado que o config não pede).

**2. Congelar não é remover do problema.** A MV excluída continua no modelo, com o valor real medido: é assim que o efeito dela sobre as CVs continua entrando na predição — o papel de distúrbio medido, sem um segundo caminho de código. O mecanismo é o `_tvp` `dumax_<mv>` **zerado no horizonte inteiro** (`mpc/worker.py::_apply_tvp`), o que faz a restrição `|u − uprev| ≤ dumax` que o `builder.py` já monta virar `u ≡ uprev` para aquela MV. **Nenhuma linha de `mpc/builder.py` muda e o solver não é tocado** (do-mpc/IPOPT, ADR-004): o problema estrutural que chega ao solver é o mesmo de sempre, com um parâmetro diferente.

**3. A MV indisponível não recebe escrita.** `_write_pid` pula a MV cujo status não é `rcas_ok`. É a metade do BKCAL que faltava: parar de empurrar comando para quem não está ouvindo é o que evita que o registrador do PID guarde um valor velho para o instante do retorno.

**4. A porta da MV indisponível reporta a posição real**, pelo mesmo caminho de LOCAL, e não o plano do MPC — inclusive semeando o valor manual em REMOTO+MAN. É o que fecha o bumpless nos dois sentidos: a volta parte de onde o atuador está, não de onde o MPC gostaria que ele estivesse.

**5. Base de bias e de delta é sempre o valor medido.** Já era assim (`mpc/worker.py::_propagate` propaga com `u_applied`, e `_write_bias` faz `bias := y_medido − C·x`), e este ADR **trava a propriedade** onde ela estava furada: o `u_applied` de uma MV com readback ruim caía no último valor calculado pelo MPC. Passa a existir a âncora `_last_good_readback` — leitura viva, depois última leitura confiável, e só então o hold.

**6. Shed do bloco vira o caso extremo.** Divergência **parcial** não derruba mais o MPC: as MVs restantes seguem controlando (modo degradado). O shed do RF-604 dispara quando **nenhuma** MV está disponível por 2 execuções consecutivas. A fase de **confirmação do arme** não muda: entrar em REMOTO continua exigindo confirmação de todas as MVs monitoradas e readback de toda MV que declare a tag — armar é transição deliberada, e este ADR relaxa o conjunto ativo **durante a operação**, nunca a régua de entrada.

O gate de arme (`auto_arm_blocked_reason`) **não ganha** um motivo "nenhuma MV disponível": seria circular, porque LOCAL→REMOTO é justamente o ato de escrever `mode_cmd = target` nos PIDs — exigir `rcas_ok` antes dele é exigir que a malha já esteja em RCAS antes do comando que a põe em RCAS. O caso "o operador travou o PID fora de RCAS" já é coberto, sem circularidade, pelo watchdog de confirmação (`mpc_arm_failed {reason: no_confirm}`); a perda total depois de armado é o shed.

**7. Saturação NÃO é status de disponibilidade.** Uma MV encostada no limite continua controlável (pode sair no sentido oposto); congelá-la degradaria o controle sem ganho de segurança. Os limites duros já são `mpc.bounds` do builder (spec F4 §3.4).

**8. O status não é persistido.** Vive em memória e é publicado no `MpcState` (`vars.<mv_id>.status`, campo opcional aditivo ao contrato do canal `mpc.state.*`, PRD §7.1). `mpc_samples` (migration 0003) segue com as colunas de sempre — **sem migration, sem coluna nova, sem tabela de histórico**, mesmo espírito do ADR-016 para predições. A auditoria das transições vai para o log de eventos (ADR-020) no kind novo `mpc_mv_status_changed` (`warning` ao sair de `rcas_ok`, `info` ao voltar), sem alteração de schema — `events.payload` é JSONB.

## Consequências

- (+) Manutenção numa malha deixa de derrubar o APC inteiro: o MPC degrada em vez de parar.
- (+) O bump da devolução de controle deixa de depender de disciplina operacional (avisar antes de tirar de RCAS) e passa a ser estrutural.
- (+) O furo do caso 2 (MPC realimentando o próprio cálculo quando o readback some) fecha, e fecha na camada onde ele existia — a resolução de "qual é a posição real agora?".
- (+) Custo computacional nulo no solve: o congelamento é um parâmetro já existente na montagem.
- (−) **Um MPC pode operar por tempo indeterminado com menos graus de liberdade do que foi projetado**, e o operador só percebe isso pelo faceplate e pelo evento — não há shed que o force a reavaliar. É o preço aceito: a alternativa (shed a cada MV perdida) já se mostrou pior na prática. O que o torna aceitável: (a) o status é publicado a cada execução, então a tela de operação mostra a degradação enquanto ela dura; (b) cada transição gera evento de auditoria; (c) o shed continua existindo para o caso de perda total.
- (−) Um MPC muito quadrado (tantas CVs quanto MVs) que perca uma MV pode ficar sem como atender todas as CVs; a precedência do ADR-019 (Restrição vence CV) continua sendo o critério de quem cede, sem regra nova.
- O `mpc_shed` muda de significado: era "algum `mode_read` divergiu", passa a ser "nenhuma MV disponível". A mensagem do evento acompanha; o payload (`{}`, spec F4 §5.3) não muda.
- Depende de `readback_tag_id` e `pid.mode_read_tag_id` estarem configurados para valer: MV cega segue no comportamento pré-ADR-028, por construção.
- (−) **Erro de configuração passa a ter consequência de processo.** `mode_values.target` errado (ou apontando para uma tag de modo que o PLC codifica de outro jeito) faz o sistema classificar uma MV saudável como `local_override` e **parar de escrever nela** — um MPC que parece rodando e não comanda. Antes do ADR-028 o mesmo erro só se manifestava no shed (mais barulhento). Mitigação: o status vai publicado a cada execução e a transição gera evento; a comissão de uma malha nova deve confirmar `mv_status = rcas_ok` no faceplate antes de armar.
- PRD §7.1 (payload de `mpc.state.*`) e spec F4 §4.5/§5.1/§5.3 precisam ser atualizados para refletir o campo `status`, o kind `mpc_mv_status_changed` e a nova condição de shed.
