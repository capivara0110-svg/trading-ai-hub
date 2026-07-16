//+------------------------------------------------------------------+
//| Trading AI Hub Bridge EA                                         |
//| Demo-first bridge for Trading AI Hub execution/pending endpoint. |
//+------------------------------------------------------------------+
#property strict
#property version   "1.01"

#include <Trade/Trade.mqh>

input string InpApiBaseUrl = "https://trading-ai-hub-production.up.railway.app";
input string InpExecutionSecret = "";
input string InpExpectedApiSymbol = "EURUSD";
input string InpTradeSymbol = "";
input int    InpPollSeconds = 5;
input int    InpRequestTimeoutMs = 5000;
input int    InpMaxDeviationPoints = 20;
input double InpMaxSpreadPips = 1.2;
input bool   InpAllowLateEntryIfRR = true;
input double InpMinLateEntryRR = 0.80;
input double InpHardMaxDeviationPips = 5.0;
input bool   InpBreakEvenEnabled = false;    // DESLIGADO - usar Profit Manager do backend
input double InpBreakEvenTriggerPips = 8.0; // backup case InpBreakEvenEnabled=true
input double InpBreakEvenOffsetPips = 1.5;  // backup case InpBreakEvenEnabled=true
input bool   InpProfitManagerEnabled = true;  // GERENCIAMENTO DE LUCRO VIA BACKEND
input int    InpProfitManagerPollSeconds = 10; // consultar backend a cada N segundos
input ulong  InpMagicNumber = 240601;
input bool   InpDemoOnly = true;

CTrade trade;
datetime lastPollAt = 0;
string claimedOrderId = "";
datetime lastProfitCheckAt = 0;
double profitManagerCurrentSl = 0.0;  // SL definido pelo backend
double profitManagerCurrentTp = 0.0;
string activeTrackedOrderId = "";
ulong activeTrackedPositionTicket = 0;
string activeTrackedSymbol = "";

int OnInit()
{
   trade.SetExpertMagicNumber(InpMagicNumber);
   trade.SetDeviationInPoints(InpMaxDeviationPoints);

   if(InpExecutionSecret == "")
   {
      Print("Trading AI Hub: configure InpExecutionSecret antes de iniciar.");
      return INIT_PARAMETERS_INCORRECT;
   }

   long accountMode = AccountInfoInteger(ACCOUNT_TRADE_MODE);
   if(InpDemoOnly && accountMode != ACCOUNT_TRADE_MODE_DEMO && accountMode != ACCOUNT_TRADE_MODE_CONTEST)
   {
      Print("Trading AI Hub: InpDemoOnly=true. Use primeiro em conta DEMO.");
      return INIT_FAILED;
   }

   EventSetTimer((int)MathMax(1, InpPollSeconds));
   LoadTrackedOrder();
   Print("Trading AI Hub Bridge EA iniciado.");
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   EventKillTimer();
}

void OnTradeTransaction(const MqlTradeTransaction &trans,
                        const MqlTradeRequest &request,
                        const MqlTradeResult &result)
{
   if(trans.type != TRADE_TRANSACTION_DEAL_ADD || trans.deal == 0)
      return;

   if(!HistoryDealSelect(trans.deal))
      return;

   long entry = HistoryDealGetInteger(trans.deal, DEAL_ENTRY);
   if(entry != DEAL_ENTRY_OUT && entry != DEAL_ENTRY_INOUT)
      return;

   long magic = HistoryDealGetInteger(trans.deal, DEAL_MAGIC);
   if(magic != (long)InpMagicNumber)
      return;

   ulong positionId = (ulong)HistoryDealGetInteger(trans.deal, DEAL_POSITION_ID);
   if(activeTrackedPositionTicket > 0 && positionId != activeTrackedPositionTicket)
      return;

   if(activeTrackedOrderId == "")
      return;

   if(HasPositionTicket(positionId))
      return;

   double closePrice = HistoryDealGetDouble(trans.deal, DEAL_PRICE);
   double profit = HistoryDealGetDouble(trans.deal, DEAL_PROFIT)
                 + HistoryDealGetDouble(trans.deal, DEAL_SWAP)
                 + HistoryDealGetDouble(trans.deal, DEAL_COMMISSION);
   string status = profit >= 0.0 ? "WIN" : "LOSS";
   SendCloseResult(activeTrackedOrderId, status, positionId, closePrice, profit, "position closed in MT5");
   ClearTrackedOrder();
}

