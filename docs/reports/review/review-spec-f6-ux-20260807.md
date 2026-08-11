# Revisão da spec F6 — conformidade com DESIGN.md/PRODUCT.md e arquitetura de informação

**Spec:** docs/specs/F6-portabilidade-hardening.md @ da25cd6
**Veredito:** APPROVE WITH CHANGES
**Achados:** 0 Critical, 8 Important, 2 Minor

## Achados

### UX-01 — Lâmpada âmbar de pendência de segredo colide com a Regra da Cor Anormal no cenário que a própria fase testa [Important]

**Seção:** §6.3-2 (linha 268); Anexo A-4 (linha 416)

**Problema:** DESIGN.md define Âmbar como "advertência, overrun, qualidade degradada, **estados pendentes de atenção**" (DESIGN.md:50) — no sentido estrito da definição, uma pendência de credencial se encaixa, então §6.3-2 não viola a letra da regra de cor por severidade isolada. O problema é outro: a Regra da Cor Anormal (DESIGN.md:54) diz "em qualquer tela em **operação normal**... cor saturada aparece somente quando algo exige atenção... Se uma tela parada 'colorida' surgir num mockup, o mockup está errado." O cenário de aceite da própria fase (E2E-F6-02, linha 343) é: importar um projeto com conexão segura ⇒ toda conexão importada nasce com `pending_secrets` (§3.2-7, linha 177-179) ⇒ **toda linha da tabela de Conexões acende âmbar simultaneamente** logo após um import bem-sucedido — que é o estado normal e esperado do primeiro dia de uma instalação (`docs/IMPLANTACAO.md` §5, linha 320: "re-informar segredos no destino" é o procedimento documentado, não uma falha). Uma tela onde toda linha está âmbar não é "operação normal com uma exceção que exige atenção": é a tela inteira colorida em repouso, exatamente o caso que a Regra da Cor Anormal chama de mockup errado.

**Evidência:** DESIGN.md:50 ("Âmbar Advertência: ... estados pendentes de atenção"), DESIGN.md:54 ("Se uma tela parada 'colorida' surgir num mockup, o mockup está errado"), F6-portabilidade-hardening.md:268 ("Coluna Pendências... lâmpada âmbar + ícone + rótulo curto"), F6-portabilidade-hardening.md:343 (E2E-F6-02, round-trip que produz `pending_secrets` para toda conexão segura importada).

**Consequência:** Um engenheiro comissionando uma planta nova (o público de `docs/IMPLANTACAO.md`) abre a tela de Conexões pela primeira vez e vê tudo âmbar — não porque algo está errado, mas porque é o primeiro passo do procedimento normal. Isso desvaloriza o âmbar como sinal: se "acabei de importar" e "conexão prestes a falhar de verdade" usam a mesma cor saturada, o operador/engenheiro perde o hábito de tratar âmbar como "isso é anômalo, olhe agora".

**Correção sugerida:** Distinguir dois estados visualmente, sem inventar campo novo (a pendência continua 100% derivada, §6.3-1): (1) **pendência recém-importada / nunca configurada** — célula com ícone + rótulo em tom **neutro** (Texto Secundário sobre Chapa, sem saturação), já que é esperado nesse momento do fluxo; (2) **pendência em conexão que uma vez teve o segredo e o perdeu, ou que está deployada e falhando por causa dela** (i.e., a conexão pertence a um flow com `desired_state != "stopped"` ou já reportou `comm_failure`/`cert_missing`) — aí sim lâmpada âmbar, porque é desvio de um estado que deveria estar operacional. O predicado extra é barato: `pendente && (flow_deployado || já_falhou)`, calculável no mesmo lugar que já calcula `has_password`/`server_cert_file` (§6.3-1), sem nova consulta ao servidor além do que a tela de Conexões/Flows já busca.

---

### UX-02 — `application_uri` como plaqueta contradiz o tratamento que DESIGN.md já dá a identificadores técnicos equivalentes [Important]

**Seção:** §6.2-1 (linha 255)

