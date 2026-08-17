import type { TooltipContent } from "../../../components/ui/tooltip";

/**
 * Conteúdo dos tooltips de campo do modal MPC (pedido do usuário: descrição completa +
 * exemplo ao passar o mouse sobre o nome do parâmetro). Fonte de cada entrada: docstrings
 * Pydantic de `mpc_config.py` (contrato real, gerado em `graph.ts`), PRD §5.9/§5.10/§5.16
 * (RF-601..628, RF-901..903) e a tabela de dominância de `ssto.py`. Nunca invenção — texto
 * pt-BR próprio, mas o CONTEÚDO técnico é rastreável até essas três fontes.
 *
 * Agrupado por onde cada campo aparece; conceitos idênticos entre categorias (kind/
 * prioridade/ação de falha de CV e Restrição são o MESMO tipo no backend, `RowKind`/
 * `RowFailAction`) ficam em `AJUDA_LINHA`, uma entrada só, reaproveitada nos dois lugares —
 * evita duas cópias divergindo com o tempo.
 */

// Cabeçalho do modal (MpcModal.tsx) + aba Geral (TabGeneral.tsx)
export const AJUDA_GERAL = {
  rotulo: {
    description:
      "Rótulo de exibição genérico do bloco no canvas do editor — todo tipo de bloco tem um (OPC-Read, Script, TFS…), não é exclusivo do MPC. Diferente do campo Nome (aba Geral): o Nome é o que o operador vê nas telas de operação; o Rótulo é só a etiqueta do bloco no grafo de engenharia.",
    example: "'MPC coluna C-101' no canvas, enquanto o Nome pode ser 'Coluna C-101'.",
  },
  execOrder: {
    description:
      "Posição deste bloco na ordem de execução do flow (ADR-024) — os blocos rodam estritamente em ordem crescente, nunca por dependência topológica. Um MPC precisa executar depois dos blocos de leitura que alimentam suas CVs/DVs e antes dos blocos de escrita que aplicam suas MVs.",
    example:
      "leituras em 1-5, MPC em 6, escritas em 7-8 — inverter a ordem faz o MPC calcular com o valor da varredura anterior.",
  },
  nome: {
    description:
      "Nome de negócio deste bloco MPC (distinto do Rótulo do canvas) — é o que aparece pro operador nas telas de operação (seletor de MPC, faceplate principal, trend) e no histórico.",
    example: "'Coluna de destilação C-101' — mais descritivo que o rótulo técnico do editor.",
  },
  multiplicador: {
    description:
      "Quantas varreduras do flow se passam entre uma execução do MPC e a próxima (RF-606) — entre execuções, as saídas mantêm o último valor calculado. Define Ts_mpc = multiplicador × Ts_flow.",
    example:
      "flow com Ts_flow=1 s e multiplicador=5 → o MPC resolve a cada 5 s, mesmo a leitura das tags acontecendo a cada 1 s.",
  },
  tsMpc: {
    description:
      "Período de execução do MPC, derivado — nunca editado diretamente (RF-603). Ts_mpc = multiplicador × Ts_flow; é a base de tempo usada pra converter taxas (Δu, τ da trajetória) e pra derivar Np/Nc na aba Horizontes.",
    example: "Ts_flow=2 s, multiplicador=3 → Ts_mpc=6 s.",
  },
} satisfies Record<string, TooltipContent>;

