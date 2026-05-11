"""
Triagem inteligente de editais usando Claude API.

Fluxo:
- Fase 1 (Haiku 4.5): classifica TODOS os editais por categoria JK pelo objeto curto.
  System prompt grande (carteira de produtos) com prompt caching = 1 cache miss + N hits.
- Fase 2 (Sonnet 4.6): só nos PNCP que passaram Fase 1. Baixa itens via API PNCP
  e extrai specs detalhadas (gramatura, formato, qtd, prazo, valor).

Saída: lista de matches (subset dos editais originais) + email separado.
Falhas individuais NÃO interrompem o fluxo — script principal já enviou o email completo.
"""

import os
import json
import re
import smtplib
import requests
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from concurrent.futures import ThreadPoolExecutor

try:
    from anthropic import Anthropic
except ImportError:
    Anthropic = None


ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

MODEL_FASE1 = "claude-haiku-4-5"
MODEL_FASE2 = "claude-sonnet-4-6"

# ──────────────────────────────────────────────
# CARTEIRA JK (vai no system prompt, com cache)
# ──────────────────────────────────────────────
CARTEIRA_PROMPT = """Você é um classificador de editais de licitação para a JK Artes Gráficas.

A JK fabrica internamente OU revende os seguintes produtos:

[MATERIAL GRÁFICO]
- pasta (com aba, sem aba, em couché ou cartão)
- cartão de visita
- cartilha (PROERD, infantil, escolar, instrucional)
- folder
- panfleto
- flyer
- bloco em geral (de notas, de pedido, de receita médica, autocopiativo, numerado, receituário)
- talão
- talonário
- crachá (PVC, papel, com cordão)
- livro
- brochura
- encadernação
- convite
- agenda
- certificado (papel especial, com brasão, diploma)
- revista
- cartaz (cartazete, pôster)
- broche (metal, acrílico, papel)

[COMUNICAÇÃO VISUAL]
- fachada comercial (ACM, letra caixa em PVC/inox/acrílico)
- banner (lona, tecido)
- faixa
- lona impressa
- adesivo
- vinil (recorte ou impressão digital)
- placa de sinalização (interna, externa, indicativa)
- letreiro
- luminoso (LED, neon)
- totem
- backdrop
- painel de evento

REGRAS DE CLASSIFICAÇÃO:
1. Receba o objeto/órgão de um edital e identifique TODOS os produtos da carteira JK que aparecem.
2. Use os NOMES EXATOS da lista acima (categoria principal). Ex: "cartão de visita", não "cartão".
3. Se um item está descrito com sinônimo (ex: "díptico" → folder, "pôster" → cartaz), traduza pra categoria JK.
4. NÃO inclua produtos relacionados que a JK não faz. Ex: "uniforme escolar" → não é cartilha; "fardamento" → não é nada.
5. Em "fachada", inclua APENAS comercial/empresarial (ACM, letras caixa). NÃO inclua "fachada predial reforma" (obra civil).
6. Se NENHUM produto da carteira aparecer, retorne lista vazia.

FORMATO DE RESPOSTA: APENAS JSON puro, sem markdown, sem comentários, sem texto antes/depois:
{"produtos": ["nome1", "nome2"], "confianca": "alta"}

Confiança:
- "alta": produto mencionado claramente
- "media": ambíguo ou sinônimo não-direto
- "baixa": pode ser produto JK mas contexto pouco claro

Se lista vazia, sempre confiança "alta"."""


SYSTEM_FASE2 = """Você é um extrator de specs técnicas de editais de licitação para a JK Artes Gráficas (gráfica + comunicação visual).

Você recebe:
- A lista de PRODUTOS JK identificados na fase 1
- Os ITENS da compra (JSON do PNCP, com descrição e quantidade)

Sua tarefa: para cada item da compra que se encaixa nos produtos JK, extraia as specs.

Campos a extrair (null se ausente):
- produto_jk: categoria JK (ex: "cartilha", "banner")
- descricao_completa: descrição literal do item no edital
- quantidade: número (apenas o número, sem unidade)
- unidade: "un", "kg", "m²", etc.
- formato: tamanho/dimensão (ex: "A4", "14x21cm", "1,20m x 0,80m")
- gramatura_papel: gramatura do papel (ex: "75g", "couché 150g") ou null se não for produto gráfico
- cores: cores de impressão (ex: "4x4", "4x0", "1x1", "policromia") ou null
- acabamento: laminação, encadernação, vinco, dobra, espiral, wire-o, etc.
- material: para CV — ACM, lona, vinil, etc. Para gráfica — papel offset, couché, etc.
- valor_unitario_estimado: número decimal
- valor_total_estimado: número decimal
- prazo_entrega_dias: número (apenas) ou null

FORMATO: APENAS JSON puro, sem markdown:
{"itens": [{...}, {...}]}

Se nenhum item da compra se encaixar nos produtos JK identificados (ex: item é só "serviço de instalação"), retorne {"itens": []}."""


