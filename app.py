import os, websocket, time, logging
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

# logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
logger = logging.getLogger('degiro-preorder')

# parameters
PREORDERS_FILE = '/app/preorders.json'
FINNHUB_TOKEN = os.environ['FINNHUB_TOKEN']
credentials = Credentials(
    int_account=int(os.environ['DG_INTACCOUNT']),
    username=os.environ['DG_USERNAME'],
    password=os.environ['DG_PASSWORD'],
)

trading_api_mutex = Lock()
trading_api = TradingAPI(credentials=credentials)
trading_api.connect()
trading_api.get_account_info()
logger.info('connected to DEGIRO API.')

# set logging levels for libs to critical or higher
for key, value in logging.Logger.manager.loggerDict.items():
    if key.startswith('trading'):
        logging.getLogger(key).setLevel(logging.CRITICAL + 1)
    elif key != 'degiro-preorder':
        logging.getLogger(key).setLevel(logging.CRITICAL)

# test writing to preorders file
preorders = load(open(PREORDERS_FILE, 'r'))
dump(preorders, open(PREORDERS_FILE, 'w'), indent=4, sort_keys=True)

# poll trading_api periodically to keep session alive
def recreate_trading_api_periodically():
    global trading_api
    while True:
        # every 10 minutes, recreate session.
        time.sleep(600)
        trading_api_mutex.acquire()
        try:
            trading_api = TradingAPI(credentials=credentials)
            trading_api.connect()
            trading_api.get_account_info()
        except:
            logger.error('failed to recreate TradingAPI.')
        finally:
            trading_api_mutex.release()

def poll_trading_api_periodically():
    while True:
        time.sleep(60)
        trading_api_mutex.acquire()
        try:
            trading_api.get_account_info()
        except:
            logger.error('unable to get_account_info from TradingAPI.')
        finally:
            trading_api_mutex.release()

Thread(target=recreate_trading_api_periodically, daemon=True).start()
Thread(target=poll_trading_api_periodically, daemon=True).start()

prices_queue = Queue()

def price_aggregator():
    while True:
        sums = {}

        # obtain all readings from the prices_queue
        while True:
            try:
                price = prices_queue.get(timeout=0.1)
                if price['s'] not in sums:
                    sums[price['s']] = {'v_sum': 0, 'pv_sum': 0}
                sums[price['s']]['v_sum'] += price['v']
                sums[price['s']]['pv_sum'] += price['p'] * price['v']
            except:
                break
        
        for symbol, sums in sums.items():
            if sums['v_sum'] > 0:
                price = sums['pv_sum'] / sums['v_sum']
                on_price_update(symbol, price)
                logging.debug(f'on_price_update("{symbol}", {price})')

        time.sleep(5)

Thread(target=price_aggregator, daemon=True).start()

# DEGIRO limits
def is_order_valid(preorder, last_price, use_margins=True):
    if 'order_created' in preorder and preorder['order_created'] == True:
        return False

    if 'preorder_canceled' in preorder:
        return False

    if preorder['time_type'] != 'GOOD_TILL_CANCELED' and preorder['time_type'] != 'GOOD_TILL_DAY':
        return False

    offset = 0.025 if use_margins else 0

    if preorder['action'] == 'BUY':
        return preorder['price'] >= last_price * (0.80 + offset) and preorder['price'] <= last_price * (1.10 - offset)
    elif preorder['action'] == 'SELL':
        return preorder['price'] >= last_price * (0.90 + offset) and preorder['price'] <= last_price * (1.20 - offset)
    
    return False

def on_price_update(symbol, last_price):
    preorders = load(open(PREORDERS_FILE, 'r'))

    for preorder in preorders:
        if preorder['product_ticker'] != symbol:
            continue

        if is_order_valid(preorder, last_price):
            logger.info(f'creating {preorder["action"]} order for {preorder["product_ticker"]}: ${preorder["price"]} x {preorder["amount"]}.')
            order = Order(
                action=Order.Action.SELL if preorder['action'] == 'SELL' else Order.Action.BUY,
                order_type=Order.OrderType.LIMIT,
                price=preorder['price'],
                product_id=preorder['product_id'],
                size=preorder['amount'],
                time_type=Order.TimeType.GOOD_TILL_CANCELED \
                            if preorder['time_type'] == 'GOOD_TILL_CANCELED' \
                            else Order.TimeType.GOOD_TILL_DAY
            )

            trading_api_mutex.acquire()
            try:
                checking_response = trading_api.check_order(order=order)
                if checking_response != False:
                    confirmation_response = trading_api.confirm_order(
                        confirmation_id=checking_response.confirmation_id,
                        order=order
                    )

                    if confirmation_response != False:
                        logger.info('created order.')
                        preorder['order_created'] = True
                        preorder['order_created_utc'] = datetime.utcnow().isoformat()
                        dump(preorders, open(PREORDERS_FILE, 'w'), indent=4, sort_keys=True)
                    else:
                        logger.warning('order creation failed due to invalid price.')
                else:
                    # insufficient funds or shares
                    logger.warning('order creation failed due to insufficient funds or shares. order canceled.')
                    preorder['preorder_canceled'] = True
                    dump(preorders, open(PREORDERS_FILE, 'w'), indent=4, sort_keys=True)
            except e:
                logger.error('unable to create order due to an exception.')
                logger.error(e)
            finally:
                trading_api_mutex.release()

def on_ws_message(ws, message):
    # parse the trades object
    trades = loads(message)

    if 'data' not in trades:
        return

    # collect sums per symbol
    sums = {}

    # sum all volumes and price*volume products
    for trade in trades['data']:
        if trade['s'] not in sums:
            sums[trade['s']] = {'v_sum': 0, 'pv_sum': 0}
        sums[trade['s']]['v_sum'] += trade['v']
        sums[trade['s']]['pv_sum'] += trade['p'] * trade['v']
    
    for symbol, sums in sums.items():
        # ignore 0-volume trades
        if sums['v_sum'] > 0:
            try:
                prices_queue.put({'v': sums['v_sum'], 'p': sums['pv_sum'] / sums['v_sum'], 's': symbol}, timeout=0.1)
            except:
                logger.warning('timeout for queue put expired. this should NEVER happen.')
                pass

def on_ws_error(ws, error):
    logger.error(error)

def on_ws_close(ws):
    logger.info('websocket disconnected, exiting.')

def on_ws_open(ws):
    # find which tickers to subscribe to on the WS connection
    preorders = load(open(PREORDERS_FILE, 'r'))
    tickers = set()
    for preorder in preorders:
        tickers.add(preorder['product_ticker'])
    
    # subscribe to the tickers
    for ticker in tickers:
        ws.send(f'{{"type":"subscribe","symbol":"{ticker}"}}')
        logger.info(f'subscribed to {ticker} data from Finnhub.')

    logger.info('connected to Finnhub WS.')

ws = websocket.WebSocketApp(f'wss://ws.finnhub.io?token={FINNHUB_TOKEN}',
                              on_message = on_ws_message,
                              on_error = on_ws_error,
                              on_close = on_ws_close)

ws.on_open = on_ws_open

ws.run_forever()
