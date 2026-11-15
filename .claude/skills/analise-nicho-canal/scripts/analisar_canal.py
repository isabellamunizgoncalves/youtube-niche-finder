#!/usr/bin/env python3
"""
Coleta e analisa um canal do YouTube para diagnostico de nicho.

Dois modos:

  coletar   resolve o canal (link, @handle, UC id ou nome), baixa os videos
            LONGOS (nunca Shorts), e devolve um relatorio markdown + um JSON
            com todos os titulos, views, datas e as metricas de titulo
            (tamanho, pergunta, numero, maiuscula, gatilhos, n-gramas,
            agrupamento por padrao de abertura).

  mistura   recebe a classificacao que o agente escreveu (nicho / subnicho /
            microsubnicho por video) e calcula a distribuicao, as views medias
            de cada grupo, antigo vs recente e o veredito de mistura.

Chave da API (modo coletar), nesta ordem:
  1. --api-key
  2. variavel de ambiente YOUTUBE_API_KEY
  3. arquivo ~/.youtube_api_key

Custo de quota (cota diaria padrao = 10.000 unidades):
  channels.list      = 1 unidade
  playlistItems.list = 1 unidade por pagina de 50
  videos.list        = 1 unidade por lote de 50
  search.list        = 100 unidades (so quando o canal e achado por nome)
Uma coleta normal custa entre 6 e 12 unidades. E barato.
"""

import argparse
import csv
import json
import os
import re
import sys
import time
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from statistics import median

try:
    import requests
except ImportError:  # pragma: no cover
    sys.exit("ERRO: instale a dependencia -> pip install requests")

API = "https://www.googleapis.com/youtube/v3"

ISO_DUR = re.compile(
    r"^P(?:(?P<days>\d+)D)?T?(?:(?P<h>\d+)H)?(?:(?P<m>\d+)M)?(?:(?P<s>\d+)S)?$"
)


def iso_duration_to_seconds(value):
    if not value:
        return None
    m = ISO_DUR.match(value)
    if not m:
        return None
    d = m.groupdict()
    return (
        int(d["days"] or 0) * 86400
        + int(d["h"] or 0) * 3600
        + int(d["m"] or 0) * 60
        + int(d["s"] or 0)
    )


def hhmmss(seconds):
    if seconds is None:
        return "?"
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def parse_ts(value):
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def human(n):
    if n is None:
        return "?"
    n = float(n)
    for limit, suf in ((1e9, "B"), (1e6, "M"), (1e3, "k")):
        if abs(n) >= limit:
            return f"{n / limit:.1f}{suf}".replace(".0", "")
    return str(int(n))


def chunks(seq, size):
    seq = list(seq)
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


# ---------------------------------------------------------------- cliente API


class Youtube:
    def __init__(self, api_key):
        self.key = api_key
        self.units = 0
        self.session = requests.Session()

    def _get(self, endpoint, params, cost):
        params = dict(params)
        params["key"] = self.key
        for attempt in range(4):
            try:
                r = self.session.get(f"{API}/{endpoint}", params=params, timeout=30)
            except requests.RequestException:
                if attempt == 3:
                    raise SystemExit("ERRO: falha de rede apos varias tentativas.")
                time.sleep(2 ** attempt)
                continue
            self.units += cost
            if r.status_code == 200:
                return r.json()
            try:
                err = r.json()["error"]
                reason = err.get("errors", [{}])[0].get("reason", "")
                msg = err.get("message", "")
            except Exception:
                reason, msg = "", r.text[:300]
            if reason in ("quotaExceeded", "dailyLimitExceeded"):
                raise SystemExit(
                    "\nQUOTA ESGOTADA: a cota diaria da chave acabou. "
                    "Ela zera a meia-noite no horario do Pacifico (PT).\n"
                    f"Unidades gastas nesta execucao: {self.units}"
                )
            if r.status_code in (400, 401, 403):
                raise SystemExit(
                    f"\nERRO DA API ({r.status_code} / {reason}): {msg}\n"
                    "Confira se a chave e valida e se a 'YouTube Data API v3' "
                    "esta ativada no projeto do Google Cloud."
                )
            if r.status_code >= 500 and attempt < 3:
                time.sleep(2 ** attempt)
                continue
            raise SystemExit(f"ERRO HTTP {r.status_code}: {msg}")
        raise SystemExit("ERRO: falha de rede apos varias tentativas.")

    def channel_by_id(self, channel_id):
        data = self._get(
            "channels",
            {"part": "snippet,statistics,contentDetails,brandingSettings",
             "id": channel_id},
            cost=1,
        )
        items = data.get("items") or []
        return items[0] if items else None

    def channel_by_handle(self, handle):
        data = self._get(
            "channels",
            {"part": "snippet,statistics,contentDetails,brandingSettings",
             "forHandle": handle.lstrip("@")},
            cost=1,
        )
        items = data.get("items") or []
        return items[0] if items else None

    def channel_by_username(self, name):
        data = self._get(
            "channels",
            {"part": "snippet,statistics,contentDetails,brandingSettings",
             "forUsername": name},
            cost=1,
        )
        items = data.get("items") or []
        return items[0] if items else None

    def search_channel(self, query):
        data = self._get(
            "search",
            {"part": "snippet", "q": query, "type": "channel", "maxResults": 5},
            cost=100,
        )
        return [
            {
                "id": it.get("id", {}).get("channelId"),
                "title": it.get("snippet", {}).get("channelTitle")
                or it.get("snippet", {}).get("title"),
            }
            for it in data.get("items", [])
            if it.get("id", {}).get("channelId")
        ]

    def channel_of_video(self, video_id):
        data = self._get("videos", {"part": "snippet", "id": video_id}, cost=1)
        items = data.get("items") or []
        return items[0]["snippet"]["channelId"] if items else None

    def playlist_pages(self, playlist_id, max_pages):
        """Gera listas de ate 50 videoIds, da mais nova para a mais antiga."""
        token = None
        for _ in range(max(1, max_pages)):
            params = {
                "part": "contentDetails",
                "playlistId": playlist_id,
                "maxResults": 50,
            }
            if token:
                params["pageToken"] = token
            data = self._get("playlistItems", params, cost=1)
            ids = [
                it["contentDetails"]["videoId"]
                for it in data.get("items", [])
                if it.get("contentDetails", {}).get("videoId")
            ]
            if ids:
                yield ids
            token = data.get("nextPageToken")
            if not token:
                break

    def videos(self, video_ids):
        out = {}
        for batch in chunks(video_ids, 50):
            data = self._get(
                "videos",
                {
                    "part": "snippet,statistics,contentDetails",
                    "id": ",".join(batch),
                },
                cost=1,
            )
            for it in data.get("items", []):
                out[it["id"]] = it
        return out