**Problema:** §6.2-1 manda "Fingerprint e datas em mono tabular; `application_uri` como plaqueta." Mas DESIGN.md §Typography já classifica explicitamente o tipo de dado ao qual `application_uri` pertence — um identificador técnico opaco, no mesmo formato de `node_id` (ambos strings com dois-pontos/dois-pontos-vírgula delimitando namespace, ex.: `urn:ottima:opc-worker` vs `ns=2;s=WD_R`, PRD/bundle exemplo em F6-portabilidade-hardening.md:91-92) — e a coloca sob **mono tabular**, não plaqueta: "Valor de Processo (Spline Sans Mono): todo número de processo, **node_id**, timestamp" (DESIGN.md:76). A Regra da Plaqueta (DESIGN.md:78) é para "rótulo de tag/equipamento/variável" — nome de instrumento, não identificador de namespace/URI. `application_uri` não é o nome de um equipamento; é um identificador técnico de certificado, categoricamente mais próximo de `node_id` do que de "TT-101".

**Evidência:** DESIGN.md:76 ("todo número de processo, node_id, timestamp" → mono); DESIGN.md:78 ("Regra da Plaqueta... rótulo de tag/equipamento/variável"); F6-portabilidade-hardening.md:255 (`application_uri` como plaqueta).

**Consequência:** Dois implementadores resolvem diferente — um segue a letra de §6.2-1 (plaqueta, caps+Narrow+tracking), outro segue DESIGN.md por analogia com `node_id` (mono tabular). O resultado é um segundo dialeto tipográfico para o mesmo tipo de dado (identificador técnico opaco), o que a Regra do Layout proíbe explicitamente ("Don't introduzir... dialeto visual por tela", DESIGN.md:128).

**Correção sugerida:** Trocar `application_uri` de plaqueta para **mono tabular** (mesmo tratamento de `node_id`), consistente com DESIGN.md:76. `subject` (nome distinto X.509, também não é nome de equipamento) deveria seguir o mesmo raciocínio — texto corrente (Body), não plaqueta. Reservar plaqueta exclusivamente para o rótulo do card ("Certificado da aplicação (instalação)") e para nomes de campo, não para os valores do certificado em si.

---

### UX-03 — Estado de erro do certificado ilegível e o aviso de re-trust não têm tratamento de canal redundante especificado [Important]

**Seção:** §6.2-1 (linhas 257-258)

**Problema:** §6.2-1 trata dois estados de atenção sem dizer qual canal visual usam: (1) "Regerar manda `force: true`, exige confirmação e, ao voltar, exibe o `warning` de re-trust que o backend já devolve... **verbatim**, sem reescrever" — o texto vem do backend, mas a spec não diz se esse texto ganha ícone+cor de advertência (âmbar, por ser literalmente um warning) ou se é só um parágrafo de texto solto; (2) "`GET /app` respondendo 500 com o texto de `_MSG_ILEGIVEL` (`certificates.py:33-36`) é estado de erro renderizado, não tela quebrada" — não diz que a Regra do Canal Redundante (DESIGN.md:58: "Severidade nunca é comunicada só por cor: sempre cor + ícone/forma + texto") se aplica aqui, nem que cor (o certificado de aplicação ilegível é um problema de segurança/confiança — mais perto de Vermelho Alarme, "falha", DESIGN.md:49, do que de Âmbar).

**Evidência:** F6-portabilidade-hardening.md:257-258; DESIGN.md:49 ("Vermelho Alarme: alarme ativo, falha... "); DESIGN.md:58 (Regra do Canal Redundante).

**Consequência:** Sem a atribuição explícita de severidade+ícone, o implementador tem duas leituras plausíveis (texto simples vs. bloco de alerta colorido) para um estado que é justamente sobre a identidade criptográfica da instalação falhar — o tipo de estado que DESIGN.md pede para nunca depender só de texto solto.

**Correção sugerida:** Especificar: certificado ilegível ⇒ bloco de erro com ícone de falha + Vermelho Alarme + o texto de `_MSG_ILEGIVEL` verbatim (é uma falha de infraestrutura de segurança, não uma advertência transitória) + botão **Gerar** habilitado (mesmo caminho do "ausente"). Aviso de re-trust pós-regeração ⇒ bloco Âmbar Advertência + ícone + o texto do backend verbatim (é literalmente um warning), permanecendo visível até o admin confiar de novo no certificado da aplicação nos servidores OPC — não um toast que desaparece sozinho.

---

### UX-04 — Certificado de instalação na página de Conexões (decisão A-7) não tem mitigação visual de escopo especificada [Important]

