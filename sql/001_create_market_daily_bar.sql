CREATE TABLE IF NOT EXISTS market_daily_bar (
    id                BIGSERIAL PRIMARY KEY,
    symbol            VARCHAR(20)     NOT NULL,
    con_id            BIGINT,
    security_type     VARCHAR(10)     NOT NULL,
    exchange          VARCHAR(20)     NOT NULL,
    primary_exchange  VARCHAR(20)     NOT NULL,
    currency          VARCHAR(10)     NOT NULL,
    trade_date        DATE            NOT NULL,
    open_price        NUMERIC(20, 8)  NOT NULL,
    high_price        NUMERIC(20, 8)  NOT NULL,
    low_price         NUMERIC(20, 8)  NOT NULL,
    close_price       NUMERIC(20, 8)  NOT NULL,
    volume            BIGINT          NOT NULL,
    wap               NUMERIC(20, 8),
    bar_count         INTEGER,
    what_to_show      VARCHAR(30)     NOT NULL,
    source            VARCHAR(20)     NOT NULL,
    created_at        TIMESTAMPTZ     NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ     NOT NULL DEFAULT now(),
    CONSTRAINT uq_market_daily_bar_symbol_date_type UNIQUE (symbol, trade_date, what_to_show)
);

CREATE INDEX IF NOT EXISTS idx_market_daily_bar_symbol_date
ON market_daily_bar (symbol, trade_date DESC);
