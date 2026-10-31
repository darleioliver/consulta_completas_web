import csv
import random
import re
import unicodedata
from datetime import date, datetime
from pathlib import Path

import pandas as pd

PASTA_MEI_2026 = None
PASTA_CPF = None
CHUNK_EXPORTACAO = 100_000
FATOR_AMOSTRA_ALEATORIA = 10
MAX_POOL_ALEATORIO = 100_000

UFS_VALIDAS = {
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO",
    "MA", "MT", "MS", "MG", "PA", "PB", "PR", "PE", "PI",
    "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO",
}


class TelefonesVistosComHistorico:
    """
    Conjunto compatível com o motor atual, mas consulta também o histórico
    persistente do cliente sem carregar milhões de telefones na RAM.
    """
    def __init__(self, historico_checker=None, atuais=None, contador=None):
        self.historico_checker = historico_checker
        self.atuais = set(atuais or [])
        self.contador = contador if contador is not None else {"historico_hits": 0}

    def __contains__(self, numero):
        if numero in self.atuais:
            return True
        if self.historico_checker and self.historico_checker(numero):
            self.contador["historico_hits"] = int(self.contador.get("historico_hits", 0)) + 1
            return True
        return False

    def add(self, numero):
        self.atuais.add(numero)

    def __iter__(self):
        return iter(self.atuais)

    def __len__(self):
        return len(self.atuais)

    def clone(self):
        return TelefonesVistosComHistorico(
            historico_checker=self.historico_checker,
            atuais=self.atuais.copy(),
            contador=self.contador,
        )


def _clonar_telefones_vistos(telefones_vistos):
    if hasattr(telefones_vistos, "clone"):
        return telefones_vistos.clone()
    return set(telefones_vistos)

def configurar_caminhos(pasta_mei_2026, pasta_cpf):
    global PASTA_MEI_2026, PASTA_CPF
    PASTA_MEI_2026 = Path(pasta_mei_2026)
    PASTA_CPF = Path(pasta_cpf)

def remover_acentos(texto):
    texto = str(texto)
    return "".join(
        c
        for c in unicodedata.normalize("NFD", texto)
        if unicodedata.category(c) != "Mn"
    )

def normalizar_comparacao(texto):
    texto = remover_acentos(str(texto).strip().upper())
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip()

def normalizar_nome_coluna(texto):
    return normalizar_comparacao(texto)

def mapa_colunas_dataframe(df):
    return {
        normalizar_nome_coluna(coluna): coluna
        for coluna in df.columns
    }

def obter_coluna(mapa, *nomes):
    for nome in nomes:
        chave = normalizar_nome_coluna(nome)
        if chave in mapa:
            return mapa[chave]
    return None

def limpar_codigo(valor):
    texto = str(valor).strip()
    return re.sub(r"\.0+$", "", texto)

def limpar_razao_social(valor):
    """
    Mantém somente letras e espaços.
    Remove números, pontos, traços e demais sinais.
    """
    texto = str(valor).strip().upper()
    saida = []

    for caractere in texto:
        categoria = unicodedata.category(caractere)

        if caractere.isspace():
            saida.append(" ")
        elif categoria.startswith("L"):
            saida.append(caractere)
        else:
            saida.append(" ")

    texto = "".join(saida)
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip()

def parse_lista_texto(texto):
    if not str(texto).strip():
        return []

    texto = str(texto).replace(";", ",").replace("\n", ",")
    itens = [item.strip() for item in texto.split(",") if item.strip()]
    return list(dict.fromkeys(itens))

def parse_ddds(texto):
    if not str(texto).strip():
        return []

    resultado = []

    for parte in re.split(r"[,;\s]+", str(texto)):
        digitos = re.sub(r"\D", "", parte)
        if len(digitos) == 2:
            resultado.append(digitos)

    return list(dict.fromkeys(resultado))

def normalizar_telefone_nacional(valor, uf=""):
    """
    Ex.: +55 (77) 99833-4733 -> 77998334733
    O DDD passa a ser os dois primeiros dígitos: 77.
    """
    numero = re.sub(r"\D", "", str(valor))

    if len(numero) in (12, 13) and numero.startswith("55"):
        numero = numero[2:]

    minimo = 6 if str(uf).strip().upper() == "SP" else 7

    if len(numero) == 10:
        if not numero[2].isdigit() or int(numero[2]) < minimo:
            return None
        numero = numero[:2] + "9" + numero[2:]

    elif len(numero) == 11:
        if not numero[2].isdigit() or int(numero[2]) < minimo:
            return None

    else:
        return None

    return numero if len(numero) == 11 else None

def telefone_final_com_55(numero_nacional):
    if not numero_nacional:
        return None
    return "+55" + numero_nacional

def ddd_do_telefone(numero_nacional):
    if numero_nacional and len(numero_nacional) >= 2:
        return numero_nacional[:2]
    return ""

def detectar_encoding_csv(caminho):
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin1"):
        try:
            with open(caminho, "r", encoding=encoding) as arquivo:
                arquivo.read(100_000)
            return encoding
        except UnicodeDecodeError:
            pass

    return "latin1"

def detectar_separador_csv(caminho, encoding):
    try:
        with open(
            caminho,
            "r",
            encoding=encoding,
            errors="replace",
        ) as arquivo:
            amostra = arquivo.read(100_000)

        dialect = csv.Sniffer().sniff(amostra, delimiters=";,\t|")
        return dialect.delimiter

    except Exception:
        return ";"

def serie_normalizada(serie):
    return (
        serie.fillna("")
        .astype(str)
        .map(normalizar_comparacao)
    )

