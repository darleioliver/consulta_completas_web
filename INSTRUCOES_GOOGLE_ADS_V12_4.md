# Contatos Zap V12.4 — conversões REAIS de recargas Pix (Google Ads)

## Como funciona

- Mantém a conversão de cadastro do GTM e o webhook Asaas existentes.
- Ao confirmar `PAYMENT_RECEIVED`, o saldo continua sendo creditado da mesma maneira.
- Na mesma transação do saldo, grava uma conversão pendente na tabela `google_ads_conversoes`.
- O envio à API é feito em segundo plano; problemas no Google não interrompem a compra.
- Cada **ID único de pagamento Asaas** só entra uma vez na fila e é enviado como `transactionId`.
- Marca `ENVIADO` quando a API retorna `requestId`. Isso significa que aceitou a requisição, **não é garantia de conversão atribuída**.
- Se o cliente não tiver identificador do anúncio, mantém a compra como `SEM_CLIQUE` (não inventa atribuição).
- Faz novas tentativas nas falhas temporárias. Sem reenviar saldo e sem cobrar novamente.
- Não envia nome, telefone, CPF ou e-mail do cliente para o Google; somente identificador do clique, ID de transação, data, BRL e valor.

## 1. Página de vendas `app.contatozap.com`

Como os dois sites já usam o mesmo GTM, adicione no contêiner `GTM-NQTCRWB5` uma tag **HTML personalizado** com o conteúdo de `CAPTURA_CLIQUE_PAGINA_VENDAS.html`, com acionador **Initialization - All Pages**. Publique depois de testar. Isso permite que o cookie de clique seja lido por `painel.contatozap.com`.

O painel V12.4 também captura parâmetros e reconhece o cookie `_gcl_aw` da tag do Google como alternativa. O snippet só armazena IDs de clique e **não** registra compra. Assegure que ele respeita sua configuração de consentimento e atualize a política de cookies/privacidade quando cabível.

## 2. Google Ads

- Use a conversão **Compra confirmada — Asaas**, de origem **Importação de cliques/off-line** (`UPLOAD_CLICKS`), com contagem **Todas** e valor diferente por conversão.
- Mantenha como **Secundária** até confirmar que o envio de testes foi processado.
- Para a integração da API, precisa do **ID numérico da ação de conversão** (campo `productDestinationId`). **Não confunda** com o código de conversão do GTM `718365247` nem com o rótulo.
- Pause a tag GTM **Comprou** caso ela tente contar o mesmo evento sem confirmação real do Pix; a conversão off-line **não usa acionador GTM**.

Documentação oficial: https://developers.google.com/data-manager/api/devguides/events/google-ads/offline/send-events

## 3. Google Cloud / OAuth

1. Ative a **Data Manager API** no seu projeto do Google Cloud.
2. Configure a tela de consentimento OAuth com escopo `https://www.googleapis.com/auth/datamanager`.
3. Crie um **Cliente OAuth — Aplicativo para computador** e salve o JSON apenas no seu computador.
4. No Windows: `py -m pip install google-auth-oauthlib`.
5. Execute `py GERAR_CREDENCIAIS_GOOGLE_NO_PC.py`, escolha seu arquivo OAuth JSON e autorize usando a conta que tem acesso ao Google Ads.
6. O script mostra `GOOGLE_DM_CLIENT_ID`, `GOOGLE_DM_CLIENT_SECRET` e `GOOGLE_DM_REFRESH_TOKEN` para copiar **somente nas variáveis protegidas do Railway**. **Nunca envie essas três variáveis em chats e não coloque o JSON no GitHub.**

**Atenção:** se o OAuth externo estiver em modo Teste, o refresh token normalmente expira em 7 dias. É necessário configurar e manter a autenticação adequadamente para uso contínuo.

Documentação oficial: https://developers.google.com/data-manager/api/devguides/quickstart/set-up-access

## 4. Variáveis Railway no serviço do painel

