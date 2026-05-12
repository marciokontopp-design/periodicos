"""
Monitor de Periódicos Científicos
Verifica RSS feeds de revistas, detecta novas edições e palavras-chave,
e envia alertas por e-mail.
"""

import json
import os
import hashlib
import smtplib
import feedparser
from html import escape
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path


# ── Configurações ──────────────────────────────────────────────────────────────

CONFIG_FILE = "journals_config.json"
ESTADO_FILE = "estado_visto.json"  # rastreia o que já foi alertado


def carregar_config():
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def carregar_estado():
    if Path(ESTADO_FILE).exists():
        with open(ESTADO_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"vistos": []}


def salvar_estado(estado):
    with open(ESTADO_FILE, "w", encoding="utf-8") as f:
        json.dump(estado, f, ensure_ascii=False, indent=2)


def id_entrada(entry):
    """Gera um ID único para cada entrada do feed."""
    chave = (entry.get("link") or entry.get("id") or entry.get("title") or "")
    return hashlib.md5(chave.encode()).hexdigest()


# ── Leitura de RSS ─────────────────────────────────────────────────────────────

def buscar_novidades(revista, estado, palavras_chave, escopo):
    """Lê o RSS da revista e retorna novas entradas, separando por tipo."""
    feed = feedparser.parse(revista["rss"])
    nome = revista["nome"]
    novos_artigos = []
    matches_keywords = []
    cfp_encontrados = []

    for entry in feed.entries:
        eid = id_entrada(entry)
        if eid in estado["vistos"]:
            continue

        titulo = entry.get("title", "")
        resumo = entry.get("summary", "")
        link = entry.get("link", "#")
        publicado = entry.get("published", "")

        # Detecta call for papers / special issue no título
        cfp_terms = ["call for papers", "special issue", "chamada de artigos",
                     "guest editor", "thematic issue"]
        is_cfp = any(t in titulo.lower() or t in resumo.lower() for t in cfp_terms)

        if is_cfp and revista.get("monitorar_cfp", False):
            cfp_encontrados.append({
                "revista": nome, "titulo": titulo,
                "link": link, "publicado": publicado, "id": eid
            })
        else:
            novos_artigos.append({
                "revista": nome, "titulo": titulo,
                "link": link, "publicado": publicado, "id": eid,
                "resumo": resumo[:300] + "..." if len(resumo) > 300 else resumo
            })

        # Busca palavras-chave
        texto_busca = ""
        if escopo.get("titulos"):
            texto_busca += titulo.lower() + " "
        if escopo.get("resumos"):
            texto_busca += resumo.lower() + " "

        encontradas = [kw for kw in palavras_chave if kw.lower() in texto_busca]
        if encontradas:
            matches_keywords.append({
                "revista": nome, "titulo": titulo, "link": link,
                "publicado": publicado, "keywords": encontradas, "id": eid
            })

    return novos_artigos, matches_keywords, cfp_encontrados


# ── Geração do e-mail ──────────────────────────────────────────────────────────

def agrupar_por_revista(itens):
    """Agrupa uma lista de itens pelo nome da revista."""
    grupos = {}
    for item in itens:
        revista = item.get("revista", "Revista não identificada")
        grupos.setdefault(revista, []).append(item)
    return grupos


def badge_keywords(keywords):
    """Renderiza as palavras-chave encontradas como pequenos marcadores HTML."""
    if not keywords:
        return ""
    return " ".join(
        f"<span style='display:inline-block;background:#E8F3F0;color:#0F6E56;"
        f"border-radius:4px;padding:2px 6px;margin:2px;font-size:11px;'>{escape(str(k))}</span>"
        for k in keywords
    )


