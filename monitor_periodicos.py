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

def construir_html(novos_artigos, matches_keywords, cfp_encontrados):
    hoje = datetime.now().strftime("%d/%m/%Y")
    html = f"""
    <html><body style="font-family: Arial, sans-serif; max-width: 680px; margin: auto; color: #222;">
    <h2 style="border-bottom: 2px solid #333; padding-bottom: 8px;">
      📚 Monitor de Periódicos — {hoje}
    </h2>
    """

    # Seção: novas edições / artigos
    if novos_artigos:
        html += """<h3 style="color:#185FA5;">📄 Novos artigos publicados</h3><ul>"""
        for a in novos_artigos[:20]:  # limita a 20 por e-mail
            html += f"""
            <li style="margin-bottom:12px;">
              <strong><a href="{a['link']}" style="color:#185FA5;">{a['titulo']}</a></strong><br>
              <span style="font-size:12px; color:#666;">{a['revista']} · {a['publicado']}</span>
              {f"<br><span style='font-size:13px; color:#444;'>{a['resumo']}</span>" if a.get('resumo') else ''}
            </li>"""
        if len(novos_artigos) > 20:
            html += f"<li style='color:#666;'>... e mais {len(novos_artigos)-20} artigos.</li>"
        html += "</ul>"

    # Seção: matches de palavras-chave
    if matches_keywords:
        html += """<h3 style="color:#0F6E56;">🔍 Correspondências de palavras-chave</h3><ul>"""
        for m in matches_keywords:
            kws = ", ".join(f"<code>{k}</code>" for k in m["keywords"])
            html += f"""
            <li style="margin-bottom:12px;">
              <strong><a href="{m['link']}" style="color:#0F6E56;">{m['titulo']}</a></strong><br>
              <span style="font-size:12px; color:#666;">{m['revista']} · {m['publicado']}</span><br>
              <span style="font-size:12px;">Palavras encontradas: {kws}</span>
            </li>"""
        html += "</ul>"

    # Seção: calls for papers
    if cfp_encontrados:
        html += """<h3 style="color:#854F0B;">📢 Chamadas de artigos (Call for Papers)</h3><ul>"""
        for c in cfp_encontrados:
            html += f"""
            <li style="margin-bottom:12px;">
              <strong><a href="{c['link']}" style="color:#854F0B;">{c['titulo']}</a></strong><br>
              <span style="font-size:12px; color:#666;">{c['revista']} · {c['publicado']}</span>
            </li>"""
        html += "</ul>"

    if not any([novos_artigos, matches_keywords, cfp_encontrados]):
        html += "<p style='color:#666;'>Nenhuma novidade desde a última verificação.</p>"

    html += """
    <hr style="margin-top:24px; border:none; border-top:1px solid #ddd;">
    <p style="font-size:11px; color:#aaa; text-align:center;">
      Monitor de Periódicos · gerado automaticamente
    </p>
    </body></html>"""
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