**Seção:** §6.2-1 (linha 254); Anexo A-7 (linha 419)

**Problema:** Não relitigo a decisão A-7 (certificado de aplicação — escopo de **instalação**, um por servidor — vive no topo de `/engenharia/conexoes`, que é a página do **projeto ativo**). A decisão é aprovada e o motivo é bom (comissionar uma conexão segura exige os dois certificados na mesma sessão). O que falta é a mitigação de escopo que a própria pergunta A-7 registra como problema ("o certificado de aplicação é de INSTALAÇÃO e não tem casa na navegação") e que a decisão resolve só posicionalmente, não visualmente: o único sinal textual é o parêntese "(instalação)" no título da chapa (§6.2-1, linha 254). Nada na spec diz que essa chapa precisa se distinguir estruturalmente da tabela de Conexões abaixo dela (que É por-projeto), nem que o texto explique a consequência prática do escopo: o certificado **não muda** quando o admin troca de projeto ativo (§6.1-4).

**Evidência:** F6-portabilidade-hardening.md:254 ("Chapa 'Certificado da aplicação (instalação)' no topo de `/engenharia/conexoes`"); Anexo A-7 linha 419; DESIGN.md:84 (hierarquia de console é por **projeto ativo** → canvas → operação → modal — não prevê um nível "instalação" dentro dela); DESIGN.md:98 (Regra da Chapa: "se dois elementos precisam se separar, muda-se o tom ou traça-se uma linha").

**Consequência:** Um admin que ativa outro projeto (§6.1-4, ação que já é a única de consequência de processo na tela) pode razoavelmente perguntar "o certificado que acabei de gerar/regerar ainda vale?" — a resposta é sim, mas nada na tela diz isso. Sem separação visual clara, a chapa de instalação lê como "mais uma seção de configuração deste projeto", e um usuário apressado pode tentar "resolver" a pendência de certificado pensando que ela é por-projeto quando na verdade é única para toda a instalação.

**Correção sugerida (sem reabrir A-7):** (1) Aplicar a Regra da Chapa como separação física real, não cosmética: a chapa do certificado de aplicação recebe um tom distinto (ex.: um passo mais claro que a Chapa padrão) e uma linha 1px cheia entre ela e a tabela de Conexões, não apenas espaçamento; (2) legenda fixa abaixo do título da chapa, Texto Secundário: "Este certificado pertence à instalação — não muda ao trocar de projeto ativo." Ambas são mudanças de apresentação, zero rota nova, zero contrato de API novo.

---

### UX-05 — Fluxo de import não mostra prévia antes de criar; o engenheiro comita às cegas [Important]

**Seção:** §6.1-6 (linha 250)

**Problema:** O fluxo descrito é: selecionar arquivo → nome editável (pré-preenchido de `bundle.project.name`) → **ao concluir**, resumo com `pending_secrets`. Não existe etapa intermediária em que o engenheiro vê o que vai ser criado (quantas conexões, tags, flows, quais nomes) **antes** de disparar o `POST /api/projects/import`. Isso é operacionalmente diferente de "escolher arquivo, editar nome, confirmar", que sugere reversibilidade — na prática é "escolher arquivo, editar nome, **criar imediatamente**, só então saber o que foi criado".

**Evidência:** F6-portabilidade-hardening.md:250 ("Importar no cabeçalho: seleção de arquivo..., campo Nome do projeto..., e ao concluir um resumo com `pending_secrets`").

**Consequência:** Para o público de `docs/IMPLANTACAO.md` (engenheiro comissionando uma planta de cliente, §8), importar o bundle errado (ex.: arquivo de outra planta, salvo com nome parecido) só é percebido **depois** que o projeto já existe no banco — exigindo um `DELETE` de limpeza manual em vez de um cancelamento antes da criação.

**Correção sugerida:** Sem tocar o contrato da API (o `bundle` já está no cliente, em memória, antes do `POST` — é o mesmo arquivo lido por `File.arrayBuffer()` no primitivo de upload, §6.2-3): fazer o `JSON.parse` do arquivo **no cliente**, ao selecioná-lo, e renderizar uma prévia entre a seleção do arquivo e o botão "Importar" — nome/descrição do projeto, contagem de conexões/tags/flows, e a mesma pendência derivada de §6.3-1 calculada sobre o `bundle.connections` (sem chamada ao servidor: os campos `auth_mode`/`security_policy` já estão no JSON do bundle). Arquivo que não é JSON válido ou não tem o formato esperado (`schema_version`/`project`/`connections` ausentes) mostra erro de leitura ali mesmo, antes de qualquer requisição.

