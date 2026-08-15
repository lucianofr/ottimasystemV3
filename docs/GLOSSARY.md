# Glossário — OttimaSystem

> Termos do domínio com significado fixado para o projeto. Itens marcados ⚠️ ainda dependem de decisão na entrevista.

| Termo | Definição |
|---|---|
| **Projeto** | Unidade que agrupa flows + configurações do sistema (servidores OPC etc.). Exportável/importável em JSON, sem dados históricos. N projetos armazenados, **um ativo por vez**. |
| **Arquivo de projeto** | JSON de export/import de um projeto completo (projeto + conexões + tags + flows), sem dados históricos — mesma fronteira do `Projeto`. Chamado de `bundle` apenas no código (ex.: campo `ProjectImportIn.bundle`, módulo `ottima_core.portability`); **"bundle" é termo interno de código e não aparece em nenhuma string de tela**. Traz `schema_version` para evolução do formato e passa por 4 camadas de validação antes de aplicar ao banco. |
| **Pendência** | Condição de configuração de uma conexão que impede o `opc-worker` de subir a sessão OPC-UA (senha ou certificado faltando). Calculada sob demanda a partir dos dados já existentes da conexão (`auth_mode`, presença de senha, `security_policy`, certificados — os 3 predicados `needs_password`/`needs_server_certificate`/`needs_app_certificate`), **nunca persistida como estado no banco**. Reportada ao importar um `Arquivo de projeto` (`pending_secrets` na resposta de import), para o admin completar os segredos antes do deploy. |
| **Flow** | Grafo de blocos criado no canvas que implementa uma lógica/estratégia APC. Executa em scan cycle com Ts próprio. Pertence a um projeto. |
| **Scan cycle** | Semântica de execução: a cada Ts, todos os blocos do flow são avaliados **em ordem crescente de `exec_order`** com os últimos valores conhecidos. |
| **exec_order** | Parâmetro de todo bloco: inteiro único de 1 a N que define a ordem de execução na varredura (leituras < Script/MPC < escritas). Auto-numerado na inserção, editável, com badge no nó. Ordem invertida em relação a uma aresta ⇒ consumo do valor da varredura anterior (1 scan de atraso). |
| **Ts (tempo de amostragem)** | Período do scan de um flow. Valores permitidos: 0.5, 1, 2, 5, 10, 30, 60 s. Definido individualmente por flow. |
| **Bloco** | Nó do flow com entradas/saídas tipadas. Tipos da v1: OPC-Read, OPC-Write, MPC, Python-Script, TFS, Filtro 1ª ordem, Filtro Kalman, Fuzzy, PID. |
| **opc-worker** | Processo asyncio que mantém as sessões OPC-UA (asyncua), publica leituras no barramento, executa escritas e opera o watchdog. Único processo que fala com PLC/DCS. |
| **flow-runtime** | Processo asyncio que interpreta e executa os flows (MPC, scripts) como loops vivos. |
| **recorder** | Consumidor do barramento que grava amostras na hypertable do TimescaleDB. |
| **Barramento** | Redis pub/sub interno: canais `opc.values.*` (leituras) e `opc.writes` (comandos de escrita). |
| **Loop vivo** | Processo contínuo que mantém estado e cicla indefinidamente (MPC, sessão OPC); task asyncio, nunca job de fila. |
| **Watchdog** | Bit alternante com NOT cruzado entre sistema e PLC, configurado **por flow** (não por conexão): um flow escolhe a conexão OPC-UA e o par de nós (1 leitura + 1 escrita, distintos) por onde o handshake passa. O sistema copia o bit lido para a escrita sem inverter; o PLC aplica o NOT do lado dele. Bit parado por >10 s ⇒ falha de comunicação daquele flow ⇒ para as escritas e para o flow; flows-irmãos na mesma conexão não são afetados; PLC retoma controle convencional. |
| **LOCAL / REMOTO** | Eixo de modo do MPC. LOCAL: PID do PLC controla. REMOTO: MPC assume. Transições bumpless nos dois sentidos, comandadas escrevendo o modo do PID no PLC (AUTO ↔ RCAS/CAS/ROUT). |
| **PID** | Bloco do canvas (não o PID de campo do PLC — ver **LOCAL/REMOTO**) com uma entrada **`pv`** (obrigatória), uma entrada **`sp`** opcional (sobrepõe o `setpoint` da config quando conectada) e uma saída **`out`**. Estrutura **ISA**, configurado por **`kc`** (ganho), **`ti_seconds`** (tempo integral), **`td_seconds`** (tempo derivativo) e limites de saída (`output_min`/`output_max`). Cobre malhas sem PID de campo ou malhas auxiliares/computadas dentro do canvas — não substitui nem interage com os eixos de modo do MPC. |
| **Tempo integral (Ti)** | Parâmetro do bloco PID, em **segundos por repetição**. Reset em repetições por segundo é `1/Ti`. **`Ti = 0` desliga a ação integral** (convenção documentada, permite P ou PD puro). |
| **Tempo derivativo (Td)** | Parâmetro do bloco PID, em **segundos**. **`Td = 0` desliga a ação derivativa**. |
| **Ganho (Kc)** | Ganho da forma ISA do bloco PID. Qualquer sinal — **negativo é ação reversa**. |
| **MAN / AUTO** | Sub-modo de REMOTO. MAN: operador escreve as MVs pela UI. AUTO: MPC calcula. Em LOCAL o sistema não escreve MV. |
| **RCAS / CAS / ROUT** | Modos do PID no PLC usados pelo APC: SP remoto em cascata (RCAS/CAS) ou saída remota direta (ROUT). Determina o que o MPC escreve por MV. |
| **Bumpless** | Transferência de controle sem salto na MV: MPC inicializa nas MVs atuais ao assumir; PID faz SP/OUT-tracking ao retomar. |
| **Hot-swap** | Edição de flow em execução aplicada atomicamente na próxima varredura, sem interrupção e preservando estado dos blocos não alterados. |
| **PV / MV / SP / CV / DV** | Variável de processo / manipulada / setpoint / controlada / distúrbio — nomenclatura padrão APC. |
| **Admin** | Papel de engenharia: cria/edita flows, conexões OPC, tags, projetos, usuários — e tudo que o operador faz. |
| **Operador** | Papel de operação (ex-"visualizador"): troca LOCAL/REMOTO e MAN/AUTO, escreve SP e MV (em MAN); enxerga tudo; não edita engenharia. |
| **TSS** | Time to Steady State: tempo aproximado até o processo estabilizar após mudança na entrada. Informado por CV; deriva Np/Nc automaticamente. |
| **SOPDT** | Modelo de 2ª ordem com tempo morto (K, τ1, τ2, θ) por par MV→CV / DV→CV, para CVs autorreguláveis. |
| **Processo integrador** | CV que não estabiliza (rampa); modelado por ganho integrador Ki + θ por par. Tipo de resposta definido por CV. |
| **Multiplicador (MPC)** | N tal que o bloco MPC executa a cada N varreduras do flow (Ts_mpc = N × Ts_flow). |
| **Deploy** | Ato explícito de colocar um flow em execução. Após boot, flows sobem parados aguardando deploy. |
| **Faceplate** | Painel de operação de um elemento: principal (modos/status/comandos do MPC) e menores (uma variável cada: CV+SP, MV, DV). |
| **Tela de operação** | Tela dedicada por MPC: faceplate principal + faceplates das variáveis (base) + tendência central com histórico e **predição** (PVs/MVs no horizonte Np). |
| **Predição** | Trajetória futura de PVs/MVs calculada no último solve; publicada no barramento (`mpc.state.*`), exibida na tendência, nunca persistida. |
| **IN*n* / OUT*n*** | Convenção de portas do bloco Python-Script: entradas viram variáveis IN1..INn; o script escreve OUT1..OUTn. |
| **state (script)** | Dict persistente por instância do bloco de script, preservado entre varreduras (filtros, rampas, totalizadores). |
| **Restrição (variável)** | Categoria de variável do MPC controlada dentro de uma **faixa** (low/high), sem SP, com **precedência sobre as CVs** (soft constraint com slack e penalidade dominante). |
| **TFS** | Bloco de simulação: matriz de funções de transferência até 2×2, cada elemento SOPDT ou IOPDT, em tempo discreto no Ts do flow. Fecha malha com o MPC sem PLC/OPC. |
| **IOPDT** | Modelo integrador com tempo morto (Ki, θ) — usado em CVs/Restrições integradoras e no bloco TFS. |
| **Filtro 1ª ordem** | Bloco de uma entrada e uma saída que suaviza o sinal por atraso de 1ª ordem, com parâmetro único `tau` (constante de tempo, em segundos), discretizado no Ts do flow. |
| **Filtro Kalman** | Bloco de uma entrada e uma saída que estima o valor verdadeiro de um sinal ruidoso (passeio aleatório escalar). Configurado por dois desvios padrão na EU do sinal: `measurement_noise` (ruído da medição) e `process_noise` (variação esperada do valor verdadeiro por varredura). |
| **MV tracking** | Em LOCAL, a saída MV do MPC segue a MV real do PID (tag de readback), garantindo transição bumpless LOCAL→REMOTO. |
| **Log de eventos** | Hypertable de eventos (info/warning/alarm) com retenção de 1 mês; alimenta o banner de alarmes ativos (sem ACK) e a auditoria de operação. |
| **Hypertable** | Tabela particionada por tempo do TimescaleDB; amostras com retenção de 1 mês. |
| **Continuous aggregate** | Agregação materializada auto-atualizada do Timescale (ex.: média por minuto) para trends. |

## Dimensionamento-alvo
~10 flows simultâneos · ~100 tags OPC (R+W) · até 5 servidores OPC-UA · retenção 1 mês.
