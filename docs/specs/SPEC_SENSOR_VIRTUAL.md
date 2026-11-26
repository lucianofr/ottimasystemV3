# SPEC — Sensor virtual (blocos PLS, ESN e LSTM, coleta de laboratório, treino e Optuna)

**Data:** 2026-11-25 · **Status:** desenho em revisão, aguardando aprovação do usuário
**Baseline:** `main` @ `69d72f3`
**Origem:** porte dos três métodos do projeto `../SensorPredict` (PyQt6, desktop) para dentro do
OttimaSystem.

> **Este documento contém propostas normativas ainda NÃO aceitas** (§12: ADR-046, RFs do PRD,
> termos do GLOSSARY, texto do `CLAUDE.md`). Nada foi escrito em `docs/adr/`, `docs/PRD.md`
> nem `docs/GLOSSARY.md`. Aprovar esta spec é aprovar essas propostas; a primeira tarefa do
> primeiro plano é materializá-las.

Legenda usada no texto: **[usuário]** = decidido pelo usuário na conversa de desenho;
**[chamada]** = decisão de quem escreveu a spec, sujeita a correção.

## 1. Objetivo e motivo

Um **sensor virtual** estima, a cada varredura, uma variável que só existe como análise de
laboratório (teor, viscosidade, ponto de fulgor), a partir de variáveis contínuas de processo.
Hoje isso roda num aplicativo desktop separado (SensorPredict), com seu próprio cliente OPC-UA,
seu próprio histórico em SQLite e sem nenhuma das garantias de qualidade de sinal do Ottima.

Trazer para dentro do Ottima dá ao sensor virtual o que o resto da plataforma já tem: histórico
contínuo das entradas, qualidade fim a fim (ADR-043), execução no flow e a possibilidade de a
estimativa alimentar um PID ou MPC.

**[usuário]** A saída pode ser só indicação ou pode fechar malha. Por isso, enquanto o valor
não for confiável, a qualidade da saída é BAD (ou UNCERTAIN, §5.4), nunca um número com cara
de bom.

## 2. Metas, não-metas e anti-metas

### Metas
1. Três tipos de bloco no canvas, um por método: `soft_sensor_pls`, `soft_sensor_esn`,
   `soft_sensor_lstm`. **[usuário]**
2. Entrada de análises de laboratório por digitação e por CSV, com o instante da **coleta da
   amostra**. **[usuário]**
3. Período de coleta que emparelha dados contínuos de processo com as análises e gera um
   conjunto de treino. **[usuário]**
4. Treino do modelo e otimização de hiperparâmetros com Optuna. **[usuário]**
5. Duas páginas novas na navegação, visíveis só quando o projeto ativo tem ao menos um bloco de
   sensor virtual. **[usuário]**
6. Troca de modelo decidida pelo usuário, sem interromper a saída: o modelo antigo opera até o
   novo produzir resultado válido. **[usuário]**
7. Pré-aquecimento pelo histórico: o bloco sai válido no primeiro passo depois de um deploy,
   sem esperar a janela encher. **[usuário]**

### Não-metas (ficam fora desta entrega)
- SPE, contribuições por variável e alarme de SPE. No SensorPredict esses valores saem sempre
  zerados nos três adaptadores (`predict()` devolve `spe = 0.0`); seria funcionalidade nova.
- Análise de laboratório como **entrada** do modelo (no SensorPredict, "entrada manual"
  mantida no último valor). Aqui a análise é só o alvo. **[chamada]**
- Importação de Excel e do formato `.spm`. Só CSV.
- Escrita automática de métricas (RMSE/R²/MAE) em tags OPC. Quem quiser escreve a saída do
  bloco com um `opc_write` comum.
- Comparação automática da estimativa em operação contra análises novas (deriva do modelo).
- Variável de laboratório na página TREND.
- GPU. O treino é em CPU.

### Anti-metas (seria falha mesmo funcionando)
- O flow-runtime ganhar torch, scikit-learn, optuna ou qualquer biblioteca de treino.
- O flow-runtime abrir pickle/joblib.
- Um valor de aquecimento, de janela contaminada ou não finito sair com qualidade GOOD.
- Treino ou Optuna atrasarem a varredura de qualquer flow.
- Dado de processo posterior à coleta da amostra entrar no pareamento.

## 3. Restrições herdadas

| Fonte | Restrição | Como esta spec responde |
|---|---|---|
| ADR-004 | Loops vivos em asyncio; sem Celery; nunca bloquear o event loop | Treino é job discreto: emenda no ADR-046 (§12). Inferência de ESN/LSTM via `run_in_executor` |
| ADR-003 | Banco único; retenção por policy do Timescale (1 a 120 dias) | Análises e conjuntos ficam em tabelas comuns, fora da retenção |
| ADR-005 | Frontend não executa lógica de flow | Páginas só consultam REST e mostram estado persistido |
| ADR-002 / PRD §7.1 | Canal novo exige ADR | **Nenhum canal novo.** Só um `cmd` novo em `flow.commands` e `kind`s novos em `events` |
| ADR-006 | Só o opc-worker fala OPC-UA | Inalterado. O ml-worker nem usa o barramento |
| ADR-011 | Hot-swap preserva blocos não alterados | A troca de modelo NÃO passa pelo grafo (§5.6) |
| ADR-012 | Projeto exportável sem dados históricos | Modelo viaja no bundle; análises e conjuntos não (§9) |
| ADR-018 / RNF-04 | Serviço que executa código não recebe o `.env` inteiro | ml-worker recebe só URL do banco e nível de log |
| ADR-043 | `ok ≡ quality is GOOD`; qualidade nunca sobe | Tabela de qualidade do §5.4 |
| CLAUDE.md | Dependência nova exige justificativa | §12.4 |

## 4. Abordagens consideradas

### 4.1 Onde roda o quê

**A — Porte fiel.** Copiar os três adaptadores do SensorPredict; o flow-runtime instala torch,
reservoirpy, bibmon e scikit-learn e carrega arquivos pickle. É o caminho mais curto e mantém
o comportamento idêntico. Custa gigabytes na imagem do processo que escreve na planta, coloca
`joblib.load` nesse mesmo processo e quebra o carregamento a qualquer diferença de versão
entre quem treinou e quem executa.

**B — Treino pesado fora, inferência leve dentro. (ESCOLHIDA pelo usuário)** Um serviço novo,
`ml-worker`, concentra as bibliotecas pesadas. Ao terminar, grava o modelo como números puros
(escalas, coeficientes, matrizes de pesos). O bloco calcula a estimativa só com numpy, que o
flow-runtime já tem. Custa escrever à mão a conta de cada método e manter um teste de paridade.

