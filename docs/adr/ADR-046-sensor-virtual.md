# ADR-046 — Sensor virtual: jobs de treino, artefato numérico e serviço ml-worker

**Status:** Aceito · 2026-11-25 · **Emenda ao ADR-004** (passa a existir um job discreto: o treino) **e ao ADR-023** (a lista de serviços do Compose ganha o `ml-worker`; a stack passa de 8 para 9 serviços) · Relacionado: ADR-003, 011, 012, 018, 043 · Spec: `docs/specs/SPEC_SENSOR_VIRTUAL.md` · Emendado em 2026-11-27 (D1: raias de otimização e geral no `ml-worker`)

## Contexto
Um **sensor virtual** estima, a cada varredura, uma variável que só existe como análise de laboratório (teor, viscosidade, ponto de fulgor) a partir de variáveis contínuas de processo. Hoje isso roda num aplicativo desktop separado (SensorPredict), com seu próprio cliente OPC-UA, seu próprio histórico em SQLite e sem nenhuma das garantias de qualidade de sinal do Ottima. Trazê-lo para dentro dá ao sensor virtual o histórico contínuo das entradas, a qualidade fim a fim (ADR-043), a execução no flow e a possibilidade de a estimativa alimentar um PID ou um MPC. Como a saída pode ser só indicação **ou** fechar malha, enquanto o valor não for confiável a qualidade da saída é BAD (ou UNCERTAIN) — nunca um número com cara de bom.

Os três métodos a portar (regressão PLS, Echo State Network e LSTM) treinam com `torch`, `scikit-learn` e `optuna`, o que custa gigabytes de imagem. O porte fiel instalaria tudo isso no `flow-runtime` — o processo que escreve na planta — e carregaria arquivos pickle (`joblib.load`) nesse mesmo processo, quebrando o carregamento a qualquer diferença de versão entre quem treinou e quem executa. ONNX foi descartado: é dependência nova no `flow-runtime` e o ESN não tem exportador pronto (a conta seria escrita à mão de qualquer jeito). Escolhido pelo usuário: **treino pesado fora, inferência leve dentro** — um serviço novo concentra as bibliotecas pesadas e grava o modelo como números puros; o bloco calcula a estimativa só com numpy, que o `flow-runtime` já tem.

O ADR-004 previa reavaliar Celery/RQ quando surgisse um job discreto (a decisão original citava treino de modelo como exemplo). Treino e otimização de hiperparâmetros são esses jobs: duram minutos a horas, rodam um por vez e não pertencem ao caminho de controle. O conjunto de treino é montado por **janela contínua** (para cada análise coletada em *t*, o trecho de dados de processo que termina em *t*, no período de amostragem do modelo), e não por uma linha por análise como no SensorPredict: o bloco alimenta o modelo nesse mesmo período, então treino e operação enxergam a mesma escala de tempo. Consequências aceitas: as métricas saem mais baixas e mais honestas, o período do modelo é parâmetro do conjunto e o Ts do flow precisa ser divisor dele.

## Decisão

### D1 — Jobs discretos existem
O ADR-004 previa reavaliar Celery/RQ quando surgisse um job discreto. Reavaliado: treino e otimização são jobs de minutos a horas, um por vez, sem necessidade de broker. Decisão: fila em tabela Postgres (`ml_jobs`), consumidor único (`ml-worker`), execução em processo filho. **Celery continua fora da stack.** MPC, scripts e OPC continuam loops vivos; nada do caminho de controle passa por fila.

Contrato da fila (spec §7.5): `ml_jobs(kind ∈ {dataset_build, train, tune}, status ∈ {queued, running, done, failed, cancelled}, params, progress, result, error, cancel_requested, …)`. O `ml-worker` consulta a tabela a cada 2 s (`FOR UPDATE SKIP LOCKED`) e executa **um job por vez** — por raia, desde a emenda de 2026-11-27 —, num processo filho (`multiprocessing` com `spawn`). Cancelar = a API liga `cancel_requested` e o laço do `ml-worker` mata o filho. O filho devolve o progresso ao pai por `Pipe`. Job `running` órfão (reinício do serviço) vira `failed` com o erro "interrompido pelo reinício do serviço"; não há retomada. O estudo do Optuna é em memória, dentro do filho — nenhuma tabela do Optuna no banco.

> **Emendado em 2026-11-27 (§Emenda — raias do ml-worker):** "um job por vez" passa a valer por raia; são duas raias, otimização (`tune`) e geral (demais kinds).

