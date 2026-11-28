-- ETL warehouse for observations, created alongside Airflow's metadata DB.
-- Runs once, on the first start of an empty Postgres volume.
-- Local development credentials only; the server listens on loopback.
CREATE USER airwatch WITH PASSWORD 'airwatch';
CREATE DATABASE airwatch OWNER airwatch;
