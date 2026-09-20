import os
from functools import wraps

import psycopg
from flask import Flask, flash, redirect, render_template_string, request, session, url_for
from psycopg.rows import dict_row
from werkzeug.security import check_password_hash, generate_password_hash


DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
SECRET_KEY = os.getenv("SECRET_KEY", "").strip()
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin").strip()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "").strip()

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL não configurada no Railway.")

if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY não configurada no Railway.")

if not ADMIN_PASSWORD:
    raise RuntimeError("ADMIN_PASSWORD não configurada no Railway.")


app = Flask(__name__)
app.secret_key = SECRET_KEY


def conectar():
    return psycopg.connect(
        DATABASE_URL,
        row_factory=dict_row,
        connect_timeout=15,
    )


def init_db():
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
                    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS pedidos (
                    id BIGSERIAL PRIMARY KEY,
                    usuario_id BIGINT NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
                    quantidade INTEGER NOT NULL,
                    status VARCHAR(30) NOT NULL DEFAULT 'AGUARDANDO',
                    filtros_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                    resultado_json JSONB,
                    arquivo_chave TEXT,
                    saldo_descontado BOOLEAN NOT NULL DEFAULT FALSE,
                    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    iniciado_em TIMESTAMPTZ,
                    concluido_em TIMESTAMPTZ
                )
            """)

            cur.execute("""
                INSERT INTO usuarios (usuario, senha_hash, perfil, saldo, ativo)
                VALUES (%s, %s, 'ADMIN', 0, TRUE)
                ON CONFLICT (usuario)
                DO UPDATE SET
                    senha_hash = EXCLUDED.senha_hash,
                    perfil = 'ADMIN',
                    ativo = TRUE
            """, (
                ADMIN_USERNAME,
                generate_password_hash(ADMIN_PASSWORD),
            ))

        conn.commit()


def usuario_atual():
    uid = session.get("usuario_id")

    if not uid:
        return None

    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM usuarios WHERE id=%s",
                (uid,),
            )
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
        usuario = usuario_atual()

        if usuario["perfil"] != "ADMIN":
            return redirect(url_for("painel"))

        return func(*args, **kwargs)

    return wrapper


BASE_STYLE = """
<style>
:root{
    --bg:#f4f7fb;--card:#fff;--text:#172033;--muted:#6b7280;
    --line:#e5e7eb;--primary:#0f766e;--primary2:#14b8a6;
    --danger:#b42318;--green:#166534
}
*{box-sizing:border-box}
body{margin:0;font-family:Inter,system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif;background:var(--bg);color:var(--text)}
a{text-decoration:none;color:inherit}
.wrap{max-width:1180px;margin:auto;padding:24px}
.top{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:22px}
.brand{font-weight:900;font-size:23px}
.brand small{display:block;color:var(--muted);font-size:12px;font-weight:600;margin-top:4px}
.nav{display:flex;gap:8px;flex-wrap:wrap}
.btn,.btn2,.danger{display:inline-flex;align-items:center;justify-content:center;min-height:42px;padding:0 14px;border-radius:11px;font-weight:800;cursor:pointer}
.btn{border:0;background:linear-gradient(135deg,var(--primary),var(--primary2));color:#fff}
.btn2{background:#fff;border:1px solid var(--line);color:#344054}
.danger{background:#fff1f0;border:1px solid #ffd5d1;color:var(--danger)}
.grid{display:grid;grid-template-columns:repeat(12,minmax(0,1fr));gap:14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:20px;box-shadow:0 10px 28px rgba(15,23,42,.05)}
.w4{grid-column:span 4}.w12{grid-column:1/-1}
.metric strong{display:block;font-size:30px;color:var(--primary)}
.metric span{display:block;color:var(--muted);font-size:12px;margin-top:5px}
label{display:block;font-size:12px;font-weight:800;margin-bottom:7px}
input{width:100%;height:44px;border:1px solid #d8e0e9;border-radius:11px;padding:0 12px;font:inherit;background:#fff}
table{width:100%;border-collapse:collapse}
th,td{text-align:left;padding:12px;border-bottom:1px solid #edf0f4;font-size:13px}
th{font-size:11px;color:#667085;text-transform:uppercase;background:#fafbfc}
.flash{padding:12px 14px;border-radius:12px;margin-bottom:14px;background:#ecfdf3;color:#166534;border:1px solid #d2f5de}
.flash.erro{background:#fff1f0;color:#b42318;border-color:#ffd5d1}
.pill{display:inline-flex;padding:5px 8px;border-radius:999px;font-size:10px;font-weight:850}
.pill.on{background:#dcfce7;color:#166534}.pill.off{background:#fee2e2;color:#991b1b}
.muted{color:var(--muted)}
.actions{display:flex;gap:7px;flex-wrap:wrap;align-items:center}
.actions input{height:36px;width:130px}
.actions button{min-height:36px}
@media(max-width:800px){
    .wrap{padding:14px}.top{align-items:flex-start;flex-direction:column}
    .w4,.w12{grid-column:1/-1}.card{padding:15px;overflow:auto}
}
</style>
"""


LOGIN_HTML = """
<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Consulta de Contatos • Login</title>
""" + BASE_STYLE + """
<style>
body{
    min-height:100vh;display:grid;place-items:center;
    background:radial-gradient(circle at 10% 0,rgba(20,184,166,.20),transparent 32%),
               linear-gradient(145deg,#08111f,#101b2d)
}
.login-card{width:min(430px,calc(100% - 28px));background:#fff;border-radius:24px;padding:32px;box-shadow:0 25px 80px rgba(0,0,0,.24)}
.logo{width:54px;height:54px;border-radius:16px;display:grid;place-items:center;background:linear-gradient(135deg,#0f766e,#2dd4bf);color:#fff;font-size:25px;margin-bottom:22px}
.login-card h1{font-size:27px;margin-bottom:8px}
.login-card p{color:var(--muted);font-size:13px;margin-bottom:24px}
.login-card input{margin-bottom:13px}
.login-card .btn{width:100%;margin-top:4px}
</style>
</head>
<body>
<div class="login-card">
    <div class="logo">📊</div>
    <h1>Consulta de Contatos</h1>
    <p>Entre com seu usuário e senha.</p>
    {% if erro %}<div class="flash erro">{{ erro }}</div>{% endif %}
    <form method="post">
        <label>Usuário</label>
        <input name="usuario" autocomplete="username" autofocus required>
        <label>Senha</label>
        <input type="password" name="senha" autocomplete="current-password" required>
        <button class="btn" type="submit">Entrar</button>
    </form>
</div>
</body>
</html>
"""


PAINEL_HTML = """
<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Consulta de Contatos</title>
""" + BASE_STYLE + """
</head>
<body>
<div class="wrap">
    <div class="top">
        <div class="brand">📊 Consulta de Contatos<small>Área do cliente</small></div>
        <div class="nav">
            {% if usuario.perfil == 'ADMIN' %}
                <a class="btn2" href="{{ url_for('admin') }}">⚙️ Administração</a>
            {% endif %}
            <a class="btn2" href="{{ url_for('logout') }}">Sair</a>
        </div>
    </div>

    {% with mensagens = get_flashed_messages(with_categories=true) %}
        {% for categoria, mensagem in mensagens %}
            <div class="flash {% if categoria == 'erro' %}erro{% endif %}">{{ mensagem }}</div>
        {% endfor %}
    {% endwith %}

    <div class="grid">
        <div class="card w4 metric">
            <strong>{{ "{:,}".format(usuario.saldo).replace(",", ".") }}</strong>
            <span>Saldo disponível em contatos</span>
        </div>
        <div class="card w4 metric">
            <strong>{{ pedidos|length }}</strong>
            <span>Pedidos recentes</span>
        </div>
        <div class="card w4 metric">
            <strong>{% if usuario.ativo %}Ativa{% else %}Bloqueada{% endif %}</strong>
            <span>Status da conta</span>
        </div>

        <div class="card w12">
            <h2>Novo pedido</h2>
            <p class="muted">A próxima etapa vai conectar aqui os filtros do sistema que já funciona no seu PC.</p>
        </div>

        <div class="card w12">
            <h2>Últimos pedidos</h2>
            {% if pedidos %}
            <table>
                <thead><tr><th>ID</th><th>Quantidade</th><th>Status</th><th>Criado em</th></tr></thead>
                <tbody>
                {% for p in pedidos %}
                    <tr>
                        <td>#{{ p.id }}</td>
                        <td>{{ "{:,}".format(p.quantidade).replace(",", ".") }}</td>
                        <td>{{ p.status }}</td>
                        <td>{{ p.criado_em }}</td>
                    </tr>
                {% endfor %}
                </tbody>
            </table>
            {% else %}
                <p class="muted">Nenhum pedido criado ainda.</p>
            {% endif %}
        </div>
    </div>
</div>
</body>
</html>
"""


ADMIN_HTML = """
<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Administração • Consulta de Contatos</title>
""" + BASE_STYLE + """
</head>
<body>
<div class="wrap">
    <div class="top">
        <div class="brand">⚙️ Administração<small>Usuários, saldos e acessos</small></div>
        <div class="nav">
            <a class="btn2" href="{{ url_for('painel') }}">← Painel</a>
            <a class="btn2" href="{{ url_for('logout') }}">Sair</a>
        </div>
    </div>

    {% with mensagens = get_flashed_messages(with_categories=true) %}
        {% for categoria, mensagem in mensagens %}
            <div class="flash {% if categoria == 'erro' %}erro{% endif %}">{{ mensagem }}</div>
        {% endfor %}
    {% endwith %}

    <div class="grid">
        <div class="card w4">
            <h2>Criar usuário</h2>
            <form method="post" action="{{ url_for('admin_criar_usuario') }}">
                <label>Usuário</label>
                <input name="usuario" required>

                <label style="margin-top:12px">Senha</label>
                <input type="password" name="senha" required>

                <label style="margin-top:12px">Saldo inicial</label>
                <input type="number" name="saldo" value="0" min="0" step="1" required>

                <button class="btn" type="submit" style="width:100%;margin-top:14px">Criar usuário</button>
            </form>
        </div>

        <div class="card w4 metric">
            <strong>{{ total_clientes }}</strong>
            <span>Clientes cadastrados</span>
        </div>

        <div class="card w4 metric">
            <strong>{{ "{:,}".format(total_saldo).replace(",", ".") }}</strong>
            <span>Saldo total disponível</span>
        </div>

        <div class="card w12">
            <h2>Usuários</h2>
            <table>
                <thead><tr><th>Usuário</th><th>Saldo</th><th>Status</th><th>Criado</th><th>Ações</th></tr></thead>
                <tbody>
                {% for u in usuarios %}
                    <tr>
                        <td><strong>{{ u.usuario }}</strong>{% if u.perfil == 'ADMIN' %}<span class="muted"> · ADMIN</span>{% endif %}</td>
                        <td>{{ "{:,}".format(u.saldo).replace(",", ".") }}</td>
                        <td>
                            {% if u.ativo %}
                                <span class="pill on">ATIVO</span>
                            {% else %}
                                <span class="pill off">BLOQUEADO</span>
                            {% endif %}
                        </td>
                        <td>{{ u.criado_em }}</td>
                        <td>
                            {% if u.perfil != 'ADMIN' %}
                            <div class="actions">
                                <form method="post" action="{{ url_for('admin_saldo', usuario_id=u.id) }}">
                                    <input type="number" name="valor" placeholder="+/- saldo" required>
                                    <button class="btn2" type="submit">Saldo</button>
                                </form>

                                <form method="post" action="{{ url_for('admin_toggle', usuario_id=u.id) }}">
                                    <button class="{% if u.ativo %}danger{% else %}btn2{% endif %}" type="submit">
                                        {% if u.ativo %}Bloquear{% else %}Ativar{% endif %}
                                    </button>
                                </form>

                                <form method="post" action="{{ url_for('admin_senha', usuario_id=u.id) }}">
                                    <input type="password" name="senha" placeholder="Nova senha" required>
                                    <button class="btn2" type="submit">Alterar senha</button>
                                </form>
                            </div>
                            {% else %}
                                <span class="muted">Conta administrativa</span>
                            {% endif %}
                        </td>
                    </tr>
                {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
</div>
</body>
</html>
"""


@app.route("/health")
def health():
    return {"ok": True}


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("usuario_id"):
        return redirect(url_for("painel"))

    erro = None

    if request.method == "POST":
        usuario_digitado = request.form.get("usuario", "").strip()
        senha = request.form.get("senha", "")

        with conectar() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM usuarios WHERE usuario=%s",
                    (usuario_digitado,),
                )
                usuario = cur.fetchone()

        if not usuario or not check_password_hash(usuario["senha_hash"], senha):
            erro = "Usuário ou senha incorretos."
        elif not usuario["ativo"]:
            erro = "Esta conta está bloqueada."
        else:
            session.clear()
            session["usuario_id"] = usuario["id"]
            return redirect(url_for("painel"))

    return render_template_string(LOGIN_HTML, erro=erro)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def painel():
    usuario = usuario_atual()

    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, quantidade, status, criado_em
                FROM pedidos
                WHERE usuario_id=%s
                ORDER BY id DESC
                LIMIT 12
                """,
                (usuario["id"],),
            )
            pedidos = cur.fetchall()

    return render_template_string(
        PAINEL_HTML,
        usuario=usuario,
        pedidos=pedidos,
    )


@app.route("/admin")
@admin_required
def admin():
    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, usuario, perfil, saldo, ativo, criado_em
                FROM usuarios
                ORDER BY CASE WHEN perfil='ADMIN' THEN 0 ELSE 1 END, usuario
            """)
            usuarios = cur.fetchall()

            cur.execute("""
                SELECT
                    COUNT(*) FILTER (WHERE perfil='CLIENTE') AS total_clientes,
                    COALESCE(SUM(saldo) FILTER (WHERE perfil='CLIENTE'), 0) AS total_saldo
                FROM usuarios
            """)
            resumo = cur.fetchone()

    return render_template_string(
        ADMIN_HTML,
        usuarios=usuarios,
        total_clientes=resumo["total_clientes"] or 0,
        total_saldo=resumo["total_saldo"] or 0,
    )


@app.route("/admin/usuarios/criar", methods=["POST"])
@admin_required
def admin_criar_usuario():
    nome = request.form.get("usuario", "").strip()
    senha = request.form.get("senha", "")

    try:
        saldo = int(request.form.get("saldo", "0") or 0)
    except ValueError:
        saldo = -1

    if not nome or not senha:
        flash("Informe usuário e senha.", "erro")
        return redirect(url_for("admin"))

    if len(senha) < 4:
        flash("A senha precisa ter pelo menos 4 caracteres.", "erro")
        return redirect(url_for("admin"))

    if saldo < 0:
        flash("O saldo inicial não pode ser negativo.", "erro")
        return redirect(url_for("admin"))

    try:
        with conectar() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO usuarios (usuario, senha_hash, perfil, saldo, ativo)
                    VALUES (%s, %s, 'CLIENTE', %s, TRUE)
                    RETURNING id
                    """,
                    (nome, generate_password_hash(senha), saldo),
                )
                novo_id = cur.fetchone()["id"]

                if saldo:
                    cur.execute(
                        """
                        INSERT INTO movimentacoes (usuario_id, valor, tipo, descricao)
                        VALUES (%s, %s, 'CREDITO_INICIAL', 'Saldo inicial')
                        """,
                        (novo_id, saldo),
                    )

            conn.commit()

        flash("Usuário criado com sucesso.")

    except psycopg.errors.UniqueViolation:
        flash("Já existe um usuário com esse nome.", "erro")

    return redirect(url_for("admin"))


@app.route("/admin/usuarios/<int:usuario_id>/saldo", methods=["POST"])
@admin_required
def admin_saldo(usuario_id):
    try:
        valor = int(request.form.get("valor", "0") or 0)
    except ValueError:
        valor = 0

    if valor == 0:
        flash("Informe um valor diferente de zero.", "erro")
        return redirect(url_for("admin"))

    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE usuarios
                SET saldo = saldo + %s
                WHERE id=%s
                  AND perfil='CLIENTE'
                  AND saldo + %s >= 0
                RETURNING saldo
                """,
                (valor, usuario_id, valor),
            )
            atualizado = cur.fetchone()

            if not atualizado:
                conn.rollback()
                flash("Operação inválida ou saldo insuficiente.", "erro")
                return redirect(url_for("admin"))

            cur.execute(
                """
                INSERT INTO movimentacoes (usuario_id, valor, tipo, descricao)
                VALUES (%s, %s, %s, %s)
                """,
                (
                    usuario_id,
                    valor,
                    "CREDITO_ADMIN" if valor > 0 else "DEBITO_ADMIN",
                    "Ajuste manual pelo administrador",
                ),
            )

        conn.commit()

    flash("Saldo atualizado.")
    return redirect(url_for("admin"))


@app.route("/admin/usuarios/<int:usuario_id>/toggle", methods=["POST"])
@admin_required
def admin_toggle(usuario_id):
    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE usuarios
                SET ativo = NOT ativo
                WHERE id=%s AND perfil='CLIENTE'
                """,
                (usuario_id,),
            )
        conn.commit()

    flash("Status do usuário atualizado.")
    return redirect(url_for("admin"))


@app.route("/admin/usuarios/<int:usuario_id>/senha", methods=["POST"])
@admin_required
def admin_senha(usuario_id):
    senha = request.form.get("senha", "")

    if len(senha) < 4:
        flash("A nova senha precisa ter pelo menos 4 caracteres.", "erro")
        return redirect(url_for("admin"))

    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE usuarios
                SET senha_hash=%s
                WHERE id=%s AND perfil='CLIENTE'
                """,
                (generate_password_hash(senha), usuario_id),
            )
        conn.commit()

    flash("Senha alterada.")
    return redirect(url_for("admin"))


init_db()


if __name__ == "__main__":
    porta = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=porta, debug=False)