---

### UX-06 — `detail` de import com até 10 problemas concatenados numa string não tem tratamento de apresentação; um split ingênuo por `;` quebra em dados reais [Important]

**Seção:** §3.2-5 (linha 171); §6.1-6 (linha 250)

**Problema:** O formato normativo do erro é uma string única pt-BR com até 10 problemas separados por `; ` (ex.: `"Import recusado (3 problemas): flows[2].graph: nó 'mpc_x7k2' refere tag inexistente (conexão 'gateway-1', tag 'TT-999'); tags[7]: conexão 'gateway-2' não existe no arquivo; ..."`). §6.1-6 só diz "Recusa exibe o `detail` agregado inteiro, sem truncar" — sem especificar apresentação. Renderizado como um parágrafo contínuo de `Body`, 10 problemas concatenados por `;` é difícil de escanear — o próprio caso de exemplo da spec já tem duas cláusulas cabendo numa linha típica de tela. Mas a correção óbvia (dividir a string por `;` e renderizar como lista) é **insegura sobre os dados reais do domínio**: `node_id` de tag OPC-UA contém `;` legitimamente (o próprio exemplo normativo do bundle usa `"ns=2;s=WD_R"`, linha 91) e mensagens de erro sobre tag/conexão citam nome e `node_id` (§2.2-2 cita a forma "conexão/tag" como algo a **evitar** por ambiguidade de separador, linha 129 — o mesmo raciocínio se aplica aqui: um separador textual sobre dados que já contêm esse caractere é uma armadilha).

**Evidência:** F6-portabilidade-hardening.md:171 (formato do `detail`); F6-portabilidade-hardening.md:91 (`"watchdog_read_node_id": "ns=2;s=WD_R"` — `;` é caractere válido em `node_id`); F6-portabilidade-hardening.md:129 (a própria spec já rejeitou um separador textual em `tag_ref` pelo mesmo motivo — ambiguidade sobre dados que contêm o separador).

**Consequência:** Se o implementador "resolver" a legibilidade dividindo a string por `;` (solução óbvia e não especificada), uma mensagem de erro que cite um `node_id` com `;` quebra no meio, produzindo itens de lista truncados/errados na tela exatamente no momento em que o engenheiro mais precisa ler o texto exato para corrigir o bundle.

**Correção sugerida (sem mudar o contrato de string única, A-5):** Não fazer parsing/split algum sobre o conteúdo. Tratamento puramente tipográfico: renderizar o `detail` dentro de um bloco de largura fixa, fonte mono (Spline Sans Mono — o mesmo registro que a Regra do Número Tabular já usa para dado técnico denso), com `white-space: pre-wrap` para quebra natural por linha sem cortar palavras, dentro de um container roládo se ultrapassar a altura do modal — preservando a string inteira, literal, copiável (útil para colar num ticket de suporte), só melhorando a densidade de leitura sem interpretar o conteúdo.

---

### UX-07 — "Ativar" (para todos os flows do projeto anterior) usa a mesma força de confirmação que ações de consequência muito menor [Important]

**Seção:** §6.1-4 (linha 248)

**Problema:** §6.1-4 já reconhece que Ativar é a ação de maior consequência da tela ("É a única ação da tela com consequência de processo") e pede confirmação com o efeito escrito. Mas o mecanismo — um modal com o texto do efeito e um botão de confirmar — é o **mesmo peso de interação** usado em `§6.1-3` para excluir uma linha e em `§6.2-1` para regerar um certificado. Comparado ao **Comando pendente-até-confirmar** que a F5 usa para escritas de SP/MV (F5-operacao.md:203) — mecanismo deliberadamente mais leve, porque a ação é frequente, de um único flow, e autorreverte se não confirmada —, Ativar é o oposto em todo eixo: rara, admin-only, afeta **todos** os flows do projeto atual simultaneamente (até a ordem de grandeza de RNF-01, ~10 flows), e é irreversível pelo próprio mecanismo de confirmação (não há "desfazer" análogo ao autorreverte do F5). Nenhuma ação do sistema, em nenhuma fase, tem esse raio de efeito num único clique confirmado.