void OnTimer()
{
   // Profit Manager (backend) - substitui o break-even local
   if(InpProfitManagerEnabled)
      ManageProfitViaBackend();
   else
      ManageBreakEven();

   // Poll de novas ordens pendentes
   if(TimeCurrent() - lastPollAt < InpPollSeconds)
      return;
   lastPollAt = TimeCurrent();
   PollPendingOrder();
}

void PollPendingOrder()
{
   string url = InpApiBaseUrl + "/execution/pending?secret=" + UrlEncode(InpExecutionSecret);
   string response = "";
   int status = HttpGet(url, response);
   if(status != 200)
   {
      Print("Trading AI Hub: falha ao consultar pending. HTTP=", status, " body=", response);
      return;
   }

   if(StringFind(response, "\"order\": null") >= 0 || StringFind(response, "\"order\":null") >= 0)
      return;

   string orderId = JsonString(response, "id");
   if(orderId == "" || orderId == claimedOrderId)
      return;

   string apiSymbol = JsonString(response, "symbol");
   string side = JsonString(response, "side");
   string statusText = JsonString(response, "status");
   string expiresAt = JsonString(response, "expiresAt");
   double lot = JsonNumber(response, "lot", 0.01);
   double entry = JsonNumber(response, "entry", 0.0);
   double stopLoss = JsonNumber(response, "stopLoss", 0.0);
   double takeProfit = JsonNumber(response, "takeProfit", 0.0);
   double maxDeviationPips = JsonNumber(response, "maxEntryDeviationPips", 1.5);

   if(statusText != "PENDING")
      return;

   if(apiSymbol != InpExpectedApiSymbol)
   {
      Print("Trading AI Hub: simbolo ignorado: ", apiSymbol);
      return;
   }

   if(IsExpiredUtc(expiresAt))
   {
      Print("Trading AI Hub: ordem expirada: ", orderId);
      return;
   }

   string symbol = InpTradeSymbol == "" ? _Symbol : InpTradeSymbol;
   if(!SymbolSelect(symbol, true))
   {
      // Remove do Profit Manager se estava registrado
      string removeBody = "{\"secret\":\"" + JsonEscape(InpExecutionSecret) + "\",\"order_id\":\"" + orderId + "\"}";
      string remResponse = "";
      HttpPost(InpApiBaseUrl + "/profit-manager/remove", removeBody, remResponse);
      SendResult(orderId, "REJECTED", 0, 0.0, "symbol not available");
      return;
   }

   if(HasOpenPosition(symbol))
   {
      Print("Trading AI Hub: ja existe posicao aberta em ", symbol);
      return;
   }

   double ask = SymbolInfoDouble(symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(symbol, SYMBOL_BID);
   double spreadPips = (ask - bid) / PipSize(symbol);
   if(spreadPips > InpMaxSpreadPips)
   {
      Print("Trading AI Hub: spread alto. spreadPips=", DoubleToString(spreadPips, 2));
      SendResult(orderId, "REJECTED", 0, 0.0, "spread too high");
      return;
   }

   double currentPrice = side == "BUY" ? ask : bid;
   if(currentPrice <= 0 || entry <= 0 || stopLoss <= 0 || takeProfit <= 0)
   {
      SendResult(orderId, "REJECTED", 0, 0.0, "invalid price, stop or target");
      return;
   }

   double diffPips = MathAbs(currentPrice - entry) / PipSize(symbol);
   if(diffPips > maxDeviationPips)
   {
      double rr = RewardRiskRatio(side, currentPrice, stopLoss, takeProfit, symbol);
      if(!InpAllowLateEntryIfRR || diffPips > InpHardMaxDeviationPips || rr < InpMinLateEntryRR)
      {
         Print("Trading AI Hub: preco longe da entrada. diffPips=", DoubleToString(diffPips, 2), " rr=", DoubleToString(rr, 2));
         SendResult(orderId, "REJECTED", 0, currentPrice, "price moved too far");
         return;
      }
      Print("Trading AI Hub: entrada atrasada aceita por RR. diffPips=", DoubleToString(diffPips, 2), " rr=", DoubleToString(rr, 2));
   }

   if(!ClaimOrder(orderId))
      return;

   claimedOrderId = orderId;
   bool opened = false;
   if(side == "BUY")
      opened = trade.Buy(lot, symbol, 0.0, stopLoss, takeProfit, "Trading AI Hub");
   else if(side == "SELL")
      opened = trade.Sell(lot, symbol, 0.0, stopLoss, takeProfit, "Trading AI Hub");

   if(opened)
   {
      ulong ticket = trade.ResultOrder();
      double fillPrice = trade.ResultPrice();
      ulong positionTicket = FindOpenPositionTicket(symbol);
      if(positionTicket == 0)
         positionTicket = ticket;
      Print("Trading AI Hub: ordem aberta. id=", orderId, " ticket=", ticket);
      SaveTrackedOrder(orderId, positionTicket, symbol);
      // Registra no Profit Manager do backend
      string registerBody = "{";
      registerBody += "\"secret\":\"" + JsonEscape(InpExecutionSecret) + "\",";
      registerBody += "\"order_id\":\"" + orderId + "\",";
      registerBody += "\"current_price\":" + DoubleToString(fillPrice, _Digits);
      registerBody += "}";
      string regResponse = "";
      HttpPost(InpApiBaseUrl + "/profit-manager/update", registerBody, regResponse);
      SendResult(orderId, "EXECUTED", positionTicket, fillPrice, "opened in MT5 demo");
      return;
   }

   string msg = "trade failed retcode=" + IntegerToString((int)trade.ResultRetcode()) + " " + trade.ResultRetcodeDescription();
   Print("Trading AI Hub: ", msg);
   SendResult(orderId, "ERROR", 0, currentPrice, msg);
}

double RewardRiskRatio(const string side, const double price, const double stopLoss, const double takeProfit, const string symbol)
{
   double pip = PipSize(symbol);
   if(pip <= 0)
      return 0.0;

   double risk = 0.0;
   double reward = 0.0;
   if(side == "BUY")
   {
      risk = price - stopLoss;
      reward = takeProfit - price;
   }
   else if(side == "SELL")
   {
      risk = stopLoss - price;
      reward = price - takeProfit;
   }

   if(risk <= 0 || reward <= 0)
      return 0.0;
   return (reward / pip) / (risk / pip);
}

void ManageProfitViaBackend()
{
   if(!InpProfitManagerEnabled)
      return;

   datetime now = TimeCurrent();
   if(now - lastProfitCheckAt < InpProfitManagerPollSeconds)
      return;
   lastProfitCheckAt = now;

   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;

      string symbol = PositionGetString(POSITION_SYMBOL);
      if(PositionGetInteger(POSITION_MAGIC) != (long)InpMagicNumber) continue;

      long type = PositionGetInteger(POSITION_TYPE);
      double openPrice = PositionGetDouble(POSITION_PRICE_OPEN);
      double currentStopLoss = PositionGetDouble(POSITION_SL);
      double currentTakeProfit = PositionGetDouble(POSITION_TP);
      double volume = PositionGetDouble(POSITION_VOLUME);
      double bid = SymbolInfoDouble(symbol, SYMBOL_BID);
      double ask = SymbolInfoDouble(symbol, SYMBOL_ASK);
      double currentPrice = (type == POSITION_TYPE_BUY) ? bid : ask;

      string orderId = activeTrackedOrderId;
      if(orderId == "" || ticket != activeTrackedPositionTicket)
         orderId = IntegerToString(ticket);

      // Monta JSON para enviar ao backend
      string body = "{";
      body += "\"secret\":\"" + JsonEscape(InpExecutionSecret) + "\",";
      body += "\"order_id\":\"" + orderId + "\",";
      body += "\"current_price\":" + DoubleToString(currentPrice, (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS));
      body += "}";

      string response = "";
      int status = HttpPost(InpApiBaseUrl + "/profit-manager/update", body, response);
      if(status != 200)
      {
         if(status > 0) // so mostra se conseguiu conectar
            Print("Profit Manager: HTTP=", status, " response=", response);
         continue;
      }

      // Verifica se tem ajuste
      if(StringFind(response, "\"adjusted\": true") < 0 && StringFind(response, "\"adjusted\":true") < 0)
         continue;

      // Extrai novo SL se houver
      double newSL = JsonNumber(response, "new_sl", 0.0);
      if(newSL > 0.0)
      {
         double pip = PipSize(symbol);
         int digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
         newSL = NormalizeDouble(newSL, digits);

         // Verifica se o novo SL e melhor que o atual
         bool shouldUpdate = false;
         if(type == POSITION_TYPE_BUY && newSL > currentStopLoss && newSL < bid)
            shouldUpdate = true;
         if(type == POSITION_TYPE_SELL && (currentStopLoss == 0.0 || newSL < currentStopLoss) && newSL > ask)
            shouldUpdate = true;

         if(shouldUpdate)
         {
            CTrade modTrade;
            modTrade.SetExpertMagicNumber(InpMagicNumber);
            if(modTrade.PositionModify(ticket, newSL, currentTakeProfit))
            {
               string reason = JsonString(response, "reason");
               Print("Profit Manager: SL ajustado ticket=", ticket,
                     " novoSL=", DoubleToString(newSL, digits),
                     " razao=", reason);
            }
         }
      }

      // Verifica fechamento parcial
      double closePct = JsonNumber(response, "partial_close_pct", 0.0);
      if(closePct > 0.0)
      {
         double closeVol = JsonNumber(response, "partial_close_volume", 0.0);
         if(closeVol > 0.0 && closeVol <= volume)
         {
            CTrade partTrade;
            partTrade.SetExpertMagicNumber(InpMagicNumber);
            if(type == POSITION_TYPE_BUY)
               partTrade.Sell(closeVol, symbol, 0.0, 0.0, 0.0, "TP Parcial");
            else
               partTrade.Buy(closeVol, symbol, 0.0, 0.0, 0.0, "TP Parcial");

            Print("Profit Manager: fechamento parcial ticket=", ticket,
                  " volume=", DoubleToString(closeVol, 2));
         }
      }
   }
}

