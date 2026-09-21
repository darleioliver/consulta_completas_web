import json
import hashlib
import os
import re
import secrets
import time
from functools import wraps

import psycopg
import boto3
from flask import Flask, jsonify, redirect, render_template_string, request, session, url_for, flash
from psycopg.rows import dict_row
from werkzeug.security import check_password_hash, generate_password_hash


DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
SECRET_KEY = os.getenv("SECRET_KEY", "").strip()
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin").strip()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "").strip()
AGENT_API_KEY = os.getenv("AGENT_API_KEY", "").strip()

AWS_ENDPOINT_URL = os.getenv("AWS_ENDPOINT_URL", "").strip()
AWS_S3_BUCKET_NAME = os.getenv("AWS_S3_BUCKET_NAME", "").strip()
AWS_DEFAULT_REGION = os.getenv("AWS_DEFAULT_REGION", "auto").strip() or "auto"
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "").strip()
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "").strip()

def bucket_configurado():
    return all([
        AWS_ENDPOINT_URL,
        AWS_S3_BUCKET_NAME,
        AWS_ACCESS_KEY_ID,
        AWS_SECRET_ACCESS_KEY,
    ])

def cliente_s3():
    if not bucket_configurado():
        raise RuntimeError("Bucket não configurado.")
    return boto3.client(
        "s3",
        endpoint_url=AWS_ENDPOINT_URL,
        region_name=AWS_DEFAULT_REGION,
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    )


if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL não configurada no Railway.")
if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY não configurada no Railway.")
if not ADMIN_PASSWORD:
    raise RuntimeError("ADMIN_PASSWORD não configurada no Railway.")

app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_SAMESITE="Lax",
)

FAIXAS_RENDA_DESCRICAO = {
    "1": "R$ 0 até R$ 999",
    "2": "R$ 1.000 até R$ 1.499",
    "3": "R$ 1.500 até R$ 1.999",
    "4": "R$ 2.000 até R$ 2.499",
    "5": "R$ 2.500 até R$ 2.999",
    "6": "R$ 3.000 até R$ 3.999",
    "7": "R$ 4.000 até R$ 4.999",
    "8": "R$ 5.000 até R$ 5.999",
    "9": "R$ 6.000 até R$ 6.999",
    "10": "R$ 7.000 até R$ 7.999",
    "11": "R$ 8.000 até R$ 8.999",
    "12": "R$ 9.000 até R$ 20.000",
}


UF_NOMES = {
    "AC": "Acre", "AL": "Alagoas", "AP": "Amapá", "AM": "Amazonas",
    "BA": "Bahia", "CE": "Ceará", "DF": "Distrito Federal",
    "ES": "Espírito Santo", "GO": "Goiás", "MA": "Maranhão",
    "MT": "Mato Grosso", "MS": "Mato Grosso do Sul", "MG": "Minas Gerais",
    "PA": "Pará", "PB": "Paraíba", "PR": "Paraná", "PE": "Pernambuco",
    "PI": "Piauí", "RJ": "Rio de Janeiro", "RN": "Rio Grande do Norte",
    "RS": "Rio Grande do Sul", "RO": "Rondônia", "RR": "Roraima",
    "SC": "Santa Catarina", "SP": "São Paulo", "SE": "Sergipe",
    "TO": "Tocantins",
}


def conectar():
    return psycopg.connect(
        DATABASE_URL,
        row_factory=dict_row,
        connect_timeout=15,
    )


def init_db():
    ultimo_erro = None
    for tentativa in range(15):
        try:
            with conectar() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS usuarios (
                            id BIGSERIAL PRIMARY KEY,
                            usuario VARCHAR(80) UNIQUE NOT NULL,
                            senha_hash TEXT NOT NULL,
                            perfil VARCHAR(20) NOT NULL DEFAULT 'CLIENTE',
                            saldo BIGINT NOT NULL DEFAULT 0,
                            ativo BOOLEAN NOT NULL DEFAULT TRUE,
                            criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        )
                    """)
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS movimentacoes (
                            id BIGSERIAL PRIMARY KEY,
                            usuario_id BIGINT NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
                            valor BIGINT NOT NULL,
                            tipo VARCHAR(30) NOT NULL,
                            descricao TEXT,
                            pedido_id BIGINT,
                            criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        )
                    """)
                    cur.execute("ALTER TABLE movimentacoes ADD COLUMN IF NOT EXISTS pedido_id BIGINT")
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS pedidos (
                            id BIGSERIAL PRIMARY KEY,
                            usuario_id BIGINT NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
                            quantidade INTEGER NOT NULL,
                            status VARCHAR(30) NOT NULL DEFAULT 'AGUARDANDO',
                            progresso INTEGER NOT NULL DEFAULT 0,
                            mensagem TEXT,
                            filtros_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                            resultado_json JSONB,
                            arquivo_chave TEXT,
                            saldo_descontado BOOLEAN NOT NULL DEFAULT FALSE,
                            criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                            iniciado_em TIMESTAMPTZ,
                            concluido_em TIMESTAMPTZ,
                            erro TEXT
                        )
                    """)
                    cur.execute("ALTER TABLE pedidos ADD COLUMN IF NOT EXISTS progresso INTEGER NOT NULL DEFAULT 0")
                    cur.execute("ALTER TABLE pedidos ADD COLUMN IF NOT EXISTS mensagem TEXT")
                    cur.execute("ALTER TABLE pedidos ADD COLUMN IF NOT EXISTS erro TEXT")
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS menu_opcoes (
                            tipo VARCHAR(40) NOT NULL,
                            valor TEXT NOT NULL,
                            PRIMARY KEY (tipo, valor)
                        )
                    """)
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS menu_uf_cidade (
                            uf VARCHAR(2) NOT NULL,
                            cidade TEXT NOT NULL,
                            PRIMARY KEY (uf, cidade)
                        )
                    """)
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS menu_config (
                            chave VARCHAR(60) PRIMARY KEY,
                            valor TEXT NOT NULL
                        )
                    """)
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS consultas_contagem (
                            id BIGSERIAL PRIMARY KEY,
                            usuario_id BIGINT NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
                            chave_hash VARCHAR(64) NOT NULL,
                            filtros_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                            status VARCHAR(20) NOT NULL DEFAULT 'AGUARDANDO',
                            quantidade BIGINT,
                            erro TEXT,
                            criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                            iniciado_em TIMESTAMPTZ,
                            concluido_em TIMESTAMPTZ
                        )
                    """)
                    cur.execute("CREATE INDEX IF NOT EXISTS idx_contagem_status ON consultas_contagem(status, id)")
                    cur.execute("CREATE INDEX IF NOT EXISTS idx_contagem_hash ON consultas_contagem(usuario_id, chave_hash, concluido_em DESC)")
                    cur.execute("CREATE INDEX IF NOT EXISTS idx_pedidos_status ON pedidos(status)")
                    cur.execute("CREATE INDEX IF NOT EXISTS idx_pedidos_usuario ON pedidos(usuario_id)")
                    cur.execute("CREATE INDEX IF NOT EXISTS idx_menu_uf_cidade_uf ON menu_uf_cidade(uf)")

                    cur.execute("""
                        INSERT INTO usuarios (usuario, senha_hash, perfil, saldo, ativo)
                        VALUES (%s, %s, 'ADMIN', 0, TRUE)
                        ON CONFLICT (usuario)
                        DO UPDATE SET
                            senha_hash=EXCLUDED.senha_hash,
                            perfil='ADMIN',
                            ativo=TRUE
                    """, (ADMIN_USERNAME, generate_password_hash(ADMIN_PASSWORD)))
                conn.commit()
            return
        except Exception as exc:
            ultimo_erro = exc
            if tentativa == 14:
                raise
            time.sleep(2)
    raise ultimo_erro


init_db()


def csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


app.jinja_env.globals["csrf_token"] = csrf_token


def validar_csrf():
    esperado = session.get("csrf_token")
    recebido = request.form.get("csrf_token", "")
    return bool(esperado and recebido and secrets.compare_digest(esperado, recebido))


def usuario_atual():
    uid = session.get("usuario_id")
    if not uid:
        return None
    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM usuarios WHERE id=%s", (uid,))
            return cur.fetchone()


def login_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        usuario = usuario_atual()
        if not usuario or not usuario["ativo"]:
            session.clear()
            return redirect(url_for("login"))
        return func(*args, **kwargs)
    return wrapper


def admin_required(func):
    @wraps(func)
    @login_required
    def wrapper(*args, **kwargs):
        if usuario_atual()["perfil"] != "ADMIN":
            return redirect(url_for("painel"))
        return func(*args, **kwargs)
    return wrapper


def api_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not AGENT_API_KEY:
            return jsonify({"erro": "AGENT_API_KEY_nao_configurada"}), 503
        auth = request.headers.get("Authorization", "")
        if not secrets.compare_digest(auth, f"Bearer {AGENT_API_KEY}"):
            return jsonify({"erro": "nao_autorizado"}), 401
        return func(*args, **kwargs)
    return wrapper


def split_texto(texto):
    import re
    if not texto:
        return []
    partes = re.split(r"[,;\n\r\s]+", texto)
    saida = []
    vistos = set()
    for item in partes:
        item = item.strip()
        if item and item not in vistos:
            vistos.add(item)
            saida.append(item)
    return saida


def opcoes(tipo):
    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT valor FROM menu_opcoes WHERE tipo=%s ORDER BY valor", (tipo,))
            return [r["valor"] for r in cur.fetchall()]


def cidades_menu():
    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT uf, cidade FROM menu_uf_cidade ORDER BY cidade, uf")
            return cur.fetchall()


def config_menu(chave, padrao=""):
    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT valor FROM menu_config WHERE chave=%s", (chave,))
            r = cur.fetchone()
            return r["valor"] if r else padrao


def saldo_reservado(usuario_id):
    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COALESCE(SUM(quantidade),0) AS total
                FROM pedidos
                WHERE usuario_id=%s
                  AND status IN ('AGUARDANDO','PROCESSANDO')
            """, (usuario_id,))
            return int(cur.fetchone()["total"] or 0)


BASE_STYLE = r"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