def construir_html(novos_artigos, matches_keywords, cfp_encontrados):
    hoje = datetime.now().strftime("%d/%m/%Y")
    total_artigos = len(novos_artigos)
    total_keywords = len(matches_keywords)
    total_cfp = len(cfp_encontrados)

    html = f"""
    <html>
    <body style="font-family: Arial, sans-serif; max-width: 760px; margin: auto; color: #222; background:#F7F5F0; padding: 20px;">
      <div style="background:#FFFFFF;border:1px solid #E2DDD5;border-radius:14px;padding:22px 24px;">
        <h2 style="margin:0 0 6px 0; font-size:22px; color:#1A1714;">
          📚 Monitor de Periódicos
        </h2>
        <p style="margin:0 0 18px 0; font-size:13px; color:#6B6560;">
          Atualização de {hoje} · {total_artigos} artigo(s), {total_keywords} correspondência(s) de palavras-chave, {total_cfp} chamada(s)
        </p>
        <div style="display:block;border-top:1px solid #E2DDD5;margin:12px 0 18px 0;"></div>
    """

    # Seção: novos artigos, agrupados por revista
    if novos_artigos:
        html += """
        <h3 style="font-size:17px;color:#185FA5;margin:0 0 12px 0;">📄 Novos artigos por revista</h3>
        """
        for revista, artigos in agrupar_por_revista(novos_artigos).items():
            html += f"""
            <div style="border:1px solid #E8EEF8;background:#FAFCFF;border-radius:12px;padding:14px 16px;margin:0 0 14px 0;">
              <h4 style="font-size:16px;color:#1A1714;margin:0 0 10px 0;">{escape(revista)}</h4>
            """
            for a in artigos[:20]:
                titulo = escape(a.get("titulo", "Sem título"))
                link = escape(a.get("link", "#"), quote=True)
                publicado = escape(a.get("publicado", ""))
                resumo = escape(a.get("resumo", ""))
                html += f"""
                <div style="padding:10px 0;border-top:1px solid #E2DDD5;">
                  <div style="font-size:14px;font-weight:bold;line-height:1.4;">
                    <a href="{link}" style="color:#185FA5;text-decoration:none;">{titulo}</a>
                  </div>
                  <div style="font-size:12px;color:#6B6560;margin-top:3px;">{publicado}</div>
                  {f"<div style='font-size:13px;color:#444;line-height:1.5;margin-top:6px;'>{resumo}</div>" if resumo else ""}
                </div>
                """
            if len(artigos) > 20:
                html += f"<p style='font-size:12px;color:#6B6560;margin:8px 0 0 0;'>... e mais {len(artigos)-20} artigo(s) nesta revista.</p>"
            html += "</div>"

    # Seção: matches de palavras-chave, separada e agrupada por revista
    if matches_keywords:
        html += """
        <h3 style="font-size:17px;color:#0F6E56;margin:22px 0 12px 0;">🔍 Correspondências de palavras-chave</h3>
        <p style="font-size:13px;color:#6B6560;margin:0 0 12px 0;">Itens em que os termos cadastrados apareceram nos campos monitorados pelo sistema.</p>
        """
        for revista, matches in agrupar_por_revista(matches_keywords).items():
            html += f"""
            <div style="border:1px solid #CFE4DE;background:#F8FCFB;border-radius:12px;padding:14px 16px;margin:0 0 14px 0;">
              <h4 style="font-size:16px;color:#1A1714;margin:0 0 10px 0;">{escape(revista)}</h4>
            """
            for m in matches:
                titulo = escape(m.get("titulo", "Sem título"))
                link = escape(m.get("link", "#"), quote=True)
                publicado = escape(m.get("publicado", ""))
                kws = badge_keywords(m.get("keywords", []))
                html += f"""
                <div style="padding:10px 0;border-top:1px solid #E2DDD5;">
                  <div style="font-size:14px;font-weight:bold;line-height:1.4;">
                    <a href="{link}" style="color:#0F6E56;text-decoration:none;">{titulo}</a>
                  </div>
                  <div style="font-size:12px;color:#6B6560;margin-top:3px;">{publicado}</div>
                  <div style="font-size:12px;color:#333;margin-top:6px;">Palavras encontradas: {kws}</div>
                </div>
                """
            html += "</div>"

    # Seção: calls for papers / special issues
    if cfp_encontrados:
        html += """
        <h3 style="font-size:17px;color:#854F0B;margin:22px 0 12px 0;">📢 Chamadas de artigos e special issues</h3>
        """
        for revista, chamadas in agrupar_por_revista(cfp_encontrados).items():
            html += f"""
            <div style="border:1px solid #F1D8A8;background:#FFFDF7;border-radius:12px;padding:14px 16px;margin:0 0 14px 0;">
              <h4 style="font-size:16px;color:#1A1714;margin:0 0 10px 0;">{escape(revista)}</h4>
            """
            for c in chamadas:
                titulo = escape(c.get("titulo", "Sem título"))
                link = escape(c.get("link", "#"), quote=True)
                publicado = escape(c.get("publicado", ""))
                html += f"""
                <div style="padding:10px 0;border-top:1px solid #E2DDD5;">
                  <div style="font-size:14px;font-weight:bold;line-height:1.4;">
                    <a href="{link}" style="color:#854F0B;text-decoration:none;">{titulo}</a>
                  </div>
                  <div style="font-size:12px;color:#6B6560;margin-top:3px;">{publicado}</div>
                </div>
                """
            html += "</div>"

    if not any([novos_artigos, matches_keywords, cfp_encontrados]):
        html += "<p style='color:#666;'>Nenhuma novidade desde a última verificação.</p>"

    html += """
        <div style="display:block;border-top:1px solid #E2DDD5;margin:22px 0 12px 0;"></div>
        <p style="font-size:11px; color:#9E9890; text-align:center; margin:0;">
          Monitor de Periódicos · gerado automaticamente via GitHub Actions
        </p>
      </div>
    </body>
    </html>
    """
    return html