void ManageBreakEven()
{
   if(!InpBreakEvenEnabled)
      return;

   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0)
         continue;

      string symbol = PositionGetString(POSITION_SYMBOL);
      if(PositionGetInteger(POSITION_MAGIC) != (long)InpMagicNumber)
         continue;

      long type = PositionGetInteger(POSITION_TYPE);
      double openPrice = PositionGetDouble(POSITION_PRICE_OPEN);
      double stopLoss = PositionGetDouble(POSITION_SL);
      double takeProfit = PositionGetDouble(POSITION_TP);
      double pip = PipSize(symbol);
      double bid = SymbolInfoDouble(symbol, SYMBOL_BID);
      double ask = SymbolInfoDouble(symbol, SYMBOL_ASK);
      int digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);

      if(type == POSITION_TYPE_BUY)
      {
         double profitPips = (bid - openPrice) / pip;
         double newStop = NormalizeDouble(openPrice + InpBreakEvenOffsetPips * pip, digits);
         if(profitPips >= InpBreakEvenTriggerPips && (stopLoss == 0.0 || stopLoss < newStop) && newStop < bid)
         {
            if(trade.PositionModify(ticket, newStop, takeProfit))
               Print("Trading AI Hub: break-even BUY aplicado. ticket=", ticket, " SL=", DoubleToString(newStop, digits));
            else
               Print("Trading AI Hub: falha break-even BUY. retcode=", trade.ResultRetcode(), " ", trade.ResultRetcodeDescription());
         }
      }

      if(type == POSITION_TYPE_SELL)
      {
         double profitPips = (openPrice - ask) / pip;
         double newStop = NormalizeDouble(openPrice - InpBreakEvenOffsetPips * pip, digits);
         if(profitPips >= InpBreakEvenTriggerPips && (stopLoss == 0.0 || stopLoss > newStop) && newStop > ask)
         {
            if(trade.PositionModify(ticket, newStop, takeProfit))
               Print("Trading AI Hub: break-even SELL aplicado. ticket=", ticket, " SL=", DoubleToString(newStop, digits));
            else
               Print("Trading AI Hub: falha break-even SELL. retcode=", trade.ResultRetcode(), " ", trade.ResultRetcodeDescription());
         }
      }
   }
}

