-- PostgreSQL schema for application tables (apply manually or via migration tooling).
-- Source of truth for DDL; SQLAlchemy maps to these tables only (no ORM create_all).

-- postgresql://postgres:Rokowins@2027@db.olsjzrqlasbdsvokkrna.supabase.co:5432/postgres?sslmode=require




CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    role TEXT,
    team TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);




