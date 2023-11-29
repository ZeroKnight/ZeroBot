CREATE TABLE IF NOT EXISTS magic8ball (
    response TEXT NOT NULL UNIQUE,
    action BOOLEAN NOT NULL DEFAULT 0 CHECK (action IN (0,1)),
    response_type INTEGER DEFAULT 1,
    expects_action BOOLEAN CHECK (expects_action IN (NULL,0,1)),
    PRIMARY KEY (response)
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS idx_magic8ball_response_type
ON magic8ball (response_type ASC);
