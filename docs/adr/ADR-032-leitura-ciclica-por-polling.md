# ADR-032 — Leitura cíclica por polling (reverte subscription da F2)

**Status:** Aceito · 2026-08-15

## Contexto
A spec F2 (`docs/specs/F2-aquisicao.md` §2.2-5, aprovada 2026-08-03) estabeleceu que o opc-worker
publicaria leituras via **subscription** OPC-UA: 1 monitored item por tag `direction='r'`,
`publishing_interval = sampling = 250 ms`, `queue_size = 1`, complementado por um **heartbeat de
valor** a cada 10 s para tags sem mudança (report-by-exception + heartbeat). O piso de volume
citado naquela decisão — ~864 mil linhas/dia no teto do RNF-01 (~100 tags) — era o caso
degenerado de nenhuma tag mudar nunca; na prática o volume real depende do quanto cada tag varia,
imprevisível a partir da config.

Essa imprevisibilidade é o problema: a cadência de amostragem efetiva de uma tag deixa de ser uma
decisão do engenheiro e passa a depender do comportamento do processo (uma tag ruidosa amostra
quase a 250 ms; uma tag estável só amostra a cada 10 s pelo heartbeat). Para trend de engenharia e
para qualquer análise que compare séries de tags diferentes, essa cadência não-determinística é
uma fonte de distorção — dois pontos "adjacentes" na mesma tabela `samples` podem ter sido lidos
com defasagem de até 10 s entre si, dependendo de qual das duas mudou por último.

## Decisão
Reverte a política de publicação da F2 (§2.2-5/6 — subscription + report-by-exception +
heartbeat) para **polling cíclico**, com período configurável **por conexão**:

1. **Coluna nova** `opc_connections.polling_period_ms INTEGER NOT NULL DEFAULT 1000`, faixa
   **100–60000 ms** (`CheckConstraint ck_opc_connections_polling_period`, migration
   `0011_opc_polling_period`, `down_revision = 0010_fuzzy_samples`). Cadência de amostragem passa
   a ser uma decisão explícita do operador por conexão, não um efeito colateral do comportamento
   do processo.
2. **1 task de polling por conexão.** A cada ciclo, `client.read_attributes(nodes,
   ua.AttributeIds.Value)` — **um único round trip** — devolve `list[ua.DataValue]` para
   **todas as tags com série** da conexão: toda `direction='r'` e também a `direction='w'` cujo
   node o servidor declare legível (AccessLevel com o bit `CurrentRead`). `direction` governa
   quem o sistema pode **escrever**, não o que ele pode **observar**: o valor de uma tag `w` é o
   comando **em vigor** no servidor, grandeza distinta do readback de posição real que RF-604
   exige como tag `r` própria — os dois divergem por tempo de curso e histerese, e ambos são
   dado de processo por direito próprio. A lista de tags e a de nodes nascem juntas na criação do
   poller e são emparelhadas com `zip(..., strict=True)`: resposta curta do servidor vira exceção
   em vez de truncar em silêncio (a mesma disciplina de falha explícita já aplicada ao Fuzzy —
   ADR-029 — e ao PID — ADR-031).
   **Comando write-only fica fora do ciclo, sem erro:** nem todo node de comando de PLC/gateway é
   legível, então uma tag `w` sem `CurrentRead` declarado é configuração correta, não falha — não
   entra na lista, não conta `read_errors` (item 6) e não emite aviso; quem consome `opc.values`
   exibe "sem dado". A checagem custa **um round trip na subida da sessão**, só para as tags `w`,
   e é otimista: servidor que não expõe o atributo conta como legível, e uma leitura ruim depois
   cai no caminho normal de quality. Tag `r` **não** passa por essa checagem — ela é leitura por
   cadastro, e AccessLevel torto nela é erro que precisa aparecer.
3. **Sleep compensado** pelo tempo gasto na própria leitura, sem acúmulo de drift ciclo a ciclo.
   Timeout de I/O `max(10, 3*período)`. Exceção na leitura leva a conexão a `failed` com
   `reason="session_lost"` — mesma máquina de estados e mesmo evento `comm_failure` de hoje
   (§3.6), só a causa da exceção que muda.
4. **Toda tag publica a todo ciclo** — não é mais report-by-exception. StatusCode OPC → quality
   `0/1/2` e a ordem de resolução do `ts` (SourceTimestamp → ServerTimestamp → `now()`) seguem
   inalterados (spec F1 §3.4-4, spec F2 §2.2-7).