def idade_de_nascimento_bruto(valor, referencia=None):
    if referencia is None:
        referencia = date.today()

    texto = str(valor).strip()
    if not texto:
        return None

    match = re.match(r"^\s*(\d{4})-(\d{1,2})", texto)

    if match:
        ano = int(match.group(1))
        mes = int(match.group(2))
    else:
        match = re.match(r"^\s*\d{1,2}/(\d{1,2})/(\d{4})", texto)
        if not match:
            return None
        mes = int(match.group(1))
        ano = int(match.group(2))

    if not 1 <= mes <= 12:
        return None

    meses_ref = referencia.year * 12 + referencia.month - 1
    meses_nasc = ano * 12 + mes - 1
    idade = (meses_ref - meses_nasc) // 12

    return idade if 0 <= idade <= 130 else None

def descobrir_uf_pelo_caminho(caminho, pasta_raiz):
    try:
        relativo = Path(caminho).resolve().relative_to(Path(pasta_raiz).resolve())
        partes = relativo.parts
    except Exception:
        partes = Path(caminho).parts

    for parte in partes:
        valor = str(parte).strip().upper()
        if valor in UFS_VALIDAS:
            return valor

    nome_base = Path(caminho).stem.strip().upper()
    return nome_base if nome_base in UFS_VALIDAS else ""

def listar_csvs_mei(ufs_sel):
    if not PASTA_MEI_2026.exists():
        raise RuntimeError(
            "A pasta dos arquivos Atualizados 2026 não foi encontrada:\n"
            f"{PASTA_MEI_2026}"
        )

    todos = sorted(PASTA_MEI_2026.rglob("*.csv"))

    if not ufs_sel:
        return todos

    desejadas = {str(uf).upper() for uf in ufs_sel}
    selecionados = []

    for caminho in todos:
        uf_arquivo = descobrir_uf_pelo_caminho(caminho, PASTA_MEI_2026)
        if uf_arquivo in desejadas:
            selecionados.append(caminho)

    # Caso o nome do arquivo não permita saber a UF,
    # ainda filtra pela própria coluna UF dentro do CSV.
    return selecionados if selecionados else todos

def listar_csvs_cpf(ufs_sel):
    if not PASTA_CPF.exists():
        raise RuntimeError(
            "A pasta dos arquivos detalhados não foi encontrada:\n"
            f"{PASTA_CPF}"
        )

    if ufs_sel:
        arquivos = []

        for uf in ufs_sel:
            pasta_uf = PASTA_CPF / str(uf).upper()
            if pasta_uf.exists():
                arquivos.extend(sorted(pasta_uf.rglob("*.csv")))

        if arquivos:
            return arquivos

    return sorted(PASTA_CPF.rglob("*.csv"))

def aplicar_filtros_comuns(
    df,
    coluna_uf,
    coluna_cidade,
    coluna_sexo,
    ufs_sel,
    cidades_sel,
    sexos_sel,
):
    mascara = pd.Series(True, index=df.index)

    if ufs_sel:
        ufs_norm = {normalizar_comparacao(uf) for uf in ufs_sel}
        mascara &= serie_normalizada(df[coluna_uf]).isin(ufs_norm)

    if cidades_sel:
        cidades_norm = {
            normalizar_comparacao(cidade)
            for cidade in cidades_sel
        }
        mascara &= serie_normalizada(df[coluna_cidade]).isin(cidades_norm)

    if sexos_sel:
        sexos_norm = {str(sexo).strip().upper() for sexo in sexos_sel}
        mascara &= (
            df[coluna_sexo]
            .fillna("")
            .astype(str)
            .str.strip()
            .str.upper()
            .isin(sexos_norm)
        )

    return mascara

