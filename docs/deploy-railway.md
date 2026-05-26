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
- `/ai/status`: status da chave OpenAI e modelo configurado.
- `/ai/explain-latest-signal`: gera uma leitura curta do sinal atual.
- `/jobs/status`: mostra o ultimo resultado do robo automatico.
- `/jobs/check-alerts`: job protegido para cron de alertas.
- `/jobs/twelve-data-scan`: baixa candles da Twelve Data, analisa e alerta Telegram.
- `/market/candles`: recebe candles de MT5/API externa.
- `/market/forex/status`: mostra se o Forex esta aberto ou fechado.
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
- `TELEGRAM_MIN_CONFIDENCE` opcional, padrao `0.60`
- `TELEGRAM_SEND_NO_SIGNAL_STATUS` opcional, padrao `false`
- `TELEGRAM_STATUS_EVERY_MINUTES` opcional, padrao `240`
- `ALERT_JOB_SECRET` para proteger `/jobs/check-alerts`
- `MARKET_INGEST_SECRET` para proteger `/market/candles`
- `ALPHA_VANTAGE_API_KEY` para atualizar candles via Alpha Vantage
- `TWELVE_DATA_API_KEY` para atualizar candles via Twelve Data
- `OPENAI_API_KEY` para explicar sinais com IA
- `AI_MODEL` opcional, padrao `gpt-4.1-nano`
- `AI_TELEGRAM_EXPLANATION` opcional, padrao `true`
- `WATCH_SYMBOL` opcional, padrao `EURUSD`
- `WATCH_TIMEFRAME` opcional, padrao `M5`
- `WATCH_OUTPUTSIZE` opcional, padrao `120`
- `SIGNAL_LOOKBACK_CANDLES` opcional, padrao `4`
- `FOREX_MARKET_GUARD` opcional, padrao `true`
- `FOREX_FRIDAY_CLOSE_HOUR` opcional, padrao `18`
- `FOREX_SUNDAY_OPEN_HOUR` opcional, padrao `18`
- `MARKET_TIMEZONE` opcional, padrao `America/Sao_Paulo`

## Job Automatico

Para monitorar o mercado, configure um cron externo chamando:

```text
POST /jobs/twelve-data-scan
Header: X-Job-Secret: valor_do_ALERT_JOB_SECRET
```

Sugestao de intervalo:

- `WATCH_TIMEFRAME=M5`: chamar a cada 5 minutos.
- `WATCH_TIMEFRAME=M15`: chamar a cada 15 minutos.
- `WATCH_TIMEFRAME=H1`: chamar a cada 1 hora.

O job usa Twelve Data como fonte, salva os candles novos, recalcula o sinal e envia Telegram apenas quando o sinal for operacional, tiver confianca minima e ainda nao tiver sido enviado.

Por padrao, o job automatico nao busca candles durante o fim de semana do Forex: sexta a partir de 18h, sabado inteiro e domingo antes de 18h no timezone configurado. Para teste manual, envie `"force": true` no JSON da chamada.
