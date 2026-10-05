"""initial schema: users, handymen, conversations, messages, tickets

Revision ID: 0001
Revises:
"""

from alembic import op

revision = "0001"
down_revision = None

CATEGORIES = "'PLUMBING','ELECTRICAL','HVAC','CARPENTRY','APPLIANCE','GENERAL'"

UPGRADE_SQL = f"""
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    role TEXT NOT NULL CHECK (role IN ('CUSTOMER','HANDYMAN','ADMIN')),
    email TEXT UNIQUE,
    phone_e164 TEXT UNIQUE,
    auth_provider TEXT,
    provider_sub TEXT,
    preferred_channel TEXT NOT NULL DEFAULT 'WEB'
        CHECK (preferred_channel IN ('WEB','SMS','WHATSAPP')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (auth_provider, provider_sub)
);

CREATE TABLE handymen (
    user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    display_name TEXT NOT NULL,
    service_zips TEXT[] NOT NULL DEFAULT '{{}}',
    rating_avg NUMERIC(3,2) NOT NULL DEFAULT 0,
    response_rate NUMERIC(3,2) NOT NULL DEFAULT 0,
    is_available BOOLEAN NOT NULL DEFAULT TRUE,
    verified_at TIMESTAMPTZ
);
CREATE INDEX idx_handymen_zips ON handymen USING GIN (service_zips);

CREATE TABLE handymen_skills (
    handyman_id UUID NOT NULL REFERENCES handymen(user_id) ON DELETE CASCADE,
    category TEXT NOT NULL CHECK (category IN ({CATEGORIES})),
    PRIMARY KEY (handyman_id, category)
);

CREATE SEQUENCE ticket_number_seq START 1024;
CREATE TABLE tickets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ticket_number BIGINT NOT NULL UNIQUE DEFAULT nextval('ticket_number_seq'),
    customer_id UUID NOT NULL REFERENCES users(id),
    category TEXT NOT NULL CHECK (category IN ({CATEGORIES})),
    issue_summary TEXT NOT NULL,
    urgency TEXT NOT NULL CHECK (urgency IN ('EMERGENCY','SAME_DAY','FLEXIBLE')),
    location_zip TEXT NOT NULL,
    severity TEXT,
    status TEXT NOT NULL DEFAULT 'DRAFT' CHECK (status IN (
        'DRAFT','OPEN','MATCHING','ASSIGNED','IN_PROGRESS','COMPLETED',
        'RATED','UNMATCHED','CANCELLED')),
    assigned_handyman_id UUID REFERENCES handymen(user_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_tickets_status ON tickets (status);
CREATE INDEX idx_tickets_customer ON tickets (customer_id);

CREATE TABLE conversations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    channel TEXT NOT NULL CHECK (channel IN ('WEB','SMS','WHATSAPP')),
    status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','CLOSED')),
    ticket_id UUID REFERENCES tickets(id),
    started_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_conversations_user ON conversations (user_id);

CREATE TABLE messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    sender TEXT NOT NULL CHECK (sender IN ('USER','BOT','HANDYMAN')),
    body TEXT NOT NULL,
    media_refs JSONB NOT NULL DEFAULT '[]',
    provider_message_id TEXT UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_messages_conv ON messages (conversation_id, created_at);
"""


def upgrade() -> None:
    for stmt in [s for s in UPGRADE_SQL.split(";\n") if s.strip()]:
        op.execute(stmt)


def downgrade() -> None:
    op.execute(
        "DROP TABLE IF EXISTS messages, conversations, tickets, handymen_skills, "
        "handymen, users CASCADE"
    )
    op.execute("DROP SEQUENCE IF EXISTS ticket_number_seq")