**C — ONNX.** Treina no ml-worker, exporta ONNX, executa com onnxruntime. Formato padrão, mas
é dependência nova no flow-runtime e o ESN não tem exportador pronto (a conta seria escrita à
mão de qualquer jeito). Perde para a B neste tamanho.

Por que B: zero dependência nova no flow-runtime, nenhum pickle, custo de varredura medido e
previsível, e o modelo vira dado que cabe no export do projeto.

### 4.2 Como o conjunto de treino é montado

**1 — Como no SensorPredict.** Uma linha por análise (`merge_asof` da leitura mais próxima,
tolerância de 2 h). A sequência do LSTM e a memória do ESN são formadas por análises
sucessivas, separadas por horas; em operação o modelo é alimentado a cada varredura. Treina
numa escala de tempo e executa em outra. A validação cruzada embaralha as linhas.

**2 — Janela contínua. (ESCOLHIDA pelo usuário)** Para cada análise coletada em *t*, a entrada
é o trecho de dados de processo que termina em *t*, no período de amostragem do modelo. O
bloco alimenta o modelo nesse mesmo período. A validação usa blocos em ordem de tempo.

Consequências aceitas da opção 2: as métricas saem mais baixas e mais honestas que as do
SensorPredict; o período do modelo é parâmetro do conjunto; o Ts do flow precisa ser divisor
dele.

## 5. O bloco

### 5.1 Tipos, config e portas

Três tipos, com o mesmo schema de config e o mesmo contrato de portas:

| Tipo | Método | Rótulo na paleta |
|---|---|---|
| `soft_sensor_pls` | Regressão PLS | Sensor virtual PLS |
| `soft_sensor_esn` | Echo State Network | Sensor virtual ESN |
| `soft_sensor_lstm` | LSTM | Sensor virtual LSTM |

Config (`SoftSensorConfig`, `extra="forbid"`): `{n_inputs: int (1..32), output_eu: str}`.
**[chamada]** O teto de 32 é maior que o `MAX_SCRIPT_PORTS = 8` do Script/Fuzzy porque
regressão PLS com mais de 8 entradas é o caso comum.

Portas: entradas `IN1..INn` (numéricas), saída única `out`. O mapeamento porta ↔ variável é
**posicional**: `INk` corresponde à k-ésima entrada do conjunto de treino do modelo ativo. O
canvas rotula cada porta com o nome da tag esperada quando há modelo ativo (dado vindo da API,
§8.3); ligar o sinal certo na porta certa é responsabilidade do engenheiro, e o bloco não tem
como conferir.

O modelo **não** está na config do grafo. O vínculo bloco → modelo mora em tabela (§7.4).

### 5.2 Período do modelo

O modelo tem um período de amostragem `period_s` (herdado do conjunto de treino). O bloco
executa um **passo de modelo** a cada `N = period_s / Ts` varreduras e mantém o último valor
entre passos. `period_s` precisa ser múltiplo inteiro do Ts do flow; a ativação recusa (422)
quando não for, e o deploy de um flow cujo Ts deixou de dividir o período sobe o bloco **sem
modelo** (saída BAD, evento `soft_sensor_model_missing`).

O valor que entra no passo é o valor das portas naquela varredura.

### 5.3 A conta de cada método (módulo compartilhado)

Mora em `packages/ottima-core/src/ottima_core/softsensor/` e é a **única** implementação da
inferência: o flow-runtime usa para operar e o ml-worker usa para calcular métricas e validar o
que exporta. Só numpy.

**Todo modelo é uma função pura das últimas `K` amostras.** O bloco guarda, para cada modelo
que está rodando (o em uso e, durante uma troca, o candidato), um buffer circular das últimas
256 amostras **no período daquele modelo**: valores crus das portas mais a pior qualidade das
portas naquele passo. Nenhum modelo carrega estado numérico próprio entre passos. É isso que
garante que treino e operação enxergam exatamente a mesma coisa, e é o que torna a troca de
modelo quase instantânea (§5.6).

(Emenda de 2026-11-25, na escrita do plano da SV-1: a primeira versão dizia "um buffer do
bloco". Um candidato pode ter período diferente do modelo em uso, e as amostras de um não
servem para o outro; por isso o buffer é por modelo.)

- **PLS (`K = 1`):** `y = w · x + b`, com `w` e `b` já em unidade de engenharia.
- **ESN (`K = warmup`):** parte do estado zero e aplica, sobre as últimas `warmup` amostras
  padronizadas, `s = (1 − lr)·s + lr·tanh(W·s + Win·x_n + bias)`; depois
  `y_n = Wout·s + b_out`, despadronizado. É o mesmo cálculo que o treino faz sobre cada janela
  (§8.1). **[chamada]** O estado **não** é carregado de um passo para o outro: um estado
  contínuo divergiria do regime em que a saída foi ajustada sempre que a memória do
  reservatório fosse maior que `warmup`.
- **LSTM (`K = L`):** roda a rede (camadas empilhadas, ordem de portões `i, f, g, o` do
  PyTorch, estado inicial zero) sobre as últimas `L` amostras padronizadas e aplica a camada
  linear ao último estado oculto.

**Fora do event loop:** PLS roda inline. ESN e LSTM rodam por `loop.run_in_executor` (thread).
O numpy solta o GIL nas multiplicações de matriz, mas não no laço Python em volta; parte do
custo abaixo ainda é paga pelo event loop da partição, e o `block_overrun` do scheduler é quem
denuncia um modelo caro demais. Custo medido com numpy puro nesta máquina, por passo de modelo:

| Modelo | Configuração | Tempo |
|---|---|---|
| ESN | 500 unidades, `warmup` 100 (default) | 5 ms |
| ESN | 500 unidades, `warmup` 200 (teto da busca) | 11 ms |
| LSTM | 64 un., 2 camadas, janela 10 (default) | 0,9 ms |
| LSTM | 256 un., 4 camadas, janela 50 (teto da busca) | 28 ms |

(ESN: 0,054 ms por iteração × `warmup`. Com 1000 unidades a iteração sobe a 8,4 ms por sair do
cache, o que daria 1,7 s por passo; por isso o teto de `units` do ESN é 500, §8.2.)

### 5.4 Qualidade da saída

A tabela abaixo é o comportamento final. As **qualidades** são as que o usuário aprovou. A
coluna de **valor** foi refinada depois da aprovação em dois pontos, marcados com ★ e
explicados logo abaixo das regras; eles precisam do aceite do usuário.

