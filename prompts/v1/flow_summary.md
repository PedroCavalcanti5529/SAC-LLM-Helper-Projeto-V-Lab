# Tarefa: resumo do fluxo de atendimento

Resuma o fluxo de decisão para resolver este atendimento.

Responda em JSON neste formato (árvore de decisão; cada `yes`/`no` é `{"next": "<id do nó>"}` ou `{"action": "...", "ref": "<id da base ou null>"}`):
{"title": "...", "start": "D1", "nodes": [{"id": "D1", "question": "...?", "yes": {"next": "D2"}, "no": {"action": "...", "ref": null}}]}