### D2 — Serviço `ml-worker`, porta 8005, sem acesso ao barramento
Pacote `ottima_ml_worker` em `services/ml-worker/`; health na porta **8005** (`OTTIMA_HEALTH_URL_ML_WORKER`, default `http://ml-worker:8005/health`, incluído em `GET /api/health/workers`). Não usa Redis. Mesmo padrão do RNF-04/ADR-018: o `env_file` lista só `OTTIMA_DATABASE_URL` e `OTTIMA_LOG_LEVEL`. Sobe sem executar nada. **Limite de CPU:** o servidor on-prem é um só; o serviço limita as threads do torch e do BLAS (`OTTIMA_ML_THREADS`, default 2) e tem `cpus` limitado no Compose, para o treino não disputar núcleo com o `flow-runtime` (treino ou Optuna atrasarem a varredura de qualquer flow é anti-meta).

### D3 — Artefato numérico, sem pickle
Modelo treinado é persistido como **metadados JSON + `.npz`** (`numpy.savez_compressed`, matrizes em `float32`), lido sempre com `allow_pickle=False`. O `flow-runtime` infere só com numpy e **nunca** importa biblioteca de treino nem abre pickle/joblib. Metadados: `schema_version`, `method` (`pls`/`esn`/`lstm`), `period_s`, `inputs[{name, eu, min, max}]` na ordem das portas, `output{name, eu}`, hiperparâmetros, `warmup_steps`, métricas, `trained_at` e ids do(s) conjunto(s) de origem. Pesos: PLS `w`, `b`; ESN `W`, `Win`, `bias`, `Wout`, `b_out`, `lr`, `x_mean`, `x_std`, `y_mean`, `y_std`; LSTM, por camada, `w_ih`, `w_hh`, `b_ih`, `b_hh`, mais `fc_w`, `fc_b`, `x_mean`, `x_std`, `y_mean`, `y_std`. Teto de 8 MB por artefato (o maior LSTM da busca dá cerca de 7 MB); treino cujo resultado estoura falha com mensagem.

### D4 — Implementação única da inferência
A conta de cada método mora em `ottima_core.softsensor` (só numpy) e é a **única** implementação: o `flow-runtime` a usa para operar e o `ml-worker` a usa para calcular métricas e validar o que exporta. **Todo modelo é uma função pura das últimas `K` amostras** (PLS `K = 1`; ESN `K = warmup`; LSTM `K = L`), lidas de um buffer circular de 256 amostras **por modelo** — nenhum modelo carrega estado numérico próprio entre passos, o que garante que treino e operação enxergam a mesma coisa. PLS roda inline; ESN e LSTM rodam por `run_in_executor`. **Teste de paridade obrigatório (TDD):** para PLS e LSTM, a saída do módulo sobre o artefato exportado é igual à da biblioteca que treinou (`PLSRegression.predict`, `torch`) em entradas aleatórias, tolerância `1e-4`; o ESN, sem biblioteca de referência (o próprio módulo calcula os estados no treino), ganha teste de valor fixo com semente fixa.

### D5 — Qualidade
A tabela e a regra abaixo valem para os três métodos e implementam o ADR-043 (`ok ≡ quality is GOOD`; a qualidade nunca sobe).

| Situação | Valor | Qualidade |
|---|---|---|
| Bloco sem modelo ativo, nunca produziu valor | `None` | BAD |
| Primeiro aquecimento após deploy ou retomada | `None` | BAD |
| Janela com amostra BAD (entrada BAD agora ou há menos de `K` passos) | último calculado | BAD |
| Modelo devolve NaN ou infinito | último calculado | BAD |
| Alguma amostra da janela UNCERTAIN | calculado neste passo | UNCERTAIN |
| Alguma amostra da janela fora da faixa vista no treino | calculado neste passo | UNCERTAIN |
| Tudo válido | calculado neste passo | GOOD |

1. A cada passo de modelo, o bloco grava no buffer os valores das portas e a pior qualidade entre elas; porta sem valor conta como BAD.
2. Para um modelo, a qualidade de cada amostra da sua janela (as últimas `K`) é a qualidade gravada, rebaixada a UNCERTAIN se alguma entrada estiver fora de `[min − 5%·span, max + 5%·span]` do treino **daquele modelo** (faixas no artefato).
3. Janela incompleta ou com alguma amostra BAD: o modelo não é calculado; a saída é BAD.
4. Janela completa e sem BAD: o modelo é calculado; a qualidade da saída é a pior da janela (GOOD ou UNCERTAIN). Resultado não finito: BAD.
5. Entre passos de modelo, a saída mantém o último valor, com qualidade `min(qualidade do último passo, pior porta na varredura atual)`.

