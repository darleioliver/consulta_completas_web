import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="Consulta da Base",
    page_icon="📊",
    layout="wide"
)

st.title("📊 Consulta da Base de Contatos")
st.caption("Consulta por UF, CBO, cidade(s) e faixa de renda.")

PASTA_SCRIPT = Path(__file__).resolve().parent
bancos = sorted(list(PASTA_SCRIPT.glob("*.sqlite")) + list(PASTA_SCRIPT.glob("*.db")))

if not bancos:
    st.error("Nenhum arquivo .sqlite ou .db foi encontrado na mesma pasta do sistema.")
    st.info("Coloque o base_contagens.sqlite na mesma pasta deste arquivo e atualize a página.")
    st.stop()

if len(bancos) == 1:
    BANCO = bancos[0]
else:
    BANCO = Path(st.selectbox("Banco de dados", bancos, format_func=lambda p: p.name))

st.success(f"✅ Base carregada: {BANCO.name}")


def conectar():
    uri = BANCO.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=30)
    conn.execute("PRAGMA query_only = ON;")
    conn.execute("PRAGMA busy_timeout = 30000;")
    try:
        yield conn
    finally:
        conn.close()


def consulta_valor(sql, params=()):
    for conn in conectar():
        r = conn.execute(sql, params).fetchone()
        return 0 if not r or r[0] is None else int(r[0])


def consulta_df(sql, params=()):
    for conn in conectar():
        return pd.read_sql_query(sql, conn, params=params)


for conn in conectar():
    tabelas = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }

necessarias = {
    "contagem_uf",
    "contagem_cbo",
    "contagem_cidade",
    "contagem_faixa",
    "contagem_uf_cbo",
    "contagem_uf_cidade",
    "contagem_uf_faixa",
    "contagem_uf_cbo_cidade",
    "contagem_uf_cbo_faixa",
    "contagem_uf_cidade_faixa",
    "contagem_uf_completa",
    "contagem_cbo_cidade",
    "contagem_cbo_faixa",
    "contagem_cidade_faixa",
    "contagem_completa",
    "resumo_arquivos",
}

faltando = necessarias - tabelas
if faltando:
    st.error("Esse banco ainda é da versão antiga ou está incompleto para o filtro por UF.")
    st.write("Tabelas faltando:")
    st.code("\n".join(sorted(faltando)))
    st.info("Gere novamente o base_contagens.sqlite usando gerar_relatorio_com_uf.py.")
    st.stop()


@st.cache_data(show_spinner=False)
def carregar_lista(caminho_banco, tabela, coluna, numerico=False):
    uri = Path(caminho_banco).resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=30)
    try:
        if numerico:
            sql = f"""
                SELECT {coluna}
                FROM {tabela}
                WHERE {coluna} IS NOT NULL
                  AND TRIM({coluna}) <> ''
                ORDER BY
                    CASE
                        WHEN {coluna} GLOB '[0-9]*'
                        THEN CAST({coluna} AS INTEGER)
                        ELSE 999999999
                    END,
                    {coluna}
            """
        else:
            sql = f"""
                SELECT {coluna}
                FROM {tabela}
                WHERE {coluna} IS NOT NULL
                  AND TRIM({coluna}) <> ''
                ORDER BY {coluna}
            """
        df = pd.read_sql_query(sql, conn)
        return df[coluna].astype(str).tolist()
    finally:
        conn.close()


@st.cache_data(show_spinner=False)
def carregar_cidades_por_uf(caminho_banco, uf):
    uri = Path(caminho_banco).resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=30)
    try:
        if uf == "TODOS":
            sql = "SELECT cidade FROM contagem_cidade WHERE cidade IS NOT NULL AND TRIM(cidade) <> '' ORDER BY cidade"
            params = ()
        else:
            sql = """
                SELECT cidade
                FROM contagem_uf_cidade
                WHERE uf = ?
                  AND cidade IS NOT NULL
                  AND TRIM(cidade) <> ''
                ORDER BY cidade
            """
            params = (uf,)
            
        df = pd.read_sql_query(sql, conn, params=params)
        return df["cidade"].astype(str).tolist()
    finally:
        conn.close()


