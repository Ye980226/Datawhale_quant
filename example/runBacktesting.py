# encoding: UTF-8
"""
展示如何执行策略回测。
"""
from __future__ import division
from vnpy.trader.app.ctaStrategy.ctaBacktesting import BacktestingEngine
from vnpy.trader.app.ctaStrategy.ctaBase import *
import os
if __name__ == '__main__':
    from StrategyBollBand import BollBandsStrategy
    
    # 创建回测引擎
    engine = BacktestingEngine()

    # 设置引擎的回测模式为K线
    engine.setBacktestingMode(engine.BAR_MODE)
    # 设置使用的历史数据库
    engine.setDatabase(MINUTE_DB_NAME)

    # 设置回测用的数据起始日期，initHours 默认值为 0
    engine.setStartDate('20180101 06:00',initHours=1)   
    engine.setEndDate('20181101 08:00')
    # 设置产品相关参数
    engine.setCapital(1000000)  # 设置起始资金，默认值是1,000,000
    engine.setSlippage(0.2)     # 股指1跳
    engine.setRate(0.3/10000)   # 万0.3
    engine.setSize(300)         # 股指合约大小 
    engine.setPriceTick(0.2)    # 股指最小价格变动
    
    # 策略报告默认不输出，默认文件夹生成于当前文件夹下
    dirname=os.path.dirname(os.path.abspath(__file__))
    
    engine.setLog(True,os.path.join(dirname,"log"))        # 设置是否输出日志和交割单, 默认值是不输出False
    engine.setCachePath(os.path.join(dirname,"Cache")) # 设置本地数据缓存的路径，默认存在用户文件夹内
    
    # 在引擎中创建策略对象
    d = {'symbolList':['EOSUSDT:binance']}
    engine.initStrategy(BollBandsStrategy, d)
    
    # 开始跑回测
    engine.runBacktesting()

    # 显示回测结果
    engine.showBacktestingResult()
    engine.showDailyResult()