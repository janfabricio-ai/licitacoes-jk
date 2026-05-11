import requests
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import os

# ──────────────────────────────────────────────
# CONFIGURAÇÃO
# ──────────────────────────────────────────────
GMAIL_USER         = os.environ.get("GMAIL_USER", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
EMAIL_DESTINO      = "licitacao.jkartesgraficas@gmail.com"
EMAIL_COPIA        = "janfabricio@gmail.com"
EMAIL_FROM_NAME    = "JK Licitações"

ESTADOS = ["PR", "SP", "SC", "RS"]

# Modalidades PNCP relevantes (códigos da Lei 14.133/2021)
MODALIDADES = {
    4:  "Concorrência Eletrônica",
    5:  "Concorrência Presencial",
    6:  "Pregão Eletrônico",
    7:  "Pregão Presencial",
    8:  "Dispensa",
    9:  "Inexigibilidade",
    12: "Credenciamento",
}

# ──────────────────────────────────────────────────────────────────────────────
# KEYWORDS — 3 pilares do negócio JK Artes Gráficas
#
#  PILAR 1 — Material Gráfico (impressos em geral)
#  PILAR 2 — Comunicação Visual (banner, adesivo, lona, placa, ACM, fachada…)
#  PILAR 3 — PROERD (exclusivo Paraná)
# ──────────────────────────────────────────────────────────────────────────────

KEYWORDS_PRIMARIAS = [
    # ── PILAR 1: Material Gráfico ─────────────────────────────────────────
    "gráfica", "grafica",
    "serviço gráfico", "servico grafico",
    "serviços gráficos", "servicos graficos",
    "produção gráfica", "producao grafica",
    "material gráfico", "material grafico",
    "impressão gráfica", "impressao grafica",
    "offset", "off-set",
    "plotagem", "ploter", "plotter",
    "folder", "folders",
    "panfleto", "panfletos",
    "flyer", "flyers",
    "encadernação", "encadernacao",
    "plastificação", "plastificacao",
    "catálogo impresso", "catalogo impresso",
    "calendário impresso", "calendario impresso",
    "crachá", "cracha", "crachás", "crachas",

    # ── PILAR 2: Comunicação Visual ───────────────────────────────────────
    "comunicação visual", "comunicacao visual",
    "banner", "banners",
    "faixa", "faixas",
    "lona impressa", "lona para banner", "lona de licitação", "impressão em lona",
    "impressao em lona",
    "adesivo", "adesivos",
    "vinil adesivo", "plotagem vinil",
    "placa de sinalização", "placa sinalizacao",
    "placa sinalizadora", "placa sinalética",
    "sinalização visual", "sinalizacao visual",
    "sinalização interna", "sinalizacao interna",
    "sinalização externa", "sinalizacao externa",
    "letreiro", "letreiros",
    "totem", "totens",
    "backlight", "back-light",
    "luminoso", "luminosos",
    "acm", "painel acm", "chapa acm",
    "alumínio composto", "aluminio composto",
    "fachada comercial", "fachada de loja",
    "letras caixa", "letra caixa",
    "letras em acm", "letras em alumínio",
]

KEYWORDS_COMPOSTAS = [
    # Termos genéricos — só válidos quando acompanhados de contexto gráfico/visual
    "impressão", "impressao",
    "lona",
    "vinil",
    "cartaz", "cartazes",
    "sinalização", "sinalizacao",
    "fachada",
    "painel", "painéis", "paineis",
]

# Keywords exclusivas por estado
KEYWORDS_PR = [
    "proerd",
    "cartilha proerd",
    "material proerd",
    "kit proerd",
]

# Termos que ELIMINAM o edital — fora do segmento
KEYWORDS_EXCLUSAO = [
    # Obras / engenharia civil
    "pavimentação", "pavimentacao", "pavimento",
    "recape", "recapeamento", "asfalto", "asfáltico", "asfaltico",
    "obras de engenharia", "obra de engenharia",
    "construção civil", "construcao civil",
    "reforma predial", "reforma de edificação",
    "drenagem", "esgoto", "saneamento",
    "terraplanagem", "aterro",
    "ponte", "viaduto", "galeria de concreto",
    "instalação elétrica", "instalacao eletrica",
    "instalação hidráulica", "instalacao hidraulica",
    # Fachada de obra (não comunicação visual)
    "reforma de fachada", "revitalização de fachada",
    "fachada predial", "fachada de edificação",
    "fachada ventilada",
    # Lona industrial / transporte
    "lona de freio", "lona de caminhão", "lona caminhao",
    "lona agrícola", "lona agricola",
    "lona de cobertura",
    # ACM / alumínio na construção civil
    "esquadria de alumínio", "esquadria aluminio",
    "cobertura em alumínio",
    # Outros fora do segmento
    "uniforme", "uniforme escolar",
    "vestuário", "vestuario",
    "têxtil", "textil",
    "bordado",
    "sublimação em tecido", "sublimacao em tecido",
]

def contem_keyword(texto: str, uf: str = "") -> bool:
    if not texto:
        return False
    t = texto.lower()

    # Eliminar imediatamente se contém termos fora do segmento
    if any(k in t for k in KEYWORDS_EXCLUSAO):
        return False

    # Keywords exclusivas do PR
    if uf == "PR" and any(k in t for k in KEYWORDS_PR):
        return True
    # Match direto nas primárias
    if any(k in t for k in KEYWORDS_PRIMARIAS):
        return True
    # Para compostas, exige contexto gráfico
    CONTEXTO = ["gráf", "graf", "impress", "visual", "print", "tipograf"]
    if any(k in t for k in KEYWORDS_COMPOSTAS):
        return any(c in t for c in CONTEXTO)
    return False

# Manter compatibilidade com chamadas antigas
KEYWORDS = KEYWORDS_PRIMARIAS + KEYWORDS_COMPOSTAS

HOJE       = datetime.now()
HOJE_DATE  = HOJE.date()
DIAS_ATRAS = HOJE - timedelta(days=4)   # janela de 5 dias para não perder editais de fim de semana
DATA_I     = DIAS_ATRAS.strftime("%Y%m%d")
DATA_F     = HOJE.strftime("%Y%m%d")
DATA_I_DISPLAY = DIAS_ATRAS.strftime("%d/%m/%Y")
DATA_F_DISPLAY = HOJE.strftime("%d/%m/%Y")


# ──────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────
def edital_vigente(data_abertura: str) -> bool:
    """True se data de abertura/disputa >= hoje. Aceita campo vazio (mantém)."""
    if not data_abertura:
        return True
    s = data_abertura.strip()[:10]
    try:
        if "/" in s:
            d, m, y = s.split("/")
            dt = datetime(int(y), int(m), int(d)).date()
        else:
            y, mo, d = s.split("-")
            dt = datetime(int(y), int(mo), int(d)).date()
        return dt >= HOJE_DATE
    except Exception:
        return True


def formatar_moeda(valor) -> str:
    try:
        return f"R$ {float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "—"


def safe_get(url, params=None, headers=None, timeout=45) -> dict | None:
    import time
    for tentativa in (1, 2):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=timeout)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 204:
                return None  # No Content — combinação sem editais, comportamento normal
            print(f"  [ERRO] {url}: HTTP {r.status_code}")
            return None
        except Exception as e:
            if tentativa == 1:
                time.sleep(2)
                continue
            print(f"  [ERRO] {url}: {e}")
    return None


