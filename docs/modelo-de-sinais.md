# Modelo de Sinais

## Entrada

Candles OHLCV:

- `time`
- `open`
- `high`
- `low`
- `close`
- `volume`

Contexto opcional:

- ativo
- timeframe
- sessão
- spread
- notícias/eventos

## Features Iniciais

- Retorno dos últimos candles.
- Distância do preço para médias móveis.
- Inclinação das médias.
- RSI.
- ATR.
- Tamanho do corpo do candle.
- Pavio superior e inferior.
- Range atual contra range médio.
- Máxima/mínima dos últimos N candles.
- Hora do dia.

## Rótulo para Treino

Exemplo simples:

- `BUY_WIN`: após a entrada, preço atinge alvo antes do stop.
- `SELL_WIN`: após a entrada vendida, preço atinge alvo antes do stop.
- `NO_TRADE`: não há vantagem clara ou o risco/retorno é ruim.

O rótulo deve ser calculado olhando apenas o futuro depois do candle de entrada, nunca usando informação que o modelo teria antes da decisão.

## Saída do Modelo

O modelo deve retornar:

- direção: compra, venda ou sem operação
- probabilidade
- setup detectado
- stop sugerido
- alvos
- motivo em linguagem simples

## Modelo Atual

A primeira versao usa um classificador leve por similaridade:

- gera features de tendencia, momentum, volatilidade, forca do candle e retorno recente
- rotula exemplos historicos pelo comportamento dos proximos candles
- calcula centroides de exemplos vencedores e perdedores
- pontua o candle atual pela proximidade com exemplos vencedores

Esse modelo e apenas a primeira camada de IA. A proxima evolucao deve usar scikit-learn com validacao fora da amostra.

## Regras de Segurança

- Ignorar sinal com confiança abaixo do mínimo configurado.
- Ignorar sinal se o spread estiver alto.
- Ignorar sinal se o stop for maior que o risco máximo.
- Limitar operações por dia.
- Parar após perda diária máxima.
- Parar após sequência de perdas.

## Métricas

- Win rate.
- Payoff médio.
- Expectativa por trade.
- Drawdown máximo.
- Profit factor.
- Quantidade de trades.
- Resultado por horário.
- Resultado por ativo/timeframe.
