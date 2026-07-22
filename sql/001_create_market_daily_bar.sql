CREATE TABLE IF NOT EXISTS market_daily_bar (
    id                BIGSERIAL PRIMARY KEY,
    symbol            VARCHAR(20)     NOT NULL,--    股票/标的代码（如 AAPL）
    con_id            BIGINT,--                      IBKR 合约 ID（合约全局唯一标识，可空）
    security_type     VARCHAR(10)     NOT NULL,--    证券类型（如 STK-股票、OPT-期权、FUT-期货）
    exchange          VARCHAR(20)     NOT NULL,--    路由/交易所（如 SMART）
    primary_exchange  VARCHAR(20)     NOT NULL,--    首选/上市交易所（如 NASDAQ、NYSE）
    currency          VARCHAR(10)     NOT NULL,--    结算计价货币（如 USD）
    trade_date        DATE            NOT NULL,--    交易日期（YYYY-MM-DD）
    open_price        NUMERIC(20, 8)  NOT NULL,--    开盘价（高精度数值）
    high_price        NUMERIC(20, 8)  NOT NULL,--    最高价
    low_price         NUMERIC(20, 8)  NOT NULL,--    最低价
    close_price       NUMERIC(20, 8)  NOT NULL,--    收盘价
    volume            BIGINT          NOT NULL,--    成交量（成交股数/手）
    wap               NUMERIC(20, 8),--              加权平均价（VWAP，可空）大部分资金真实成交的平均成本线
    bar_count         INTEGER,--                     成交笔数（可空）
    what_to_show      VARCHAR(30)     NOT NULL,--    行情数据类型（如 TRADES实际成交数据、MIDPOINT中间价数据、BID买一价、ASK卖一价、BID_ASK买卖差价、HISTORICAL_VOLATILITY历史波动率、OPTION_IMPLIED_VOLATILITY期权隐含波动率）
    source            VARCHAR(20)     NOT NULL,--    数据来源标识（如 IBKR）
    created_at        TIMESTAMPTZ     NOT NULL DEFAULT now(),-- 记录创建时间（带时区）
    updated_at        TIMESTAMPTZ     NOT NULL DEFAULT now(),-- 记录更新时间（带时区）
    CONSTRAINT uq_market_daily_bar_symbol_date_type UNIQUE (symbol, trade_date, what_to_show)-- 唯一约束：标的+日期+行情类型组合唯一
);

CREATE INDEX IF NOT EXISTS idx_market_daily_bar_symbol_date -- 索引名称与存在性检查
ON market_daily_bar (symbol, trade_date DESC);