# ------------------------------------------------------- resolucao da entrada


URL_PATTERNS = [
    (re.compile(r"youtube\.com/channel/(UC[\w-]{20,})", re.I), "id"),
    (re.compile(r"youtube\.com/(?:@)([\w.\-]+)", re.I), "handle"),
    (re.compile(r"youtube\.com/c/([\w.\-]+)", re.I), "legacy"),
    (re.compile(r"youtube\.com/user/([\w.\-]+)", re.I), "user"),
    (re.compile(r"(?:youtube\.com/watch\?v=|youtu\.be/)([\w-]{11})", re.I), "video"),
    (re.compile(r"youtube\.com/shorts/([\w-]{11})", re.I), "video"),
]


def resolve_channel(yt, alvo):
    alvo = alvo.strip()
    kind, value = None, None
    for rx, k in URL_PATTERNS:
        m = rx.search(alvo)
        if m:
            kind, value = k, m.group(1)
            break
    if kind is None:
        if re.fullmatch(r"UC[\w-]{20,}", alvo):
            kind, value = "id", alvo
        elif alvo.startswith("@"):
            kind, value = "handle", alvo
        else:
            kind, value = "nome", alvo

    if kind == "id":
        ch = yt.channel_by_id(value)
        if ch:
            return ch
    if kind == "video":
        cid = yt.channel_of_video(value)
        if cid:
            ch = yt.channel_by_id(cid)
            if ch:
                return ch
    if kind in ("handle", "legacy", "user", "nome"):
        ch = yt.channel_by_handle(value)
        if ch:
            return ch
        if kind in ("user", "legacy"):
            ch = yt.channel_by_username(value)
            if ch:
                return ch
        hits = yt.search_channel(value)
        if hits:
            ch = yt.channel_by_id(hits[0]["id"])
            if ch:
                if len(hits) > 1:
                    outros = ", ".join(h["title"] for h in hits[1:4])
                    print(
                        f"AVISO: achei o canal por busca por nome. Usei "
                        f"'{ch['snippet']['title']}'. Outros parecidos: {outros}",
                        file=sys.stderr,
                    )
                return ch
    raise SystemExit(
        f"ERRO: nao consegui achar o canal a partir de '{alvo}'. "
        "Tente o link completo do canal ou o @handle exato."
    )


# ---------------------------------------------------- analise textual, titulos

STOPWORDS = set(
    """
a o as os um uma uns umas de do da dos das em no na nos nas por para com sem
sobre entre ao aos à às e ou mas que se como quando onde qual quais quem mais
menos muito muita muitos muitas todo toda todos todas este esta estes estas
esse essa esses essas isso aquilo seu sua seus suas meu minha nosso nossa é
são foi era ser tem têm ter foi vai vão já não sim lhe ele ela eles elas eu
você vocês nós me te nem só até depois antes então pelo pela pelos pelas
the a an of in on at to for with without about from by and or but that this
these those is are was were be been being has have had will would can could
you your my our their his her its it he she they we i as if then than so
what which who when where how why do does did not no yes more most less very
el la los las un una unos unas de del en por para con sin sobre entre y o
pero que si como cuando donde quien mas menos muy todo todos esta este eso su
le les la de du des un une dans sur avec sans pour par et ou mais que si
comme quand ou qui plus moins tres tout tous cette ce ces son ses leur
re ve ll don doesn isn didn wasn won aren hasn haven couldn shouldn wouldn
""".split()
)

