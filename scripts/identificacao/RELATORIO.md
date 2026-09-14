# Identificação de processo — FV-201 e FV-202 × LT-201 / Refluxo / FT-204

**Planta:** flow 987 "Controle MPC coluna de naftaleno", bloco `mpc_f376ff5d`, Ts = 2 s.
**Data:** 13/09/2026 (horários em BRT; o dado bruto guarda UTC).
**Condição:** MPC em REMOTO/MAN durante os degraus (malha aberta real), REMOTO/AUTO antes e
depois. Nenhum outro bloco foi alterado.

---

## 1. Resumo

Seis pares MV→CV identificados a partir de dois testes de degrau (+10 %, −20 %, +10 %), um
por MV, com a outra MV congelada. Todos na forma que o bloco MPC aceita (SOPDT para linha
autorregulável, IFOPDT para integradora), em unidades de config, prontos para a matriz
`models`.

| # | Par | Estrutura | Parâmetros (unidade de config do MPC) | Ganho em EU | R² | RMS |
|---|-----|-----------|----------------------------------------|-------------|----|-----|
| 1 | FV-201 → LT-201  | IFOPDT | `Ki=+0,004547`  `tau1=104,8 s`  `theta=23 s` | +0,004547 %/(%·s) | 0,9917 | 0,210 % |
| 2 | FV-201 → Refluxo | FOPDT  | `K=−1,8642`  `tau1=0,03 s`  `tau2=0`  `theta=4,68 s` | −1,864 %/% | 0,9400 | 3,830 % |
| 3 | FV-201 → FT-204  | SOPDT  | `K=+0,043667`  `tau1=9,07 s`  `tau2=7,58 s`  `theta=0 s` | +0,008733 m³/h/% | 0,9737 | 0,0111 m³/h |
| 4 | FV-202 → LT-201  | IFOPDT | `Ki=−0,002704`  `tau1=24,6 s`  `theta=23 s` | −0,002704 %/(%·s) | 0,9979 | 0,219 % |
| 5 | FV-202 → Refluxo | FOPDT  | `K=−1,9906`  `tau1=2,57 s`  `tau2=0`  `theta=4,73 s` | −1,991 %/% | 0,9989 | 0,545 % |
| 6 | FV-202 → FT-204  | FOPDT  | `K=+1,0299`  `tau1=17,58 s`  `tau2=0`  `theta=4,51 s` | +0,205985 m³/h/% | 0,9899 | 0,157 m³/h |

`td` dos pares com LT-201 **fixado em 23 s** (valor informado; único parâmetro não ajustado).
Nos demais o atraso foi identificado e caiu em 4,5–4,7 s, exceto o Modelo 3, que colou no
limite inferior (ver §6.3).

**Unidades.** `K` e `Ki` do config são normalizados por span (`mpc_config.py:353-361`:
`K_EU = K × span_CV/span_MV`). Só o FT-204 tem span ≠ 100 (20 m³/h), então ali
`K_config = 5 × K_EU`; nas demais linhas os dois números coincidem. A coluna "Ganho em EU" é
a que aparece nos gráficos.

Incerteza (1σ da covariância do ajuste; otimista, porque o resíduo é autocorrelacionado):

| # | σ(ganho) | σ(tau1) | σ(theta) |
|---|----------|---------|----------|
| 1 | ±0,000097 %/(%·s) (2,1 %) | ±2,8 s | fixo |
| 2 | ±0,0289 %/% | ≈0 (τ no limite) | ±0,17 s |
| 3 | ±0,000097 m³/h/% | ±13,2 s (polos não separáveis) | ±1,70 s (no limite) |
| 4 | ±0,000025 %/(%·s) (0,9 %) | ±0,95 s | fixo |
| 5 | ±0,0042 %/% | ±0,09 s | ±0,06 s |
| 6 | ±0,0014 m³/h/% | ±0,60 s | ±0,40 s |

**Achados que mudam decisão:**

1. O par **LT-201 ← FV-201 hoje configurado no MPC tem metade do ganho real** (0,002191 vs
   0,004547) — §8.
2. O **refluxo não é uma variável de processo, é uma razão de vazões**, e por isso não
   lineariza na direção da FV-201. Modelando as duas vazões e reconstruindo a razão, o erro
   cai de 3,83 % para 0,47 % — §7.
3. Validação **fora-da-amostra** (MPC em AUTO, as duas MVs se movendo, zero parâmetro livre):
   FT-204 com R² = 0,986; LT-201 com RMS de 0,27 % quando se reajusta apenas a constante de
   desbalanço — que é exatamente o que a atualização de bias do MPC faz a cada ciclo — §9.

---

