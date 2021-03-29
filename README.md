# degiro-autosell

## Why does this tool exist
On DEGIRO it is not possible to create limit sell orders with target price > current price x 1.2. This tool creates orders as soon as the current price crosses the threshold for order creation to be possible.

## Limitations
Only works on US securities when using Finnhub.io free account.

Stability is unknown.

The Python library degiro-connector currently does not work properly so this tool uses my own fork of this library.

## How to use
Obtain a Finnhub.io API key. Obtain a DEGIRO account with holdings, collect username, password and intaccount credentials. Set environment variables in `.env` accordingly.

Create a file called `status.json` (based on `status.json.example`) on a Python-writable location. Refer to it in `.env`.

`product_id` is used to identify the security at DEGIRO.

`product_ticker` is used to identify the security at Finnhub.io.

The example status.json does the following:

- As soon as it becomes possible to create a limit sell order for AAPL for 130$, create a limit sell order for 130$, for 1 share.
- As soon as it becomes possible to create a limit sell order for AAPL for 145.30$, create a limit sell order for 145.30$, for 30 shares.
- As soon as it becomes possible to create a limit sell order for AAPL for 173.43$, create a limit sell order for 173.43$, for 50 shares.

To run in background with Docker Compose:

```
$ docker-compose up --build -d
```

For foreground/development use:

```
$ docker-compose up --build
```