def coletar_mei(
    limite,
    ufs_sel,
    cidades_sel,
    sexos_sel,
    ceps_sel,
    bairros_sel,
    ddds_sel,
    telefones_vistos,
    callback=None,
):
    registros = []
    arquivos = listar_csvs_mei(ufs_sel)
    total_arquivos = len(arquivos)

    estatisticas = {
        "arquivos_lidos": 0,
        "linhas_filtradas": 0,
        "invalidos_telefone": 0,
        "duplicados": 0,
    }

    bairros_norm = {
        normalizar_comparacao(bairro)
        for bairro in bairros_sel
    }

    ceps_norm = {
        re.sub(r"\D", "", str(cep)).zfill(8)
        for cep in ceps_sel
    }

    ddds_norm = {str(ddd) for ddd in ddds_sel}

    for indice_arquivo, caminho in enumerate(arquivos, start=1):
        if len(registros) >= limite:
            break

        if callback:
            callback(
                len(registros),
                limite,
                f"Processando dados selecionados ({indice_arquivo}/{total_arquivos})...",
            )

        encoding = detectar_encoding_csv(caminho)
        separador = detectar_separador_csv(caminho, encoding)

        leitor = pd.read_csv(
            caminho,
            sep=separador,
            encoding=encoding,
            dtype=str,
            keep_default_na=False,
            chunksize=CHUNK_EXPORTACAO,
            low_memory=False,
            on_bad_lines="skip",
        )

        estatisticas["arquivos_lidos"] += 1

        for df in leitor:
            if len(registros) >= limite:
                break

            df.columns = [str(coluna).strip() for coluna in df.columns]
            mapa = mapa_colunas_dataframe(df)

            col_nome = obter_coluna(mapa, "Razão Social", "Razao Social")
            col_tel = obter_coluna(mapa, "Telefone 1", "Telefone")
            col_cep = obter_coluna(mapa, "CEP")
            col_cidade = obter_coluna(
                mapa,
                "Município",
                "Municipio",
                "Cidade",
            )
            col_bairro = obter_coluna(mapa, "Bairro")
            col_uf = obter_coluna(mapa, "UF")
            col_sexo = obter_coluna(mapa, "Sexo")

            obrigatorias = {
                "Razão Social": col_nome,
                "Telefone 1": col_tel,
                "Município": col_cidade,
                "Bairro": col_bairro,
                "UF": col_uf,
                "Sexo": col_sexo,
            }

            faltando = [
                nome
                for nome, coluna in obrigatorias.items()
                if coluna is None
            ]

            if faltando:
                print(
                    f"[AVISO] CSV MEI ignorado (colunas incompatíveis): {caminho} "
                    f"| Faltando: {', '.join(faltando)}",
                    flush=True,
                )
                break  # Passa ao próximo CSV; não interrompe o pedido.

            mascara = aplicar_filtros_comuns(
                df,
                col_uf,
                col_cidade,
                col_sexo,
                ufs_sel,
                cidades_sel,
                sexos_sel,
            )

            if ceps_norm:
                if col_cep is None:
                    mascara &= False
                else:
                    cep_serie = (
                        df[col_cep]
                        .fillna("")
                        .astype(str)
                        .str.replace(r"\D", "", regex=True)
                        .str.zfill(8)
                    )
                    mascara &= cep_serie.isin(ceps_norm)

            if bairros_norm:
                mascara &= serie_normalizada(df[col_bairro]).isin(bairros_norm)

            filtrado = df.loc[mascara]
            estatisticas["linhas_filtradas"] += len(filtrado)

            for _, linha in filtrado.iterrows():
                if len(registros) >= limite:
                    break

                uf = str(linha[col_uf]).strip().upper()
                numero_nacional = normalizar_telefone_nacional(
                    linha[col_tel],
                    uf,
                )

                if not numero_nacional:
                    estatisticas["invalidos_telefone"] += 1
                    continue

                if ddds_norm and ddd_do_telefone(numero_nacional) not in ddds_norm:
                    continue

                if numero_nacional in telefones_vistos:
                    estatisticas["duplicados"] += 1
                    continue

                telefones_vistos.add(numero_nacional)

                cep_valor = ""
                if col_cep is not None:
                    cep_valor = re.sub(r"\D", "", str(linha[col_cep]))
                    if cep_valor:
                        cep_valor = cep_valor.zfill(8)

                registros.append(
                    {
                        "Nome": limpar_razao_social(linha[col_nome]),
                        "Telefone": telefone_final_com_55(numero_nacional),
                        "CEP": cep_valor,
                        "Município": str(linha[col_cidade]).strip(),
                        "Bairro": str(linha[col_bairro]).strip(),
                        "UF": uf,
                    }
                )

    return registros, estatisticas

