# Consultas Contatos Zap — Servidor V9

Esta versão parte da V7 visual e adiciona integração com o histórico por cliente usado pelo Agente V9.

## Novidades
- campo **Telefone do cliente** obrigatório na criação de novos clientes;
- telefone único por cliente;
- clientes antigos sem telefone aparecem como **SEM TELEFONE** no Admin;
- botão no Admin para cadastrar/alterar o telefone de clientes existentes;
- cada novo pedido grava uma cópia do telefone do cliente no próprio pedido;
- a API do agente envia `telefone_cliente` junto do pedido;
- endpoint seguro de retomada para o Agente V9 finalizar pedidos interrompidos sem gerar outro conjunto de contatos;
- visual e funcionalidades da V7 foram preservados;
- alerta de pré-contagem mantido no amarelo discreto solicitado.

## Depois do deploy
Entre em **Administração** e preencha o telefone de todos os clientes antigos antes que eles façam novos pedidos.

Formato recomendado: `77998334733` (DDD + número, sem +55). Se digitar +55, o servidor normaliza automaticamente.

Não há nova variável obrigatória no Railway para esta V9.