| Situação | Valor | Qualidade |
|---|---|---|
| Bloco sem modelo ativo, nunca produziu valor | `None` | BAD |
| Primeiro aquecimento após deploy ou retomada | `None` | BAD |
| Janela com amostra BAD (entrada BAD agora ou há menos de `K` passos) ★ | último calculado | BAD |
| Modelo devolve NaN ou infinito ★ | último calculado | BAD |
| Alguma amostra da janela UNCERTAIN | calculado neste passo | UNCERTAIN |
| Alguma amostra da janela fora da faixa vista no treino | calculado neste passo | UNCERTAIN |
| Tudo válido | calculado neste passo | GOOD |

**[chamada]** Regra que implementa a tabela, igual para os três métodos:

1. A cada passo de modelo, o bloco grava no buffer os valores das portas e a pior qualidade
   entre elas. Porta sem valor conta como BAD.
2. Para um modelo, a qualidade de cada amostra da sua janela (as últimas `K`) é a qualidade
   gravada, rebaixada a UNCERTAIN se alguma entrada estiver fora de
   `[min − 5%·span, max + 5%·span]` do treino **daquele modelo** (faixas no artefato, §6).
3. **Janela incompleta ou com alguma amostra BAD:** o modelo não é calculado; a saída é BAD.
4. **Janela completa e sem BAD:** o modelo é calculado; a qualidade da saída é a pior da
   janela (GOOD ou UNCERTAIN). Resultado não finito: BAD.
5. Entre passos de modelo, a saída mantém o último valor, com qualidade
   `min(qualidade do último passo, pior porta na varredura atual)`.

★ **"Sem valor" só existe antes do primeiro resultado. [chamada, refina a tabela aprovada,
que dizia "sem valor, BAD" nas duas linhas marcadas]** A saída é
`v = None` apenas enquanto o bloco nunca produziu um valor desde que foi instanciado (deploy,
retomada, sem modelo). Depois disso, toda saída BAD **mantém o último valor calculado**, com
qualidade BAD. Motivo, verificado no código: no Ottima, `v = None` é o sinal de *cold start*,
não de medição inválida. O MPC que recebe `None` numa CV sai pelo portão frio
(`blocks/mpc.py:463-472`) **antes** do tratamento de entrada inválida (`fail_action`,
`fail_timeout_s`, queda da malha). Uma saída `None` no meio da operação deixaria o MPC parado
no portão frio em vez de derrubar a malha para o PLC. É também a convenção do ADR-043 D7.

O bloco emite eventos **só na borda** (entrada e saída do estado), nunca por varredura:
`soft_sensor_extrapolating` (início/fim) e `soft_sensor_model_missing`.

### 5.5 Consequência operacional do aquecimento (ler antes de fechar malha)

O aquecimento dura `K × period_s`: `L` passos no LSTM (3 a 50), `warmup` passos no ESN
(10 a 200), um passo no PLS. Um ESN com `warmup = 200` e período de 60 s precisa de
**3 h 20 min** de dado bom contínuo. Sem o pré-aquecimento do §5.7, esse seria o tempo em BAD
depois de cada deploy; com ele, o tempo só é pago quando o histórico recente tem falha. Ele
também é pago depois de **cada amostra BAD em qualquer entrada**, até ela sair da janela.

São dois casos com efeitos diferentes a jusante:

- **Amostra BAD no meio da operação.** A saída mantém o último valor com qualidade BAD. O MPC
  trata a CV como inválida (`fail_action` e, vencido o `fail_timeout_s`, a ação final).
- **Primeiro aquecimento após deploy ou retomada.** A saída é `None`. O portão frio do MPC
  (`has_cold_input` sobre todas as entradas, `blocks/mpc.py:463-472`) devolve saídas nulas
  para o **bloco inteiro**: o controlador todo fica inerte, não só a CV estimada, durante
  `K × period_s`. Hoje esse portão dura cerca de uma varredura; com um sensor virtual como CV
  ele passa a durar o aquecimento do modelo, a cada deploy e a cada retomada automática.

**[usuário]** O segundo caso não é aceito como está: o bloco pré-aquece pelo histórico (§5.7).
O aquecimento completo só acontece quando o pré-aquecimento não é possível.

### 5.7 Pré-aquecimento pelo histórico

Ao **instanciar** o bloco com um modelo vinculado (deploy, retomada automática, hot-swap que
recria o bloco), o runtime preenche o buffer de 256 passos antes da primeira varredura, com os
valores das tags de entrada do modelo lidos de `samples`.

- **Grade:** instantes `agora − k × period_s`, `k = 1..256` contados do pré-aquecimento, sendo
  o primeiro passo do bloco o ponto `k = 0` (emenda de 2026-11-25 (implementação SV-1): esse ponto é a amostra real da
  primeira varredura; tirá-lo também do histórico o poria duas vezes na janela). Cada ponto é o último valor da tag
  em ou antes do instante, não mais velho que `max(3 × period_s, 180 s)`. É a **mesma função**
  de grade do congelamento do conjunto (§7.3), compartilhada em `ottima_core.softsensor`, para
  treino, conjunto e pré-aquecimento nunca divergirem.
- **Qualidade de cada ponto:** a gravada em `samples` (GOOD ou UNCERTAIN). Ponto sem amostra
  válida dentro da tolerância (lacuna, ou amostra BAD, que o recorder grava como NULL,
  ADR-037) entra no buffer como **BAD**.
- **Efeito:** com histórico íntegro, o primeiro passo de modelo já calcula um valor, e o portão
  frio do MPC volta a durar cerca de uma varredura. Com lacuna dentro da janela do modelo, a
  saída fica BAD até a lacuna sair da janela, pela regra normal do §5.4.
- **Quando não ajuda, por desenho:** na retomada depois de falha de comunicação, o histórico
  do período da falha é BAD; a janela fica contaminada e a saída só volta quando houver `K`
  passos de dado bom. É a regra do §1 funcionando, não uma falha do pré-aquecimento.
  **Limitação residual:** como o bloco recém-instanciado ainda não calculou nenhum valor, a
  saída nesse intervalo é `None`, e um MPC que use a estimativa como CV fica inteiro no portão
  frio até a janela ficar limpa. Depois de uma falha de comunicação, portanto, o MPC só volta
  a atuar `K × period_s` depois de o dado bom voltar.
- **Sem pré-aquecimento (buffer vazio, aquecimento completo):** alguma tag de entrada do
  modelo não existe mais no projeto, ou a consulta não responde em 5 s. O deploy **nunca**
  falha nem espera por isso; sai o evento `soft_sensor_prewarm_skipped` (info) com o motivo.
- **Premissa:** o histórico guarda o valor cru da tag. Se o engenheiro ligar na porta um sinal
  transformado (filtro, escala), o pré-aquecimento usa o valor cru. É a mesma premissa do
  treino, que também lê o histórico cru; as amostras reais das portas substituem as do
  histórico à medida que os passos acontecem.
