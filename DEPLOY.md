# Hospedando o PILAS 🚀

O PILAS usa **long-polling** (ele fica conectado puxando mensagens do Telegram).
Isso quer dizer que precisa de um processo **sempre ligado** — não serve um
"web service" grátis que dorme por inatividade. E como os dados ficam em SQLite
(`pilas.db`), o host precisa de **disco que persiste** entre reinícios, senão você
perde tudo a cada deploy.

> Verdade nua e crua: quase todo host "grátis pra sempre" ou (a) dorme, (b) zera o
> disco, ou (c) pede cartão de crédito mesmo no plano free. Abaixo, as melhores
> opções reais, da mais fácil pra mais trabalhosa.

---

## Antes de tudo

1. Garanta que o `.env` **não** vai pro Git (já está no `.gitignore`). Você vai
   configurar as chaves direto no painel/secrets do host.
2. Suba o código pro GitHub (a maioria dos hosts puxa de lá):

   ```powershell
   git init
   git add .
   git commit -m "PILAS pronto pra deploy"
   # crie um repo no github e:
   git remote add origin https://github.com/SEU_USUARIO/pilas.git
   git push -u origin main
   ```

   As chaves que você vai precisar configurar no host:
   `TELEGRAM_BOT_TOKEN`, `GEMINI_API_KEY`, (opcional) `GEMINI_API_KEYS`,
   `PROVIDER=gemini`, `GEMINI_MODEL=gemini-2.5-flash-lite`.

---

## Opção 1 — Fly.io (recomendada) 🟢

Roda em container, tem **volume persistente** e roda processo sempre-ligado.
Tem franquia grátis, mas **pede cartão** no cadastro (não cobra dentro da franquia).
Já deixei o `Dockerfile` e o `fly.toml` prontos.

1. Instale o `flyctl`:
   - Windows (PowerShell): `iwr https://fly.io/install.ps1 -useb | iex`
2. Crie a conta / faça login:
   ```powershell
   fly auth signup   # ou: fly auth login
   ```
3. Na pasta do projeto, prepare o app (NÃO deixe ele deployar ainda):
   ```powershell
   fly launch --no-deploy
   ```
   - Aceite usar o `fly.toml` existente. Escolha um nome único e a região `gru`.
   - Se perguntar de banco de dados (Postgres/Redis): **não**.
4. Crie o volume persistente (mesmo nome do `fly.toml`: `pilas_data`):
   ```powershell
   fly volumes create pilas_data --region gru --size 1
   ```
5. Configure as chaves (secrets):
   ```powershell
   fly secrets set TELEGRAM_BOT_TOKEN="seu_token" GEMINI_API_KEY="sua_chave" PROVIDER="gemini" GEMINI_MODEL="gemini-2.5-flash-lite"
   # se tiver mais chaves:
   fly secrets set GEMINI_API_KEYS="chave2,chave3"
   ```
6. Suba:
   ```powershell
   fly deploy
   ```
7. Veja os logs (e o "PILAS no ar"):
   ```powershell
   fly logs
   ```

Pronto — manda `oi` pro bot no Telegram. Pra atualizar depois: `git push` + `fly deploy`.

---

## Opção 2 — Railway 🟡 (mais fácil, crédito mensal pequeno)

Bem simples (puxa do GitHub, lê o `Dockerfile`/`Procfile`), mas **não é grátis pra
sempre**: dá um crédito mensal que cobre um bot pequeno por um tempo.

1. Crie conta em [railway.app](https://railway.app) e "New Project → Deploy from GitHub repo".
2. Em **Variables**, adicione: `TELEGRAM_BOT_TOKEN`, `GEMINI_API_KEY`,
   `PROVIDER=gemini`, `GEMINI_MODEL=gemini-2.5-flash-lite` (e `GEMINI_API_KEYS` se tiver).
3. Em **Settings**, garanta que o start é `python bot.py` (o `Procfile` já define `worker`).
4. Pra não perder dados: crie um **Volume** e monte em `/data`, e adicione as variáveis
   `DB_PATH=/data/pilas.db` e `CHARTS_DIR=/data/charts`.

---

## Opção 3 — Oracle Cloud "Always Free" 🟢 (grátis de verdade, mais trabalho)

Uma VM Linux gratuita pra sempre (pede cartão no cadastro, mas não cobra). Você tem
controle total e os dados ficam no disco da VM.

1. Crie conta em [oracle.com/cloud/free](https://www.oracle.com/cloud/free/) e crie
   uma VM **Always Free** (Ubuntu, formato Ampere/ARM).
2. Conecte via SSH e prepare:
   ```bash
   sudo apt update && sudo apt install -y python3 python3-venv git
   git clone https://github.com/SEU_USUARIO/pilas.git && cd pilas
   python3 -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   cp .env.example .env && nano .env    # cole suas chaves
   ```
3. Deixe rodando sempre com **systemd** (sobrevive a reboot). Crie
   `/etc/systemd/system/pilas.service`:
   ```ini
   [Unit]
   Description=PILAS bot
   After=network-online.target

   [Service]
   WorkingDirectory=/home/ubuntu/pilas
   ExecStart=/home/ubuntu/pilas/.venv/bin/python bot.py
   Restart=always
   User=ubuntu

   [Install]
   WantedBy=multi-user.target
   ```
   Depois:
   ```bash
   sudo systemctl enable --now pilas
   sudo journalctl -u pilas -f   # ver logs
   ```

---

## Opção 4 — Seu próprio PC / Raspberry Pi 🟢

Se você deixa um PC ligado (ou tem um Raspberry Pi), é o jeito mais simples e 100%
grátis: é só rodar `python bot.py`. No Windows, dá pra usar o Agendador de Tarefas
pra iniciar junto com o sistema. Só lembre que o bot só responde com o PC ligado.

---

## Dúvidas comuns

- **Preciso mudar o código pra cada host?** Não. O bot lê tudo de variáveis de
  ambiente; cada host tem seu jeito de definir (secrets/variables/.env).
- **Webhook em vez de polling?** Não precisa. Polling funciona em qualquer host que
  deixe um processo rodando e tenha saída pra internet.
- **Meus dados somem?** Só se o host não tiver disco persistente. Por isso o volume
  em `/data` nas opções 1 e 2, e o disco da VM nas opções 3 e 4.
- **Posso rodar em mais de um lugar ao mesmo tempo?** Não — o Telegram só deixa um
  processo fazer polling do mesmo bot. Rode em um host só.