// Campos comuns a MV/CV/Restrição(/DV para zero e span) — CampoNomeEu/CampoZeroSpan em
// TabVariables.tsx, um único ponto de render pras 4 categorias.
export const AJUDA_COMUM = {
  nome: {
    description:
      "Nome de engenharia da variável — aparece na matriz de Modelos, na aba Horizontes e nos faceplates de operação.",
    example: "'Nível do tanque V-101', 'Vazão de refluxo', 'Temperatura do prato 12'.",
  },
  eu: {
    description:
      "Unidade de engenharia da variável, texto livre — só documentação, não afeta nenhum cálculo (a conversão dos ganhos usa Zero/Span, não este texto).",
    example: "'%', 'm³/h', '°C', 'kg/h'.",
  },
  descricao: {
    description:
      "Descrição curta da variável (RF-610), até 14 caracteres — aparece embaixo do nome no faceplate de operação, onde o espaço é apertado. Opcional; não afeta nenhum cálculo.",
    example: "'Nível V-101' ou 'Refluxo' — o nome completo já está nesta aba.",
  },
  zero: {
    description:
      "Início da faixa de instrumento desta variável [zero, zero+span] (RF-609) — junto com Span, define a escala usada pra converter os ganhos %/% da matriz de Modelos pra EU real, e a escala da barra no faceplate.",
    example: "transmissor 4-20 mA calibrado pra 0-100 °C → zero=0.",
  },
  span: {
    description:
      "Extensão da faixa de instrumento a partir do Zero (RF-609): faixa = [zero, zero+span]. Os ganhos K/Ki da matriz de Modelos são adimensionais (%/%) — o motor multiplica por span_linha/span_coluna pra chegar na EU real. Default 100 preserva o comportamento anterior a este campo.",
    example: "zero=0 e span=5000 pra um transmissor calibrado 0-5000 kg/h.",
  },
} satisfies Record<string, TooltipContent>;

// Aba Variáveis — lista de MVs (TabVariables.tsx) + seção PID (CamposPid.tsx)
export const AJUDA_MV = {
  limiteMin: {
    description:
      "Limite físico inferior de curso do atuador desta MV, na coordenada absoluta da planta (mesma referência do Valor inicial e do Ponto de operação) — limite DURO, nunca ultrapassado pelo solver nem pelo SSTO.",
    example: "válvula 0-100% de abertura → limite mín.=0.",
  },
  limiteMax: {
    description:
      "Limite físico superior de curso do atuador desta MV, na coordenada absoluta da planta — limite DURO, nunca ultrapassado pelo solver nem pelo SSTO.",
    example: "válvula 0-100% de abertura → limite máx.=100.",
  },
  maxRate: {
    description:
      "Taxa máxima de variação desta MV, em EU por segundo (RF-604 revisado) — o solver nunca pede um movimento maior que max_rate × Ts_mpc num único ciclo.",
    example:
      "atuador que não deve variar mais que 2%/s → max_rate=2; com Ts_mpc=5 s, o passo máximo por execução é 10%.",
  },
  duMin: {
    description:
      "Banda morta do atuador, na EU da MV (TD-007): movimentos pedidos menores que este valor não são aplicados — a válvula não responderia mesmo — e sem essa quantização o modelo interno do MPC divergiria do que foi de fato escrito na planta.",
    example: "válvula com folga mecânica de 0,5% de curso → du_min=0,5 evita micro-ajustes ignorados pelo atuador.",
  },
  moveWeight: {
    description:
      "Peso multiplicativo do custo de movimento desta MV no solve dinâmico — 1,0 mantém o comportamento padrão; valores maiores deixam esta MV mais 'preguiçosa' (o solver prefere mover outras MVs primeiro).",
    example:
      "move_weight=5 numa MV cara de operar (desgaste de atuador) faz o MPC preferir mexer nas outras MVs disponíveis antes dela.",
  },
  valorInicial: {
    description:
      "Valor desta MV usado como estado inicial do solver antes da primeira execução válida (coordenada absoluta da planta) — só importa no cold start; depois disso o solver parte do valor realmente aplicado.",
    example:
      "válvula que normalmente abre perto de 40% em regime — valor_inicial=40 evita um primeiro move-plan artificialmente longo.",
  },
  pontoOperacao: {
    description:
      "Valor desta MV no ponto em que a matriz de Modelos foi linearizada (TD-003) — o modelo interno recebe (MV − ponto_de_operação), não a MV bruta. Sem isso, uma linha integradora acumula erro e a predição deriva sozinha com o tempo. 0,0 reproduz o comportamento anterior a este campo.",
    example: "modelo identificado com a válvula em torno de 35% → ponto_de_operação=35.",
  },
  readbackTag: {
    description:
      "Tag de leitura com a posição REAL desta MV — usada só quando a MV é DIRETA (sem PID marcado): em LOCAL a saída acompanha essa tag (transferência bumpless pro REMOTO); em REMOTO ela é o valor efetivamente aplicado no solve. Com PID marcado, quem cumpre esse papel é o readback da seção PID, não este campo.",
    example: "readback da posição real da válvula via um transmissor de posição (LVDT) ligado a esta tag.",
  },
  objetivo: {
    description:
      "Direção econômica desta MV pro otimizador de regime permanente (SSTO), resolvido a cada execução do MPC. Ordem de dominância: Alvo (de CV) > Maximizar/Minimizar > PSV ≈ Nivelar > Observar limite (de CV). Pra MV: PSV ancora perto de um valor preferido (preferência fraca); Nivelar distribui igualmente entre 2+ MVs marcadas (grupo único). 'Nenhuma' (padrão) desliga a otimização pra esta MV.",
    example: "duas bombas em paralelo com objetivo Nivelar dividem a vazão igualmente em vez de uma carregar tudo.",
  },
  psv: {
    description:
      "Valor preferido desta MV quando o objetivo é PSV — precisa estar dentro dos limites mín./máx. da MV. É uma preferência FRACA no SSTO: cede a qualquer objetivo Maximizar/Minimizar de outra variável.",
    example: "manter uma válvula de bypass perto de 50% aberta como preferência, sem brigar com uma CV que precisa maximizar produção.",
  },
  comPid: {
    description:
      "Liga a amarração com um PID de campo/PLC pra esta MV (RF-604). Sem marcar, a MV é 'direta': o MPC escreve o valor calculado direto numa tag de escrita. Marcando, o MPC comanda o SP/saída de um controlador PID já existente no PLC em vez de abrir a válvula direto.",
    example: "MPC de nível que ajusta o SP de um PID de vazão já existente na malha do PLC, em vez de abrir a válvula diretamente.",
  },
  failAction: {
    description:
      "O que fazer quando esta MV fica indisponível em REMOTO (RF-613), com debounce de 2 execuções antes de agir. 'Sem ação' (padrão) mantém o comportamento anterior; 'Devolver ao local' tira só esta MV de REMOTO; 'Manual' força modo manual.",
    example: "atuador que perde comunicação com frequência → Devolver ao local evita o MPC tentar mover uma MV que não responde.",
  },
  localShedMode: {
    description:
      "Valor escrito na tag de comando de modo do PID sempre que esta MV volta ao controle local — por qualquer motivo (shed geral, ação de falha, comando REMOTO→LOCAL). Em branco usa o valor 'auto' já configurado na seção PID. Só faz sentido com PID marcado.",
    example: "mode_cmd=1 pra forçar o PID de campo a AUTO local sempre que este MPC devolve o controle.",
  },
} satisfies Record<string, TooltipContent>;

