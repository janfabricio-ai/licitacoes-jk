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
EMAIL_FROM_NAME    = "JK Licitações"

ESTADOS = ["PR", "SP", "SC", "RS"]

# Modalidades PNCP relevantes
MODALIDADES = {
    4: "Concorrência Eletrônica",
    5: "Concorrência Presencial",
    6: "Pregão Eletrônico",
    7: "Pregão Presencial",
    8: "Dispensa",
    9: "Inexigibilidade",
}

# Keywords específicas do segmento gráfica/comunicação visual
# Divididas em PRIMÁRIAS (match direto) e COMPOSTAS (precisam de contexto)
KEYWORDS_PRIMARIAS = [
    # Serviços gráficos
    "gráfica", "grafica",
    "serviço gráfico", "servico grafico",
    "serviços gráficos", "servicos graficos",
    "produção gráfica", "producao grafica",
    "material gráfico", "material grafico",
    "impressão gráfica", "impressao grafica",
    # Comunicação visual
    "comunicação visual", "comunicacao visual",
    # Técnicas específicas de impressão
    "offset", "off-set",
    "serigrafia",
    "sublimação", "sublimacao",
    "plotagem", "ploter", "plotter",
    # Produtos específicos
    "banner", "banners",
    "faixa", "faixas",
    "diagramação", "diagramacao",
]

KEYWORDS_COMPOSTAS = [
    # Termos que sozinhos são genéricos mas no contexto são válidos
    "impressão", "impressao",
    "panfleto", "panfletos",
    "cartaz", "cartazes",
    "folder", "folders",
    "lona", "vinil", "adesivo",
]

# Keywords exclusivas por estado
KEYWORDS_PR = [
    "proerd",
    "cartilha proerd",
]

# Termos que ELIMINAM o edital — fora do segmento
KEYWORDS_EXCLUSAO = [
    "pavimentação", "pavimentacao", "pavimento",
    "recape", "recapeamento", "asfalto", "asfáltico", "asfaltico",
    "obras de engenharia", "obra de engenharia",
    "construção", "construcao", "reforma predial",
    "drenagem", "esgoto", "saneamento",
    "terraplanagem", "aterro",
    "ponte", "viaduto", "galeria",
    "elétrica", "eletrica", "instalação elétrica",
    "hidráulica", "hidraulica",
    "lona de freio", "lona de caminhão",
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

HOJE   = datetime.now()
ONTEM  = HOJE - timedelta(days=1)
DATA_I = ONTEM.strftime("%Y%m%d")
DATA_F = HOJE.strftime("%Y%m%d")
DATA_I_DISPLAY = ONTEM.strftime("%d/%m/%Y")
DATA_F_DISPLAY = HOJE.strftime("%d/%m/%Y")


# ──────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────
def formatar_moeda(valor) -> str:
    try:
        return f"R$ {float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "—"


def safe_get(url, params=None, headers=None, timeout=25) -> dict | None:
    try:
        r = requests.get(url, params=params, headers=headers, timeout=timeout)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
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
                "data":       (item.get("dataPublicacaoPncp") or "")[:10],
                "link":       f"https://pncp.gov.br/app/editais/{cnpj}/{ano}/{seq}" if cnpj else "https://pncp.gov.br/app/editais",
                "_chave":     item.get("numeroControlePNCP", objeto[:40]),
            })
        total_pag = dados.get("totalPaginas", 1)
        if pagina >= total_pag or pagina >= 3:
            break
        pagina += 1
    return resultados


def buscar_pncp_publicacoes() -> list[dict]:
    editais = []
    vistos  = set()
    combinacoes = [(uf, cod, nome) for uf in ESTADOS for cod, nome in MODALIDADES.items()]

    with ThreadPoolExecutor(max_workers=8) as executor:
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
        "grafica impressao",
        "servicos graficos",
        "banner comunicacao visual",
        "material grafico impressos",
        "plotagem vinil adesivo",
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
                "data":       data_pub,
                "link":       link,
            })

    print(f"[PNCP Texto] {len(editais)} editais complementares encontrados")
    return editais


