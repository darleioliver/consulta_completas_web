"""Integração opt-in Google Data Manager API para conversões de recarga pagas.

Sem efeitos colaterais em importação. Não contém credenciais; ler apenas Railway vars.
"""
import os
import re
from datetime import datetime, timezone
from decimal import Decimal
from urllib.parse import unquote

import requests

API_URL = "https://datamanager.googleapis.com/v1/events:ingest"
TOKEN_URL = "https://oauth2.googleapis.com/token"


def ads_configurado():
    chaves = (
        "GOOGLE_DM_CLIENT_ID", "GOOGLE_DM_CLIENT_SECRET", "GOOGLE_DM_REFRESH_TOKEN",
        "GOOGLE_DM_CUSTOMER_ID", "GOOGLE_DM_CONVERSION_ACTION_ID",
    )
    return os.getenv("GOOGLE_DM_ENABLED", "0") == "1" and all(os.getenv(k, "").strip() for k in chaves)


def normalizar_click_id(valor):
    valor = str(valor or "").strip()
    # IDs vêm do Google e não devem conter tags/JS; limites evitam cookies adulterados.
    return valor if re.fullmatch(r"[A-Za-z0-9_.~+:/=-]{6,500}", valor) else None


def identificar_clique(args, cookies):
    """Prioriza parâmetros do clique; em seguida cookies compartilhados entre subdomínios.

    _gcl_aw é gerado pelo tag do Google quando disponível (formato GCL.timestamp.gclid).
    """
    if cookies.get("cz_consent") != "granted":
        return {}
    identificadores = {}
    for nome in ("gclid", "gbraid", "wbraid"):
        valor = normalizar_click_id(args.get(nome)) or normalizar_click_id(unquote(str(cookies.get("cz_ads_" + nome) or "")))
        if nome == "gclid" and not valor:
            cookie_gcl = str(cookies.get("_gcl_aw") or "")
            partes = cookie_gcl.split(".", 2)
            if len(partes) == 3 and partes[0] == "GCL":
                valor = normalizar_click_id(partes[2])
        if valor:
            identificadores[nome] = valor
    # Somente um identificador por conversão evita combinar campanhas de visitas distintas.
    for prioridade in ("gclid", "gbraid", "wbraid"):
        if prioridade in identificadores:
            return {prioridade: identificadores[prioridade]}
    return {}


def payload_evento(pagamento):
    """Converte uma linha da fila em evento; nenhum nome/email/telefone é enviado."""
    chave = next((k for k in ("gclid", "gbraid", "wbraid") if pagamento.get(k)), None)
    if not chave:
        raise ValueError("Sem identificador de clique do Google Ads")
    event_dt = pagamento["evento_em"]
    if isinstance(event_dt, str):
        event_dt = datetime.fromisoformat(event_dt.replace("Z", "+00:00"))
    if event_dt.tzinfo is None:
        event_dt = event_dt.replace(tzinfo=timezone.utc)
    return {
        "adIdentifiers": {chave: pagamento[chave]},
        "conversionValue": float(Decimal(str(pagamento["valor"])).quantize(Decimal("0.01"))),
        "currency": "BRL",
        "eventTimestamp": event_dt.isoformat(timespec="seconds"),
        "transactionId": str(pagamento["asaas_payment_id"]),
        "eventSource": "WEB",
    }


def montar_requisicao(evento):
    customer = re.sub(r"\D", "", os.getenv("GOOGLE_DM_CUSTOMER_ID", ""))
    login = re.sub(r"\D", "", os.getenv("GOOGLE_DM_LOGIN_CUSTOMER_ID", "")) or customer
    action = os.getenv("GOOGLE_DM_CONVERSION_ACTION_ID", "").strip()
    if len(customer) != 10 or not action.isdigit():
        raise ValueError("Customer ID (10 dígitos) ou ID da ação de conversão inválido")
    return {
        "destinations": [{
            "operatingAccount": {"accountType": "GOOGLE_ADS", "accountId": customer},
            "loginAccount": {"accountType": "GOOGLE_ADS", "accountId": login},
            "productDestinationId": action,
        }],
        "events": [evento],
        "validateOnly": False,
    }


