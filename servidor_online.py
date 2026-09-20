import json
import os
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
                    # Migração segura para quem já tinha a tabela da versão 1.
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
:root{--bg:#f4f7fb;--card:#fff;--text:#172033;--muted:#697586;--line:#e5eaf1;--primary:#0f766e;--primary2:#14b8a6;--danger:#b42318;--green:#166534;--amber:#8a5a00;--soft:#e9f8f5;--shadow:0 10px 32px rgba(15,23,42,.06)}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;font-family:Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,Arial;background:linear-gradient(180deg,#f8fafc,#f4f7fb);color:var(--text)}a{text-decoration:none;color:inherit}.wrap{max-width:1360px;margin:auto;padding:22px}.top{display:flex;justify-content:space-between;align-items:center;gap:16px;margin-bottom:18px}.brand{display:flex;align-items:center;gap:12px}.logo{width:48px;height:48px;border-radius:15px;background:linear-gradient(135deg,var(--primary),#2dd4bf);color:#fff;display:grid;place-items:center;font-size:23px;box-shadow:0 10px 22px rgba(15,118,110,.18)}.brand h1{font-size:23px;margin:0}.brand p{font-size:12px;color:var(--muted);margin:4px 0 0}.nav{display:flex;gap:8px;flex-wrap:wrap}.btn,.btn2,.danger{display:inline-flex;align-items:center;justify-content:center;min-height:42px;padding:0 14px;border-radius:11px;font-weight:800;cursor:pointer;font-size:13px}.btn{border:0;background:linear-gradient(135deg,var(--primary),var(--primary2));color:#fff;box-shadow:0 8px 18px rgba(15,118,110,.18)}.btn2{background:#fff;border:1px solid var(--line);color:#344054}.danger{background:#fff1f0;border:1px solid #ffd5d1;color:var(--danger)}.grid{display:grid;grid-template-columns:repeat(12,minmax(0,1fr));gap:14px}.card{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:19px;box-shadow:var(--shadow)}.w3{grid-column:span 3}.w4{grid-column:span 4}.w6{grid-column:span 6}.w12{grid-column:1/-1}.metric strong{display:block;font-size:29px;color:var(--primary);letter-spacing:-.02em}.metric span{display:block;color:var(--muted);font-size:11.5px;margin-top:5px}.section-title{font-size:15px;font-weight:850;margin:2px 0 15px}.fields{display:grid;grid-template-columns:repeat(12,minmax(0,1fr));gap:13px}.field{grid-column:span 4}.field.w6{grid-column:span 6}.field.w3{grid-column:span 3}.field.full{grid-column:1/-1}label{display:block;font-size:12px;font-weight:800;margin-bottom:7px;color:#374151}input,select,textarea{width:100%;border:1px solid #d8e0e9;border-radius:11px;padding:9px 11px;font:inherit;background:#fff;color:#1f2937;outline:none}input,select:not([multiple]){height:43px}select[multiple]{min-height:120px}textarea{min-height:78px;resize:vertical}.helper{font-size:10.5px;color:#8b96a6;margin-top:5px;line-height:1.4}.flash{padding:12px 14px;border-radius:12px;margin-bottom:14px;background:#ecfdf3;color:#166534;border:1px solid #d2f5de;font-size:13px}.flash.erro{background:#fff1f0;color:#b42318;border-color:#ffd5d1}.pill{display:inline-flex;padding:5px 8px;border-radius:999px;font-size:10px;font-weight:850}.pill.ATIVO,.pill.CONCLUIDO{background:#dcfce7;color:#166534}.pill.BLOQUEADO,.pill.ERRO{background:#fee2e2;color:#991b1b}.pill.AGUARDANDO{background:#fff4d5;color:#8a5a00}.pill.PROCESSANDO{background:#e7f0ff;color:#1d4ed8}.muted{color:var(--muted)}table{width:100%;border-collapse:collapse;min-width:720px}th,td{text-align:left;padding:11px 12px;border-bottom:1px solid #edf0f4;font-size:12.5px}th{font-size:10.5px;color:#667085;text-transform:uppercase;background:#fafbfc}.table-wrap{overflow:auto}.actions{display:flex;gap:7px;flex-wrap:wrap;align-items:center}.actions input{height:36px;width:125px}.actions button{min-height:36px}.switchrow{display:flex;align-items:center;gap:9px;padding:11px 12px;border:1px solid var(--line);border-radius:12px;background:#fbfcfd}.switchrow input{width:auto;height:auto}.notice{padding:12px 14px;border-radius:12px;background:#f0fdf9;border:1px solid #d1fae5;color:#0f5f58;font-size:12px}.progress{height:7px;border-radius:999px;background:#edf1f5;overflow:hidden;min-width:90px}.progress>span{display:block;height:100%;background:linear-gradient(90deg,var(--primary),var(--primary2))}.loginbody{min-height:100vh;display:grid;place-items:center;background:radial-gradient(circle at 10% 0,rgba(20,184,166,.2),transparent 32%),linear-gradient(145deg,#08111f,#101b2d)}.login-card{width:min(430px,calc(100% - 28px));background:#fff;border-radius:24px;padding:32px;box-shadow:0 25px 80px rgba(0,0,0,.24)}.login-card input{margin-bottom:13px}.login-card .btn{width:100%}.login-card h1{font-size:27px;margin:0 0 7px}.login-card p{color:var(--muted);font-size:13px;margin:0 0 24px}
@media(max-width:900px){.w3,.w4,.w6,.w12,.field,.field.w6,.field.w3{grid-column:1/-1}.wrap{padding:13px}.top{align-items:flex-start;flex-direction:column}.card{padding:15px}}
</style>
"""

LOGIN_HTML = """<!doctype html><html lang='pt-BR'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Consulta de Contatos</title>""" + BASE_STYLE + """</head><body class='loginbody'><div class='login-card'><div class='logo' style='margin-bottom:20px'>📊</div><h1>Consulta de Contatos</h1><p>Entre com seu usuário e senha.</p>{% if erro %}<div class='flash erro'>{{erro}}</div>{% endif %}<form method='post'><label>Usuário</label><input name='usuario' autocomplete='username' autofocus required><label>Senha</label><input type='password' name='senha' autocomplete='current-password' required><button class='btn' type='submit'>Entrar</button></form></div></body></html>"""

PAINEL_HTML = """<!doctype html><html lang='pt-BR'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Consulta de Contatos</title>""" + BASE_STYLE + r"""</head><body><div class='wrap'>
<div class='top'><div class='brand'><div class='logo'>📊</div><div><h1>Consulta de Contatos</h1><p>Olá, {{usuario.usuario}}.</p></div></div><div class='nav'>{% if usuario.perfil=='ADMIN' %}<a class='btn2' href='{{url_for("admin")}}'>⚙️ Administração</a>{% endif %}<a class='btn2' href='{{url_for("logout")}}'>Sair</a></div></div>
{% with msgs=get_flashed_messages(with_categories=true) %}{% for cat,msg in msgs %}<div class='flash {% if cat=="erro" %}erro{% endif %}'>{{msg}}</div>{% endfor %}{% endwith %}
<div class='grid'>
<div class='card w3 metric'><strong>{{"{:,}".format(usuario.saldo).replace(",", ".")}}</strong><span>Saldo total</span></div>
<div class='card w3 metric'><strong>{{"{:,}".format(reservado).replace(",", ".")}}</strong><span>Reservado em pedidos</span></div>
<div class='card w3 metric'><strong>{{"{:,}".format(disponivel).replace(",", ".")}}</strong><span>Disponível para novos pedidos</span></div>
<div class='card w3 metric'><strong>{{recentes|length}}</strong><span>Pedidos recentes</span></div>

<div class='card w12'>
<div class='section-title'>🔎 Nova exportação</div>
{% if not menu_pronto %}<div class='flash erro'>O agente do seu PC ainda não sincronizou os menus. Inicie o agente local primeiro.</div>{% endif %}
<form method='post' action='{{url_for("criar_pedido")}}'>
<input type='hidden' name='csrf_token' value='{{csrf_token()}}'>
<div class='fields'>
<div class='field w3'><label>Estados (UF)</label><select name='ufs' multiple>{% for x in ufs %}<option value='{{x}}'>{{x}}</option>{% endfor %}</select><div class='helper'>Sem seleção = Brasil inteiro.</div></div>
<div class='field w6'><label>Cidades</label><select name='cidades' multiple>{% for x in cidades %}<option value='{{x.cidade}}'>{{x.cidade}} — {{x.uf}}</option>{% endfor %}</select></div>
<div class='field w3'><label>Sexo</label><select name='sexos' multiple>{% for x in sexos %}<option value='{{x}}'>{% if x=='F' %}F — Feminino{% elif x=='M' %}M — Masculino{% else %}I — Indefinido{% endif %}</option>{% endfor %}</select></div>

<div class='field w6'><label>CBO</label><select id='cbos' name='cbos' multiple>{% for x in cbos %}<option value='{{x}}'>{{x}}</option>{% endfor %}</select></div>
<div class='field w6'><label>Faixa de renda</label><select id='faixas' name='faixas_renda' multiple>{% for x in faixas %}<option value='{{x}}'>{{x}} — {{faixas_desc.get(x,'')}}</option>{% endfor %}</select></div>

<div class='field w3'><label>CEP(s)</label><textarea id='ceps' name='ceps' placeholder='45000000, 45020000'></textarea><div class='helper'>Usado no modo Atualizados 2026.</div></div>
<div class='field w3'><label>Bairro(s)</label><textarea name='bairros' placeholder='Centro, Candeias'></textarea></div>
<div class='field w3'><label>DDD(s)</label><textarea name='ddds' placeholder='77, 73, 75'></textarea><div class='helper'>Obtido pelos 2 primeiros dígitos do telefone nacional.</div></div>
<div class='field w3'><label>Quantidade</label><input type='number' name='quantidade' value='5000' min='1' max='1000000' required></div>

<div class='field w6'><div class='switchrow'><input id='idade_check' type='checkbox' name='filtrar_idade' value='1'><label for='idade_check' style='margin:0'>Filtrar por idade</label><input id='idade_min' type='number' name='idade_min' value='{{idade_min}}' min='0' max='90' style='width:95px' disabled><span>até</span><input id='idade_max' type='number' name='idade_max' value='{{idade_max}}' min='0' max='90' style='width:95px' disabled></div></div>
<div class='field w6'><div class='switchrow'><input id='atualizados' type='checkbox' name='atualizados_2026' value='1'><label for='atualizados' style='margin:0'>⚡ Atualizados 2026</label><span class='muted' style='font-size:11px'>Somente a base 2026.</span></div></div>
</div>
<div class='notice' style='margin-top:14px'>A quantidade solicitada fica reservada enquanto o pedido estiver aguardando/processando. O saldo só é descontado quando a exportação termina com sucesso, usando a quantidade realmente entregue.</div>
<div style='display:flex;justify-content:flex-end;margin-top:15px'><button class='btn' type='submit' {% if not menu_pronto %}disabled{% endif %}>📤 Criar pedido de exportação</button></div>
</form></div>

<div class='card w12'><div class='section-title'>📋 Últimos pedidos</div><div class='table-wrap'>{% if recentes %}<table><thead><tr><th>Pedido</th><th>Quantidade</th><th>Status</th><th>Progresso</th><th>Mensagem</th><th>Criado</th></tr></thead><tbody>{% for p in recentes %}<tr><td><a href='{{url_for("ver_pedido",pedido_id=p.id)}}'><b>#{{p.id}}</b></a></td><td>{{"{:,}".format(p.quantidade).replace(",", ".")}}</td><td><span class='pill {{p.status}}'>{{p.status}}</span></td><td><div class='progress'><span style='width:{{p.progresso}}%'></span></div><small>{{p.progresso}}%</small></td><td>{{p.mensagem or ''}}</td><td>{{p.criado_em}}</td></tr>{% endfor %}</tbody></table>{% else %}<p class='muted'>Nenhum pedido criado ainda.</p>{% endif %}</div></div>
</div></div>
<script>
const atualizados=document.getElementById('atualizados');const cbos=document.getElementById('cbos');const faixas=document.getElementById('faixas');const idadeCheck=document.getElementById('idade_check');const idadeMin=document.getElementById('idade_min');const idadeMax=document.getElementById('idade_max');
function sync(){const a=atualizados.checked;cbos.disabled=a;faixas.disabled=a;idadeCheck.disabled=a;if(a){idadeCheck.checked=false;}idadeMin.disabled=a||!idadeCheck.checked;idadeMax.disabled=a||!idadeCheck.checked;}
atualizados.addEventListener('change',sync);idadeCheck.addEventListener('change',sync);sync();
</script></body></html>"""

PEDIDO_HTML = """<!doctype html><html lang='pt-BR'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><meta http-equiv='refresh' content='5'><title>Pedido</title>""" + BASE_STYLE + r"""</head><body><div class='wrap'><div class='top'><div class='brand'><div class='logo'>📦</div><div><h1>Pedido #{{p.id}}</h1><p>Atualização automática a cada 5 segundos.</p></div></div><div class='nav'><a class='btn2' href='{{url_for("painel")}}'>← Voltar</a></div></div>
<div class='grid'><div class='card w3 metric'><strong>{{p.progresso}}%</strong><span>Progresso</span></div><div class='card w3 metric'><strong>{{p.status}}</strong><span>Status</span></div><div class='card w3 metric'><strong>{{p.quantidade}}</strong><span>Solicitados</span></div><div class='card w3 metric'><strong>{{entregues}}</strong><span>Entregues</span></div><div class='card w12'><h3>{{p.mensagem or 'Aguardando...'}}</h3><div class='progress' style='height:12px'><span style='width:{{p.progresso}}%'></span></div>{% if p.erro %}<div class='flash erro' style='margin-top:15px'>{{p.erro}}</div>{% endif %}{% if resultado %}<div class='notice' style='margin-top:15px'>Exportação concluída.{% if p.arquivo_chave %}<div style='margin-top:14px'><a class='btn' href='{{url_for("baixar_pedido", pedido_id=p.id)}}'>📥 Baixar Excel</a></div>{% else %}<div class='muted' style='margin-top:10px'>Arquivo ainda não disponível para download.</div>{% endif %}</div><pre style='white-space:pre-wrap;background:#f8fafc;padding:12px;border-radius:12px;border:1px solid #edf0f4'>{{resultado_pretty}}</pre>{% endif %}</div></div></div></body></html>"""

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
        cidades=cidades_menu(),
        sexos=opcoes("sexo"),
        cbos=opcoes("cbo"),
        faixas=opcoes("faixa_renda"),
        faixas_desc=FAIXAS_RENDA_DESCRICAO,
        idade_min=int(config_menu("idade_min", "0") or 0),
        idade_max=min(90, int(config_menu("idade_max", "90") or 90)),
    )


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
        "ceps": split_texto(request.form.get("ceps")) if atualizados else [],
        "bairros": split_texto(request.form.get("bairros")),
        "ddds": split_texto(request.form.get("ddds")),
        "atualizados_2026": atualizados,
    }

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

    # Nunca confia em caminhos enviados pelo agente.
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