:root {
  --bg: #0f172a;
  --bg-page: #f8fafc;
  --card: #ffffff;
  --text: #0f172a;
  --muted: #64748b;
  --line: #e2e8f0;
  --primary: #4f46e5;
  --primary-hover: #4338ca;
  --primary-light: #eeef2e0;
  --primary-soft: #eef2ff;
  --accent: #06b6d4;
  --danger: #ef4444;
  --danger-soft: #fef2f2;
  --green: #10b981;
  --green-soft: #ecfdf5;
  --amber: #f59e0b;
  --amber-soft: #fffbeb;
  --shadow-sm: 0 1px 2px 0 rgb(0 0 0 / 0.05);
  --shadow: 0 4px 6px -1px rgb(0 0 0 / 0.07), 0 2px 4px -2px rgb(0 0 0 / 0.07);
  --shadow-lg: 0 10px 25px -3px rgb(0 0 0 / 0.08), 0 4px 6px -4px rgb(0 0 0 / 0.04);
  --radius: 14px;
}

* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body { 
  margin: 0; 
  font-family: 'Inter', system-ui, -apple-system, sans-serif; 
  background-color: var(--bg-page); 
  color: var(--text); 
  -webkit-font-smoothing: antialiased;
}

a { text-decoration: none; color: inherit; }

.wrap { max-width: 1320px; margin: 0 auto; padding: 28px 20px; }

