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
- Site: `https://contatozap.com`
- Termos: `https://contatozap.com/termos_de_uso.html`
- Privacidade: `https://contatozap.com/privacy.html`
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
