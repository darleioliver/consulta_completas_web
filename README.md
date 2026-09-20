# Consulta Completas Web V3

V3 adiciona download seguro dos XLSX pelo site.

## Railway
Mantenha as variáveis já configuradas:
- DATABASE_URL
- ADMIN_USERNAME
- ADMIN_PASSWORD
- SECRET_KEY
- AGENT_API_KEY
- AWS_ENDPOINT_URL
- AWS_S3_BUCKET_NAME
- AWS_DEFAULT_REGION
- AWS_ACCESS_KEY_ID
- AWS_SECRET_ACCESS_KEY

O Bucket continua privado.

## Fluxo
1. Cliente cria pedido.
2. Agente local processa.
3. Servidor gera URL temporária de upload.
4. Agente envia o XLSX diretamente ao Bucket.
5. Pedido é concluído e recebe `arquivo_chave`.
6. O dono do pedido vê `Baixar Excel`.
7. Ao clicar, o servidor valida o usuário e gera URL temporária de download (15 min).

As bases brutas permanecem no PC.
