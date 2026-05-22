const statusEl = document.querySelector("#api-status");
const refreshButton = document.querySelector("#refresh-button");

const formatNumber = (value, digits = 5) => {
  if (value === null || value === undefined) return "--";
  return Number(value).toFixed(digits);
};

const formatPercent = (value) => `${Math.round(Number(value || 0) * 100)}%`;

async function getJson(path) {
  const response = await fetch(path);
  if (!response.ok) {
    throw new Error(`Falha ao carregar ${path}`);
  }
  return response.json();
}

function renderSignal(signal) {
  document.querySelector("#signal-side").textContent = signal.side || "--";
  document.querySelector("#signal-symbol").textContent = signal.symbol || "--";
  document.querySelector("#signal-timeframe").textContent = signal.timeframe || "--";
  document.querySelector("#signal-confidence").textContent = formatPercent(signal.confidence);
  document.querySelector("#signal-entry").textContent = formatNumber(signal.entry);
  document.querySelector("#signal-stop").textContent = formatNumber(signal.stopLoss);
  document.querySelector("#signal-targets").textContent = Array.isArray(signal.takeProfit)
    ? signal.takeProfit.map((target) => formatNumber(target)).join(" / ")
    : "--";
  document.querySelector("#signal-reason").textContent = Array.isArray(signal.reason)
    ? signal.reason.join(" | ")
    : "Sem motivo informado.";
}

function renderBacktest(backtest) {
  document.querySelector("#metric-profit").textContent = `${Number(backtest.totalPips || 0).toFixed(1)}`;
  document.querySelector("#metric-winrate").textContent = formatPercent(backtest.winRate);
  document.querySelector("#metric-payoff").textContent = Number(backtest.payoff || 0).toFixed(2);
  document.querySelector("#metric-drawdown").textContent = `${Number(backtest.maxDrawdownPips || 0).toFixed(1)}`;

  const tradesBody = document.querySelector("#trades-body");
  const trades = Array.isArray(backtest.trades) ? backtest.trades : [];
  if (!trades.length) {
    tradesBody.innerHTML = '<tr><td colspan="5">Nenhum trade simulado neste periodo.</td></tr>';
    return;
  }

  tradesBody.innerHTML = trades
    .slice(-10)
    .reverse()
    .map((trade) => {
      const resultClass = Number(trade.resultPips) >= 0 ? "positive" : "negative";
      return `
        <tr>
          <td>${trade.entryTime}</td>
          <td>${trade.side}</td>
          <td>${formatNumber(trade.entry)}</td>
          <td>${formatNumber(trade.exit)}</td>
          <td class="${resultClass}">${Number(trade.resultPips).toFixed(1)} pips</td>
        </tr>
      `;
    })
    .join("");
}

async function loadDashboard() {
  statusEl.textContent = "Atualizando";
  try {
    const [signal, backtest] = await Promise.all([
      getJson("/signals/latest"),
      getJson("/backtest"),
    ]);
    renderSignal(signal);
    renderBacktest(backtest);
    statusEl.textContent = "Online";
  } catch (error) {
    statusEl.textContent = "Erro na API";
    console.error(error);
  }
}

refreshButton.addEventListener("click", loadDashboard);
loadDashboard();