**Evidência:** F6-portabilidade-hardening.md:248; F5-operacao.md:203 (mecanismo mais leve usado propositalmente para ações menores, frequentes, autorreversíveis); PRODUCT.md:35 ("Dimensionamento-alvo: ~10 flows simultâneos"); PRODUCT.md:62 (Princípio 1 — "Falhar para o lado seguro é inegociável").

**Consequência:** Um modal padrão de confirmação é vulnerável ao hábito — o mesmo dedo que já clicou "Confirmar" em cinco exclusões de tag naquela sessão clica "Confirmar" em Ativar sem ler o texto do efeito, na primeira vez em que a consequência é realmente grave (planta de cliente com flows em REMOTO/AUTO reais, não em laboratório).

**Correção sugerida:** Manter o modal e o texto do efeito (não mexe no contrato), mas exigir que o admin **digite o nome do projeto atualmente ativo** (não o nome do alvo) no campo de confirmação antes do botão "Ativar" habilitar — o mesmo texto que aparecerá na frase do efeito ("Ativar 'X' encerra a execução de todos os flows do projeto atual"), então não é memorização, é copiar o que já está na tela. Zero dependência nova, zero rota nova; é só um campo de texto e uma comparação de string no cliente.

---

### UX-08 — "bundle" é vocabulário inventado fora do GLOSSARY, com risco real de vazar para a UI em pt-BR [Important]

**Seção:** §2 (título, linha 71); §2.1-1 (linha 75); §3.2-1 (linha 159); Anexo A-2 (linha 414)

**Problema:** `docs/GLOSSARY.md` não define "bundle" (conferido: a tabela de termos não tem a entrada). `PRODUCT.md` também não usa o termo — fala em "export/import JSON" (PRODUCT.md:40). A spec F6, no entanto, usa "bundle" como substantivo normativo em todo o texto (título de §2, `bundle.project.name` em §6.1-6, e — o ponto que importa — **é literalmente a chave do corpo da requisição da API**: `{"name": "...", "bundle": {…}}`, §3.2-1, linha 159). PRODUCT.md exige "UI 100% pt-BR (ADR-023). Terminologia fixada pelo `docs/GLOSSARY.md`... não renomear conceitos" (PRODUCT.md:42) — regra que a própria F6 invoca para justificar §2.1-1 ("o JSON de projeto não inventa vocabulário"). O termo "bundle" não é um dos termos consagrados que a Regra explicitamente permite não traduzir (SP/MV/CV/RCAS/bumpless, DESIGN.md:118/PRODUCT.md:65) — é um substantivo genérico em inglês para "arquivo/pacote", sem lastro no domínio APC.

**Evidência:** GLOSSARY.md (tabela completa, sem entrada "bundle"); PRODUCT.md:42; DESIGN.md:118 (lista fechada de termos que não se traduz); F6-portabilidade-hardening.md:159 (`bundle` como chave JSON da API).

**Consequência:** Nada na spec diz qual é o nome pt-BR que a UI mostra para o que o código chama de `bundle`. Um implementador seguindo o vocabulário da própria spec como fonte (é o nome usado em toda a seção §2 e §6) tem chance real de escrever rótulo/copy como "Arquivo de bundle" ou "Bundle do projeto" na tela de import/export — violando a regra 100% pt-BR sem que ninguém tenha decidido isso conscientemente.

**Correção sugerida:** Adicionar uma linha à spec (ou ao GLOSSARY) fixando o termo de UI: "bundle" é nome de campo de API/código; a UI e toda copy pt-BR dizem **"arquivo do projeto"** (export) ou **"arquivo de importação"** (import) — nunca "bundle" em texto visível ao usuário. Consistente com o padrão já usado para o certificado (`.der` é nome de arquivo técnico, mas a UI diz "Baixar .der" citando a extensão, não inventando um substantivo).

---

### UX-09 — Estado vazio "nenhum projeto cadastrado" (zero projetos, não apenas nenhum ativo) não é especificado [Important]

**Seção:** §6.1-2 (linha 246); §6.1-7 (linha 251)

