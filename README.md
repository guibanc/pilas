# PILAS 🐷

Agente financeiro pessoal que vive dentro do Telegram. Você fala em linguagem
natural ("gastei 45 no mercado"), e ele registra, organiza e analisa seus gastos
e entradas — sem formulário, sem comando chato.

Construído com **Python + python-telegram-bot** (function calling) e **SQLite** local.
Funciona com **Gemini (grátis)** ou **Claude/Anthropic (pago)** — você escolhe no `.env`.

## Como funciona

```
Telegram  ──►  bot.py  ──►  agent.py (IA + tool use)  ──►  tools.py  ──►  SQLite
                                       │
                                       └─► charts.py (gráficos PNG) ──► enviados de volta
```

A IA interpreta a mensagem e decide quais tools chamar (`add_transaction`,
`get_summary`, `generate_chart`, etc.). O bot executa contra o banco e responde.

### Fast-path local (economiza IA) ⚡

Antes de chamar a IA, o bot tenta resolver a mensagem **localmente** em
[fast.py](fast.py) — com regex e palavras-chave. Mensagens comuns ("gastei 45 no
mercado", "quanto gastei essa semana", "gera um gráfico") são respondidas na hora,
**sem gastar quota da IA**. Só o que for ambíguo/diferente cai no Gemini/Claude.

Na prática, a maioria das mensagens nem toca na IA. **Todo gasto/entrada com valor
é registrado localmente** — se a categoria não for reconhecida, vai pra "outros"
(com o resto da frase como descrição). Entende `2k`, `3 mil`, `1.200,50` e dezenas
de marcas (ifood, uber, netflix, nike...). Desligue com `FAST_PATH=false` no `.env`.

### Várias chaves do Gemini (multiplica a quota grátis)

O tier grátis tem limite por minuto. Crie chaves em contas diferentes e liste em
`GEMINI_API_KEYS` (separadas por vírgula) — o bot **rotaciona** entre elas e, quando
uma bate no limite, pula pra próxima na hora. Com o fast-path, raramente vai precisar.

## Gemini (grátis) ou Anthropic (pago)?

- **Gemini** tem tier gratuito generoso — recomendado pra uso pessoal. Pegue a chave
  em [aistudio.google.com/apikey](https://aistudio.google.com/apikey). É o padrão.
- **Anthropic/Claude** é pago (você adiciona crédito). Use se preferir o Claude.

No `.env`: `PROVIDER=gemini` (padrão) ou `PROVIDER=anthropic`.

## Setup

1. **Crie um bot no Telegram** com o [@BotFather](https://t.me/BotFather) e copie o token.
2. **Pegue a chave grátis do Gemini** em [aistudio.google.com/apikey](https://aistudio.google.com/apikey).
   (Ou, se for usar Claude, pegue em [console.anthropic.com](https://console.anthropic.com) e use `PROVIDER=anthropic`.)
3. **Instale as dependências:**

   ```powershell
   python -m venv .venv
   .venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

4. **Configure o ambiente:** já existe um `.env` no projeto — abra e cole seu
   `TELEGRAM_BOT_TOKEN` e `GEMINI_API_KEY`. (Se ele não existir, copie do modelo:)

   ```powershell
   Copy-Item .env.example .env
   ```

   Opcional: defina `ALLOWED_USER_IDS` (seu ID do Telegram, via [@userinfobot](https://t.me/userinfobot))
   pra travar o bot só pra você.

5. **Rode:**

   ```powershell
   python bot.py
   ```

   No Telegram, mande `/start` pro seu bot.

## Comandos e exemplos

| Você manda | O PILAS faz |
|---|---|
| `gastei 45 no mercado` | registra gasto de R$45 em alimentação |
| `recebi 3500 de salário` | registra entrada de R$3500 em renda |
| `quanto gastei essa semana?` | resumo da semana |
| `o que gastei em lazer esse mês?` | filtra por categoria |
| `gera um resumo do mês` | gráfico de pizza + insight |
| `quero ver meus gastos por dia` | gráfico de linha |
| `compara esse mês com o passado` | gráfico comparativo |
| `me avisa se gastar mais de 500 em lazer por mês` | cria limite (alerta automático) |

## Login e multiusuário 🔐

O PILAS separa as finanças por pessoa. No 1º contato ele pergunta seu nome e
te guia pra criar uma conta (usuário + senha). Depois é só conversar normalmente.

- **Cadastro:** manda `oi` → ele pergunta o nome → escolhe usuário → cria senha. Pronto.
- **Login:** `/login` (ou "entrar") → usuário → senha.
- **Sair:** "quero sair" (ou `/sair`, "encerrar") → desloga. Seus dados ficam guardados.
- Cada usuário só vê os próprios gastos/entradas/limites. A sessão fica salva, então
  reiniciar o bot não te desloga.

Comandos: `/start` (recomeça), `/login`, `/cadastrar`, `/sair`, `/reset` (limpa a
memória da conversa atual).

> Senhas são guardadas com hash (PBKDF2-SHA256 + salt), nunca em texto puro.
> Obs: o Telegram mostra o que você digita no chat — a senha aparece na sua janela
> de conversa como qualquer mensagem. Pra um financeiro pessoal tá de bom tamanho.

## Arquivos

| Arquivo | Papel |
|---|---|
| `bot.py` | Entrada — Telegram, roteamento, memória de conversa |
| `auth.py` | Login/cadastro multiusuário (onboarding, sessão, logout) |
| `agent.py` | Persona do PILAS + loop de tool use (Gemini/Claude) |
| `tools.py` | As 8 tools (schemas + execução no banco) |
| `database.py` | SQLite: schema e acesso |
| `charts.py` | Gráficos com matplotlib |
| `periods.py` | "semana", "mês passado" → intervalos de data |
| `config.py` | Variáveis de ambiente |

## Notas

- O banco (`pilas.db`) e os gráficos (`charts/`) são criados na primeira execução.
- A memória de conversa guarda as últimas ~10 trocas por chat (em memória; some ao reiniciar).
- O modelo padrão é `claude-opus-4-8`; ajuste em `.env` (`MODEL`, `EFFORT`).