bool ClaimOrder(const string orderId)
{
   long tradeMode = AccountInfoInteger(ACCOUNT_TRADE_MODE);
   string accountMode = tradeMode == ACCOUNT_TRADE_MODE_DEMO ? "DEMO" : (tradeMode == ACCOUNT_TRADE_MODE_CONTEST ? "CONTEST" : "REAL");
   string body = "{\"secret\":\"" + JsonEscape(InpExecutionSecret) + "\",\"id\":\"" + JsonEscape(orderId) + "\",\"accountMode\":\"" + accountMode + "\"}";
   string response = "";
   int status = HttpPost(InpApiBaseUrl + "/execution/claim", body, response);
   if(status != 200)
   {
      Print("Trading AI Hub: claim falhou HTTP=", status, " body=", response);
      return false;
   }
   if(StringFind(response, "\"claimed\": true") >= 0 || StringFind(response, "\"claimed\":true") >= 0)
      return true;
   Print("Trading AI Hub: claim recusado: ", response);
   return false;
}

void SendResult(const string orderId, const string status, const ulong ticket, const double fillPrice, const string message)
{
   string body = "{";
   body += "\"secret\":\"" + JsonEscape(InpExecutionSecret) + "\",";
   body += "\"id\":\"" + JsonEscape(orderId) + "\",";
   body += "\"status\":\"" + JsonEscape(status) + "\",";
   body += "\"brokerTicket\":\"" + IntegerToString((long)ticket) + "\",";
   body += "\"fillPrice\":" + DoubleToString(fillPrice, _Digits) + ",";
   body += "\"message\":\"" + JsonEscape(message) + "\"";
   body += "}";

   string response = "";
   int httpStatus = HttpPost(InpApiBaseUrl + "/execution/result", body, response);
   Print("Trading AI Hub: result HTTP=", httpStatus, " body=", response);
}

