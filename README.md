# Consulta Completas Web V5 — Contagem + Histórico

Mantém o download privado via Railway Bucket e adiciona:

- a tela inicial NÃO mostra milhões de contatos sem filtro;
- ao selecionar UF, cidade, sexo, CBO, renda, idade ou modo Atualizados 2026, o site solicita a contagem ao agente local;
- a contagem é feita nos SQLite locais, sem enviar as bases brutas ao Railway;
- Bairro e DDD continuam sendo filtros de exportação e não entram na pré-contagem;
- resultados idênticos são reaproveitados por 10 minutos;
- pedidos de exportação têm prioridade no agente;
- no histórico da página inicial, pedidos concluídos exibem botão `📥 Baixar`;
- clientes podem voltar à tela inicial e baixar um pedido concluído depois.

Publicação:
1. publique este ZIP no GitHub/Railway;
2. aguarde o deploy;
3. depois substitua o agente local pela V5 e execute INICIAR_AGENTE_PC_V5.bat;
4. preserve o config_agente.json atual.