GATILHOS = {
    "segredo": ["segredo", "secreto", "secret", "oculto", "hidden", "secreto"],
    "proibido": ["proibido", "proibida", "banned", "forbidden", "ilegal", "censurado"],
    "ninguem_conta": ["ninguém", "ninguem", "nobody", "no one", "nadie", "personne"],
    "choque": ["chocante", "assustador", "brutal", "horrível", "horrivel", "shocking",
               "insane", "crazy", "louco", "bizarro", "terrível", "terrivel"],
    "morte": ["morte", "morreu", "morrer", "death", "died", "kill", "matou",
              "execução", "execucao", "muerte"],
    "dinheiro": ["dinheiro", "milhões", "milhoes", "money", "rich", "rico",
                 "fortuna", "salário", "salario", "custava", "preço", "preco", "$"],
    "nostalgia": ["anos", "antigamente", "antiga", "antigo", "era", "época",
                  "epoca", "nostalgia", "retro", "1950", "1960", "1970", "1980",
                  "1990"],
    "verdade": ["verdade", "verdadeira", "real", "truth", "realidade", "mentira"],
    "superlativo": ["mais", "maior", "pior", "melhor", "único", "unico", "jamais",
                    "nunca", "sempre", "most", "worst", "best", "ever", "never"],
    "voce_no_lugar": ["você", "voce", "se você", "you were", "if you"],
}


def norm(txt):
    txt = unicodedata.normalize("NFKD", txt.lower())
    return "".join(c for c in txt if not unicodedata.combining(c))


def tokens(title):
    palavras = re.findall(r"[^\W\d_]{2,}", title.lower(), flags=re.UNICODE)
    return [p for p in palavras if norm(p) not in STOPWORDS and p not in STOPWORDS]


def ngrams(words, n):
    return [" ".join(words[i : i + n]) for i in range(len(words) - n + 1)]


EMOJI = re.compile(
    "[" "\U0001F300-\U0001FAFF" "\U00002600-\U000027BF" "\U0001F000-\U0001F2FF" "]"
)


def title_features(title):
    palavras_brutas = re.findall(r"\S+", title)
    caps = [
        w
        for w in palavras_brutas
        if len(re.sub(r"\W", "", w)) >= 3 and re.sub(r"\W", "", w).isupper()
    ]
    sem_sinais = [w for w in palavras_brutas if len(re.sub(r"\W", "", w)) >= 3]
    return {
        "chars": len(title),
        "palavras": len(palavras_brutas),
        "pergunta": "?" in title,
        "numero": bool(re.search(r"\d", title)),
        "maiuscula": bool(caps),
        "caps_palavras": len(caps),
        "tudo_maiusculo": bool(sem_sinais) and len(caps) == len(sem_sinais),
        "hashtag": bool(re.search(r"#\w", title)),
        "parenteses": bool(re.search(r"[\(\[]", title)),
        "dois_pontos": ":" in title,
        "pipe": "|" in title,
        "emoji": bool(EMOJI.search(title)),
        "reticencias": "..." in title or "…" in title,
        "gatilhos": sorted(
            g
            for g, termos in GATILHOS.items()
            if any(t in norm(title) for t in (norm(x) for x in termos))
        ),
    }


PESSOA = {
    "2a_pessoa": ["voce", "vocês", "voces", "teu", "tua", "seu", "sua", "you",
                  "your", "tu", "ti", "vous", "votre", "tus"],
    "1a_pessoa": ["eu", "meu", "minha", "nos", "nosso", "i ", "my", "we ",
                  "our", "je ", "mon", "ma "],
}


def pessoa_gramatical(title):
    n = " " + norm(title) + " "
    achados = []
    for pessoa, marcas in PESSOA.items():
        if any(f" {norm(m).strip()} " in n for m in marcas):
            achados.append(pessoa)
    return achados or ["impessoal"]


def agrupar_por_abertura(videos, min_grupo=2, n_palavras=2):
    """Agrupa titulos pelas primeiras N palavras significativas (padrao de abertura)."""
    grupos = defaultdict(list)
    for v in videos:
        pal = re.findall(r"[^\W_]+", v["titulo"].lower(), flags=re.UNICODE)
        chave = " ".join(pal[:n_palavras]) if pal else "(vazio)"
        grupos[chave].append(v)
    return {k: v for k, v in grupos.items() if len(v) >= min_grupo}


def stats_views(videos):
    vs = [v["views"] for v in videos if v["views"] is not None]
    if not vs:
        return {"n": len(videos), "media": None, "mediana": None,
                "min": None, "max": None}
    return {
        "n": len(videos),
        "media": sum(vs) / len(vs),
        "mediana": median(vs),
        "min": min(vs),
        "max": max(vs),
    }