5. **Heartbeat de valor (10 s) não é removido**, mas seu papel muda: com o polling publicando toda
   tag a todo ciclo, o heartbeat vira efetivamente no-op para qualquer conexão com
   `polling_period_ms ≤ 10000` (nunca encontra tag "sem publicação há ≥10 s"); só volta a ter
   efeito em conexões deliberadamente configuradas com período **> 10 s**, preenchendo a lacuna
   entre ciclos longos. Semântica de falha (rajada de quality=bad na detecção + heartbeat bad
   contínuo durante a queda) é a mesma de hoje.
6. **`/health`:** `tags_subscribed` → `tags_polled`, `monitored_errors` → `read_errors` — os dois
   nomes descreviam o mecanismo de subscription; o polling não tem "monitored items" para contar
   erros de assinatura, e sim tags lidas por ciclo e leituras que falharam.
7. **Nenhuma dependência nova** — `asyncua` já expõe `read_attributes`; o polling não precisa de
   `create_subscription`/`subscribe_data_change` nem de manutenção de monitored items no lado do
   servidor.

## Consequências
- (+) Cadência de amostragem determinística e sob controle do operador, por conexão — o mesmo
  argumento de "leitura explícita, não subscription" que já regia o watchdog (spec F2 §3.1) passa
  a valer também para as tags de processo.
- (+) Um único round trip por ciclo por conexão é mais barato em requisições OPC-UA que N
  monitored items reportando de forma assíncrona e desalinhada.
- (+) Resposta curta do servidor (`zip(..., strict=True)`) falha alto e explícito em vez de
  truncar/desalinhar tag↔valor em silêncio.
- (−) **Volume de `samples` sobe e passa a ser previsível ao invés de dependente do processo.**
  No teto de dimensionamento do RNF-01 (~100 tags, spec F1 §3.4-5/GLOSSARY "Dimensionamento-alvo")
  com o período default de 1 s: **100 tags × 86.400 ciclos/dia = 8,64 milhões de linhas/dia** —
  dez vezes o piso de ~864 mil linhas/dia que a subscription revertida citava como caso
  degenerado. Esse volume **cabe** no dimensionamento já feito:
  - `docs/specs/F1-fundacao.md` §3.4-5 já previu chunks de 1 dia em `samples` dimensionados para
    **9–17 milhões de linhas/dia** no teto do RNF-01 — 8,64 M/dia está dentro dessa faixa, não a
    ultrapassa.
  - `docs/specs/F2-aquisicao.md` §6-2 já orçou o recorder para **200–400 msg/s** com folga ampla;
    100 tags a 1 ciclo/s produzem **~100 msg/s** — bem dentro do orçamento existente, sem
    necessidade de rever batch (1 s/1000 linhas) nem fila (100k, drop-oldest).
- (−) **A tag `w` legível conta no volume como qualquer outra.** O teto de ~100 tags do RNF-01 é
  de tags **cadastradas**, não de tags `r`, então o cálculo acima não muda de patamar; o que muda
  é que uma conexão cujas tags de comando antes não geravam linha nenhuma passa a gerar uma por
  ciclo por comando legível. Quem não quiser a série de um comando específico remove a tag do
  cadastro — não existe (nem deve existir) chave por tag para desligar só a leitura, porque a
  mesma tag é a que o sistema escreve.
- (−) **Períodos agressivos multiplicam esse volume linearmente e são responsabilidade do
  operador.** Um `polling_period_ms = 100` (piso da faixa permitida) roda o ciclo **10×** mais
  rápido que o default e, para as mesmas 100 tags, produz **~86,4 milhões de linhas/dia** —
  acima do teto de 9–17 M/dia que F1 §3.4-5 dimensionou, e acima do orçamento de 200–400 msg/s do
  recorder (~1000 msg/s). A faixa **100–60000 ms** do `CheckConstraint` impede apenas o extremo
  patológico (< 100 ms); dentro da faixa permitida, escolher um período agressivo por conexão é
  uma decisão de engenharia do operador, não uma proteção automática do sistema — o mesmo
  raciocínio de "erro explícito, nunca clamp silencioso" que ADR-029/ADR-031 já aplicam a outros
  parâmetros configuráveis pelo usuário.
- Esta decisão **substitui** integralmente a política de publicação da F2 (§2.2-5/6): não há
  período de convivência entre subscription e polling; a spec F2 é atualizada in-place para
  refletir o polling como comportamento atual, com a subscription citada apenas como referência
  histórica revertida.
