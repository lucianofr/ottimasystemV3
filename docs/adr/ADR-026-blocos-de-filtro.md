# ADR-026 — Blocos de filtro de sinal: Filtro 1ª ordem e Filtro Kalman

**Status:** Aceito · 2026-08-10

## Contexto
Sinal de campo chega com ruído. Filtrar antes de entregar a uma CV/Restrição do MPC (ou a
uma escrita) já era possível pelo bloco Python-Script (ADR-018: `math` + `numpy` + `state`
persistente), mas cada instância virava código livre: sem validação no save, sem resumo
legível no canvas e sem garantia de que dois flows usam a mesma discretização.

## Decisão
Dois blocos dedicados na paleta, ambos com **uma entrada (`in`) e uma saída (`out`)**,
numéricas, entrada obrigatória:

- **Filtro 1ª ordem** — parâmetro único `tau` (constante de tempo, em segundos).
  Discretização ZOH no Ts do flow: `y[n] = a*y[n-1] + (1-a)*u[n]`, `a = exp(-Ts/tau)`.
  `tau` abaixo de `Ts/10` degrada para passagem direta — mesma convenção e mesmo código do
  estágio de 1ª ordem do bloco TFS (ADR-022).
- **Filtro Kalman** — filtro escalar de passeio aleatório (`x[k] = x[k-1] + w`,
  `z[k] = x[k] + v`), configurado por **dois desvios padrão na EU do próprio sinal**:
  `measurement_noise` (ruído da medição) e `process_noise` (variação esperada do valor
  verdadeiro por varredura). O bloco eleva os dois ao quadrado internamente (`r`, `q`) —
  variância e covariância não aparecem na interface.
  Covariância inicial `P₀ = r` e `x` inicializado na primeira amostra válida após o reset,
  sem transiente artificial partindo de zero.

Os dois seguem as regras gerais de bloco já vigentes: `exec_order` (ADR-024), estado interno
preservado no hot-swap enquanto a config não muda (ADR-011), cold start ⇒ saída nula e
inválida, amostra inválida (`ok=False`) é processada e a flag é propagada.

## Consequências
- (+) Filtragem passa a ser config declarativa validada no save (422 para `tau` negativo,
  `measurement_noise` não-positivo, número não-finito), não código por instância.
- (+) O Kalman fica configurável por quem lê uma tendência: os dois campos estão na EU do
  sinal e são estimáveis por inspeção, sem estatística.
- O estágio de 1ª ordem sai de `blocks/tfs.py` para um módulo compartilhado; TFS e Filtro 1ª
  ordem passam a ter, por construção, a mesma resposta ao degrau.
- A paleta da v1 cresce de 5 para 7 blocos (RF-301, GLOSSARY).
- Filtro em cascata continua sendo trabalho do engenheiro: um bloco por estágio, ligados em
  série — nenhum dos dois blocos ganha ordem configurável.