# ----------------------------------------------------------------- modo coleta


def _video_row(vid, item, dur):
    s = item.get("snippet", {})
    st = item.get("statistics", {})
    pub = parse_ts(s.get("publishedAt"))
    return {
        "id": vid,
        "titulo": s.get("title", ""),
        "publicado_em": s.get("publishedAt"),
        "idade_dias": (datetime.now(timezone.utc) - pub).days if pub else None,
        "duracao_s": dur,
        "duracao": hhmmss(dur),
        "views": int(st["viewCount"]) if "viewCount" in st else None,
        "likes": int(st["likeCount"]) if "likeCount" in st else None,
        "comentarios": int(st["commentCount"]) if "commentCount" in st else None,
        "tags": s.get("tags", [])[:15],
        "idioma": s.get("defaultAudioLanguage") or s.get("defaultLanguage"),
        "features": None,
        "pessoa": None,
    }


def coletar(args):
    api_key = (
        args.api_key
        or os.environ.get("YOUTUBE_API_KEY")
        or _key_from_file()
    )
    if not api_key:
        raise SystemExit(
            "ERRO: nenhuma chave da YouTube Data API encontrada.\n"
            "Defina YOUTUBE_API_KEY nas variaveis de ambiente da sessao, "
            "ou passe --api-key, ou grave a chave em ~/.youtube_api_key.\n"
            "Nunca cole a chave no chat."
        )
    yt = Youtube(api_key)
    ch = resolve_channel(yt, args.canal)

    snip = ch.get("snippet", {})
    stat = ch.get("statistics", {})
    uploads = ch["contentDetails"]["relatedPlaylists"]["uploads"]

    canal = {
        "id": ch["id"],
        "nome": snip.get("title"),
        "handle": snip.get("customUrl"),
        "descricao": (snip.get("description") or "").strip(),
        "pais": snip.get("country"),
        "idioma_default": snip.get("defaultLanguage")
        or ch.get("brandingSettings", {}).get("channel", {}).get("defaultLanguage"),
        "criado_em": snip.get("publishedAt"),
        "inscritos": None if stat.get("hiddenSubscriberCount") else
        int(stat.get("subscriberCount", 0) or 0),
        "inscritos_ocultos": bool(stat.get("hiddenSubscriberCount")),
        "views_totais": int(stat.get("viewCount", 0) or 0),
        "total_videos": int(stat.get("videoCount", 0) or 0),
        "url": f"https://www.youtube.com/channel/{ch['id']}",
    }

    longos, shorts, lidos, paginas = [], 0, 0, 0
    for pagina in yt.playlist_pages(uploads, args.max_pages):
        paginas += 1
        lidos += len(pagina)
        detalhes = yt.videos(pagina)
        for vid in pagina:
            it = detalhes.get(vid)
            if not it:
                continue
            dur = iso_duration_to_seconds(
                it.get("contentDetails", {}).get("duration")
            )
            if dur is None or dur < args.min_duration:
                shorts += 1
                continue
            longos.append(_video_row(vid, it, dur))
        if len(longos) >= args.alvo_longos:
            break

    ids = [v["id"] for v in longos]

    for v in longos:
        v["features"] = title_features(v["titulo"])
        v["pessoa"] = pessoa_gramatical(v["titulo"])

    por_views = sorted(
        [v for v in longos if v["views"] is not None],
        key=lambda v: v["views"],
        reverse=True,
    )
    por_data = sorted(longos, key=lambda v: v["publicado_em"] or "", reverse=True)

    med = median([v["views"] for v in por_views]) if por_views else 0
    for v in longos:
        v["indice_vs_mediana"] = (
            round(v["views"] / med, 2) if med and v["views"] is not None else None
        )

    todos_tokens = []
    for v in longos:
        todos_tokens.extend(tokens(v["titulo"]))
    bi, tri = Counter(), Counter()
    for v in longos:
        w = tokens(v["titulo"])
        bi.update(ngrams(w, 2))
        tri.update(ngrams(w, 3))

    grupos_abertura = agrupar_por_abertura(longos, min_grupo=args.min_grupo)

    gat = Counter()
    for v in longos:
        gat.update(v["features"]["gatilhos"])
    pes = Counter()
    for v in longos:
        pes.update(v["pessoa"])

    resultado = {
        "canal": canal,
        "coleta": {
            "videos_lidos": lidos,
            "paginas_lidas": paginas,
            "longos": len(longos),
            "descartados_curtos": shorts,
            "min_duration_s": args.min_duration,
            "quota_gasta": yt.units,
            "gerado_em": datetime.now(timezone.utc).isoformat(),
        },
        "videos": longos,
        "titulos_metricas": _metricas_titulos(longos),
        "ngramas": {
            "palavras": todos_tokens and Counter(todos_tokens).most_common(25) or [],
            "bigramas": bi.most_common(20),
            "trigramas": tri.most_common(15),
        },
        "gatilhos": gat.most_common(),
        "pessoa": pes.most_common(),
        "grupos_abertura": {
            k: {"n": len(v), **stats_views(v),
                "exemplos": [x["titulo"] for x in sorted(
                    v, key=lambda y: y["views"] or 0, reverse=True)[:3]]}
            for k, v in sorted(
                grupos_abertura.items(), key=lambda kv: -len(kv[1])
            )
        },
        "top_views": [v["id"] for v in por_views[: args.top]],
        "recentes": [v["id"] for v in por_data[: args.recentes]],
    }

    md = relatorio_coleta(resultado, args)
    _escrever(args, md, resultado)
    return resultado


