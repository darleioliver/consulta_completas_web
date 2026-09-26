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