- A consulta roda na instanciação do bloco, fora do laço de varredura.

### 5.6 Troca de modelo

**[usuário]** O usuário decide quando o modelo novo entra; o antigo segue operando; os dois
rodam em paralelo até o novo ter resultado válido; então o antigo é descartado.

**[chamada]** Mecanismo:

1. `POST /api/operate/{flow_id}/{block_id}/model` com `{model_id}` (`require_admin`). A API
   valida (método = tipo do bloco, `n_inputs` igual, `period_s` múltiplo do Ts), grava
   `desired_model_id` no vínculo (§7.4) e publica `FlowCommand(cmd="soft_sensor_model")` em
   `flow.commands`. Responde 202. A API não emite evento (mesmo desenho do `mpc_sp`).
2. O runtime carrega o artefato do banco fora do event loop, cria o **candidato** e grava
   `candidate_model_id` no vínculo. O buffer do candidato nasce como **cópia do buffer do
   modelo em uso** quando os dois têm o mesmo período; com período diferente, nasce
   pré-aquecido pelo histórico (§5.7) ou, se isso não for possível, vazio. A cada passo os dois
   modelos são calculados, cada um no seu período; a saída do bloco continua sendo a do modelo
   em uso.
3. O candidato é **promovido** no primeiro passo em que as duas condições valem: ele
   **calculou um valor** neste passo (janela completa, sem BAD, resultado finito) e a qualidade
   desse valor é **maior ou igual** à da saída do modelo em uso. A troca nunca piora a saída.
   Ele vira o modelo em uso, o antigo é descartado, o runtime grava `active_model_id`, limpa
   `candidate_model_id` e emite `soft_sensor_model_activated`. Como o candidato já nasce com
   amostras, ele costuma ser promovido no passo seguinte; a execução em dobro só dura enquanto
   a janela dele for maior que as amostras disponíveis ou enquanto o processo estiver fora da
   faixa de treino dele.
4. Se o candidato não for promovido em `2 × K × period_s` (mínimo 60 s), é descartado, o antigo
   continua, o runtime limpa `candidate_model_id`, devolve `desired_model_id` ao modelo que o
   bloco vai acabar rodando (o pedido enfileirado, o candidato em curso, o em uso ou NULL), e
   só se ele ainda aponta para o rejeitado, e emite `soft_sensor_model_rejected` (severidade
   warning) com o motivo (janela incompleta, entrada BAD ou extrapolação). A mesma devolução
   vale para a recusa no comando (método, `n_inputs`, período, artefato ilegível). Condicional
   por emenda de 2026-11-25 (implementação SV-1): um pedido mais novo, gravado pela API durante a recusa, não é desfeito.
5. Bloco sem modelo em uso: o candidato vira o modelo em uso na hora (a saída segue BAD até
   a janela completar). Flow parado: só `desired_model_id` muda; o próximo deploy carrega
   `desired_model_id` direto e iguala `active_model_id`. Flow que para ou cai em falha com uma
   troca em voo tem `candidate_model_id` limpo pelo runtime, sem esperar o banco;
   `desired_model_id` fica (emenda de 2026-11-25 (implementação SV-1)).
6. Uma segunda ativação durante a troca substitui o candidato.

A ativação **não** é edição do grafo: um modelo guardado na config do bloco mudaria o bloco a
cada troca, o hot-swap o recriaria (ADR-011) e abriria o buraco de BAD que este desenho evita.

**Estado mostrado na página (Regra do Estado Publicado).** O que a página chama de "em uso" e
de "aquecendo" vem só de colunas que **o runtime** grava: `active_model_id` e
`candidate_model_id`. `desired_model_id`, que a API grava, nunca é mostrado como estado; quando
ele difere de `active_model_id` e não há candidato, a página mostra "aguardando o runtime"
(flow parado ou comando perdido) e reenviar a ativação é idempotente. A página relê o vínculo
por REST ao chegar um dos eventos acima pelo `/ws` (canal `events`, já assinado por toda
sessão). Nenhum canal de estado novo.

## 6. O artefato do modelo

Contrato entre o ml-worker (produz), o flow-runtime (consome) e o export (transporta).

- **Metadados** (JSON): `schema_version`, `method` (`pls`/`esn`/`lstm`), `period_s`,
  `inputs[{name, eu, min, max}]` na ordem das portas, `output{name, eu}`, hiperparâmetros,
  `warmup_steps`, métricas, `trained_at`, ids do(s) conjunto(s) de origem.
- **Pesos**: um `.npz` (`numpy.savez_compressed`), matrizes em `float32`, lido sempre com
  `allow_pickle=False`.
  - PLS: `w`, `b`.
  - ESN: `W`, `Win`, `bias`, `Wout`, `b_out`, `lr`, `x_mean`, `x_std`, `y_mean`, `y_std`.
  - LSTM: por camada `w_ih`, `w_hh`, `b_ih`, `b_hh`; `fc_w`, `fc_b`; `x_mean`, `x_std`,
    `y_mean`, `y_std`.
- Teto de 8 MB por artefato **[chamada]** (o maior LSTM da busca, 256 × 4 camadas, dá cerca de
  7 MB; o maior ESN, 500 unidades, 1 MB); treino cujo resultado estoura falha com mensagem.

**Teste de paridade (obrigatório, TDD):** para **PLS** e **LSTM**, a saída do módulo do §5.3
sobre o artefato exportado é igual à da biblioteca que treinou (`PLSRegression.predict`,
`torch`), em entradas aleatórias, com tolerância `1e-4`. É esse teste que impede o porte à mão
de divergir em silêncio. O **ESN** não tem biblioteca de referência: o próprio módulo do §5.3
calcula os estados no treino, então treino e operação são a mesma função por construção; ele
ganha um teste de valor fixo (semente fixa → saída esperada gravada no teste).

## 7. Dados

Todas as tabelas abaixo são tabelas Postgres comuns (não hypertables, sem policy de retenção).

### 7.1 Variável de laboratório e análises

**[chamada]** A variável de laboratório **não** é linha em `tags`. Motivo: entrar em `tags`
faria ela aparecer no seletor de tags do canvas, nas entradas de tag calculada e na lista do
TREND, sempre com série vazia, porque os valores não vão para `samples` (análise é retroativa e
não pode sumir com a retenção).

- `lab_variables(id, project_id → projects ON DELETE CASCADE, name, eu, description)` com
  `UNIQUE(project_id, name)`. `name` é o que vem na primeira coluna do CSV.
