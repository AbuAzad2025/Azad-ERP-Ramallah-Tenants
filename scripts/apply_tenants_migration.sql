-- garage_manager ONLY — جدول tenants + دمج alembic head
-- لا يُنفَّذ على قواعد أخرى.

CREATE TABLE IF NOT EXISTS public.tenants (
    id SERIAL PRIMARY KEY,
    slug VARCHAR(60) NOT NULL,
    schema_name VARCHAR(63) NOT NULL,
    display_name VARCHAR(200),
    domain VARCHAR(255),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_tenants_slug UNIQUE (slug),
    CONSTRAINT uq_tenants_schema_name UNIQUE (schema_name),
    CONSTRAINT uq_tenants_domain UNIQUE (domain)
);

CREATE INDEX IF NOT EXISTS ix_tenants_slug ON public.tenants (slug);
CREATE INDEX IF NOT EXISTS ix_tenants_schema_name ON public.tenants (schema_name);
CREATE INDEX IF NOT EXISTS ix_tenants_is_active ON public.tenants (is_active);

-- دمج الرأسين: 94948c531c03 + b2c3d4e5f6a7 -> c4d5e6f7a8b9
-- بعد ذلك نفّذ: flask db upgrade  (حتى g1h2i3j4k5l6)
UPDATE public.alembic_version SET version_num = 'c4d5e6f7a8b9'
WHERE version_num IN ('94948c531c03', 'b2c3d4e5f6a7');

INSERT INTO public.alembic_version (version_num)
SELECT 'c4d5e6f7a8b9'
WHERE NOT EXISTS (SELECT 1 FROM public.alembic_version);