## 2. Procedimento executado

Cada degrau foi comandado por `POST /api/operate/{flow}/{bloco}/mv` (MCP `mpc_write_mv`) e
**confirmado por evento `mpc_mv_written`**, nunca pelo valor publicado.

**O degrau é degrau, não rampa.** Em REMOTO+MAN a porta da MV devolve o valor manual
clampado direto (`blocks/mpc.py:813-814`); `max_rate`/`du_max` só existem na restrição do
solve em AUTO (`mpc/builder.py:390`). Confirmado no dado: as seis transições acontecem em
**uma única varredura**, sem nenhuma amostra intermediária.

| Comando | de → para | Δ em 1 varredura |
|---|---|---|
| T1 degrau 1 | 58,639 → 68,640 | 10,00 % |
| T1 degrau 2 | 68,640 → 48,640 | 20,00 % |
| T1 degrau 3 | 48,640 → 58,640 | 10,00 % |
| T2 degrau 1 | 42,860 → 52,860 | 10,00 % |
| T2 degrau 2 | 52,860 → 32,860 | 20,00 % |
| T2 degrau 3 | 32,860 → 42,860 | 10,00 % |

### Teste 1 — FV-201 (FV-202 congelada em 40,24 %)

| Evento | UTC | Local | MV |
|---|---|---|---|
| REMOTO/AUTO → MAN | 19:26:38 | 16:26:38 | FV-201 = 58,64 % |
| Degrau +10 % | 19:28:10 | 16:28:10 | 58,64 → 68,64 |
| Degrau −20 % | 19:31:10 | 16:31:10 | 68,64 → 48,64 |
| Degrau +10 % | 19:34:10 | 16:34:10 | 48,64 → 58,64 |
| MAN → AUTO | 19:37:10 | 16:37:10 | — |

### Teste 2 — FV-202 (FV-201 congelada em 54,30 %)

Entre os testes o MPC ficou em AUTO até LT-201 voltar a |erro| < 0,6 % e o refluxo a
|erro| < 1,2 % por 4 leituras consecutivas (estabilizou às 16:42).

| Evento | UTC | Local | MV |
|---|---|---|---|
| REMOTO/AUTO → MAN | 19:42:12 | 16:42:12 | FV-202 = 42,86 % |
| Degrau +10 % | 19:43:44 | 16:43:44 | 42,86 → 52,86 |
| Degrau −20 % | 19:46:44 | 16:46:44 | 52,86 → 32,86 |
| Degrau +10 % | 19:49:44 | 16:49:44 | 32,86 → 42,86 |
| MAN → AUTO | 19:52:44 | 16:52:44 | — |

**Patamar de 180 s bastou para as autorreguladas** — prova no dado, não no relógio: as
vazões voltam ao valor de partida no 4º patamar com 3 casas
(FT-202 5,936 → 5,939; FT-203 4,142 → 4,149; FT-204 1,796 → 1,796 m³/h), e o resíduo dos
Modelos 2/3/5/6 é plano nos últimos 60 s de cada patamar. **Não bastou para LT-201**, que é
integradora e tem τ de 25–105 s (§6.1).

**Faixa de nível durante os testes:** 48,7–55,7 % no teste 1 e 33,9–49,1 % no teste 2 —
sempre longe de 0/100 %, sem saturação. FT-204 também não saturou: o mínimo medido foi
0,615 m³/h no patamar −20 % do teste 2, com ruído de σ = 0,005 m³/h no patamar (vazão baixa,
porém viva e linear).

Estado final verificado: REMOTO/AUTO, LT-201 = 49,6 % (SP 50), Refluxo = 71,1 % (SP 70).
Watchdog vivo o tempo todo, nenhum alarme de comunicação.

---

## 3. Dados

**CSVs dos ensaios completos** (entrada em MAN → degraus → retorno a AUTO; coluna `degrau`
vale −1 fora do ensaio, 0 na linha de base e 1..3 nos degraus):

| Arquivo | Janela | Linhas |
|---|---|---|
| `out/teste1_FV-201_completo_2026-09-13.csv` | 16:26:20 → 16:37:28 | 340 |
| `out/teste2_FV-202_completo_2026-09-13.csv` | 16:41:50 → 16:52:58 | 340 |

**CSVs das janelas de identificação** (as pedidas, 16:27–16:36 e 16:43–16:52):

| Arquivo | Linhas |
|---|---|
| `out/teste1_FV-201_2026-09-13_1627-1636.csv` | 273 |
| `out/teste2_FV-202_2026-09-13_1643-1652.csv` | 273 |