# ──────────────────────────────────────────────
# 1. PNCP — API de Publicações (principal)
#    Busca paralela por UF + Data + Modalidade
# ──────────────────────────────────────────────
def _buscar_pncp_combinacao(uf: str, cod_mod: int, nome_mod: str) -> list[dict]:
    """Busca uma combinação UF+modalidade no PNCP."""
    resultados = []
    url = "https://pncp.gov.br/api/consulta/v1/contratacoes/publicacao"
    pagina = 1
    while True:
        params = {
            "dataInicial": DATA_I,
            "dataFinal":   DATA_F,
            "uf":          uf,
            "codigoModalidadeContratacao": cod_mod,
            "pagina":      pagina,
            "tamanhoPagina": 50,
        }
        dados = safe_get(url, params=params)
        if not dados:
            break
        itens = dados.get("data", [])
        if not itens:
            break
        for item in itens:
            objeto = item.get("objetoCompra", "") or ""
            if not contem_keyword(objeto, uf):
                continue
            data_abertura = (item.get("dataAberturaProposta") or item.get("dataEncerramentoProposta") or "")[:10]
            if not edital_vigente(data_abertura):
                continue
            cnpj = item.get("orgaoEntidade", {}).get("cnpj", "")
            ano  = item.get("anoCompra", "")
            seq  = item.get("sequencialCompra", "")
            resultados.append({
                "portal":     "PNCP",
                "uf":         uf,
                "orgao":      item.get("orgaoEntidade", {}).get("razaoSocial", "—"),
                "objeto":     objeto[:200],
                "valor":      formatar_moeda(item.get("valorTotalEstimado")),
                "modalidade": nome_mod,
                "data":       data_abertura or (item.get("dataPublicacaoPncp") or "")[:10],
                "link":       f"https://pncp.gov.br/app/editais/{cnpj}/{ano}/{seq}" if cnpj else "https://pncp.gov.br/app/editais",
                "_chave":     item.get("numeroControlePNCP", objeto[:40]),
            })
        total_pag = dados.get("totalPaginas", 1)
        if pagina >= total_pag or pagina >= 5:
            break
        pagina += 1
    return resultados