def _key_from_file():
    caminho = os.path.expanduser("~/.youtube_api_key")
    if os.path.exists(caminho):
        with open(caminho) as fh:
            return fh.read().strip()
    return None


def _metricas_titulos(videos):
    if not videos:
        return {}
    n = len(videos)
    chars = [v["features"]["chars"] for v in videos]
    palavras = [v["features"]["palavras"] for v in videos]

    def pct(campo):
        return round(
            100 * sum(1 for v in videos if v["features"][campo]) / n, 1
        )

    return {
        "n": n,
        "chars_media": round(sum(chars) / n, 1),
        "chars_min": min(chars),
        "chars_max": max(chars),
        "palavras_media": round(sum(palavras) / n, 1),
        "pct_pergunta": pct("pergunta"),
        "pct_numero": pct("numero"),
        "pct_maiuscula": pct("maiuscula"),
        "pct_tudo_maiusculo": pct("tudo_maiusculo"),
        "pct_hashtag": pct("hashtag"),
        "caps_palavras_media": round(
            sum(v["features"]["caps_palavras"] for v in videos) / n, 1
        ),
        "pct_parenteses": pct("parenteses"),
        "pct_dois_pontos": pct("dois_pontos"),
        "pct_pipe": pct("pipe"),
        "pct_emoji": pct("emoji"),
        "pct_reticencias": pct("reticencias"),
    }


def _escrever(args, md, resultado):
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(md)
        print(f"relatorio markdown -> {args.out}", file=sys.stderr)
    else:
        print(md)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(resultado, fh, ensure_ascii=False, indent=2)
        print(f"json bruto -> {args.json}", file=sys.stderr)