**`None` só existe antes do primeiro resultado.** A saída é `v = None` apenas enquanto o bloco nunca produziu valor desde que foi instanciado (deploy, retomada, sem modelo). Depois disso, toda saída BAD **mantém o último valor calculado**, com qualidade BAD. Motivo: no Ottima `v = None` é o sinal de *cold start*, não de medição inválida (convenção do ADR-043 D7). O MPC que recebe `None` numa CV sai pelo portão frio (`has_cold_input`, `blocks/mpc.py`) **antes** do tratamento de entrada inválida (`fail_action`, `fail_timeout_s`, queda da malha): uma saída `None` no meio da operação deixaria o MPC parado no portão frio em vez de derrubar a malha para o PLC.

O bloco emite eventos **só na borda** (entrada e saída do estado), nunca por varredura: `soft_sensor_extrapolating` (início/fim) e `soft_sensor_model_missing`.

### D6 — Troca de modelo fora do grafo
O vínculo bloco → modelo mora em tabela (`soft_sensor_bindings(flow_id, block_id, desired_model_id, active_model_id, candidate_model_id, …)`), **não** na config do grafo: um modelo guardado na config mudaria o bloco a cada troca, o hot-swap o recriaria (ADR-011) e abriria o buraco de BAD que este desenho evita. Mecanismo:

1. `POST /api/operate/{flow_id}/{block_id}/model` com `{model_id}` (`require_admin`): a API valida (método = tipo do bloco, `n_inputs` igual, `period_s` múltiplo do Ts), grava `desired_model_id` e publica `FlowCommand(cmd="soft_sensor_model")` em `flow.commands`. Responde 202; a API não emite evento (mesmo desenho do `mpc_sp`).
2. O runtime carrega o artefato fora do event loop e cria o **candidato**, gravando `candidate_model_id`. O buffer do candidato nasce como cópia do buffer do modelo em uso quando os dois têm o mesmo período; com período diferente, nasce pré-aquecido pelo histórico (D9) ou, se isso não for possível, vazio. Os dois modelos são calculados a cada passo, cada um no seu período; a saída do bloco continua sendo a do modelo em uso.
3. O candidato é **promovido** no primeiro passo em que **calculou um valor** (janela completa, sem BAD, resultado finito) e a qualidade desse valor é **maior ou igual** à da saída do modelo em uso: a troca nunca piora a saída. O runtime grava `active_model_id`, limpa `candidate_model_id`, descarta o antigo e emite `soft_sensor_model_activated`.
4. Sem promoção em `2 × K × period_s` (mínimo 60 s), o candidato é descartado, o antigo continua, o runtime limpa `candidate_model_id`, devolve `desired_model_id` ao modelo que o bloco vai acabar rodando (o pedido enfileirado, o candidato em curso, o em uso ou NULL), e só se ele ainda aponta para o rejeitado e emite `soft_sensor_model_rejected` (warning) com o motivo (janela incompleta, entrada BAD ou extrapolação). A mesma devolução vale para a recusa no comando (método, `n_inputs`, período, artefato ilegível). Condicional por emenda de 2026-11-25 (implementação SV-1): um pedido mais novo, gravado pela API durante a recusa, não é desfeito.
5. Bloco sem modelo em uso: o candidato vira o modelo em uso na hora. Flow parado: só `desired_model_id` muda; o próximo deploy carrega `desired_model_id` direto e iguala `active_model_id` ao modelo realmente carregado (NULL sem modelo, com artefato ilegível ou incompatível), com `candidate_model_id` NULL. Flow que para ou cai em falha com uma troca em voo tem `candidate_model_id` limpo pelo runtime, sem esperar o banco; `desired_model_id` fica. Uma segunda ativação durante a troca substitui o candidato. (emenda de 2026-11-25 (implementação SV-1): a igualação de `active_model_id` e a limpeza na parada.)