Configure, sem colocar aspas adicionais:

| Variável | Explicação |
| --- | --- |
| `GOOGLE_DM_ENABLED` | `0` inicialmente; altere para `1` **após** todas as demais configurações e testes |
| `GOOGLE_DM_CUSTOMER_ID` | ID de 10 dígitos da conta Google Ads responsável pela conversão; sem hífens |
| `GOOGLE_DM_LOGIN_CUSTOMER_ID` | Opcional: ID da conta gerente (MCC) usada no login da API; não configure se usar diretamente a conta anunciante |
| `GOOGLE_DM_CONVERSION_ACTION_ID` | ID **numérico da ação de conversão off-line**, não é o ID da tag GTM |
| `GOOGLE_DM_CLIENT_ID` | Client ID do OAuth Google Cloud |
| `GOOGLE_DM_CLIENT_SECRET` | Client Secret do OAuth Google Cloud (secreto) |
| `GOOGLE_DM_REFRESH_TOKEN` | Refresh token do usuário autorizado (secreto) |
| `GOOGLE_DM_PROJECT_ID` | ID do projeto Google Cloud (recomendado para o cabeçalho `x-goog-user-project`) |

Não precisa adicionar dependências do Google ao serviço Railway; a API é acessada via HTTPS com `requests` já instalado.

## 5. Implantação e teste

1. Substitua o código do seu repositório GitHub com os arquivos do ZIP (mantenha as variáveis atuais e o banco PostgreSQL).
2. Publique com `GOOGLE_DM_ENABLED=0` para assegurar que cadastro, login e Asaas seguem normais.
3. Publique a tag HTML da página de vendas e teste no navegador se o cookie `cz_ads_gclid` foi criado em `.contatozap.com` depois de acessar um link de teste com `?gclid=CjEXEMPLO123456` (exemplo apenas para teste de captura; **não envie conversão com clique fictício**).
4. Confirme que no painel o cookie ficou visível nos dois subdomínios (Ferramentas do desenvolvedor → Application/Aplicativo → Cookies).
5. Configure as credenciais e altere `GOOGLE_DM_ENABLED=1`. O worker começa após a primeira requisição ao painel e consulta a fila em intervalos de até 60 segundos.
6. Para testar uma conversão real, use **uma compra real e um clique publicitário verdadeiro**, evitando dados de teste em produção.
7. Ao entrar com um administrador do painel, acesse `/admin/google-ads/status` para ver quantidade de eventos `PENDENTE`, `SEM_CLIQUE`, `ENVIADO` e `FALHA`. Nos logs Railway também aparecem falhas de envio.
8. Confira os diagnósticos de importação no Google Ads; o processamento e atribuição não são instantâneos. Após validar, você pode avaliar se a conversão deve ficar como **Principal**.

## Limites e cuidados

- Não é possível atribuir automaticamente **todas** as recargas a anúncios: algumas compras são orgânicas ou não possuem identificadores; só as atribuíveis serão importadas.
- A API Data Manager exige que a ação seja do tipo apropriado `UPLOAD_CLICKS`. Não tente usar a antiga ação de **Site** (`WEBPAGE`) nesta integração.
- Quando um pedido é recebido, a fila é atualizada atomicamente com o saldo; indisponibilidade Google não interfere em saldo.
- A API pode retornar um `requestId` e ainda apresentar avisos ou problemas de processamento; confira diagnósticos do Google Ads.
- Se a API ficar desconfigurada, a fila aguarda; após 12 tentativas com erros, o evento muda para `FALHA` para inspeção manual.
- Se houver necessidade legal de consentimento para medição publicitária, o uso do script/cookie e o envio dos IDs devem obedecer a essa preferência. Revise sua Política de Privacidade, especialmente transferência de dados para o Google Ads.
- **Não foi possível testar pagamentos reais nem autenticação do Google dentro deste pacote**, pois não temos as credenciais do seu ambiente.