// Conceitos compartilhados por CV e Restrição — mesmo tipo no backend (`RowKind`/
// `RowFailAction`), uma entrada só reaproveitada nos dois lugares.
export const AJUDA_LINHA = {
  kind: {
    description:
      "Forma do modelo dinâmico desta linha na matriz de Modelos (RF-602). Autorregulável (SOPDT): resposta que se estabiliza sozinha num novo valor — parâmetros K/τ1/τ2/θ. Integrador (IOPDT): resposta que não para de variar sozinha — parâmetros Ki/θ. Trocar o kind troca a forma dos parâmetros da linha inteira na matriz.",
    example: "temperatura controlada por uma malha com dreno → Autorregulável; nível de um tanque de acúmulo sem escoamento livre → Integrador.",
  },
  prioridade: {
    description:
      "Posição desta linha na fila de desistência do otimizador de regime permanente (SSTO) — maior número = mais importante. Quando o LP fica inviável, a linha VIOLADA de menor prioridade é removida primeiro, e o LP roda de novo até sobrar só o que cabe (ADR-027 §6). O default 1 deixa todas as linhas no mesmo patamar.",
    example: "uma Restrição de segurança com prioridade 10 nunca cede espaço antes de uma CV de qualidade com prioridade 1.",
  },
  failAction: {
    description:
      "Ação quando esta linha (CV/Restrição) recebe entrada inválida por tempo prolongado (RF-613), avaliada só em REMOTO com debounce de 2 execuções. As opções 'Simular…' seguram o último valor previsto por até o Timeout de falha antes de aplicar a ação final.",
    example: "sensor intermitente → 'Simular e devolver ao local' segura a predição por um tempo antes de agir, em vez de reagir a uma falha de meio segundo.",
  },
  failTimeout: {
    description:
      "Quanto tempo (segundos) esta linha segura o último valor previsto sob falha, antes de aplicar a ação final — só relevante quando a Ação de falha é uma das opções 'Simular…'.",
    example: "fail_timeout_s=60 tolera até 1 minuto de sensor fora do ar antes de agir.",
  },
} satisfies Record<string, TooltipContent>;