void SendCloseResult(const string orderId, const string status, const ulong ticket, const double closePrice, const double profit, const string message)
{
   string body = "{";
   body += "\"secret\":\"" + JsonEscape(InpExecutionSecret) + "\",";
   body += "\"id\":\"" + JsonEscape(orderId) + "\",";
   body += "\"status\":\"" + JsonEscape(status) + "\",";
   body += "\"brokerTicket\":\"" + IntegerToString((long)ticket) + "\",";
   body += "\"closePrice\":" + DoubleToString(closePrice, _Digits) + ",";
   body += "\"profit\":" + DoubleToString(profit, 2) + ",";
   body += "\"message\":\"" + JsonEscape(message) + "\"";
   body += "}";

   string response = "";
   int httpStatus = HttpPost(InpApiBaseUrl + "/execution/result", body, response);
   Print("Trading AI Hub: close result HTTP=", httpStatus, " body=", response);
}

int HttpGet(const string url, string &response)
{
   char data[];
   char result[];
   string headers = "";
   string resultHeaders = "";
   ResetLastError();
   int status = WebRequest("GET", url, "", "", InpRequestTimeoutMs, data, 0, result, resultHeaders);
   response = CharArrayToString(result, 0, -1, CP_UTF8);
   if(status == -1)
      Print("Trading AI Hub: WebRequest GET erro=", GetLastError(), ". Libere a URL em Tools > Options > Expert Advisors.");
   return status;
}

int HttpPost(const string url, const string body, string &response)
{
   char data[];
   char result[];
   string resultHeaders = "";
   string headers = "Content-Type: application/json\r\n";
   StringToCharArray(body, data, 0, StringLen(body), CP_UTF8);
   ResetLastError();
   int status = WebRequest("POST", url, headers, InpRequestTimeoutMs, data, result, resultHeaders);
   response = CharArrayToString(result, 0, -1, CP_UTF8);
   if(status == -1)
      Print("Trading AI Hub: WebRequest POST erro=", GetLastError(), ". Libere a URL em Tools > Options > Expert Advisors.");
   return status;
}

bool HasOpenPosition(const string symbol)
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0)
         continue;
      if(PositionGetString(POSITION_SYMBOL) == symbol && PositionGetInteger(POSITION_MAGIC) == (long)InpMagicNumber)
         return true;
   }
   return false;
}

bool HasPositionTicket(const ulong positionTicket)
{
   if(positionTicket == 0)
      return false;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == positionTicket)
         return true;
   }
   return false;
}

ulong FindOpenPositionTicket(const string symbol)
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0)
         continue;
      if(PositionGetString(POSITION_SYMBOL) == symbol && PositionGetInteger(POSITION_MAGIC) == (long)InpMagicNumber)
         return ticket;
   }
   return 0;
}

string TrackingFileName()
{
   return "trading_ai_hub_tracking_" + IntegerToString((int)InpMagicNumber) + ".txt";
}

