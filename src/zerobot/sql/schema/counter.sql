CREATE TABLE IF NOT EXISTS counter (
    name TEXT NOT NULL UNIQUE,
    count INTEGER NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_triggered DATETIME,
    last_user INTEGER,
    last_channel TEXT,
    PRIMARY KEY (name),
    FOREIGN KEY (last_user) REFERENCES participants (participant_id)
        ON DELETE SET NULL
        ON UPDATE CASCADE
) WITHOUT ROWID;