**Regra do Estado Publicado (ADR-002):** o que a página chama de "em uso" e de "aquecendo" vem só de colunas que **o runtime** grava (`active_model_id`, `candidate_model_id`); `desired_model_id`, que a API grava, nunca é mostrado como estado — quando difere de `active_model_id` e não há candidato, a página mostra "aguardando o runtime". **Nenhum canal novo:** o único acréscimo ao barramento é o `cmd` `soft_sensor_model` em `flow.commands` e os `kind`s novos em `events` (`soft_sensor_model_activated`, `soft_sensor_model_rejected`, `soft_sensor_model_missing`, `soft_sensor_extrapolating`, `soft_sensor_prewarm_skipped`). O vínculo é apagado no save do flow quando o `block_id` sai do grafo ou muda de tipo (mesma faxina do ADR-041); modelo vinculado a um bloco (qualquer das três colunas) não pode ser apagado.

### D7 — Análises e conjuntos fora da retenção
Análises de laboratório e conjuntos de treino ficam em **tabelas Postgres comuns** (não hypertables, sem policy de retenção): análise é retroativa e não pode sumir com a retenção do ADR-003. A **variável de laboratório não é linha em `tags`**: entrar em `tags` a faria aparecer no seletor de tags do canvas, nas entradas de tag calculada e na lista do TREND, sempre com série vazia, porque os valores não vão para `samples`. O conjunto congela as janelas (`W = 256` passos de modelo, `.npz`) no `dataset_build`, justamente para sobreviver à retenção; o treino aceita vários conjuntos compatíveis, concatenados em ordem de tempo.

### D8 — Export
O arquivo de projeto passa a levar as **variáveis de laboratório** (definições), os **modelos referenciados por algum vínculo** (metadados + pesos em base64) e os **vínculos**. **Não** leva análises nem conjuntos de treino: são dado histórico, a mesma fronteira do ADR-012. Sem o modelo no bundle, um flow importado teria um bloco que nunca sai de BAD. Tags de entrada do modelo viajam como referência de tag do bundle e são religadas no import; referência que não resolve não impede o import (o bloco apenas não pré-aquece). `schema_version` **continua 1** (campos novos opcionais; o import recusa qualquer versão diferente de 1). O teto do corpo do import sobe de 4 MiB para **32 MiB** (um LSTM de 7 MB dá cerca de 10 MB em base64), com o mesmo ajuste no `client_max_body_size` do nginx do frontend — emenda à spec `F6-portabilidade-hardening.md` §3.2-1.

### D9 — Pré-aquecimento pelo histórico
Ao **instanciar** o bloco com um modelo vinculado (deploy, retomada, hot-swap que o recria), o runtime preenche o buffer de 256 passos a partir de `samples`, com a **mesma função de grade** do congelamento do conjunto de treino (compartilhada em `ottima_core.softsensor`, para treino, conjunto e pré-aquecimento nunca divergirem). Grade: instantes `agora − k × period_s`, `k = 1..256` contados do pré-aquecimento, sendo o primeiro passo do bloco o ponto `k = 0` (emenda de 2026-11-25 (implementação SV-1): esse ponto é a amostra real da primeira varredura; tirá-lo também do histórico o poria duas vezes na janela); cada ponto é o último valor da tag em ou antes do instante, não mais velho que `max(3 × period_s, 180 s)`. A qualidade de cada ponto é a gravada em `samples`; ponto sem amostra válida dentro da tolerância (lacuna, ou amostra BAD gravada como NULL, ADR-037) entra no buffer como BAD. Com histórico íntegro, o primeiro passo de modelo já calcula um valor; com lacuna dentro da janela, a saída fica BAD pela regra de D5.

**Falha ou ausência de tag nunca bloqueia o deploy:** se alguma tag de entrada do modelo não existe mais ou a consulta não responde em 5 s, o buffer fica vazio (aquecimento completo) e sai o evento `soft_sensor_prewarm_skipped` (info) com o motivo. A consulta roda na instanciação, fora do laço de varredura. Premissa: o histórico guarda o valor cru da tag; as amostras reais das portas substituem as do histórico à medida que os passos acontecem.

### Dependências novas (só no `ml-worker`)
CLAUDE.md exige justificativa para dependência fora da stack declarada. O `flow-runtime` **não ganha nenhuma**.

| Pacote | Por quê | Alternativa descartada |
|---|---|---|
| `torch` (CPU) | Treino do LSTM | TensorFlow: o SensorPredict declara, mas o código já usa PyTorch |
| `scikit-learn` | PLS, ridge, padronização, divisão por tempo, métricas | bibmon: só embrulhava isto |
| `optuna` | Otimização de hiperparâmetros, pedido explícito | busca em grade à mão |

`uv sync --all-packages` passa a baixar o torch no ambiente de desenvolvimento. Sem pandas, bibmon, reservoirpy ou tensorflow: o gerador das matrizes do ESN é numpy (`default_rng(seed)`) porque as matrizes viajam no artefato e o gerador não faz parte do contrato de operação.

