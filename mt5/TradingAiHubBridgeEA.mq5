//+------------------------------------------------------------------+
//| Trading AI Hub Bridge EA                                         |
//| Demo-first bridge for Trading AI Hub execution/pending endpoint. |
//+------------------------------------------------------------------+
#property strict
#property version   "1.00"

#include <Trade/Trade.mqh>

input string InpApiBaseUrl = "https://trading-ai-hub-production.up.railway.app";
input string InpExecutionSecret = "";
input string InpExpectedApiSymbol = "EURUSD";
input string InpTradeSymbol = "";
input int    InpPollSeconds = 2;
input int    InpRequestTimeoutMs = 5000;
input int    InpMaxDeviationPoints = 20;
input ulong  InpMagicNumber = 240601;
input bool   InpDemoOnly = true;

CTrade trade;
datetime lastPollAt = 0;
string claimedOrderId = "";

int OnInit()
{
   trade.SetExpertMagicNumber(InpMagicNumber);
   trade.SetDeviationInPoints(InpMaxDeviationPoints);

   if(InpExecutionSecret == "")
   {
      Print("Trading AI Hub: configure InpExecutionSecret antes de iniciar.");
      return INIT_PARAMETERS_INCORRECT;
   }

   if(InpDemoOnly && AccountInfoInteger(ACCOUNT_TRADE_MODE) != ACCOUNT_TRADE_MODE_DEMO)
   {
      Print("Trading AI Hub: InpDemoOnly=true. Use primeiro em conta DEMO.");
      return INIT_FAILED;
   }

   EventSetTimer((int)MathMax(1, InpPollSeconds));
   Print("Trading AI Hub Bridge EA iniciado.");
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   EventKillTimer();
}

void OnTimer()
{
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
      SendResult(orderId, "REJECTED", 0, 0.0, "symbol not available");
      return;
   }

   if(HasOpenPosition(symbol))
   {
      Print("Trading AI Hub: ja existe posicao aberta em ", symbol);
      return;
   }

   double currentPrice = side == "BUY" ? SymbolInfoDouble(symbol, SYMBOL_ASK) : SymbolInfoDouble(symbol, SYMBOL_BID);
   if(currentPrice <= 0 || entry <= 0 || stopLoss <= 0 || takeProfit <= 0)
   {
      SendResult(orderId, "REJECTED", 0, 0.0, "invalid price, stop or target");
      return;
   }

   double diffPips = MathAbs(currentPrice - entry) / PipSize(symbol);
   if(diffPips > maxDeviationPips)
   {
      Print("Trading AI Hub: preco longe da entrada. diffPips=", DoubleToString(diffPips, 2));
      SendResult(orderId, "REJECTED", 0, currentPrice, "price moved too far");
      return;
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
      Print("Trading AI Hub: ordem aberta. id=", orderId, " ticket=", ticket);
      SendResult(orderId, "EXECUTED", ticket, fillPrice, "opened in MT5 demo");
      return;
   }

   string msg = "trade failed retcode=" + IntegerToString((int)trade.ResultRetcode()) + " " + trade.ResultRetcodeDescription();
   Print("Trading AI Hub: ", msg);
   SendResult(orderId, "ERROR", 0, currentPrice, msg);
}

bool ClaimOrder(const string orderId)
{
   string body = "{\"secret\":\"" + JsonEscape(InpExecutionSecret) + "\",\"id\":\"" + JsonEscape(orderId) + "\"}";
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
