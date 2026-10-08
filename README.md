# Consultas Contatos Zap — V12 Cadastro + Identidade Profissional

Baseada na V11. Mantém consultas, exportações, histórico local do agente, Bucket privado e pagamentos Asaas.

## Novidades
- cadastro público de clientes em `/cadastro`;
- campos: usuário, e-mail, telefone, senha e confirmação de senha;
- telefone salvo no padrão DDD+número (ex.: `77998334733`);
- telefone é o identificador do histórico de contatos enviados e não pode ser alterado pelo próprio cliente;
- usuário, telefone e e-mail são verificados para evitar duplicidade;
- aceite obrigatório dos Termos de Uso e da Política de Privacidade;
- tela `Minha conta` com telefone somente leitura;
- tela `Histórico` com até 100 pedidos recentes;
- cabeçalho profissional em páginas internas;
- rodapé institucional em todo o site;
- logo Contatos Zap incluído na pasta `static`;
- links institucionais para site oficial, Termos e Privacidade;
- CNPJ e e-mail de suporte no rodapé;
- texto do Asaas simplificado para usuários finais;
- correção da ordem de inicialização dos globals Jinja da V11.

## Dados institucionais padrão
- Site: `https://app.contatozap.com/`
- Termos: `https://app.contatozap.com/termos`
- Privacidade: `https://app.contatozap.com/privacidade`
- E-mail: `suporte@contatoszap.com`
- CNPJ: `49.710.958/0001-65`

Todos podem ser sobrescritos por variáveis Railway: `SALES_SITE_URL`, `TERMS_URL`, `PRIVACY_URL`, `SUPPORT_EMAIL`, `COMPANY_CNPJ`, `COPYRIGHT_YEAR`.

## Importante
O agente local V11 continua compatível. Esta V12 altera apenas o servidor/site.


## V12.2 — Google Tag Manager + conversão de cadastro

Esta versão mantém toda a V12.1 e adiciona:

- Google Tag Manager em todas as páginas da plataforma;
- container padrão: `GTM-NQTCRWB5`;
- variável opcional no Railway: `GTM_CONTAINER_ID`;
- nova página `/cadastro/sucesso`;
- evento `cadastro_concluido` enviado ao `dataLayer` somente quando o cadastro realmente termina com sucesso;
- proteção contra repetição: a flag é consumida na primeira abertura da página de sucesso, então atualizar a página não dispara o evento outra vez.

### Configuração no Google Tag Manager

No container `GTM-NQTCRWB5`, crie/use uma tag **Acompanhamento de conversões do Google Ads** com:

- Código de conversão: `718365247`
- Rótulo de conversão: `uBK8CO7N-oYdEL_ExdYC`

Acionador:

- Tipo: **Evento personalizado**
- Nome do evento: `cadastro_concluido`
- Disparar em: **Todos os eventos personalizados**

Depois publique o container no GTM.

Não é necessário colocar o snippet antigo `Chamou no ZAP 2025` dentro do Python. A plataforma apenas envia o evento ao GTM; o GTM cuida da conversão do Google Ads.


## V12.3 — Ajustes visuais e institucionais
- Rodapé da tela de login/cadastro integrado ao fundo azul-escuro (sem bloco branco).
- Ordem dos planos na página Adicionar saldo: Básico → Intermediário → Avançado.
- Site oficial: `https://app.contatozap.com/`
- Termos de Uso: `https://app.contatozap.com/termos`
- Política de Privacidade: `https://app.contatozap.com/privacidade`
- Valores legados dessas URLs no Railway são migrados automaticamente para os novos endereços.
- Toda a lógica atual de login, cadastro, GTM, Asaas, saldo, consultas, histórico e downloads foi preservada.

## V12.4 — Google Ads Data Manager / recargas Asaas
- Integração opcional e desligada por padrão para importar compras Pix pagas a partir de `PAYMENT_RECEIVED`.
- Registro e tentativas de envio pela tabela `google_ads_conversoes` (transação única por pagamento do Asaas).
- Captura de gclid/gbraid/wbraid entre `app.contatozap.com` e `painel.contatozap.com`.
- Status exclusivo para administrador: `/admin/google-ads/status`.
- Configuração completa em `INSTRUCOES_GOOGLE_ADS_V12_4.md`.
- Compatível com o agente local da versão anterior: **nenhuma alteração no agente**.

## V12.5 — Google Consent Mode v2 no painel

- Respeita `cz_consent` de `.contatozap.com` antes de carregar o GTM.
- Captura de IDs Google Ads só com consentimento; exclusão de fila pendente após recusa.
- Fallback com banner apenas se o visitante abrir diretamente o painel sem preferência de cookies.
- Veja `INSTRUCOES_CONSENTIMENTO_V12_5.md`.

## V12.6 — Teste administrativo sem compra

Novo endereço: `/admin/google-ads/testar` (somente ADMIN). Testa OAuth do Railway e valida o corpo da chamada da Data Manager API com `validateOnly=true`, **sem processar nenhuma compra ou conversão**. Instruções no arquivo `INSTRUCOES_TESTE_SEM_COMPRA_V12_6.md`.