/* Top Header */
.top { display: flex; justify-content: space-between; align-items: center; gap: 16px; margin-bottom: 24px; }
.brand { display: flex; align-items: center; gap: 14px; }
.logo { 
  width: 46px; height: 46px; border-radius: 12px; 
  background: linear-gradient(135deg, var(--primary), var(--accent)); 
  color: #fff; display: grid; place-items: center; font-size: 22px; 
  box-shadow: 0 8px 16px rgba(79, 70, 229, 0.25);
}
.brand h1 { font-size: 22px; font-weight: 800; margin: 0; letter-spacing: -0.02em; color: #0f172a; }
.brand p { font-size: 13px; color: var(--muted); margin: 2px 0 0 0; font-weight: 500; }

.nav { display: flex; gap: 10px; flex-wrap: wrap; }

/* Buttons */
.btn, .btn2, .danger { 
  display: inline-flex; align-items: center; justify-content: center; gap: 8px;
  min-height: 42px; padding: 0 18px; border-radius: 10px; font-weight: 600; 
  cursor: pointer; font-size: 13px; transition: all 0.2s ease; border: none;
}
.btn { 
  background: var(--primary); color: #fff; 
  box-shadow: 0 4px 12px rgba(79, 70, 229, 0.25); 
}
.btn:hover { background: var(--primary-hover); transform: translateY(-1px); }
.btn2 { background: #fff; border: 1px solid var(--line); color: #334155; box-shadow: var(--shadow-sm); }
.btn2:hover { background: #f8fafc; border-color: #cbd5e1; color: #0f172a; }
.danger { background: var(--danger-soft); border: 1px solid #fecaca; color: var(--danger); }
.danger:hover { background: #fee2e2; }

/* Grid & Cards */
.grid { display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 18px; }
.card { 
  background: var(--card); border: 1px solid var(--line); 
  border-radius: var(--radius); padding: 22px; box-shadow: var(--shadow);
}
.w3 { grid-column: span 3; }
.w4 { grid-column: span 4; }
.w6 { grid-column: span 6; }
.w12 { grid-column: 1 / -1; }

/* Metrics Cards */
.metric { display: flex; flex-direction: column; justify-content: space-between; }
.metric strong { display: block; font-size: 28px; font-weight: 800; color: #0f172a; letter-spacing: -0.03em; }
.metric span { display: block; color: var(--muted); font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; margin-top: 6px; }

/* Form Elements */
.section-title { font-size: 16px; font-weight: 700; margin: 0 0 16px 0; color: #0f172a; letter-spacing: -0.01em; }
.fields { display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 16px; }
.field { grid-column: span 4; }
.field.w6 { grid-column: span 6; }
.field.w3 { grid-column: span 3; }
.field.full { grid-column: 1 / -1; }

label { display: block; font-size: 13px; font-weight: 600; margin-bottom: 6px; color: #334155; }
input, select, textarea { 
  width: 100%; border: 1px solid var(--line); border-radius: 10px; 
  padding: 10px 14px; font: inherit; font-size: 13px; background: #fff; color: #0f172a; 
  outline: none; transition: border-color 0.2s, box-shadow 0.2s;
}
input:focus, select:focus, textarea:focus {
  border-color: var(--primary); box-shadow: 0 0 0 3px rgba(79, 70, 229, 0.12);
}
input, select:not([multiple]) { height: 44px; }
select[multiple] { min-height: 120px; }
textarea { min-height: 80px; resize: vertical; }

.helper { font-size: 11px; color: var(--muted); margin-top: 6px; line-height: 1.4; }

/* Flashes & Alerts */
.flash { padding: 14px 16px; border-radius: 10px; margin-bottom: 18px; background: var(--green-soft); color: #065f46; border: 1px solid #a7f3d0; font-size: 13px; font-weight: 500; }
.flash.erro { background: var(--danger-soft); color: #991b1b; border-color: #fecaca; }

/* Badges / Pills */
.pill { display: inline-flex; align-items: center; padding: 4px 10px; border-radius: 999px; font-size: 11px; font-weight: 700; letter-spacing: 0.02em; }
.pill.ATIVO, .pill.CONCLUIDO { background: var(--green-soft); color: #047857; border: 1px solid #a7f3d0; }
.pill.BLOQUEADO, .pill.ERRO { background: var(--danger-soft); color: #b91c1c; border: 1px solid #fecaca; }
.pill.AGUARDANDO { background: var(--amber-soft); color: #b45309; border: 1px solid #fde68a; }
.pill.PROCESSANDO { background: #eff6ff; color: #1d4ed8; border: 1px solid #bfdbfe; }

.muted { color: var(--muted); }

/* Tables */
table { width: 100%; border-collapse: collapse; min-width: 720px; }
th, td { text-align: left; padding: 12px 14px; border-bottom: 1px solid var(--line); font-size: 13px; }
th { font-size: 11px; font-weight: 700; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; background: #f8fafc; }
tr:last-child td { border-bottom: none; }
.table-wrap { overflow-x: auto; border-radius: 10px; border: 1px solid var(--line); }

.actions { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
.actions input { height: 38px; width: 130px; }
.actions button { min-height: 38px; }

.switchrow { display: flex; align-items: center; gap: 10px; padding: 12px 14px; border: 1px solid var(--line); border-radius: 10px; background: #f8fafc; }
.switchrow input { width: auto; height: auto; cursor: pointer; }

.notice { padding: 14px 16px; border-radius: 10px; background: var(--primary-soft); border: 1px solid #c7d2fe; color: #3730a3; font-size: 13px; }
.progress { height: 8px; border-radius: 999px; background: #e2e8f0; overflow: hidden; min-width: 90px; }
.progress > span { display: block; height: 100%; background: linear-gradient(90deg, var(--primary), var(--accent)); transition: width 0.3s ease; }

/* Login */
.loginbody { min-height: 100vh; display: grid; place-items: center; background: radial-gradient(circle at 50% 0%, #1e1b4b 0%, #0f172a 100%); }
.login-card { width: min(420px, calc(100% - 32px)); background: #fff; border-radius: 20px; padding: 36px; box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.35); }
.login-card input { margin-bottom: 16px; }
.login-card .btn { width: 100%; height: 46px; font-size: 14px; }
.login-card h1 { font-size: 24px; font-weight: 800; margin: 0 0 6px 0; color: #0f172a; }
.login-card p { color: var(--muted); font-size: 13px; margin: 0 0 24px 0; }

/* Responsivo */
@media(max-width: 900px) {
  .w3, .w4, .w6, .w12, .field, .field.w6, .field.w3 { grid-column: 1 / -1; }
  .wrap { padding: 16px 12px; }
  .top { align-items: flex-start; flex-direction: column; }
  .card { padding: 16px; }
}

/* Filtros e SmartMulti */
.filter-intro { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; margin-bottom: 18px; flex-wrap: wrap; }
.filter-intro .copy { max-width: 760px; }
.filter-intro .copy p { margin: 4px 0 0 0; color: var(--muted); font-size: 13px; line-height: 1.5; }
.filter-badge { display: inline-flex; align-items: center; gap: 6px; background: var(--primary-soft); color: var(--primary); border: 1px solid #c7d2fe; border-radius: 999px; padding: 6px 12px; font-size: 12px; font-weight: 700; }

.smartmulti { position: relative; }
.smartmulti-native { position: absolute !important; width: 1px !important; height: 1px !important; opacity: 0 !important; pointer-events: none !important; overflow: hidden !important; }
.smartmulti-control { min-height: 44px; border: 1px solid var(--line); border-radius: 10px; background: #fff; display: flex; align-items: center; gap: 6px; flex-wrap: wrap; padding: 6px 10px; cursor: text; transition: border-color 0.2s, box-shadow 0.2s; }
.smartmulti-control:focus-within { border-color: var(--primary); box-shadow: 0 0 0 3px rgba(79, 70, 229, 0.12); }
.smartmulti.disabled .smartmulti-control { background: #f1f5f9; cursor: not-allowed; opacity: 0.7; }
.smartmulti-search { border: 0 !important; box-shadow: none !important; outline: 0 !important; padding: 4px 2px !important; height: 28px !important; min-width: 110px; flex: 1; background: transparent !important; font-size: 13px; }
.smartmulti-chip { display: inline-flex; align-items: center; gap: 6px; max-width: 100%; padding: 4px 8px; border-radius: 6px; background: var(--primary-soft); color: var(--primary); font-size: 12px; font-weight: 600; border: 1px solid #c7d2fe; }
.smartmulti-chip span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 220px; }
.smartmulti-chip button { border: 0; background: transparent; color: var(--primary); font-size: 14px; line-height: 1; padding: 0; cursor: pointer; font-weight: bold; }
.smartmulti-menu { position: absolute; left: 0; right: 0; top: calc(100% + 6px); z-index: 50; background: #fff; border: 1px solid var(--line); border-radius: 12px; box-shadow: var(--shadow-lg); max-height: 260px; overflow-y: auto; padding: 6px; display: none; }
.smartmulti.open .smartmulti-menu { display: block; }
.smartmulti-option { width: 100%; border: 0; background: #fff; border-radius: 8px; padding: 8px 10px; text-align: left; cursor: pointer; font: inherit; font-size: 13px; color: #334155; display: flex; justify-content: space-between; align-items: center; gap: 10px; }
.smartmulti-option:hover, .smartmulti-option:focus { background: var(--primary-soft); color: var(--primary); outline: 0; }
.smartmulti-option.selected { background: var(--primary-soft); color: var(--primary); font-weight: 700; }
.smartmulti-option small { color: var(--muted); }
.smartmulti-empty { padding: 12px; color: var(--muted); font-size: 12px; text-align: center; }

.compact-input { min-height: 44px; }
.form-actions { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-top: 18px; flex-wrap: wrap; }

.mode-card { transition: all 0.2s; }
.mode-card.on { border-color: #c7d2fe; background: var(--primary-soft); }

.order-success { display: flex; align-items: center; justify-content: space-between; gap: 14px; flex-wrap: wrap; }
.order-success strong { font-size: 15px; }
.order-file { font-size: 12px; color: var(--muted); margin-top: 2px; }

/* Quantidade / Painel de Pré-contagem */
.count-panel { display: none; margin: 0 0 20px 0; border: 1px solid #c7d2fe; background: var(--primary-soft); border-radius: var(--radius); padding: 16px 20px; align-items: center; justify-content: space-between; gap: 14px; flex-wrap: wrap; }
.count-panel.show { display: flex; }
.count-copy span { display: block; color: var(--muted); font-size: 12px; margin-bottom: 2px; font-weight: 600; text-transform: uppercase; }
.count-copy strong { display: block; font-size: 26px; color: var(--primary); line-height: 1.1; font-weight: 800; letter-spacing: -0.02em; }
.count-copy small { display: block; color: var(--muted); margin-top: 4px; font-size: 11px; }
.count-state { font-size: 12px; font-weight: 700; color: var(--muted); }
.count-state.loading { color: var(--primary); }
.count-state.error { color: var(--danger); }

.history-actions { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.btn-mini { display: inline-flex; align-items: center; justify-content: center; text-decoration: none; border: 1px solid var(--line); background: #fff; color: #334155; border-radius: 8px; padding: 6px 10px; font-size: 12px; font-weight: 600; white-space: nowrap; transition: all 0.15s ease; }
.btn-mini:hover { border-color: #cbd5e1; background: #f8fafc; }
.btn-mini.download { background: var(--green); color: #fff; border-color: var(--green); }
.btn-mini.download:hover { background: #059669; }

.precount-warning {
  margin-top: 14px;
  border: 1px solid #fde68a;
  background: var(--amber-soft);
  color: #92400e;
  border-radius: 10px;
  padding: 12px 16px;
  font-size: 12px;
  font-weight: 500;
  line-height: 1.5;
}
.precount-warning strong { color: #78350f; font-weight: 700; }

.btn-calc {
  display: inline-flex; align-items: center; justify-content: center; gap: 8px;
  border: 1px solid #3b82f6; background: #2563eb; color: #fff; border-radius: 10px;
  padding: 0 16px; height: 42px; font-size: 13px; font-weight: 600; cursor: pointer;
  box-shadow: 0 2px 4px rgba(37, 99, 235, 0.2); transition: all 0.2s;
}
.btn-calc:hover { background: #1d4ed8; }
.btn-calc:disabled { opacity: 0.5; cursor: not-allowed; }

.btn-clean-strong {
  display: inline-flex; align-items: center; justify-content: center; gap: 6px;
  border: 1px solid #fecaca; background: #fff; color: var(--danger);
  border-radius: 10px; padding: 0 14px; height: 42px; font-size: 13px; font-weight: 600;
  cursor: pointer; transition: all 0.2s;
}
.btn-clean-strong:hover { background: var(--danger-soft); border-color: #fca5a5; }

.calc-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; margin-top: 18px; }
.calc-actions { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.filename-help { font-size: 11px; color: var(--muted); margin-top: 4px; }
</style>
"""

LOGIN_HTML = """<!doctype html><html lang='pt-BR'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Consulta de Contatos</title>""" + BASE_STYLE + """</head><body class='loginbody'><div class='login-card'><div class='logo' style='margin-bottom:20px'>📊</div><h1>Consulta de Contatos</h1><p>Entre com seu usuário e senha para continuar.</p>{% if erro %}<div class='flash erro'>{{erro}}</div>{% endif %}<form method='post'><label>Usuário</label><input name='usuario' autocomplete='username' autofocus required><label>Senha</label><input type='password' name='senha' autocomplete='current-password' required><button class='btn' type='submit'>Entrar na conta</button></form></div></body></html>"""

PAINEL_HTML = """<!doctype html><html lang='pt-BR'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Consulta de Contatos</title>""" + BASE_STYLE + r"""</head><body><div class='wrap'>
<div class='top'><div class='brand'><div class='logo'>📊</div><div><h1>Consulta de Contatos</h1><p>Olá, {{usuario.usuario}}.</p></div></div><div class='nav'>{% if usuario.perfil=='ADMIN' %}<a class='btn2' href='{{url_for("admin")}}'>⚙️ Administração</a>{% endif %}<a class='btn2' href='{{url_for("logout")}}'>Sair</a></div></div>
{% with msgs=get_flashed_messages(with_categories=true) %}{% for cat,msg in msgs %}<div class='flash {% if cat=="erro" %}erro{% endif %}'>{{msg}}</div>{% endfor %}{% endwith %}
<div class='grid'>
<div class='card w3 metric'><strong>{{"{:,}".format(usuario.saldo).replace(",", ".")}}</strong><span>Saldo total</span></div>
<div class='card w3 metric'><strong>{{"{:,}".format(reservado).replace(",", ".")}}</strong><span>Reservado em pedidos</span></div>
<div class='card w3 metric'><strong>{{"{:,}".format(disponivel).replace(",", ".")}}</strong><span>Disponível para novos pedidos</span></div>
<div class='card w3 metric'><strong>{{recentes|length}}</strong><span>Pedidos recentes</span></div>

<div class='card w12'>
<div class='filter-intro'>
  <div class='copy'><div class='section-title' style='margin-bottom:0'>🔎 Nova exportação</div><p>Pesquise e selecione um ou vários estados, cidades e CBOs. Bairro, CEP e DDD podem ser informados separados por vírgula.</p></div>
  <div class='filter-badge'>✓ Filtros combináveis</div>
</div>
{% if not menu_pronto %}<div class='flash erro'>O agente do seu PC ainda não sincronizou os menus. Inicie o agente local primeiro.</div>{% endif %}

<div id='count-panel' class='count-panel' aria-live='polite'>
  <div class='count-copy'>
    <span>Contatos encontrados</span>
    <strong id='count-value'>—</strong>
    <small id='count-note'>A contagem considera os filtros compatíveis com os bancos de quantidade.</small>
  </div>
  <div id='count-state' class='count-state'></div>
</div>

<form id='export-form' method='post' action='{{url_for("criar_pedido")}}'>
<input type='hidden' name='csrf_token' value='{{csrf_token()}}'>
<div class='fields'>

<div class='field w4'>
<label>Estados (UF)</label>
<select id='ufs' class='smartmulti-native' name='ufs' multiple data-placeholder='Pesquisar estado...'>
{% for x in ufs %}<option value='{{x}}'>{{x}} — {{uf_nomes.get(x,x)}}</option>{% endfor %}
</select>
<div class='helper'>Sem seleção = Brasil inteiro. Você pode selecionar vários estados.</div>
</div>

<div class='field w4'>
<label>Cidades</label>
<select id='cidades' class='smartmulti-native' name='cidades' multiple data-placeholder='Pesquisar cidade...'>
{% for x in cidades %}<option value='{{x.cidade}}' data-uf='{{x.uf}}'>{{x.cidade}} — {{x.uf}}</option>{% endfor %}
</select>
<div id='cidade-helper' class='helper'>Selecione um estado para mostrar somente as cidades dele, ou pesquise no Brasil inteiro.</div>
</div>

<div class='field w4'>
<label>Sexo</label>
<select id='sexos' class='smartmulti-native' name='sexos' multiple data-placeholder='Selecionar sexo...'>
{% for x in sexos %}<option value='{{x}}'>{% if x=='F' %}F — Feminino{% elif x=='M' %}M — Masculino{% else %}I — Indefinido{% endif %}</option>{% endfor %}
</select>
<div class='helper'>Sem seleção = todos.</div>
</div>

<div class='field w6'>
<label>CBO</label>
<select id='cbos' class='smartmulti-native' name='cbos' multiple data-placeholder='Digite o CBO para pesquisar...'>
{% for x in cbos %}<option value='{{x}}'>{{x}}</option>{% endfor %}
</select>
<div class='helper'>Você pode selecionar vários CBOs.</div>
</div>

<div class='field w6'>
<label>Faixa de renda</label>
<select id='faixas' class='smartmulti-native' name='faixas_renda' multiple data-placeholder='Selecionar faixa de renda...'>
{% for x in faixas %}<option value='{{x}}'>{{x}} — {{faixas_desc.get(x,'')}}</option>{% endfor %}
</select>
<div class='helper'>Sem seleção = todas as faixas.</div>
</div>

<div class='field w3'>
<label>CEP(s)</label>
<input class='compact-input' id='ceps' name='ceps' placeholder='45000000, 45020000'>
<div class='helper'>Aplicado na exportação tanto na base Atualizados 2026 quanto na base detalhada.</div>
</div>

<div class='field w3'>
<label>Bairro(s)</label>
<input class='compact-input' id='bairros' name='bairros' placeholder='Centro, Candeias, Brasil'>
<div class='helper'>Separe vários bairros por vírgula.</div>
</div>

<div class='field w3'>
<label>DDD(s)</label>
<input class='compact-input' id='ddds' name='ddds' placeholder='77, 73, 75'>
<div class='helper'>Separe vários DDDs por vírgula.</div>
</div>

<div class='field w3'>
<label>Nome do arquivo</label>
<input class='compact-input' id='nome_arquivo' name='nome_arquivo' maxlength='80' placeholder='Ex.: CLIENTES_BAHIA'>
<div class='filename-help'>Opcional. Data e hora serão acrescentadas automaticamente para evitar nomes repetidos.</div>
</div>

<div class='field w3'>
<label>Quantidade</label>
<input type='number' name='quantidade' value='5000' min='1' max='1000000' required>
<div class='helper'>Quantidade final de contatos únicos.</div>
</div>

<div class='field w6'>
<div class='switchrow mode-card' id='idade-card'>
<input id='idade_check' type='checkbox' name='filtrar_idade' value='1'>
<label for='idade_check' style='margin:0'>Filtrar por idade</label>
<input id='idade_min' type='number' name='idade_min' value='{{idade_min}}' min='0' max='90' style='width:95px' disabled>
<span>até</span>
<input id='idade_max' type='number' name='idade_max' value='{{idade_max}}' min='0' max='90' style='width:95px' disabled>
</div>
</div>

<div class='field w6'>
<div class='switchrow mode-card' id='atualizados-card'>
<input id='atualizados' type='checkbox' name='atualizados_2026' value='1'>
<label for='atualizados' style='margin:0'>⚡ Atualizados 2026</label>
<span class='muted' style='font-size:11px'>Somente a base 2026.</span>
</div>
</div>
</div>

<div class='precount-warning'><strong>⚠️ Importante:</strong> Bairro, DDD e CEP são aplicados somente durante a exportação e <u>não entram na pré-contagem</u>. A quantidade calculada pode, portanto, ser maior que a quantidade realmente disponível após esses três filtros.</div>
<div class='notice' style='margin-top:12px'>A quantidade solicitada fica reservada enquanto o pedido estiver aguardando/processando. O saldo só é descontado quando a exportação termina com sucesso, usando a quantidade realmente entregue.</div>
<div class='calc-row'>
  <div class='calc-actions'>
    <button id='calcular-quantidade' class='btn-calc' type='button' {% if disponivel <= 0 %}disabled title='Sem saldo disponível'{% endif %}>🔢 Calcular quantidade</button>
    <button id='limpar-filtros' class='btn-clean-strong' type='button'>🧹 Limpar filtros</button>
  </div>
  <button class='btn' type='submit' {% if not menu_pronto %}disabled{% endif %}>📤 Criar pedido de exportação</button>
</div>
{% if disponivel <= 0 %}<div class='flash erro' style='margin-top:10px'>Seu saldo disponível está zerado. A pré-contagem e novos pedidos ficam indisponíveis até adicionar saldo.</div>{% endif %}
</form>
</div>

<div class='card w12'><div class='section-title'>📋 Últimos pedidos</div><div class='table-wrap'>{% if recentes %}<table><thead><tr><th>Pedido</th><th>Quantidade</th><th>Status</th><th>Progresso</th><th>Mensagem</th><th>Criado</th><th>Ações</th></tr></thead><tbody>{% for p in recentes %}<tr><td><a href='{{url_for("ver_pedido",pedido_id=p.id)}}'><b>#{{p.id}}</b></a></td><td>{{"{:,}".format(p.quantidade).replace(",", ".")}}</td><td><span class='pill {{p.status}}'>{{p.status}}</span></td><td><div class='progress'><span style='width:{{p.progresso}}%'></span></div><small>{{p.progresso}}%</small></td><td>{{p.mensagem or ''}}</td><td>{{p.criado_em}}</td><td><div class='history-actions'><a class='btn-mini' href='{{url_for("ver_pedido",pedido_id=p.id)}}'>Abrir</a>{% if p.status=='CONCLUIDO' and p.arquivo_chave %}<a class='btn-mini download' href='{{url_for("baixar_pedido",pedido_id=p.id)}}'>📥 Baixar</a>{% endif %}</div></td></tr>{% endfor %}</tbody></table>{% else %}<p class='muted'>Nenhum pedido criado ainda.</p>{% endif %}</div></div>
</div></div>

<script>
(function(){
  class SmartMulti {
    constructor(select, opts={}){
      this.select=select;
      this.opts=opts;
      this.disabled=select.disabled;
      this.root=document.createElement('div');
      this.root.className='smartmulti';
      this.control=document.createElement('div');
      this.control.className='smartmulti-control';
      this.control.setAttribute('role','combobox');
      this.control.setAttribute('aria-expanded','false');
      this.input=document.createElement('input');
      this.input.type='text';
      this.input.className='smartmulti-search';
      this.input.autocomplete='off';
      this.input.placeholder=select.dataset.placeholder || 'Pesquisar...';
      this.menu=document.createElement('div');
      this.menu.className='smartmulti-menu';
      this.menu.setAttribute('role','listbox');
      this.menu.setAttribute('aria-multiselectable','true');
      this.control.appendChild(this.input);
      this.root.appendChild(this.control);
      this.root.appendChild(this.menu);
      select.insertAdjacentElement('afterend',this.root);

      this.input.addEventListener('focus',()=>this.open());
      this.input.addEventListener('click',(e)=>{e.stopPropagation();this.open();});
      this.input.addEventListener('input',()=>{this.open();this.renderMenu();});
      this.control.addEventListener('click',(e)=>{
        if(!this.disabled && !e.target.closest('.smartmulti-chip button')) this.input.focus();
      });
      this.input.addEventListener('keydown',(e)=>{
        if(e.key==='Escape') this.close();
        if(e.key==='Backspace' && !this.input.value){
          const selected=this.selectedOptions();
          if(selected.length){selected[selected.length-1].selected=false;this.changed();}
        }
      });
      this.setDisabled(this.disabled);
      this.render();
    }
    allOptions(){ return Array.from(this.select.options); }
    allowedOptions(){
      const fn=this.opts.filter || (()=>true);
      return this.allOptions().filter(fn);
    }
    selectedOptions(){ return this.allOptions().filter(o=>o.selected); }
    open(){
      if(this.disabled) return;
      document.querySelectorAll('.smartmulti.open').forEach(x=>{if(x!==this.root)x.classList.remove('open')});
      this.root.classList.add('open');
      this.control.setAttribute('aria-expanded','true');
      this.renderMenu();
    }
    close(){this.root.classList.remove('open');this.control.setAttribute('aria-expanded','false')}
    render(){
      Array.from(this.control.querySelectorAll('.smartmulti-chip')).forEach(x=>x.remove());
      const selected=this.selectedOptions();
      selected.forEach(opt=>{
        const chip=document.createElement('span');
        chip.className='smartmulti-chip';
        const text=document.createElement('span');
        text.textContent=opt.textContent.trim();
        const remove=document.createElement('button');
        remove.type='button';
        remove.setAttribute('aria-label','Remover '+opt.textContent.trim());
        remove.textContent='×';
        remove.addEventListener('click',(e)=>{
          e.stopPropagation();
          if(this.disabled) return;
          opt.selected=false;
          this.changed();
        });
        chip.appendChild(text);chip.appendChild(remove);
        this.control.insertBefore(chip,this.input);
      });
      this.input.placeholder=selected.length ? 'Adicionar...' : (this.select.dataset.placeholder || 'Pesquisar...');
      this.renderMenu();
    }
    renderMenu(){
      if(!this.root.classList.contains('open')) return;
      const q=this.input.value.trim().toLocaleLowerCase('pt-BR');
      let options=this.allowedOptions().filter(o=>o.textContent.toLocaleLowerCase('pt-BR').includes(q));
      const total=options.length;
      options=options.slice(0,100);
      this.menu.innerHTML='';
      if(!options.length){
        const empty=document.createElement('div');
        empty.className='smartmulti-empty';
        empty.textContent='Nenhuma opção encontrada.';
        this.menu.appendChild(empty);
        return;
      }
      options.forEach(opt=>{
        const b=document.createElement('button');
        b.type='button';
        b.className='smartmulti-option'+(opt.selected?' selected':'');
        const left=document.createElement('span');
        left.textContent=opt.textContent.trim();
        const right=document.createElement('small');
        right.textContent=opt.selected?'✓ Selecionado':'Selecionar';
        b.appendChild(left);b.appendChild(right);
        b.addEventListener('click',(e)=>{
          e.preventDefault();
          e.stopPropagation();
          opt.selected=!opt.selected;
          this.input.value='';
          this.changed();
          this.open();
          this.input.focus();
        });
        this.menu.appendChild(b);
      });
      if(total>100){
        const hint=document.createElement('div');
        hint.className='smartmulti-empty';
        hint.textContent='Mostrando 100 resultados. Digite mais letras para refinar.';
        this.menu.appendChild(hint);
      }
    }
    changed(){
      this.select.dispatchEvent(new Event('change',{bubbles:true}));
      this.render();
    }
    refresh(){
      const allowed=new Set(this.allowedOptions());
      this.selectedOptions().forEach(o=>{if(!allowed.has(o))o.selected=false});
      this.render();
    }
    clear(){
      this.allOptions().forEach(o=>o.selected=false);
      this.input.value='';
      this.changed();
    }
    setDisabled(v){
      this.disabled=!!v;
      this.select.disabled=this.disabled;
      this.input.disabled=this.disabled;
      this.root.classList.toggle('disabled',this.disabled);
      if(this.disabled)this.close();
    }
  }

  const ufSelect=document.getElementById('ufs');
  const cidadeSelect=document.getElementById('cidades');
  const sexoSelect=document.getElementById('sexos');
  const cboSelect=document.getElementById('cbos');
  const faixaSelect=document.getElementById('faixas');

  let ufMulti;
  let cidadeMulti;
  const getUFs=()=>new Set(Array.from(ufSelect.selectedOptions).map(o=>o.value));

  ufMulti=new SmartMulti(ufSelect);
  cidadeMulti=new SmartMulti(cidadeSelect,{
    filter:(opt)=>{
      const ufs=getUFs();
      return !ufs.size || ufs.has(opt.dataset.uf);
    }
  });
  const sexoMulti=new SmartMulti(sexoSelect);
  const cboMulti=new SmartMulti(cboSelect);
  const faixaMulti=new SmartMulti(faixaSelect);

  const cidadeHelper=document.getElementById('cidade-helper');
  function atualizarCidades(){
    const ufs=Array.from(getUFs());
    cidadeMulti.refresh();
    if(!ufs.length){
      cidadeHelper.textContent='Nenhum estado selecionado: pesquise cidades do Brasil inteiro.';
    }else if(ufs.length===1){
      cidadeHelper.textContent='Mostrando somente cidades de '+ufs[0]+'. Você pode selecionar várias.';
    }else{
      cidadeHelper.textContent='Mostrando somente cidades dos estados selecionados: '+ufs.join(', ')+'.';
    }
  }
  ufSelect.addEventListener('change',atualizarCidades);
  atualizarCidades();

  document.addEventListener('click',(e)=>{
    document.querySelectorAll('.smartmulti.open').forEach(root=>{
      if(!root.contains(e.target)){root.classList.remove('open');root.querySelector('.smartmulti-control')?.setAttribute('aria-expanded','false')}
    });
  });

  const atualizados=document.getElementById('atualizados');
  const idadeCheck=document.getElementById('idade_check');
  const idadeMin=document.getElementById('idade_min');
  const idadeMax=document.getElementById('idade_max');
  const ceps=document.getElementById('ceps');
  const idadeCard=document.getElementById('idade-card');
  const atualizadosCard=document.getElementById('atualizados-card');

  function syncModo(){
    const a=atualizados.checked;
    cboMulti.setDisabled(a);
    faixaMulti.setDisabled(a);
    idadeCheck.disabled=a;
    if(a) idadeCheck.checked=false;
    idadeMin.disabled=a||!idadeCheck.checked;
    idadeMax.disabled=a||!idadeCheck.checked;
    ceps.disabled=false;
    idadeCard.classList.toggle('on',idadeCheck.checked&&!a);
    atualizadosCard.classList.toggle('on',a);
  }
  atualizados.addEventListener('change',syncModo);
  idadeCheck.addEventListener('change',syncModo);
  syncModo();

  const countPanel=document.getElementById('count-panel');
  const countValue=document.getElementById('count-value');
  const countState=document.getElementById('count-state');
  const countNote=document.getElementById('count-note');
  const csrfToken=document.querySelector('input[name="csrf_token"]').value;
  let countTimer=null;
  let countPollTimer=null;
  let countSequence=0;

  function selectedValues(select){
    return Array.from(select.selectedOptions).map(o=>o.value);
  }

  function splitComma(value, digitsOnly=false){
    const seen=new Set();
    return String(value||'').split(/[,;\n\r]+/).map(x=>x.trim()).filter(Boolean).map(x=>{
      if(!digitsOnly) return x;
      const d=x.replace(/\D/g,'');
      return d;
    }).filter(Boolean).filter(x=>{if(seen.has(x))return false;seen.add(x);return true});
  }

  function filtrosContagem(){
    const atual=atualizados.checked;
    return {
      ufs:selectedValues(ufSelect),
      cidades:selectedValues(cidadeSelect),
      sexos:selectedValues(sexoSelect),
      cbos:atual?[]:selectedValues(cboSelect),
      faixas_renda:atual?[]:selectedValues(faixaSelect),
      filtrar_idade:(!atual && idadeCheck.checked),
      idade_min:Number(idadeMin.value||0),
      idade_max:Number(idadeMax.value||90),
      ceps:[],
      atualizados_2026:atual
    };
  }

  function temFiltroContavel(f){
    return Boolean(
      f.atualizados_2026 ||
      f.ufs.length || f.cidades.length || f.sexos.length ||
      f.cbos.length || f.faixas_renda.length || f.filtrar_idade
    );
  }

  function esconderContagem(){
    countPanel.classList.remove('show');
    countState.textContent='';
    countValue.textContent='—';
  }

  function formatarNumero(n){
    return new Intl.NumberFormat('pt-BR').format(Number(n||0));
  }

  async function consultarStatus(id, seq){
    if(seq!==countSequence) return;
    try{
      const r=await fetch('/api/contagem/'+id,{headers:{'Accept':'application/json'}});
      if(!r.ok) throw new Error('HTTP '+r.status);
      const data=await r.json();
      if(seq!==countSequence) return;
      if(data.status==='CONCLUIDO'){
        countValue.textContent=formatarNumero(data.quantidade);
        countState.textContent='Atualizado';
        countState.className='count-state';

        countPanel.scrollIntoView({
          behavior:'smooth',
          block:'center'
        });

        return;
      }
      if(data.status==='ERRO'){
        countValue.textContent='—';
        countState.textContent='Não foi possível calcular';
        countState.className='count-state error';
        return;
      }
      countState.textContent=data.status==='PROCESSANDO'?'Calculando...':'Aguardando agente...';
      countState.className='count-state loading';
      countPollTimer=setTimeout(()=>consultarStatus(id,seq),900);
    }catch(e){
      if(seq!==countSequence) return;
      countValue.textContent='—';
      countState.textContent='Agente/servidor indisponível';
      countState.className='count-state error';
    }
  }

  async function solicitarContagem(){
    const f=filtrosContagem();
    countSequence++;
    const seq=countSequence;
    if(countPollTimer){clearTimeout(countPollTimer);countPollTimer=null;}

    if(!temFiltroContavel(f)){
      esconderContagem();
      return;
    }

    countPanel.classList.add('show');
    countValue.textContent='—';
    countState.textContent='Calculando...';
    countState.className='count-state loading';

    countNote.textContent='Bairro, DDD e CEP não entram nesta pré-contagem; eles são aplicados somente na exportação.';

    try{
      const r=await fetch('/api/contagem/solicitar',{
        method:'POST',
        headers:{'Content-Type':'application/json','Accept':'application/json'},
        body:JSON.stringify({csrf_token:csrfToken,filtros:f})
      });
      if(!r.ok) throw new Error('HTTP '+r.status);
      const data=await r.json();
      if(seq!==countSequence) return;
      if(data.status==='CONCLUIDO'){
        countValue.textContent=formatarNumero(data.quantidade);
        countState.textContent=data.cache?'Resultado recente':'Atualizado';
        countState.className='count-state';

        countPanel.scrollIntoView({
          behavior:'smooth',
          block:'center'
        });
      }else{
        consultarStatus(data.id,seq);
      }
    }catch(e){
      if(seq!==countSequence) return;
      countValue.textContent='—';
      countState.textContent='Não foi possível solicitar a contagem';
      countState.className='count-state error';
    }
  }

  function marcarContagemDesatualizada(){
    if(countPanel.classList.contains('show') && countValue.textContent!=='—'){
      countState.textContent='Filtros alterados — calcule novamente';
      countState.className='count-state error';
    }
  }

  [ufSelect,cidadeSelect,sexoSelect,cboSelect,faixaSelect,atualizados,idadeCheck,idadeMin,idadeMax]
    .forEach(el=>el.addEventListener('change',marcarContagemDesatualizada));
  ['ceps','bairros','ddds'].forEach(id=>{
    document.getElementById(id).addEventListener('input',marcarContagemDesatualizada);
  });

  const calcBtn=document.getElementById('calcular-quantidade');
  if(calcBtn){
    calcBtn.addEventListener('click',()=>{
      const f=filtrosContagem();
      if(!temFiltroContavel(f)){
        countPanel.classList.add('show');
        countValue.textContent='—';
        countState.textContent='Selecione UF, cidade, sexo, CBO, renda, idade ou Atualizados 2026.';
        countState.className='count-state error';
        countNote.textContent='Bairro, DDD e CEP não entram na pré-contagem.';
        return;
      }
      solicitarContagem();
    });
  }

  document.getElementById('limpar-filtros').addEventListener('click',()=>{
    [ufMulti,cidadeMulti,sexoMulti,cboMulti,faixaMulti].forEach(x=>x.clear());
    document.getElementById('ceps').value='';
    document.getElementById('bairros').value='';
    document.getElementById('ddds').value='';
    document.getElementById('nome_arquivo').value='';
    idadeCheck.checked=false;
    atualizados.checked=false;
    document.querySelector('input[name="quantidade"]').value='5000';
    atualizarCidades();
    syncModo();
    countSequence++;
    if(countPollTimer){clearTimeout(countPollTimer);countPollTimer=null;}
    esconderContagem();
  });
})();
</script></body></html>"""
PEDIDO_HTML = """<!doctype html><html lang='pt-BR'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><meta http-equiv='refresh' content='5'><title>Pedido</title>""" + BASE_STYLE + r"""</head><body><div class='wrap'><div class='top'><div class='brand'><div class='logo'>📦</div><div><h1>Pedido #{{p.id}}</h1><p>{% if p.status in ['AGUARDANDO','PROCESSANDO'] %}Atualização automática a cada 5 segundos.{% else %}Detalhes da exportação.{% endif %}</p></div></div><div class='nav'><a class='btn2' href='{{url_for("painel")}}'>← Voltar</a></div></div>
<div class='grid'>
<div class='card w3 metric'><strong>{{p.progresso}}%</strong><span>Progresso</span></div>
<div class='card w3 metric'><strong>{{p.status}}</strong><span>Status</span></div>
<div class='card w3 metric'><strong>{{"{:,}".format(p.quantidade).replace(",", ".")}}</strong><span>Solicitados</span></div>
<div class='card w3 metric'><strong>{{"{:,}".format(entregues).replace(",", ".")}}</strong><span>Entregues</span></div>

<div class='card w12'>
<h3 style='margin-top:0'>{{p.mensagem or 'Aguardando...'}}</h3>
<div class='progress' style='height:12px'><span style='width:{{p.progresso}}%'></span></div>

{% if p.erro %}
<div class='flash erro' style='margin-top:15px'>Não foi possível concluir esta exportação. Tente novamente ou entre em contato com o suporte.</div>
{% endif %}

{% if p.status=='CONCLUIDO' %}
<div class='notice order-success' style='margin-top:15px'>
  <div>
    <strong>✓ Exportação concluída com sucesso</strong>
    <div class='order-file'>{{"{:,}".format(entregues).replace(",", ".")}} contatos entregues{% if resultado.arquivo_nome %} · {{resultado.arquivo_nome}}{% endif %}</div>
  </div>
  {% if p.arquivo_chave %}<a class='btn' href='{{url_for("baixar_pedido", pedido_id=p.id)}}'>📥 Baixar Excel</a>{% endif %}
</div>
{% endif %}

{% if usuario.perfil=='ADMIN' and resultado %}
<details style='margin-top:16px'>
<summary class='muted' style='cursor:pointer;font-size:12px;font-weight:800'>Detalhes técnicos</summary>
<pre style='white-space:pre-wrap;background:#f8fafc;padding:12px;border-radius:12px;border:1px solid #edf0f4;font-size:11px'>{{resultado_pretty}}</pre>
</details>
{% endif %}
</div>
</div></div></body></html>"""
ADMIN_HTML = """<!doctype html><html lang='pt-BR'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Administração</title>""" + BASE_STYLE + r"""</head><body><div class='wrap'><div class='top'><div class='brand'><div class='logo'>⚙️</div><div><h1>Administração</h1><p>Usuários, saldos e acessos.</p></div></div><div class='nav'><a class='btn2' href='{{url_for("painel")}}'>← Painel</a><a class='btn2' href='{{url_for("logout")}}'>Sair</a></div></div>
{% with msgs=get_flashed_messages(with_categories=true) %}{% for cat,msg in msgs %}<div class='flash {% if cat=="erro" %}erro{% endif %}'>{{msg}}</div>{% endfor %}{% endwith %}
<div class='grid'><div class='card w4'><h3>Criar usuário</h3><form method='post' action='{{url_for("admin_criar_usuario")}}'><input type='hidden' name='csrf_token' value='{{csrf_token()}}'><label>Usuário</label><input name='usuario' required><label style='margin-top:11px'>Senha</label><input type='password' name='senha' required><label style='margin-top:11px'>Saldo inicial</label><input type='number' name='saldo' value='0' min='0' required><button class='btn' type='submit' style='width:100%;margin-top:13px'>Criar usuário</button></form></div><div class='card w4 metric'><strong>{{total_clientes}}</strong><span>Clientes</span></div><div class='card w4 metric'><strong>{{"{:,}".format(total_saldo).replace(",", ".")}}</strong><span>Saldo total dos clientes</span></div>
<div class='card w12'><h3>Usuários</h3><div class='table-wrap'><table><thead><tr><th>Usuário</th><th>Saldo</th><th>Reservado</th><th>Status</th><th>Ações</th></tr></thead><tbody>{% for u in usuarios %}<tr><td><b>{{u.usuario}}</b>{% if u.perfil=='ADMIN' %} <span class='muted'>ADMIN</span>{% endif %}</td><td>{{"{:,}".format(u.saldo).replace(",", ".")}}</td><td>{{"{:,}".format(u.reservado).replace(",", ".")}}</td><td><span class='pill {% if u.ativo %}ATIVO{% else %}BLOQUEADO{% endif %}'>{% if u.ativo %}ATIVO{% else %}BLOQUEADO{% endif %}</span></td><td>{% if u.perfil!='ADMIN' %}<div class='actions'><form method='post' action='{{url_for("admin_saldo",usuario_id=u.id)}}'><input type='hidden' name='csrf_token' value='{{csrf_token()}}'><input type='number' name='valor' placeholder='+/- saldo' required><button class='btn2'>Saldo</button></form><form method='post' action='{{url_for("admin_toggle",usuario_id=u.id)}}'><input type='hidden' name='csrf_token' value='{{csrf_token()}}'><button class='{% if u.ativo %}danger{% else %}btn2{% endif %}'>{% if u.ativo %}Bloquear{% else %}Ativar{% endif %}</button></form><form method='post' action='{{url_for("admin_senha",usuario_id=u.id)}}'><input type='hidden' name='csrf_token' value='{{csrf_token()}}'><input type='password' name='senha' placeholder='Nova senha' required><button class='btn2'>Senha</button></form></div>{% else %}<span class='muted'>Conta administrativa</span>{% endif %}</td></tr>{% endfor %}</tbody></table></div></div></div></div></body></html>"""


@app.route("/health")
def health():
    return jsonify({"ok": True, "bucket": bucket_configurado()})


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("usuario_id"):
        return redirect(url_for("painel"))
    erro = None
    if request.method == "POST":
        nome = request.form.get("usuario", "").strip()
        senha = request.form.get("senha", "")
        with conectar() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM usuarios WHERE usuario=%s", (nome,))
                u = cur.fetchone()
        if not u or not check_password_hash(u["senha_hash"], senha):
            erro = "Usuário ou senha incorretos."
        elif not u["ativo"]:
            erro = "Esta conta está bloqueada."
        else:
            session.clear()
            session["usuario_id"] = u["id"]
            csrf_token()
            return redirect(url_for("painel"))
    return render_template_string(LOGIN_HTML, erro=erro)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def painel():
    u = usuario_atual()
    reservado = saldo_reservado(u["id"])
    disponivel = max(0, int(u["saldo"]) - reservado)
    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM pedidos WHERE usuario_id=%s ORDER BY id DESC LIMIT 12", (u["id"],))
            recentes = cur.fetchall()
            cur.execute("SELECT COUNT(*) AS n FROM menu_opcoes")
            menu_pronto = int(cur.fetchone()["n"]) > 0
    return render_template_string(
        PAINEL_HTML,
        usuario=u,
        reservado=reservado,
        disponivel=disponivel,
        recentes=recentes,
        menu_pronto=menu_pronto,
        ufs=opcoes("uf"),
        uf_nomes=UF_NOMES,
        cidades=cidades_menu(),
        sexos=opcoes("sexo"),
        cbos=opcoes("cbo"),
        faixas=opcoes("faixa_renda"),
        faixas_desc=FAIXAS_RENDA_DESCRICAO,
        idade_min=int(config_menu("idade_min", "0") or 0),
        idade_max=min(90, int(config_menu("idade_max", "90") or 90)),
    )


def normalizar_filtros_contagem(dados):
    dados = dados if isinstance(dados, dict) else {}

    def lista(nome):
        valor = dados.get(nome, [])
        if not isinstance(valor, list):
            return []
        saida = []
        vistos = set()
        for x in valor:
            x = str(x).strip()
            if x and x not in vistos:
                vistos.add(x)
                saida.append(x)
        return saida[:500]

    atualizados = bool(dados.get("atualizados_2026", False))
    filtrar_idade = bool(dados.get("filtrar_idade", False)) and not atualizados
    try:
        idade_min = max(0, min(90, int(dados.get("idade_min", 0))))
        idade_max = max(0, min(90, int(dados.get("idade_max", 90))))
    except Exception:
        idade_min, idade_max = 0, 90

    ceps = []

    return {
        "ufs": [x.upper() for x in lista("ufs") if len(x.strip()) == 2],
        "cidades": lista("cidades"),
        "sexos": [x.upper() for x in lista("sexos") if x.upper() in {"F", "M", "I"}],
        "cbos": [] if atualizados else lista("cbos"),
        "faixas_renda": [] if atualizados else lista("faixas_renda"),
        "filtrar_idade": filtrar_idade,
        "idade_min": idade_min,
        "idade_max": idade_max,
        "ceps": ceps,
        "atualizados_2026": atualizados,
    }


def tem_filtro_contagem(f):
    return bool(
        f["atualizados_2026"]
        or f["ufs"] or f["cidades"] or f["sexos"]
        or f["cbos"] or f["faixas_renda"] or f["filtrar_idade"]
        or f["ceps"]
    )


@app.route("/api/contagem/solicitar", methods=["POST"])
@login_required
def solicitar_contagem():
    u = usuario_atual()
    reservado = saldo_reservado(u["id"])
    disponivel = int(u["saldo"]) - reservado
    if disponivel <= 0:
        return jsonify({"erro": "saldo_indisponivel", "mensagem": "Sem saldo disponível para calcular quantidade."}), 403

    dados = request.get_json(silent=True) or {}
    recebido = str(dados.get("csrf_token", ""))
    esperado = str(session.get("csrf_token", ""))
    if not esperado or not recebido or not secrets.compare_digest(esperado, recebido):
        return jsonify({"erro": "csrf_invalido"}), 400

    filtros = normalizar_filtros_contagem(dados.get("filtros"))
    if not tem_filtro_contagem(filtros):
        return jsonify({"erro": "selecione_um_filtro"}), 400

    canonico = json.dumps(filtros, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    chave = hashlib.sha256(canonico.encode("utf-8")).hexdigest()

    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, status, quantidade
                FROM consultas_contagem
                WHERE usuario_id=%s
                  AND chave_hash=%s
                  AND status='CONCLUIDO'
                  AND concluido_em > NOW() - INTERVAL '10 minutes'
                ORDER BY id DESC
                LIMIT 1
            """, (u["id"], chave))
            cache = cur.fetchone()
            if cache:
                return jsonify({
                    "id": cache["id"],
                    "status": "CONCLUIDO",
                    "quantidade": int(cache["quantidade"] or 0),
                    "cache": True,
                })

            cur.execute("""
                SELECT id, status
                FROM consultas_contagem
                WHERE usuario_id=%s AND chave_hash=%s
                  AND status IN ('AGUARDANDO','PROCESSANDO')
                ORDER BY id DESC
                LIMIT 1
            """, (u["id"], chave))
            pendente = cur.fetchone()
            if pendente:
                return jsonify({"id": pendente["id"], "status": pendente["status"], "cache": False})

            cur.execute("""
                INSERT INTO consultas_contagem
                    (usuario_id, chave_hash, filtros_json, status)
                VALUES (%s,%s,%s::jsonb,'AGUARDANDO')
                RETURNING id
            """, (u["id"], chave, canonico))
            cid = cur.fetchone()["id"]
        conn.commit()

    return jsonify({"id": cid, "status": "AGUARDANDO", "cache": False})


@app.route("/api/contagem/<int:consulta_id>", methods=["GET"])
@login_required
def status_contagem(consulta_id):
    u = usuario_atual()
    with conectar() as conn:
        with conn.cursor() as cur:
            if u["perfil"] == "ADMIN":
                cur.execute("SELECT id,status,quantidade,erro FROM consultas_contagem WHERE id=%s", (consulta_id,))
            else:
                cur.execute(
                    "SELECT id,status,quantidade,erro FROM consultas_contagem WHERE id=%s AND usuario_id=%s",
                    (consulta_id, u["id"]),
                )
            c = cur.fetchone()
    if not c:
        return jsonify({"erro": "consulta_nao_encontrada"}), 404
    return jsonify({
        "id": c["id"],
        "status": c["status"],
        "quantidade": int(c["quantidade"] or 0) if c["quantidade"] is not None else None,
        "erro": c["erro"],
    })


@app.route("/pedido/<int:pedido_id>")
@login_required
def ver_pedido(pedido_id):
    u = usuario_atual()
    with conectar() as conn:
        with conn.cursor() as cur:
            if u["perfil"] == "ADMIN":
                cur.execute("SELECT * FROM pedidos WHERE id=%s", (pedido_id,))
            else:
                cur.execute("SELECT * FROM pedidos WHERE id=%s AND usuario_id=%s", (pedido_id, u["id"]))
            p = cur.fetchone()
    if not p:
        return "Pedido não encontrado", 404
    resultado = p["resultado_json"] or {}
    if isinstance(resultado, str):
        try:
            resultado = json.loads(resultado)
        except Exception:
            resultado = {"resultado": resultado}
    entregues = int(resultado.get("linhas", 0) or 0) if isinstance(resultado, dict) else 0
    return render_template_string(
        PEDIDO_HTML,
        p=p,
        usuario=u,
        resultado=resultado,
        entregues=entregues,
        resultado_pretty=json.dumps(resultado, ensure_ascii=False, indent=2, default=str),
    )


@app.route("/pedido/<int:pedido_id>/baixar")
@login_required
def baixar_pedido(pedido_id):
    u = usuario_atual()

    with conectar() as conn:
        with conn.cursor() as cur:
            if u["perfil"] == "ADMIN":
                cur.execute(
                    "SELECT id, usuario_id, status, arquivo_chave FROM pedidos WHERE id=%s",
                    (pedido_id,),
                )
            else:
                cur.execute(
                    "SELECT id, usuario_id, status, arquivo_chave FROM pedidos WHERE id=%s AND usuario_id=%s",
                    (pedido_id, u["id"]),
                )
            p = cur.fetchone()

    if not p:
        return "Pedido não encontrado.", 404

    if p["status"] != "CONCLUIDO" or not p["arquivo_chave"]:
        return "Arquivo ainda não está disponível.", 409

    try:
        url = cliente_s3().generate_presigned_url(
            "get_object",
            Params={
                "Bucket": AWS_S3_BUCKET_NAME,
                "Key": p["arquivo_chave"],
            },
            ExpiresIn=900,
        )
    except Exception:
        app.logger.exception("Falha ao gerar link de download do pedido %s", pedido_id)
        return "Não foi possível preparar o download agora.", 503

    return redirect(url)


@app.route("/criar", methods=["POST"])
@login_required
def criar_pedido():
    if not validar_csrf():
        return "CSRF inválido", 400
    u = usuario_atual()
    try:
        quantidade = int(request.form.get("quantidade", "0") or 0)
    except ValueError:
        quantidade = 0
    if quantidade <= 0 or quantidade > 1_000_000:
        flash("Informe uma quantidade válida.", "erro")
        return redirect(url_for("painel"))

    reservado = saldo_reservado(u["id"])
    disponivel = int(u["saldo"]) - reservado
    if quantidade > disponivel:
        flash(f"Saldo disponível insuficiente. Disponível: {disponivel:,}".replace(",", "."), "erro")
        return redirect(url_for("painel"))

    atualizados = request.form.get("atualizados_2026") == "1"
    filtrar_idade = (request.form.get("filtrar_idade") == "1") and not atualizados

    try:
        idade_min = int(request.form.get("idade_min", "0") or 0)
        idade_max = int(request.form.get("idade_max", "90") or 90)
    except ValueError:
        idade_min, idade_max = 0, 90
    idade_min = max(0, min(90, idade_min))
    idade_max = max(0, min(90, idade_max))
    if filtrar_idade and idade_min > idade_max:
        flash("A idade mínima não pode ser maior que a máxima.", "erro")
        return redirect(url_for("painel"))

    filtros = {
        "ufs": request.form.getlist("ufs"),
        "cidades": request.form.getlist("cidades"),
        "sexos": request.form.getlist("sexos"),
        "cbos": [] if atualizados else request.form.getlist("cbos"),
        "faixas_renda": [] if atualizados else request.form.getlist("faixas_renda"),
        "filtrar_idade": filtrar_idade,
        "idade_min": idade_min,
        "idade_max": idade_max,
        "ceps": split_texto(request.form.get("ceps")),
        "bairros": split_texto(request.form.get("bairros")),
        "ddds": split_texto(request.form.get("ddds")),
        "atualizados_2026": atualizados,
    }

    nome_arquivo = str(request.form.get("nome_arquivo", "") or "").strip()
    nome_arquivo = re.sub(r"[^A-Za-zÀ-ÿ0-9 _.-]+", "", nome_arquivo)
    nome_arquivo = re.sub(r"\s+", "_", nome_arquivo).strip("._- ")
    filtros["nome_arquivo"] = nome_arquivo[:80] if nome_arquivo else "CONTATOS"

    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO pedidos
                    (usuario_id, quantidade, status, progresso, mensagem, filtros_json)
                VALUES (%s,%s,'AGUARDANDO',0,'Aguardando o computador de processamento.',%s::jsonb)
                RETURNING id
            """, (u["id"], quantidade, json.dumps(filtros, ensure_ascii=False)))
            pedido_id = cur.fetchone()["id"]
        conn.commit()
    return redirect(url_for("ver_pedido", pedido_id=pedido_id))


@app.route("/admin")
@admin_required
def admin():
    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT u.*,
                       COALESCE((SELECT SUM(p.quantidade) FROM pedidos p WHERE p.usuario_id=u.id AND p.status IN ('AGUARDANDO','PROCESSANDO')),0) AS reservado
                FROM usuarios u
                ORDER BY CASE WHEN perfil='ADMIN' THEN 0 ELSE 1 END, usuario
            """)
            usuarios = cur.fetchall()
            cur.execute("SELECT COUNT(*) FILTER (WHERE perfil='CLIENTE') total_clientes, COALESCE(SUM(saldo) FILTER (WHERE perfil='CLIENTE'),0) total_saldo FROM usuarios")
            resumo = cur.fetchone()
    return render_template_string(ADMIN_HTML, usuarios=usuarios, total_clientes=resumo["total_clientes"] or 0, total_saldo=resumo["total_saldo"] or 0)


@app.route("/admin/usuarios/criar", methods=["POST"])
@admin_required
def admin_criar_usuario():
    if not validar_csrf():
        return "CSRF inválido", 400
    nome = request.form.get("usuario", "").strip()
    senha = request.form.get("senha", "")
    try:
        saldo = int(request.form.get("saldo", "0") or 0)
    except ValueError:
        saldo = -1
    if not nome or len(senha) < 4 or saldo < 0:
        flash("Confira usuário, senha e saldo inicial.", "erro")
        return redirect(url_for("admin"))
    try:
        with conectar() as conn:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO usuarios(usuario,senha_hash,perfil,saldo,ativo) VALUES(%s,%s,'CLIENTE',%s,TRUE) RETURNING id", (nome, generate_password_hash(senha), saldo))
                uid = cur.fetchone()["id"]
                if saldo:
                    cur.execute("INSERT INTO movimentacoes(usuario_id,valor,tipo,descricao) VALUES(%s,%s,'CREDITO_INICIAL','Saldo inicial')", (uid, saldo))
            conn.commit()
        flash("Usuário criado com sucesso.")
    except psycopg.errors.UniqueViolation:
        flash("Já existe um usuário com esse nome.", "erro")
    return redirect(url_for("admin"))


@app.route("/admin/usuarios/<int:usuario_id>/saldo", methods=["POST"])
@admin_required
def admin_saldo(usuario_id):
    if not validar_csrf():
        return "CSRF inválido", 400
    try:
        valor = int(request.form.get("valor", "0") or 0)
    except ValueError:
        valor = 0
    if not valor:
        flash("Informe um valor diferente de zero.", "erro")
        return redirect(url_for("admin"))
    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT saldo, perfil FROM usuarios WHERE id=%s FOR UPDATE", (usuario_id,))
            alvo = cur.fetchone()
            if not alvo or alvo["perfil"] != "CLIENTE":
                conn.rollback(); flash("Usuário inválido.", "erro"); return redirect(url_for("admin"))
            cur.execute("SELECT COALESCE(SUM(quantidade),0) total FROM pedidos WHERE usuario_id=%s AND status IN ('AGUARDANDO','PROCESSANDO')", (usuario_id,))
            reservado = int(cur.fetchone()["total"] or 0)
            novo = int(alvo["saldo"]) + valor
            if novo < reservado or novo < 0:
                conn.rollback(); flash("O novo saldo não pode ficar abaixo do valor já reservado em pedidos.", "erro"); return redirect(url_for("admin"))
            cur.execute("UPDATE usuarios SET saldo=%s WHERE id=%s", (novo, usuario_id))
            cur.execute("INSERT INTO movimentacoes(usuario_id,valor,tipo,descricao) VALUES(%s,%s,%s,'Ajuste manual pelo administrador')", (usuario_id, valor, "CREDITO_ADMIN" if valor>0 else "DEBITO_ADMIN"))
        conn.commit()
    flash("Saldo atualizado.")
    return redirect(url_for("admin"))


@app.route("/admin/usuarios/<int:usuario_id>/toggle", methods=["POST"])
@admin_required
def admin_toggle(usuario_id):
    if not validar_csrf():
        return "CSRF inválido", 400
    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE usuarios SET ativo=NOT ativo WHERE id=%s AND perfil='CLIENTE'", (usuario_id,))
        conn.commit()
    flash("Status atualizado.")
    return redirect(url_for("admin"))


@app.route("/admin/usuarios/<int:usuario_id>/senha", methods=["POST"])
@admin_required
def admin_senha(usuario_id):
    if not validar_csrf():
        return "CSRF inválido", 400
    senha = request.form.get("senha", "")
    if len(senha) < 4:
        flash("A senha precisa ter pelo menos 4 caracteres.", "erro")
        return redirect(url_for("admin"))
    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE usuarios SET senha_hash=%s WHERE id=%s AND perfil='CLIENTE'", (generate_password_hash(senha), usuario_id))
        conn.commit()
    flash("Senha alterada.")
    return redirect(url_for("admin"))


@app.route("/api/menu/sincronizar", methods=["POST"])
@api_required
def sincronizar_menu():
    dados = request.get_json(force=True) or {}
    mapa = {"ufs": "uf", "sexos": "sexo", "cbos": "cbo", "faixas_renda": "faixa_renda"}
    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM menu_opcoes")
            cur.execute("DELETE FROM menu_uf_cidade")
            for chave, tipo in mapa.items():
                vistos = set()
                for valor in dados.get(chave, []):
                    valor = str(valor).strip()
                    if valor and valor not in vistos:
                        vistos.add(valor)
                        cur.execute("INSERT INTO menu_opcoes(tipo,valor) VALUES(%s,%s) ON CONFLICT DO NOTHING", (tipo, valor))
            for item in dados.get("uf_cidade", []):
                uf = str(item.get("uf", "")).strip().upper()
                cidade = str(item.get("cidade", "")).strip()
                if len(uf)==2 and cidade:
                    cur.execute("INSERT INTO menu_uf_cidade(uf,cidade) VALUES(%s,%s) ON CONFLICT DO NOTHING", (uf, cidade))
            for chave in ("idade_min", "idade_max"):
                if chave in dados:
                    cur.execute("INSERT INTO menu_config(chave,valor) VALUES(%s,%s) ON CONFLICT(chave) DO UPDATE SET valor=EXCLUDED.valor", (chave, str(dados[chave])))
        conn.commit()
    return jsonify({"ok": True, "ufs": len(dados.get("ufs", [])), "cidades": len(dados.get("uf_cidade", []))})


@app.route("/api/contagens/proxima", methods=["POST"])
@api_required
def proxima_contagem():
    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute("BEGIN")
            cur.execute("""
                SELECT c.*
                FROM consultas_contagem c
                JOIN usuarios u ON u.id=c.usuario_id
                WHERE c.status='AGUARDANDO' AND u.ativo=TRUE
                ORDER BY c.id
                FOR UPDATE OF c SKIP LOCKED
                LIMIT 1
            """)
            c = cur.fetchone()
            if not c:
                conn.commit()
                return jsonify({"consulta": None})
            cur.execute(
                "UPDATE consultas_contagem SET status='PROCESSANDO', iniciado_em=NOW() WHERE id=%s",
                (c["id"],),
            )
            conn.commit()

    filtros = c["filtros_json"] or {}
    if isinstance(filtros, str):
        filtros = json.loads(filtros)
    return jsonify({"consulta": {"id": c["id"], "filtros": filtros}})


@app.route("/api/contagens/<int:consulta_id>/concluir", methods=["POST"])
@api_required
def concluir_contagem(consulta_id):
    dados = request.get_json(force=True) or {}
    try:
        quantidade = max(0, int(dados.get("quantidade", 0)))
    except Exception:
        return jsonify({"erro": "quantidade_invalida"}), 400

    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE consultas_contagem
                SET status='CONCLUIDO', quantidade=%s, erro=NULL, concluido_em=NOW()
                WHERE id=%s AND status='PROCESSANDO'
            """, (quantidade, consulta_id))
            ok = cur.rowcount > 0
        conn.commit()
    if not ok:
        return jsonify({"erro": "consulta_nao_encontrada_ou_status_invalido"}), 404
    return jsonify({"ok": True})


@app.route("/api/contagens/<int:consulta_id>/falhar", methods=["POST"])
@api_required
def falhar_contagem(consulta_id):
    dados = request.get_json(force=True) or {}
    erro = str(dados.get("erro", "Falha na contagem"))[:2000]
    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE consultas_contagem
                SET status='ERRO', erro=%s, concluido_em=NOW()
                WHERE id=%s AND status IN ('AGUARDANDO','PROCESSANDO')
            """, (erro, consulta_id))
        conn.commit()
    return jsonify({"ok": True})

@app.route("/api/pedidos/proximo", methods=["POST"])
@api_required
def proximo_pedido():
    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute("BEGIN")
            cur.execute("""
                SELECT p.*, u.usuario
                FROM pedidos p
                JOIN usuarios u ON u.id=p.usuario_id
                WHERE p.status='AGUARDANDO' AND u.ativo=TRUE
                ORDER BY p.id
                FOR UPDATE OF p SKIP LOCKED
                LIMIT 1
            """)
            p = cur.fetchone()
            if not p:
                conn.commit()
                return jsonify({"pedido": None})
            cur.execute("UPDATE pedidos SET status='PROCESSANDO', iniciado_em=NOW(), progresso=1, mensagem='Pedido recebido pelo computador.' WHERE id=%s", (p["id"],))
            conn.commit()
    filtros = p["filtros_json"] or {}
    if isinstance(filtros, str):
        filtros = json.loads(filtros)
    return jsonify({"pedido": {"id": p["id"], "usuario": p["usuario"], "quantidade": p["quantidade"], "filtros": filtros}})


@app.route("/api/pedidos/<int:pedido_id>/preparar-upload", methods=["POST"])
@api_required
def preparar_upload(pedido_id):
    if not bucket_configurado():
        return jsonify({"erro": "bucket_nao_configurado"}), 503

    dados = request.get_json(force=True) or {}
    nome_original = str(dados.get("nome_arquivo", "")).strip()

    if not nome_original:
        return jsonify({"erro": "nome_arquivo_obrigatorio"}), 400

    nome_seguro = re.sub(r"[^A-Za-z0-9._-]+", "_", os.path.basename(nome_original))
    if not nome_seguro.lower().endswith(".xlsx"):
        return jsonify({"erro": "somente_xlsx"}), 400

    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT p.id, p.usuario_id, p.status, u.usuario
                FROM pedidos p
                JOIN usuarios u ON u.id=p.usuario_id
                WHERE p.id=%s
                """,
                (pedido_id,),
            )
            p = cur.fetchone()

    if not p:
        return jsonify({"erro": "pedido_nao_encontrado"}), 404

    if p["status"] != "PROCESSANDO":
        return jsonify({"erro": "status_invalido"}), 409

    chave = f"exportacoes/usuario_{p['usuario_id']}/pedido_{pedido_id}/{nome_seguro}"

    try:
        url = cliente_s3().generate_presigned_url(
            "put_object",
            Params={
                "Bucket": AWS_S3_BUCKET_NAME,
                "Key": chave,
                "ContentType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            },
            ExpiresIn=900,
        )
    except Exception:
        app.logger.exception("Falha ao gerar URL de upload para pedido %s", pedido_id)
        return jsonify({"erro": "falha_preparar_upload"}), 503

    return jsonify({
        "ok": True,
        "upload_url": url,
        "arquivo_chave": chave,
        "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "expira_em_segundos": 900,
    })


@app.route("/api/pedidos/<int:pedido_id>/progresso", methods=["POST"])
@api_required
def progresso_pedido(pedido_id):
    dados = request.get_json(force=True) or {}
    progresso = max(1, min(99, int(dados.get("progresso", 1))))
    mensagem = str(dados.get("mensagem", ""))[:1000]
    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE pedidos SET progresso=%s,mensagem=%s WHERE id=%s AND status='PROCESSANDO'", (progresso, mensagem, pedido_id))
        conn.commit()
    return jsonify({"ok": True})


@app.route("/api/pedidos/<int:pedido_id>/concluir", methods=["POST"])
@api_required
def concluir_pedido(pedido_id):
    dados = request.get_json(force=True) or {}
    resultado = dados.get("resultado") or {}
    mensagem = str(dados.get("mensagem", "Concluído."))[:1000]
    arquivo_chave = dados.get("arquivo_chave")
    try:
        linhas = int(resultado.get("linhas", 0) or 0)
    except Exception:
        return jsonify({"erro": "resultado_invalido"}), 400

    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM pedidos WHERE id=%s FOR UPDATE", (pedido_id,))
            p = cur.fetchone()
            if not p:
                conn.rollback(); return jsonify({"erro": "pedido_nao_encontrado"}), 404
            if p["status"] == "CONCLUIDO":
                conn.commit(); return jsonify({"ok": True, "ja_concluido": True})
            if p["status"] != "PROCESSANDO":
                conn.rollback(); return jsonify({"erro": "status_invalido"}), 409
            if linhas < 0 or linhas > int(p["quantidade"]):
                conn.rollback(); return jsonify({"erro": "quantidade_entregue_invalida"}), 400

            cur.execute("SELECT saldo FROM usuarios WHERE id=%s FOR UPDATE", (p["usuario_id"],))
            saldo = int(cur.fetchone()["saldo"])
            if saldo < linhas:
                conn.rollback(); return jsonify({"erro": "saldo_insuficiente_na_conclusao"}), 409

            if not p["saldo_descontado"] and linhas:
                cur.execute("UPDATE usuarios SET saldo=saldo-%s WHERE id=%s", (linhas, p["usuario_id"]))
                cur.execute("INSERT INTO movimentacoes(usuario_id,valor,tipo,descricao,pedido_id) VALUES(%s,%s,'DEBITO_EXPORTACAO',%s,%s)", (p["usuario_id"], -linhas, f"Pedido #{pedido_id}", pedido_id))

            cur.execute("""
                UPDATE pedidos
                SET status='CONCLUIDO', progresso=100, mensagem=%s, concluido_em=NOW(), resultado_json=%s::jsonb, arquivo_chave=%s, saldo_descontado=TRUE, erro=NULL
                WHERE id=%s
            """, (mensagem, json.dumps(resultado, ensure_ascii=False, default=str), arquivo_chave, pedido_id))
        conn.commit()
    return jsonify({"ok": True, "descontado": linhas})


@app.route("/api/pedidos/<int:pedido_id>/falhar", methods=["POST"])
@api_required
def falhar_pedido(pedido_id):
    dados = request.get_json(force=True) or {}
    erro = str(dados.get("erro", "Erro desconhecido"))[:10000]
    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE pedidos SET status='ERRO', mensagem='Falha no processamento.', concluido_em=NOW(), erro=%s WHERE id=%s AND status='PROCESSANDO'", (erro, pedido_id))
        conn.commit()
    return jsonify({"ok": True})


if __name__ == "__main__":
    porta = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=porta, debug=False)
