-- Phase 0: enable TimescaleDB. The durable schema (securities, market_bar hypertable,
-- feature/score snapshots, events, watchlists, audits) is created by migrations in
-- Phase 1+. Keeping schema out of init.sql lets migrations own it from the start.
CREATE EXTENSION IF NOT EXISTS timescaledb;
