const statusEl = document.querySelector("#api-status");
const apiBaseInput = document.querySelector("#api-base-input");
const apiSaveButton = document.querySelector("#api-save-button");
const apiConfigMessage = document.querySelector("#api-config-message");
const refreshButton = document.querySelector("#refresh-button");
const importForm = document.querySelector("#import-form");
const importMessage = document.querySelector("#import-message");
const telegramTestButton = document.querySelector("#telegram-test-button");
const telegramSignalButton = document.querySelector("#telegram-signal-button");
const telegramCheckButton = document.querySelector("#telegram-check-button");
const telegramMessage = document.querySelector("#telegram-message");
const alphaForm = document.querySelector("#alpha-form");
const alphaMessage = document.querySelector("#alpha-message");
const alphaRefreshButton = document.querySelector("#alpha-refresh-button");
const twelveForm = document.querySelector("#twelve-form");
const twelveMessage = document.querySelector("#twelve-message");
const twelveRefreshButton = document.querySelector("#twelve-refresh-button");
const aiExplainButton = document.querySelector("#ai-explain-button");
const aiMessage = document.querySelector("#ai-message");
const aiOutput = document.querySelector("#ai-output");

const API_STORAGE_KEY = "tradingAiApiBaseUrl";
const initialApiParam = new URLSearchParams(window.location.search).get("api");
let apiBaseUrl = normalizeApiBase(
  initialApiParam || localStorage.getItem(API_STORAGE_KEY) || window.TRADING_AI_API_BASE_URL || ""
);

if (initialApiParam) {
  localStorage.setItem(API_STORAGE_KEY, apiBaseUrl);
}
apiBaseInput.value = apiBaseUrl;

const formatNumber = (value, digits = 5) => {
  if (value === null || value === undefined) return "--";
  return Number(value).toFixed(digits);
};

const formatPercent = (value) => `${Math.round(Number(value || 0) * 100)}%`;

const formatDateTime = (value) => {
  if (!value) return "--";
  return new Date(value).toLocaleString("pt-BR", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
};

function normalizeApiBase(value) {
  const clean = String(value || "").trim().replace(/\/+$/, "");
  if (!clean || clean.startsWith("/") || clean.startsWith("http://") || clean.startsWith("https://")) {
    return clean;
  }
  return `https://${clean}`;
}

function needsExternalApi() {
  return window.location.hostname.includes("netlify.app") || window.location.hostname.includes("netlify");
}

function apiUrl(path) {
  if (!apiBaseUrl && needsExternalApi()) {
    throw new Error("Informe a URL da API no Railway para carregar o painel no Netlify.");
  }
  return apiBaseUrl ? `${apiBaseUrl}${path}` : path;
}

async function getJson(path) {
  const response = await fetch(apiUrl(path));
  if (!response.ok) {
    throw new Error(`Falha ao carregar ${path}`);
  }
  if (!String(response.headers.get("Content-Type") || "").includes("application/json")) {
    throw new Error("A API retornou HTML. Configure a URL publica do Railway no campo API Railway.");
  }
  return response.json();
}

async function postJson(path, payload) {
  const response = await fetch(apiUrl(path), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!String(response.headers.get("Content-Type") || "").includes("application/json")) {
    throw new Error("A API retornou HTML. Configure a URL publica do Railway no campo API Railway.");
  }
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || `Falha ao enviar ${path}`);
  }
  return data;
}

