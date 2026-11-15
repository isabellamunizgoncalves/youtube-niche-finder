---
name: analise-nicho-canal
description: Diagnostica o nicho de QUALQUER canal do YouTube — nicho, subnicho, microsubnicho, se o canal esta misturando esses niveis (e se a mistura ajuda ou atrapalha) e a estrutura/formula dos titulos. Use quando a pessoa mandar um canal, link, @handle, nome de canal ou uma lista de titulos e perguntar "qual o nicho desse canal", "qual o subnicho", "microsubnicho", "esse canal esta misturando nicho", "qual a estrutura de titulo dele", "analisa esse canal pra mim", "what niche is this channel", "title formula".
---

# Analise de nicho, mistura e estrutura de titulo

Dado um canal X — link, @handle, nome, link de um video dele, ou so uma lista
de titulos colada — entregar cinco coisas:

1. **Nicho**
2. **Subnicho**
3. **Microsubnicho**
4. **Esta misturando?** (em qual nivel, e se isso ajuda ou atrapalha)
5. **Estrutura de titulo** (formula reutilizavel)

Responda sempre em portugues do Brasil. Titulos do canal ficam no idioma
original, com traducao pt-BR ao lado quando nao forem em portugues.

Nao e uma analise de achismo: **classifique video por video e conte**. O
veredito de mistura sai dos numeros, nao da impressao geral.

## Passo 1 — coletar os videos

Use a primeira fonte que funcionar.

### A) O script (preferido)

```bash
python3 .claude/skills/analise-nicho-canal/scripts/analisar_canal.py coletar "<canal>" \
  --out /tmp/canal.md --json /tmp/canal.json
```

`<canal>` aceita: `https://youtube.com/@handle`, `https://youtube.com/channel/UC...`,
`@handle`, `UC...`, link de um video do canal, ou o nome do canal (nesse ultimo
caso ele busca e avisa qual escolheu — confirme que e o certo).

O script resolve o canal, le os uploads **do mais novo para o mais antigo**,
descarta tudo que tem menos de 180s (**Shorts nunca entram**) e devolve:
mais vistos, mais recentes, metricas de titulo (tamanho, % pergunta, % numero,
MAIUSCULA, parenteses, emoji, pessoa gramatical, gatilhos), vocabulario e
n-gramas repetidos, agrupamento por padrao de abertura, e a lista completa de
titulos com id e views para voce classificar.

Flags uteis:

| Flag | Padrao | Para que |
|---|---|---|
| `--alvo-longos` | 100 | para de paginar ao juntar N videos longos |
| `--max-pages` | 12 | teto de paginas de 50 uploads (12 = 600 uploads) |
| `--min-duration` | 180 | duracao minima em segundos (corte de Shorts) |
| `--top` / `--recentes` | 30 / 15 | tamanho das tabelas do relatorio |
| `--api-key` | — | chave explicita |

A quota e barata (uma coleta normal custa 6–15 unidades de 10.000/dia), ao
contrario da skill `canais-novos-virais`. Para varrer um canal grande inteiro,
suba `--alvo-longos 500 --max-pages 20` sem medo.

**Atencao ao aviso do relatorio:** se a leitura parou antes do fim do canal, os
"mais vistos" sao os mais vistos *do trecho lido*. Em canal antigo e grande,
rode de novo com `--alvo-longos` alto antes de falar de "video que mais bombou".

Chave da API: `--api-key`, ou `YOUTUBE_API_KEY` no ambiente, ou
`~/.youtube_api_key`. Se nao houver nenhuma, diga a ela para cadastrar
`YOUTUBE_API_KEY` nas variaveis de ambiente da sessao (menu do ambiente na
barra de titulo -> Edit) e que uma sessao nova passa a ver a chave.
**Nunca peca para colar a chave no chat.**

### B) vidIQ (se as ferramentas `mcp__vidIQ__*` estiverem disponiveis)

Carregue via ToolSearch e use `vidiq_channel_search` (achar),
`vidiq_channel_stats` (inscritos, data de criacao), `vidiq_channel_videos`
(videos). Serve como segunda fonte, e e o caminho quando nao ha chave da API.

### C) Titulos colados

Se ela colar os titulos, use direto — e avise no fim que a analise saiu so dos
titulos (sem views, a parte de performance e o "ajudando/atrapalhando" ficam de
fora).

Em qualquer caso: **separe mais vistos** (o que o algoritmo premiou) de
**mais recentes** (para onde o canal esta indo).

## Passo 2 — definir a hierarquia

Funil, do mais amplo ao mais especifico:

| Nivel | O que e | Pergunta-guia | Exemplo |
|---|---|---|---|
| **Nicho** | Grande area tematica | "Em que prateleira da livraria isso fica?" | Historia |
| **Subnicho** | Recorte dentro da area | "Qual pedaco dessa area?" | Idade Media europeia |
| **Microsubnicho** | Angulo + promessa + formato que separa ESTE canal dos vizinhos | "Por que alguem assiste este e nao outro do mesmo subnicho?" | O dia a dia brutal de pessoas comuns na Idade Media, narrado em 2a pessoa ("voce seria...") |

O erro mais comum e parar no subnicho e chamar isso de microsubnicho. O
microsubnicho so esta pronto quando a frase responde **quem assiste, que
promessa recebe e em que formato**. Para chegar nele, olhe:

- **Angulo** — cotidiano, bastidores, dinheiro, curiosidade proibida, ranking,
  comparacao, "e se...", mito desmentido
