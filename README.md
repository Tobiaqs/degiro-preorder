# degiro-preorder

## Why this tool exists
On DEGIRO it is not possible to create limit orders with a target price that differs significantly from the last price. This tool creates orders as soon as the current price crosses the threshold for order creation to become possible.

## Limitations
- Only works on US securities when using Finnhub.io free account.
- Stability is unknown.

## Configuration
Obtain a Finnhub.io API key. Obtain a DEGIRO account with holdings, collect username, password and intaccount credentials. Set environment variables in `.env` accordingly.

Create a file called `preorders.json` (based on `preorders.json.example`) on a Python-writable location. Refer to it in `.env`.

`product_id` is used to identify the security at DEGIRO. Can be grabbed from URL in the web application.

`product_ticker` is used to identify the security at Finnhub.io.

The example preorders.json means the following:

- As soon as it becomes possible to create a limit buy order for AAPL for 90$, create a limit buy order for 90$, for 20 shares, that expires at EOD.
- As soon as it becomes possible to create a limit sell order for AAPL for 130.54$, create a limit sell order for 130.54$, for 31 shares, that does not expire until canceled.

## How to run
To run in background with Docker Compose:

```
$ docker-compose up --build -d
```

For foreground/development use:

```
$ docker-compose up --build
```

The container is automatically restarted by Docker in case the application crashes or websocket disconnects.

## Future plans
- Web interface
- Robustness tweaks based on findings after a few weeks of usage