def coletar_cpf(
    limite,
    ufs_sel,
    cidades_sel,
    sexos_sel,
    cbos_sel,
    faixas_sel,
    usar_idade,
    idade_min,
    idade_max,
    ceps_sel,
    bairros_sel,
    ddds_sel,
    telefones_vistos,
    modo_unificado,
    callback=None,
):
    registros = []
    arquivos = listar_csvs_cpf(ufs_sel)
    total_arquivos = len(arquivos)

    estatisticas = {
        "arquivos_lidos": 0,
        "linhas_filtradas": 0,
        "invalidos_telefone": 0,
        "duplicados": 0,
    }

    bairros_norm = {
        normalizar_comparacao(bairro)
        for bairro in bairros_sel
    }
    ceps_norm = {
        re.sub(r"\D", "", str(cep)).zfill(8)
        for cep in ceps_sel
        if str(cep).strip()
    }
    ddds_norm = {str(ddd) for ddd in ddds_sel}
    cbos_norm = {limpar_codigo(cbo) for cbo in cbos_sel}
    faixas_norm = {limpar_codigo(faixa) for faixa in faixas_sel}

    for indice_arquivo, caminho in enumerate(arquivos, start=1):
        if len(registros) >= limite:
            break

        if callback:
            callback(
                len(registros),
                limite,
                f"Processando contatos disponíveis ({indice_arquivo}/{total_arquivos})...",
            )

        encoding = detectar_encoding_csv(caminho)
        separador = detectar_separador_csv(caminho, encoding)

        leitor = pd.read_csv(
            caminho,
            sep=separador,
            encoding=encoding,
            dtype=str,
            keep_default_na=False,
            chunksize=CHUNK_EXPORTACAO,
            low_memory=False,
            on_bad_lines="skip",
        )

        estatisticas["arquivos_lidos"] += 1

        for df in leitor:
            if len(registros) >= limite:
                break

            df.columns = [str(coluna).strip() for coluna in df.columns]
            mapa = mapa_colunas_dataframe(df)

            col_cpf = obter_coluna(mapa, "CPF")
            col_nome = obter_coluna(mapa, "NOME", "Nome")
            col_sexo = obter_coluna(mapa, "SEXO", "Sexo")
            col_bairro = obter_coluna(mapa, "BAIRRO", "Bairro")
            col_cidade = obter_coluna(
                mapa,
                "CIDADE",
                "Cidade",
                "Município",
                "Municipio",
            )
            col_uf = obter_coluna(mapa, "UF")
            col_cep = obter_coluna(mapa, "CEP")
            col_nasc = obter_coluna(mapa, "NASC")
            col_cbo = obter_coluna(mapa, "CBO")
            col_renda = obter_coluna(mapa, "RENDA")
            col_faixa = obter_coluna(mapa, "FAIXA_RENDA_ID")
            col_tel = obter_coluna(
                mapa,
                "TELEFONE_COMPLETO",
                "Telefone Completo",
                "Telefone",
            )

            obrigatorias = {
                "NOME": col_nome,
                "SEXO": col_sexo,
                "BAIRRO": col_bairro,
                "CIDADE": col_cidade,
                "UF": col_uf,
                "CEP": col_cep,
                "NASC": col_nasc,
                "CBO": col_cbo,
                "RENDA": col_renda,
                "FAIXA_RENDA_ID": col_faixa,
                "TELEFONE_COMPLETO": col_tel,
            }

            if not modo_unificado:
                obrigatorias["CPF"] = col_cpf

            faltando = [
                nome
                for nome, coluna in obrigatorias.items()
                if coluna is None
            ]

            if faltando:
                print(
                    f"[AVISO] CSV CPF ignorado (colunas incompatíveis): {caminho} "
                    f"| Faltando: {', '.join(faltando)}",
                    flush=True,
                )
                break  # Passa ao próximo CSV; não interrompe o pedido.

            mascara = aplicar_filtros_comuns(
                df,
                col_uf,
                col_cidade,
                col_sexo,
                ufs_sel,
                cidades_sel,
                sexos_sel,
            )

            if ceps_norm:
                cep_serie = (
                    df[col_cep]
                    .fillna("")
                    .astype(str)
                    .str.replace(r"\D", "", regex=True)
                    .str.zfill(8)
                )
                mascara &= cep_serie.isin(ceps_norm)

            if cbos_norm:
                mascara &= (
                    df[col_cbo]
                    .fillna("")
                    .astype(str)
                    .map(limpar_codigo)
                    .isin(cbos_norm)
                )

            if faixas_norm:
                mascara &= (
                    df[col_faixa]
                    .fillna("")
                    .astype(str)
                    .map(limpar_codigo)
                    .isin(faixas_norm)
                )

            if usar_idade:
                idades = (
                    df[col_nasc]
                    .fillna("")
                    .astype(str)
                    .map(idade_de_nascimento_bruto)
                )

                mascara &= (
                    idades.ge(int(idade_min))
                    & idades.le(int(idade_max))
                )

            if bairros_norm:
                mascara &= serie_normalizada(df[col_bairro]).isin(bairros_norm)

            filtrado = df.loc[mascara]
            estatisticas["linhas_filtradas"] += len(filtrado)

            for _, linha in filtrado.iterrows():
                if len(registros) >= limite:
                    break

                uf = str(linha[col_uf]).strip().upper()
                numero_nacional = normalizar_telefone_nacional(
                    linha[col_tel],
                    uf,
                )

                if not numero_nacional:
                    estatisticas["invalidos_telefone"] += 1
                    continue

                if ddds_norm and ddd_do_telefone(numero_nacional) not in ddds_norm:
                    continue

                if numero_nacional in telefones_vistos:
                    estatisticas["duplicados"] += 1
                    continue

                telefones_vistos.add(numero_nacional)
                telefone_final = telefone_final_com_55(numero_nacional)

                cep_valor = re.sub(r"\D", "", str(linha[col_cep]))
                if cep_valor:
                    cep_valor = cep_valor.zfill(8)

                if modo_unificado:
                    registros.append(
                        {
                            "Nome": str(linha[col_nome]).strip(),
                            "Telefone": telefone_final,
                            "CEP": cep_valor,
                            "Município": str(linha[col_cidade]).strip(),
                            "Bairro": str(linha[col_bairro]).strip(),
                            "UF": uf,
                        }
                    )
                else:
                    registros.append(
                        {
                            "CPF": str(linha[col_cpf]).strip(),
                            "NOME": str(linha[col_nome]).strip(),
                            "SEXO": str(linha[col_sexo]).strip().upper(),
                            "BAIRRO": str(linha[col_bairro]).strip(),
                            "CIDADE": str(linha[col_cidade]).strip(),
                            "UF": uf,
                            "CEP": cep_valor,
                            "NASC": str(linha[col_nasc]).strip(),
                            "CBO": str(linha[col_cbo]).strip(),
                            "RENDA": str(linha[col_renda]).strip(),
                            "TELEFONE_COMPLETO": telefone_final,
                        }
                    )

    return registros, estatisticas

def _somar_estatisticas(destino, origem):
    if not origem:
        return destino

    if destino is None:
        destino = {
            "arquivos_lidos": 0,
            "linhas_filtradas": 0,
            "invalidos_telefone": 0,
            "duplicados": 0,
        }

    for chave in destino:
        destino[chave] += int(origem.get(chave, 0))

    return destino

def _telefone_nacional_do_registro(registro, modo_unificado):
    chave = "Telefone" if modo_unificado else "TELEFONE_COMPLETO"
    valor = re.sub(r"\D", "", str(registro.get(chave, "")))

    if valor.startswith("55") and len(valor) == 13:
        valor = valor[2:]

    return valor if len(valor) == 11 else ""

def _registrar_selecionados(registros, telefones_vistos, modo_unificado):
    for registro in registros:
        numero = _telefone_nacional_do_registro(
            registro,
            modo_unificado,
        )

        if numero:
            telefones_vistos.add(numero)

def _limite_pool_aleatorio(quantidade):
    quantidade = max(1, int(quantidade))

    # 5.000 -> 50.000 candidatos.
    # Para pedidos muito grandes, o teto evita transformar
    # a amostragem em uma leitura excessiva.
    return max(
        quantidade,
        min(
            quantidade * FATOR_AMOSTRA_ALEATORIA,
            MAX_POOL_ALEATORIO,
        ),
    )