// Aba Variáveis — lista de CVs (campos que não são compartilhados via AJUDA_LINHA/AJUDA_COMUM)
export const AJUDA_CV = {
  objetivo: {
    description:
      "Direção econômica desta CV pro otimizador de regime permanente (SSTO), resolvido a cada execução do MPC. Ordem de dominância: Alvo > Maximizar/Minimizar > PSV ≈ Nivelar (de MV) > Observar limite. Alvo ancora forte no SP; Maximizar/Minimizar empurram até um limite ou preço mais forte; Observar limite é a preferência mais fraca — só se move o necessário pra viabilizar restrições. 'Nenhuma' (padrão) desliga a otimização pra esta CV.",
    example: "CV de vazão de produto com Maximizar empurra a produção pra cima até uma Restrição de qualidade ou uma MV baterem no limite.",
  },
  peso: {
    description:
      "Peso (w) desta CV no custo dinâmico do solve — quanto maior, mais o MPC prioriza manter esta CV perto do seu SP em relação às demais CVs e ao custo de movimento das MVs. Distinto de Prioridade: peso afeta o controle DINÂMICO a cada execução; prioridade só entra no LP de regime permanente do SSTO.",
    example: "CV de qualidade de produto com peso 10 versus CV de nível com peso 1 — o MPC sacrifica nível antes de sacrificar qualidade.",
  },
  trajTau: {
    description:
      "Constante de tempo (τ, em segundos) da trajetória de referência exponencial usada pelo MPC pra ir do valor atual até o SP, em vez de mirar o SP em degrau (RF-611). 0 = comportamento padrão, sem suavização.",
    example: "traj_tau_s=30 numa CV sensível a mudanças bruscas suaviza a aproximação ao SP ao longo de ~30 s em vez de tentar chegar de uma vez.",
  },
  trackSp: {
    description:
      "Fora do modo AUTO, o SP desta CV acompanha o PV em tempo real (transferência bumpless) — marcado é o padrão. Desmarcar trava o SP no valor que o operador deixou, mesmo com o MPC fora de AUTO (RF-612).",
    example: "desmarcar quando o operador precisa preparar um SP novo enquanto o MPC ainda está em MAN, sem o SP 'fugir' atrás do PV.",
  },
  spMin: {
    description:
      "Limite inferior que o SP desta CV pode assumir — tanto o operador quanto o SP remoto (RF-614) são travados (clamp) nesta faixa.",
    example: "CV de nível com faixa física 0-100% mas SP travado entre 20-80% pra manter folga de segurança.",
  },
  spMax: {
    description:
      "Limite superior que o SP desta CV pode assumir — tanto o operador quanto o SP remoto (RF-614) são travados (clamp) nesta faixa.",
    example: "CV de nível com faixa física 0-100% mas SP travado entre 20-80% pra manter folga de segurança.",
  },
  spRangePct: {
    description:
      "Banda do SP usada pelo SSTO (RF-615), com significado diferente por kind da linha: numa CV Autorregulável, trava o alvo em SP ± pct/100 × Span (banda de nível). Numa Integradora, vira uma tolerância de TAXA (pct/100 × Span/TSS), porque uma linha integradora não tem nível de regime — só faz sentido controlar o quanto ela pode derivar por ciclo de assentamento. Em branco = sem banda específica desta linha.",
    example: "CV autorregulável com SP=50, span=100, sp_range_pct=10 → o SSTO trava o alvo entre 45 e 55.",
  },
  remoteSp: {
    description:
      "Tag OPC-UA de onde o SP desta CV é lido a cada varredura (RF-614), em vez do valor digitado pelo operador — sempre travado (clamp) na faixa de SP mín./máx. Vazio usa o SP local do operador.",
    example: "SP vindo de um otimizador externo ou de outra malha via uma tag calculada.",
  },
} satisfies Record<string, TooltipContent>;