- `lab_samples(lab_variable_id → lab_variables ON DELETE CASCADE, sampled_at timestamptz,
  value double precision, source ('manual'|'csv'), created_by, created_at)` com
  `PRIMARY KEY(lab_variable_id, sampled_at)`. `sampled_at` é o instante da **coleta da
  amostra**, nunca o da digitação.

### 7.2 CSV

**[usuário]** Formato: `"nome do TAG";"data/hora";"valor"`.

**[chamada]** Regras de leitura:
- Separador `;`, aspas opcionais, UTF-8 com ou sem BOM.
- Primeira linha é cabeçalho se a terceira coluna não for número; então é ignorada.
- Data/hora: `dd/mm/aaaa hh:mm[:ss]` ou ISO-8601. Sem fuso no texto, vale o fuso IANA do
  navegador, enviado junto com o upload.
- Valor: aceita vírgula ou ponto decimal.
- Um arquivo pode trazer várias variáveis. Nome que não existe em `lab_variables` do projeto
  ativo, linha malformada ou data futura: **o arquivo inteiro é recusado** (422) com a lista
  de linhas e motivos. Nada é importado pela metade.
- Mesma variável e mesmo instante de uma análise já existente: substitui (reimportar o mesmo
  arquivo é idempotente).
- Teto de 5 MB por arquivo.

### 7.3 Conjunto de treino

`soft_sensor_datasets(id, project_id, name, lab_variable_id, input_tag_ids bigint[] (ordem =
ordem das portas), period_s, start_ts, end_ts NULL, status, stats jsonb, inputs_meta jsonb,
data bytea NULL, created_by, created_at)`.

Estados: `collecting` → `building` → `ready` | `failed`.

- **Iniciar** cria o conjunto em `collecting` com `start_ts` = agora ou um instante passado.
  A página avisa quando `start_ts` é mais antigo que a retenção vigente.
- **Entradas** podem ser qualquer linha de `tags` do projeto: OPC, calculada ou variável
  historiada. De 1 a 32, na ordem em que viram portas.
- `period_s` vem de uma lista fechada: 1, 2, 5, 10, 30, 60, 300, 600 s. **[chamada]**
- **Finalizar** fixa `end_ts`, passa a `building` e enfileira o job `dataset_build` (§7.5).

**O que o job congela:** para cada análise da variável com `start_ts ≤ sampled_at ≤ end_ts`,
uma janela de `W = 256` passos de modelo **[chamada]** terminando em `sampled_at` (256 cobre a
maior janela do LSTM, 50, e o maior aquecimento do ESN, 200). Cada ponto da grade é a última
amostra da tag em `samples` em ou antes daquele instante, desde que não seja mais velha que
`max(3 × period_s, 180 s)` e que seja GOOD; senão o ponto é **lacuna** e é guardado como `NaN`.
(A função de grade é a mesma do pré-aquecimento, §5.7: ela devolve valor e qualidade da última
amostra; o conjunto de treino só aproveita as GOOD.)

Lacuna não descarta a análise no congelamento. Só é descartada a análise cujo **último** ponto
(o do instante da coleta) é lacuna, porque nenhum método consegue usá-la. Para as demais, cada
treino usa as análises cujos últimos `K` pontos não têm lacuna, com o `K` daquele treino
(PLS 1, LSTM `L`, ESN `warmup`). Exigir os 256 pontos íntegros descartaria, num período de
600 s, toda análise com qualquer falha nas 42 horas anteriores, mesmo para o PLS, que usa um
ponto só.
(O piso de 180 s existe porque fontes legítimas publicam a cada 60 s: polling de conexão,
tag calculada e variável historiada de flow lento. Com piso menor, um modelo de período curto
sobre uma fonte lenta não emparelharia quase nada.)
A janela pode buscar dado anterior a `start_ts`: o período define quais análises entram, não
de onde vem o processo.

`data` guarda um `.npz` com `x` (`float32`, forma `[n, 256, n_inputs]`), `y` (`float64`, `[n]`)
e `ts` (`[n]`). `stats` guarda quantas análises existiam no período, quantas foram descartadas
por lacuna no instante da coleta e quantas têm a janela inteira sem lacuna. `inputs_meta`
congela nome e EU de cada entrada. O job de treino informa no resultado quantas análises usou
e falha se forem menos que o mínimo do §8.1.

**Retreino com dado antigo:** um job de treino aceita **vários** conjuntos `ready` com a mesma
variável de laboratório, as mesmas entradas na mesma ordem e o mesmo período; eles são
concatenados em ordem de tempo. É assim que o dado de seis meses atrás sobrevive à retenção.

### 7.4 Modelos e vínculo

- `soft_sensor_models(id, project_id, name, method, period_s, n_inputs, input_tag_ids
  bigint[], meta jsonb, weights bytea, created_by, created_at)`. `meta` são os metadados do §6.
  `input_tag_ids` são as tags de entrada, na ordem das portas, copiadas do conjunto de treino;
  é o que o pré-aquecimento (§5.7) e os rótulos de porta (§5.1) usam.
- `soft_sensor_bindings(flow_id → flows ON DELETE CASCADE, block_id, desired_model_id,
  active_model_id, candidate_model_id, updated_by, updated_at)` com
  `PRIMARY KEY(flow_id, block_id)`. `desired_model_id` é gravado pela API (e devolvido
  pelo runtime quando rejeita um pedido, §5.6-4); `active_model_id` e
  `candidate_model_id`, só pelo runtime (§5.6). As três colunas
  referenciam `soft_sensor_models` com FK `DEFERRABLE INITIALLY DEFERRED`, sem `ON DELETE`
  (emenda de 2026-11-25 (implementação SV-1); era `ON DELETE RESTRICT`): a ordem entre as cascatas projeto → flows → vínculos e
  projeto → modelos é a dos triggers de RI, que varia, e uma checagem imediata falharia ao
  apagar o projeto; adiada, ela só vê o estado final, no COMMIT. Modelo vinculado a um bloco
  continua não podendo ser apagado (a recusa sai no COMMIT).
- **Faxina no save do flow:** o save apaga o vínculo de todo `block_id` que saiu do grafo ou
  mudou de tipo, na mesma transação. É a mesma faxina que o ADR-041 faz com a porta historiada
  que deixou de existir; sem ela, um bloco removido deixaria um vínculo órfão que impede apagar
  o modelo para sempre.

### 7.5 Jobs

`ml_jobs(id, project_id, kind ('dataset_build'|'train'|'tune'), status ('queued'|'running'|
'done'|'failed'|'cancelled'), params jsonb, progress jsonb, result jsonb, error text,
cancel_requested bool, created_by, created_at, started_at, finished_at)`.

