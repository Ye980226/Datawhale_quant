# encoding: UTF-8

# 重载sys模块，设置默认字符串编码方式为utf8
import sys


# 判断操作系统
import platform
system = platform.system()

# vn.trader模块
from vnpy.event import EventEngine
from vnpy.trader.vtEngine import MainEngine
from vnpy.trader.uiQt import createQApp
from vnpy.trader.uiMainWindow import MainWindow

# 加载底层接口
from vnpy.trader.gateway import (okexfGateway,huobiGateway,binanceGateway,ctpGateway)

# 加载上层应用
from vnpy.trader.app import (riskManager, 
                            ctaStrategy,
                            #algoTrading,
                            # dataRecorder,
                            # spreadTrading,
                            # optionMaster,
                            # jaqsService,
                            # rpcService
                            )


#----------------------------------------------------------------------
def main():
    """主程序入口"""
    # 创建Qt应用对象
    qApp = createQApp()

    # 创建事件引擎
    ee = EventEngine()

    # 创建主引擎
    me = MainEngine(ee)

    # 添加交易接口
    me.addGateway(okexfGateway)
    me.addGateway(huobiGateway)
    me.addGateway(binanceGateway)
    me.addGateway(ctpGateway)

    # 添加上层应用
    me.addApp(riskManager)
    me.addApp(ctaStrategy)
    #me.addApp(algoTrading)
    # me.addApp(dataRecorder)
    # me.addApp(spreadTrading)
    # me.addApp(optionMaster)
    # me.addApp(jaqsService)
    # me.addApp(rpcService)


    # 创建主窗口
    mw = MainWindow(me, ee)
    mw.showMaximized()

    # 在主线程中启动Qt事件循环
    sys.exit(qApp.exec_())


if __name__ == '__main__':
    main()
