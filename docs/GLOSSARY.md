# Glossário — OttimaSystem

> Termos do domínio com significado fixado para o projeto. Itens marcados ⚠️ ainda dependem de decisão na entrevista.

| Termo | Definição |
|---|---|
| **Projeto** | Unidade que agrupa flows + configurações do sistema (servidores OPC etc.). Exportável/importável em JSON, sem dados históricos. N projetos armazenados, **um ativo por vez**. |
| **Flow** | Grafo de blocos criado no canvas que implementa uma lógica/estratégia APC. Executa em scan cycle com Ts próprio. Pertence a um projeto. |
| **Scan cycle** | Semântica de execução: a cada Ts, todos os blocos do flow são avaliados em ordem topológica com os últimos valores conhecidos. |
| **Ts (tempo de amostragem)** | Período do scan de um flow. Valores permitidos: 0.5, 1, 2, 5, 10, 30, 60 s. Definido individualmente por flow. |
| **Bloco** | Nó do flow com entradas/saídas tipadas. Tipos da v1: OPC-Read, OPC-Write, MPC, Python-Script, TFS. |
| **opc-worker** | Processo asyncio que mantém as sessões OPC-UA (asyncua), publica leituras no barramento, executa escritas e opera o watchdog. Único processo que fala com PLC/DCS. |
| **flow-runtime** | Processo asyncio que interpreta e executa os flows (MPC, scripts) como loops vivos. |
| **recorder** | Consumidor do barramento que grava amostras na hypertable do TimescaleDB. |
| **Barramento** | Redis pub/sub interno: canais `opc.values.*` (leituras) e `opc.writes` (comandos de escrita). |
| **Loop vivo** | Processo contínuo que mantém estado e cicla indefinidamente (MPC, sessão OPC); task asyncio, nunca job de fila. |
| **Watchdog** | Bit alternante com NOT cruzado entre sistema e PLC (1 tag de leitura + 1 de escrita). Bit parado por >10 s ⇒ falha de comunicação ⇒ para escritas e para o flow; PLC retoma controle convencional. |
| **LOCAL / REMOTO** | Eixo de modo do MPC. LOCAL: PID do PLC controla. REMOTO: MPC assume. Transições bumpless nos dois sentidos, comandadas escrevendo o modo do PID no PLC (AUTO ↔ RCAS/CAS/ROUT). |
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
| **MV tracking** | Em LOCAL, a saída MV do MPC segue a MV real do PID (tag de readback), garantindo transição bumpless LOCAL→REMOTO. |
| **Log de eventos** | Hypertable de eventos (info/warning/alarm) com retenção de 1 mês; alimenta o banner de alarmes ativos (sem ACK) e a auditoria de operação. |
| **Hypertable** | Tabela particionada por tempo do TimescaleDB; amostras com retenção de 1 mês. |
| **Continuous aggregate** | Agregação materializada auto-atualizada do Timescale (ex.: média por minuto) para trends. |

## Dimensionamento-alvo
~10 flows simultâneos · ~100 tags OPC (R+W) · até 5 servidores OPC-UA · retenção 1 mês.
