# V12.6 — Teste de Google Ads sem compra

Esta versão mantém a V12.5 e acrescenta um diagnóstico administrativo (não cria cobranças, não modifica saldo e não registra conversões).

## Passo a passo
1. Publique todos os arquivos do ZIP no mesmo repositório GitHub do painel e espere `Success/Active` no Railway.
2. Mantenha as variáveis já configuradas, inclusive `GOOGLE_DM_ENABLED=1`.
3. Acesse `https://painel.contatozap.com/admin/google-ads/testar` estando logado na conta **ADMIN**.
4. Clique em **Testar conexão com Google**.
5. Veja o diagnóstico em tela. O teste obtém um access token com as credenciais no Railway e envia uma requisição Data Manager `events:ingest` com `validateOnly=true`. Usa um identificador sintético que **não** corresponde a um clique real. Nenhum evento é processado/importado.

## Interpretação do resultado
- `ok: true`, `oauth: OK`, `data_manager: REQUISICAO_VALIDADA`: OAuth, autorização e estrutura básica foram aceitos na validação. Não garante atribuição de conversões reais.
- `etapa: oauth`, `CREDENCIAIS_RECUSADAS`: verificar Client ID, Client Secret, Refresh Token e autorização OAuth.
- `oauth: OK`, `etapa: data_manager`, `http_status: 403`: conferir permissões, projeto Google Cloud/API e conta de anúncios.
- `oauth: OK`, `etapa: data_manager`, `http_status: 400`: a API recebeu a requisição, mas recusou algum campo; pode incluir o **identificador sintético de clique** usado no teste ou a configuração da ação de conversão. Não significa necessariamente que os pagamentos reais vão falhar.
- `etapa: configuracao`: conferir as variáveis de ambiente, ID de conta e ID da ação de conversão.

## Proteções
- Somente conta ADMIN pode abrir/executar; o clique executa POST protegido com CSRF.
- Usa exclusivamente `validateOnly=true`; nada é importado e não se cria pagamento.
- O resultado não mostra tokens, segredos nem identificadores publicitários.
- Não reinicializa nem altera a fila de conversões existente.
- Para concluir a verificação completa ainda é necessária **uma compra real com clique publicitário legítimo e consentimento adequado**, seguida de inspeção dos diagnósticos do Google Ads.
