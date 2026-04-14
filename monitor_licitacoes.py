import requests
import json
from datetime import datetime, timedelta
import os

# ──────────────────────────────────────────────
# CONFIGURAÇÃO
# ──────────────────────────────────────────────
BREVO_API_KEY = os.environ.get("BREVO_API_KEY", "")
EMAIL_DESTINO = "licitacao.jkartesgraficas@gmail.com"
EMAIL_FROM = "a7c066001@smtp-brevo.com"
EMAIL_FROM_NAME = "JK Licitações"

KEYWORDS = [
    "gráfica", "grafica", "gráfico", "grafico", "gráficos", "graficos",
    "impressão", "impressao", "impressos", "imprimir",
    "banner", "faixa", "lona", "vinil", "adesivo",
    "comunicação visual", "comunicacao visual",
    "plotagem", "ploter", "plotter",
    "folder", "panfleto", "cartaz", "panfletos", "cartazes",
    "material gráfico", "material grafico", "serviço gráfico", "servico grafico",
    "offset", "off-set", "serigrafia", "sublimação", "sublimacao",
    "brochura", "catálogo", "catalogo", "etiqueta",
    "embalagem", "confecção de carimbos", "confeccao de carimbos",
    "diagramação", "diagramacao",
]

ESTADOS = ["PR", "SP", "SC", "RS"]

HOJE = datetime.now()
ONTEM = HOJE - timedelta(days=1)
DATA_CORTE = (HOJE - timedelta(days=30)).strftime("%Y-%m-%d")   # aceita até 30 dias
DATA_INICIAL = ONTEM.strftime("%Y%m%d")
DATA_FINAL = HOJE.strftime("%Y%m%d")


# ──────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────
def contem_keyword(texto: str) -> bool:
    if not texto:
        return False
    texto_lower = texto.lower()
    return any(kw in texto_lower for kw in KEYWORDS)


def formatar_moeda(valor) -> str:
    try:
        return f"R$ {float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return str(valor) if valor else "—"


# ──────────────────────────────────────────────
# 1. PNCP (Portal Nacional de Contratações Públicas)
# ──────────────────────────────────────────────
def buscar_pncp() -> list[dict]:
    editais = []
    vistos = set()
    TERMOS_PNCP = [
        "grafica",
        "impressao grafica",
        "servicos graficos",
        "banner comunicacao visual",
        "material grafico",
    ]
    for termo in TERMOS_PNCP:
        try:
            url = "https://pncp.gov.br/api/search"
            params = {"q": termo, "tipos_documento": "edital", "pagina": 1, "tam_pagina": 20}
            r = requests.get(url, params=params, timeout=30)
            if r.status_code != 200:
                continue
            itens = r.json().get("items", [])
            for item in itens:
                uf = item.get("uf", "")
                if uf not in ESTADOS:
                    continue
                data_pub = item.get("data_publicacao_pncp", item.get("createdAt", ""))[:10]
                if data_pub < DATA_CORTE:
                    continue
                objeto = item.get("description", "") or item.get("title", "")
                chave = item.get("id", objeto[:40])
                if chave in vistos:
                    continue
                vistos.add(chave)
                item_url = item.get("item_url", "")
                editais.append({
                    "portal": "PNCP",
                    "uf": uf,
                    "orgao": item.get("orgao_nome", "—"),
                    "objeto": objeto[:200],
                    "valor": formatar_moeda(item.get("valor_global")),
                    "modalidade": item.get("modalidade_licitacao_nome", "—"),
                    "data": data_pub,
                    "link": f"https://pncp.gov.br{item_url}" if item_url else "https://pncp.gov.br",
                })
        except Exception as e:
            print(f"[PNCP/{termo}] Erro: {e}")
    print(f"[PNCP] {len(editais)} editais encontrados")
    return editais


# ──────────────────────────────────────────────
# 2. BLL Compras
# ──────────────────────────────────────────────
def buscar_bll() -> list[dict]:
    editais = []
    try:
        url = "https://bllcompras.com/Home/SearchEditalPublic"
        headers = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}
        payload = {
            "Palavras": "grafica impressao banner comunicacao visual",
            "Estados": ",".join(ESTADOS),
            "PageIndex": 1,
            "PageSize": 50,
        }
        r = requests.post(url, json=payload, headers=headers, timeout=20)
        if r.status_code == 200:
            itens = r.json().get("Editais", []) or []
            for item in itens:
                objeto = item.get("Objeto", "") or ""
                if contem_keyword(objeto):
                    editais.append({
                        "portal": "BLL",
                        "uf": item.get("Estado", "—"),
                        "orgao": item.get("NomeOrgao", "—"),
                        "objeto": objeto[:200],
                        "valor": formatar_moeda(item.get("ValorEstimado")),
                        "modalidade": item.get("Modalidade", "—"),
                        "data": item.get("DataPublicacao", "")[:10] if item.get("DataPublicacao") else "—",
                        "link": f"https://bllcompras.com{item.get('UrlEdital', '')}",
                    })
    except Exception as e:
        print(f"[BLL] Erro: {e}")
    print(f"[BLL] {len(editais)} editais encontrados")
    return editais


