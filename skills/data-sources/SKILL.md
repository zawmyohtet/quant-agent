---
name: data-sources
description: >
  Use this skill when the user asks about available data, data quality, supported
  fields, provider capabilities, or when you are unsure whether a specific data
  field (such as options data, real-time quotes, or intraday data) is available
  from the currently active provider. Also use before fetching unusual data types
  to confirm the active provider supports them.
license: MIT
metadata:
  author: quantagent
  version: "1.0"
allowed-tools: get_stock_quote, get_ohlcv_data, get_stock_fundamentals
---

# Data Sources

## Overview
QuantAgent supports multiple data providers. The active provider is set by the user
via /provider. Before fetching any data, confirm the active provider supports the
required fields. Never assume all providers return the same fields.

## Provider Capability Matrix

| Capability | yfinance | alpha_vantage | polygon |
|---|---|---|---|
| OHLCV (daily) | ✅ | ✅ | ✅ |
| OHLCV (intraday) | ✅ delayed | ✅ delayed | ✅ real-time |
| Real-time quotes | ❌ 15m delay | ❌ 15m delay | ✅ |
| Fundamentals | ✅ | ✅ | ✅ |
| Options chain | ✅ | ❌ | ✅ |
| Crypto | ✅ | ✅ | ✅ |
| News | ✅ | ✅ | ✅ |

## Rate Limits
- yfinance: ~2000 requests/hour; no API key required
- alpha_vantage: 25 requests/day (free tier); key required
- polygon: based on plan; key required; real-time on paid plans

## Known Limitations
- yfinance: dividend and split data may lag by 1 trading day
- alpha_vantage: free tier makes full stock screening impractical
- All providers: intraday data older than 60 days may be incomplete
- Fundamentals coverage varies — always check if fields are None before using them

## Supporting files
- field_reference.md — full list of field names returned by each data function
