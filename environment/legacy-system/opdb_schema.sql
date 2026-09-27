create table customers (
    id              bigint primary key,
    email           varchar not null,
    segment         varchar not null,
    region          varchar not null,
    deleted_at      timestamp,
    last_login_ip   varchar
);
create table orders (
    id              bigint primary key,
    customer_id     bigint,
    guest_email     varchar,
    channel         varchar,
    placed_at       timestamp not null,
    total_eur       decimal(18,2) not null,
    status          varchar not null,
    promo_id        varchar
);
create table order_lines (
    id              bigint primary key,
    order_id        bigint not null,
    sku             varchar not null,
    quantity        integer not null,
    unit_price_minor bigint not null,
    discount_minor  bigint not null,
    currency        varchar(3) not null,
    net_eur         decimal(18,2) not null
);
create table payments (
    id              bigint primary key,
    order_id        bigint not null,
    kind            varchar not null,
    amount_minor    bigint not null,
    currency        varchar(3) not null,
    amount_eur      decimal(18,2) not null,
    occurred_at     timestamp not null,
    recorded_at     timestamp not null
);
create table order_lifecycle (
    id              bigint primary key,
    order_id        bigint not null,
    state           varchar not null,
    changed_at      timestamp not null
);
create table promo_applications (
    order_id        bigint not null,
    seq             integer not null,
    promo_code      varchar not null,
    applied_at      timestamp not null,
    removed_at      timestamp
);
create table shipments (
    id              bigint primary key,
    order_id        bigint not null,
    shipped_at      timestamp not null,
    cancelled_at    timestamp
);
create table products (
    sku             varchar primary key,
    name            varchar not null,
    category        varchar not null
);
create table fx_rates (
    date            date not null,
    currency        varchar(3) not null,
    rate_to_eur     decimal not null,
    primary key (date, currency)
);