def _sortear(registros, quantidade):
    quantidade = min(
        int(quantidade),
        len(registros),
    )

    if quantidade <= 0:
        return []

    if len(registros) <= quantidade:
        copia = list(registros)
        random.shuffle(copia)
        return copia

    return random.sample(
        registros,
        quantidade,
    )

def _todos_estados_selecionados(ufs_sel, universo_ufs):
    universo = {
        str(uf).strip().upper()
        for uf in universo_ufs
        if str(uf).strip()
    }

    selecionados = {
        str(uf).strip().upper()
        for uf in ufs_sel
        if str(uf).strip()
    }

    return (
        not selecionados
        or (
            universo
            and selecionados == universo
        )
    )

def coletar_mei_inteligente(
    limite,
    ufs_sel,
    cidades_sel,
    sexos_sel,
    ceps_sel,
    bairros_sel,
    ddds_sel,
    telefones_vistos,
    universo_ufs,
    aleatorio=False,
    distribuir_estados=False,
    callback=None,
):
    """
    - Consulta simples em um estado/cidade: coleta até 10x a quantidade
      e sorteia o resultado.
    - Brasil inteiro / todas as UFs: divide a quantidade entre os estados,
      coleta uma amostra por UF e redistribui eventual sobra.
    """
    limite = int(limite)

    if limite <= 0:
        return [], None

    # -----------------------------------------------------
    # DISTRIBUIÇÃO NACIONAL
    # -----------------------------------------------------
    if distribuir_estados:
        # Se o cliente selecionou várias UFs, distribui SOMENTE entre elas.
        # Sem UF selecionada, distribui entre todo o universo nacional.
        estados = sorted({
            str(uf).strip().upper()
            for uf in ufs_sel
            if str(uf).strip()
        })

        if not estados:
            estados = sorted({
                str(uf).strip().upper()
                for uf in universo_ufs
                if str(uf).strip()
            })

        if not estados:
            estados = sorted(UFS_VALIDAS)

        # Embaralha a ordem só para não privilegiar alfabeticamente
        # sempre os mesmos estados quando houver alguma escassez.
        random.shuffle(estados)

        base = limite // len(estados)
        resto = limite % len(estados)

        selecionados_finais = []
        sobras = []
        stats_total = None

        for indice, uf in enumerate(estados):
            quota = base + (1 if indice < resto else 0)

            if quota <= 0:
                continue

            if callback:
                callback(
                    len(selecionados_finais),
                    limite,
                    f"Organizando resultados ({indice + 1}/{len(estados)})...",
                )

            pool_limite = (
                _limite_pool_aleatorio(quota)
                if aleatorio
                else quota
            )

            # Não deixa candidatos NÃO selecionados bloquearem
            # outras fontes/estados na deduplicação final.
            vistos_temporarios = _clonar_telefones_vistos(telefones_vistos)

            candidatos, stats = coletar_mei(
                limite=pool_limite,
                ufs_sel=[uf],
                cidades_sel=cidades_sel,
                sexos_sel=sexos_sel,
                ceps_sel=ceps_sel,
                bairros_sel=bairros_sel,
                ddds_sel=ddds_sel,
                telefones_vistos=vistos_temporarios,
                callback=None,
            )

            stats_total = _somar_estatisticas(
                stats_total,
                stats,
            )

            random.shuffle(candidatos)

            escolhidos = candidatos[:quota]
            extras = candidatos[quota:]

            _registrar_selecionados(
                escolhidos,
                telefones_vistos,
                modo_unificado=True,
            )

            selecionados_finais.extend(escolhidos)
            sobras.extend(extras)

        # Se alguma UF não conseguiu preencher a própria cota,
        # usa candidatos excedentes das outras UFs.
        faltam = limite - len(selecionados_finais)

        if faltam > 0 and sobras:
            random.shuffle(sobras)

            for registro in sobras:
                if faltam <= 0:
                    break

                numero = _telefone_nacional_do_registro(
                    registro,
                    modo_unificado=True,
                )

                if (
                    not numero
                    or numero in telefones_vistos
                ):
                    continue

                telefones_vistos.add(numero)
                selecionados_finais.append(registro)
                faltam -= 1

        # Fallback: se ainda faltar, procura normalmente em todas as UFs.
        faltam = limite - len(selecionados_finais)

        if faltam > 0:
            extras, stats = coletar_mei(
                limite=faltam,
                ufs_sel=estados,
                cidades_sel=cidades_sel,
                sexos_sel=sexos_sel,
                ceps_sel=ceps_sel,
                bairros_sel=bairros_sel,
                ddds_sel=ddds_sel,
                telefones_vistos=telefones_vistos,
                callback=callback,
            )

            stats_total = _somar_estatisticas(
                stats_total,
                stats,
            )

            selecionados_finais.extend(extras)

        return (
            selecionados_finais[:limite],
            stats_total,
        )

    # -----------------------------------------------------
    # AMOSTRAGEM ALEATÓRIA NORMAL
    # -----------------------------------------------------
    if aleatorio:
        pool_limite = _limite_pool_aleatorio(
            limite
        )

        vistos_temporarios = _clonar_telefones_vistos(
            telefones_vistos
        )

        candidatos, stats = coletar_mei(
            limite=pool_limite,
            ufs_sel=ufs_sel,
            cidades_sel=cidades_sel,
            sexos_sel=sexos_sel,
            ceps_sel=ceps_sel,
            bairros_sel=bairros_sel,
            ddds_sel=ddds_sel,
            telefones_vistos=vistos_temporarios,
            callback=callback,
        )

        escolhidos = _sortear(
            candidatos,
            limite,
        )

        _registrar_selecionados(
            escolhidos,
            telefones_vistos,
            modo_unificado=True,
        )

        return escolhidos, stats

    # -----------------------------------------------------
    # SEQUENCIAL
    # -----------------------------------------------------
    return coletar_mei(
        limite=limite,
        ufs_sel=ufs_sel,
        cidades_sel=cidades_sel,
        sexos_sel=sexos_sel,
        ceps_sel=ceps_sel,
        bairros_sel=bairros_sel,
        ddds_sel=ddds_sel,
        telefones_vistos=telefones_vistos,
        callback=callback,
    )

