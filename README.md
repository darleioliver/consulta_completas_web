# Consulta Completas Web — V2

Versão com usuários, saldo, filtros online e API do agente local.

## Variáveis do Railway

- `DATABASE_URL` — referência ao Postgres do projeto
- `ADMIN_USERNAME` — usuário administrador
- `ADMIN_PASSWORD` — senha do administrador
- `SECRET_KEY` — chave longa e aleatória da sessão
- `AGENT_API_KEY` — chave longa e aleatória compartilhada somente com o agente do PC

## Fluxo

1. Cliente entra no site e cria um pedido.
2. O pedido fica `AGUARDANDO` e reserva a quantidade do saldo.
3. O agente do PC busca o pedido e muda para `PROCESSANDO`.
4. A exportação roda nas bases locais.
5. Quando termina, o servidor desconta somente a quantidade realmente entregue.
6. Nesta V2 o Excel continua no PC. O Bucket/download online entra na próxima etapa.
