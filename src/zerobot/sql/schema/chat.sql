CREATE TABLE IF NOT EXISTS chat_activity (
    activity TEXT NOT NULL,
    type INTEGER NOT NULL DEFAULT 1,
    emoji TEXT,
    details TEXT,
    submitter INTEGER NOT NULL DEFAULT 0,
    date_added DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (activity, type),
    FOREIGN KEY (submitter) REFERENCES participants (participant_id)
        ON UPDATE CASCADE
        ON DELETE SET DEFAULT
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS chat_badcmd (
    phrase TEXT NOT NULL UNIQUE,
    action BOOLEAN NOT NULL DEFAULT 0 CHECK (action IN (0,1)),
    error_type INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (phrase)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS chat_berate (
    phrase TEXT NOT NULL UNIQUE,
    action BOOLEAN NOT NULL DEFAULT 0 CHECK (action IN (0,1)),
    PRIMARY KEY (phrase)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS chat_greetings (
    phrase TEXT NOT NULL UNIQUE,
    action BOOLEAN NOT NULL DEFAULT 0 CHECK (action IN (0,1)),
    PRIMARY KEY (phrase)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS chat_mentioned (
    phrase TEXT NOT NULL UNIQUE,
    action BOOLEAN NOT NULL DEFAULT 0 CHECK (action IN (0,1)),
    PRIMARY KEY (phrase)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS chat_questioned (
    phrase TEXT NOT NULL UNIQUE,
    action BOOLEAN NOT NULL DEFAULT 0 CHECK (action IN (0,1)),
    response_type INTEGER NOT NULL,
    PRIMARY KEY (phrase)
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS idx_chat_questioned_response_type
ON chat_questioned (response_type ASC);