## Consequências
- (+) O `flow-runtime` continua sem torch, scikit-learn ou optuna e nunca abre pickle: zero dependência nova no processo que escreve na planta, custo de varredura medido e previsível (ESN 500 unidades com `warmup` 100: 5 ms por passo; LSTM 64×2 com janela 10: 0,9 ms; tetos de busca 11 ms e 28 ms).
- (+) O modelo vira dado: cabe no export do projeto e não quebra por diferença de versão de biblioteca entre treino e operação.
- (+) Uma implementação só da inferência, com teste de paridade contra a biblioteca que treinou; treino e operação enxergam exatamente as mesmas últimas `K` amostras.
- (+) A troca de modelo não passa pelo grafo: sem hot-swap, sem buraco de BAD, e nunca piora a qualidade da saída.
- (+) Treino e Optuna num serviço próprio, com CPU limitada: não atrasam a varredura de nenhum flow.
- (−) A conta de cada método é escrita à mão em numpy, e o teste de paridade precisa ser mantido (é ele que impede o porte de divergir em silêncio). O `units` do ESN tem teto de 500: com 1000 unidades a iteração sai do cache e o passo chega a 1,7 s.
- (−) A stack passa de 8 para 9 serviços (`deploy/smoke.sh` conta serviços) e a imagem do `ml-worker` é grande (torch). O ADR-004 deixa de valer sem ressalva: existe uma fila, `ml_jobs`, restrita ao treino.
- (−) **Aquecimento:** a saída só é válida depois de `K × period_s` de dado bom contínuo (ESN com `warmup = 200` e período de 60 s: 3 h 20 min), e esse tempo é pago de novo depois de cada amostra BAD em qualquer entrada, até ela sair da janela. O pré-aquecimento (D9) elimina o custo depois de um deploy com histórico íntegro.
- (−) **Limitação residual do pré-aquecimento:** depois de uma falha de comunicação o histórico do período é BAD e a janela fica contaminada; como o bloco recém-instanciado ainda não calculou nenhum valor, a saída é `None`, e um MPC que use a estimativa como CV fica inteiro no portão frio até a janela ficar limpa (`K × period_s` depois de o dado bom voltar).
- (−) Os modelos são válidos só para o `period_s` do conjunto de treino: o Ts do flow precisa ser divisor dele, a ativação recusa (422) quando não for e o deploy de um flow cujo Ts deixou de dividir o período sobe o bloco sem modelo (`soft_sensor_model_missing`).
- Fora desta decisão (não-metas): SPE e contribuições por variável, análise de laboratório como entrada do modelo, importação de Excel/`.spm`, escrita automática de métricas em tag OPC, detecção de deriva do modelo, variável de laboratório no TREND e GPU.

## Emenda — raias do ml-worker (2026-11-27)

**Contexto:** D1 fixou um job por vez no serviço inteiro. Uma otimização (`tune`) de ESN chega a
durar horas (centenas de tentativas, cada uma calculando a predição janela por janela), e
enquanto ela roda nenhuma montagem de conjunto (`dataset_build`) nem treino manual (`train`)
sai da fila.

**Decisão:** o `ml-worker` passa a ter **duas raias**, cada uma executando **um job por vez**
num processo filho `spawn` próprio:

- **raia de otimização:** só jobs `kind = 'tune'`;
- **raia geral:** todo outro kind (definida por exclusão: um kind novo cai nela).

No máximo dois filhos simultâneos (um `tune` e um outro); dois `tune` continuam serializados.
Continua sendo **um único serviço consumidor** e a fila continua em tabela Postgres (`ml_jobs`,
`FOR UPDATE SKIP LOCKED`, ordem por id dentro da raia). Cancelamento, progresso por `Pipe` e
tratamento de órfão seguem D1, por job. A varredura de órfãos de cada raia fica restrita aos
kinds dela — na subida (a união das duas cobre a fila inteira) e no re-arme após erro —, para
nunca alcançar o job vivo da outra raia. O `/health` do serviço mantém `job.running_id` (raia
geral) e ganha `job.tune_running_id`.

**Consequência:** as duas raias dividem o mesmo limite de CPU do contêiner (D2); com dois
filhos ao mesmo tempo, cada um com `OTTIMA_ML_THREADS` threads de BLAS, o contêiner pode
pedir o dobro de threads. Nada muda no caminho de controle nem na contagem de filas.