// Aba Variáveis — lista de Restrições (campos que não são compartilhados via AJUDA_LINHA/AJUDA_COMUM)
export const AJUDA_RESTRICAO = {
  objetivo: {
    description:
      "Direção econômica desta Restrição pro otimizador de regime permanente (SSTO) — só Maximizar/Minimizar (sem âncora, ao contrário da CV, porque Restrição não tem SP): vira um preço linear puro no LP. 'Nenhuma' (padrão) desliga a otimização pra esta linha.",
    example: "Restrição de vazão de utilidade com objetivo Minimizar reduz consumo até esbarrar noutro limite mais forte.",
  },
  faixaMin: {
    description:
      "Limite inferior aceitável desta Restrição — folga soft na montagem (penalizada, nunca dura como o limite de uma MV); tem PRECEDÊNCIA sobre CVs quando os dois disputam a mesma MV (RF-601).",
    example: "Restrição de temperatura mínima de um vaso — o MPC sacrifica o SP de uma CV antes de violar esta faixa.",
  },
  faixaMax: {
    description:
      "Limite superior aceitável desta Restrição — folga soft na montagem (penalizada, nunca dura como o limite de uma MV); tem PRECEDÊNCIA sobre CVs quando os dois disputam a mesma MV (RF-601).",
    example: "Restrição de temperatura máxima de um vaso — o MPC sacrifica o SP de uma CV antes de violar esta faixa.",
  },
} satisfies Record<string, TooltipContent>;

// Aba Variáveis — lista de DVs
export const AJUDA_DV = {
  faixaMin: {
    description:
      "Faixa desta DV, opcional (spec RFC-16) — hoje é só documentação/contexto pro engenheiro; não alimenta mais a escala de nenhum faceplate (quem faz isso é Zero/Span). Deixar em branco não afeta o cálculo.",
    example: "faixa esperada de uma temperatura ambiente medida, só como referência visual.",
  },
  faixaMax: {
    description:
      "Faixa desta DV, opcional (spec RFC-16) — hoje é só documentação/contexto pro engenheiro; não alimenta mais a escala de nenhum faceplate (quem faz isso é Zero/Span). Deixar em branco não afeta o cálculo.",
    example: "faixa esperada de uma temperatura ambiente medida, só como referência visual.",
  },
  pontoOperacao: {
    description:
      "Valor desta DV no ponto em que a matriz de Modelos foi linearizada — o modelo interno recebe (DV − ponto_de_operação), mesma lógica do ponto de operação da MV. Permite ligar a medida crua da planta direto na porta da DV, sem um bloco Script somando constantes antes.",
    example: "DV de temperatura ambiente identificada em torno de 25°C → ponto_de_operação=25.",
  },
} satisfies Record<string, TooltipContent>;

// Seção PID de uma MV (CamposPid.tsx) — RF-604, spec F4 §2.1-3
export const AJUDA_PID = {
  writeTag: {
    description:
      "Tag de escrita (W) pela qual o MPC comanda este PID de campo/PLC quando em REMOTO — normalmente o SP (RCAS/CAS) ou a saída (ROUT) do controlador, conforme o Modo alvo configurado abaixo.",
    example: "tag de SP remoto do bloco PID_101 no PLC.",
  },
  readbackTag: {
    description:
      "Tag de leitura (R) com o valor real que o PID está aplicando — usada pra transferência bumpless na volta ao LOCAL (o MPC assume a partir daqui, sem salto).",
    example: "leitura do OUT ou do PV atual do PID_101.",
  },
  modeCmdTag: {
    description:
      "Tag de escrita (W) pela qual o MPC comanda o MODO do PID de campo: o Modo alvo (RCAS/CAS/ROUT) ao assumir REMOTO, e o Valor do modo — devolver ao voltar pro LOCAL.",
    example: "tag de comando de modo do bloco PID_101.",
  },
  modeReadTag: {
    description:
      "Tag de leitura (R) opcional com o modo atual do PID de campo — só pra exibição/diagnóstico; o MPC não decide nada a partir dela.",
    example: "leitura de confirmação de que o PID_101 de fato assumiu RCAS.",
  },
  targetMode: {
    description:
      "Modo que o MPC escreve no PID de campo ao assumir REMOTO (RF-622): RCAS/CAS mandam SP externo (o PID de campo segue o SP do MPC com seu próprio controle interno); ROUT manda saída externa (o MPC dita a saída direto). Depende de como o bloco PID do PLC foi configurado.",
    example: "PID de vazão de campo aceita SP remoto → RCAS; controlador só aceita saída manual remota → ROUT.",
  },
  modeAuto: {
    description:
      "Valor escrito na tag de comando de modo sempre que este MPC devolve o controle ao LOCAL — normalmente o código de modo AUTO do PID de campo.",
    example: "1 se o bloco PID do PLC usa 1=AUTO, 0=MAN.",
  },
  modeTarget: {
    description:
      "Valor escrito na tag de comando de modo quando este MPC assume o controle em REMOTO — o código correspondente ao Modo alvo escolhido acima (RCAS/CAS/ROUT) no PID de campo específico.",
    example: "3 se o bloco PID do PLC usa 3=RCAS.",
  },
} satisfies Record<string, TooltipContent>;