def _parse_json_resposta(text: str) -> dict | None:
    """Extrai JSON da resposta do modelo, tolerante a markdown wrapping."""
    text = text.strip()
    if text.startswith("```"):
        m = re.search(r"```(?:json)?\s*(.+?)```", text, re.DOTALL)
        if m:
            text = m.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Tenta achar primeiro objeto JSON na string
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    return None


def _classificar_um(client, edital: dict) -> dict | None:
    """Roda Fase 1 em 1 edital. Retorna edital enriquecido se match, None se não."""
    user_msg = (
        f"Órgão: {(edital.get('orgao') or '')[:200]}\n"
        f"Modalidade: {(edital.get('modalidade') or '')[:80]}\n"
        f"Objeto: {(edital.get('objeto') or '')[:800]}"
    )
    try:
        resp = client.messages.create(
            model=MODEL_FASE1,
            max_tokens=200,
            system=[{
                "type": "text",
                "text": CARTEIRA_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": user_msg}],
        )
        text = resp.content[0].text
        data = _parse_json_resposta(text)
        if data and data.get("produtos"):
            return {
                **edital,
                "produtos_jk": data["produtos"],
                "confianca_fase1": data.get("confianca", "media"),
            }
    except Exception as e:
        print(f"  [Fase1 ERR] {(edital.get('orgao') or '?')[:30]}: {e}")
    return None


def _buscar_itens_pncp(cnpj: str, ano: str, seq: str) -> list[dict] | None:
    """Busca itens de uma compra PNCP via API pública."""
    url = f"https://pncp.gov.br/api/pncp/v1/orgaos/{cnpj}/compras/{ano}/{seq}/itens"
    try:
        r = requests.get(url, timeout=30, headers={"User-Agent": "JK-Triagem/1.0"})
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


def _extrair_specs_um(client, edital: dict) -> dict:
    """Roda Fase 2 em 1 edital PNCP. Anota campo specs_fase2 (ou marca erro)."""
    cnpj = edital.get("_cnpj", "")
    ano = edital.get("_ano", "")
    seq = edital.get("_seq", "")
    if not (cnpj and ano and seq):
        edital["specs_fase2"] = {"erro": "sem identificadores PNCP"}
        return edital

    itens = _buscar_itens_pncp(cnpj, ano, seq)
    if not itens:
        edital["specs_fase2"] = {"erro": "não foi possível baixar itens"}
        return edital

    # Trunca pra evitar prompts gigantes (>30 itens é raro e indica compra agrupada)
    itens_compactos = [
        {
            "n": i.get("numeroItem"),
            "desc": (i.get("descricao") or "")[:600],
            "qtd": i.get("quantidade"),
            "un": i.get("unidadeMedida"),
            "valor_unit": i.get("valorUnitarioEstimado"),
            "valor_total": i.get("valorTotal"),
        }
        for i in itens[:30]
    ]
    payload = {
        "produtos_jk_identificados": edital["produtos_jk"],
        "itens_compra": itens_compactos,
    }
    user_msg = json.dumps(payload, ensure_ascii=False)

    try:
        resp = client.messages.create(
            model=MODEL_FASE2,
            max_tokens=4000,
            system=[{
                "type": "text",
                "text": SYSTEM_FASE2,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": user_msg}],
        )
        text = resp.content[0].text
        data = _parse_json_resposta(text)
        if data and "itens" in data:
            edital["specs_fase2"] = data
        else:
            edital["specs_fase2"] = {"erro": "resposta inválida", "raw": text[:300]}
    except Exception as e:
        edital["specs_fase2"] = {"erro": str(e)[:200]}
    return edital


def triar(editais: list[dict]) -> list[dict]:
    """Roda Fase 1 em todos os editais, Fase 2 só nos PNCP que passaram.
    Retorna lista de matches (subset). Lista vazia se nada bateu."""
    if not ANTHROPIC_API_KEY or Anthropic is None:
        print("[TRIAGEM] Pulado — ANTHROPIC_API_KEY ou lib anthropic ausente")
        return []

    client = Anthropic(api_key=ANTHROPIC_API_KEY)

    print(f"[TRIAGEM] Fase 1 (Haiku) em {len(editais)} editais...")
    matches: list[dict] = []
    with ThreadPoolExecutor(max_workers=10) as ex:
        for r in ex.map(lambda e: _classificar_um(client, e), editais):
            if r:
                matches.append(r)
    print(f"[TRIAGEM] Fase 1: {len(matches)} matches")

    pncp_matches = [m for m in matches if m.get("portal") == "PNCP"]
    if pncp_matches:
        print(f"[TRIAGEM] Fase 2 (Sonnet) em {len(pncp_matches)} editais PNCP...")
        with ThreadPoolExecutor(max_workers=5) as ex:
            list(ex.map(lambda e: _extrair_specs_um(client, e), pncp_matches))

    return matches


# ──────────────────────────────────────────────
# EMAIL DA TRIAGEM
# ──────────────────────────────────────────────
def _linha_specs_html(specs: dict) -> str:
    if not specs or specs.get("erro"):
        return f"<span style='color:#999;font-size:11px;'>Specs indisponíveis: {specs.get('erro', '—') if specs else '—'}</span>"
    itens = specs.get("itens", [])
    if not itens:
        return "<span style='color:#999;font-size:11px;'>Nenhum item da compra bateu com produtos JK</span>"
    linhas = []
    for it in itens[:8]:  # limita a 8 itens por edital pro email não explodir
        partes = []
        if it.get("produto_jk"):
            partes.append(f"<b>{it['produto_jk']}</b>")
        if it.get("quantidade"):
            partes.append(f"{it['quantidade']}{' ' + it['unidade'] if it.get('unidade') else ''}")
        if it.get("formato"):
            partes.append(f"fmt {it['formato']}")
        if it.get("gramatura_papel"):
            partes.append(it["gramatura_papel"])
        if it.get("cores"):
            partes.append(f"cores {it['cores']}")
        if it.get("acabamento"):
            partes.append(it["acabamento"])
        if it.get("valor_unitario_estimado"):
            partes.append(f"R$ {it['valor_unitario_estimado']:.2f}/un")
        linhas.append("• " + " · ".join(str(p) for p in partes if p))
    extra = f"<br><i>(+{len(itens) - 8} itens)</i>" if len(itens) > 8 else ""
    return "<br>".join(linhas) + extra


def montar_html_triagem(matches: list[dict]) -> str:
    total = len(matches)
    com_specs = sum(1 for m in matches if m.get("specs_fase2") and not m["specs_fase2"].get("erro"))

    if not matches:
        corpo = "<p style='color:#666;'>Nenhum edital com produtos da carteira JK hoje.</p>"
    else:
        linhas = ""
        for i, m in enumerate(matches):
            bg = "#f9f9f9" if i % 2 == 0 else "#ffffff"
            produtos = ", ".join(m.get("produtos_jk", []))
            confianca = m.get("confianca_fase1", "?")
            specs_html = _linha_specs_html(m.get("specs_fase2", {})) if m.get("portal") == "PNCP" else "<span style='color:#bbb;font-size:11px;'>Specs disponíveis só pra PNCP</span>"
            link = m.get("link", "")
            link_html = f'<a href="{link}" style="color:#1a73e8;">Ver edital</a>' if link else "—"
            linhas += f"""
            <tr style="background:{bg};">
              <td style="padding:10px;border:1px solid #e0e0e0;vertical-align:top;">
                <b>{m['portal']}</b> · {m['uf']} · {m.get('data', '—')}<br>
                <span style="font-size:11px;color:#666;">{m.get('orgao', '—')}</span><br>
                <span style="font-size:11px;color:#666;">{m.get('modalidade', '—')} · {m.get('valor', '—')}</span>
              </td>
              <td style="padding:10px;border:1px solid #e0e0e0;vertical-align:top;font-size:12px;">
                {m.get('objeto', '—')[:300]}
              </td>
              <td style="padding:10px;border:1px solid #e0e0e0;vertical-align:top;">
                <span style="background:#e8f0fe;color:#1a73e8;padding:2px 6px;border-radius:3px;font-size:11px;">{produtos}</span>
                <br><span style="color:#999;font-size:10px;">confiança: {confianca}</span>
              </td>
              <td style="padding:10px;border:1px solid #e0e0e0;vertical-align:top;font-size:12px;">
                {specs_html}
              </td>
              <td style="padding:10px;border:1px solid #e0e0e0;vertical-align:top;">{link_html}</td>
            </tr>"""
        corpo = f"""
        <p style="font-size:13px;color:#444;">
          <b>{total}</b> editais com produtos da carteira JK · <b>{com_specs}</b> com specs detalhadas (PNCP).
        </p>
        <table style="border-collapse:collapse;width:100%;font-size:12px;">
          <thead>
            <tr style="background:#1a73e8;color:#fff;">
              <th style="padding:10px;border:1px solid #1558b0;text-align:left;">Edital</th>
              <th style="padding:10px;border:1px solid #1558b0;text-align:left;">Objeto</th>
              <th style="padding:10px;border:1px solid #1558b0;text-align:left;">Produtos JK</th>
              <th style="padding:10px;border:1px solid #1558b0;text-align:left;">Specs (PNCP)</th>
              <th style="padding:10px;border:1px solid #1558b0;text-align:left;">Link</th>
            </tr>
          </thead>
          <tbody>{linhas}</tbody>
        </table>"""

    return f"""<!DOCTYPE html>
<html><body style="font-family:Arial,sans-serif;max-width:1300px;margin:0 auto;padding:20px;background:#f4f4f4;">
  <div style="background:#1a73e8;color:#fff;padding:20px 25px;border-radius:8px 8px 0 0;">
    <h2 style="margin:0;font-size:20px;">JK Artes Gráficas — Triagem de Matches</h2>
    <p style="margin:6px 0 0;font-size:13px;opacity:.9;">
      Editais filtrados pela carteira de produtos JK · {datetime.now().strftime('%d/%m/%Y %H:%M')}
    </p>
  </div>
  <div style="background:#fff;padding:20px;border:1px solid #ddd;border-top:none;border-radius:0 0 8px 8px;overflow-x:auto;">
    {corpo}
    <hr style="margin-top:30px;border:none;border-top:1px solid #eee;">
    <p style="font-size:11px;color:#999;margin:10px 0 0;">
      Fase 1: Claude Haiku 4.5 · Fase 2: Claude Sonnet 4.6 (só PNCP) · Carteira: pasta, cartão, cartilha, folder, bloco, talão, crachá, livro, certificado, revista, cartaz, broche, fachada/ACM, banner, vinil, placa, totem, etc.
    </p>
  </div>
</body></html>"""


def enviar_email_triagem(matches: list[dict], gmail_user: str, gmail_pass: str,
                         destino: str, copia: str, from_name: str = "JK Licitações"):
    """Envia o email de triagem. Não levanta exceção em caso de erro — só loga."""
    try:
        html = montar_html_triagem(matches)
        com_specs = sum(1 for m in matches if m.get("specs_fase2") and not m["specs_fase2"].get("erro"))
        assunto = f"Licitações JK — TRIAGEM: {len(matches)} matches ({com_specs} com specs)"
        msg = MIMEMultipart("alternative")
        msg["Subject"] = assunto
        msg["From"] = f"{from_name} <{gmail_user}>"
        msg["To"] = destino
        msg["Cc"] = copia
        msg.attach(MIMEText(html, "html", "utf-8"))
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.ehlo()
            server.starttls()
            server.login(gmail_user, gmail_pass)
            server.sendmail(gmail_user, [destino, copia], msg.as_string())
        print(f"[TRIAGEM] Email enviado: {assunto}")
    except Exception as e:
        print(f"[TRIAGEM] Falha ao enviar email: {e}")
