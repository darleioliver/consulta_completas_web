# V12.5 — Consentimento compartilhado app + painel

A página de vendas `app.contatozap.com` já tem Consent Mode v2 implementado. Este pacote atualiza SOMENTE o painel `painel.contatozap.com`.

- O painel lê `cz_consent` do cookie `.contatozap.com` antes do GTM `GTM-NQTCRWB5`.
- Se `granted`: Consent Mode v2 com valores concedidos. Se `denied` ou ausente: todos os quatro sinais inicialmente negados.
- Captura de `gclid` / `gbraid` / `wbraid` só acontece quando `cz_consent=granted` — conferido no navegador E no servidor.
- Se o usuário acessar o painel diretamente sem preferência anterior, ele recebe um banner simples. Se já aceitou/recusou na página de vendas, nenhum segundo banner aparece.
- Ao revogar o consentimento, a próxima visita autenticada ao painel limpa os identificadores publicitários armazenados e cancela o envio de conversões ainda pendentes. Envios já concluídos não podem ser desfeitos.
- Se o usuário revogar consentimento somente na página de vendas, o painel toma conhecimento na próxima requisição ao painel; o cookie, por si só, não avisa o servidor em tempo real.
- A sincronização inicial pode adicionar uma breve consulta ao PostgreSQL por sessão.

## Importante: NÃO duplique a captura no GTM

Como a página de vendas já captura cliques no próprio código respeitando consentimento, **não publique** o HTML antigo `CAPTURA_CLIQUE_PAGINA_VENDAS.html` como tag independente em `Initialization - All Pages`. Se já publicou uma tag com esse script antigo sem bloqueio por consentimento, **pause-a**. A versão V12.5 controla a captura dentro do painel.

## Teste

1. Teste anônimo após limpar cookies: abra `painel.contatozap.com/cadastro`; painel deve exibir banner. Antes do aceite: dataLayer deve conter consent default denied.
2. Aceite no painel: cookie `cz_consent=granted`, Domain `.contatozap.com` visível em F12 > Application > Cookies; após reload, GTM recebe consent default granted.
3. Aceite na página de vendas e abra painel: não aparece segundo banner.
4. Recuse na página de vendas e abra painel: não aparece segundo banner, mas GTM recebe consent default denied.
5. **Apenas em ambiente de teste**: com aceite e URL `https://painel.contatozap.com/cadastro?gclid=CjTESTE1234567`, deve existir cookie `cz_ads_gclid`; após recusa, o cookie de anúncio deve ser apagado. NÃO envie conversões com GCLID fictício.
6. Na tela de cadastro, o evento `cadastro_concluido` permanece o mesmo. Verifique no GTM Preview se a tag de cadastro e as permissões de consentimento estão corretas.

## Configuração de servidor

Mantenha `GOOGLE_DM_ENABLED=0` durante os testes. A V12.5 não precisa de novas variáveis de ambiente. A importação de conversões reais só começará após configurar OAuth, IDs e mudar para `1`, conforme `INSTRUCOES_GOOGLE_ADS_V12_4.md`.

## Proteção de dados

Esse ajuste é técnico; revise os textos de privacidade/cookies e as bases legais com profissional habilitado. A escolha compartilhada entre subdomínios depende de cookies aceitos pelo navegador. Navegação anônima, bloqueio de cookies e recusa impedem ou limitam a atribuição de anúncios.