def buscar_pncp_publicacoes() -> list[dict]:
    editais = []
    vistos  = set()
    combinacoes = [(uf, cod, nome) for uf in ESTADOS for cod, nome in MODALIDADES.items()]

    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {
            executor.submit(_buscar_pncp_combinacao, uf, cod, nome): (uf, cod)
            for uf, cod, nome in combinacoes
        }
        for future in as_completed(futures):
            try:
                for item in future.result():
                    chave = item.pop("_chave")
                    if chave not in vistos:
                        vistos.add(chave)
                        editais.append(item)
            except Exception as e:
                print(f"  [PNCP thread] {e}")

    print(f"[PNCP Publicações] {len(editais)} editais encontrados")
    return editais


# ──────────────────────────────────────────────
# 2. PNCP — Busca por Texto (complementar)
#    Captura editais que escapam da API de publicações
# ──────────────────────────────────────────────
def buscar_pncp_texto() -> list[dict]:
    editais = []
    vistos  = set()
    DATA_CORTE = (HOJE - timedelta(days=30)).strftime("%Y-%m-%d")

    TERMOS = [
        # Pilar 1 — Material gráfico
        "grafica material grafico",
        "servicos graficos impressos",
        "plotagem folder panfleto",
        "impressao grafica offset",
        # Pilar 2 — Comunicação visual
        "comunicacao visual banner",
        "adesivo vinil plotagem",
        "lona impressa banner faixa",
        "placa sinalizacao comunicacao visual",
        "letreiro totem luminoso backlight",
        "acm aluminio composto fachada",
        "sinalização visual interna externa",
        # Pilar 3 — PROERD (PR)
        "proerd cartilha material",
    ]

    for termo in TERMOS:
        dados = safe_get(
            "https://pncp.gov.br/api/search",
            params={"q": termo, "tipos_documento": "edital", "pagina": 1, "tam_pagina": 20},
        )
        if not dados:
            continue

        for item in dados.get("items", []):
            if item.get("uf") not in ESTADOS:
                continue
            data_pub = (item.get("data_publicacao_pncp") or item.get("createdAt") or "")[:10]
            if data_pub < DATA_CORTE:
                continue
            data_abertura = (item.get("data_abertura_proposta") or item.get("data_encerramento_proposta") or "")[:10]
            if not edital_vigente(data_abertura):
                continue
            objeto = item.get("description", "") or item.get("title", "")
            if not contem_keyword(objeto, item.get("uf", "")):
                continue
            chave = item.get("id", objeto[:40])
            if chave in vistos:
                continue
            vistos.add(chave)

            item_url = item.get("item_url", "")
            link = f"https://pncp.gov.br/app/editais{item_url.replace('/compras', '')}" if item_url else "https://pncp.gov.br/app/editais"

            editais.append({
                "portal":     "PNCP",
                "uf":         item.get("uf", "—"),
                "orgao":      item.get("orgao_nome", "—"),
                "objeto":     objeto[:200],
                "valor":      formatar_moeda(item.get("valor_global")),
                "modalidade": item.get("modalidade_licitacao_nome", "—"),
                "data":       data_abertura or data_pub,
                "link":       link,
            })

    print(f"[PNCP Texto] {len(editais)} editais complementares encontrados")
    return editais


# ──────────────────────────────────────────────
# 3. BLL Compras — busca autenticada (plano pago + reCAPTCHA v3 via 2captcha)
# ──────────────────────────────────────────────
BLL_USER         = os.environ.get("BLL_USER", "licitacao.graficajfacardoso@gmail.com")
BLL_PASS         = os.environ.get("BLL_PASS", "")
CAPTCHA_API_KEY  = os.environ.get("CAPTCHA_API_KEY", "")
BLL_ATIVO        = bool(BLL_PASS) and bool(CAPTCHA_API_KEY)

# Códigos numéricos do BLL para fkState (descobertos via DevTools 09/05)
BLL_FKSTATE = {"PR": 15, "SP": 24, "SC": 23, "RS": 20}

# Site keys do reCAPTCHA v3 — cada portal usa uma chave própria
BLL_RECAPTCHA_SITEKEYS = {
    "https://bllcompras.com": "6LdpKvsmAAAAAA4rzH5iQNswgItyulQ1J2HQ1FkK",
    "https://bnccompras.com": "6LestvomAAAAAG9MNzlBaMEufF1QLdpKoL48qGsq",
}


def _resolver_recaptcha_v3(base_url: str) -> str | None:
    """Resolve reCAPTCHA v3 invisível via 2captcha. Retorna token ou None."""
    if not CAPTCHA_API_KEY:
        return None
    sitekey = BLL_RECAPTCHA_SITEKEYS.get(base_url)
    if not sitekey:
        print(f"  [2captcha] Sitekey desconhecida para {base_url}")
        return None
    try:
        from twocaptcha import TwoCaptcha
        solver = TwoCaptcha(CAPTCHA_API_KEY)
        result = solver.recaptcha(
            sitekey=sitekey,
            url=f"{base_url}/Participant",
            version="v3",
            action="submit",
            score=0.3,
        )
        return result.get("code")
    except Exception as e:
        print(f"  [2captcha] Falha ao resolver: {e}")
        return None


