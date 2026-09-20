# Consulta Completas Web

Primeira versão online do sistema.

## Variáveis necessárias no Railway

- `DATABASE_URL` -> referência ao Postgres do projeto
- `ADMIN_USERNAME` -> ex.: `admin`
- `ADMIN_PASSWORD` -> escolha uma senha forte
- `SECRET_KEY` -> chave aleatória longa

## O que esta primeira versão faz

- cria automaticamente as tabelas do PostgreSQL
- cria/atualiza a conta ADMIN
- login individual
- painel administrativo
- criar clientes
- adicionar/remover saldo
- bloquear/desbloquear cliente
- alterar senha do cliente

A próxima etapa será conectar os filtros e o agente que roda no PC.