def relatorio_coleta(r, args):
    c = r["canal"]
    col = r["coleta"]
    vids = {v["id"]: v for v in r["videos"]}
    L = []
    A = L.append
    A(f"# {c['nome']}  ({c['handle'] or c['id']})")
    A("")
    insc = "oculto" if c["inscritos_ocultos"] else human(c["inscritos"])
    A(
        f"- inscritos: **{insc}** | views totais: **{human(c['views_totais'])}** "
        f"| videos no canal: **{c['total_videos']}**"
    )
    A(f"- criado em: {(c['criado_em'] or '?')[:10]} | pais: {c['pais'] or '?'} "
      f"| idioma: {c['idioma_default'] or '?'}")
    A(f"- url: {c['url']}")
    A(
        f"- coleta: **{col['longos']} videos longos** de {col['videos_lidos']} "
        f"uploads lidos ({col['descartados_curtos']} descartados por duracao < "
        f"{col['min_duration_s']}s) | quota gasta: {col['quota_gasta']} unidades"
    )
    if col["longos"] < c["total_videos"] - col["descartados_curtos"]:
        A(
            "- ATENCAO: a leitura comeca pelos uploads MAIS NOVOS e parou antes "
            "do fim do canal. Os 'mais vistos' abaixo sao os mais vistos **do "
            "trecho lido**, nao de toda a historia do canal. Para varrer tudo, "
            "aumente --alvo-longos e --max-pages."
        )
    if c["descricao"]:
        desc = c["descricao"].replace("\n", " ")[:400]
        A("")
        A(f"**Descricao do canal:** {desc}")

    if not r["videos"]:
        A("")
        A("**Nenhum video longo encontrado.** Canal so de Shorts, ou vazio.")
        return "\n".join(L)

    A("")
    A(f"## {min(args.top, len(r['top_views']))} mais vistos (video longo)")
    A("")
    A("| # | views | x mediana | data | dur | titulo |")
    A("|---|---|---|---|---|---|")
    for i, vid in enumerate(r["top_views"], 1):
        v = vids[vid]
        A(
            f"| {i} | {human(v['views'])} | {v['indice_vs_mediana'] or '?'}x "
            f"| {(v['publicado_em'] or '?')[:10]} | {v['duracao']} "
            f"| {v['titulo'].replace('|', '/')} |"
        )

    A("")
    A(f"## {min(args.recentes, len(r['recentes']))} mais recentes")
    A("")
    A("| data | views | x mediana | dur | titulo |")
    A("|---|---|---|---|---|")
    for vid in r["recentes"]:
        v = vids[vid]
        A(
            f"| {(v['publicado_em'] or '?')[:10]} | {human(v['views'])} "
            f"| {v['indice_vs_mediana'] or '?'}x | {v['duracao']} "
            f"| {v['titulo'].replace('|', '/')} |"
        )

    m = r["titulos_metricas"]
    A("")
    A("## Metricas dos titulos")
    A("")
    A(f"- tamanho: media {m['chars_media']} caracteres "
      f"({m['chars_min']}-{m['chars_max']}), {m['palavras_media']} palavras")
    A(f"- pergunta: {m['pct_pergunta']}% | numero: {m['pct_numero']}% "
      f"| hashtag: {m['pct_hashtag']}%")
    A(f"- MAIUSCULA: {m['pct_maiuscula']}% dos titulos tem alguma palavra toda "
      f"em caixa alta (media {m['caps_palavras_media']} por titulo); "
      f"{m['pct_tudo_maiusculo']}% tem o titulo INTEIRO em caixa alta")
    A(f"- parenteses/colchetes: {m['pct_parenteses']}% | dois-pontos: "
      f"{m['pct_dois_pontos']}% | pipe: {m['pct_pipe']}% | emoji: {m['pct_emoji']}%"
      f" | reticencias: {m['pct_reticencias']}%")
    A(f"- pessoa gramatical: "
      + ", ".join(f"{k} {v}x" for k, v in r["pessoa"]))
    if r["gatilhos"]:
        A(f"- gatilhos detectados: "
          + ", ".join(f"{k} {v}x" for k, v in r["gatilhos"]))

    A("")
    A("## Vocabulario recorrente")
    A("")
    A("- palavras: " + ", ".join(f"{w} ({n})" for w, n in r["ngramas"]["palavras"][:20]))
    bi = [f"{w} ({n})" for w, n in r["ngramas"]["bigramas"][:12] if n > 1]
    tri = [f"{w} ({n})" for w, n in r["ngramas"]["trigramas"][:10] if n > 1]
    if bi:
        A("- bigramas repetidos: " + ", ".join(bi))
    if tri:
        A("- trigramas repetidos: " + ", ".join(tri))
    if not bi and not tri:
        A("- nenhum bigrama/trigrama se repete: os titulos nao reaproveitam "
          "blocos de texto prontos (formula mais solta, no estilo frase unica).")

    if r["grupos_abertura"]:
        A("")
        A("## Padroes de abertura (mesmas primeiras palavras)")
        A("")
        A("| abertura | n | views medias | exemplo |")
        A("|---|---|---|---|")
        for k, g in list(r["grupos_abertura"].items())[:15]:
            A(
                f"| {k} | {g['n']} | {human(g['media'])} "
                f"| {(g['exemplos'][0] if g['exemplos'] else '').replace('|','/')} |"
            )
        A("")
        A("> Agrupamento mecanico, so pelas primeiras palavras. A formula de "
          "titulo de verdade voce escreve lendo os titulos; isso aqui e so pista.")

    A("")
    A("## Todos os titulos longos (para classificar)")
    A("")
    A("| id | data | views | titulo |")
    A("|---|---|---|---|")
    for v in sorted(r["videos"], key=lambda x: x["views"] or 0, reverse=True):
        A(
            f"| {v['id']} | {(v['publicado_em'] or '?')[:10]} "
            f"| {v['views'] if v['views'] is not None else '?'} "
            f"| {v['titulo'].replace('|', '/')} |"
        )
    return "\n".join(L)


# --------------------------------------------------------------- modo mistura


def _ler_classificacao(caminho):
    """Aceita TSV/CSV (id<TAB>nicho<TAB>subnicho<TAB>micro) ou JSON."""
    if caminho.lower().endswith(".json"):
        with open(caminho, encoding="utf-8") as fh:
            data = json.load(fh)
        linhas = data["videos"] if isinstance(data, dict) else data
        return [
            {
                "id": l.get("id") or l.get("video_id"),
                "nicho": (l.get("nicho") or "").strip(),
                "subnicho": (l.get("subnicho") or "").strip(),
                "micro": (l.get("micro") or l.get("microsubnicho") or "").strip(),
            }
            for l in linhas
        ]
    with open(caminho, encoding="utf-8", newline="") as fh:
        amostra = fh.read(4096)
        fh.seek(0)
        delim = "\t" if "\t" in amostra.splitlines()[0] else ","
        out = []
        for row in csv.reader(fh, delimiter=delim):
            row = [c.strip() for c in row]
            if len(row) < 4 or not row[0] or row[0].lower() in ("id", "video_id"):
                continue
            out.append(
                {"id": row[0], "nicho": row[1], "subnicho": row[2], "micro": row[3]}
            )
        return out