**Problema:** §6.1-7 cobre "sem projeto ativo" (as quatro telas que hoje apontam para a página inexistente). Mas a própria página `/engenharia/projetos`, no dia zero de uma instalação nova (antes do primeiro `POST /api/projects` ou do primeiro import — exatamente o ponto de partida de `docs/IMPLANTACAO.md` §4, linha 319, "Comissionamento passo a passo... projeto, conexão, tags, flow..."), tem **zero linhas**. §6.1-2 descreve só a tabela com dados ("nome, descrição, Ativo..., ações"); não há menção ao estado da tabela vazia.

**Evidência:** F6-portabilidade-hardening.md:246 (tabela descrita só com dados); F6-portabilidade-hardening.md:319 (IMPLANTACAO.md §4 — comissionamento começa criando o primeiro projeto, cenário de tabela vazia); F6-portabilidade-hardening.md:251 (§6.1-7 cobre "sem ativo", não "sem nenhum").

**Consequência:** É o primeiro estado que qualquer instalação nova encontra na primeira tela de engenharia que o guia de implantação manda abrir. Sem especificação, o resultado plausível é uma tabela com cabeçalho e nada embaixo — sem indicar que "Criar" (ou "Importar") é o próximo passo, o que é justamente o tipo de tela vazia sem afordância que o roteiro de comissionamento (que é read-only/procedural, não interativo) não vai pegar sozinho.

**Correção sugerida:** Estado vazio explícito na tabela quando `GET /api/projects` retorna lista vazia: mensagem "Nenhum projeto cadastrado" + os dois CTAs já existentes na tela (Criar, Importar) em destaque, sem nova rota nem novo componente — reaproveita os mesmos botões do cabeçalho, só evita a tabela em branco.

---

### UX-10 — Cor da lâmpada "Ativo" não é especificada; a leitura intuitiva (verde) viola a reserva exclusiva do Verde Rodando [Important]

**Seção:** §6.1-2 (linha 246)

**Problema:** "Tabela... nome, descrição, **Ativo** como lâmpada de estado (quadrado + ícone + rótulo, nunca só cor), ações" — a forma do componente é normativa (lâmpada = quadrado+ícone+rótulo), mas a **cor** não é dita. DESIGN.md reserva Verde exclusivamente: "**Verde Rodando** (apagado/mutado): exclusivamente lâmpada de estado 'rodando/vivo' (flow em execução, heartbeat, watchdog OK)" (DESIGN.md:51) — e reforça no Don't: "nunca cor... verde fora da lâmpada 'rodando/vivo'" (DESIGN.md:124). "Ativo" (projeto selecionado) não é "rodando" no sentido literal do glossário — um projeto ativo pode ter todos os flows parados (`desired_state: stopped`); e nada garante que os flows do projeto ativo estejam de fato "vivos" no instante em que a lâmpada é lida.