def enviar_evento(pagamento):
    if not ads_configurado():
        raise RuntimeError("Google Data Manager não configurado no Railway")
    evento = payload_evento(pagamento)
    corpo = montar_requisicao(evento)
    token_resp = requests.post(TOKEN_URL, data={
        "grant_type": "refresh_token",
        "client_id": os.environ["GOOGLE_DM_CLIENT_ID"],
        "client_secret": os.environ["GOOGLE_DM_CLIENT_SECRET"],
        "refresh_token": os.environ["GOOGLE_DM_REFRESH_TOKEN"],
    }, timeout=20)
    if not token_resp.ok:
        raise RuntimeError(f"OAuth Google recusou autenticação (HTTP {token_resp.status_code})")
    token = token_resp.json().get("access_token")
    if not token:
        raise RuntimeError("OAuth Google não retornou access_token")
    headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
    project = os.getenv("GOOGLE_DM_PROJECT_ID", "").strip()
    if project:
        headers["x-goog-user-project"] = project
    resposta = requests.post(API_URL, headers=headers, json=corpo, timeout=30)
    if not resposta.ok:
        # Evita expor email, credenciais ou gclid dos clientes nos logs.
        raise RuntimeError(f"Data Manager rejeitou a conversão (HTTP {resposta.status_code}): "
                           f"{resposta.text[:220]}")
    json_resp = resposta.json()
    if not json_resp.get("requestId"):
        raise RuntimeError("Data Manager não devolveu requestId")
    return str(json_resp["requestId"])


def testar_integracao_sem_compra():
    """Diagnostica OAuth e valida um evento SINTÉTICO sem ingeri-lo.

    Usado SOMENTE numa ação POST administrativa; não cria recargas ou conversões.
    Os identificadores de teste nunca são enviados com validateOnly=False.
    """
    if not ads_configurado():
        return {"ok": False, "etapa": "configuracao", "motivo": "INTEGRACAO_DESABILITADA_OU_INCOMPLETA"}

    try:
        corpo = montar_requisicao(payload_evento({
            "gclid": "CZ_VALIDACAO_SEM_COMPRA_1234567890123456",
            "asaas_payment_id": "CZ-SOMENTE-VALIDACAO",
            "valor": "1.00",
            "evento_em": datetime.now(timezone.utc),
        }))
    except (ValueError, TypeError, KeyError):
        return {"ok": False, "etapa": "configuracao", "motivo": "ID_CONTA_OU_CONVERSAO_INVALIDO"}
    # A API NÃO processa nem contabiliza eventos quando validateOnly=True.
    corpo["validateOnly"] = True

    try:
        token_resp = requests.post(TOKEN_URL, data={
            "grant_type": "refresh_token",
            "client_id": os.environ["GOOGLE_DM_CLIENT_ID"],
            "client_secret": os.environ["GOOGLE_DM_CLIENT_SECRET"],
            "refresh_token": os.environ["GOOGLE_DM_REFRESH_TOKEN"],
        }, timeout=20)
    except requests.RequestException:
        return {"ok": False, "etapa": "oauth", "motivo": "FALHA_DE_REDE"}
    if not token_resp.ok:
        return {"ok": False, "etapa": "oauth", "http_status": token_resp.status_code,
                "motivo": "CREDENCIAIS_RECUSADAS"}
    try:
        access_token = token_resp.json().get("access_token")
    except ValueError:
        access_token = None
    if not access_token:
        return {"ok": False, "etapa": "oauth", "motivo": "TOKEN_AUSENTE"}

    headers = {"Authorization": "Bearer " + access_token, "Content-Type": "application/json"}
    project = os.getenv("GOOGLE_DM_PROJECT_ID", "").strip()
    if project:
        headers["x-goog-user-project"] = project
    try:
        resposta = requests.post(API_URL, headers=headers, json=corpo, timeout=30)
    except requests.RequestException:
        return {"ok": False, "oauth": "OK", "etapa": "data_manager", "motivo": "FALHA_DE_REDE"}
    if not resposta.ok:
        # Nunca apresentar corpo da resposta, códigos secretos, IDs de clientes ou de cliques.
        try:
            status = str(resposta.json().get("error", {}).get("status", "ERRO_DESCONHECIDO"))
        except (ValueError, TypeError, AttributeError):
            status = "ERRO_DESCONHECIDO"
        return {"ok": False, "oauth": "OK", "etapa": "data_manager",
                "http_status": resposta.status_code, "motivo": status,
                "validate_only": True, "conversoes_registradas": 0}
    return {"ok": True, "oauth": "OK", "data_manager": "REQUISICAO_VALIDADA",
            "validate_only": True, "conversoes_registradas": 0,
            "aviso": "Teste de validacao; ainda precisa confirmar um pagamento real e os diagnosticos de importacao."}