Colunas: `ts_utc, ts_local, t_s, degrau, modo_auto, FV-201_pct, FV-202_pct, LT-201_pct,
LT-201_SP_pct, Refluxo_pct, Refluxo_SP_pct, FT-204_m3h, FT-202_m3h, FT-203_m3h`.

Origem: `mpc_samples` (uma amostra por varredura, publicada pelo próprio bloco) para
MV/CV/Restrição/SP/modo; `samples` (tags OPC cruas) para FT-202/FT-203, casadas por vizinho
mais próximo. Toda coleta verifica `mode == "raw"` na resposta da API — acima de 2 h de
janela o endpoint entrega médias de 1 min, que apagariam o `td` de 23 s; as janelas usadas
têm 9–11 min.

**A grade tem 5 amostras fora da fronteira de varredura por ensaio** — nem uma a mais: além
da publicação de fim de varredura, o runtime publica no instante do comando
(`blocks/mpc.py:1100`), e são exatamente 3 comandos de MV + 2 trocas de modo. O ensaio 1 tem
340 amostras para 335 esperadas em 668,000 s de janela; o ensaio 2, 340 para 335 em
668,001 s. É ótimo para cravar o `t0` do degrau e inofensivo para o resto, porque todo
ajuste reamostra em grade fixa de 2 s antes de simular.

---

## 4. Método

1. Reamostragem em grade fixa de Ts = 2 s.
2. Variável em desvio: `u − u₀`, `u₀` = média das 5 primeiras amostras.
3. **O modelo é simulado com o sinal de MV medido**, não com um degrau ideal, e **a campanha
   inteira é simulada de uma única condição inicial** — sem reancorar a cada patamar. Para o
   integrador isso é essencial: reancorar esconderia viés de `Ki` no reset.
4. Discretização exata (ZOH) por polo; atraso fracionário por interpolação linear.
5. Ajuste por mínimos quadrados não-lineares com limites (`scipy.optimize.least_squares`).
   Autorregulável: FOPDT e depois SOPDT partindo do FOPDT (partida quente evita mínimo
   local), fica o de maior R². Integradora: IFOPDT `Ki·e^(−θs)/(s(τ₁s+1))` com `θ = 23 s`
   fixo **mais um termo de deriva constante**.
6. Métricas sobre a janela inteira.

### A deriva, e por que ela não vai no par exportado

O termo de deriva é o desbalanço do vaso no ponto de operação congelado — nível subindo ou
descendo com as MVs paradas. Sem ele o ajuste distorce `Ki` para explicar uma rampa que não
veio do degrau.

| Campanha | deriva | ao longo da janela | excursão medida do nível |
|---|---|---|---|
| 1 (FV-201) | +0,00315 %/s (+0,19 %/min) | +1,7 % | 7,0 % |
| 2 (FV-202) | −0,02881 %/s (−1,73 %/min) | −15,5 % | 15,2 % |

No teste 2 a deriva domina: as MVs foram congeladas em (54,30 / 42,86), longe do balanço de
massa, e o nível caiu de 48,6 % para 34 % sozinho. **Isso está nos gráficos e NÃO está no
par exportado** (`params_mpc` devolve só `{Ki, tau1, theta}`) — é viés de ponto de operação,
exatamente o que a atualização de bias do MPC corrige a cada ciclo. O número aparece na caixa
dos Modelos 1 e 4 para não haver dúvida sobre o que o R² está validando. A §9 mostra que,
reajustando só essa constante, o modelo prevê fora-da-amostra com RMS de 0,27 %.

As duas campanhas são consistentes entre si: escrevendo `dLT/dt = Ki₁·u₁ + Ki₂·u₂ + c`, a
constante absoluta sai **c = −0,1547 %/s** pela campanha 1 e **−0,1598 %/s** pela campanha 2
— 3 % de diferença, com as MVs em pontos completamente distintos.

Reprodução:

```bash
uv run python scripts/identificacao/coleta.py --start 2026-09-13T19:27:00Z \
    --end 2026-09-13T19:36:00Z --out scripts/identificacao/out/fv201_1627_1636.csv \
    --tags 1480,1481,1482,1487
uv run python scripts/identificacao/exporta_csv.py \
    --csv scripts/identificacao/out/teste1_full.csv --mv mv_chns \
    --out scripts/identificacao/out/teste1_FV-201_completo_2026-09-13.csv
uv run python scripts/identificacao/identifica.py \
    --csv scripts/identificacao/out/fv201_1627_1636.csv \
    --marcas scripts/identificacao/out/marcas_fv201.json --mv mv_chns --n0 1
uv run python scripts/identificacao/valida.py      # vazões, refluxo reconstruído, MIMO
```

---

## 5. Medido × previsto

