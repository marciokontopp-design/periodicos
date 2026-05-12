"""
Monitor de Periódicos Científicos
Verifica RSS feeds de revistas, detecta novas edições e palavras-chave,
e envia alertas por e-mail.
"""

import json
import os
import hashlib
import smtplib
import re
import html as html_lib
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.header import Header
from pathlib import Path
from email.utils import parsedate_to_datetime

import feedparser


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


# ── Limpeza e normalização de campos RSS ───────────────────────────────────────

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def limpar_html(valor):
    """Remove tags HTML e entidades escapadas vindas dos feeds RSS."""
    if not valor:
        return ""
    texto = str(valor)

    # Alguns feeds vêm duplamente escapados (&lt;p&gt;...&lt;/p&gt;).
    for _ in range(3):
        novo = html_lib.unescape(texto)
        if novo == texto:
            break
        texto = novo

    # Converte quebras estruturais em espaço antes de remover tags.
    texto = re.sub(r"</?(p|div|br|li|ul|ol|span|strong|em|i|b)[^>]*>", " ", texto, flags=re.I)
    texto = _TAG_RE.sub(" ", texto)
    texto = _WS_RE.sub(" ", texto).strip()
    return texto


def resumo_da_entrada(entry):
    """Extrai resumo do RSS usando os campos mais comuns."""
    candidatos = []

    # Campos típicos do feedparser.
    for campo in ("summary", "description", "subtitle", "content_encoded", "dc_description"):
        valor = entry.get(campo)
        if valor:
            candidatos.append(valor)

    # content costuma ser uma lista de dicts: [{'type': 'text/html', 'value': '...'}]
    content = entry.get("content")
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and item.get("value"):
                candidatos.append(item.get("value"))

    for candidato in candidatos:
        limpo = limpar_html(candidato)
        if limpo:
            return limpo
    return ""


def truncar(texto, limite=420):
    texto = limpar_html(texto)
    if len(texto) <= limite:
        return texto
    corte = texto[:limite].rsplit(" ", 1)[0]
    return corte + "..."


def formatar_data(valor):
    """Tenta converter datas RSS para dd/mm/aaaa. Se não conseguir, limpa e retorna original."""
    if not valor:
        return ""
    try:
        dt = parsedate_to_datetime(valor)
        return dt.strftime("%d/%m/%Y")
    except Exception:
        return limpar_html(valor)


# ── Classificação de chamadas ─────────────────────────────────────────────────

CFP_CATEGORIAS = [
    (
        "Chamadas de artigos / Call for papers",
        [
            "call for papers", "call for contributions", "call for articles",
            "call for abstracts", "chamada de artigos", "chamada para artigos",
            "convocatoria", "llamada a artículos", "llamado a artículos",
            "recebe artigos", "submissions invited"
        ],
    ),
    (
        "Special issue / Número especial",
        [
            "special issue", "special section", "número especial",
            "numero especial", "edición especial", "edicion especial"
        ],
    ),
    (
        "Dossiê / Número temático",
        [
            "dossiê", "dossie", "dossier", "dossier temático",
            "dossier tematico", "número temático", "numero temático",
            "numero tematico", "thematic issue", "thematic section"
        ],
    ),
    (
        "Prazo de submissão",
        [
            "submission deadline", "deadline", "prazo de submissão",
            "prazo para submissão", "fecha límite", "fecha limite",
            "hasta el", "submissões até", "submissoes ate"
        ],
    ),
    (
        "Editoria convidada / Guest editors",
        [
            "guest editor", "guest editors", "editores convidados",
            "editor convidado", "editores invitados", "editor invitado"
        ],
    ),
    (
        "Avisos e notícias editoriais",
        [
            "announcement", "announcements", "avisos", "notícias",
            "noticias", "news", "editorial notice", "comunicado"
        ],
    ),
]