- O ml-worker consulta a tabela a cada 2 s (`FOR UPDATE SKIP LOCKED`) e executa **um job por
  vez**, num processo filho (`multiprocessing` com `spawn`).
- **Cancelar:** a API liga `cancel_requested`; o laço do ml-worker vê e mata o processo filho.
- **Progresso:** o filho devolve o progresso ao pai por `Pipe`; o pai grava `progress`. A
  página consulta por REST a cada 2 s enquanto houver job ativo.
- **Reinício do ml-worker:** job que estava `running` vira `failed` com o erro "interrompido
  pelo reinício do serviço". Não há retomada.
- O estudo do Optuna é em memória, dentro do filho. Nenhuma tabela do Optuna no banco.

## 8. Treino, otimização e páginas

### 8.1 Como cada método treina (no ml-worker)

Comum aos três: os conjuntos são ordenados por `ts`; os **últimos 20%** viram teste; as
métricas exibidas (R², RMSE, MAE, em unidade de engenharia) são desse teste, com o modelo
treinado nos 80% iniciais. O modelo que é gravado é **reajustado sobre 100%** com os mesmos
hiperparâmetros. Mínimo de 20 análises emparelhadas para treinar **[chamada]**; abaixo disso o
job falha com mensagem clara. A única normalização é a padronização (média e desvio) do treino.

- **PLS:** `sklearn.cross_decomposition.PLSRegression` sobre a última linha de cada janela.
  O exportador reduz o modelo a `w` e `b` em unidade de engenharia. (O bibmon do SensorPredict
  só embrulhava essa normalização; não entra.)
- **ESN:** para cada janela, roda o reservatório do estado zero pelos últimos `warmup` passos
  (com a função do §5.3) e guarda o estado final; ajusta a saída por regressão ridge
  (`sklearn.linear_model.Ridge`) sobre esses estados. As matrizes `W`, `Win` e `bias` são
  geradas em numpy a partir de `numpy.random.default_rng(seed)`: `W` esparsa com densidade
  `rc_connectivity`, reescalada para raio espectral `sr`; `Win` esparsa com densidade
  `input_connectivity`, multiplicada por `input_scaling`. **Sem `reservoirpy` [chamada]:**
  como as matrizes viajam no artefato, o gerador não faz parte do contrato de operação, e a
  API da biblioteca mudou entre as versões 0.3 e 0.4.
- **LSTM:** PyTorch (CPU), sobre os últimos `L` passos de cada janela; Adam, MSE, parada
  antecipada com paciência 10.

Hiperparâmetros editáveis no treino manual, com os defaults do SensorPredict:
PLS `n_components = 3`; ESN `units = 500, sr = 0.9, lr = 0.3, rc_connectivity = 0.1,
input_connectivity = 0.1, input_scaling = 1.0, ridge = 1e-6, warmup = 100, seed = 42`;
LSTM `units = 64, layers = 2, epochs = 100, batch_size = 32, sequence_length = 10, lr = 1e-3`.

### 8.2 Otimização (Optuna)

Objetivo: maximizar o R² médio de uma validação em **3 blocos em ordem de tempo**
(`TimeSeriesSplit(n_splits=3)`) sobre os 80% de treino. Nunca embaralha.

Faixas de busca, copiadas do SensorPredict com uma exceção: `units` do ESN vai até 500, não
1000, pelo custo por passo medido no §5.3. O mesmo teto vale para o treino manual.

| Método | Parâmetros |
|---|---|
| PLS | `n_components` 1 .. min(n_entradas, n_amostras, 20) |
| ESN | `units` 100..500 · `sr` 0,1..1,5 · `rc_connectivity` 0,01..0,99 · `input_connectivity` 0,01..0,99 · `lr` 0,01..1,0 · `ridge` 1e-8..1e-1 (log) · `input_scaling` 0,1..3,0 · `warmup` 10..200 |
| LSTM | `units` 16..256 · `layers` 1..4 · `epochs` 30..200 · `batch_size` {8,16,32,64} · `sequence_length` 3..50 · `lr` 1e-4..1e-2 (log), com `MedianPruner(n_startup_trials=3, n_warmup_steps=10)` |

Controles do usuário: número de tentativas (10 a 500, default 20) e **R² mínimo** (0 a 1,
default 0 = desligado). **[chamada]** No SensorPredict o R² mínimo é aceito e nunca usado; aqui
ele é real: o estudo para na primeira tentativa que o atinge.

Ao terminar (ou ao parar pelo R² mínimo), o job treina o modelo final com os melhores
hiperparâmetros, pela mesma regra do §8.1, e grava em `soft_sensor_models`. Cancelado no meio,
não grava modelo.

### 8.3 Páginas

Dois itens novos no grupo de engenharia da navegação, depois de "Trend", visíveis só quando
`GET /api/softsensor/blocks` devolve ao menos um bloco para o projeto ativo:

- **Coleta e treino** → `/engenharia/sensor-virtual/coleta`
- **Otimização** → `/engenharia/sensor-virtual/otimizacao`

**Papéis [chamada]:** operador abre as duas páginas, cria variável de laboratório não, lança e
apaga análise (digitada ou CSV) sim. Todo o resto (variável de laboratório, conjunto, treino,
otimização, ativação, apagar modelo) é `require_admin`.

**Coleta e treino:**

```
Sensor virtual · Coleta e treino             [conjunto: Teor de enxofre ▾] [Novo]
┌──────────────────────────────────────────┬──────────────────────────────┐
│ Entradas de processo (tendência)         │ Período                      │
│ ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ │ início [__/__ __:__] [Agora] │
│ ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ │ período do modelo [60 s ▾]   │
├──────────────────────────────────────────┤ [Iniciar]   [Finalizar]      │
│ Análises de laboratório (pontos)         │──────────────────────────────│
│      ◆        ◆            ◆      ◆      │ Nova análise                 │
│                                          │ valor  [______]              │
│                                          │ coleta [__/__ __:__]         │
│                                          │ [Adicionar]  [Importar CSV]  │
├──────────────────────────────────────────┴──────────────────────────────┤
│ Emparelhadas 41 de 44 · 3 sem dado de processo no instante da coleta    │
│ Método [PLS ▾]  hiperparâmetros […]   [Gerar modelo]                    │
├─────────────────────────────────────────────────────────────────────────┤
│ Modelos                                                                 │
│ nome        método  R²    RMSE   MAE    aquecimento  em uso em          │
│ enxofre-v3  LSTM    0,91  0,12   0,09   10 min       flow 4 / ss1  [▾]  │
│ enxofre-v2  PLS     0,84  0,17   0,13   nenhum       —        [Ativar ▾]│
└─────────────────────────────────────────────────────────────────────────┘
```