# ──────────────────────────────────────────────
# 3. Licitanet
# ──────────────────────────────────────────────
def buscar_licitanet() -> list[dict]:
    editais = []
    try:
        url = "https://www.licitanet.com.br/api/licitacao/busca"
        headers = {"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"}
        payload = {
            "texto": "grafica impressao",
            "estados": ESTADOS,
            "pagina": 1,
            "itensPorPagina": 50,
        }
        r = requests.post(url, json=payload, headers=headers, timeout=20)
        if r.status_code == 200:
            dados = r.json()
            itens = dados.get("licitacoes", dados.get("itens", dados.get("data", [])))
            for item in itens:
                objeto = item.get("objeto", item.get("descricao", "")) or ""
                if contem_keyword(objeto):
                    editais.append({
                        "portal": "Licitanet",
                        "uf": item.get("uf", item.get("estado", "—")),
                        "orgao": item.get("orgao", item.get("nomeOrgao", "—")),
                        "objeto": objeto[:200],
                        "valor": formatar_moeda(item.get("valor", item.get("valorEstimado"))),
                        "modalidade": item.get("modalidade", "—"),
                        "data": str(item.get("dataPublicacao", ""))[:10] or "—",
                        "link": item.get("link", item.get("url", "https://www.licitanet.com.br")),
                    })
    except Exception as e:
        print(f"[Licitanet] Erro: {e}")
    print(f"[Licitanet] {len(editais)} editais encontrados")
    return editais


# ──────────────────────────────────────────────
# 4. Portal de Compras Públicas
# ──────────────────────────────────────────────
def buscar_compras_publicas() -> list[dict]:
    editais = []
    try:
        url = "https://www.portaldecompraspublicas.com.br/18/processos/"
        params = {
            "busca": "grafica impressao banner comunicacao visual",
            "estados": ",".join(ESTADOS),
        }
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, params=params, headers=headers, timeout=20)
        if r.status_code == 200:
            # Tentativa de parsing JSON se disponível
            try:
                dados = r.json()
                itens = dados.get("data", dados.get("processos", []))
                for item in itens:
                    objeto = item.get("objeto", "") or ""
                    if contem_keyword(objeto):
                        editais.append({
                            "portal": "Compras Públicas",
                            "uf": item.get("uf", "—"),
                            "orgao": item.get("orgao", "—"),
                            "objeto": objeto[:200],
                            "valor": formatar_moeda(item.get("valor")),
                            "modalidade": item.get("modalidade", "—"),
                            "data": str(item.get("data", ""))[:10] or "—",
                            "link": item.get("link", "https://www.portaldecompraspublicas.com.br"),
                        })
            except Exception:
                pass
    except Exception as e:
        print(f"[Compras Públicas] Erro: {e}")
    print(f"[Compras Públicas] {len(editais)} editais encontrados")
    return editais