MV (topo), CV medida × modelo (meio, com parâmetros/R²/RMS), resíduo `medido − modelo`
(base). Linhas pontilhadas = instantes dos comandos.

### Modelo 1 — FV-201 → LT-201
![Modelo 1](out/modelo1_FV-201_LT-201.png)

### Modelo 2 — FV-201 → Refluxo
![Modelo 2](out/modelo2_FV-201_Refluxo.png)

### Modelo 3 — FV-201 → FT-204
![Modelo 3](out/modelo3_FV-201_FT-204.png)

### Modelo 4 — FV-202 → LT-201
![Modelo 4](out/modelo4_FV-202_LT-201.png)

### Modelo 5 — FV-202 → Refluxo
![Modelo 5](out/modelo5_FV-202_Refluxo.png)

### Modelo 6 — FV-202 → FT-204
![Modelo 6](out/modelo6_FV-202_FT-204.png)

---

## 6. Leitura modelo a modelo

### 6.1 Modelos 1 e 4 — o mesmo nível com dois τ diferentes

`τ₁ = 104,8 s` pela FV-201 e `24,6 s` pela FV-202, para o MESMO estado integrador. Não é erro
de ajuste: é caminho físico diferente. A FV-202 mexe direto na vazão de produto (FT-204, que
sai do vaso), enquanto a FV-201 mexe na vazão total (FT-202), e essa chega ao vaso com um lag
bem maior.

Os dois `τ` são identificáveis, mas o da FV-201 é frouxo. Perfil de RMS com `τ₁` travado
(reajustando `Ki` e a deriva a cada ponto):

| τ₁ travado | 10 s | 25 s | 50 s | 78 s | **105 s** | 150 s | 250 s |
|---|---|---|---|---|---|---|---|
| Modelo 1 — Ki | 0,00209 | 0,00239 | 0,00296 | 0,00373 | **0,00455** | 0,00605 | 0,00953 |
| Modelo 1 — RMS [%] | 0,800 | 0,622 | 0,395 | 0,252 | **0,210** | 0,272 | 0,473 |
| Modelo 4 — Ki | −0,00258 | **−0,00271** | −0,00302 | −0,00348 | −0,00401 | −0,00500 | −0,00735 |
| Modelo 4 — RMS [%] | 0,316 | **0,219** | 0,365 | 0,540 | 0,660 | 0,795 | 0,969 |

O mínimo existe e é claro nos dois (o RMS dobra a 50 s ou 250 s no Modelo 1), mas **`Ki` e
`τ₁` trocam entre si**: o `Ki` varia 4,5× ao longo da tabela. Publicar `Ki` sem o `τ₁` que o
acompanha é errado.

**A incerteza real do `Ki` é a do perfil, não os ±2,1 % da covariância.** Critério: aceitar
como equivalentes os ajustes com RMS até +30 % do ótimo, com a banda varrida por ajustes
reais (não por interpolação da tabela acima) — Modelo 1 `RMS ≤ 0,273 %`, Modelo 4
`RMS ≤ 0,285 %`:

| | τ₁ aceito | Ki na banda | fora da banda |
|---|---|---|---|
| Modelo 1 | **78 – 150 s** (τ=70 dá 0,282; τ=160 dá 0,293) | +0,003726 a +0,006045 | **−18 % / +33 %** |
| Modelo 4 | **15 – 38 s** (τ=12 dá 0,293; τ=40 dá 0,291) | −0,002618 a −0,002854 | **−3 % / +6 %** |

Ou seja, o `Ki` do Modelo 4 está determinado em ±5 %; o do Modelo 1, não melhor que ±25 %.
Só o par da FV-201 merece um ensaio dedicado com patamar de 8–10 min (§11).

**Estrutura conferida.** Ajustando o nível como autorregulável lento (SOPDT de τ livre até
5000 s) em vez de integrador: Modelo 1 vai para τ₁ = 5000 s (o limite — ou seja, degenera em
integrador) com RMS idêntico (0,211 vs 0,210); Modelo 4 piora de 0,219 para 1,917. Nenhum
indício de autorregulação; IFOPDT é a estrutura certa.

**Sobre os ganhos incrementais da §7 serem menores que o `Ki` ajustado:** não é
inconsistência. Num IFOPDT, a inclinação média na janela de 120–180 s após o degrau vale
`Ki·Δu·[1 − (τ/60)(e^(−120/τ) − e^(−180/τ))]`; com τ = 104,8 s o fator é 0,757, e
0,004547 × 0,757 = 0,00344 — praticamente o primeiro incremental medido (0,003526). Quem
subestima é a medida de inclinação num patamar curto para o τ, não o ajuste.

### 6.2 Modelos 2 e 5 — refluxo