def _criar_sessao_bll(base_url: str) -> requests.Session | None:
    """Faz login no BLL/BNC e retorna sessão autenticada."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    })
    try:
        # 1. Pega a página de login para capturar cookies de sessão
        login_page = session.get(f"{base_url}/Home/Login", timeout=20)
        if login_page.status_code != 200:
            print(f"  [BLL Login] Erro ao carregar página: HTTP {login_page.status_code}")
            return None

        # 2. POST do login
        resp = session.post(
            f"{base_url}/Home/Login",
            data={"Email": BLL_USER, "Password": BLL_PASS},
            headers={"Content-Type": "application/x-www-form-urlencoded",
                     "Referer": f"{base_url}/Home/Login"},
            allow_redirects=True,
            timeout=20,
        )
        # Autenticação bem-sucedida se não redireciona para Login novamente
        if "Login" in resp.url or resp.status_code != 200:
            print(f"  [BLL Login] Falha na autenticação — verifique credenciais/plano")
            return None

        print(f"  [BLL Login] Autenticado em {base_url}")
        return session
    except Exception as e:
        print(f"  [BLL Login] {e}")
        return None


def _buscar_bll_bnc(portal: str, base_url: str, uf: str, session: requests.Session = None) -> list[dict]:
    """Busca um estado no BLL/BNC. Fluxo:
       1. Listagem autenticada (1 reCAPTCHA v3) → HTML com ~100 <tr>, sem o objeto/descrição
       2. Pra cada <tr>, GET em /Process/ProcessView (sem captcha) → extrai objeto
       3. Filtra por keyword no objeto
    """
    import re, html as html_lib
    resultados = []
    if session is None:
        return resultados
    fkstate_cod = BLL_FKSTATE.get(uf)
    if fkstate_cod is None:
        print(f"  [{portal}/{uf}] UF sem código BLL mapeado, pulando")
        return resultados

    # 1. Listagem (1 captcha)
    token = _resolver_recaptcha_v3(base_url)
    if not token:
        print(f"  [{portal}/{uf}] Sem token reCAPTCHA, abortando")
        return resultados
    try:
        r = session.post(
            f"{base_url}/Participant/GetProcessByParams",
            data={
                "Organization":     "",
                "Number":           "",
                "City":             "",
                "fkState":          fkstate_cod,
                "fkModality":       "",
                "fkStatus":         "",
                "fkDisputeKind":    "",
                "DateStart":        DATA_I_DISPLAY,
                "DateEnd":          DATA_F_DISPLAY,
                "DateStartDispute": "",
                "DateEndDispute":   "",
                "Offset":           0,
                "token":            token,
            },
            headers={
                "Content-Type":     "application/x-www-form-urlencoded",
                "X-Requested-With": "XMLHttpRequest",
                "Referer":          f"{base_url}/Participant",
            },
            timeout=45,
        )
        if r.status_code != 200:
            print(f"  [{portal}/{uf}] HTTP {r.status_code} na listagem")
            return resultados
        dados = r.json()
        if dados.get("modal") == "error":
            msg = re.sub(r"<[^>]+>", " ", dados.get("html", ""))
            msg = re.sub(r"\s+", " ", msg).strip()[:120]
            print(f"  [{portal}/{uf}] ⚠️ Erro do portal: {msg}")
            return resultados
        html_listagem = dados.get("html", "")
    except Exception as e:
        print(f"  [{portal}/{uf}] Erro listagem: {e}")
        return resultados

    # 2. Parse HTML — extrai metadados + link de ProcessView de cada <tr>
    def _clean(s: str) -> str:
        s = re.sub(r"<[^>]+>", " ", s)
        s = html_lib.unescape(s)
        return re.sub(r"\s+", " ", s).strip()

    candidatos = []
    for tr_html in re.findall(r"<tr[^>]*>(.*?)</tr>", html_listagem, re.DOTALL):
        m_href = re.search(r'href="(/Process/ProcessView\?param1=[^"]+)"', tr_html)
        if not m_href:
            continue
        tds = re.findall(r"<td[^>]*>(.*?)</td>", tr_html, re.DOTALL)
        if len(tds) < 8:
            continue
        # tds[7] = data da disputa "DD/MM/YYYY HH:MM" — usar pra filtrar editais vencidos
        data_disp = _clean(tds[7])[:10] if len(tds) > 7 else ""
        if not edital_vigente(data_disp):
            continue
        candidatos.append({
            "link_view":  base_url + m_href.group(1).replace("&amp;", "&"),
            "orgao":      _clean(tds[1]),
            "numero":     _clean(tds[2]),
            "modalidade": _clean(tds[3]),
            "cidade":     _clean(tds[4]),
            "status":     _clean(tds[5]),
            "data_pub":   _clean(tds[6])[:16],
            "data_disp":  data_disp,
        })

    if not candidatos:
        print(f"  [{portal}/{uf}] Listagem vazia")
        return resultados

    # 3. Pra cada candidato, GET detalhes (sem captcha, ~0.2s) e extrai objeto
    def _objeto_de(link_view: str) -> str:
        try:
            rr = session.get(link_view, timeout=20)
            if rr.status_code != 200:
                return ""
            m_obj = re.search(r">Objeto:?</[^>]+>\s*<[^>]+>([^<]+)<", rr.text, re.IGNORECASE)
            return html_lib.unescape(m_obj.group(1)).strip() if m_obj else ""
        except Exception:
            return ""

    with ThreadPoolExecutor(max_workers=8) as ex:
        objetos = list(ex.map(_objeto_de, [c["link_view"] for c in candidatos]))

    for cand, objeto in zip(candidatos, objetos):
        if not objeto or not contem_keyword(objeto, uf):
            continue
        resultados.append({
            "portal":     portal,
            "uf":         uf,
            "orgao":      cand["orgao"],
            "objeto":     objeto[:200],
            "valor":      "—",
            "modalidade": cand["modalidade"],
            "data":       cand["data_disp"] or cand["data_pub"][:10] or "—",
            "link":       cand["link_view"],
        })
    return resultados


def buscar_bll() -> list[dict]:
    editais = []
    if not BLL_ATIVO:
        falta = []
        if not BLL_PASS: falta.append("BLL_PASS")
        if not CAPTCHA_API_KEY: falta.append("CAPTCHA_API_KEY")
        print(f"[BLL] Pulado — secrets faltando: {', '.join(falta)}")
        return editais
    sessao = _criar_sessao_bll("https://bllcompras.com")
    if not sessao:
        return editais
    with ThreadPoolExecutor(max_workers=4) as ex:
        futuros = {ex.submit(_buscar_bll_bnc, "BLL", "https://bllcompras.com", uf, sessao): uf for uf in ESTADOS}
        for f in as_completed(futuros):
            editais += f.result()
    print(f"[BLL] {len(editais)} editais encontrados")
    return editais


# ──────────────────────────────────────────────
# 4. BNC Compras — mesma plataforma que BLL
# ──────────────────────────────────────────────
def buscar_bnc() -> list[dict]:
    editais = []
    if not BLL_ATIVO:
        falta = []
        if not BLL_PASS: falta.append("BLL_PASS")
        if not CAPTCHA_API_KEY: falta.append("CAPTCHA_API_KEY")
        print(f"[BNC] Pulado — secrets faltando: {', '.join(falta)}")
        return editais
    sessao = _criar_sessao_bll("https://bnccompras.com")
    if not sessao:
        return editais
    with ThreadPoolExecutor(max_workers=4) as ex:
        futuros = {ex.submit(_buscar_bll_bnc, "BNC", "https://bnccompras.com", uf, sessao): uf for uf in ESTADOS}
        for f in as_completed(futuros):
            editais += f.result()
    print(f"[BNC] {len(editais)} editais encontrados")
    return editais


# ──────────────────────────────────────────────
# 5. DIOE-PR (Diário Oficial Executivo do Paraná)
#    Cobre Copel, Sanepar, Compagás, Cohapar, gov PR, prefeituras PR.
#    Busca exige CAPTCHA visual — resolvido via 2captcha (modo image).
# ──────────────────────────────────────────────
DIOE_BASE = "https://www.documentos.dioe.pr.gov.br/dioe"

# DIOE-PR exige termos SEM acento (testado 10/05 — "gráfica" retorna 0, "grafica" retorna 16).
# Diário com mais volume pra material gráfico/comunicação visual: ComInd (cod 2).
DIOE_KEYWORDS = [
    "grafica",
    "impressao",
    "sinalizacao",
    "comunicacao visual",
    "totem",
    "adesivo",
    "fachada",
    "vinil",
]

DIOE_DIARIO_CODIGO = 2  # Comércio, Indústria e Serviços — onde gráfica/CV aparecem
DIOE_DIARIO_NOME   = "Com/Ind/Serv"


def _resolver_captcha_image(b64: str) -> str | None:
    """Resolve CAPTCHA visual (imagem) via 2captcha. Retorna texto ou None."""
    if not CAPTCHA_API_KEY:
        return None
    try:
        from twocaptcha import TwoCaptcha
        solver = TwoCaptcha(CAPTCHA_API_KEY)
        result = solver.normal(b64)
        return result.get("code")
    except Exception as e:
        print(f"  [2captcha image] Falha: {e}")
        return None


def _buscar_dioe_termo(termo: str) -> list[dict]:
    """Busca 1 termo no DIOE-PR Executivo. Retorna matches deduplicados."""
    import base64, re, html as html_lib
    resultados = []
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
    try:
        # 1. Sessão (cookies)
        s.get(f"{DIOE_BASE}/consultaPublicaPDF.do?action=pgLocalizar", timeout=30)
        # 2. Imagem do captcha
        r_img = s.get(f"{DIOE_BASE}/consultaPublicaPDF.do?action=imagemVerificacao", timeout=30)
        if r_img.status_code != 200 or len(r_img.content) < 100:
            return resultados
        captcha_texto = _resolver_captcha_image(base64.b64encode(r_img.content).decode())
        if not captcha_texto:
            return resultados
        # 3. Busca (janela 15 dias retroativos — editais publicados ainda em prazo)
        data_ini = (HOJE - timedelta(days=15)).strftime("%d/%m/%Y")
        data_fim = HOJE.strftime("%d/%m/%Y")
        r = s.get(f"{DIOE_BASE}/consultaPublicaPDF.do", params={
            "action":               "pgLocalizar",
            "enviado":              "true",
            "search":               termo,
            "dataInicialEntrada":   data_ini,
            "dataFinalEntrada":     data_fim,
            "diarioCodigo":         DIOE_DIARIO_CODIGO,
            "imagemVerificacao":    captcha_texto,
        }, timeout=30)
        if r.status_code != 200:
            return resultados
        # Verifica se captcha foi rejeitado ou sem resultados
        if "Para continuar" in r.text and "informação da imagem" in r.text:
            print(f"  [DIOE/{termo}] CAPTCHA rejeitado")
            return resultados
        if "Não encontramos" in r.text or "N&atilde;o encontramos" in r.text:
            return resultados
        # 4. Parse — cada bloco começa em destaqueImg(...)
        blocos = re.split(r"destaqueImg\(", r.text)[1:]
        for bloco in blocos[:50]:  # limite de segurança
            m_id   = re.search(r"'([A-Za-z0-9_]+)_(\d+)'", bloco)
            m_edi  = re.search(r"N.{1,3} da Edi.{1,3}o:</td>\s*<td[^>]*>(\d+)", bloco)
            m_dat  = re.search(r"Data da Publica.{1,3}o:</td>\s*<td[^>]*>(\d{2}/\d{2}/\d{4})", bloco)
            m_rel  = re.search(r"Grau de relev.{1,3}ncia:</td>\s*<td[^>]*>([\d,.]+)%", bloco)
            if not (m_id and m_dat):
                continue
            id_pag = m_id.group(1); num_pag = m_id.group(2)
            edicao_str = m_edi.group(1) if m_edi else ""
            # Link clicável aponta pra busca da edição no DIOE — usuário resolve 1 captcha
            # no site e baixa o PDF vetorial legível. O PNG bruto da página existe em
            # ?action=imgPaginaPNG mas vem em resolução baixa demais pra ser útil.
            link_edicao = (
                f"{DIOE_BASE}/consultaPublicaPDF.do?action=pgLocalizar&enviado=true"
                f"&numero={edicao_str}&diarioCodigo={DIOE_DIARIO_CODIGO}"
                f"&dataInicialEntrada=&dataFinalEntrada=&search="
            ) if edicao_str else f"{DIOE_BASE}/consultaPublicaPDF.do?action=pgLocalizar"
            resultados.append({
                "portal":     "DIOE-PR",
                "uf":         "PR",
                "orgao":      f"Diário {DIOE_DIARIO_NOME}",
                "objeto":     f'"{termo}" — Edição {edicao_str or "?"}, pág {num_pag}' + (f" (relevância {m_rel.group(1)}%)" if m_rel else ""),
                "valor":      "—",
                "modalidade": "—",
                "data":       m_dat.group(1),
                "link":       link_edicao,
                "_dedup_key": (edicao_str, num_pag),
            })
    except Exception as e:
        print(f"  [DIOE/{termo}] erro: {e}")
    return resultados


def buscar_dioe_pr() -> list[dict]:
    editais = []
    if not CAPTCHA_API_KEY:
        print("[DIOE-PR] Pulado — CAPTCHA_API_KEY não configurado")
        return editais
    # Busca paralela por termo (3 workers — DIOE-PR é lento mas não bloqueia)
    with ThreadPoolExecutor(max_workers=3) as ex:
        for matches in ex.map(_buscar_dioe_termo, DIOE_KEYWORDS):
            editais += matches
    # Dedup por (data, edição, página) — mesmo edital pode aparecer em vários termos.
    vistos = set()
    unicos = []
    for e in editais:
        chave = (e["data"],) + e.get("_dedup_key", (e["link"],))
        if chave in vistos:
            continue
        vistos.add(chave)
        e.pop("_dedup_key", None)
        unicos.append(e)
    print(f"[DIOE-PR] {len(unicos)} matches únicos encontrados ({len(editais)} brutos)")
    return unicos


# ──────────────────────────────────────────────
# 6. Licitanet
# ──────────────────────────────────────────────
def buscar_licitanet() -> list[dict]:
    editais = []
    try:
        r = requests.get(
            "https://www.licitanet.com.br/licitacoes",
            params={"busca": "grafica comunicacao visual banner adesivo lona placa sinalizacao acm", "uf": ",".join(ESTADOS), "pagina": 1},
            headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
            timeout=20,
        )
        if r.status_code == 200:
            try:
                dados = r.json()
                itens = dados.get("licitacoes", dados.get("itens", dados.get("data", [])))
                for item in itens:
                    objeto = item.get("objeto", item.get("descricao", "")) or ""
                    if contem_keyword(objeto):
                        editais.append({
                            "portal":     "Licitanet",
                            "uf":         item.get("uf", item.get("estado", "—")),
                            "orgao":      item.get("orgao", item.get("nomeOrgao", "—")),
                            "objeto":     objeto[:200],
                            "valor":      formatar_moeda(item.get("valor", item.get("valorEstimado"))),
                            "modalidade": item.get("modalidade", "—"),
                            "data":       str(item.get("dataPublicacao", ""))[:10] or "—",
                            "link":       item.get("link", "https://www.licitanet.com.br"),
                        })
            except Exception:
                pass
    except Exception as e:
        print(f"  [Licitanet] {e}")

    print(f"[Licitanet] {len(editais)} editais encontrados")
    return editais


# ──────────────────────────────────────────────
# 6. Portal de Compras Públicas
# ──────────────────────────────────────────────
def buscar_compras_publicas() -> list[dict]:
    editais = []
    try:
        r = requests.get(
            "https://www.portaldecompraspublicas.com.br/18/processos/",
            params={"busca": "grafica comunicacao visual banner adesivo lona placa sinalizacao acm", "estados": ",".join(ESTADOS)},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=20,
        )
        if r.status_code == 200:
            try:
                dados = r.json()
                itens = dados.get("data", dados.get("processos", []))
                for item in itens:
                    objeto = item.get("objeto", "") or ""
                    if contem_keyword(objeto):
                        editais.append({
                            "portal":     "Compras Públicas",
                            "uf":         item.get("uf", "—"),
                            "orgao":      item.get("orgao", "—"),
                            "objeto":     objeto[:200],
                            "valor":      formatar_moeda(item.get("valor")),
                            "modalidade": item.get("modalidade", "—"),
                            "data":       str(item.get("data", ""))[:10] or "—",
                            "link":       item.get("link", "https://www.portaldecompraspublicas.com.br"),
                        })
            except Exception:
                pass
    except Exception as e:
        print(f"  [Compras Públicas] {e}")

    print(f"[Compras Públicas] {len(editais)} editais encontrados")
    return editais


# ──────────────────────────────────────────────
# HTML DO E-MAIL
# ──────────────────────────────────────────────
def montar_html(editais: list[dict]) -> str:
    total = len(editais)

    if total == 0:
        corpo = "<p style='color:#666;font-size:14px;'>Nenhum edital relevante encontrado hoje nos portais monitorados.</p>"
    else:
        linhas = ""
        for i, e in enumerate(editais):
            bg = "#f9f9f9" if i % 2 == 0 else "#ffffff"
            link_html = f'<a href="{e["link"]}" style="color:#1a73e8;white-space:nowrap;">Ver edital</a>' if e.get("link") else "—"
            linhas += f"""
            <tr style="background:{bg};">
              <td style="padding:8px 10px;border:1px solid #e0e0e0;">{e['portal']}</td>
              <td style="padding:8px 10px;border:1px solid #e0e0e0;text-align:center;">{e['uf']}</td>
              <td style="padding:8px 10px;border:1px solid #e0e0e0;">{e['orgao']}</td>
              <td style="padding:8px 10px;border:1px solid #e0e0e0;">{e['objeto']}</td>
              <td style="padding:8px 10px;border:1px solid #e0e0e0;white-space:nowrap;">{e['valor']}</td>
              <td style="padding:8px 10px;border:1px solid #e0e0e0;">{e['modalidade']}</td>
              <td style="padding:8px 10px;border:1px solid #e0e0e0;white-space:nowrap;">{e['data']}</td>
              <td style="padding:8px 10px;border:1px solid #e0e0e0;">{link_html}</td>
            </tr>"""

        corpo = f"""
        <table style="border-collapse:collapse;width:100%;font-size:13px;">
          <thead>
            <tr style="background:#1a73e8;color:#fff;">
              <th style="padding:10px;border:1px solid #1558b0;text-align:left;">Portal</th>
              <th style="padding:10px;border:1px solid #1558b0;text-align:center;">UF</th>
              <th style="padding:10px;border:1px solid #1558b0;text-align:left;">Órgão</th>
              <th style="padding:10px;border:1px solid #1558b0;text-align:left;">Objeto</th>
              <th style="padding:10px;border:1px solid #1558b0;text-align:left;">Valor Est.</th>
              <th style="padding:10px;border:1px solid #1558b0;text-align:left;">Modalidade</th>
              <th style="padding:10px;border:1px solid #1558b0;text-align:left;">Data</th>
              <th style="padding:10px;border:1px solid #1558b0;text-align:left;">Link</th>
            </tr>
          </thead>
          <tbody>{linhas}</tbody>
        </table>"""

    html = f"""<!DOCTYPE html>