# ──────────────────────────────────────────────
# 3. BLL Compras — busca pública por estado + data, filtra por keyword
# ──────────────────────────────────────────────
def _buscar_bll_bnc(portal: str, base_url: str, uf: str) -> list[dict]:
    """Busca um estado no BLL ou BNC via endpoint público."""
    resultados = []
    offset = 0
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Content-Type": "application/x-www-form-urlencoded",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": f"{base_url}/Process/ProcessSearchPublic?param1=0",
    }
    while True:
        try:
            r = requests.post(
                f"{base_url}/Process/GetProcessByParams",
                data={
                    "Organization": "",
                    "Number":       "",
                    "City":         "",
                    "fkState":      uf,
                    "fkModality":   "",
                    "fkStatus":     "2",   # Publicado
                    "fkDisputeKind": "",
                    "DateStart":    DATA_I_DISPLAY,
                    "DateEnd":      DATA_F_DISPLAY,
                    "DateStartDispute": "",
                    "DateEndDispute":   "",
                    "Offset":       offset,
                    "token":        "",
                },
                headers=headers,
                timeout=25,
            )
            if r.status_code != 200:
                print(f"  [{portal}/{uf}] HTTP {r.status_code}")
                break
            dados = r.json()
            itens = dados if isinstance(dados, list) else dados.get("data", dados.get("Processos", dados.get("processes", [])))
            if not itens:
                break
            for item in itens:
                objeto = (
                    item.get("Description") or item.get("Objeto") or
                    item.get("objeto") or item.get("description") or ""
                )
                if not contem_keyword(objeto, uf):
                    continue
                url_edital = item.get("UrlProcess") or item.get("UrlEdital") or item.get("url") or ""
                resultados.append({
                    "portal":     portal,
                    "uf":         uf,
                    "orgao":      item.get("Organization") or item.get("NomeOrgao") or item.get("orgao") or "—",
                    "objeto":     objeto[:200],
                    "valor":      formatar_moeda(item.get("EstimatedValue") or item.get("ValorEstimado") or item.get("valor")),
                    "modalidade": item.get("Modality") or item.get("Modalidade") or item.get("modalidade") or "—",
                    "data":       str(item.get("PublicationDate") or item.get("DataPublicacao") or "")[:10] or "—",
                    "link":       f"{base_url}{url_edital}" if url_edital.startswith("/") else url_edital or base_url,
                })
            # Paginação: cada página tem 20 itens
            if len(itens) < 20:
                break
            offset += 20
        except Exception as e:
            print(f"  [{portal}/{uf}] {e}")
            break
    return resultados


def buscar_bll() -> list[dict]:
    editais = []
    with ThreadPoolExecutor(max_workers=4) as ex:
        futuros = {ex.submit(_buscar_bll_bnc, "BLL", "https://bllcompras.com", uf): uf for uf in ESTADOS}
        for f in as_completed(futuros):
            editais += f.result()
    print(f"[BLL] {len(editais)} editais encontrados")
    return editais


# ──────────────────────────────────────────────
# 4. BNC Compras — mesma plataforma que BLL
# ──────────────────────────────────────────────
def buscar_bnc() -> list[dict]:
    editais = []
    with ThreadPoolExecutor(max_workers=4) as ex:
        futuros = {ex.submit(_buscar_bll_bnc, "BNC", "https://bnccompras.com", uf): uf for uf in ESTADOS}
        for f in as_completed(futuros):
            editais += f.result()
    print(f"[BNC] {len(editais)} editais encontrados")
    return editais


# ──────────────────────────────────────────────
# 5. Licitanet
# ──────────────────────────────────────────────
def buscar_licitanet() -> list[dict]:
    editais = []
    try:
        r = requests.get(
            "https://www.licitanet.com.br/licitacoes",
            params={"busca": "grafica impressao banner", "uf": ",".join(ESTADOS), "pagina": 1},
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
            params={"busca": "grafica impressao banner", "estados": ",".join(ESTADOS)},
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
      {DATA_I_DISPLAY} a {DATA_F_DISPLAY} &nbsp;|&nbsp;
      <strong>{total} edital(is) encontrado(s)</strong> &nbsp;|&nbsp;
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
    assunto = f"Licitações JK — {total} edital(is) | {DATA_I_DISPLAY} a {DATA_F_DISPLAY}"
    msg = MIMEMultipart("alternative")
    msg["Subject"] = assunto
    msg["From"]    = f"{EMAIL_FROM_NAME} <{GMAIL_USER}>"
    msg["To"]      = EMAIL_DESTINO
    msg.attach(MIMEText(html, "html", "utf-8"))

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.ehlo()
        server.starttls()
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_USER, EMAIL_DESTINO, msg.as_string())
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