def classificar_chamada(titulo, resumo):
    """Classifica possíveis chamadas editoriais a partir de título/resumo do RSS."""
    texto = f"{titulo} {resumo}".lower()
    categorias = []
    termos_encontrados = []
    for categoria, termos in CFP_CATEGORIAS:
        encontrados_categoria = [t for t in termos if t.lower() in texto]
        if encontrados_categoria:
            categorias.append(categoria)
            termos_encontrados.extend(encontrados_categoria)
    return categorias, sorted(set(termos_encontrados))


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

        titulo = limpar_html(entry.get("title", ""))
        resumo_completo = resumo_da_entrada(entry)
        resumo_curto = truncar(resumo_completo, 420)
        link = entry.get("link", "#")
        publicado = formatar_data(entry.get("published", "") or entry.get("updated", ""))

        categorias_cfp, termos_cfp = classificar_chamada(titulo, resumo_completo)
        is_cfp = bool(categorias_cfp)

        if is_cfp and revista.get("monitorar_cfp", False):
            cfp_encontrados.append({
                "revista": nome,
                "titulo": titulo,
                "link": link,
                "publicado": publicado,
                "id": eid,
                "resumo": resumo_curto,
                "categorias": categorias_cfp,
                "termos": termos_cfp,
            })
        else:
            novos_artigos.append({
                "revista": nome,
                "titulo": titulo,
                "link": link,
                "publicado": publicado,
                "id": eid,
                "resumo": resumo_curto,
            })

        # Busca palavras-chave no texto já limpo.
        texto_busca = ""
        if escopo.get("titulos"):
            texto_busca += titulo.lower() + " "
        if escopo.get("resumos"):
            texto_busca += resumo_completo.lower() + " "

        encontradas = [kw for kw in palavras_chave if kw.lower() in texto_busca]
        if encontradas:
            matches_keywords.append({
                "revista": nome,
                "titulo": titulo,
                "link": link,
                "publicado": publicado,
                "keywords": encontradas,
                "id": eid,
                "resumo": resumo_curto,
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


def agrupar_chamadas_por_categoria(chamadas):
    """Agrupa chamadas primeiro por categoria e depois por revista."""
    grupos = {}
    for item in chamadas:
        categorias = item.get("categorias") or ["Chamadas não classificadas"]
        for categoria in categorias:
            grupos.setdefault(categoria, {})
            revista = item.get("revista", "Revista não identificada")
            grupos[categoria].setdefault(revista, []).append(item)
    return grupos


def badge_termos(termos):
    if not termos:
        return ""
    return " ".join(
        f"<span style='display:inline-block;background:#FBF3E3;color:#854F0B;"
        f"border-radius:4px;padding:2px 6px;margin:2px;font-size:11px;'>{html_lib.escape(str(t))}</span>"
        for t in termos
    )


def badge_keywords(keywords):
    """Renderiza as palavras-chave encontradas como pequenos marcadores HTML."""
    if not keywords:
        return ""
    return " ".join(
        f"<span style='display:inline-block;background:#E8F3F0;color:#0F6E56;"
        f"border-radius:4px;padding:2px 6px;margin:2px;font-size:11px;'>{html_lib.escape(str(k))}</span>"
        for k in keywords
    )


def bloco_item(item, cor_link):
    titulo = html_lib.escape(item.get("titulo", "Sem título"))
    link = html_lib.escape(item.get("link", "#"), quote=True)
    publicado = html_lib.escape(item.get("publicado", ""))
    resumo = html_lib.escape(item.get("resumo", ""))

    meta = f"<div style='font-size:12px;color:#6B6560;margin-top:3px;'>{publicado}</div>" if publicado else ""
    resumo_html = f"<div style='font-size:13px;color:#444;line-height:1.5;margin-top:6px;'>{resumo}</div>" if resumo else ""

    return f"""
    <div style="padding:10px 0;border-top:1px solid #E2DDD5;">
      <div style="font-size:14px;font-weight:bold;line-height:1.4;">
        <a href="{link}" style="color:{cor_link};text-decoration:none;">{titulo}</a>
      </div>
      {meta}
      {resumo_html}
    </div>
    """


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

    if novos_artigos:
        html += """
        <h3 style="font-size:17px;color:#185FA5;margin:0 0 12px 0;">📄 Novos artigos por revista</h3>
        """
        for revista, artigos in agrupar_por_revista(novos_artigos).items():
            html += f"""
            <div style="border:1px solid #E8EEF8;background:#FAFCFF;border-radius:12px;padding:14px 16px;margin:0 0 14px 0;">
              <h4 style="font-size:16px;color:#1A1714;margin:0 0 10px 0;">{html_lib.escape(revista)}</h4>
            """
            for a in artigos[:20]:
                html += bloco_item(a, "#185FA5")
            if len(artigos) > 20:
                html += f"<p style='font-size:12px;color:#6B6560;margin:8px 0 0 0;'>... e mais {len(artigos)-20} artigo(s) nesta revista.</p>"
            html += "</div>"

    if matches_keywords:
        html += """
        <h3 style="font-size:17px;color:#0F6E56;margin:22px 0 12px 0;">🔍 Correspondências de palavras-chave</h3>
        <p style="font-size:13px;color:#6B6560;margin:0 0 12px 0;">Itens em que os termos cadastrados apareceram nos campos monitorados pelo sistema.</p>
        """
        for revista, matches in agrupar_por_revista(matches_keywords).items():
            html += f"""
            <div style="border:1px solid #CFE4DE;background:#F8FCFB;border-radius:12px;padding:14px 16px;margin:0 0 14px 0;">
              <h4 style="font-size:16px;color:#1A1714;margin:0 0 10px 0;">{html_lib.escape(revista)}</h4>
            """
            for m in matches:
                html += bloco_item(m, "#0F6E56")
                kws = badge_keywords(m.get("keywords", []))
                html += f"<div style='font-size:12px;color:#333;margin:-6px 0 8px 0;'>Palavras encontradas: {kws}</div>"
            html += "</div>"

    if cfp_encontrados:
        html += """
        <h3 style="font-size:17px;color:#854F0B;margin:22px 0 12px 0;">📢 Chamadas, dossiês e special issues</h3>
        <p style="font-size:13px;color:#6B6560;margin:0 0 12px 0;">Itens classificados automaticamente a partir de termos encontrados no título e/ou resumo do RSS.</p>
        """
        for categoria, revistas in agrupar_chamadas_por_categoria(cfp_encontrados).items():
            html += f"""
            <div style="border:1px solid #F1D8A8;background:#FFFDF7;border-radius:12px;padding:14px 16px;margin:0 0 16px 0;">
              <h4 style="font-size:16px;color:#854F0B;margin:0 0 12px 0;">{html_lib.escape(categoria)}</h4>
            """
            for revista, chamadas in revistas.items():
                html += f"<h5 style='font-size:14px;color:#1A1714;margin:12px 0 6px 0;'>{html_lib.escape(revista)}</h5>"
                for c in chamadas:
                    html += bloco_item(c, "#854F0B")
                    termos_html = badge_termos(c.get("termos", []))
                    if termos_html:
                        html += f"<div style='font-size:12px;color:#333;margin:-6px 0 8px 0;'>Termos de classificação: {termos_html}</div>"
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
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = str(Header(f"📚 Monitor de Periódicos — {total_novidades} novidade(s) encontrada(s)", "utf-8"))
    msg["From"] = email_cfg["remetente"]
    msg["To"] = email_cfg["destinatario"]
    msg.attach(MIMEText(html, "html", "utf-8"))

    with smtplib.SMTP(email_cfg["smtp_server"], email_cfg["smtp_port"]) as server:
        server.starttls()
        server.login(email_cfg["remetente"], senha)
        server.sendmail(email_cfg["remetente"], email_cfg["destinatario"], msg.as_string())
    print(f"✅ E-mail enviado para {email_cfg['destinatario']}")
    return True


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

    enviado = True
    if total > 0 or todos_keywords:
        html = construir_html(todos_artigos, todos_keywords, todos_cfp)
        enviado = enviar_email(config, html, total + len(todos_keywords))
    else:
        print("  Nenhuma novidade. E-mail não enviado.")

    # Atualiza estado apenas se não havia e-mail a enviar ou se o envio foi concluído.
    # Isso evita marcar itens como vistos quando há erro de SMTP.
    if enviado:
        estado["vistos"].extend(ids_novos)
        estado["vistos"] = list(set(estado["vistos"]))
        estado["ultima_verificacao"] = datetime.now(timezone.utc).isoformat()
        salvar_estado(estado)
        print("  Estado salvo.")
    else:
        print("  Estado não salvo, pois o e-mail não foi enviado.")


if __name__ == "__main__":
    main()