function saveApiBaseUrl() {
  apiBaseUrl = normalizeApiBase(apiBaseInput.value);
  if (apiBaseUrl) {
    localStorage.setItem(API_STORAGE_KEY, apiBaseUrl);
    apiConfigMessage.textContent = "API configurada. Atualizando painel...";
  } else {
    localStorage.removeItem(API_STORAGE_KEY);
    apiConfigMessage.textContent = "Usando API no mesmo dominio do painel.";
  }
  loadDashboard();
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

function renderAlphaStatus(status) {
  document.querySelector("#alpha-status").textContent = status.configured
    ? "Alpha Vantage configurada no ambiente."
    : "Configure ALPHA_VANTAGE_API_KEY no Railway.";
  alphaRefreshButton.disabled = !status.configured;
}

function renderTwelveStatus(status) {
  document.querySelector("#twelve-status").textContent = status.configured
    ? "Twelve Data configurada no ambiente."
    : "Configure TWELVE_DATA_API_KEY no Railway.";
  twelveRefreshButton.disabled = !status.configured;
}

function renderAiStatus(status) {
  document.querySelector("#ai-status").textContent = status.configured
    ? `OpenAI configurada | modelo ${status.model}`
    : "Configure OPENAI_API_KEY no Railway.";
  aiExplainButton.disabled = !status.configured;
}

function renderMarketStatus(status) {
  document.querySelector("#metric-market-status").textContent = status.isOpen ? "Aberto" : "Fechado";
  document.querySelector("#metric-market-status").className = status.isOpen ? "positive" : "warning";
  document.querySelector("#metric-market-detail").textContent = status.isOpen
    ? `Fecha ${formatDateTime(status.nextClose)}`
    : `Abre ${formatDateTime(status.nextOpen)}`;
}

function renderJobStatus(status) {
  const result = status.result || {};
  const alert = result.alert || result;
  const sent = alert.sent === true;
  const skipped = result.skipped === true;
  document.querySelector("#metric-job-status").textContent = sent ? "Enviado" : skipped ? "Pausado" : "Rodando";
  document.querySelector("#metric-job-status").className = sent ? "positive" : skipped ? "warning" : "";
  document.querySelector("#metric-job-detail").textContent =
    alert.reason || result.reason || (status.lastRunAt ? `Ultimo ${formatDateTime(status.lastRunAt)}` : "Sem execucao");
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
    const [signal, backtest, datasets, model, validation, telegram, alpha, twelve, ai, market, job] = await Promise.all([
      getJson("/signals/latest"),
      getJson("/backtest"),
      getJson("/datasets"),
      getJson("/ml/status"),
      getJson("/ml/validation"),
      getJson("/alerts/telegram/status"),
      getJson("/market/alpha-vantage/status"),
      getJson("/market/twelve-data/status"),
      getJson("/ai/status"),
      getJson("/market/forex/status"),
      getJson("/jobs/status"),
    ]);
    renderSignal(signal);
    renderBacktest(backtest);
    renderDatasets(datasets);
    renderMlStatus(model);
    renderValidation(validation);
    renderTelegramStatus(telegram);
    renderAlphaStatus(alpha);
    renderTwelveStatus(twelve);
    renderAiStatus(ai);
    renderMarketStatus(market);
    renderJobStatus(job);
    statusEl.textContent = "Online";
  } catch (error) {
    statusEl.textContent = needsExternalApi() && !apiBaseUrl ? "Configurar API" : "Erro na API";
    apiConfigMessage.textContent = error.message;
    console.error(error);
  }
}

async function handleAiExplain() {
  aiMessage.textContent = "Gerando leitura da IA...";
  aiOutput.value = "";
  try {
    const response = await postJson("/ai/explain-latest-signal", {});
    aiOutput.value = response.text || "";
    aiMessage.textContent = `Explicacao gerada com ${response.model}.`;
  } catch (error) {
    aiMessage.textContent = error.message;
  }
}

async function handleTwelveRefresh(event) {
  event.preventDefault();
  twelveMessage.textContent = "Atualizando candles...";
  try {
    await postJson("/market/twelve-data/refresh", {
      symbol: document.querySelector("#twelve-symbol-input").value,
      timeframe: document.querySelector("#twelve-timeframe-input").value,
      outputsize: Number(document.querySelector("#twelve-outputsize-input").value || 100),
      alert: document.querySelector("#twelve-alert-input").checked,
    });
    twelveMessage.textContent = "Candles atualizados.";
    await loadDashboard();
  } catch (error) {
    twelveMessage.textContent = error.message;
  }
}

async function handleAlphaRefresh(event) {
  event.preventDefault();
  alphaMessage.textContent = "Atualizando candles...";
  try {
    await postJson("/market/alpha-vantage/refresh", {
      symbol: document.querySelector("#alpha-symbol-input").value,
      timeframe: document.querySelector("#alpha-timeframe-input").value,
      alert: document.querySelector("#alpha-alert-input").checked,
    });
    alphaMessage.textContent = "Candles atualizados.";
    await loadDashboard();
  } catch (error) {
    alphaMessage.textContent = error.message;
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
apiSaveButton.addEventListener("click", saveApiBaseUrl);
importForm.addEventListener("submit", handleImport);
alphaForm.addEventListener("submit", handleAlphaRefresh);
twelveForm.addEventListener("submit", handleTwelveRefresh);
aiExplainButton.addEventListener("click", handleAiExplain);
telegramTestButton.addEventListener("click", () => sendTelegram("/alerts/telegram/test", "Mensagem de teste enviada."));
telegramSignalButton.addEventListener("click", () => sendTelegram("/alerts/telegram/latest-signal", "Sinal enviado ao Telegram."));
telegramCheckButton.addEventListener("click", () => sendTelegram("/alerts/telegram/check-latest", "Alerta enviado ao Telegram."));
loadDashboard();