# ── Envio de e-mail ────────────────────────────────────────────────────────────

def enviar_email(config, html, total_novidades):
    email_cfg = config["email"]
    senha = os.environ.get("EMAIL_SENHA")  # definida como secret no GitHub Actions

    if not senha:
        print("⚠️  Variável EMAIL_SENHA não encontrada. E-mail não enviado.")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"📚 Monitor de Periódicos — {total_novidades} novidade(s) encontrada(s)"
    msg["From"] = email_cfg["remetente"]
    msg["To"] = email_cfg["destinatario"]
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP(email_cfg["smtp_server"], email_cfg["smtp_port"]) as server:
        server.starttls()
        server.login(email_cfg["remetente"], senha)
        server.sendmail(email_cfg["remetente"], email_cfg["destinatario"], msg.as_string())
    print(f"✅ E-mail enviado para {email_cfg['destinatario']}")


# ── Execução principal ─────────────────────────────────────────────────────────

def main():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Iniciando monitoramento...")

    config = carregar_config()
    estado = carregar_estado()
    palavras_chave = config.get("palavras_chave", [])
    escopo = config.get("escopo_busca", {"titulos": True, "resumos": True})

    todos_artigos = []
    todos_keywords = []
    todos_cfp = []
    ids_novos = []

    for revista in config["revistas"]:
        print(f"  → Verificando: {revista['nome']}")
        try:
            artigos, keywords_matches, cfps = buscar_novidades(
                revista, estado, palavras_chave, escopo
            )
            todos_artigos.extend(artigos)
            todos_keywords.extend(keywords_matches)
            todos_cfp.extend(cfps)
            ids_novos.extend([a["id"] for a in artigos])
            ids_novos.extend([c["id"] for c in cfps])
        except Exception as e:
            print(f"    ⚠️  Erro ao verificar {revista['nome']}: {e}")

    total = len(todos_artigos) + len(todos_cfp)
    print(f"  Novidades: {len(todos_artigos)} artigos, {len(todos_cfp)} CFPs, "
          f"{len(todos_keywords)} matches de palavras-chave")

    # Envia e-mail se houver qualquer novidade
    if total > 0 or todos_keywords:
        html = construir_html(todos_artigos, todos_keywords, todos_cfp)
        enviar_email(config, html, total + len(todos_keywords))
    else:
        print("  Nenhuma novidade. E-mail não enviado.")

    # Atualiza estado
    estado["vistos"].extend(ids_novos)
    estado["vistos"] = list(set(estado["vistos"]))  # remove duplicatas
    estado["ultima_verificacao"] = datetime.now(timezone.utc).isoformat()
    salvar_estado(estado)
    print("  Estado salvo.")


if __name__ == "__main__":
    main()