def coletar_cpf_inteligente(
    limite,
    ufs_sel,
    cidades_sel,
    sexos_sel,
    cbos_sel,
    faixas_sel,
    usar_idade,
    idade_min,
    idade_max,
    ceps_sel,
    bairros_sel,
    ddds_sel,
    telefones_vistos,
    modo_unificado,
    universo_ufs,
    aleatorio=False,
    distribuir_estados=False,
    callback=None,
):
    limite = int(limite)

    if limite <= 0:
        return [], None

    # -----------------------------------------------------
    # DISTRIBUIÇÃO NACIONAL
    # -----------------------------------------------------
    if distribuir_estados:
        # Se o cliente selecionou várias UFs, distribui SOMENTE entre elas.
        # Sem UF selecionada, distribui entre todo o universo nacional.
        estados = sorted({
            str(uf).strip().upper()
            for uf in ufs_sel
            if str(uf).strip()
        })

        if not estados:
            estados = sorted({
                str(uf).strip().upper()
                for uf in universo_ufs
                if str(uf).strip()
            })

        if not estados:
            estados = sorted(UFS_VALIDAS)

        random.shuffle(estados)

        base = limite // len(estados)
        resto = limite % len(estados)

        selecionados_finais = []
        sobras = []
        stats_total = None

        for indice, uf in enumerate(estados):
            quota = base + (1 if indice < resto else 0)

            if quota <= 0:
                continue

            if callback:
                callback(
                    len(selecionados_finais),
                    limite,
                    f"Organizando resultados ({indice + 1}/{len(estados)})...",
                )

            pool_limite = (
                _limite_pool_aleatorio(quota)
                if aleatorio
                else quota
            )

            vistos_temporarios = _clonar_telefones_vistos(
                telefones_vistos
            )

            candidatos, stats = coletar_cpf(
                limite=pool_limite,
                ufs_sel=[uf],
                cidades_sel=cidades_sel,
                sexos_sel=sexos_sel,
                cbos_sel=cbos_sel,
                faixas_sel=faixas_sel,
                usar_idade=usar_idade,
                idade_min=idade_min,
                idade_max=idade_max,
                ceps_sel=ceps_sel,
                bairros_sel=bairros_sel,
                ddds_sel=ddds_sel,
                telefones_vistos=vistos_temporarios,
                modo_unificado=modo_unificado,
                callback=None,
            )

            stats_total = _somar_estatisticas(
                stats_total,
                stats,
            )

            random.shuffle(candidatos)

            escolhidos = candidatos[:quota]
            extras = candidatos[quota:]

            _registrar_selecionados(
                escolhidos,
                telefones_vistos,
                modo_unificado=modo_unificado,
            )

            selecionados_finais.extend(
                escolhidos
            )

            sobras.extend(
                extras
            )

        faltam = limite - len(
            selecionados_finais
        )

        if faltam > 0 and sobras:
            random.shuffle(
                sobras
            )

            for registro in sobras:
                if faltam <= 0:
                    break

                numero = _telefone_nacional_do_registro(
                    registro,
                    modo_unificado=modo_unificado,
                )

                if (
                    not numero
                    or numero in telefones_vistos
                ):
                    continue

                telefones_vistos.add(
                    numero
                )

                selecionados_finais.append(
                    registro
                )

                faltam -= 1

        faltam = limite - len(
            selecionados_finais
        )

        if faltam > 0:
            extras, stats = coletar_cpf(
                limite=faltam,
                ufs_sel=estados,
                cidades_sel=cidades_sel,
                sexos_sel=sexos_sel,
                cbos_sel=cbos_sel,
                faixas_sel=faixas_sel,
                usar_idade=usar_idade,
                idade_min=idade_min,
                idade_max=idade_max,
                ceps_sel=ceps_sel,
                bairros_sel=bairros_sel,
                ddds_sel=ddds_sel,
                telefones_vistos=telefones_vistos,
                modo_unificado=modo_unificado,
                callback=callback,
            )

            stats_total = _somar_estatisticas(
                stats_total,
                stats,
            )

            selecionados_finais.extend(
                extras
            )

        return (
            selecionados_finais[:limite],
            stats_total,
        )

    # -----------------------------------------------------
    # AMOSTRAGEM ALEATÓRIA NORMAL
    # -----------------------------------------------------
    if aleatorio:
        pool_limite = (
            _limite_pool_aleatorio(
                limite
            )
        )

        vistos_temporarios = _clonar_telefones_vistos(
            telefones_vistos
        )

        candidatos, stats = coletar_cpf(
            limite=pool_limite,
            ufs_sel=ufs_sel,
            cidades_sel=cidades_sel,
            sexos_sel=sexos_sel,
            cbos_sel=cbos_sel,
            faixas_sel=faixas_sel,
            usar_idade=usar_idade,
            idade_min=idade_min,
            idade_max=idade_max,
            ceps_sel=ceps_sel,
            bairros_sel=bairros_sel,
            ddds_sel=ddds_sel,
            telefones_vistos=vistos_temporarios,
            modo_unificado=modo_unificado,
            callback=callback,
        )

        escolhidos = _sortear(
            candidatos,
            limite,
        )

        _registrar_selecionados(
            escolhidos,
            telefones_vistos,
            modo_unificado=modo_unificado,
        )

        return (
            escolhidos,
            stats,
        )

    # -----------------------------------------------------
    # SEQUENCIAL
    # -----------------------------------------------------
    return coletar_cpf(
        limite=limite,
        ufs_sel=ufs_sel,
        cidades_sel=cidades_sel,
        sexos_sel=sexos_sel,
        cbos_sel=cbos_sel,
        faixas_sel=faixas_sel,
        usar_idade=usar_idade,
        idade_min=idade_min,
        idade_max=idade_max,
        ceps_sel=ceps_sel,
        bairros_sel=bairros_sel,
        ddds_sel=ddds_sel,
        telefones_vistos=telefones_vistos,
        modo_unificado=modo_unificado,
        callback=callback,
    )

