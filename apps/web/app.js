const statusEl = document.querySelector("#api-status");
const refreshButton = document.querySelector("#refresh-button");
const importForm = document.querySelector("#import-form");
const importMessage = document.querySelector("#import-message");
const telegramTestButton = document.querySelector("#telegram-test-button");
const telegramSignalButton = document.querySelector("#telegram-signal-button");
const telegramCheckButton = document.querySelector("#telegram-check-button");
const telegramMessage = document.querySelector("#telegram-message");

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

async function postJson(path, payload) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || `Falha ao enviar ${path}`);
  }
  return data;
}

function renderSignal(signal) {
  const sideEl = document.querySelector("#signal-side");
  sideEl.textContent = signal.side || "--";
  sideEl.className = `side-${String(signal.side || "none").toLowerCase()}`;
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
  document.querySelector("#metric-ml-score").textContent = signal.mlScore === null || signal.mlScore === undefined
    ? "--"
    : formatPercent(signal.mlScore);
}

function renderMlStatus(model) {
  const status = model.trained
    ? `${model.samples} amostras | treino ${formatPercent(model.trainAccuracy)}`
    : `${model.samples} amostras | precisa de mais dados`;
  document.querySelector("#metric-ml-status").textContent = status;
}

function renderValidation(validation) {
  document.querySelector("#validation-base-pips").textContent = `${Number(validation.base.totalPips || 0).toFixed(1)} pips`;
  document.querySelector("#validation-ai-pips").textContent = `${Number(validation.aiFiltered.totalPips || 0).toFixed(1)} pips`;
  document.querySelector("#validation-delta-pips").textContent = `${Number(validation.delta.totalPips || 0).toFixed(1)} pips`;
  document.querySelector("#validation-base-detail").textContent =
    `${validation.base.totalTrades} trades | ${formatPercent(validation.base.winRate)} acerto`;
  document.querySelector("#validation-ai-detail").textContent =
    `${validation.aiFiltered.totalTrades} trades | ${formatPercent(validation.aiFiltered.winRate)} acerto`;
  document.querySelector("#validation-delta-detail").textContent =
    `${validation.delta.trades} trades | DD ${Number(validation.delta.drawdownPips || 0).toFixed(1)}`;
}

function renderTelegramStatus(status) {
  const text = status.configured
    ? "Telegram configurado no ambiente."
    : "Configure TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID no Railway.";
  document.querySelector("#telegram-status").textContent = text;
  telegramTestButton.disabled = !status.configured;
  telegramSignalButton.disabled = !status.configured;
  telegramCheckButton.disabled = !status.configured;
}

function renderDatasets(payload) {
  const list = document.querySelector("#datasets-list");
  const datasets = Array.isArray(payload.datasets) ? payload.datasets : [];
  if (!datasets.length) {
    list.innerHTML = "<p>Nenhum dataset encontrado.</p>";
    return;
  }

  list.innerHTML = datasets
    .map((dataset) => `
      <button class="dataset-button ${dataset.active ? "active" : ""}" data-id="${dataset.id}" type="button">
        <span>${dataset.symbol} ${dataset.timeframe}</span>
        <small>${dataset.candles} candles</small>
      </button>
    `)
    .join("");

  list.querySelectorAll(".dataset-button").forEach((button) => {
    button.addEventListener("click", async () => {
      await postJson("/datasets/select", { id: button.dataset.id });
      await loadDashboard();
    });
  });
}

function renderBacktest(backtest) {
  document.querySelector("#metric-profit").textContent = `${Number(backtest.totalPips || 0).toFixed(1)}`;
  document.querySelector("#metric-winrate").textContent = formatPercent(backtest.winRate);
  document.querySelector("#metric-payoff").textContent = Number(backtest.payoff || 0).toFixed(2);
  document.querySelector("#metric-drawdown").textContent = `${Number(backtest.maxDrawdownPips || 0).toFixed(1)}`;
  document.querySelector("#metric-trades").textContent = Number(backtest.totalTrades || 0);
  document.querySelector("#metric-profit-factor").textContent = Number(backtest.profitFactor || 0).toFixed(2);

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
    const [signal, backtest, datasets, model, validation, telegram] = await Promise.all([
      getJson("/signals/latest"),
      getJson("/backtest"),
      getJson("/datasets"),
      getJson("/ml/status"),
      getJson("/ml/validation"),
      getJson("/alerts/telegram/status"),
    ]);
    renderSignal(signal);
    renderBacktest(backtest);
    renderDatasets(datasets);
    renderMlStatus(model);
    renderValidation(validation);
    renderTelegramStatus(telegram);
    statusEl.textContent = "Online";
  } catch (error) {
    statusEl.textContent = "Erro na API";
    console.error(error);
  }
}

async function sendTelegram(path, successMessage) {
  telegramMessage.textContent = "Enviando...";
  try {
    const response = await postJson(path, {});
    telegramMessage.textContent = response.sent === false
      ? response.reason
      : successMessage;
  } catch (error) {
    telegramMessage.textContent = error.message;
  }
}

async function handleImport(event) {
  event.preventDefault();
  const file = document.querySelector("#csv-input").files[0];
  if (!file) {
    importMessage.textContent = "Selecione um arquivo CSV.";
    return;
  }

  importMessage.textContent = "Importando...";
  try {
    await postJson("/datasets/import", {
      symbol: document.querySelector("#symbol-input").value,
      timeframe: document.querySelector("#timeframe-input").value,
      content: await file.text(),
    });
    importForm.reset();
    document.querySelector("#symbol-input").value = "EURUSD";
    importMessage.textContent = "CSV importado e ativado.";
    await loadDashboard();
  } catch (error) {
    importMessage.textContent = error.message;
  }
}

refreshButton.addEventListener("click", loadDashboard);
importForm.addEventListener("submit", handleImport);
telegramTestButton.addEventListener("click", () => sendTelegram("/alerts/telegram/test", "Mensagem de teste enviada."));
telegramSignalButton.addEventListener("click", () => sendTelegram("/alerts/telegram/latest-signal", "Sinal enviado ao Telegram."));
telegramCheckButton.addEventListener("click", () => sendTelegram("/alerts/telegram/check-latest", "Alerta enviado ao Telegram."));
loadDashboard();
