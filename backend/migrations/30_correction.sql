-- 工签更正 / 换签与签发存根
-- 设计要点：
--   1. recipes 仍是“当前有效工签”的唯一指针（一版一行），换签时在同一事务内一次性更新；
--   2. recipe_issues 是每次出签的不可变存根，保存签发时采用的试条与读数快照，旧工签始终可查；
--   3. corrections 记录一次“发起更正 -> 重算 -> 达标签发/换签”的过程；
--   4. assays.readings 留存该次检验（送检/重算）所依据的读数。

ALTER TABLE assays ADD COLUMN IF NOT EXISTS readings jsonb;

CREATE TABLE IF NOT EXISTS recipe_issues (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    plate text NOT NULL REFERENCES plates(code),
    revision int NOT NULL CHECK (revision >= 1),
    assay bigint NOT NULL REFERENCES assays(id),
    wash_sec int NOT NULL CHECK (wash_sec > 0),
    signer text NOT NULL,
    sample_key text NOT NULL,
    readings jsonb NOT NULL,
    all_readings jsonb,
    state text NOT NULL DEFAULT 'current' CHECK (state IN ('current', 'replaced')),
    correction_id bigint,
    issued_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (plate, revision),
    UNIQUE (assay)
);

CREATE TABLE IF NOT EXISTS corrections (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    plate text NOT NULL REFERENCES plates(code),
    revision int NOT NULL CHECK (revision >= 2),
    reason text,
    initiator text NOT NULL,
    state text NOT NULL DEFAULT 'open' CHECK (state IN ('open', 'applied', 'cancelled')),
    from_issue bigint,
    from_assay bigint,
    to_issue bigint,
    to_assay bigint,
    created_at timestamptz NOT NULL DEFAULT now(),
    applied_at timestamptz
);

-- 旧库升级时，把已有 recipes 回填为第 1 版存根
INSERT INTO recipe_issues
    (plate, revision, assay, wash_sec, signer, sample_key, readings, state, issued_at)
SELECT r.plate, 1, r.assay, r.wash_sec, r.signer, a.sample_key,
       COALESCE(a.readings, '[]'::jsonb), 'current', r.signed_at
FROM recipes r
JOIN assays a ON a.id = r.assay
ON CONFLICT (plate, revision) DO NOTHING;

-- 每版至多一条“当前”存根：保证一次性切换后指针唯一
CREATE UNIQUE INDEX IF NOT EXISTS recipe_issues_one_current
    ON recipe_issues (plate) WHERE state = 'current';

-- 每版至多一个进行中的更正单
CREATE UNIQUE INDEX IF NOT EXISTS corrections_one_open
    ON corrections (plate) WHERE state = 'open';

CREATE INDEX IF NOT EXISTS recipe_issues_plate_order
    ON recipe_issues (plate, revision DESC, id DESC);
CREATE INDEX IF NOT EXISTS corrections_plate_order
    ON corrections (plate, id DESC);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'recipe_issues_correction_fk'
    ) THEN
        ALTER TABLE recipe_issues
            ADD CONSTRAINT recipe_issues_correction_fk
            FOREIGN KEY (correction_id) REFERENCES corrections(id);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'corrections_from_issue_fk'
    ) THEN
        ALTER TABLE corrections
            ADD CONSTRAINT corrections_from_issue_fk
            FOREIGN KEY (from_issue) REFERENCES recipe_issues(id);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'corrections_to_issue_fk'
    ) THEN
        ALTER TABLE corrections
            ADD CONSTRAINT corrections_to_issue_fk
            FOREIGN KEY (to_issue) REFERENCES recipe_issues(id);
    END IF;
END $$;