- **Publico** — pais/idioma, faixa de idade, nivel de conhecimento
- **Formato/narrativa** — 2a pessoa, lista, documentario, niveis, cronologia
- **Emocao dominante** — choque, nostalgia, medo, ganancia, curiosidade, indignacao
- **Recorte de tempo/lugar**

O relatorio do Passo 1 ja entrega as pistas de formato e emocao prontas
(pessoa gramatical, gatilhos, vocabulario recorrente). Use-as, nao chute.

## Passo 3 — medir a mistura

1. **Classifique cada video longo** em nicho / subnicho / microsubnicho. Grave
   um TSV (uma linha por video, tab entre as colunas):

```
VIDEO_ID<TAB>Nicho<TAB>Subnicho<TAB>Microsubnicho
```

   Os ids e titulos estao na secao "Todos os titulos longos" do relatorio e no
   JSON. Use **os mesmos rotulos** para videos do mesmo grupo — rotulo escrito
   de duas formas diferentes vira dois grupos e estraga a contagem.

2. Rode:

```bash
python3 .claude/skills/analise-nicho-canal/scripts/analisar_canal.py mistura \
  --dados /tmp/canal.json --classificacao /tmp/classif.tsv --out /tmp/mistura.md
```

   Ele devolve: distribuicao nos tres niveis (n, %, views medias e medianas por
   grupo), o veredito, a comparacao do micro dominante contra o resto, e antigo
   vs recente (pivo). `--foco 0.8` ajusta o limiar; `--janela-recente 0.3`
   ajusta o que conta como "fase recente".

3. Escala do veredito (o script aplica, voce interpreta):

| Situacao | Veredito | Leitura |
|---|---|---|
| >=80% no mesmo microsubnicho | **Focado** | O algoritmo sabe a quem recomendar. |
| Mesmo subnicho, micros variados | **Mistura de microsubnicho** | Geralmente saudavel: varia o angulo, mantem o publico. |
| Mesmo nicho, subnichos diferentes | **Mistura de subnicho** | Risco medio: publicos parecidos mas nao iguais. |
| Nichos diferentes | **Mistura de nicho** | Problema de identidade: publicos que nao se encontram. |

4. **Nao pare no rotulo.** Diga com numero se a mistura ajuda ou atrapalha
   ("os videos fora do micro principal fazem 0,4x as views do principal") e o
   que fazer: focar em qual micro, cortar qual subnicho, ou pivotar se o lado
   "de fora" performa melhor.

Se os dados forem so titulos sem views: faca a classificacao e a distribuicao
a mao, e diga que a parte de performance ficou de fora.

## Passo 4 — extrair a estrutura de titulo

O script conta padroes; a formula quem escreve e voce, lendo os titulos.

1. Agrupe os titulos por padrao parecido (a tabela "padroes de abertura" e os
   n-gramas repetidos sao o ponto de partida, nao a resposta).
2. Escreva cada formula com as variaveis entre colchetes:
   - `Por que [grupo] [fato surpreendente]?`
   - `A vida de um(a) [profissao] em [epoca/lugar]`
   - `[Numero] [coisas] que [grupo] fazia e hoje seria [proibido]`
   - `O que acontecia se voce [acao] em [epoca]`
3. Para cada formula: quantos titulos seguem, views medias, 2–3 exemplos reais.
4. Aponte a **formula campea** (maiores views medias, nao a mais frequente) e
   diga quantos videos a sustentam — campea apoiada em 2 videos e palpite.
5. Liste os elementos recorrentes com os numeros do relatorio: tamanho medio,
   pessoa gramatical, pergunta, numero, MAIUSCULA (e quantas palavras por titulo), hashtag, parenteses, dois-pontos,
   emoji, gatilhos, palavras que se repetem.
6. Se o canal mistura, diga se **a estrutura de titulo tambem muda** entre os
   grupos — muitas vezes o titulo e o que esta denunciando a mistura.

## Passo 5 — formato da entrega

```
## Canal: [nome] | [inscritos] | [n videos longos lidos] | criado em [data] | idioma

### Nicho
[1 linha]

### Subnicho
[1 linha]

### Microsubnicho
[1-2 linhas: angulo + publico + formato + emocao]

### Esta misturando?
**Veredito:** [Focado / Mistura de microsubnicho / Mistura de subnicho / Mistura de nicho]

| Grupo (nicho > subnicho > micro) | % dos videos | Views medias |
|---|---|---|

- Antigo vs recente: [mudou de linha? para onde?]
- A mistura esta [ajudando / neutra / atrapalhando] porque [numero].
- Recomendacao: [1-2 linhas]

### Estrutura de titulo
**Formula campea:** `...`
- Exemplos: "..." (X views) / "..." (Y views)

**Outras formulas:** 1. `...` | N titulos, media X views | ex.: "..."

**Padroes gerais:** tamanho, pessoa gramatical, gatilhos, palavras recorrentes.

### Como replicar (so se ela pedir)
3 titulos novos na formula campea.
```

## Cuidados

- Nicho, subnicho e microsubnicho em **uma linha cada**, sem enrolacao. A
  analise longa vem depois.
- **Nunca invente views.** Sem dados, diga que a analise saiu so dos titulos.
- Canal com menos de ~8 videos longos: faca a analise, mas avise que o padrao e
  o veredito de mistura ainda sao pouco confiaveis.
- Nao leia a tabela inteira em voz alta. Comente o que muda a decisao dela.
- Shorts nunca entram na conta. Se o canal e majoritariamente Shorts, diga isso
  — e um fato sobre o canal, nao uma falha da coleta.