try:
    ufs = carregar_lista(str(BANCO), "contagem_uf", "uf")
    cbos = carregar_lista(str(BANCO), "contagem_cbo", "cbo")
    faixas = carregar_lista(str(BANCO), "contagem_faixa", "faixa_renda_id", numerico=True)
except Exception as erro:
    st.error("Não foi possível carregar os filtros.")
    st.exception(erro)
    st.stop()


# Inicialização segura do session_state (cidades agora é uma lista)
if "filtro_uf" not in st.session_state:
    st.session_state.filtro_uf = "TODOS"
if "filtro_cbo" not in st.session_state:
    st.session_state.filtro_cbo = "TODOS"
if "filtro_cidades" not in st.session_state:
    st.session_state.filtro_cidades = []
if "filtro_faixa" not in st.session_state:
    st.session_state.filtro_faixa = "TODAS"


def limpar_filtros():
    st.session_state.filtro_uf = "TODOS"
    st.session_state.filtro_cbo = "TODOS"
    st.session_state.filtro_cidades = []
    st.session_state.filtro_faixa = "TODAS"


st.subheader("🔎 Filtros")
col1, col2, col3, col4, col5 = st.columns([0.8, 1.1, 2.2, 1.2, 0.8])

with col1:
    uf = st.selectbox("UF", ["TODOS"] + ufs, key="filtro_uf")

cidades_disponiveis = carregar_cidades_por_uf(str(BANCO), uf)

# Remove da seleção cidades que não pertencem mais à UF escolhida
st.session_state.filtro_cidades = [
    c for c in st.session_state.filtro_cidades if c in cidades_disponiveis
]

with col2:
    cbo = st.selectbox("CBO", ["TODOS"] + cbos, key="filtro_cbo")

with col3:
    # Mudança de selectbox para multiselect
    cidades_selecionadas = st.multiselect(
        "Cidades", 
        cidades_disponiveis, 
        key="filtro_cidades",
        placeholder="Selecione uma ou mais cidades..."
    )

with col4:
    faixa = st.selectbox("Faixa de renda", ["TODAS"] + faixas, key="filtro_faixa")

with col5:
    st.write("")
    st.write("")
    st.button("🧹 Limpar", on_click=limpar_filtros, use_container_width=True)


def consultar_quantidade(uf, cbo, cidades_selecionadas, faixa):
    ativos = {}

    if uf != "TODOS":
        ativos["uf"] = uf
    if cbo != "TODOS":
        ativos["cbo"] = cbo
    if cidades_selecionadas: # Lista não vazia
        ativos["cidade"] = cidades_selecionadas
    if faixa != "TODAS":
        ativos["faixa_renda_id"] = faixa

    if not ativos:
        return consulta_valor(
            """
            SELECT COALESCE(SUM(linhas_processadas), 0)
            FROM resumo_arquivos
            WHERE status = 'OK'
            """
        )

    chave = tuple(
        campo
        for campo in ("uf", "cbo", "cidade", "faixa_renda_id")
        if campo in ativos
    )

    mapa_tabelas = {
        ("uf",): "contagem_uf",
        ("cbo",): "contagem_cbo",
        ("cidade",): "contagem_cidade",
        ("faixa_renda_id",): "contagem_faixa",
        ("cbo", "cidade"): "contagem_cbo_cidade",
        ("cbo", "faixa_renda_id"): "contagem_cbo_faixa",
        ("cidade", "faixa_renda_id"): "contagem_cidade_faixa",
        ("cbo", "cidade", "faixa_renda_id"): "contagem_completa",
        ("uf", "cbo"): "contagem_uf_cbo",
        ("uf", "cidade"): "contagem_uf_cidade",
        ("uf", "faixa_renda_id"): "contagem_uf_faixa",
        ("uf", "cbo", "cidade"): "contagem_uf_cbo_cidade",
        ("uf", "cbo", "faixa_renda_id"): "contagem_uf_cbo_faixa",
        ("uf", "cidade", "faixa_renda_id"): "contagem_uf_cidade_faixa",
        ("uf", "cbo", "cidade", "faixa_renda_id"): "contagem_uf_completa",
    }

    tabela = mapa_tabelas.get(chave)
    if tabela is None:
        return 0

    clausulas = []
    params = []

    for campo in chave:
        if campo == "cidade":
            # Caso especial para múltiplas cidades usando IN (?, ?, ?)
            placeholders = ", ".join(["?"] * len(cidades_selecionadas))
            clausulas.append(f"cidade IN ({placeholders})")
            params.extend(cidades_selecionadas)
        else:
            clausulas.append(f"{campo} = ?")
            params.append(ativos[campo])

    sql = f"""
        SELECT SUM(quantidade)
        FROM {tabela}
        WHERE {' AND '.join(clausulas)}
    """

    return consulta_valor(sql, tuple(params))