O Modelo 5 (FV-202) é quase perfeito: R² = 0,9989, resíduo só nos três transitórios (picos de
−3 %, dois ciclos de largura, quantização do atraso contra a grade de 2 s).

O Modelo 2 (FV-201) é o único ajuste ruim da bateria, e **por não-linearidade estrutural**: a
dinâmica está certa (τ ≈ 0, θ = 4,7 s, resíduo plano dentro de cada patamar), o que sobra é
offset por patamar (+5,4 / −2,7 / −3,0 %). Causa e solução em §7.

### 6.3 Modelos 3 e 6 — FT-204

O Modelo 6 é canal forte (0,206 m³/h por %) e bem ajustado (R² = 0,99), com resíduo em
patamar de ±0,12 m³/h — resquício de não-linearidade de ganho (§7).

O Modelo 3 é o **elo fraco do conjunto** e deve ser tratado como estimativa de baixa
confiança:

- Ganho 24× menor que o do caminho pela FV-202 (0,0087 contra 0,206 m³/h/%): 10 % de FV-201
  movem a vazão de produto em 0,09 m³/h.
- Relação sinal/ruído boa o suficiente para o GANHO (σ do patamar = 0,006–0,009 m³/h contra
  degrau de 0,09), mas não para a dinâmica: `τ₁` e `τ₂` (9,1 e 7,6 s) têm σ = ±13 s, ou seja,
  não são separáveis — leia como "dois polos somando ≈ 17 s".
- `θ = 0` **colou no limite inferior** do ajuste: o otimizador queria atraso negativo, sinal
  de que o modelo está compensando outra coisa (provável acoplamento pelo nível) em vez de
  descrever transporte. Sigma de parâmetro na borda não tem significado.

---

## 7. Linearidade

Ganho incremental de cada degrau, direto do dado (média dos 30 s finais de cada patamar; para
o nível, diferença de inclinação dos 60 s finais — com o viés explicado em §6.1):

### Teste 1 — FV-201

| Transição | ΔMV | LT-201 [%/(%·s)] | Refluxo [%/%] | FT-204 [m³/h/%] |
|---|---|---|---|---|
| 58,64 → 68,64 | +10 | +0,003526 | **−2,659** | +0,006740 |
| 68,64 → 48,64 | −20 | +0,002753 | **−1,857** | +0,008661 |
| 48,64 → 58,64 | +10 | +0,001035 | **−1,040** | +0,010810 |

### Teste 2 — FV-202

| Transição | ΔMV | LT-201 [%/(%·s)] | Refluxo [%/%] | FT-204 [m³/h/%] |
|---|---|---|---|---|
| 42,86 → 52,86 | +10 | −0,003752 | −1,953 | +0,239833 |
| 52,86 → 32,86 | −20 | −0,002935 | −1,992 | +0,202883 |
| 32,86 → 42,86 | +10 | −0,001964 | −2,035 | +0,165308 |

Refluxo × FV-202 é linear (dispersão de 4 %); refluxo × FV-201 varia **2,6×** dentro de
±10 % da MV; FT-204 × FV-202 varia ±20 %.

### Por que o refluxo × FV-201 não lineariza

Vazões cruas por patamar (média dos 60 s finais):

| Teste | MV | FT-202 [m³/h] | FT-203 [m³/h] | FT-204 [m³/h] | Refluxo |
|---|---|---|---|---|---|
| 1 | FV-201 = 58,64 | 5,936 | 4,142 | 1,796 | 69,79 % |
| 1 | FV-201 = 68,64 | 3,281 | 1,414 | 1,864 | 43,08 % |
| 1 | FV-201 = 48,64 | 8,495 | 6,807 | 1,689 | 80,12 % |
| 1 | FV-201 = 58,64 | 5,939 | 4,149 | 1,796 | 69,85 % |
| 2 | FV-202 = 42,86 | 7,513 | 5,238 | 2,280 | 69,72 % |
| 2 | FV-202 = 52,86 | 9,364 | 4,684 | 4,682 | 50,02 % |
| 2 | FV-202 = 32,86 | 6,148 | 5,526 | 0,624 | 89,88 % |

Vale `FT-202 = FT-203 + FT-204` em todos os patamares (erro < 0,5 %), logo
`Refluxo = 100·(1 − FT-204/FT-202)`.

**As vazões são lineares; a razão é que não é.** Ganhos incrementais de FV-201:
FT-202 → −0,2655 / −0,2607 / −0,2556 (dispersão 4 %); FT-203 → −0,2728 / −0,2697 / −0,2658
(dispersão 3 %). Só o quociente espalha 2,6×, porque FV-201 muda FT-202 em −45 % e o refluxo
depende de `1/FT-202`. Derivando no ponto de operação:
`dR/du = 100·FT-204·(dFT-202/du)/FT-202² ≈ −1,48 %/%`, contra −1,86 %/% da secante de ±10 % —
é a curvatura, não ruído.