# ──────────────────────────────────────────────
# MONTAR HTML DO E-MAIL
# ──────────────────────────────────────────────
def montar_html(editais: list[dict]) -> str:
    data_ref = HOJE.strftime("%d/%m/%Y")
    total = len(editais)

    if total == 0:
        corpo = "<p style='color:#666;'>Nenhum edital relevante encontrado hoje nos portais monitorados.</p>"
    else:
        linhas = ""
        for i, e in enumerate(editais):
            bg = "#f9f9f9" if i % 2 == 0 else "#ffffff"
            link_html = f'<a href="{e["link"]}" style="color:#1a73e8;">Ver edital</a>' if e.get("link") else "—"
            linhas += f"""
            <tr style="background:{bg};">
              <td style="padding:8px;border:1px solid #ddd;">{e['portal']}</td>
              <td style="padding:8px;border:1px solid #ddd;">{e['uf']}</td>
              <td style="padding:8px;border:1px solid #ddd;">{e['orgao']}</td>
              <td style="padding:8px;border:1px solid #ddd;">{e['objeto']}</td>
              <td style="padding:8px;border:1px solid #ddd;white-space:nowrap;">{e['valor']}</td>
              <td style="padding:8px;border:1px solid #ddd;">{e['modalidade']}</td>
              <td style="padding:8px;border:1px solid #ddd;white-space:nowrap;">{e['data']}</td>
              <td style="padding:8px;border:1px solid #ddd;">{link_html}</td>
            </tr>"""

        corpo = f"""
        <table style="border-collapse:collapse;width:100%;font-size:13px;">
          <thead>
            <tr style="background:#1a73e8;color:#fff;">
              <th style="padding:10px;border:1px solid #ddd;text-align:left;">Portal</th>
              <th style="padding:10px;border:1px solid #ddd;text-align:left;">UF</th>
              <th style="padding:10px;border:1px solid #ddd;text-align:left;">Órgão</th>
              <th style="padding:10px;border:1px solid #ddd;text-align:left;">Objeto</th>
              <th style="padding:10px;border:1px solid #ddd;text-align:left;">Valor Est.</th>
              <th style="padding:10px;border:1px solid #ddd;text-align:left;">Modalidade</th>
              <th style="padding:10px;border:1px solid #ddd;text-align:left;">Data</th>
              <th style="padding:10px;border:1px solid #ddd;text-align:left;">Link</th>
            </tr>
          </thead>
          <tbody>{linhas}</tbody>
        </table>"""

    html = f"""<!DOCTYPE html>
<html>
<body style="font-family:Arial,sans-serif;max-width:1100px;margin:0 auto;padding:20px;">
  <div style="background:#1a73e8;color:#fff;padding:20px;border-radius:8px 8px 0 0;">
    <h2 style="margin:0;">JK Artes Gráficas — Monitoramento de Licitações</h2>
    <p style="margin:5px 0 0;">{data_ref} &nbsp;|&nbsp; {total} edital(is) encontrado(s) &nbsp;|&nbsp; Estados: PR, SP, SC, RS</p>
  </div>
  <div style="background:#fff;padding:20px;border:1px solid #ddd;border-top:none;border-radius:0 0 8px 8px;">
    {corpo}
    <hr style="margin-top:30px;border:none;border-top:1px solid #eee;">
    <p style="font-size:11px;color:#999;">
      Portais monitorados: PNCP · BLL · Licitanet · Portal de Compras Públicas<br>
      Palavras-chave: gráfica, impressão, banner, comunicação visual, plotagem, adesivo, folder, offset, serigrafia, sublimação e outros.<br>
      Enviado automaticamente pelo sistema JK Licitações via GitHub Actions.
    </p>
  </div>
</body>
</html>"""
    return html


# ──────────────────────────────────────────────
# ENVIAR E-MAIL VIA BREVO
# ──────────────────────────────────────────────
def enviar_email(html: str, total: int):
    data_ref = HOJE.strftime("%d/%m/%Y")
    assunto = f"Licitações JK — {total} edital(is) encontrado(s) em {data_ref}"

    payload = {
        "sender": {"name": EMAIL_FROM_NAME, "email": EMAIL_FROM},
        "to": [{"email": EMAIL_DESTINO}],
        "subject": assunto,
        "htmlContent": html,
    }
    headers = {
        "api-key": BREVO_API_KEY,
        "Content-Type": "application/json",
    }
    r = requests.post("https://api.brevo.com/v3/smtp/email", json=payload, headers=headers, timeout=20)
    if r.status_code in (200, 201):
        print(f"[EMAIL] Enviado com sucesso: {r.json().get('messageId')}")
    else:
        print(f"[EMAIL] Erro {r.status_code}: {r.text}")
        raise Exception(f"Falha ao enviar e-mail: {r.status_code}")


# ──────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────
if __name__ == "__main__":
    print(f"=== Monitoramento JK Licitações — {HOJE.strftime('%d/%m/%Y %H:%M')} ===")
    print(f"Período: {ONTEM.strftime('%d/%m/%Y')} a {HOJE.strftime('%d/%m/%Y')}")

    todos = []
    todos += buscar_pncp()
    todos += buscar_bll()
    todos += buscar_licitanet()
    todos += buscar_compras_publicas()

    # Deduplicar por objeto+orgao
    vistos = set()
    unicos = []
    for e in todos:
        chave = (e["orgao"], e["objeto"][:50])
        if chave not in vistos:
            vistos.add(chave)
            unicos.append(e)

    # Ordenar por portal
    unicos.sort(key=lambda x: (x["portal"], x["uf"]))

    print(f"\n=== Total de editais únicos: {len(unicos)} ===")
    html = montar_html(unicos)
    enviar_email(html, len(unicos))
    print("=== Concluído ===")
