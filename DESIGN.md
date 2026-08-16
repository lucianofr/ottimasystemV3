---
name: OttimaSystem
description: Console de operação APC — campo grafite, cor reservada a estado, predição como tinta que ainda não secou
---

<!-- SEED: established with the user before implementation; re-run $impeccable document once there's code to capture the actual tokens and components. -->

# Design System: OttimaSystem

> Documento normativo para SPECs e planos de codificação. Direção "Console OttimaSystem" aprovada pelo usuário em 2026-08-03 (seed key `e8f7c8d5`, modo Operate). Em conflito entre este documento e o PRD/ADRs sobre **comportamento**, o PRD/ADR prevalece; sobre **aparência**, este documento prevalece.

## Overview

**Creative North Star: "O Console OttimaSystem"**

O OttimaSystem se veste como aquilo que é: um console de operação de geração atual — o habitat visual que operadores e engenheiros de APC já conhecem dos postos de comando modernos — com identidade própria de produto, não clone de vendor de DCS. A personalidade é sóbria, precisa e densa-porém-calma: o cromo da interface recua em cinzas de baixo contraste, os **dados de processo são o protagonista** em alto contraste, e cor saturada é um evento raro que significa alguma coisa. Não é SaaS genérico, não é SCADA anos 90, não é dashboard IoT com brilho neon: é instrumento profissional que aguenta 24/7.

O campo é **grafite** — cinza escuro dessaturado, nunca preto — escolhido para a cena física real: salas de controle cuja luz varia de penumbra a escritório claro. Telas se compõem como **chapas de painel** (zonas tonais planas com linhas de 1px), numa hierarquia de console: visão geral → flow/canvas → tela de operação → detalhe. Não há fotografia nem ilustração; **o dado de processo é a imagem**. A movimentação é de instrumento: transições de valor, barras e lâmpadas de estado com easing curto e funcional — nunca animação decorativa; `prefers-reduced-motion` respeitado.

A assinatura reutilizável do sistema é a **"tinta que ainda não secou"**: em toda tendência, o histórico é traço sólido, uma linha-cursor marca "agora", e a predição do MPC continua no mesmo matiz, mais clara e tracejada, desvanecendo rumo ao horizonte — CVs como trajetória contínua, plano de MVs como degraus fantasma. Segunda assinatura: **plaquetas** — todo rótulo de equipamento/tag/variável usa a mesma gravação (caps, condensado, espaçado), como plaqueta de instrumento.

**Key Characteristics:**
- Campo grafite único (sem tema claro/escuro alternável na v1); dados claros sobre fundo escuro-médio
- Cor reservada a estado (filosofia ISA-101): vermelho alarme, âmbar advertência; um único azul industrial para interação
- Chapas tonais planas + linhas 1px; zero sombra decorativa
- Tipografia de plaqueta (Archivo/Archivo Narrow) + mono tabular para todo valor de processo (Spline Sans Mono)
- Predição como tinta-que-não-secou em toda tendência
- Faceplates com barras verticais PV/SP/OUT (convenção intocável, confirmada pelo usuário)
- UI 100% pt-BR; nomenclatura do GLOSSARY.md; sem emojis

**Anti-referências confirmadas:** dashboard "IoT industrial" escuro com gauges neon; admin shadcn/SaaS claro genérico; SCADA legado (cinza Windows, ícones 3D); texturas esqueumórficas retrô (metal escovado, LEDs falsos).

## Colors

Estratégia **Restrained**: neutros grafite + um acento de interação; cores de severidade são funcionais, não paleta. Valores exatos `[a resolver na implementação]` dentro das faixas abaixo; o re-scan pós-código carboniza os tokens.

### Primary
- **Azul Industrial** (`[a resolver]`; alvo OKLCH ≈ L 62–70%, C 0.08–0.12, H 230–250): seleção, foco, links, botão primário, item ativo de navegação. Dessaturado e calibrado — jamais neon/ciano brilhante. É a única cor de interação do sistema — **nunca** desenha dado, nem a pena de SP em trends (A Regra do Azul Único, abaixo).