try:
    quantidade = consultar_quantidade(uf, cbo, cidades_selecionadas, faixa)
except Exception as erro:
    st.error("A consulta falhou, mas o sistema permaneceu aberto.")
    st.exception(erro)
    st.stop()


st.divider()
r1, r2 = st.columns([1, 3])

with r1:
    st.metric(
        "Contatos encontrados",
        f"{quantidade:,}".replace(",", ".")
    )

with r2:
    st.write("**Filtros aplicados:**")
    str_cidades = ", ".join(cidades_selecionadas) if cidades_selecionadas else "TODAS"
    st.write(
        f"UF: **{uf}**  |  "
        f"CBO: **{cbo}**  |  "
        f"Cidade(s): **{str_cidades}**  |  "
        f"Faixa: **{faixa}**"
    )


st.divider()
col_a, col_b, col_c = st.columns(3)

def formatar_df_ranking(df):
    if not df.empty and "Contatos" in df.columns:
        df["Contatos"] = df["Contatos"].apply(lambda x: f"{x:,}".replace(",", "."))
    return df

try:
    with col_a:
        st.subheader("🗺️ Estados")
        top_uf = consulta_df(
            """
            SELECT uf AS UF, quantidade AS Contatos
            FROM contagem_uf
            ORDER BY quantidade DESC
            LIMIT 27
            """
        )
        st.dataframe(formatar_df_ranking(top_uf), use_container_width=True, hide_index=True)

    with col_b:
        st.subheader("🏙️ Cidades")
        if uf == "TODOS":
            top_cidades = consulta_df(
                """
                SELECT cidade AS Cidade, quantidade AS Contatos
                FROM contagem_cidade
                ORDER BY quantidade DESC
                LIMIT 20
                """
            )
        else:
            top_cidades = consulta_df(
                """
                SELECT cidade AS Cidade, quantidade AS Contatos
                FROM contagem_uf_cidade
                WHERE uf = ?
                ORDER BY quantidade DESC
                LIMIT 20
                """,
                (uf,)
            )
        st.dataframe(formatar_df_ranking(top_cidades), use_container_width=True, hide_index=True)

    with col_c:
        st.subheader("💼 CBOs")
        if uf == "TODOS":
            top_cbos = consulta_df(
                """
                SELECT cbo AS CBO, quantidade AS Contatos
                FROM contagem_cbo
                ORDER BY quantidade DESC
                LIMIT 20
                """
            )
        else:
            top_cbos = consulta_df(
                """
                SELECT cbo AS CBO, quantidade AS Contatos
                FROM contagem_uf_cbo
                WHERE uf = ?
                ORDER BY quantidade DESC
                LIMIT 20
                """,
                (uf,)
            )
        st.dataframe(formatar_df_ranking(top_cbos), use_container_width=True, hide_index=True)

except Exception as erro:
    st.warning("Não foi possível carregar um dos rankings.")
    st.exception(erro)


st.caption(
    "Sistema com filtro por UF, CBO, Múltiplas Cidades e Faixa de renda. "
    "Ao escolher uma UF, a lista de cidades disponíveis no campo de múltipla escolha é restrita àquele estado."
)