### Refluxo reconstruído das vazões

Identificando FV→FT-202 e FV→FT-203 (FOPDT, EU) e montando a razão:

| Par | K [m³/h/%] | τ₁ [s] | θ [s] | R² | RMS [m³/h] |
|---|---|---|---|---|---|
| FV-201 → FT-202 | −0,26059 | 2,53 | 4,96 | 0,9997 | 0,036 |
| FV-201 → FT-203 | −0,26971 | 1,65 | 4,85 | 0,9998 | 0,035 |
| FV-202 → FT-202 | +0,16150 | 2,89 | 4,71 | 0,9916 | 0,120 |
| FV-202 → FT-203 | −0,04185 | 2,20 | 4,47 | 0,9701 | 0,059 |

Refluxo previsto pela razão dessas duas vazões, contra o modelo linear direto (mesmo direito
a um bias constante para os dois):

| Campanha | Linear direto | Reconstruído FT-203/FT-202 |
|---|---|---|
| FV-201 | R² = 0,9400  RMS = 3,830 % | **R² = 0,9991  RMS = 0,466 %** |
| FV-202 | **R² = 0,9989  RMS = 0,545 %** | R² = 0,9778  RMS = 2,396 % |

![Refluxo reconstruído — FV-201](out/refluxo_reconstruido_FV-201.png)

Na direção da FV-201 a reconstrução acerta os quatro patamares (erro de 8 % vira 0,5 %); na
direção da FV-202 ela PIORA, porque o ganho FV-202→FT-203 é pequeno (−0,042) e mal
determinado (R² = 0,97), e o erro relativo das duas vazões se soma no quociente enquanto o
modelo linear direto já era ótimo ali.

![Refluxo reconstruído — FV-202](out/refluxo_reconstruido_FV-202.png)

---

## 8. Comparação com a matriz hoje configurada no MPC

| Par | Configurado hoje | Identificado | Δ ganho |
|---|---|---|---|
| LT-201 ← FV-201  | `Ki=0,002191  τ₁=78  θ=24` | `Ki=0,004547  τ₁=104,8  θ=23` | **2,08×** (1,70× no mesmo τ) |
| LT-201 ← FV-202  | `Ki=−0,003088  τ₁=16  θ=22` | `Ki=−0,002704  τ₁=24,6  θ=23` | 0,88× |
| Refluxo ← FV-201 | `K=−1,629  τ₁=0,7  τ₂=1,5  θ=3,7` | `K=−1,864  τ₁=0,03  θ=4,68` | 1,14× |
| Refluxo ← FV-202 | `K=−2,270  τ₁=0,6  τ₂=1,5  θ=2,0` | `K=−1,991  τ₁=2,57  θ=4,73` | 0,88× |
| FT-204 ← FV-201  | `K=0,0737  τ₁=0,7  τ₂=16,3  θ=3,7` | `K=0,04367  τ₁=9,07  τ₂=7,58  θ=0` | 0,59× |
| FT-204 ← FV-202  | `K=1,0986  τ₁=0,6  τ₂=16,3  θ=2,0` | `K=1,0299  τ₁=17,58  θ=4,51` | 0,94× |

Quatro dos seis pares batem em ±15 % — a matriz atual é boa. Os dois que destoam:

