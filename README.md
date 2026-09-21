# Consultas Contatos Zap — V7

Novidades desta versão:
- marca/título alterados para **Consultas Contatos Zap**;
- botão **Adicionar saldo** no painel, abrindo o WhatsApp;
- CBO, renda e idade ficam ocultos em **Filtros avançados**;
- aviso de que filtros avançados podem reduzir significativamente a quantidade de números ativos;
- ao ativar **Atualizados 2026**, CBO, renda e idade são limpos e aparece um aviso;
- removido o texto `Selecionar` das listas; itens já marcados mostram apenas `✓`;
- tecla Enter não envia mais o formulário acidentalmente;
- campos pesquisáveis usam `enterkeyhint=next` para melhorar o teclado no celular;
- mantida a rolagem automática até `Contatos encontrados` somente depois que a contagem conclui;
- todo o restante da V6 (Bucket, histórico, download, pré-contagem manual, CEP, nome do arquivo etc.) foi preservado.

## Nova variável do Railway para o WhatsApp

Adicione em `consulta_completas_web > Variables`:

`WHATSAPP_NUMBER`

Use somente números, incluindo país e DDD. Exemplo de formato:

`5577999999999`

Não use `+`, espaços ou traços.

Alternativamente, você pode criar `WHATSAPP_SALDO_URL` com uma URL completa do WhatsApp; ela terá prioridade sobre `WHATSAPP_NUMBER`.

O agente local V6 NÃO precisa ser alterado.