**Evidência:** F6-portabilidade-hardening.md:246; DESIGN.md:51 (Verde Rodando, uso exclusivo); DESIGN.md:124 (Don't); DESIGN.md:38 (Azul Industrial cobre "item ativo de navegação" — candidato mais próximo semanticamente, já que "Ativo" aqui é "selecionado/em uso", não "em execução").

**Consequência:** A leitura intuitiva de "Ativo" para a maioria dos implementadores/designers é verde ("ligado" = verde, convenção universal de UI) — que é exatamente a cor que DESIGN.md proíbe fora do sentido estrito de execução. Um projeto ativo mas com todos os flows parados mostraria verde numa tela em repouso, confundindo "projeto selecionado" com "processo rodando" — a mesma confusão semântica que a Regra do Canal Redundante e a nomenclatura do sistema (LOCAL/REMOTO, deploy, `desired_state`) trabalham duro para evitar em todo o resto do produto.

**Correção sugerida:** Especificar explicitamente: lâmpada "Ativo" usa **Azul Industrial** (não verde, não âmbar) — é estado de seleção/interação ("este é o projeto com o qual o sistema opera agora"), a mesma semântica de "item ativo de navegação" que DESIGN.md já atribui ao azul (DESIGN.md:38). Projetos inativos ficam com a lâmpada em tom neutro (Texto Secundário), sem cor saturada nenhuma.

---

### UX-11 — Estado "arquivo selecionado não é JSON válido" não é coberto (Minor)

**Seção:** §6.1-6 (linha 250); §6.2-3 (linha 260)

**Problema:** O primitivo de upload (§6.2-3) é genérico (`File.arrayBuffer()` → corpo bruto) e reusado pelo import. Para o certificado, um arquivo inválido só é descoberto no servidor (via `_MSG_ILEGIVEL`, coberto em §6.2-1). Para o import, se a UX-05 acima for adotada (parse client-side para prévia), passa a existir um novo ponto de falha client-side — arquivo que não é JSON, ou JSON sem os campos mínimos (`schema_version`/`project`/`connections`) — que a spec não cobre em nenhum dos dois cenários (com ou sem a prévia da UX-05).

**Evidência:** F6-portabilidade-hardening.md:250; F6-portabilidade-hardening.md:260.

**Consequência:** Menor porque, sem a prévia client-side, o comportamento hoje é "servidor recusa com 422 (`schema_version` ausente cai na camada 2, forma)" — funciona, só não é tão amigável quanto poderia. Não bloqueia o aceite.

**Correção sugerida:** Se a UX-05 for adotada: erro de leitura local ("Arquivo selecionado não é um projeto OttimaSystem válido") antes da prévia, sem round-trip ao servidor. Se não for adotada: nenhuma mudança necessária, o 422 do servidor já cobre o caso.

---

### UX-12 — "Pendência" e "confiar certificado" não estão no GLOSSARY, mas são uso genérico de linguagem, não termo de domínio (Minor)

**Seção:** §6.2-2 (linha 259); §6.3 (título, linha 263)

**Problema:** Nem "pendência" nem "confiar (certificado)" aparecem em `docs/GLOSSARY.md`. Diferente do achado UX-08 (onde "bundle" é um substantivo técnico inglês sem tradução óbvia e vira chave de API), esses dois são verbos/substantivos comuns do português, usados de forma consistente com o domínio (ADR-021 já fala de "trust"/confiança de certificado) e não competem com nenhum termo já fixado no glossário.

**Evidência:** GLOSSARY.md (tabela completa); F6-portabilidade-hardening.md:259/263.

**Consequência:** Nenhuma prática identificada — registro para não ser redescoberto, não é ação necessária.

**Correção sugerida:** Nenhuma. Verificação positiva, listada aqui só para deixar registrado que o eixo de vocabulário foi conferido nesses dois termos e não achou problema.

---

## Verificações positivas

- **`exportar`/`importar`** como verbos de UI batem com GLOSSARY.md:7 ("Exportável/importável em JSON") — sem divergência.
- **Coluna Pendências (§6.3-2)** já cumpre a Regra do Canal Redundante por construção própria: lâmpada + ícone + rótulo curto + `title` com o efeito — os três canais estão presentes (o problema levantado em UX-01 é sobre a cor específica no cenário de import em massa, não sobre a ausência de canal).
- **EU nas portas de Script/TFS no canvas (§6.4-2)** segue exatamente a Regra do Número Tabular: mono tabular para o número, Texto Secundário menor para a unidade — mesmo tratamento que os nós OPC já dão à tag.
- **Faceplate de DV sem `range` (§4.2-4, §6.5)**: plaqueta + valor mono tabular + EU, sem barra — consistente com o que a F5 já entregou e com a convenção de PV/SP/OUT só aparecer quando há escala real para desenhar.
- **Primitivo de upload (§6.2-3)**: escolha de corpo bruto em vez de `FormData`/multipart é coerente com o padrão do resto do repo (nenhum outro uso de formulário multipart) — não introduz um segundo padrão de transporte de arquivo.
- **Hierarquia de nav (§6.1-1)**: Projetos entra no grupo de engenharia existente (Conexões · Tags · Flows · Trend), sem inventar um nível novo na hierarquia de quatro camadas do DESIGN.md §Layout — é o lugar certo para uma tela de CRUD de engenharia, distinta da "visão geral do projeto ativo" que a Home (F5) já ocupa.
- **`Ts_mpc`, RCAS/CAS/ROUT, LOCAL/REMOTO, MAN/AUTO** e demais termos herdados de fases anteriores: a F6 não introduz nenhuma tradução nova nem sinônimo para vocabulário já fixado — confere com PRODUCT.md:65 ("não traduzir nem apelidar termos consagrados").