### Neutral
- **Grafite Campo** (alvo L 22–28%, C ≤ 0.015): fundo geral da aplicação.
- **Chapa** (1–2 passos mais clara que o campo): superfícies de painel, cards, formulários, faceplates.
- **Poço** (1–2 passos mais escura que o campo): áreas rebaixadas — fundo de trend, canvas, wells de entrada.
- **Linha** (contraste baixo sobre chapa): bordas 1px, divisores, grades de tabela e de trend.
- **Texto Primário** (contraste ≥ 7:1 sobre chapa): valores e conteúdo.
- **Texto Secundário** (contraste ≥ 4.5:1): rótulos, EU, metadados.

### Severity (funcional; fora dela estas cores são proibidas)
- **Vermelho Alarme**: alarme ativo, falha (watchdog, conexão caída, solver), flow em falha, ações destrutivas.
- **Âmbar Advertência**: advertência, overrun, qualidade degradada, estados pendentes de atenção.
- **Verde Rodando** (apagado/mutado): exclusivamente lâmpada de estado "rodando/vivo" (flow em execução, heartbeat, watchdog OK) — em componente lâmpada, nunca em áreas grandes nem texto.
- **Qualidade ruim (OPC)**: não é cor — valor dessaturado + ícone/hachura + rótulo (ex.: `BAD`), para nunca depender só de cor.

**A Regra da Cor Anormal.** Em qualquer tela em operação normal, a superfície é grafite e neutros; cor saturada aparece somente quando algo exige atenção (severidade) ou o usuário interage (azul único). Se uma tela parada "colorida" surgir num mockup, o mockup está errado.

**A Regra do Azul Único.** Existe um azul. Ele nunca codifica dado, severidade ou categoria — apenas interação/seleção. Penas de trend têm paleta própria de série (dessaturada, distinguível, `[a resolver]`) que não colide com severidade nem com o azul de interação.

**A Regra do Canal Redundante.** Severidade nunca é comunicada só por cor: sempre cor + ícone/forma + texto (daltonismo e leitura à distância).

## Typography

**Display/UI Font:** Archivo (fallback: system-ui, sans-serif)
**Dense Label Font:** Archivo Narrow (rótulos densos, plaquetas)
**Data/Mono Font:** Spline Sans Mono (fallback: ui-monospace) — `font-variant-numeric: tabular-nums` obrigatório

**Character:** Voz de plaqueta de instrumento e datasheet de engenharia — grotesca neutra, precisa, sem afetação editorial. O mono é sóbrio e de UI, não "tela de editor de código".

### Hierarchy
Tamanhos exatos `[a resolver na implementação]`; papéis e regras são normativos:

- **Display** (Archivo SemiBold): raro — login, títulos de página de primeiro nível.
- **Headline** (Archivo Medium): título de tela/seção.
- **Title** (Archivo Medium, menor): cabeçalho de chapa/faceplate/modal.
- **Body** (Archivo Regular): texto corrente, formulários, tabelas.
- **Label/Plaqueta** (Archivo Narrow Medium, caps, tracking +4–8%): tags, nomes de equipamento, rótulos de porta de bloco, cabeçalhos de coluna.
- **Valor de Processo** (Spline Sans Mono): todo número de processo, node_id, timestamp. Nos faceplates, o PV é o maior elemento tipográfico da chapa — dimensionado para leitura a 1–3 m.

**A Regra da Plaqueta.** Todo rótulo de tag/equipamento/variável no sistema inteiro usa o mesmo tratamento de plaqueta (caps + Narrow + tracking). Um rótulo fora do padrão é defeito.

**A Regra do Número Tabular.** Valores de processo sempre em mono tabular, alinhados pelo decimal, com EU visível ao lado (menor, Texto Secundário). Número sem unidade de engenharia é defeito.

## Layout

Hierarquia de console em quatro níveis: **visão geral do projeto ativo** (flows, conexões, alarmes) → **canvas do flow** → **tela de operação por MPC** → **modais de detalhe/config**. Uma **faixa anunciadora** persistente no topo de toda tela em sessão: banner de alarmes ativos (herança do painel anunciador; sem ACK, conforme ADR-020), colapsada a uma linha discreta quando não há condição ativa.

Telas se compõem de chapas sobre o campo, alinhadas a um grid de base 4px (escala de espaçamento exata `[a resolver]`); densidade alta com ritmo: chapas densas (tabelas, matrizes de modelo) alternam com respiros — mais espaço acima de um cabeçalho do que abaixo.

