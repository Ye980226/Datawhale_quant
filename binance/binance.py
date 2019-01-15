from datetime import datetime, timedelta
import requests
import pandas as pd
import json
from itertools import chain
# import utils.logger
from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.errors import DuplicateKeyError
from utils.mongodb import append, read, insert
from itertools import product
from utils.conf import load
import logging
import os


FILENAME = os.environ.get("BINANCE", os.path.join(os.path.dirname(__file__), "conf.yml"))


URL = "https://api.binance.com/api/v1/klines"
GAP = 60*12*60*1000
COLUMNS = ["timestamp", "open", "high", "low", "close", "volume","closetime","quote_volume","number_of_trades","buy_base_volume","buy_quote_volume","Ignore"]
LIMIT = 60*12
# 把当前的时间转化成最近的整数分钟时间的日期

def now2startdate(t):
    return datetime.fromtimestamp(int(t.timestamp()*1000)//60000*60000/1000)

req_args = {}

CONF = {
    "mongodb": {
        "host": "localhost",
        "log": "log.binance",
        "db": "VnTrader_1Min_Db",
    },
    "data": {
        "start": 20180101,
        "retry": 3,
        "target": []
    }
}



def init(filename=FILENAME):
    load(filename, CONF)
    if "proxies" in CONF:
        req_args["proxies"] = CONF["proxies"]


# # 获取url
def get_url(**kwargs):
    query = "&".join(map(lambda item: "%s=%s" % item, kwargs.items()))
    url = URL
    if query:
        return "%s?%s" % (url, query)
    else:
        return url


# 获取分钟线原始数据(stream字符流)
def get_hist_1min_content(**kwargs):
    url = get_url(**kwargs)
    logging.debug("request url | %s", url)
    response = requests.get(url, **req_args)
    if response.status_code == 200:
        return response.content
    else:
        raise requests.ConnectionError(response.status_code, response.content)


# 获取分钟原始数据(json格式)
def get_hist_1min_docs(**kwargs):
    logging.debug("require bars | %s", kwargs)
    content = get_hist_1min_content(**kwargs)
    return json.loads(content)


# 计算分段
def gap_range(start, end):
    while start <= end:
        yield start, start + timedelta(hours=12, seconds=-1)
        yield start + timedelta(hours=12), start+timedelta(days=1, seconds=-1)
        start += timedelta(days=1)


# 获取一分钟数据，整合成DataFrame
def get_hist_1min(symbol,interval, startTime=None, endTime=None, **kwargs):
    if startTime and endTime:
        docs = get_hist_1min_docs(symbol=symbol, interval=interval,startTime=startTime, endTime=endTime, **kwargs)
    else:
        if startTime:
            kwargs["startTime"] = startTime
        if endTime:
            kwargs["endTime"] = endTime
        docs = get_hist_1min_docs(symbol=symbol, interval=interval, **kwargs)
    
    return pd.DataFrame(docs, columns=COLUMNS)


# 时间类型转换
def mts2datetime(mts):
    return datetime.fromtimestamp(mts/1000)

# 时间类型转换
def mts2date(mts):
    return dt2int(mts2datetime(mts))

def dt2int(dt):
    return dt.year*10000+dt.month*100+dt.day

# 时间类型转换
def dt2time(t):
    return t.strftime("%H:%M:%S")

# 时间类型转换
def dt2date(t):
    return t.strftime("%Y%m%d")

# 时间类型转换
def date2mts(t):
    return dt2mts(int2dt(t))

def dt2mts(dt):
    return int(dt.timestamp()*1000)

def int2dt(t):
    return datetime.strptime(str(t), "%Y%m%d")

# 创建获取数据索引并入库
def create_index(collection, symbols, start, end):
    assert isinstance(collection, Collection)
    collection.create_index([("symbol", 1), ("start", 1), ("end", 1)])
    index = create_index_frame(symbols, start, end)
    if len(index.index):
        r = append(collection, index)
        logging.warning("create index | %s | %s | %s | %s", symbols, start, end, r)

# 创建获取数据索(DataFrame)
def create_index_frame(symbols, start, end):
    keys = list(map(lambda item: (item[0], item[1][0], item[1][1]), product(symbols, gap_range(start, end))))
    index = pd.DataFrame(keys, columns=["symbol", "start", "end"])
    index["date"] = index["start"].apply(dt2int)
    index["vtSymbol"] = index["symbol"].apply(lambda s: "%s:binance" % s)
    index["count"] = 0
    index["fill"] = 0
    return index.set_index(["symbol", "start", "end"])


BAR_COLUMN = ["vtSymbol", "symbol", "exchange", "open", "high", "low", "close", "date", "time", "datetime", "volume", "openInterest"]


# 将原始DataFrame修改成符合vnpy格式
def vnpy_format(frame, symbol, vtSymbol=None):
    assert isinstance(frame, pd.DataFrame)
    frame["datetime"] = frame.pop("timestamp").apply(mts2datetime)
    frame["time"] = frame["datetime"].apply(dt2time)
    frame["date"] = frame["datetime"].apply(dt2date)
    frame["symbol"] = symbol
    frame["exchange"] = "binance"
    frame["vtSymbol"] = vtSymbol if vtSymbol else vt_symbol(symbol)
    frame["gatewayName"] = ""
    frame["rawData"] = None
    frame["openInterest"] = 0
    for key in ["open", "high", "low", "close", "volume"]:
        frame[key] = frame[key].apply(float)
    return frame[BAR_COLUMN]


def on_error(e):
    logging.error(e)


class MongoDBStorage(object):

    def __init__(self, host, db, log):
        self.client = MongoClient(host)
        self.db = self.client[db]
        log_db, log_col = log.split(".")
        self.log = self.client[log_db][log_col]

    def check(self):
        for symbol, start, end in self.find():
            self._check(symbol, start, end)

    def count(self, symbol, start, end):
        col = self.db[vt_symbol(symbol)]
        return col.find({"datetime": {"$gte": start, "$lt": end}}).count()

    def _check(self, symbol, start, end):
        count = self.count(symbol, start, end)
        if count > 0:
            self.fill(symbol, start, end, count, count)
            logging.warning("check | %s | %s | %s | %s", symbol, start, end, count)

    def create(self, symbols, start, end):
        start, end = int2dt(start), int2dt(end)
        create_index(self.log, symbols, start, end)
        for symbol in symbols:
            self.ensure(symbol)
        self.check()
    
    def ensure(self, symbol):
        col = self.db[vt_symbol(symbol)]
        col.create_index("datetime", unique=True, background=True)
        col.create_index("date", background=True)
    
    def update(self, symbols, start, end):
        start, end = int2dt(start), int2dt(end)
        for symbol in symbols:
            last = self.latest(symbol)
            if start < last:
                start = last
            create_index(self.log, [symbol], start, end)

    def latest(self, symbol):
        doc = self.log.find_one({"symbol": symbol}, sort=[("start", -1)])
        if doc:
            return doc["start"]
        else:
            return 0

    def find(self):
        docs = list(self.log.find({"count": 0}, {"_id": 0}))
        for doc in docs:
            yield doc["symbol"], doc["start"], doc["end"]

    def publish(self, retry=3):
        docs = list(self.find())
        total = len(docs)
        count = 0
        now = datetime.now()
        for symbol, start, end, in docs:
            if end > now:
                logging.warning("handle require | %s | %s | %s | end > now(%s)", symbol, start, end, now)
                count += 1
                continue
            i, c = self.handle(symbol, start, end)
            if i:
                count += 1
            logging.warning("handle require | %s | %s | %s | %s | %s", symbol, start, end, c, i)
        if retry:
            if count < total:
                self.publish(retry-1)

    def handle(self, symbol, start, end, **kwargs):
        vtSymbol = vt_symbol(symbol)
        try:
            frame = get_hist_1min(symbol, "1m", dt2mts(start), dt2mts(end), limit=LIMIT)
        except Exception as e:
            logging.error("query data | %s | %s | %s | %s", symbol, start, end, e)
            return 0, 0
        count = len(frame.index)
        if count:
            frame = vnpy_format(frame, symbol, vtSymbol)
            col = self.db[vtSymbol]
            try:
                inserted = _insert(col, frame)
            except Exception as e:
                logging.error("insert data | %s | %s | %s | %s", symbol, start, end, e)
                return
        else:
            inserted = 0
            count = -1
        self.fill(symbol, start, end, count, inserted)
        return inserted, count

    def fill(self, symbol, start, end, count, fill):
        flt = {"symbol": symbol, "start": start, "end": end} 
        to_set = {"$set": {"count": count}, "$inc": {"fill": fill}}
        try:
            self.log.update_one(
                flt,
                to_set
            )
        except Exception as e:
            logging.error("update log | %s | %s | %s | %s", symbol, start, end, e)
        else:
            logging.debug("update log | %s | %s | %s | count=%s, fill=%s", symbol, start, end, count, fill)
        

def vt_symbol(symbol):
    return "%s:binance" % symbol


def _insert(collection, frame):
    assert isinstance(collection, Collection)
    assert isinstance(frame, pd.DataFrame)
    if frame.index.name is not None:
        frame = frame.reset_index()
    count = 0
    for doc in frame.to_dict("record"):
        try:
            collection.insert_one(doc)
        except DuplicateKeyError:
            pass
        else:
            count += 1
    return count


def history(filename=FILENAME, commands=None):
    init(filename)
    target = CONF["target"]
    storage = MongoDBStorage(**CONF["mongodb"])
    if not commands:
        commands = ["create", "publish"]
    logging.warning("commands: %s", commands)
    start = target["start"]
    end = target.get("end", today())
    for command in commands:
        if command == "update":
            storage.update(target["symbol"], start, end)
        elif command == "publish":
            storage.publish(target["retry"])
        elif command == "create":
            storage.create(target["symbol"], start, end)


def today():
    date = datetime.now()
    return date.year * 10000 + date.month*100 + date.day


class StreamBars(object):

    def __init__(self, symbol, limit=LIMIT):
        self.symbol = symbol
        self.limit = limit

    def get_last(self):
        raise NotImplementedError()
    
    def handle(self, bars):
        raise NotImplementedError()
    
    def next_bars(self, retry=3, recursion=100):
        if recursion == 0:
            logging.warning("request next bars | left retry chance 0 | exit")
            return 
        try:
            last = self.get_last()
        except Exception as e:
            return 

        try:
            bars = get_hist_1min(self.symbol, "1m", last, limit=self.limit)
            self.handle(bars)
        except Exception as e:
            logging.error("request next bars | %s | %s | %s | %s", self.symbol, last, self.limit, e)
            if retry == 0:
                logging.error("request next bars | left retry chance 0 | exit")
            else:
                self.next_bars(retry-1, recursion-1)
        else:
            logging.warning("request next bars | %s | %s | %s | %s", self.symbol, last, self.limit, len(bars))
            if len(bars) >= self.limit:
                self.next_bars(retry, recursion-1)


from pymongo.collection import Collection


class MongodbStreamBars(StreamBars):

    def __init__(self, collection, symbol, limit=LIMIT, default_start=None):
        assert isinstance(collection, Collection)
        self.collection = collection
        super(MongodbStreamBars, self).__init__(symbol, limit)
        self._default = default_start if default_start else int(datetime.now().timestamp()*1000 - 7*24*60*60*1000) 

    def get_last(self):
        doc = self.collection.find_one(sort=[("datetime", -1)])
        if doc:
            return int(doc["datetime"].timestamp()*1000)
        else:
            return self._default
    
    def handle(self, bars):
        if len(bars) == 0:
            return
        data = vnpy_format(bars, self.symbol)
        for doc in data.to_dict("record"):
            try:
                self.collection.update_one({"datetime": doc["datetime"]}, {"$set": doc}, upsert=True)
            except Exception as e:
                logging.error("write bar | %s | %s | %s", self.symbol, doc, e)


def stream(filename):
    init(filename)
    mongodb = CONF["mongodb"]
    client = MongoClient(mongodb["host"])
    db = client[mongodb["db"]]
    tables = db.collection_nams()
    for symbol in CONF["data"]["target"]:
        name = vt_symbol(symbol)
        if name not in tables:
            col = db.create_collection(name, capped=True, size=2**25)
            col.create_index("datetime", unique=True, background=True)
            col.create_index("date", background=True)
        else:
            col = db[name]
        msb = MongodbStreamBars(col, symbol)
        msb.next_bars()


def main():
    import sys
    history(commands=sys.argv[1:])


if __name__ == '__main__':
    main()
