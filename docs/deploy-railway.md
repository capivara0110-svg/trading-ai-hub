# Deploy no Railway

Este projeto esta preparado para subir como um servico web Python no Railway.

## Arquivos de Deploy

- `railway.json`: comando de start, healthcheck e politica de restart.
- `Procfile`: comando alternativo de start.
- `.python-version`: fixa Python 3.12.
- `requirements.txt`: sem dependencias externas por enquanto.

## Comando de Start

```text
python -m apps.api.main
```

## Healthcheck

```text
/health
```

## Passo a Passo

1. Coloque a pasta `trading-ai-hub` em um repositorio GitHub.
2. No Railway, crie um novo projeto.
3. Escolha deploy a partir do GitHub.
4. Se o repositorio tambem tiver o Igrejahub, configure o root directory como `trading-ai-hub`.
5. Confirme o start command `python -m apps.api.main`.
6. Depois do deploy, abra a URL publica do Railway.

## Rotas

- `/`: painel web.
- `/health`: status da API, versao e dataset atual.
- `/signals/latest`: ultimo sinal calculado.
- `/backtest`: resultado do backtest atual.

## Observacao Importante

O Railway injeta a variavel `PORT` automaticamente. A API ja usa essa porta e escuta em `0.0.0.0`, que e necessario para funcionar fora da maquina local.