- A tendência das entradas reusa `TrendChart` e `GET /api/history` (as entradas são tags).
- "Novo" pede nome, variável de laboratório (com opção de criar), entradas e ordem.
- "Ativar ▾" lista os blocos compatíveis (mesmo método, mesmo `n_inputs`, Ts divisor do
  período). A coluna "em uso em" mostra `active_model_id`; durante a troca aparece
  "aquecendo" no modelo de `candidate_model_id` (§5.6).
- "Gerar modelo" permite marcar outros conjuntos compatíveis para treinar junto (§7.3).

**Otimização:** seletor de conjunto(s) e método, número de tentativas, R² mínimo,
[Otimizar] / [Cancelar]; barra "Tentativa k de N"; melhor R² até agora; tabela das tentativas
(número, R², parâmetros); ao terminar, as métricas do modelo gerado e um atalho para ativá-lo.

`data-testid` com os prefixos `sv-coleta-*` e `sv-otim-*`.

### 8.4 API (grupo novo `/api/softsensor`, mais uma rota em `/api/operate`)

| Rota | Papel |
|---|---|
| `GET /api/softsensor/blocks` (blocos do projeto ativo, com vínculo e rótulos de porta) | operador |
| `GET/POST/PATCH/DELETE /api/softsensor/lab-variables` | leitura operador, escrita admin |
| `GET/POST/DELETE /api/softsensor/lab-variables/{id}/samples`, `POST .../lab-samples/import` | operador |
| `GET/POST /api/softsensor/datasets`, `POST .../{id}/finalize`, `DELETE .../{id}` | leitura operador, escrita admin |
| `GET /api/softsensor/models`, `DELETE .../{id}` | leitura operador, escrita admin |
| `POST /api/softsensor/jobs` (`train`/`tune`), `GET .../jobs[/{id}]`, `POST .../{id}/cancel` | leitura operador, escrita admin |
| `POST /api/operate/{flow_id}/{block_id}/model` | admin |

## 9. Export e import de projeto

**[chamada]** O arquivo de projeto passa a levar: `lab_variables` (definições), os
`soft_sensor_models` referenciados por algum vínculo (metadados + pesos em base64) e os
vínculos. **Não** leva análises (`lab_samples`) nem conjuntos de treino: são dado histórico, a
mesma fronteira do ADR-012. Sem o modelo no bundle, um flow importado teria um bloco que nunca
sai de BAD.

- **Tags de entrada do modelo** (`input_tag_ids`) viajam como referência de tag do bundle e são
  religadas no import pelo mesmo mecanismo das referências de tag do grafo. Referência que não
  resolve não impede o import: o modelo entra com `input_tag_ids` vazio, tudo ou nada, porque
  as portas são posicionais e uma lista com buraco ligaria a tag errada à porta; o bloco apenas
  não pré-aquece (§5.7) (emenda de 2026-11-25 (implementação SV-1)).
- **`schema_version` continua 1.** Os campos novos são opcionais, como foram os de tag
  calculada e de variável historiada. O import recusa qualquer versão diferente de 1
  (`routers/projects.py:396-398`, cenário E2E-F6-03); subir a versão tornaria todo export
  existente não importável.
- **Tetos de tamanho sobem.** Hoje o import aceita 4 MiB (`MAX_IMPORT_BUNDLE_BYTES`,
  `routers/projects.py:316`) e o nginx do frontend não define `client_max_body_size` em
  `location /api/` (`frontend/nginx.conf`), então vale o padrão de 1 MB. Um modelo LSTM grande
  tem 7 MB, cerca de 10 MB em base64. **[chamada]** Os dois limites passam a 32 MiB. O mesmo
  ajuste do nginx é pré-requisito do upload de CSV de 5 MB (§7.2).

## 10. Serviço `ml-worker`

- `services/ml-worker/`, pacote `ottima_ml_worker`, porta de health **8005**, env
  `OTTIMA_HEALTH_URL_ML_WORKER` (default `http://ml-worker:8005/health`), incluído em
  `GET /api/health/workers`.
- `env_file` restrito a `OTTIMA_DATABASE_URL` e `OTTIMA_LOG_LEVEL`. Não usa Redis.
- Dependências: `ottima-core`, `fastapi`, `uvicorn`, `torch` (roda de CPU), `scikit-learn`,
  `optuna`. Sem pandas, sem bibmon, sem reservoirpy, sem tensorflow.
- **Limite de CPU:** o servidor on-prem é um só. O ml-worker limita as threads do torch e do
  BLAS (`OTTIMA_ML_THREADS`, default 2) e o serviço tem `cpus` limitado no compose, para o
  treino não disputar núcleo com o flow-runtime (anti-meta do §2).
- Sobe sem executar nada; job `running` órfão é marcado `failed` na partida.
- A stack passa de 8 para 9 serviços (`deploy/smoke.sh` conta serviços).

## 11. Testes e entregas

### Testes
- **TDD estrito** em lógica pura: módulo de inferência e teste de paridade (§6), montagem de
  janela e regra de lacuna (§7.3), parser de CSV (§7.2), tabela de qualidade com janela
  incompleta e janela contaminada (§5.4), máquina de estados da troca de modelo (§5.6),
  divisão por tempo (§8.1).
- **Integração:** ciclo de vida de job (fila, cancelamento, órfão), rotas e papéis, export e
  import com modelo.
- **E2E (L2):** opcsim → variável de laboratório → CSV → conjunto → treino PLS → ativação →
  `out` GOOD; troca de modelo com flow rodando sem a qualidade da saída piorar em nenhuma
  varredura; MPC com a estimativa como CV aplicando `fail_action` quando uma entrada do
  sensor virtual fica BAD (prova de que a saída inválida não cai no portão frio); e deploy de
  um flow com histórico íntegro em que `out` sai GOOD no primeiro passo de modelo (prova do
  pré-aquecimento).
- Marcar como `slow` os testes que treinam LSTM de verdade.

### Entregas (um plano por entrega, nesta ordem)
1. **SV-1 — Núcleo e blocos.** Propostas do §12 materializadas; artefato e módulo de
   inferência; três blocos; vínculo, comando e troca em paralelo; função de grade e
   pré-aquecimento; eventos; export/import.
   Testável com artefatos sintéticos, sem treino.
2. **SV-2 — Laboratório e conjuntos.** Variáveis e análises, CSV, serviço `ml-worker` com o
   job `dataset_build`, página Coleta e treino sem a parte de treino.
3. **SV-3 — Treino e otimização.** Jobs `train` e `tune`, lista de modelos e ativação na
   página, página Otimização.