**Tela de operação** (composição fixada por convenção do usuário + ADR-016): faceplate principal do MPC no topo (modos LOCAL/REMOTO e MAN/AUTO como comutadores de posição, lâmpadas de watchdog/solver/overrun), **tendência dominante no centro**, fileira de faceplates de variável na base — cada um com barra vertical PV/SP/OUT, EU e limites.

**Alvo responsivo:** desktop-first. Otimizar para 1920×1080; funcional a partir de 1366px. Sem compromisso mobile na v1 (não-objetivo do PRD); nada pode *quebrar* em janelas menores, mas não há layout dedicado.

**A Regra do Estado Publicado (visual).** Controles de operação distinguem visualmente *comandado* de *confirmado*: ao comandar, o controle entra em estado pendente (outline azul, valor comandado em fantasma) até o estado publicado pelo barramento confirmar — a UI nunca finge que o comando já valeu (RNF-05).

## Elevation & Depth

Sistema **plano com camadas tonais**; profundidade é degrau de luminosidade + linha de 1px, nunca blur ou sombra decorativa. Três alturas: Poço (rebaixado), Campo, Chapa (elevado). Única exceção: modais/popovers podem usar um scrim escurecedor e uma sombra funcional discreta `[a resolver]` para separação do plano — nada além disso.

**A Regra da Chapa.** Se dois elementos precisam se separar, muda-se o tom ou traça-se uma linha; sombra não é vocabulário deste sistema.

## Shapes

Linguagem de bisel de instrumento: cantos **2–4px** em tudo (chapas, botões, inputs, nós do canvas); nunca pills, nunca cantos ≥ 8px. Bordas hairline 1px. Formas recorrentes:

- **Barra vertical de instrumento**: PV/SP/OUT como colunas com escala, ponteiros/marcadores lineares — o DNA dos faceplates.
- **Comutador de posição**: modos (LOCAL/REMOTO, MAN/AUTO) como segmented control de posições nítidas com rótulo — estados são posições físicas, não toggles suaves.
- **Lâmpada de estado**: quadrado pequeno com ícone + rótulo (nunca só cor) para watchdog, heartbeat, rodando/parado/falha.
- **Nós do canvas**: blocos React Flow totalmente re-vestidos como equipamentos de painel — chapa, plaqueta de título, portas tipadas com rótulo; o visual default do React Flow é proibido.

## Do's and Don'ts

### Do:
- **Do** reservar cor a estado e interação; superfície em operação normal é neutra (A Regra da Cor Anormal).
- **Do** usar mono tabular + EU em todo valor de processo (A Regra do Número Tabular).
- **Do** manter barras verticais PV/SP/OUT em todo faceplate de variável — convenção intocável.
- **Do** desenhar toda tendência com a assinatura: histórico sólido → linha-agora → predição tracejada no mesmo matiz mais claro, desvanecendo ao horizonte; plano de MVs como degraus fantasma.
- **Do** distinguir comandado × confirmado em todo controle de operação (A Regra do Estado Publicado).
- **Do** tematizar shadcn/ui via CSS variables com estes tokens; re-vestir completamente React Flow e uPlot (paleta de penas própria, grade em Linha, fundo Poço).
- **Do** escrever toda a UI em pt-BR com a nomenclatura exata do GLOSSARY.md (SP, MV, CV, RCAS, bumpless — não traduzir termos consagrados).
- **Do** garantir contraste ≥ 7:1 para valores de processo e ≥ 4.5:1 para texto secundário sobre chapa.

### Don't:
- **Don't** usar neon, glow, gradientes decorativos ou glassmorphism — o rut IoT que este mundo existe para recusar.
- **Don't** usar sombras como decoração; profundidade é tonal (A Regra da Chapa).
- **Don't** usar vermelho/âmbar fora de severidade, nem verde fora da lâmpada "rodando/vivo"; nunca cor como único canal de severidade.
- **Don't** deixar componente com cara default (shadcn cinza-claro, nó React Flow padrão, cores de série default do uPlot) — tudo veste o mundo.
- **Don't** usar pills, cantos grandes, toggles "amigáveis" iOS-like em comandos de operação — modos são comutadores de posição.
- **Don't** usar emojis, fotografia ou ilustração; o dado de processo é a imagem.
- **Don't** introduzir segundo acento, tema claro alternável ou dialeto visual por tela — um mundo, todas as superfícies.
