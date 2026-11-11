"""Testes dos coletores do Instagram com uma API falsa (sem rede, sem token real).

Rodar: python3 -m unittest discover -s testes -v
"""
import json
import os
import tempfile
import unittest
import urllib.parse
from pathlib import Path

from coletores.instagram import coletar
from coletores.instagram.graph import ErroGraph, Graph

TOKEN = "TOKEN-SECRETO-DE-TESTE"


class ApiFalsa:
    """Responde por caminho; registra cada pedido."""

    def __init__(self, rotas):
        self.rotas = rotas
        self.pedidos = []

    def __call__(self, metodo, url, cab, corpo):
        partes = urllib.parse.urlsplit(url)
        caminho = partes.path.split("/", 2)[-1]
        params = dict(urllib.parse.parse_qsl(partes.query))
        if corpo and metodo == "POST" and cab.get("Content-Type", "").startswith("application/x-www"):
            params.update(urllib.parse.parse_qsl(corpo.decode()))
        self.pedidos.append((metodo, caminho, params, cab))
        for (m, padrao), resposta in self.rotas.items():
            if m == metodo and padrao == caminho:
                r = resposta(params) if callable(resposta) else resposta
                status = r.pop("_status", 200) if isinstance(r, dict) else 200
                return status, json.dumps(r).encode()
        return 404, json.dumps({"error": {"code": 803, "message": f"rota {caminho}", "type": "OAuthException"}}).encode()


def g_falso(rotas):
    api = ApiFalsa(rotas)
    return Graph(TOKEN, "v24.0", transporte=api, dormir=lambda s: None), api


class TesteGraph(unittest.TestCase):
    def test_token_vai_no_cabecalho_e_nao_na_url(self):
        g, api = g_falso({("GET", "me"): {"id": "1"}})
        g.get("me", fields="id")
        metodo, caminho, params, cab = api.pedidos[0]
        self.assertEqual(cab["Authorization"], f"Bearer {TOKEN}")
        self.assertNotIn(TOKEN, json.dumps(params))

    def test_erro_nao_vaza_token(self):
        msg = {"_status": 400, "error": {"code": 190, "message": f"token {TOKEN} expirou", "type": "OAuthException"}}
        g, _ = g_falso({("GET", "me"): msg})
        with self.assertRaises(ErroGraph) as c:
            g.get("me")
        self.assertNotIn(TOKEN, str(c.exception))
        self.assertEqual(c.exception.codigo, 190)

    def test_repete_erro_transitorio(self):
        respostas = [{"_status": 500, "error": {"code": 2, "message": "tente de novo"}}, {"id": "1"}]
        g, api = g_falso({("GET", "me"): lambda p: respostas.pop(0)})
        self.assertEqual(g.get("me")["id"], "1")
        self.assertEqual(len(api.pedidos), 2)

    def test_assinatura_do_app(self):
        api = ApiFalsa({("GET", "me"): {"id": "1"}})
        g = Graph(TOKEN, transporte=api, app_secret="segredo", dormir=lambda s: None)
        g.get("me")
        self.assertIn("appsecret_proof", api.pedidos[0][2])

    def test_paginacao(self):
        pagina2 = "https://graph.facebook.com/v24.0/123/media?after=X"
        g, _ = g_falso({
            ("GET", "123/media"): lambda p: ({"data": [{"id": "b"}]} if p.get("after")
                                             else {"data": [{"id": "a"}], "paging": {"next": pagina2}}),
        })
        self.assertEqual([m["id"] for m in g.paginar("123/media")], ["a", "b"])


class TesteColetores(unittest.TestCase):
    def test_alvos_aceita_arroba_link_e_descarta_lixo(self):
        os.environ["ALVOS_JSON"] = json.dumps(["@empresa_a", "https://www.instagram.com/empresa.b/", "x y", "@empresa_a"])
        try:
            self.assertEqual(coletar.ler_alvos(None), ["empresa_a", "empresa.b"])
        finally:
            del os.environ["ALVOS_JSON"]

    def test_concorrentes_grava_no_formato_da_base(self):
        def bd(params):
            if "naoexiste" in params["fields"]:
                return {"_status": 400, "error": {"code": 110, "error_subcode": 2207013, "message": "x"}}
            return {"business_discovery": {
                "username": "empresa_a", "name": "Empresa A", "followers_count": 1200, "media_count": 300,
                "media": {"data": [{"id": "m1", "caption": "Primeira linha\nresto", "media_type": "VIDEO",
                                    "media_product_type": "REELS", "permalink": "https://instagram.com/p/1",
                                    "timestamp": "2026-11-01T15:00:00+0000", "like_count": 10, "comments_count": 2}]}}}
        g, _ = g_falso({("GET", "999"): bd})
        with tempfile.TemporaryDirectory() as d:
            r = coletar.cmd_concorrentes(g, "999", Path(d), ["empresa_a", "naoexiste"], 12)
            self.assertEqual((r["perfis"], r["posts"], r["falhas"]), (1, 1, 1))
            perfis = next(Path(d).glob("*-perfis.tsv")).read_text().splitlines()
            posts = next(Path(d).glob("*-posts.tsv")).read_text().splitlines()
        self.assertEqual(perfis[0].split("\t"), coletar.COLUNAS_PERFIS)
        self.assertIn("Empresa A\tInstagram\t1200\t300", perfis[1])
        self.assertEqual(posts[0].split("\t"), coletar.COLUNAS_POSTS)
        self.assertIn("reels", posts[1])
        self.assertIn("Primeira linha", posts[1])
        self.assertNotIn("resto", posts[1])

    def test_conta_descobre_metricas_aceitas_por_formato(self):
        def insights(params):
            metricas = params["metric"].split(",")
            if len(metricas) > 1 and "ig_reels_avg_watch_time" in metricas:
                return {"_status": 400, "error": {"code": 100, "message": "métrica inválida"}}
            if metricas[0].startswith("ig_reels"):
                return {"_status": 400, "error": {"code": 100, "message": "métrica inválida"}}
            return {"data": [{"name": m, "values": [{"value": 5}]} for m in metricas]}
        midias = {"data": [
            {"id": "p1", "media_type": "IMAGE", "media_product_type": "FEED", "timestamp": "2026-11-01T15:00:00+0000"},
            {"id": "p2", "media_type": "IMAGE", "media_product_type": "FEED", "timestamp": "2026-11-02T15:00:00+0000"},
        ]}
        rotas = {("GET", "999"): {"username": "goryx"}, ("GET", "999/media"): midias,
                 ("GET", "p1/insights"): insights, ("GET", "p2/insights"): insights,
                 ("GET", "999/insights"): {"data": [{"name": "reach", "total_value": {"value": 40}}]}}
        g, api = g_falso(rotas)
        with tempfile.TemporaryDirectory() as d:
            r = coletar.cmd_conta(g, "999", Path(d), 25)
            dados = json.loads(next(Path(d).glob("*.json")).read_text())
        self.assertEqual(r["posts"], 2)
        self.assertEqual(dados["posts"][0]["metricas"]["reach"], 5)
        # o segundo post do mesmo formato já usa só as métricas aceitas: 1 chamada
        self.assertEqual(sum(1 for p in api.pedidos if p[1] == "p2/insights"), 1)


if __name__ == "__main__":
    unittest.main()
