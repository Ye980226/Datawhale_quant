from jaqs.data import DataApi
from pymongo import MongoClient
from pymongo.database import Database, Collection
from pymongo.errors import DuplicateKeyError
from datetime import datetime, timedelta
import pandas as pd
import logging
import traceback
from itertools import product
from utils.conf import load
import os


FILENAME = os.environ.get("JQM1", os.path.join(os.path.dirname(__file__), "conf.yml"))
CALENDAR = os.path.join(os.path.dirname(__file__), "calendar.csv")


def get_today():
    t = datetime.now()
    return t.year*10000 + t.month*100 + t.day


CONF = {
    "login": {
        "addr": "tcp://data.quantos.org:8910",
        "username": "",
        "password": ""
    },
    "mongodb": {
        "host": "localhost:27017",
        "db": "VnTrader_1Min_Db",
        "log": "log.jqm1",
        "latest": "VnTrader_1Min_Db_latest"
    },
    "history": {
        "start": 20180101,
        "end": get_today(),
        "symbols": []
    },
}


def init(filename=FILENAME):
    load(filename, CONF)


def get_api():
    login = CONF["login"]
    api = DataApi(login["addr"])
    api.login(login["username"], login["password"])
    return api


def get_mongodb_storage():
    mongodb = CONF["mongodb"]
    log = mongodb["log"].split(".")
    client = MongoClient(mongodb["host"])
    jqindex = MongodbJQIndex(client[log[0]][log[1]])
    writer = MongoDBWriter(client[mongodb["db"]])
    return jqindex, writer


def get_mongodb_latest():
    mongodb = CONF["mongodb"]
    return MongoDBWriter(
        MongoClient(mongodb["host"])[mongodb["latest"]]
    )


def get_framework():
    history = CONF["history"]
    api = get_api()
    index, writer = get_mongodb_storage()
    return FrameWork(api, index, writer, history["symbols"], CALENDAR)


class JQIndex(object):

    def create(self, symbol, date):
        pass
    
    def find(self, symbol, start, end, count=0, insert=0):
        pass
    
    def fill(self, symbol, date, count, insert):
        pass
    
    def latest(self, symbol):
        pass


class Writer(object):

    def write(self, symbol, data):
        pass

    def create(self, symbols):
        pass
    
    def count(self, symbol, date):
        pass
    
    def last(self, symbol):
        pass


def not_empty(item):
    if item[1]:
        return True
    else:
        return False

def join(item):
    return "%s=%s" % item


class FrameWork(object):

    def __init__(self, api, index, writer, symbols, calendar=None):
        assert isinstance(api, DataApi)
        assert isinstance(index, JQIndex)
        assert isinstance(writer, Writer)
        self.api = api
        self.index = index
        self.writer = writer
        self.symbols = symbols
        self.calendar = self.create_calendar(calendar)

    def query(self, view, fields="", **filters):
        ft = "&".join(map(join, filter(not_empty, filters.items())))
        data, msg = self.api.query(view, ft, fields)
        if msg == "0,":
            return data
        else:
            raise ValueError(msg)

    def get_trade_days(self, start=None, end=None):
        return self.calendar.loc[start:end]
    
    def create_calendar(self, calendar):
        if isinstance(calendar, str) and os.path.isfile(calendar):
            data = pd.read_csv(calendar)["trade_date"]
        elif isinstance(calendar, pd.Series):
            data = calendar
        else:
            data = self.query_trade_days()
        return pd.Series(data.values, data.values).sort_index()

    def query_trade_days(self):
        dates = self.query("jz.secTradeCal")
        return dates["trade_date"].apply(int)
    
    def get_m1_daily(self, symbol, date):
        data, msg = self.api.bar(symbol, trade_date=date)
        if msg == "0,":
            return vnpy_format(data, symbol)
        else:
            raise ValueError(msg)
    
    def check(self):
        for symbol, date in self.index.find(count=0):
            count = self.writer.count(symbol, date)
            if count > 0:
                self.index.fill(symbol, date, count, count)
                logging.warning("check | %s | %s | %s ", symbol, date, count)

    def publish(self):
        today = get_today()
        for symbol, date in self.index.find(count=0):
            if date == today:
                if datetime.now().hour < 17:
                    logging.warning("publish | %s | %s | data not ready", symbol, date)
                    continue
            self.handle(symbol, date)

    def create(self, symbols=None, start=None, end=None):
        if not symbols:
            symbols = self.symbols
        for symbol, date in product(symbols, self.get_trade_days(start, end)):
            self.index.create(symbol, date)
        self.writer.create(symbols)
        self.check()

    def update(self, symbols=None, start=None, end=None):
        if not symbols:
            symbols = self.symbols
        for symbol in symbols:
            last = self.index.latest(symbol)
            if not last:
               last = start
            for date in self.get_trade_days(last, end):
                self.index.create(symbol, date)

    def handle(self, symbol, date):
        try:
            data = self.get_m1_daily(symbol, date)
        except Exception as e:
            logging.error("query bar | %s | %s | %s", symbol, date, e)
            traceback.print_exc()
            return
        
        if not isinstance(data, pd.DataFrame):
            logging.error("query bar | %s | %s | invalid result: %s", symbol, date, data)
            return
        
        count = len(data)
        if count:
            try:
                insert = self.writer.write(symbol, data)
            except Exception as e:
                logging.error("write bar | %s | %s | %s", symbol, date, e)
                traceback.print_exc()
                return
        else:
            if date < get_today():
                count = -1
            insert = 0
            
        
        try:
            self.index.fill(symbol, date, count, insert)
        except Exception as e:
            logging.error("fill index | %s | %s | %s", symbol, date, e)
            traceback.print_exc()
            return
        else:
            logging.warning("download bar | %s | %s | %s | %s", symbol, date, count, insert)


