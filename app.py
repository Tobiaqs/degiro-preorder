import os, websocket, requests, time
from json import loads, load, dump
from threading import Thread
from datetime import datetime

from trading.api import API as TradingAPI
from trading.pb.trading_pb2 import (
    AccountOverview,
    Credentials,
    Update,
    Order,
    TransactionsHistory
)

STATUS_FILE = os.environ['STATUS_FILE']
FINNHUB_TOKEN = os.environ['FINNHUB_TOKEN']
DG_USERNAME = os.environ['DG_USERNAME']
DG_PASSWORD = os.environ['DG_PASSWORD']
DG_INTACCOUNT = int(os.environ['DG_INTACCOUNT'])

credentials = Credentials(
    int_account=DG_INTACCOUNT,
    username=DG_USERNAME,
    password=DG_PASSWORD,
)

trading_api = TradingAPI(credentials=credentials)
trading_api.connect()

# test writing to file
status = load(open(STATUS_FILE, 'r'))
dump(status, open(STATUS_FILE, 'w'), indent=4, sort_keys=True)

# poll trading_api periodically to keep session alove
def request_account_info_periodically():
    trading_api.get_account_info()
    time.sleep(600)

Thread(target=request_account_info_periodically, daemon=True).start()

# determine whether an order has been created for sell point
def is_order_created(sell_point):
    return 'order_created' in sell_point and sell_point['order_created'] == True

def on_price_update(last_price):
    status = load(open('status.json', 'r'))

    for sell_point in status['sell_points']:
        if not is_order_created(sell_point) and sell_point['price'] > last_price * 0.81 and sell_point['price'] < last_price * 1.19:
            print(f'creating order for {sell_point["product_ticker"]}: ${sell_point["price"]} x {sell_point["amount"]}')
            order = Order(
                action=Order.Action.SELL,
                order_type=Order.OrderType.LIMIT,
                price=sell_point['price'],
                product_id=sell_point['product_id'],
                size=sell_point['amount'],
                time_type=Order.TimeType.GOOD_TILL_CANCELED
            )

            checking_response = trading_api.check_order(order=order)
            confirmation_id = checking_response.confirmation_id
            confirmation_response = trading_api.confirm_order(
                confirmation_id=confirmation_id,
                order=order
            )

            if confirmation_response != False:
                print(f'created order for {sell_point["product_ticker"]}: ${sell_point["price"]} x {sell_point["amount"]}')
                sell_point['order_created'] = True
                sell_point['order_created_utc'] = datetime.utcnow().isoformat()
                dump(status, open('status.json', 'w'), indent=4, sort_keys=True)

def on_ws_message(ws, message):
    trade = loads(message)
    last_price = trade['data'][-1]['p']
    on_price_update(last_price)

def on_ws_error(ws, error):
    print(error)

def on_ws_close(ws):
    print('### closed ###')

def on_ws_open(ws):
    status = load(open('status.json', 'r'))
    tickers = set()
    for sell_point in status['sell_points']:
        tickers.add(sell_point['product_ticker'])
    for ticker in tickers:
        ws.send(f'{{"type":"subscribe","symbol":"{ticker}"}}')

ws = websocket.WebSocketApp(f'wss://ws.finnhub.io?token={FINNHUB_TOKEN}',
                              on_message = on_ws_message,
                              on_error = on_ws_error,
                              on_close = on_ws_close)

ws.on_open = on_ws_open

r = requests.get(f'https://finnhub.io/api/v1/quote?symbol=GME&token={FINNHUB_TOKEN}')
starting_price = r.json()['c']

on_price_update(starting_price)

ws.run_forever()
