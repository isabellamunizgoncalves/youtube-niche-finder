#!/usr/bin/env python3
"""
Encontra canais NOVOS no YouTube com MUITAS views e POUCOS inscritos,
em um nicho qualquer, em qualquer idioma, considerando apenas VIDEOS LONGOS
(nunca Shorts).

Usa a YouTube Data API v3. A chave vem de:
  1. --api-key
  2. variavel de ambiente YOUTUBE_API_KEY
  3. arquivo ~/.youtube_api_key

Custo de quota (cota diaria padrao = 10.000 unidades):
  search.list   = 100 unidades por chamada (ate 50 resultados)
  videos.list   =   1 unidade por chamada  (ate 50 ids)
  channels.list =   1 unidade por chamada  (ate 50 ids)
O script imprime a quota estimada consumida no final.
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone

try:
    import requests
except ImportError:
    sys.exit("ERRO: instale a dependencia -> pip install requests")

API = "https://www.googleapis.com/youtube/v3"

# ---------------------------------------------------------------- utilitarios

ISO_DUR = re.compile(
    r"^P(?:(?P<days>\d+)D)?T?(?:(?P<h>\d+)H)?(?:(?P<m>\d+)M)?(?:(?P<s>\d+)S)?$"
)


def iso_duration_to_seconds(value):
    """PT1H2M3S -> 3723. Retorna None se nao der para interpretar."""
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


def now_utc():
    return datetime.now(timezone.utc)


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
    def __init__(self, api_key, verbose=True):
        self.key = api_key
        self.units = 0
        self.verbose = verbose
        self.session = requests.Session()

    def _get(self, endpoint, params, cost):
        params = dict(params)
        params["key"] = self.key
        for attempt in range(4):
            try:
                r = self.session.get(f"{API}/{endpoint}", params=params, timeout=30)
            except requests.RequestException as exc:
                if attempt == 3:
                    raise
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
                    "\nQUOTA ESGOTADA: a cota diaria da sua API key acabou.\n"
                    "Ela zera a meia-noite no horario do Pacifico (PT).\n"
                    f"Unidades gastas nesta execucao: {self.units}"
                )
            if reason in ("keyInvalid", "badRequest", "forbidden") or r.status_code in (
                400,
                401,
                403,
            ):
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

    def search_videos(self, query, published_after, duration, region, lang, order,
                      pages):
        """Retorna lista de videoIds."""
        ids = []
        token = None
        for _ in range(max(1, pages)):
            params = {
                "part": "id",
                "q": query,
                "type": "video",
                "maxResults": 50,
                "order": order,
                "videoDuration": duration,  # medium (4-20min) | long (>20min)
                "publishedAfter": published_after,
            }
            if region:
                params["regionCode"] = region
            if lang:
                params["relevanceLanguage"] = lang
            if token:
                params["pageToken"] = token
            data = self._get("search", params, cost=100)
            for item in data.get("items", []):
                vid = item.get("id", {}).get("videoId")
                if vid:
                    ids.append(vid)
            token = data.get("nextPageToken")
            if not token:
                break
        return ids

    def videos(self, video_ids):
        out = {}
        for batch in chunks(video_ids, 50):
            data = self._get(
                "videos",
                {
                    "part": "snippet,contentDetails,statistics",
                    "id": ",".join(batch),
                    "maxResults": 50,
                },
                cost=1,
            )
            for item in data.get("items", []):
                out[item["id"]] = item
        return out

    def channels(self, channel_ids):
        out = {}
        for batch in chunks(channel_ids, 50):
            data = self._get(
                "channels",
                {
                    "part": "snippet,statistics",
                    "id": ",".join(batch),
                    "maxResults": 50,
                },
                cost=1,
            )
            for item in data.get("items", []):
                out[item["id"]] = item
        return out


# ---------------------------------------------------------------- pipeline


def collect(yt, args):
    published_after = (
        now_utc() - timedelta(days=args.video_days)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    video_ids = []
    searches = 0
    budget = args.max_searches
    for query in args.query:
        for duration in args.durations:
            if searches >= budget:
                break
            if args.verbose:
                print(f"  buscando: '{query}'  [{duration}]", file=sys.stderr)
            video_ids += yt.search_videos(
                query=query,
                published_after=published_after,
                duration=duration,
                region=args.region,
                lang=args.lang,
                order=args.order,
                pages=args.pages,
            )
            searches += args.pages
        if searches >= budget:
            break

    video_ids = list(dict.fromkeys(video_ids))
    if args.verbose:
        print(f"  {len(video_ids)} videos unicos encontrados", file=sys.stderr)
    if not video_ids:
        return {}, {}

    videos = yt.videos(video_ids)
    channel_ids = list({v["snippet"]["channelId"] for v in videos.values()})
    if args.verbose:
        print(f"  consultando {len(channel_ids)} canais", file=sys.stderr)
    channels = yt.channels(channel_ids)
    return videos, channels


def analyse(videos, channels, args, excluded):
    now = now_utc()
    by_channel = {}

    for vid, v in videos.items():
        snip = v["snippet"]
        stats = v.get("statistics", {})
        cid = snip["channelId"]
        if cid in excluded:
            continue
        ch = channels.get(cid)
        if not ch:
            continue

        seconds = iso_duration_to_seconds(v.get("contentDetails", {}).get("duration"))
        if seconds is None or seconds < args.min_duration:
            continue  # Shorts e videos curtos fora

        views = int(stats.get("viewCount", 0) or 0)
        if views < args.min_video_views:
            continue

        cstats = ch.get("statistics", {})
        hidden = bool(cstats.get("hiddenSubscriberCount"))
        subs = None if hidden else int(cstats.get("subscriberCount", 0) or 0)
        if subs is not None and not (args.min_subs <= subs <= args.max_subs):
            continue

        created = parse_ts(ch["snippet"].get("publishedAt"))
        age_days = max((now - created).days, 1) if created else None
        if age_days is not None and age_days > args.channel_max_age_days:
            continue

        ch_views = int(cstats.get("viewCount", 0) or 0)
        ch_videos = int(cstats.get("videoCount", 0) or 0)
        if ch_views < args.min_channel_views:
            continue

        entry = by_channel.setdefault(
            cid,
            {
                "channel_id": cid,
                "canal": ch["snippet"].get("title"),
                "url": f"https://www.youtube.com/channel/{cid}",
                "criado_em": created.strftime("%Y-%m-%d") if created else None,
                "idade_dias": age_days,
                "inscritos": subs,
                "inscritos_ocultos": hidden,
                "views_totais": ch_views,
                "qtd_videos": ch_videos,
                "pais": ch["snippet"].get("country"),
                "descricao": (ch["snippet"].get("description") or "")[:300],
                "videos": [],
            },
        )
        entry["videos"].append(
            {
                "video_id": vid,
                "titulo": snip.get("title"),
                "url": f"https://www.youtube.com/watch?v={vid}",
                "publicado_em": (snip.get("publishedAt") or "")[:10],
                "duracao": hhmmss(seconds),
                "duracao_seg": seconds,
                "views": views,
                "likes": int(stats.get("likeCount", 0) or 0),
                "comentarios": int(stats.get("commentCount", 0) or 0),
                "idioma": snip.get("defaultAudioLanguage")
                or snip.get("defaultLanguage"),
            }
        )

    results = []
    for entry in by_channel.values():
        entry["videos"].sort(key=lambda x: -x["views"])
        subs = entry["inscritos"]
        base_subs = max(subs, 1) if subs is not None else None
        idade = entry["idade_dias"] or 1
        melhor = entry["videos"][0]["views"] if entry["videos"] else 0

        entry["views_por_inscrito"] = (
            round(entry["views_totais"] / base_subs, 1) if base_subs else None
        )
        entry["views_por_dia"] = round(entry["views_totais"] / idade)
        entry["media_views_por_video"] = (
            round(entry["views_totais"] / entry["qtd_videos"])
            if entry["qtd_videos"]
            else 0
        )
        entry["melhor_video_views"] = melhor
        entry["videos_encontrados"] = len(entry["videos"])
        # score: velocidade do canal x desproporcao views/inscritos x frescor
        ratio = entry["views_por_inscrito"] or 50.0
        frescor = max(0.3, min(1.0, 365 / idade))
        entry["score"] = round(
            (entry["views_por_dia"] ** 0.6) * (ratio ** 0.4) * frescor, 1
        )
        results.append(entry)

    key = {
        "score": lambda e: -e["score"],
        "views_dia": lambda e: -e["views_por_dia"],
        "views_por_inscrito": lambda e: -(e["views_por_inscrito"] or 0),
        "melhor_video": lambda e: -e["melhor_video_views"],
        "mais_novo": lambda e: e["idade_dias"] or 99999,
    }[args.sort]
    results.sort(key=key)
    return results[: args.limit]


# ---------------------------------------------------------------- saida


def to_markdown(results, args, units):
    if not results:
        return (
            "## Nenhum canal passou nos filtros\n\n"
            "Tente afrouxar: `--max-subs` maior, `--min-video-views` menor, "
            "`--channel-max-age-days` maior, ou outras palavras-chave."
        )
    lines = [
        f"## Canais novos e subindo — nicho: {args.niche or ', '.join(args.query)}",
        "",
        f"Filtros: canal criado ha <= {args.channel_max_age_days} dias · "
        f"inscritos <= {human(args.max_subs)} · video >= {hhmmss(args.min_duration)} "
        f"com >= {human(args.min_video_views)} views · "
        f"videos dos ultimos {args.video_days} dias · quota gasta: {units} unidades",
        "",
        "| # | Canal | Criado | Inscritos | Views totais | Views/inscrito | Views/dia | Melhor video | Score |",
        "|---|-------|--------|-----------|--------------|----------------|-----------|--------------|-------|",
    ]
    for i, e in enumerate(results, 1):
        subs = "oculto" if e["inscritos_ocultos"] else human(e["inscritos"])
        vpi = e["views_por_inscrito"]
        lines.append(
            f"| {i} | [{e['canal']}]({e['url']}) | {e['criado_em']} "
            f"({e['idade_dias']}d) | {subs} | {human(e['views_totais'])} | "
            f"{('%.0fx' % vpi) if vpi else '—'} | {human(e['views_por_dia'])} | "
            f"{human(e['melhor_video_views'])} | {e['score']} |"
        )
    lines.append("")
    lines.append("### Videos que puxaram cada canal")
    for i, e in enumerate(results, 1):
        lines.append("")
        subs = "oculto" if e["inscritos_ocultos"] else human(e["inscritos"])
        lines.append(
            f"**{i}. {e['canal']}** — {subs} inscritos · "
            f"{e['qtd_videos']} videos · criado em {e['criado_em']} · "
            f"{e['pais'] or 'pais nao informado'}"
        )
        for v in e["videos"][: args.videos_per_channel]:
            lines.append(
                f"- [{v['titulo']}]({v['url']}) — {human(v['views'])} views · "
                f"{v['duracao']} · {v['publicado_em']} · {v['idioma'] or '??'}"
            )
    return "\n".join(lines)


# ---------------------------------------------------------------- cli


def get_api_key(cli_key):
    if cli_key:
        return cli_key
    env = os.environ.get("YOUTUBE_API_KEY")
    if env:
        return env
    path = os.path.expanduser("~/.youtube_api_key")
    if os.path.exists(path):
        with open(path) as fh:
            value = fh.read().strip()
            if value:
                return value
    raise SystemExit(
        "ERRO: nenhuma chave encontrada.\n"
        "Defina a variavel de ambiente YOUTUBE_API_KEY, ou passe --api-key, "
        "ou salve a chave em ~/.youtube_api_key"
    )


def main():
    p = argparse.ArgumentParser(
        description="Acha canais novos do YouTube com muitas views e poucos inscritos."
    )
    p.add_argument("--query", "-q", action="append", required=True,
                   help="Termo de busca (repita para varias variacoes).")
    p.add_argument("--niche", help="Nome do nicho, so para o titulo do relatorio.")
    p.add_argument("--lang", help="Idioma de relevancia (pt, en, es, fr, hi...).")
    p.add_argument("--region", help="Codigo de pais (BR, US, ES, IN...).")
    p.add_argument("--channel-max-age-days", type=int, default=365,
                   help="Idade maxima do canal em dias. Padrao: 365.")
    p.add_argument("--max-subs", type=int, default=5000,
                   help="Maximo de inscritos. Padrao: 5000.")
    p.add_argument("--min-subs", type=int, default=0)
    p.add_argument("--min-video-views", type=int, default=50000,
                   help="Views minimas de um video. Padrao: 50000.")
    p.add_argument("--min-channel-views", type=int, default=0)
    p.add_argument("--min-duration", type=int, default=240,
                   help="Duracao minima em segundos (corta Shorts). Padrao: 240.")
    p.add_argument("--video-days", type=int, default=120,
                   help="So videos publicados nos ultimos N dias. Padrao: 120.")
    p.add_argument("--durations", default="medium,long",
                   help="medium (4-20min) e/ou long (>20min). Padrao: medium,long.")
    p.add_argument("--order", default="viewCount",
                   choices=["viewCount", "relevance", "date", "rating"])
    p.add_argument("--pages", type=int, default=1,
                   help="Paginas por busca (cada pagina = 100 unidades de quota).")
    p.add_argument("--max-searches", type=int, default=10,
                   help="Teto de chamadas search.list. Padrao: 10 (= 1000 unidades).")
    p.add_argument("--limit", type=int, default=20, help="Canais no relatorio.")
    p.add_argument("--videos-per-channel", type=int, default=3)
    p.add_argument("--sort", default="score",
                   choices=["score", "views_dia", "views_por_inscrito",
                            "melhor_video", "mais_novo"])
    p.add_argument("--exclude-file",
                   help="Arquivo com channelIds (um por linha) a ignorar.")
    p.add_argument("--json", dest="json_out", help="Salvar resultado bruto em JSON.")
    p.add_argument("--out", help="Salvar relatorio markdown neste arquivo.")
    p.add_argument("--api-key")
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args()

    args.verbose = not args.quiet
    args.durations = [d.strip() for d in args.durations.split(",") if d.strip()]

    excluded = set()
    if args.exclude_file and os.path.exists(args.exclude_file):
        with open(args.exclude_file) as fh:
            excluded = {l.strip() for l in fh if l.strip()}

    yt = Youtube(get_api_key(args.api_key), verbose=args.verbose)
    if args.verbose:
        print("Buscando no YouTube...", file=sys.stderr)
    videos, channels = collect(yt, args)
    results = analyse(videos, channels, args, excluded)

    report = to_markdown(results, args, yt.units)
    if args.out:
        with open(args.out, "w") as fh:
            fh.write(report)
    if args.json_out:
        with open(args.json_out, "w") as fh:
            json.dump(results, fh, ensure_ascii=False, indent=2)
    print(report)
    if args.verbose:
        print(
            f"\n[quota estimada usada: {yt.units} unidades de 10.000/dia]",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
