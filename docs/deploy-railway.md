# Deploy no Railway

Este projeto esta preparado para subir como um servico web Python no Railway.

## Arquivos de Deploy

- `railway.json`: comando de start, healthcheck e politica de restart.
- `Procfile`: comando alternativo de start.
- `.python-version`: fixa Python 3.12.
- `requirements.txt`: sem dependencias externas por enquanto.

## Comando de Start

```text
python main.py
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
5. Confirme o start command `python main.py`.
6. Depois do deploy, abra a URL publica do Railway.

## Rotas

- `/`: painel web.
- `/health`: status da API, versao e dataset atual.
- `/datasets`: historicos cadastrados.
- `/signals/latest`: ultimo sinal calculado.
- `/backtest`: resultado do backtest atual.
- `/ml/status`: status do treino de machine learning.
- `/ml/validation`: comparacao fora da amostra entre regra-base e filtro de IA.
- `/alerts/telegram/status`: status das variaveis Telegram.
- `/alerts/telegram/test`: envia mensagem de teste.
- `/alerts/telegram/latest-signal`: envia o sinal atual.
- `/alerts/telegram/check-latest`: envia apenas sinal valido e ainda nao enviado.
- `/jobs/check-alerts`: job protegido para cron de alertas.
- `/market/candles`: recebe candles de MT5/API externa.
- `/market/alpha-vantage/status`: status da chave Alpha Vantage.
- `/market/alpha-vantage/refresh`: baixa candles Forex da Alpha Vantage.
- `/market/twelve-data/status`: status da chave Twelve Data.
- `/market/twelve-data/refresh`: baixa candles Forex da Twelve Data.

## Observacao Importante

O Railway injeta a variavel `PORT` automaticamente. A API ja usa essa porta e escuta em `0.0.0.0`, que e necessario para funcionar fora da maquina local.

Uploads feitos pelo painel ficam em `data/uploads`. No Railway, esse armazenamento local pode ser perdido em redeploy. Para produto real, a proxima etapa e trocar isso por banco ou storage persistente, como Postgres ou volume persistente.

## Variaveis Telegram

Para alertas em grupo/canal:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `TELEGRAM_MIN_CONFIDENCE` opcional, padrao `0.70`
- `ALERT_JOB_SECRET` para proteger `/jobs/check-alerts`
- `MARKET_INGEST_SECRET` para proteger `/market/candles`
- `ALPHA_VANTAGE_API_KEY` para atualizar candles via Alpha Vantage
- `TWELVE_DATA_API_KEY` para atualizar candles via Twelve Data
