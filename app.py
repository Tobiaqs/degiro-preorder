import os, websocket, time
from json import loads, load, dump
from threading import Thread, Lock
from datetime import datetime
from queue import Queue
from signal import signal, SIGTERM
from trading.api import API as TradingAPI
from trading.pb.trading_pb2 import (
    AccountOverview,
    Credentials,
    Update,
    Order,
    TransactionsHistory
)

# handle docker's SIGTERM
def handle_sigterm(*args):
    raise KeyboardInterrupt()

signal(SIGTERM, handle_sigterm)

# parameters
STATUS_FILE = '/app/status.json'
FINNHUB_TOKEN = os.environ['FINNHUB_TOKEN']
credentials = Credentials(
    int_account=int(os.environ['DG_INTACCOUNT']),
    username=os.environ['DG_USERNAME'],
    password=os.environ['DG_PASSWORD'],
)

trading_api = TradingAPI(credentials=credentials)
trading_api.connect()
trading_api.get_account_info()
print('connected to DEGIRO API')

# test writing to status file
status = load(open(STATUS_FILE, 'r'))
dump(status, open(STATUS_FILE, 'w'), indent=4, sort_keys=True)

# poll trading_api periodically to keep session alove
def request_account_info_periodically():
    time.sleep(60)
    trading_api.get_account_info()
    print('polled DEGIRO API')

Thread(target=request_account_info_periodically, daemon=True).start()

prices_queue = Queue()

def price_aggregator():
    while True:
        v_sum = 0
        pv_sum = 0

        # obtain all readings from the prices_queue
        while True:
            try:
                price = prices_queue.get(timeout=0.1)
                v_sum += price['v']
                pv_sum += price['p'] * price['v']
            except:
                break
        
        if v_sum > 0:
            on_price_update(pv_sum / v_sum)

        time.sleep(1)

Thread(target=price_aggregator, daemon=True).start()

# determine whether an order has been created for sell point
def is_order_created(sell_point):
    return 'order_created' in sell_point and sell_point['order_created'] == True

def on_price_update(last_price):
    status = load(open('status.json', 'r'))

    for sell_point in status['sell_points']:
        if not is_order_created(sell_point) and sell_point['price'] > last_price * 0.95 and sell_point['price'] < last_price * 1.15:
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
    # parse the trades object
    trades = loads(message)

    # volume and price*volume sum
    v_sum = 0
    pv_sum = 0

    # sum all volumes and price*volume products
    for trade in trades['data']:
        v_sum += trade['v']
        pv_sum += trade['p'] * trade['v']
    
    # ignore 0-volume trades
    if v_sum > 0:
        try:
            prices_queue.put({'v': v_sum, 'p': pv_sum / v_sum}, timeout=0.1)
        except:
            print('WARNING: timeout for queue put expired. this should NEVER happen.')
            pass

def on_ws_error(ws, error):
    print(error)

def on_ws_close(ws):
    print('disconnected')

def on_ws_open(ws):
    # find which tickers to subscribe to on the WS connection
    status = load(open('status.json', 'r'))
    tickers = set()
    for sell_point in status['sell_points']:
        tickers.add(sell_point['product_ticker'])
    
    # subscribe to the tickers
    for ticker in tickers:
        ws.send(f'{{"type":"subscribe","symbol":"{ticker}"}}')

    print('connected to Finnhub WS')

ws = websocket.WebSocketApp(f'wss://ws.finnhub.io?token={FINNHUB_TOKEN}',
                              on_message = on_ws_message,
                              on_error = on_ws_error,
                              on_close = on_ws_close)

ws.on_open = on_ws_open

ws.run_forever()
