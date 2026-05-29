"""Gestão de login simples do PILAS (multiusuário, dentro do Telegram).

Fluxo conversacional:
  - 1º contato     -> "Olá! Como posso te chamar?"  (pergunta o nome)
  - depois do nome -> cria conta: escolhe usuário e senha (ou /login se já tem)
  - logado         -> mensagens normais passam direto pro bot
  - "quero sair"   -> encerra a sessão (logout)

Estado da conversa fica em memória; a sessão logada fica no banco
(tabela sessions), então reiniciar o bot não desloga ninguém.
"""
import re
import unicodedata

import database

# Estado transitório por chat: {"step": str, "data": {...}}
_state: dict[int, dict] = {}

_USERNAME_RE = re.compile(r"^[a-z0-9_]{3,20}$")

_LOGOUT = {"sair", "quero sair", "logout", "log out", "encerrar", "deslogar",
           "sair da conta", "/sair", "tchau", "encerrar consulta"}


def _norm(s: str) -> str:
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    return s.strip().lower()


def current_user(chat_id: int):
    """Usuário logado neste chat (dict) ou None."""
    return database.get_session_user(chat_id)


def _result(reply=None, passthrough=False, user=None):
    return {"reply": reply, "passthrough": passthrough, "user": user}


def handle(chat_id: int, texto: str):
    """Processa a camada de autenticação.

    Retorna dict:
      reply       -> texto a enviar (ou None)
      passthrough -> True se a mensagem deve seguir pro fluxo financeiro
      user        -> dict do usuário logado (quando passthrough=True)
    """
    n = _norm(texto)
    user = current_user(chat_id)
    state = _state.get(chat_id)

    # ---- Logout (vale a qualquer momento, se estiver logado) ----
    if n in _LOGOUT:
        _state.pop(chat_id, None)
        if user:
            database.clear_session(chat_id)
            return _result(
                f"Até mais, {user['nome']}! 🐷 Suas finanças ficam guardadas. "
                "Manda um 'oi' quando quiser voltar."
            )
        return _result("Você nem tá logado ainda 😅. Manda um 'oi' pra começar.")

    # ---- /start: reinicia o fluxo ----
    if n in ("/start", "start"):
        _state.pop(chat_id, None)
        if user:
            return _result(
                f"Você já tá logado, {user['nome']}! 🐷 Manda suas finanças, "
                "ou \"quero sair\" pra trocar de conta."
            )
        _state[chat_id] = {"step": "ASK_NAME", "data": {}}
        return _result("Olá! 🐷 Eu sou o PILAS, seu financeiro de bolso.\nComo posso te chamar?")

    # ---- Comandos explícitos ----
    if n in ("/login", "login", "entrar"):
        _state[chat_id] = {"step": "LOGIN_USER", "data": {}}
        return _result("Bora entrar. Qual seu nome de usuário?")

    if n in ("/cadastrar", "cadastrar", "criar conta", "nova conta"):
        _state[chat_id] = {"step": "ASK_NAME", "data": {}}
        return _result("Show, conta nova! Como posso te chamar?")

    # ---- Já logado e sem fluxo pendente: deixa passar ----
    if user and not state:
        return _result(passthrough=True, user=user)

    # ---- Sem estado e sem login: inicia onboarding ----
    if not state:
        _state[chat_id] = {"step": "ASK_NAME", "data": {}}
        return _result(
            "Olá! 🐷 Eu sou o PILAS, seu financeiro de bolso.\n"
            "Como posso te chamar?"
        )

    step = state["step"]
    data = state["data"]

    # ---- Onboarding: nome -> usuário -> senha ----
    if step == "ASK_NAME":
        nome = texto.strip()[:40] or "amigo(a)"
        data["nome"] = nome
        state["step"] = "REG_USER"
        return _result(
            f"Prazer, {nome}! 😄\n"
            "Pra separar suas finanças das de outras pessoas, vamos criar uma conta "
            "rapidinho.\nEscolha um nome de usuário (3 a 20 letras/números, sem espaço).\n"
            "(Já tem conta? Manda /login)"
        )

    if step == "REG_USER":
        username = _norm(texto).replace(" ", "")
        if not _USERNAME_RE.match(username):
            return _result("Usuário inválido. Use 3 a 20 letras/números, sem espaço. Tenta outro:")
        if database.get_user_by_username(username):
            return _result(
                f"O usuário '{username}' já existe. Se for você, manda /login. "
                "Senão, escolhe outro:"
            )
        data["username"] = username
        state["step"] = "REG_PASS"
        return _result(f"Boa, '{username}' tá livre. Agora cria uma senha (mín. 4 caracteres):")

    if step == "REG_PASS":
        senha = texto.strip()
        if len(senha) < 4:
            return _result("Senha muito curta (mínimo 4 caracteres). Tenta de novo:")
        novo = database.create_user(data["username"], senha, data["nome"])
        _state.pop(chat_id, None)
        if not novo:
            return _result("Ops, esse usuário acabou de ser registrado. Manda /cadastrar de novo.")
        database.set_session(chat_id, novo["id"])
        return _result(
            f"Conta criada e você já tá logado, {novo['nome']}! 🐷✅\n"
            "Agora é só mandar suas finanças: ex. \"gastei 45 no mercado\".\n"
            "(Pra sair depois, manda \"quero sair\")"
        )

    # ---- Login: usuário -> senha ----
    if step == "LOGIN_USER":
        data["username"] = _norm(texto).replace(" ", "")
        state["step"] = "LOGIN_PASS"
        return _result("E a senha?")

    if step == "LOGIN_PASS":
        senha = texto.strip()
        u = database.get_user_by_username(data.get("username", ""))
        _state.pop(chat_id, None)
        if u and database.verifica_senha(senha, u["senha_hash"]):
            database.set_session(chat_id, u["id"])
            return _result(f"Bem-vindo de volta, {u['nome']}! 🐷 Bora controlar essa grana 💸")
        return _result("Usuário ou senha incorretos 🙈. Manda /login pra tentar de novo.")

    # fallback defensivo
    _state.pop(chat_id, None)
    return _result("Beleza, recomeçando. Manda um 'oi'. 🐷")