def vt_symbol(symbol):
    return symbol.replace(".", ":")


def dt2date(dt):
    return dt.strftime("%Y%m%d")


def dt2time(dt):
    return dt.strftime("%H:%M:%S")


BAR_COLUMN = ["vtSymbol", "symbol", "exchange", "open", "high", "low", "close", "date", "time", "datetime", "volume", "openInterest"]


def vnpy_format(data, symbol):
    assert isinstance(data, pd.DataFrame)
    data["datetime"] = list(map(make_time, data["date"], data['time']))
    data["datetime"] = data["datetime"] - timedelta(minutes=1)
    data["date"] = data["datetime"].apply(dt2date)    
    data["time"] = data["datetime"].apply(dt2time)    
    data["vtSymbol"] = vt_symbol(symbol)
    data["symbol"], data["exchange"] = symbol.split(".")
    data["openInterest"] = data["oi"].fillna(0)
    return data[BAR_COLUMN]
    


class MongodbJQIndex(JQIndex):

    SYMBOL = "_s"
    DATE = "_d"
    COUNT = "_c"
    INSERT = "_i"
    MODIFY = "_m"

    def __init__(self, collection):
        assert isinstance(collection, Collection)
        self.collection = collection
        self.collection.create_index([(self.SYMBOL, 1), (self.DATE, 1)], unique=True, background=True)
        self.collection.create_index(self.COUNT)
        self.collection.create_index(self.INSERT)
    
    def create(self, symbol, date):
        doc = {
            self.SYMBOL: symbol,
            self.DATE: int(date),
            self.COUNT: 0,
            self.INSERT: 0,
            self.MODIFY: datetime.now()
        }
        try:
            self.collection.insert_one(doc)
        except DuplicateKeyError:
            logging.debug("create index | %s | %s | duplicated", symbol, date)
        else:
            logging.debug("create index | %s | %s | ok", symbol, date)

    def find(self, symbol=None, start=None, end=None, count=None, insert=None):
        ft = {}
    
        if symbol:
            if isinstance(symbol, list):
                ft[self.SYMBOL] = {"$in": symbol}
            else:
                ft[self.SYMBOL] = symbol
        if start:
            ft[self.DATE] = {"$gte": start}
        if end:
            ft.setdefault(self.DATE, {})["$lte"] = end
        if count is not None:
            ft[self.COUNT] = count
        if insert is not None:
            ft[self.INSERT] = insert
        
        cursor = self.collection.find(ft, [self.SYMBOL, self.DATE])
        for doc in list(cursor):
            yield doc[self.SYMBOL], doc[self.DATE]
        
    def fill(self, symbol, date, count, insert):
        ft = {self.SYMBOL: symbol, self.DATE: date}
        upd = {self.COUNT: count, self.INSERT: insert, self.MODIFY: datetime.now()}
        try:
            result = self.collection.update_one(ft, {"$set": upd})
        except Exception as e:
            logging.error("update index | %s | %s | %s", symbol, date, e)
        else:
            logging.debug("update index | %s | %s | %s", symbol, date, result.modified_count)

    def latest(self, symbol):
        ft = {self.SYMBOL: symbol}
        doc = self.collection.find_one(ft, sort=[(self.DATE, -1)])
        if doc:
            return doc[self.DATE]


