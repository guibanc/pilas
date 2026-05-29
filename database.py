"""Camada de acesso ao SQLite do PILAS (multiusuário).

Tabelas:
  users(id, username, senha_hash, nome, criado_em)
  sessions(chat_id, user_id)                       -- quem está logado em cada chat
  transactions(id, user_id, tipo, valor, categoria, descricao, data, criado_em)
  categories(id, nome, cor)                         -- compartilhada entre usuários
  limits(id, user_id, categoria, valor_limite, periodo)
  context(chave, valor)
"""
import binascii
import hashlib
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime

import config

DEFAULT_CATEGORIES = {
    "alimentação": "#E74C3C",
    "transporte": "#3498DB",
    "moradia": "#9B59B6",
    "saúde": "#2ECC71",
    "lazer": "#F39C12",
    "vestuário": "#E91E63",
    "educação": "#1ABC9C",
    "assinaturas": "#34495E",
    "renda": "#27AE60",
    "renda_extra": "#16A085",
    "outros": "#95A5A6",
}


@contextmanager
def get_conn():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    # garante que a pasta do banco existe (importante em hosts com volume)
    pasta = os.path.dirname(config.DB_PATH)
    if pasta:
        os.makedirs(pasta, exist_ok=True)
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                username   TEXT UNIQUE NOT NULL,
                senha_hash TEXT NOT NULL,
                nome       TEXT NOT NULL,
                criado_em  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sessions (
                chat_id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS transactions (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id   INTEGER NOT NULL,
                tipo      TEXT NOT NULL,
                valor     REAL NOT NULL,
                categoria TEXT NOT NULL,
                descricao TEXT,
                data      TEXT NOT NULL,
                criado_em TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS categories (
                id   INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT UNIQUE NOT NULL,
                cor  TEXT
            );

            CREATE TABLE IF NOT EXISTS limits (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id      INTEGER NOT NULL,
                categoria    TEXT NOT NULL,
                valor_limite REAL NOT NULL,
                periodo      TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS context (
                chave TEXT PRIMARY KEY,
                valor TEXT
            );

            CREATE TABLE IF NOT EXISTS prefs (
                user_id     INTEGER PRIMARY KEY,
                daily       INTEGER DEFAULT 1,
                daily_hour  INTEGER DEFAULT 21,
                weekly      INTEGER DEFAULT 1,
                weekly_day  INTEGER DEFAULT 6,   -- 0=segunda ... 6=domingo
                weekly_hour INTEGER DEFAULT 20,
                cofrinho    INTEGER DEFAULT 1,
                cof_day     INTEGER DEFAULT 5,    -- sábado
                cof_hour    INTEGER DEFAULT 12,
                last_daily  TEXT DEFAULT '',
                last_weekly TEXT DEFAULT '',
                last_cof    TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS savings (
                user_id INTEGER PRIMARY KEY,
                meta    REAL DEFAULT 0,
                total   REAL DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_tx_user ON transactions(user_id, data);
            CREATE INDEX IF NOT EXISTS idx_lim_user ON limits(user_id);
            """
        )
        for nome, cor in DEFAULT_CATEGORIES.items():
            conn.execute(
                "INSERT OR IGNORE INTO categories (nome, cor) VALUES (?, ?)", (nome, cor)
            )


# ------------------------------ senhas ------------------------------

def hash_senha(senha: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", senha.encode(), salt, 100_000)
    return binascii.hexlify(salt).decode() + "$" + binascii.hexlify(dk).decode()


def verifica_senha(senha: str, armazenado: str) -> bool:
    try:
        salt_hex, hash_hex = armazenado.split("$")
        salt = binascii.unhexlify(salt_hex)
        dk = hashlib.pbkdf2_hmac("sha256", senha.encode(), salt, 100_000)
        return binascii.hexlify(dk).decode() == hash_hex
    except Exception:
        return False


# ------------------------------ usuários ------------------------------

def create_user(username: str, senha: str, nome: str):
    """Cria usuário. Retorna o dict do usuário, ou None se o username já existir."""
    with get_conn() as conn:
        try:
            cur = conn.execute(
                "INSERT INTO users (username, senha_hash, nome, criado_em) VALUES (?, ?, ?, ?)",
                (username, hash_senha(senha), nome, datetime.now().isoformat()),
            )
            return {"id": cur.lastrowid, "username": username, "nome": nome}
        except sqlite3.IntegrityError:
            return None


def get_user_by_username(username: str):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        return dict(row) if row else None


def get_user(user_id: int):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None


# ------------------------------ sessões ------------------------------

def set_session(chat_id: int, user_id: int) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO sessions (chat_id, user_id) VALUES (?, ?) "
            "ON CONFLICT(chat_id) DO UPDATE SET user_id = excluded.user_id",
            (chat_id, user_id),
        )


def get_session_user(chat_id: int):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.chat_id = ?",
            (chat_id,),
        ).fetchone()
        return dict(row) if row else None


def clear_session(chat_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM sessions WHERE chat_id = ?", (chat_id,))


# ----------------------------- transações -----------------------------

def insert_transaction(user_id, tipo, valor, categoria, descricao, data) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO transactions (user_id, tipo, valor, categoria, descricao, data, criado_em)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (user_id, tipo, valor, categoria, descricao, data, datetime.now().isoformat()),
        )
        return cur.lastrowid


def query_transactions(user_id, data_inicio=None, data_fim=None, categoria=None, tipo=None):
    sql = "SELECT * FROM transactions WHERE user_id = ?"
    params = [user_id]
    if data_inicio:
        sql += " AND data >= ?"
        params.append(data_inicio)
    if data_fim:
        sql += " AND data <= ?"
        params.append(data_fim)
    if categoria:
        sql += " AND categoria = ?"
        params.append(categoria)
    if tipo:
        sql += " AND tipo = ?"
        params.append(tipo)
    sql += " ORDER BY data DESC, id DESC"
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


# ----------------------------- categorias -----------------------------

def list_categories():
    with get_conn() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM categories ORDER BY nome")]


def category_exists(nome) -> bool:
    with get_conn() as conn:
        return conn.execute("SELECT 1 FROM categories WHERE nome = ?", (nome,)).fetchone() is not None


def insert_category(nome, cor="#95A5A6") -> bool:
    with get_conn() as conn:
        try:
            conn.execute("INSERT INTO categories (nome, cor) VALUES (?, ?)", (nome, cor))
            return True
        except sqlite3.IntegrityError:
            return False


# ------------------------------- limites -------------------------------

def upsert_limit(user_id, categoria, valor_limite, periodo) -> None:
    with get_conn() as conn:
        existe = conn.execute(
            "SELECT id FROM limits WHERE user_id = ? AND categoria = ? AND periodo = ?",
            (user_id, categoria, periodo),
        ).fetchone()
        if existe:
            conn.execute(
                "UPDATE limits SET valor_limite = ? WHERE id = ?", (valor_limite, existe["id"])
            )
        else:
            conn.execute(
                "INSERT INTO limits (user_id, categoria, valor_limite, periodo) VALUES (?, ?, ?, ?)",
                (user_id, categoria, valor_limite, periodo),
            )


def list_limits(user_id):
    with get_conn() as conn:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM limits WHERE user_id = ? ORDER BY categoria", (user_id,)
            )
        ]


def get_limit_for_category(user_id, categoria):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM limits WHERE user_id = ? AND categoria = ? LIMIT 1",
            (user_id, categoria),
        ).fetchone()
        return dict(row) if row else None


# ----------------------- preferências de lembrete -----------------------

_PREF_DEFAULTS = {
    "daily": 1, "daily_hour": 21, "weekly": 1, "weekly_day": 6, "weekly_hour": 20,
    "cofrinho": 1, "cof_day": 5, "cof_hour": 12,
    "last_daily": "", "last_weekly": "", "last_cof": "",
}


def get_prefs(user_id):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM prefs WHERE user_id = ?", (user_id,)).fetchone()
        if row:
            return dict(row)
    p = dict(_PREF_DEFAULTS)
    p["user_id"] = user_id
    return p


def set_pref(user_id, campo, valor):
    if campo not in _PREF_DEFAULTS:
        return
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO prefs (user_id) VALUES (?) ON CONFLICT(user_id) DO NOTHING",
            (user_id,),
        )
        conn.execute(f"UPDATE prefs SET {campo} = ? WHERE user_id = ?", (valor, user_id))


def all_user_ids():
    with get_conn() as conn:
        return [r["id"] for r in conn.execute("SELECT id FROM users")]


def get_chats_for_user(user_id):
    with get_conn() as conn:
        return [r["chat_id"] for r in conn.execute(
            "SELECT chat_id FROM sessions WHERE user_id = ?", (user_id,)
        )]


# ------------------------------- cofrinho -------------------------------

def get_savings(user_id):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM savings WHERE user_id = ?", (user_id,)).fetchone()
        return dict(row) if row else {"user_id": user_id, "meta": 0.0, "total": 0.0}


def set_savings_meta(user_id, meta):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO savings (user_id, meta) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET meta = excluded.meta",
            (user_id, meta),
        )


def add_savings(user_id, delta):
    """Soma `delta` ao cofrinho (pode ser negativo). Retorna o novo total."""
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO savings (user_id, total) VALUES (?, 0) ON CONFLICT(user_id) DO NOTHING",
            (user_id,),
        )
        conn.execute(
            "UPDATE savings SET total = MAX(0, total + ?) WHERE user_id = ?",
            (delta, user_id),
        )
        row = conn.execute("SELECT total FROM savings WHERE user_id = ?", (user_id,)).fetchone()
        return row["total"]