<html>
<body style="font-family:Arial,sans-serif;max-width:1200px;margin:0 auto;padding:20px;background:#f4f4f4;">
  <div style="background:#1a73e8;color:#fff;padding:20px 25px;border-radius:8px 8px 0 0;">
    <h2 style="margin:0;font-size:20px;">JK Artes Gráficas — Monitoramento de Licitações</h2>
    <p style="margin:6px 0 0;font-size:13px;opacity:.9;">
      Publicações de {DATA_I_DISPLAY} a {DATA_F_DISPLAY} &nbsp;|&nbsp;
      <strong>{total} edital(is) com abertura ≥ hoje</strong> &nbsp;|&nbsp;
      Estados: PR · SP · SC · RS
    </p>
  </div>
  <div style="background:#fff;padding:20px;border:1px solid #ddd;border-top:none;border-radius:0 0 8px 8px;overflow-x:auto;">
    {corpo}
    <hr style="margin-top:30px;border:none;border-top:1px solid #eee;">
    <p style="font-size:11px;color:#999;margin:10px 0 0;">
      Portais monitorados: PNCP (Publicações + Busca) · BLL Compras · BNC Compras · Licitanet · Portal de Compras Públicas<br>
      Modalidades: Pregão Eletrônico · Pregão Presencial · Concorrência · Dispensa · Inexigibilidade<br>
      Enviado automaticamente todo dia às 7h pelo sistema JK Licitações via GitHub Actions.
    </p>
  </div>