void SaveTrackedOrder(const string orderId, const ulong positionTicket, const string symbol)
{
   activeTrackedOrderId = orderId;
   activeTrackedPositionTicket = positionTicket;
   activeTrackedSymbol = symbol;

   int handle = FileOpen(TrackingFileName(), FILE_WRITE | FILE_TXT | FILE_COMMON);
   if(handle == INVALID_HANDLE)
      return;
   FileWrite(handle, orderId);
   FileWrite(handle, IntegerToString((long)positionTicket));
   FileWrite(handle, symbol);
   FileClose(handle);
}

void LoadTrackedOrder()
{
   int handle = FileOpen(TrackingFileName(), FILE_READ | FILE_TXT | FILE_COMMON);
   if(handle == INVALID_HANDLE)
      return;
   activeTrackedOrderId = FileReadString(handle);
   activeTrackedPositionTicket = (ulong)StringToInteger(FileReadString(handle));
   activeTrackedSymbol = FileReadString(handle);
   FileClose(handle);

   if(activeTrackedPositionTicket > 0 && !HasPositionTicket(activeTrackedPositionTicket))
      ClearTrackedOrder();
}

void ClearTrackedOrder()
{
   activeTrackedOrderId = "";
   activeTrackedPositionTicket = 0;
   activeTrackedSymbol = "";
   FileDelete(TrackingFileName(), FILE_COMMON);
}

double PipSize(const string symbol)
{
   int digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
   double point = SymbolInfoDouble(symbol, SYMBOL_POINT);
   if(digits == 3 || digits == 5)
      return point * 10.0;
   return point;
}

bool IsExpiredUtc(const string iso)
{
   if(StringLen(iso) < 19)
      return false;
   string raw = StringSubstr(iso, 0, 19);
   StringReplace(raw, "T", " ");
   datetime expires = StringToTime(raw);
   if(expires <= 0)
      return false;
   return TimeGMT() > expires;
}

string JsonString(const string json, const string key)
{
   string marker = "\"" + key + "\"";
   int pos = StringFind(json, marker);
   if(pos < 0)
      return "";
   pos = StringFind(json, ":", pos + StringLen(marker));
   if(pos < 0)
      return "";
   pos++;
   while(pos < StringLen(json) && StringGetCharacter(json, pos) <= 32)
      pos++;
   if(pos >= StringLen(json) || StringGetCharacter(json, pos) != '"')
      return "";
   pos++;
   string value = "";
   bool escaped = false;
   for(int i = pos; i < StringLen(json); i++)
   {
      ushort ch = StringGetCharacter(json, i);
      if(escaped)
      {
         value += ShortToString(ch);
         escaped = false;
         continue;
      }
      if(ch == '\\')
      {
         escaped = true;
         continue;
      }
      if(ch == '"')
         break;
      value += ShortToString(ch);
   }
   return value;
}

double JsonNumber(const string json, const string key, const double fallback)
{
   string marker = "\"" + key + "\"";
   int pos = StringFind(json, marker);
   if(pos < 0)
      return fallback;
   pos = StringFind(json, ":", pos + StringLen(marker));
   if(pos < 0)
      return fallback;
   pos++;
   while(pos < StringLen(json) && StringGetCharacter(json, pos) <= 32)
      pos++;
   int start = pos;
   while(pos < StringLen(json))
   {
      ushort ch = StringGetCharacter(json, pos);
      if(ch == ',' || ch == '}' || ch == ']')
         break;
      pos++;
   }
   string raw = StringSubstr(json, start, pos - start);
   StringReplace(raw, "\"", "");
   StringTrimLeft(raw);
   StringTrimRight(raw);
   if(raw == "" || raw == "null")
      return fallback;
   return StringToDouble(raw);
}

string JsonEscape(string value)
{
   StringReplace(value, "\\", "\\\\");
   StringReplace(value, "\"", "\\\"");
   StringReplace(value, "\r", " ");
   StringReplace(value, "\n", " ");
   return value;
}

string UrlEncode(const string value)
{
   string out = "";
   for(int i = 0; i < StringLen(value); i++)
   {
      ushort ch = StringGetCharacter(value, i);
      if((ch >= 'A' && ch <= 'Z') || (ch >= 'a' && ch <= 'z') || (ch >= '0' && ch <= '9') || ch == '-' || ch == '_' || ch == '.' || ch == '~')
         out += ShortToString(ch);
      else
         out += "%" + StringFormat("%02X", ch);
   }
   return out;
}