class MongoDBWriter(Writer):

    def __init__(self, db):
        assert isinstance(db, Database)
        self.db = db
    
    def create(self, symbols):
        for symbol in symbols:
            col = self.get_collection(symbol)
            col.create_index("datetime", unique=True, background=True)
            col.create_index("date", background=True)
    
    def get_collection(self, symbol):
        return self.db[vt_symbol(symbol)]

    def write(self, symbol, data):
        col = self.get_collection(symbol)
        count = 0
        for doc in data.to_dict("record"):
            try:
                col.insert_one(doc)
            except DuplicateKeyError:
                pass
            else:
                count += 1
        return count

    def count(self, symbol, date):
        col = self.get_collection(symbol)
        return col.find({"date": str(date)}).count()
    
    def last(self, symbol):
        doc = self.get_collection(symbol).find_one(sort=[("datetime", -1)])
        if doc:
            return int(doc["date"])
        else:
            return None
            

def split(num, d=100, left=3):
    while num >= d and (left > 1):
        yield num % d
        num = int(num/d)
        left -= 1
    else:
        for i in range(left):
            yield num
            num = 0


def make_time(date, time):
    day, month, year = tuple(split(date))
    second, minute, hour = tuple(split(time))
    return datetime(year, month, day, hour, minute, second)


def test_index():
    logging.basicConfig(level=logging.DEBUG)
    col = MongoClient("192.168.0.105:37017")["log"]["JQM1"]
    jqindex = MongodbJQIndex(col)
    # jqindex.create("cu.SHF", 20180920)
    for symbol, date in jqindex.find(count=0):
        print(symbol, date)


def latest(symbol, length, writer, framework):
    assert isinstance(writer, Writer)
    assert isinstance(framework, FrameWork)
    start = writer.last(symbol)
    end = get_today()
    dates = framework.get_trade_days(start, end).iloc[:-1].values
    tables = list(reversed(list(iter_bars(symbol, dates, length, framework))))
    data = pd.concat(tables, ignore_index=True)
    count = writer.write(symbol, data)
    logging.warning("refresh data | %s | %s", symbol, count)
    

def iter_bars(symbol, dates, length, fw):
    count = 0
    data = fw.get_m1_daily(symbol, 0)
    data = data[data["volume"]>0]
    count += len(data)
    if count > 0:
        yield data
        logging.warning("get bars | %s | %s", symbol, 0)
    for date in reversed(dates):
        if count >= length:
            return
        data = fw.get_m1_daily(symbol, date)
        count += len(data)
        if len(data) > 0:
            yield data
        logging.warning("get bars | %s | %s", symbol, date)


def command(filename=FILENAME, commands=None):
    init(filename)
    histroy = CONF["history"]
    fw = get_framework()
    if not commands:
        commands = ["create", "publish"]
    
    for cmd in commands:
        if cmd == "update":
            fw.update(start=histroy["start"], end=histroy["end"])
        elif cmd == "publish":
            fw.publish()
        elif cmd == "create":
            fw.create(start=histroy["start"], end=histroy["end"])
        elif cmd == "latest":
            LATEST = CONF["latest"]
            symbols = LATEST["symbols"]
            writer = get_mongodb_latest()
            writer.create(symbols)
            for symbol in symbols:
                latest(symbol, LATEST["length"], writer, fw)

            

def main():
    import sys
    command(commands=sys.argv[1:])


if __name__ == '__main__':
    main()