### Deixado para quem implementa
- Layout fino das páginas e do modal de hiperparâmetros (seguir os padrões de `features/`).
- Distribuição dos valores não nulos de `W`, `Win` e `bias` do ESN (o contrato é o artefato do
  §6 e a semântica dos hiperparâmetros do §8.1).
- DDL exata, nomes de módulos, número da migration.
- Forma do `progress`/`result` em `ml_jobs`.
- Como o canvas busca os rótulos de porta (§5.1).

## 12. Propostas normativas (aguardando aceite)

### 12.1 ADR-046 — Sensor virtual: jobs de treino, artefato numérico e serviço ml-worker

**Status proposto:** Aceito na aprovação desta spec. **Emenda ao ADR-004** e ao **ADR-023**
(lista de serviços); relacionado a ADR-003, 011, 012, 018, 043.

- **D1 — Jobs discretos existem.** O ADR-004 previa reavaliar Celery/RQ quando surgisse um job
  discreto. Reavaliado: treino e otimização são jobs de minutos a horas, um por vez, sem
  necessidade de broker. Decisão: fila em tabela Postgres (`ml_jobs`), consumidor único
  (`ml-worker`), execução em processo filho. **Celery continua fora da stack.** MPC, scripts e
  OPC continuam loops vivos; nada do caminho de controle passa por fila.
- **D2 — Serviço `ml-worker`**, porta 8005, sem acesso ao barramento.
- **D3 — Artefato numérico.** Modelo treinado é persistido como metadados JSON + `.npz` sem
  pickle. O flow-runtime infere só com numpy e nunca importa biblioteca de treino.
- **D4 — Implementação única da inferência** em `ottima_core.softsensor`, com teste de paridade
  contra a biblioteca de treino.
- **D5 — Qualidade:** a tabela e a regra do §5.4.
- **D6 — Troca de modelo fora do grafo:** vínculo em tabela, `cmd = "soft_sensor_model"` em
  `flow.commands`, candidato em paralelo, promoção ou rejeição com evento. Nenhum canal novo.
- **D7 — Análises e conjuntos fora da retenção**, em tabelas comuns; variável de laboratório
  não é linha em `tags`.
- **D8 — Export:** leva variáveis de laboratório, modelos vinculados e vínculos; não leva
  análises nem conjuntos.
- **D9 — Pré-aquecimento pelo histórico:** ao instanciar o bloco, o runtime preenche o buffer
  a partir de `samples` com a mesma função de grade do conjunto de treino; falha ou ausência de
  tag nunca bloqueia o deploy (§5.7).

### 12.2 PRD

- **RF-301:** três tipos de bloco a mais na paleta.
- **Nova §5.19 — Sensor virtual (ADR-046):**
  - **RF-581** blocos `soft_sensor_pls/esn/lstm`, config e portas (§5.1).
  - **RF-582** período do modelo e passo a cada N varreduras (§5.2).
  - **RF-583** qualidade da saída (§5.4).
  - **RF-584** troca de modelo sem interrupção (§5.6).
  - **RF-585** variável de laboratório e análises por digitação e CSV (§7.1, §7.2).
  - **RF-586** conjunto de treino por período, janela contínua, congelado (§7.3).
  - **RF-587** treino dos três métodos com validação em ordem de tempo (§8.1).
  - **RF-588** otimização com Optuna (§8.2).
  - **RF-589** páginas Coleta e treino e Otimização, condicionais (§8.3).
  - **RF-590** modelo no arquivo de projeto (§9).
  - **RF-591** pré-aquecimento do bloco pelo histórico (§5.7).
- **§3 e §4:** serviço `ml-worker` e as entidades novas.
- **§7.1:** `flow.commands` ganha o `cmd` `soft_sensor_model`; `events` ganha os `kind`
  `soft_sensor_model_activated`, `soft_sensor_model_rejected`, `soft_sensor_model_missing`,
  `soft_sensor_extrapolating` e `soft_sensor_prewarm_skipped`.
- **§7.2:** campos novos do JSON de projeto. **§7.3:** grupo de API `/api/softsensor`.
- **§8:** fase nova com as três entregas do §11.

**Emenda à spec `F6-portabilidade-hardening.md` §3.2-1:** o teto do corpo do import passa de
4 MiB para 32 MiB (§9). Arrasta `MAX_IMPORT_BUNDLE_BYTES` e a mensagem em
`routers/projects.py`, `services/api/tests/test_projects_import.py`, o caso de 413 em
`tests/e2e/test_f6_portabilidade.py`, `frontend/src/features/projects/importar.check.ts` e o
`client_max_body_size` do `frontend/nginx.conf`. `schema_version` não muda.

### 12.3 GLOSSARY

| Termo | Identificador | Definição |
|---|---|---|
| Sensor virtual | `soft_sensor` | Bloco que estima uma variável de laboratório a partir de variáveis de processo, por um modelo treinado |
| Variável de laboratório | `lab_variable` | Grandeza medida por análise, identificada por nome único no projeto; não é tag |
| Análise | `lab_sample` | Um valor de uma variável de laboratório, carimbado com o instante da coleta da amostra |
| Conjunto de treino | `dataset` | Janelas de processo emparelhadas com análises, congeladas ao finalizar um período de coleta |
| Período do modelo | `period_s` | Intervalo entre passos do modelo, igual no treino e na operação |
| Aquecimento | `warmup` | Passos de modelo necessários até a saída ser válida |
| Modelo em uso / candidato | `active` / `candidate` | O modelo que produz a saída do bloco e o que está aquecendo para substituí-lo |

### 12.4 Dependências novas (só no `ml-worker`)

| Pacote | Por quê | Alternativa descartada |
|---|---|---|
| `torch` (CPU) | Treino do LSTM | TensorFlow: o SensorPredict declara, mas o código já usa PyTorch |
| `scikit-learn` | PLS, ridge, padronização, divisão por tempo, métricas | bibmon: só embrulhava isto |
| `optuna` | Otimização de hiperparâmetros, pedido explícito | busca em grade à mão |

`uv sync --all-packages` passa a baixar o torch no ambiente de desenvolvimento.

### 12.5 CLAUDE.md

- Invariante "Sem Celery, sem filas de job" passa a: "Sem Celery. O caminho de controle nunca
  passa por fila; a única fila é `ml_jobs`, do treino de sensor virtual (ADR-046)."
- Layout do monorepo ganha `services/ml-worker/`; a seção de comandos ganha o health 8005 e a
  contagem de 9 serviços.
- Invariante nova: "O flow-runtime nunca importa biblioteca de treino nem abre pickle; modelo
  de sensor virtual é `.npz` lido com `allow_pickle=False` (ADR-046)."