def salvar_excel_formatado(registros, caminho_saida, modo_unificado):
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font
        from openpyxl.utils import get_column_letter
    except ImportError:
        raise RuntimeError(
            "A biblioteca openpyxl não está instalada. "
            "Execute: python -m pip install openpyxl"
        )

    if modo_unificado:
        colunas = [
            "Nome",
            "Telefone",
            "CEP",
            "Município",
            "Bairro",
            "UF",
        ]
        larguras = {
            "A": 46,
            "B": 21,
            "C": 14,
            "D": 30,
            "E": 30,
            "F": 10,
        }
    else:
        # Ordem solicitada para exportação detalhada.
        colunas = [
            "CPF",
            "NOME",
            "TELEFONE_COMPLETO",
            "CEP",
            "CIDADE",
            "BAIRRO",
            "UF",
            "SEXO",
            "NASC",
            "RENDA",
            "CBO",
        ]
        larguras = {
            "A": 18,  # CPF
            "B": 42,  # NOME
            "C": 22,  # TELEFONE_COMPLETO
            "D": 14,  # CEP
            "E": 30,  # CIDADE
            "F": 28,  # BAIRRO
            "G": 10,  # UF
            "H": 12,  # SEXO
            "I": 22,  # NASC
            "J": 16,  # RENDA
            "K": 15,  # CBO
        }

    wb = Workbook()
    ws = wb.active
    ws.title = "Contatos"

    for coluna_indice, nome in enumerate(colunas, start=1):
        celula = ws.cell(row=1, column=coluna_indice, value=nome)
        celula.font = Font(bold=True)
        celula.alignment = Alignment(horizontal="center", vertical="center")

    for linha_indice, registro in enumerate(registros, start=2):
        for coluna_indice, nome in enumerate(colunas, start=1):
            valor = registro.get(nome, "")
            celula = ws.cell(
                row=linha_indice,
                column=coluna_indice,
                value=str(valor),
            )
            celula.number_format = "@"

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = (
        f"A1:{get_column_letter(len(colunas))}{ws.max_row}"
    )
    ws.row_dimensions[1].height = 24

    for letra, largura in larguras.items():
        ws.column_dimensions[letra].width = largura

    wb.save(caminho_saida)

