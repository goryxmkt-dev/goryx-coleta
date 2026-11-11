"""Coletores do Instagram pela API oficial (Graph API da Meta).

Comandos:
  diagnostico   confere token, conta, Página, permissões e cota (não grava nada)
  conta         perfil, posts e métricas da própria conta da Goryx
  concorrentes  perfis e posts públicos de outras contas profissionais (Business Discovery)

Uso:
  python3 -m coletores.instagram.coletar conta --saida <pasta privada>
  python3 -m coletores.instagram.coletar concorrentes --saida <pasta privada> [--alvos-arquivo alvos.json]

Variáveis de ambiente: IG_ACCESS_TOKEN (segredo), IG_USER_ID, IG_PAGE_ID,
IG_API_VERSION (opcional), IG_APP_SECRET (opcional), ALVOS_JSON (segredo, lista de @).

Regras do repositório público: nada coletado entra aqui, nenhum alvo no código,
log só com contagens e status.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .graph import ErroGraph, Graph, diagnostico

BRT = timezone(timedelta(hours=-3))

CAMPOS_PERFIL = "username,name,biography,website,followers_count,follows_count,media_count"
CAMPOS_MIDIA = "id,caption,media_type,media_product_type,permalink,timestamp,like_count,comments_count"

# métricas tentadas por post; as que a API recusar para um formato são descartadas para aquele formato
METRICAS_POST = ["reach", "views", "likes", "comments", "saved", "shares", "total_interactions",
                 "ig_reels_avg_watch_time", "ig_reels_video_view_total_time"]
METRICAS_CONTA = ["reach", "views", "accounts_engaged", "total_interactions", "profile_links_taps",
                  "follows_and_unfollows"]


def agora() -> datetime:
    return datetime.now(BRT)


def _valor(item: dict):
    if "total_value" in item:
        return (item["total_value"] or {}).get("value")
    vals = item.get("values") or []
    return vals[-1].get("value") if vals else None


def _metricas(g: Graph, no: str, metricas: list[str], **extra) -> tuple[dict, list[str]]:
    """Pede todas de uma vez; se a API recusar, tenta uma a uma. Devolve (valores, aceitas)."""
    try:
        dados = g.get(f"{no}/insights", metric=",".join(metricas), **extra).get("data", [])
        return {d["name"]: _valor(d) for d in dados}, list(metricas)
    except ErroGraph:
        pass
    valores, aceitas = {}, []
    for m in metricas:
        try:
            dados = g.get(f"{no}/insights", metric=m, **extra).get("data", [])
        except ErroGraph:
            continue
        aceitas.append(m)
        for d in dados:
            valores[d["name"]] = _valor(d)
    return valores, aceitas


def _data_br(ts: str | None) -> str:
    if not ts:
        return ""
    try:
        return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S%z").astimezone(BRT).strftime("%d/%m/%Y")
    except ValueError:
        return ts[:10]


def _gancho(legenda: str | None) -> str:
    primeira = (legenda or "").strip().splitlines()[0] if (legenda or "").strip() else ""
    return primeira[:150]


def _formato(m: dict) -> str:
    prod, tipo = m.get("media_product_type"), m.get("media_type")
    if prod == "REELS":
        return "reels"
    return {"CAROUSEL_ALBUM": "carrossel", "IMAGE": "imagem", "VIDEO": "vídeo"}.get(tipo, (tipo or "").lower())


def _gravar_json(caminho: Path, dados) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(dados, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _gravar_tsv(caminho: Path, cabecalho: list[str], linhas: list[list]) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with caminho.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(cabecalho)
        for linha in linhas:
            w.writerow(["" if v is None else str(v).replace("\t", " ").replace("\n", " ") for v in linha])


# Mesmas colunas das abas Perfis e Posts da base de mineração (data/mineracao/ no goryx-marketing)
COLUNAS_PERFIS = ["Perfil", "Canal", "Seguidores", "Total de publicações", "Frequência aparente",
                  "Formatos mais usados", "Link", "Data da coleta"]
COLUNAS_POSTS = ["Perfil", "Canal", "Data do post", "Formato", "Duração", "Gancho / título", "Tema",
                 "Reações", "Comentários", "Visualizações", "Link", "Data da coleta"]


def resumo_perfil(perfil: dict, midias: list[dict], hoje: datetime) -> list:
    limite = hoje - timedelta(days=30)
    recentes = 0
    for m in midias:
        try:
            if datetime.strptime(m.get("timestamp", ""), "%Y-%m-%dT%H:%M:%S%z") >= limite:
                recentes += 1
        except ValueError:
            pass
    formatos = Counter(_formato(m) for m in midias)
    usuario = perfil.get("username", "")
    return [
        perfil.get("name") or usuario, "Instagram", perfil.get("followers_count"), perfil.get("media_count"),
        f"{recentes} posts nos últimos 30 dias",
        ", ".join(f"{k} ({v})" for k, v in formatos.most_common(3)),
        f"https://www.instagram.com/{usuario}/", hoje.strftime("%d/%m/%Y"),
    ]


def linhas_posts(perfil: dict, midias: list[dict], hoje: datetime, visualizacoes: dict | None = None) -> list[list]:
    nome = perfil.get("name") or perfil.get("username", "")
    visualizacoes = visualizacoes or {}
    return [[
        nome, "Instagram", _data_br(m.get("timestamp")), _formato(m), "", _gancho(m.get("caption")), "",
        m.get("like_count"), m.get("comments_count"), visualizacoes.get(m.get("id")), m.get("permalink"),
        hoje.strftime("%d/%m/%Y"),
    ] for m in midias]


# ---------------- comandos ----------------

def cmd_conta(g: Graph, ig_id: str, saida: Path, max_posts: int) -> dict:
    hoje = agora()
    perfil = g.get(ig_id, fields=CAMPOS_PERFIL)
    midias = list(g.paginar(f"{ig_id}/media", max_paginas=4, fields=CAMPOS_MIDIA, limit=25))[:max_posts]

    aceitas_por_formato: dict[str, list[str]] = {}
    for m in midias:
        fmt = _formato(m)
        tentar = aceitas_por_formato.get(fmt, METRICAS_POST)
        valores, aceitas = _metricas(g, m["id"], tentar)
        aceitas_por_formato.setdefault(fmt, aceitas)
        m["metricas"] = valores

    fim = int(hoje.timestamp())
    inicio = int((hoje - timedelta(days=7)).timestamp())
    conta, _ = _metricas(g, ig_id, METRICAS_CONTA, period="day", metric_type="total_value", since=inicio, until=fim)

    seguidores = []
    try:
        dados = g.get(f"{ig_id}/insights", metric="follower_count", period="day",
                      since=int((hoje - timedelta(days=29)).timestamp()), until=fim).get("data", [])
        seguidores = (dados[0].get("values") if dados else []) or []
    except ErroGraph:
        pass

    data = hoje.strftime("%Y-%m-%d")
    _gravar_json(saida / f"{data}.json", {
        "coletado_em": hoje.isoformat(timespec="seconds"), "fonte": "Instagram Graph API",
        "perfil": perfil, "conta_7_dias": conta, "seguidores_por_dia": seguidores, "posts": midias,
    })
    cab = ["Data do post", "Formato", "Gancho", "Link"] + METRICAS_POST
    _gravar_tsv(saida / f"{data}-posts.tsv", cab, [
        [_data_br(m.get("timestamp")), _formato(m), _gancho(m.get("caption")), m.get("permalink")]
        + [m["metricas"].get(k) for k in METRICAS_POST] for m in midias])
    return {"posts": len(midias), "metricas_conta": len(conta), "dias_seguidores": len(seguidores)}


def ler_alvos(arquivo: str | None) -> list[str]:
    bruto = os.environ.get("ALVOS_JSON", "").strip()
    if not bruto and arquivo and Path(arquivo).is_file():
        bruto = Path(arquivo).read_text(encoding="utf-8")
    if not bruto:
        return []
    dados = json.loads(bruto)
    if isinstance(dados, dict):
        dados = dados.get("instagram", [])
    alvos = []
    for a in dados:
        a = str(a).strip().rstrip("/")
        if "instagram.com" in a:
            a = a.split("?")[0].rstrip("/").split("/")[-1]
        a = a.lstrip("@")
        if a and a.replace(".", "").replace("_", "").isalnum() and a not in alvos:
            alvos.append(a)
    return alvos


def cmd_concorrentes(g: Graph, ig_id: str, saida: Path, alvos: list[str], posts_por_perfil: int) -> dict:
    hoje = agora()
    perfis, posts, brutos = [], [], {}
    falhas = Counter()
    for usuario in alvos:
        campos = (f"business_discovery.username({usuario})"
                  f"{{{CAMPOS_PERFIL},media.limit({posts_por_perfil}){{{CAMPOS_MIDIA}}}}}")
        try:
            bd = g.get(ig_id, fields=campos).get("business_discovery") or {}
        except ErroGraph as e:
            # conta pessoal, inexistente ou privada: a API recusa; registra só o tipo de falha
            falhas[f"código {e.codigo}/{e.subcodigo}"] += 1
            continue
        midias = (bd.pop("media", None) or {}).get("data", [])
        brutos[usuario] = {**bd, "posts": midias}
        perfis.append(resumo_perfil(bd, midias, hoje))
        posts.extend(linhas_posts(bd, midias, hoje))

    data = hoje.strftime("%Y-%m-%d")
    _gravar_json(saida / f"{data}.json", {"coletado_em": hoje.isoformat(timespec="seconds"),
                                          "fonte": "Instagram Graph API (Business Discovery)", "perfis": brutos})
    _gravar_tsv(saida / f"{data}-perfis.tsv", COLUNAS_PERFIS, perfis)
    _gravar_tsv(saida / f"{data}-posts.tsv", COLUNAS_POSTS, posts)
    return {"alvos": len(alvos), "perfis": len(perfis), "posts": len(posts), "falhas": sum(falhas.values()),
            "tipos_de_falha": dict(falhas)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("comando", choices=["diagnostico", "conta", "concorrentes"])
    ap.add_argument("--saida", help="pasta de destino (no checkout do repositório privado)")
    ap.add_argument("--alvos-arquivo", help="JSON com a lista de @ (usado se ALVOS_JSON estiver vazio)")
    ap.add_argument("--max-posts", type=int, default=25)
    ap.add_argument("--posts-por-perfil", type=int, default=12)
    a = ap.parse_args(argv)

    ig_id = os.environ.get("IG_USER_ID", "").strip()
    pagina_id = os.environ.get("IG_PAGE_ID", "").strip()
    if not ig_id:
        print("Falta IG_USER_ID.")
        return 2
    try:
        g = Graph.do_ambiente()
    except ValueError as e:
        print(e)
        return 2

    try:
        if a.comando == "diagnostico":
            linhas = diagnostico(g, ig_id, pagina_id)
            for item, status in linhas:
                print(f"- {item}: {status}")
            return 1 if any("FALHOU" in s for _, s in linhas) else 0
        if not a.saida:
            print("Falta --saida.")
            return 2
        saida = Path(a.saida)
        if a.comando == "conta":
            r = cmd_conta(g, ig_id, saida, a.max_posts)
        else:
            alvos = ler_alvos(a.alvos_arquivo)
            if not alvos:
                print("Nenhum alvo: preencha o segredo ALVOS_JSON ou o arquivo de alvos no repositório privado.")
                return 0
            r = cmd_concorrentes(g, ig_id, saida, alvos, a.posts_por_perfil)
    except ErroGraph as e:
        print(f"Erro da API: {e}")
        return 1
    print(f"{a.comando}: " + ", ".join(f"{k}={v}" for k, v in r.items()) + f", chamadas={g.chamadas}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