1. **LT-201 ← FV-201: ganho configurado é cerca de metade do medido.** Comparação justa, sem
   misturar ganho com lag: travando `τ₁` no valor configurado (78 s), o ajuste dá
   `Ki = 0,003726`, ou seja **1,70×** — e 2,08× quando cada um usa o seu próprio `τ`. Os dois
   números estão fora da banda de incerteza do perfil (§6.1, ±25 %). Vale registrar a
   procedência: `0,002191` é *exatamente* o número do exemplo de migração do docstring de
   `mpc_config.py:366` ("só o `Ki` escolhido naquela janela precisa ser DIVIDIDO por 100 ao
   migrar: 0,2191 ⇒ 0,002191"). Coincidência de 4 algarismos é improvável — [INFERÊNCIA] esse
   ganho provavelmente nunca foi identificado em planta, é resíduo da correção de unidade de
   2026-09-12. Isso explica a diferença melhor do que qualquer deriva de processo, e é o par
   a corrigir primeiro.
2. **FT-204 ← FV-201: configurado é 1,7× o medido**, num canal fraco (§6.3). Impacto de
   controle pequeno, mas o SSTO usa esse ganho para prever a restrição de vazão de produto.

---

## 9. Validação fora-da-amostra

Nenhum degrau foi reservado para validação — mas o dado out-of-sample existe de graça: as
janelas em que o MPC estava em AUTO, com as **duas MVs se movendo ao mesmo tempo**, que não
entraram em ajuste nenhum. Simulação MIMO (os 6 modelos somados), condição inicial única no
`t0` (média das 5 primeiras amostras), **zero parâmetro livre**.

**Métrica é RMS em EU, não R².** Em janela de AUTO as variáveis quase não variam, e o R²
contra a média pune desproporcionalmente um erro pequeno — daí R² negativo com erro de 2 %.
O R² está no `validacao.json`; aqui lidera o RMS.

**Envelope.** As campanhas excitaram FV-201 em 48,6–68,6 % e FV-202 em 32,9–52,9 %. Fora
disso o modelo está extrapolando, e a métrica mede a extrapolação, não o par. As duas
colunas abaixo separam as coisas; nas figuras o trecho fora do envelope está sombreado.

### Janela A — 16:37–16:42, entre as campanhas (4,9 min; 61 % das amostras no envelope)
![Validação A](out/validacao_A.png)

### Janela B — 16:52–17:01, após a campanha 2 (8,2 min; 33 % no envelope)
![Validação B](out/validacao_B.png)

| Variável | Janela A (RMS) | …no envelope | Janela B (RMS) | …no envelope |
|---|---|---|---|---|
| FT-204 | 0,118 m³/h | 0,123 m³/h | 0,478 m³/h | **0,278 m³/h** |
| LT-201 (c da campanha 1) | 2,463 % | 2,901 % | 3,143 % | 3,614 % |
| LT-201 (c da campanha 2) | 3,336 % | — | 1,742 % | — |
| **LT-201 (só a constante reajustada)** | **0,269 %** | — | **0,627 %** | — |
| Refluxo (linear) | 8,608 % | 5,189 % | 22,020 % | **3,938 %** |
| Refluxo (reconstruído da razão) | 4,909 % | **3,481 %** | 195,7 % (diverge) | **3,257 %** |

Leitura:

- **FT-204 passa.** Duas MVs livres, 5–8 min, zero ajuste: 0,12–0,28 m³/h de erro dentro do
  envelope, contra excursões de 3,5 m³/h. Modelos 3 e 6 validados.
- **A dinâmica do nível passa; o que não se transporta é o ponto de balanço.** O erro cru de
  2,5–3,1 % é dominado pela escolha da constante `c`: a diferença entre `c` da campanha 1 e
  da campanha 2 (0,0052 %/s) vale 2,5 % de nível em 8 min, a mesma ordem do erro — tanto que
  trocar `c₁` por `c₂` melhora a janela B (3,14 → 1,74 %) e piora a A (2,46 → 3,34 %).
  Reajustando SÓ essa constante escalar — um parâmetro, nenhum dinâmico, exatamente o que a
  atualização de bias do MPC faz a cada ciclo — o erro cai para **0,269 % em 5 min** e
  **0,627 % em 8 min**. `Ki` e `τ₁` dos Modelos 1 e 4 estão validados fora da amostra.
- **Quatro estimativas independentes da constante de balanço do vaso, e ela NÃO é
  constante.** Em ordem cronológica: −0,15465 (campanha 1, 16:27–16:36), −0,14096 (janela A,
  16:37–16:42), −0,15982 (campanha 2, 16:43–16:52), −0,16488 (janela B, 16:52–17:01) %/s —
  ±8 % em torno de −0,155, obtidas com derivas de sinal oposto e MVs em pontos
  completamente diferentes. A concordância de ordem de grandeza confirma que `Ki₁` e `Ki₂`
  são mutuamente consistentes e que a deriva da §4 era ponto de operação, não artefato de
  ajuste. Mas a dispersão tem padrão, não é ruído: **cada janela de AUTO é melhor explicada
  pela constante da campanha vizinha no tempo** — `|c₁ − c_A| < |c₂ − c_A|` e
  `|c₂ − c_B| < |c₁ − c_B|`, e o RMS segue junto (janela A: 2,463 com c₁ contra 3,336 com
  c₂; janela B: 1,742 com c₂ contra 3,143 com c₁). O ponto de balanço do vaso **deriva na
  escala de dezenas de minutos** (entrada ou composição não medida). Conclusão de projeto:
  nenhum valor fixo de `c` serve para simulação longa — é exatamente para isso que existe a
  atualização de bias a cada ciclo no MPC, e é mais uma razão para não julgar os Modelos 1 e
  4 pelo erro da simulação crua.
- **O refluxo linear falha fora da amostra** (5,2–22 %), como a §7 previa. Dentro do
  envelope, a reconstrução pela razão continua melhor (3,5 vs 5,2 % na janela A; 3,3 vs
  3,9 % na B), mas a margem encolhe muito em relação ao in-sample (0,47 vs 3,83 %): com as
  duas MVs se movendo, o erro do par fraco FV-202→FT-203 (K = −0,042, R² = 0,97) entra no
  quociente e come o ganho.
- **A janela B é, em dois terços, teste de extrapolação — e ali os modelos falham
  corretamente.** O MPC levou FV-201 a 85 % e FV-202 a 20 %, 2–3× fora da faixa excitada; a
  vazão de produto real encosta em 0,1 m³/h enquanto o modelo linear prevê −1,1 m³/h
  (impossível), e a razão, que divide por FT-202 modelado, explode junto — vai a −794 % /
  +775 % (há um piso de 0,2 m³/h no denominador só para não gerar infinito no entregável).
  A escala do gráfico segue o medido e o modelo linear, senão a divergência achataria tudo;
  o trecho em que a reconstrução sai de escala está anotado no próprio painel. Isso **não é
  reprovação dos pares**: é a demarcação do envelope de validade. Restringindo às amostras
  dentro da faixa identificada, o mesmo trecho dá 3,3 % de erro no refluxo e 0,28 m³/h no
  FT-204.

---

## 10. Limitações

- **`Ki` e `τ₁` do par FV-201→LT-201 são correlacionados** (§6.1): patamar de 180 s contra
  τ ≈ 105 s. O mínimo de RMS é nítido, mas a banda honesta do `Ki` é ±25 %, não os ±2 % da
  covariância, e o par só faz sentido junto.
- **Envelope de validade:** FV-201 48,6–68,6 % e FV-202 32,9–52,9 %, nível 34–56 %. A
  janela B da §9 mostra o que acontece fora: vazão prevista negativa e razão divergente.
  Nenhum dos seis pares deve ser usado para prever fora dessa faixa sem novo ensaio.
- **A constante de balanço do vaso (−0,155 %/s) não é parte do modelo exportado** e responde
  por quase todo o erro da simulação crua do nível (§9). Na planta quem a corrige é a
  atualização de bias do MPC; em qualquer simulação offline ela precisa ser estimada.
- **Interação não excitada simultaneamente.** Cada campanha moveu uma MV com a outra
  congelada — correto para montar a matriz, mas não revela ganho de uma MV dependendo da
  posição da outra. Indício: o ganho FV-202→Refluxo (−1,99) foi medido com FV-201 em 54,3 %,
  não em 58,6 %. A validação MIMO da §9 é a evidência de que a superposição funciona no
  envelope.
- **Overruns do MPC subiram de 3 para 33 — artefato do host, não do ensaio.** A contagem
  ainda era 3 às 16:38, com a campanha 1 já encerrada; os 30 novos apareceram na janela em
  que os ajustes (scipy/matplotlib, 8–18 s de CPU) rodaram na mesma máquina do flow-runtime,
  com `last_solve_ms` de 827 ms contra Ts = 2000 ms. Os dados estão íntegros (273 amostras
  para 269 esperadas por janela). Ajustes seguintes rodaram com `nice -n 19`.

## 11. Recomendações

1. Atualizar a matriz `models` com os seis parâmetros da §1 — em especial
   `cv_ij93 ← mv_chns`, cujo valor atual é [INFERÊNCIA] resíduo de migração de unidade (§8).
2. Repetir só o par FV-201 → LT-201 com patamar de 8–10 min para desacoplar `Ki` de `τ₁`.
3. Refazer o par FV-201 → FT-204 com degrau maior (≥ 20 %) e θ livre para ambos os lados:
   hoje é ganho pequeno com atraso no limite (§6.3).
4. Não tratar o refluxo como linear na direção da FV-201. Duas saídas: aumentar o
   `move_weight` dessa MV para cobrir a variação de ganho de 2,6×, ou — melhor — trocar a CV
   por uma vazão medida (FT-203), que é linear em ambas as direções, e deixar a razão como
   indicador de operação. A reconstrução da razão (§7) é ótima dentro da campanha
   (RMS 0,47 %) e continua melhor que o linear fora dela (3,5 % contra 5,2 %), mas a margem
   encolhe: ela não substitui a troca de CV, só documenta a causa.
5. Antes de qualquer próximo teste em MAN, entrar em MAN **num par de MVs balanceado**
   (dLT/dt ≈ 0): no teste 2 o nível derivou 15 % sozinho por causa disso.
