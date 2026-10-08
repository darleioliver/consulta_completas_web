"""Execute LOCALMENTE no seu PC. Nunca coloque o JSON/refresh token no GitHub.

Instale apenas no PC: py -m pip install google-auth-oauthlib
No Google Cloud: ativar Data Manager API, configurar OAuth desktop (escopo
https://www.googleapis.com/auth/datamanager), incluir sua conta em usuários teste
se o aplicativo estiver em testes.
"""
import json
from pathlib import Path


def main():
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        raise SystemExit("Instale: py -m pip install google-auth-oauthlib")
    caminho = input("Cole o caminho do JSON OAuth para app de computador (Google Cloud): ").strip().strip('"')
    if not Path(caminho).is_file():
        raise SystemExit("Arquivo JSON não encontrado.")
    with open(caminho, encoding="utf-8") as f:
        dados = json.load(f)
    credenciais = dados.get("installed")
    if not credenciais:
        raise SystemExit("Use credencial OAuth tipo Aplicativo para computador (installed).")
    flow = InstalledAppFlow.from_client_secrets_file(
        caminho, scopes=["https://www.googleapis.com/auth/datamanager"]
    )
    cred = flow.run_local_server(port=0, access_type="offline", prompt="consent")
    if not cred.refresh_token:
        raise SystemExit("Google não retornou refresh_token. Revogue o acesso e tente novamente com prompt=consent.")
    print("\nCOPIE OS VALORES DIRETAMENTE PARA AS VARIÁVEIS DO RAILWAY. NÃO ENVIE EM CHATS.\n")
    print("GOOGLE_DM_CLIENT_ID=" + cred.client_id)
    print("GOOGLE_DM_CLIENT_SECRET=" + cred.client_secret)
    print("GOOGLE_DM_REFRESH_TOKEN=" + cred.refresh_token)
    print("\nATENÇÃO: refresh tokens para apps externos no modo Teste podem expirar após 7 dias.")


if __name__ == "__main__":
    main()
