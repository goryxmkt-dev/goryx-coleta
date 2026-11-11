"""Cliente mínimo da Graph API da Meta (Instagram com login do Facebook).

Só biblioteca padrão do Python: nada para instalar, nada de terceiros para validar.

Regras de segurança:
- o token vai no cabeçalho, nunca na URL;
- toda mensagem de erro passa por `_limpar`, que apaga o token antes de imprimir;
- este módulo não imprime nada: quem chama decide o que vai para o log (só contagens e status).

Este arquivo existe igual em dois lugares:
- goryx-coleta/coletores/instagram/graph.py (coletores de mercado)
- goryx-marketing/scripts/instagram/graph.py (caixa de entrada, publicação e respostas)
Ao mudar um, copiar para o outro.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

VERSAO_PADRAO = "v24.0"
BASE = "https://graph.facebook.com"
UPLOAD = "https://rupload.facebook.com/ig-api-upload"

# códigos da Meta que costumam passar se tentar de novo (instabilidade e limite de uso)
TRANSITORIOS = {1, 2, 4, 17, 32, 341, 613, 80001, 80002}


class ErroGraph(Exception):
    def __init__(self, status: int, codigo: int | None, subcodigo: int | None, tipo: str, mensagem: str):
        self.status = status
        self.codigo = codigo
        self.subcodigo = subcodigo
        self.tipo = tipo
        self.mensagem = mensagem
        super().__init__(f"HTTP {status} · código {codigo} · subcódigo {subcodigo} · {tipo}: {mensagem}")


def _transporte_urllib(metodo: str, url: str, cabecalhos: dict, corpo: bytes | None, tempo_limite: int = 60):
    req = urllib.request.Request(url, data=corpo, method=metodo, headers=cabecalhos)
    try:
        with urllib.request.urlopen(req, timeout=tempo_limite) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


class Graph:
    def __init__(self, token: str, versao: str | None = None, app_secret: str | None = None,
                 transporte=None, dormir=time.sleep, tentativas: int = 3):
        if not token:
            raise ValueError("Token vazio: confira o segredo IG_ACCESS_TOKEN.")
        self.token = token.strip()
        self.versao = versao or VERSAO_PADRAO
        self.app_secret = app_secret or None
        self._transporte = transporte or _transporte_urllib
        self._dormir = dormir
        self.tentativas = tentativas
        self.chamadas = 0

    @classmethod
    def do_ambiente(cls, **kw) -> "Graph":
        return cls(
            token=os.environ.get("IG_ACCESS_TOKEN", ""),
            versao=os.environ.get("IG_API_VERSION") or None,
            app_secret=os.environ.get("IG_APP_SECRET") or None,
            **kw,
        )

    def com_token(self, token: str) -> "Graph":
        """Mesmo cliente com outro token (ex.: token da Página para mensagens diretas)."""
        return Graph(token, self.versao, self.app_secret, self._transporte, self._dormir, self.tentativas)

    # ---------- utilidades ----------
    def _limpar(self, texto: str) -> str:
        texto = texto.replace(self.token, "***")
        if self.app_secret:
            texto = texto.replace(self.app_secret, "***")
        return texto

    def _assinatura(self) -> dict:
        if not self.app_secret:
            return {}
        prova = hmac.new(self.app_secret.encode(), self.token.encode(), hashlib.sha256).hexdigest()
        return {"appsecret_proof": prova}

    @staticmethod
    def _codificar(params: dict) -> dict:
        saida = {}
        for k, v in params.items():
            if v is None:
                continue
            if isinstance(v, (dict, list)):
                saida[k] = json.dumps(v, ensure_ascii=False, separators=(",", ":"))
            elif isinstance(v, bool):
                saida[k] = "true" if v else "false"
            else:
                saida[k] = str(v)
        return saida

    def _url(self, caminho: str) -> str:
        if caminho.startswith("https://"):
            return caminho
        return f"{BASE}/{self.versao}/{caminho.lstrip('/')}"

    def _pedir(self, metodo: str, url: str, params: dict | None = None,
               cabecalhos_extra: dict | None = None, corpo_bruto: bytes | None = None) -> dict:
        params = self._codificar({**(params or {}), **self._assinatura()})
        cabecalhos = {"Authorization": f"Bearer {self.token}", "User-Agent": "goryx-motor/1.0"}
        cabecalhos.update(cabecalhos_extra or {})
        corpo = corpo_bruto
        if metodo == "GET" or corpo_bruto is not None:
            if params:
                sep = "&" if "?" in url else "?"
                url = url + sep + urllib.parse.urlencode(params)
        else:
            corpo = urllib.parse.urlencode(params).encode()
            cabecalhos["Content-Type"] = "application/x-www-form-urlencoded"

        ultimo = None
        for tentativa in range(self.tentativas):
            self.chamadas += 1
            try:
                status, bruto = self._transporte(metodo, url, cabecalhos, corpo)
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                ultimo = ErroGraph(0, None, None, "Rede", self._limpar(str(e)))
                self._dormir(2 ** (tentativa + 1))
                continue
            try:
                dados = json.loads(bruto.decode() or "{}")
            except (ValueError, UnicodeDecodeError):
                dados = {"error": {"message": "resposta não é JSON", "type": "Formato"}}
            if 200 <= status < 300 and "error" not in dados:
                return dados
            err = dados.get("error", {}) if isinstance(dados, dict) else {}
            ultimo = ErroGraph(
                status, err.get("code"), err.get("error_subcode"), err.get("type", "Erro"),
                self._limpar(str(err.get("error_user_msg") or err.get("message") or "sem mensagem")),
            )
            transitorio = status >= 500 or err.get("is_transient") or err.get("code") in TRANSITORIOS
            if not transitorio or tentativa == self.tentativas - 1:
                break
            self._dormir(2 ** (tentativa + 1) * 5)
        raise ultimo

    # ---------- API ----------
    def get(self, caminho: str, **params) -> dict:
        return self._pedir("GET", self._url(caminho), params)

    def post(self, caminho: str, **params) -> dict:
        return self._pedir("POST", self._url(caminho), params)

    def paginar(self, caminho: str, max_paginas: int = 10, **params):
        """Percorre `data` seguindo `paging.next`, até `max_paginas` páginas."""
        resp = self.get(caminho, **params)
        for _ in range(max_paginas):
            yield from resp.get("data", [])
            prox = (resp.get("paging") or {}).get("next")
            if not prox:
                return
            resp = self._pedir("GET", prox)

    def enviar_arquivo(self, container_id: str, caminho_arquivo: str) -> dict:
        """Envio de vídeo local para um container criado com upload_type=resumable."""
        with open(caminho_arquivo, "rb") as f:
            dados = f.read()
        url = f"{UPLOAD}/{self.versao}/{container_id}"
        cab = {"Authorization": f"OAuth {self.token}", "offset": "0", "file_size": str(len(dados)),
               "Content-Type": "application/octet-stream"}
        return self._pedir("POST", url, {}, cabecalhos_extra=cab, corpo_bruto=dados)


def token_da_pagina(g: Graph, pagina_id: str) -> Graph:
    """Mensagens diretas exigem o token da Página. Se o segredo já for o da Página, usa ele mesmo."""
    try:
        resp = g.get(pagina_id, fields="access_token")
        tok = resp.get("access_token")
        if tok:
            return g.com_token(tok)
    except ErroGraph:
        pass
    return g


PERMISSOES_ESPERADAS = [
    "instagram_basic", "instagram_content_publish", "instagram_manage_comments",
    "instagram_manage_insights", "instagram_manage_messages", "pages_show_list",
    "pages_read_engagement", "pages_manage_metadata", "pages_manage_posts", "business_management",
]


def diagnostico(g: Graph, ig_id: str, pagina_id: str) -> list[tuple[str, str]]:
    """Confere token, conta, Página, permissões e cota. Devolve (item, status) sem dado pessoal."""
    linhas: list[tuple[str, str]] = []

    def tenta(nome, func):
        try:
            linhas.append((nome, func()))
        except ErroGraph as e:
            linhas.append((nome, f"FALHOU ({e.codigo}/{e.subcodigo} {e.tipo}: {e.mensagem})"))

    tenta("Token válido", lambda: "ok" if g.get("me", fields="id").get("id") else "sem id")

    def perms():
        dados = g.get("me/permissions").get("data", [])
        dadas = {p["permission"] for p in dados if p.get("status") == "granted"}
        faltam = [p for p in PERMISSOES_ESPERADAS if p not in dadas]
        return "ok" if not faltam else "faltam: " + ", ".join(faltam)

    tenta("Permissões do token", perms)
    tenta("Conta do Instagram", lambda: "ok (@{})".format(g.get(ig_id, fields="username").get("username")))
    tenta("Página do Facebook ligada", lambda: (
        "ok" if (g.get(pagina_id, fields="instagram_business_account").get("instagram_business_account") or {}).get("id") == ig_id
        else "a Página não aponta para este Instagram"))

    def cota():
        d = g.get(f"{ig_id}/content_publishing_limit", fields="config,quota_usage").get("data", [{}])[0]
        return "ok ({} de {} publicações nas últimas 24 h)".format(
            d.get("quota_usage", "?"), (d.get("config") or {}).get("quota_total", "?"))

    tenta("Cota de publicação", cota)

    def pagina():
        try:
            tok = g.get(pagina_id, fields="access_token").get("access_token")
        except ErroGraph as e:
            return f"FALHOU ao pegar o token da Página ({e.codigo}: {e.mensagem})"
        if not tok:
            return "o token não devolveu o token da Página (usando o próprio token)"
        return "ok (token da Página obtido)"

    tenta("Token da Página (envio de imagens)", pagina)

    def dm():
        gp = token_da_pagina(g, pagina_id)
        n = len(gp.get(f"{pagina_id}/conversations", platform="instagram", fields="id", limit=5).get("data", []))
        return f"ok ({n} conversa(s) lida(s) no teste)"

    tenta("Mensagens diretas", dm)
    return linhas
