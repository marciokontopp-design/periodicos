# 📚 Monitor de Periódicos Científicos

Monitora RSS feeds de revistas científicas e envia alertas por e-mail quando há:
- Novos artigos publicados
- Correspondências com suas palavras-chave (em títulos e resumos)
- Chamadas de artigos e special issues (call for papers)

Roda automaticamente via **GitHub Actions** — sem servidor, sem custo.

---

## Arquivos do projeto

```
monitor-periodicos/
├── monitor_periodicos.py   ← script principal
├── journals_config.json    ← suas revistas e configurações
├── estado_visto.json       ← gerado automaticamente (não edite)
└── .github/
    └── workflows/
        └── monitor.yml     ← agendamento automático
```

---

## Passo a passo para configurar

### 1. Criar o repositório no GitHub

1. Acesse [github.com](https://github.com) e faça login
2. Clique em **New repository**
3. Nome sugerido: `monitor-periodicos`
4. Marque como **Private** (recomendado)
5. Clique em **Create repository**

### 2. Fazer upload dos arquivos

Faça upload dos três arquivos na raiz do repositório:
- `monitor_periodicos.py`
- `journals_config.json`
- `.github/workflows/monitor.yml` ← atenção: deve estar nessa subpasta exata

No GitHub, você pode criar a pasta `.github/workflows/` manualmente ao adicionar o arquivo:
clique em **Add file → Create new file**, e no campo de nome escreva `.github/workflows/monitor.yml`.

### 3. Configurar a senha do e-mail (Gmail)

O script usa uma **senha de app** do Gmail (não sua senha normal).

**Para gerar a senha de app:**
1. Acesse [myaccount.google.com/security](https://myaccount.google.com/security)
2. Ative a **Verificação em duas etapas** (se ainda não tiver)
3. Pesquise por "Senhas de app" na barra de pesquisa da página
4. Crie uma nova senha para "Outro (nome personalizado)" → escreva "Monitor Periódicos"
5. Copie a senha de 16 caracteres gerada

**Para salvar a senha no GitHub:**
1. No seu repositório, vá em **Settings → Secrets and variables → Actions**
2. Clique em **New repository secret**
3. Nome: `EMAIL_SENHA`
4. Valor: a senha de 16 caracteres do Gmail
5. Clique em **Add secret**

### 4. Editar journals_config.json

Abra o arquivo e personalize:

```json
{
  "email": {
    "destinatario": "SEU_EMAIL@gmail.com",   ← quem recebe os alertas
    "remetente": "SEU_EMAIL@gmail.com",       ← mesmo e-mail do Gmail
    ...
  },
  "revistas": [
    {
      "nome": "Nome da Revista",
      "rss": "URL_DO_RSS_DA_REVISTA",         ← veja como encontrar abaixo
      "base": "Elsevier",
      "monitorar_cfp": true
    }
  ],
  "palavras_chave": [
    "sua palavra-chave aqui"
  ]
}
```

### 5. Testar manualmente

No GitHub, vá em **Actions → Monitor de Periódicos → Run workflow**.
Você verá os logs em tempo real e receberá o e-mail se houver novidades.

---

## Como encontrar o RSS de uma revista

| Editora | Como encontrar |
|---|---|
| **Elsevier / ScienceDirect** | `https://rss.sciencedirect.com/publication/science/ISSN` (substitua ISSN pelo número sem hífen) |
| **Springer / Nature** | Na página da revista, procure o ícone RSS ou use `https://link.springer.com/search.rss?facet-journal-id=ID` |
| **Wiley** | Na página da revista, clique em "RSS" no menu de conteúdo |
| **SAGE** | `https://journals.sagepub.com/action/showFeed?type=etoc&feed=rss&jc=SIGLA` |
| **MDPI** | `https://www.mdpi.com/rss/journal/SIGLA` (ex: `/rss/journal/publications`) |
| **SciELO** | `https://www.scielo.br/feed/SIGLA/rss.xml` |

Se não encontrar o RSS, procure no site da revista por um ícone laranja (☰) ou o texto "RSS" / "Subscribe".

---

## Ajustar a periodicidade

No arquivo `monitor.yml`, a linha `cron` controla quando o script roda:

```yaml
- cron: "0 11 * * 1"   # toda segunda-feira às 8h (Brasília)
- cron: "0 11 * * *"   # todo dia às 8h
- cron: "0 11 1 * *"   # todo dia 1º do mês
```

Use [crontab.guru](https://crontab.guru) para montar o horário que quiser.

---

## Limites do GitHub Actions (plano gratuito)

- **2.000 minutos/mês** de execução gratuita em repositórios privados
- Cada execução do script leva ~1 minuto
- Rodando semanalmente = ~4 min/mês → **muito dentro do limite**
- Rodando diariamente = ~30 min/mês → ainda confortável

---

## Dependências Python

```
feedparser
```

Instaladas automaticamente pelo workflow. Para testar localmente:
```bash
pip install feedparser
python monitor_periodicos.py
```
(Defina a variável de ambiente `EMAIL_SENHA` antes de rodar localmente.)
