"""Configuração central do PILAS — lê variáveis do .env."""
import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
OWNER_NAME = os.getenv("OWNER_NAME", "Chefe")

# Provedor de IA: "gemini" (tem tier grátis) ou "anthropic" (pago)
PROVIDER = os.getenv("PROVIDER", "gemini").strip().lower()

# Gemini (Google AI Studio) — https://aistudio.google.com/apikey
# Aceita 1 chave (GEMINI_API_KEY) ou várias (GEMINI_API_KEYS separadas por vírgula).
# Com várias, o bot rotaciona: quando uma bate no limite, pula pra próxima.
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
_extra_keys = os.getenv("GEMINI_API_KEYS", "")
GEMINI_KEYS = []
for _k in [GEMINI_API_KEY] + _extra_keys.replace(";", ",").split(","):
    _k = _k.strip()
    if _k and _k not in GEMINI_KEYS:
        GEMINI_KEYS.append(_k)
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")

# Anthropic (Claude) — https://console.anthropic.com
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# Lista de IDs liberados (vazio = libera geral)
_allowed = os.getenv("ALLOWED_USER_IDS", "").strip()
ALLOWED_USER_IDS = (
    {int(x) for x in _allowed.replace(";", ",").split(",") if x.strip()}
    if _allowed
    else set()
)

MODEL = os.getenv("MODEL", "claude-opus-4-8")  # usado só no provider anthropic
EFFORT = os.getenv("EFFORT", "medium")  # low | medium | high | max (anthropic)
DB_PATH = os.getenv("DB_PATH", "pilas.db")
CHARTS_DIR = os.getenv("CHARTS_DIR", "charts")

# Resolve mensagens comuns localmente (sem IA) pra economizar quota. true/false
FAST_PATH = os.getenv("FAST_PATH", "true").strip().lower() in ("1", "true", "sim", "yes")


def validate() -> None:
    """Garante que o essencial está configurado antes de subir o bot."""
    faltando = []
    if not TELEGRAM_BOT_TOKEN:
        faltando.append("TELEGRAM_BOT_TOKEN")
    if PROVIDER == "anthropic" and not ANTHROPIC_API_KEY:
        faltando.append("ANTHROPIC_API_KEY")
    if PROVIDER == "gemini" and not GEMINI_KEYS:
        faltando.append("GEMINI_API_KEY")
    if PROVIDER not in ("gemini", "anthropic"):
        raise SystemExit(f"PROVIDER inválido: '{PROVIDER}'. Use 'gemini' ou 'anthropic'.")
    if faltando:
        raise SystemExit(
            "Faltam variáveis no .env: "
            + ", ".join(faltando)
            + "\nCopie .env.example para .env e preencha."
        )