// Aba Modelos (TabModels.tsx) — parâmetros SOPDT/IOPDT por par + checkbox de habilitação
export const AJUDA_MODELOS: Record<string, TooltipContent> = {
  K: {
    description:
      "Ganho estático do par SOPDT, adimensional (%/%): quanto a linha varia, em % do seu Span, pra cada 1% de variação da coluna, em regime permanente. O motor converte pra EU multiplicando por Span_linha/Span_coluna na montagem (RF-602).",
    example: "K=2 significa que 10% de variação na MV vira 20% de variação na CV, na faixa de cada uma.",
  },
  tau1: {
    description: "Constante de tempo dominante do par SOPDT, em segundos — quanto maior, mais lenta a resposta até se estabilizar.",
    example: "τ1=120 s numa malha de temperatura de leito, tipicamente mais lenta que uma malha de vazão.",
  },
  tau2: {
    description:
      "Segunda constante de tempo do par SOPDT (resposta de 2ª ordem, com um leve S na curva) — 0 reduz o modelo a 1ª ordem pura.",
    example: "τ2=0 pra maioria das malhas simples; um valor > 0 só quando a curva de reação mostra um S visível antes de subir.",
  },
  theta: {
    description:
      "Tempo morto do par (atraso puro antes da resposta começar), em segundos — vira estados extras na montagem interna do modelo, então valores grandes em relação ao Ts_mpc custam mais dimensão de estado.",
    example: "θ=15 s pra uma malha com transporte de material entre o atuador e o sensor.",
  },
  Ki: {
    description:
      "Ganho do par IOPDT (linha integradora), adimensional: taxa de variação da linha, em %/s do seu Span, pra cada 1% de variação sustentada da coluna.",
    example: "Ki=0,05 numa CV de nível de tanque sem dreno, alimentado por uma MV de vazão de entrada.",
  },
  habilitado: {
    description:
      "Habilita este par linha×coluna na matriz de ganhos — sem marcar, esta CV/Restrição não reage a esta MV/DV nas predições do MPC, mesmo que a linha e a coluna existam.",
    example: "uma DV medida mas sem efeito conhecido sobre uma CV específica fica desabilitada só nesse par, sem tirar a DV das outras.",
  },
};

// Aba Horizontes (TabHorizons.tsx)
export const AJUDA_HORIZONTES = {
  tss: {
    description:
      "Tempo de assentamento (TSS) desta linha, em segundos — quanto tempo ela leva pra se estabilizar após uma perturbação. O maior TSS entre todas as CVs/Restrições define o horizonte de predição Np (RF-603).",
    example: "TSS=600 s (10 min) numa malha de temperatura lenta.",
  },
  np: {
    description:
      "Horizonte de predição, derivado: Np = arredondar_pra_cima(maior TSS / Ts_mpc) — quantos passos à frente o MPC prediz o comportamento das CVs/Restrições. Não editável; sobe com um TSS mais lento e desce com um Ts_mpc maior.",
    example: "maior TSS=600 s e Ts_mpc=10 s → Np=60.",
  },
  nc: {
    description:
      "Horizonte de controle, derivado: Nc = máx(2, arredondar_pra_cima(Np/4)) — quantos passos de movimento futuro o solver de fato otimiza (depois disso, assume MV constante até o fim do horizonte de predição).",
    example: "Np=60 → Nc=15.",
  },
} satisfies Record<string, TooltipContent>;
