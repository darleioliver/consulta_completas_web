# Consultas Contatos Zap — V10 Asaas

Base: V9. O agente local V9 não muda.

## Novidades
- botão Adicionar saldo abre uma página interna;
- criação de Link de Pagamento PIX no Asaas;
- Webhook `POST /webhook/asaas`;
- validação do header `asaas-access-token`;
- idempotência por ID do evento e por ID do pagamento;
- `PAYMENT_CONFIRMED` apenas atualiza o status;
- saldo é creditado somente em `PAYMENT_RECEIVED`;
- valor recebido deve coincidir com o pacote;
- recargas entram no histórico de movimentações como `CREDITO_ASAAS`.

## Variáveis Railway
Já configuradas:
- `ASAAS_API_KEY`
- `ASAAS_BASE_URL=https://api-sandbox.asaas.com/v3`
- `ASAAS_ENVIRONMENT=sandbox`

Adicionar agora:
- `ASAAS_WEBHOOK_TOKEN` = exatamente o token de autenticação do Webhook no Asaas.

Opcional:
- `ASAAS_USER_AGENT`
- `ASAAS_RECARGA_PACOTES_JSON`

Pacotes padrão:
- 5.000 = R$ 39,00
- 10.000 = R$ 78,00
- 25.000 = R$ 195,00
- 50.000 = R$ 390,00

Exemplo para personalizar:
`[{"creditos":5000,"valor":39},{"creditos":15000,"valor":110}]`

## Webhook Sandbox
URL:
`https://SEU-DOMINIO-RAILWAY/webhook/asaas`

No Asaas:
- ativo: sim
- versão: v3
- fila: ativa
- tipo: Sequencial
- eventos: `PAYMENT_CONFIRMED` e `PAYMENT_RECEIVED`

O token do Asaas precisa ser idêntico ao `ASAAS_WEBHOOK_TOKEN` no Railway.


## V11 — Planos e privacidade visual
- novos pacotes Básico, Intermediário e Avançado;
- botão Suporte via WhatsApp;
- mensagens de progresso públicas não exibem nomes de arquivos, bases, pastas, estados lidos ou referências ao PC;
- aviso duplicado de Bairro/DDD/CEP removido;
- mantém o aviso dentro da pré-contagem;
- inclui `dueDateLimitDays=2` no Link de Pagamento Asaas.