def mistura(args):
    with open(args.dados, encoding="utf-8") as fh:
        coleta = json.load(fh)
    vids = {v["id"]: v for v in coleta["videos"]}
    classif = _ler_classificacao(args.classificacao)

    faltando = [c["id"] for c in classif if c["id"] not in vids]
    nao_classificados = [v for v in vids if v not in {c["id"] for c in classif}]

    itens = []
    for c in classif:
        v = vids.get(c["id"])
        if not v:
            continue
        itens.append(
            {
                "id": c["id"],
                "titulo": v["titulo"],
                "views": v["views"],
                "publicado_em": v["publicado_em"],
                "nicho": c["nicho"] or "(sem)",
                "subnicho": c["subnicho"] or "(sem)",
                "micro": c["micro"] or "(sem)",
            }
        )
    if not itens:
        raise SystemExit(
            "ERRO: nenhuma linha da classificacao casou com os videos do JSON. "
            "Confira se a primeira coluna e o id do video."
        )

    itens.sort(key=lambda x: x["publicado_em"] or "")
    n = len(itens)

    niveis = {}
    for nivel, chave in (
        ("nicho", lambda x: x["nicho"]),
        ("subnicho", lambda x: f"{x['nicho']} > {x['subnicho']}"),
        ("microsubnicho", lambda x: f"{x['nicho']} > {x['subnicho']} > {x['micro']}"),
    ):
        grupos = defaultdict(list)
        for it in itens:
            grupos[chave(it)].append(it)
        tabela = []
        for nome, g in grupos.items():
            s = stats_views(g)
            tabela.append(
                {
                    "grupo": nome,
                    "n": s["n"],
                    "pct": round(100 * s["n"] / n, 1),
                    "views_media": s["media"],
                    "views_mediana": s["mediana"],
                    "melhor": max(g, key=lambda x: x["views"] or 0)["titulo"],
                }
            )
        tabela.sort(key=lambda t: -t["n"])
        niveis[nivel] = tabela

    share = {k: (v[0]["pct"] / 100 if v else 0) for k, v in niveis.items()}
    foco = args.foco
    if share["microsubnicho"] >= foco:
        veredito = "Focado"
        leitura = ("o canal tem uma identidade so. O algoritmo sabe exatamente "
                   "a quem recomendar.")
    elif share["subnicho"] >= foco:
        veredito = "Mistura de microsubnicho"
        leitura = ("mesmo subnicho, angulos diferentes. Geralmente saudavel: "
                   "varia o formato sem trocar de publico.")
    elif share["nicho"] >= foco:
        veredito = "Mistura de subnicho"
        leitura = ("mesmo nicho, publicos diferentes. Risco medio: o algoritmo "
                   "acerta menos a recomendacao.")
    else:
        veredito = "Mistura de nicho"
        leitura = ("o canal faz coisas de areas diferentes. Problema de "
                   "identidade: publicos que nao se encontram.")

    # ajudando ou atrapalhando: micro dominante x resto
    dominante_nome = niveis["microsubnicho"][0]["grupo"]
    dom = [
        it
        for it in itens
        if f"{it['nicho']} > {it['subnicho']} > {it['micro']}" == dominante_nome
    ]
    ids_dom = {it["id"] for it in dom}
    resto = [it for it in itens if it["id"] not in ids_dom]
    s_dom, s_resto = stats_views(dom), stats_views(resto)
    if not resto or s_dom["media"] is None or s_resto["media"] is None:
        julgamento = None
    else:
        ratio = s_resto["media"] / s_dom["media"] if s_dom["media"] else None
        if ratio is None:
            julgamento = None
        elif ratio >= 1.15:
            julgamento = (
                "ajudando", ratio,
                "o que esta fora do micro principal faz MAIS views que o "
                "principal. Vale olhar se o canal nao deveria pivotar para la.")
        elif ratio <= 0.7:
            julgamento = (
                "atrapalhando", ratio,
                "o que esta fora do micro principal faz bem menos views. "
                "Esses videos diluem o canal sem retorno.")
        else:
            julgamento = (
                "neutra", ratio,
                "performance parecida dentro e fora do micro principal. "
                "A mistura nao esta cobrando pedagio por enquanto.")

    # antigo vs recente
    corte = max(1, int(n * args.janela_recente))
    antigos, recentes = itens[:-corte], itens[-corte:]

    def dominante(grupo, chave):
        if not grupo:
            return None, 0
        cnt = Counter(chave(x) for x in grupo)
        nome, q = cnt.most_common(1)[0]
        return nome, round(100 * q / len(grupo), 1)

    mchave = lambda x: f"{x['nicho']} > {x['subnicho']} > {x['micro']}"
    dom_antigo = dominante(antigos, mchave)
    dom_recente = dominante(recentes, mchave)
    pivo = bool(antigos) and dom_antigo[0] != dom_recente[0]

    md = relatorio_mistura(
        coleta, itens, niveis, veredito, leitura, julgamento,
        (dom_antigo, dom_recente, pivo, len(antigos), len(recentes)),
        dominante_nome, s_dom, s_resto, faltando, nao_classificados, vids, foco,
    )
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(md)
        print(f"relatorio -> {args.out}", file=sys.stderr)
    else:
        print(md)