def exportar_pedido(
    filtros,
    quantidade_solicitada,
    pasta_saida,
    callback=None,
    historico_checker=None,
):
    """
    Executa um pedido recebido do servidor e gera XLSX local.

    historico_checker(numero_nacional) -> bool pode ser informado para
    excluir telefones que esse cliente já recebeu em pedidos anteriores.
    """
    if PASTA_MEI_2026 is None or PASTA_CPF is None:
        raise RuntimeError("Caminhos das bases não configurados.")

    quantidade_solicitada = int(quantidade_solicitada)
    if quantidade_solicitada <= 0:
        raise ValueError("Quantidade precisa ser maior que zero.")

    ufs = [str(x).strip().upper() for x in filtros.get("ufs", []) if str(x).strip()]
    cidades = [str(x).strip() for x in filtros.get("cidades", []) if str(x).strip()]
    sexos = [str(x).strip().upper() for x in filtros.get("sexos", []) if str(x).strip()]
    cbos = [str(x).strip() for x in filtros.get("cbos", []) if str(x).strip()]
    faixas = [str(x).strip() for x in filtros.get("faixas_renda", []) if str(x).strip()]
    bairros = filtros.get("bairros", [])
    ddds = filtros.get("ddds", [])
    ceps = [re.sub(r"\D", "", str(x)).zfill(8) for x in filtros.get("ceps", []) if str(x).strip()]
    atualizados_2026 = bool(filtros.get("atualizados_2026", False))
    usar_idade = bool(filtros.get("filtrar_idade", False))
    idade_min = filtros.get("idade_min")
    idade_max = filtros.get("idade_max")

    if isinstance(bairros, str):
        bairros = parse_lista_texto(bairros)
    if isinstance(ddds, str):
        ddds = parse_ddds(ddds)
    else:
        ddds = parse_ddds(",".join(map(str, ddds)))

    filtro_exclusivo_cpf = bool(cbos or faixas or usar_idade)
    modo_unificado = atualizados_2026 or not filtro_exclusivo_cpf

    # Consultas simples usam pool de até 10x para amostragem aleatória.
    consulta_simples = not bool(cbos or faixas or usar_idade or ceps or bairros)
    usar_aleatorio = consulta_simples

    universo_ufs = sorted(UFS_VALIDAS)

    # Distribui quando:
    # - nenhuma UF foi selecionada (Brasil inteiro), OU
    # - o cliente selecionou duas ou mais UFs.
    # Com uma única UF, mantém a coleta normal.
    ufs_unicas = sorted(set(ufs))
    distribuir_estados = bool(
        (not ufs_unicas or len(ufs_unicas) > 1)
        and not cidades
        and not bairros
        and not ddds
        and not ceps
    )

    telefones_vistos = TelefonesVistosComHistorico(
        historico_checker=historico_checker,
    )
    resultado_final = []
    estatisticas = {
        "mei": None,
        "cpf": None,
        "usou_mei": False,
        "usou_cpf": False,
        "aleatorio": usar_aleatorio,
        "distribuido_estados": distribuir_estados,
    }

    if atualizados_2026 or not filtro_exclusivo_cpf:
        if callback:
            callback(2, "Localizando os contatos disponíveis...")

        mei, stats_mei = coletar_mei_inteligente(
            limite=quantidade_solicitada,
            ufs_sel=ufs,
            cidades_sel=cidades,
            sexos_sel=sexos,
            ceps_sel=ceps,
            bairros_sel=bairros,
            ddds_sel=ddds,
            telefones_vistos=telefones_vistos,
            universo_ufs=universo_ufs,
            aleatorio=usar_aleatorio,
            distribuir_estados=distribuir_estados,
            callback=(lambda atual, total, msg: callback(min(85, 5 + int((atual / max(total,1))*70)), msg)) if callback else None,
        )
        resultado_final.extend(mei)
        estatisticas["mei"] = stats_mei
        estatisticas["usou_mei"] = True

    if atualizados_2026:
        pass
    elif filtro_exclusivo_cpf:
        if callback:
            callback(5, "Aplicando os filtros selecionados...")

        cpf, stats_cpf = coletar_cpf_inteligente(
            limite=quantidade_solicitada,
            ufs_sel=ufs,
            cidades_sel=cidades,
            sexos_sel=sexos,
            cbos_sel=cbos,
            faixas_sel=faixas,
            usar_idade=usar_idade,
            idade_min=idade_min,
            idade_max=idade_max,
            ceps_sel=ceps,
            bairros_sel=bairros,
            ddds_sel=ddds,
            telefones_vistos=telefones_vistos,
            modo_unificado=False,
            universo_ufs=universo_ufs,
            aleatorio=False,
            distribuir_estados=distribuir_estados,
            callback=(lambda atual, total, msg: callback(min(85, 5 + int((atual / max(total,1))*70)), msg)) if callback else None,
        )
        resultado_final.extend(cpf)
        estatisticas["cpf"] = stats_cpf
        estatisticas["usou_cpf"] = True
    else:
        faltam = quantidade_solicitada - len(resultado_final)
        if faltam > 0:
            if callback:
                callback(45, "Organizando os resultados...")

            cpf, stats_cpf = coletar_cpf_inteligente(
                limite=faltam,
                ufs_sel=ufs,
                cidades_sel=cidades,
                sexos_sel=sexos,
                cbos_sel=[],
                faixas_sel=[],
                usar_idade=False,
                idade_min=None,
                idade_max=None,
                ceps_sel=ceps,
                bairros_sel=bairros,
                ddds_sel=ddds,
                telefones_vistos=telefones_vistos,
                modo_unificado=True,
                universo_ufs=universo_ufs,
                aleatorio=usar_aleatorio,
                distribuir_estados=distribuir_estados,
                callback=(lambda atual, total, msg: callback(min(85, 45 + int((atual / max(total,1))*35)), msg)) if callback else None,
            )
            resultado_final.extend(cpf)
            estatisticas["cpf"] = stats_cpf
            estatisticas["usou_cpf"] = True

    resultado_final = resultado_final[:quantidade_solicitada]

    pasta_saida = Path(pasta_saida)
    pasta_saida.mkdir(parents=True, exist_ok=True)
    agora = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
    nome_base = str(filtros.get("nome_arquivo", "") or "CONTATOS").strip()
    nome_base = re.sub(r"[^A-Za-zÀ-ÿ0-9 _.-]+", "", nome_base)
    nome_base = re.sub(r"\s+", "_", nome_base).strip("._- ")
    if not nome_base:
        nome_base = "CONTATOS"
    nome_base = nome_base[:80]
    caminho_saida = pasta_saida / f"{nome_base}_{len(resultado_final)}_{agora}.xlsx"

    if callback:
        callback(90, "Gerando seu arquivo...")

    salvar_excel_formatado(
        resultado_final,
        caminho_saida,
        modo_unificado=modo_unificado,
    )

    if callback:
        callback(98, "Finalizando seu pedido...")

    duplicados = 0
    invalidos = 0
    arquivos_lidos = 0
    for chave in ("mei", "cpf"):
        info = estatisticas.get(chave)
        if info:
            duplicados += int(info.get("duplicados", 0))
            invalidos += int(info.get("invalidos_telefone", 0))
            arquivos_lidos += int(info.get("arquivos_lidos", 0))

    return {
        "arquivo": str(caminho_saida),
        "linhas": len(resultado_final),
        "solicitados": quantidade_solicitada,
        "duplicados_removidos": duplicados,
        "telefones_invalidos": invalidos,
        "arquivos_lidos": arquivos_lidos,
        "modo_unificado": modo_unificado,
        "aleatorio": usar_aleatorio,
        "distribuido_estados": distribuir_estados,
        "historico_cliente_ignorados": int(
            telefones_vistos.contador.get("historico_hits", 0)
        ),
    }
