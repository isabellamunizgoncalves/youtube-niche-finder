---
name: canais-novos-virais
description: Encontra canais RECEM-CRIADOS no YouTube com MUITAS views e POUCOS inscritos, em qualquer nicho e qualquer idioma, considerando apenas videos LONGOS (nunca Shorts). Use quando a pessoa pedir para achar canais novos bombando, canais pequenos virais, outliers, canais subindo rapido, oportunidades de nicho, "canal novo com muitas views", "pouco inscrito muita view", "find new channels with many views few subscribers", "small channel outliers". Usa a YouTube Data API v3 com a chave YOUTUBE_API_KEY.
---

# Canais novos e virais (poucos inscritos, muitas views)

Acha canais que acabaram de nascer e ja estao estourando: muita view, quase
nenhum inscrito, so video longo. Serve para descobrir formatos que estao
funcionando antes de o nicho encher.

## Antes de tudo: a chave da API

O script le a chave nesta ordem:

1. `--api-key SUA_CHAVE`
2. variavel de ambiente `YOUTUBE_API_KEY`
3. arquivo `~/.youtube_api_key`

Se nenhuma existir, ele para e avisa. Nesse caso, diga a pessoa que ela precisa
cadastrar `YOUTUBE_API_KEY` nas configuracoes do ambiente (menu do ambiente na
barra de titulo da sessao -> Edit -> variaveis de ambiente) e que uma sessao
nova passa a enxergar a chave. **Nunca peca para ela colar a chave no chat.**

## Como rodar

Caminho do script (a partir da raiz do repositorio):
`.claude/skills/canais-novos-virais/scripts/find_outliers.py`

### Passo 1 — traduza o nicho em buscas

A pessoa diz o nicho em uma frase. Voce gera de **3 a 6 variacoes de busca**,
no idioma alvo. Varie o angulo, nao sinonimos obvios:

- termo principal do nicho
- formato ("documentario", "compilacao", "historia completa", "explicado")
- gatilho emocional / gancho tipico do nicho
- termo de cauda longa que so quem e do nicho usaria

Exemplo, nicho "casas abandonadas" em portugues:
`-q "mansao abandonada"` `-q "explorando casa abandonada"`
`-q "o que encontrei em uma casa abandonada"` `-q "lugar abandonado documentario"`

Para "qualquer idioma": repita a rodada com `--lang` e `--region` diferentes
(pt/BR, en/US, es/MX, fr/FR, hi/IN...), uma rodada por vez por causa da quota.
Sem `--lang` e sem `--region` a busca sai global.

### Passo 2 — rode

```bash
python3 .claude/skills/canais-novos-virais/scripts/find_outliers.py \
  --niche "casas abandonadas" \
  -q "mansao abandonada" -q "explorando casa abandonada" \
  -q "lugar abandonado documentario" \
  --lang pt --region BR \
  --channel-max-age-days 365 \
  --max-subs 5000 \
  --min-video-views 50000 \
  --min-duration 240 \
  --video-days 120 \
  --out /tmp/relatorio.md
```

### Passo 3 — leia o relatorio para a pessoa

O script ja devolve markdown pronto. Nao repita a tabela inteira: comente os
**3 a 5 canais mais interessantes**, dizendo em uma linha por que cada um e um
outlier (idade do canal x views, razao views/inscrito, qual video puxou) e o
que o formato tem em comum. Depois ofereca a proxima rodada (outro idioma,
filtros mais frouxos, ou aprofundar um canal).

## Filtros (todos opcionais, com padrao)

| Flag | Padrao | O que faz |
|---|---|---|
| `--channel-max-age-days` | 365 | idade maxima do canal em dias |
| `--max-subs` | 5000 | teto de inscritos |
| `--min-subs` | 0 | piso de inscritos |
| `--min-video-views` | 50000 | views minimas de um video |
| `--min-channel-views` | 0 | views totais minimas do canal |
| `--min-duration` | 240 | duracao minima em segundos (corta Shorts) |
| `--video-days` | 120 | so videos publicados nos ultimos N dias |
| `--durations` | medium,long | `medium` 4-20min, `long` >20min |
| `--order` | viewCount | viewCount / relevance / date / rating |
| `--pages` | 1 | paginas por busca (cada pagina = 100 unidades) |
| `--max-searches` | 10 | teto de chamadas de busca (controle de quota) |
| `--sort` | score | score / views_dia / views_por_inscrito / melhor_video / mais_novo |
| `--limit` | 0 | canais no relatorio; 0 = todos os que passarem nos filtros |
| `--exclude-file` | — | arquivo com channelIds para ignorar |
| `--json` | — | salva o resultado bruto |
| `--out` | — | salva o relatorio markdown |

## Como Shorts sao excluidos

Duas camadas: a busca ja pede so `medium` (4-20 min) e `long` (>20 min), e
depois o script le a duracao real de cada video e descarta qualquer coisa
abaixo de `--min-duration`. Shorts nao passam.

## Quota — importante

A cota padrao e **10.000 unidades por dia**, e zera a meia-noite do horario do
Pacifico.

- `search.list` = **100 unidades** por chamada (o caro)
- `videos.list` = 1 unidade por lote de 50
- `channels.list` = 1 unidade por lote de 50

Uma rodada com 4 buscas x 2 duracoes = 8 buscas = **800 unidades**. Da para
~12 rodadas por dia. O script imprime quanto gastou ao final e para com aviso
claro se a quota acabar.

Regras praticas:
- comece com 3-4 `-q`, nunca 10 de uma vez
- so aumente `--pages` se a primeira rodada vier pobre
- se a pessoa quiser varios idiomas, avise do custo e faca um idioma por vez

## Se vier vazio

Afrouxe nesta ordem, uma coisa por vez:
1. `--min-video-views` para baixo (ex.: 20000)
2. `--max-subs` para cima (ex.: 20000)
3. `--channel-max-age-days` para cima (ex.: 730)
4. `--video-days` para cima (ex.: 365)
5. buscas diferentes — quase sempre o problema e a palavra-chave, nao o filtro

## Metricas do relatorio

- **views_por_inscrito** — views totais / inscritos. Acima de ~100x e
  desproporcao real (gente assiste e nao se inscreve = formato pega no
  algoritmo mas nao fideliza ainda).
- **views_por_dia** — views totais / idade do canal. Velocidade bruta.
- **score** — combina velocidade, desproporcao e frescor do canal. Use para
  ordenar; use as outras para explicar.
- **inscritos: oculto** — o dono escondeu a contagem. O canal entra mesmo
  assim, mas a razao views/inscrito fica em branco.