def relatorio_mistura(coleta, itens, niveis, veredito, leitura, julgamento,
                      tempo, dominante_nome, s_dom, s_resto, faltando,
                      nao_classificados, vids, foco):
    c = coleta["canal"]
    L = []
    A = L.append
    A(f"# Diagnostico de mistura — {c['nome']}")
    A("")
    A(f"Base: {len(itens)} videos longos classificados "
      f"(limiar de foco: {int(foco * 100)}% no mesmo grupo).")
    A("")
    A(f"## Veredito: **{veredito}**")
    A("")
    A(leitura)
    A("")
    for nivel in ("nicho", "subnicho", "microsubnicho"):
        A(f"### Distribuicao por {nivel}")
        A("")
        A("| grupo | videos | % | views medias | views medianas | melhor video |")
        A("|---|---|---|---|---|---|")
        for t in niveis[nivel]:
            A(
                f"| {t['grupo']} | {t['n']} | {t['pct']}% "
                f"| {human(t['views_media'])} | {human(t['views_mediana'])} "
                f"| {t['melhor'].replace('|', '/')} |"
            )
        A("")
    A("## A mistura esta ajudando ou atrapalhando?")
    A("")
    A(f"Micro dominante: **{dominante_nome}** "
      f"({s_dom['n']} videos, media {human(s_dom['media'])} views).")
    if julgamento is None:
        A("")
        A("Nao ha videos fora do micro dominante (ou faltam views): sem "
          "comparacao possivel.")
    else:
        rotulo, ratio, texto = julgamento
        A(f"Fora dele: {s_resto['n']} videos, media {human(s_resto['media'])} "
          f"views — **{ratio:.2f}x** o desempenho do dominante.")
        A("")
        A(f"**A mistura esta {rotulo}:** {texto}")
    A("")
    (dom_antigo, dom_recente, pivo, n_ant, n_rec) = tempo
    A("## Antigo vs recente")
    A("")
    if n_ant == 0:
        A(f"Poucos videos para separar fases ({n_rec} no total).")
    else:
        A(f"- primeiros {n_ant} videos: dominante **{dom_antigo[0]}** "
          f"({dom_antigo[1]}%)")
        A(f"- ultimos {n_rec} videos: dominante **{dom_recente[0]}** "
          f"({dom_recente[1]}%)")
        A("")
        A("**Houve pivo:** o canal trocou de linha." if pivo
          else "Sem pivo: a linha recente e a mesma de sempre.")
    if faltando or nao_classificados:
        A("")
        A("## Pendencias")
        if faltando:
            A(f"- ids na classificacao que nao existem na coleta: "
              f"{', '.join(faltando[:10])}")
        if nao_classificados:
            A(f"- {len(nao_classificados)} videos coletados ficaram SEM "
              f"classificacao, entao a distribuicao acima nao cobre o canal "
              f"inteiro. Primeiros: "
              + "; ".join(vids[i]["titulo"][:50] for i in nao_classificados[:5]))
    return "\n".join(L)


# ------------------------------------------------------------------------ CLI


def main():
    p = argparse.ArgumentParser(
        description="Coleta e diagnostica o nicho de um canal do YouTube."
    )
    sub = p.add_subparsers(dest="modo", required=True)

    c = sub.add_parser("coletar", help="baixa o canal e analisa os titulos")
    c.add_argument("canal", help="link, @handle, UC id, link de video ou nome")
    c.add_argument("--alvo-longos", type=int, default=100,
                   help="para de paginar ao juntar N videos longos (padrao 100)")
    c.add_argument("--max-pages", type=int, default=12,
                   help="teto de paginas de 50 uploads a ler (padrao 12 = 600)")
    c.add_argument("--min-duration", type=int, default=180,
                   help="duracao minima em segundos; corta Shorts (padrao 180)")
    c.add_argument("--top", type=int, default=30,
                   help="quantos mais vistos mostrar (padrao 30)")
    c.add_argument("--recentes", type=int, default=15,
                   help="quantos mais recentes mostrar (padrao 15)")
    c.add_argument("--min-grupo", type=int, default=2,
                   help="minimo de titulos para virar grupo de abertura")
    c.add_argument("--api-key", help="chave da YouTube Data API v3")
    c.add_argument("--out", help="arquivo markdown de saida")
    c.add_argument("--json", help="arquivo json bruto de saida")
    c.set_defaults(func=coletar)

    m = sub.add_parser("mistura", help="calcula distribuicao e veredito")
    m.add_argument("--dados", required=True,
                   help="json gerado por 'coletar --json'")
    m.add_argument("--classificacao", required=True,
                   help="TSV/CSV (id, nicho, subnicho, micro) ou JSON")
    m.add_argument("--foco", type=float, default=0.8,
                   help="share minimo para considerar focado (padrao 0.8)")
    m.add_argument("--janela-recente", type=float, default=0.3,
                   help="fracao final dos videos tratada como 'recente' (0.3)")
    m.add_argument("--out", help="arquivo markdown de saida")
    m.set_defaults(func=mistura)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