</body>
</html>"""
    return html


# ──────────────────────────────────────────────
# ENVIAR E-MAIL VIA GMAIL SMTP
# ──────────────────────────────────────────────
def enviar_email(html: str, total: int):
    assunto = f"Licitações JK — {total} edital(is) vigentes | publicações {DATA_I_DISPLAY}-{DATA_F_DISPLAY}"
    msg = MIMEMultipart("alternative")
    msg["Subject"] = assunto
    msg["From"]    = f"{EMAIL_FROM_NAME} <{GMAIL_USER}>"
    msg["To"]      = EMAIL_DESTINO
    msg["Cc"]      = EMAIL_COPIA
    msg.attach(MIMEText(html, "html", "utf-8"))

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.ehlo()
        server.starttls()
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_USER, [EMAIL_DESTINO, EMAIL_COPIA], msg.as_string())
    print(f"[EMAIL] Enviado: {assunto}")


# ──────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────
if __name__ == "__main__":
    print(f"=== JK Licitações — {HOJE.strftime('%d/%m/%Y %H:%M')} ===")
    print(f"Período: {DATA_I_DISPLAY} a {DATA_F_DISPLAY}")
    print(f"Estados: {', '.join(ESTADOS)}")
    print()

    todos = []
    todos += buscar_pncp_publicacoes()   # API oficial por UF+data+modalidade
    todos += buscar_pncp_texto()         # Busca por termos (complementar)
    todos += buscar_bll()               # BLL Compras — busca pública por estado+data
    todos += buscar_bnc()               # BNC Compras — mesma plataforma que BLL
    todos += buscar_dioe_pr()           # DIOE-PR (Copel, Sanepar, gov PR) via captcha visual
    todos += buscar_licitanet()         # Licitanet
    todos += buscar_compras_publicas()  # Portal de Compras Públicas

    # Deduplicar por orgao+objeto
    vistos = set()
    unicos = []
    for e in todos:
        chave = (e["orgao"].lower()[:30], e["objeto"].lower()[:50])
        if chave not in vistos:
            vistos.add(chave)
            unicos.append(e)

    # Ordenar: portal, uf, data
    unicos.sort(key=lambda x: (x["portal"], x["uf"], x["data"]), reverse=False)

    print(f"\n=== Total único: {len(unicos)} editais ===\n")
    html = montar_html(unicos)
    enviar_email(html, len(unicos))
    print("=== Concluído ===")
