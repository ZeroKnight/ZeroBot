CREATE TABLE users (
    user_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    creation_flags INTEGER NOT NULL DEFAULT 0,
    creation_metadata TEXT,
    comment TEXT
);

CREATE TABLE aliases (
    user_id INTEGER NOT NULL,
    alias TEXT NOT NULL,
    case_sensitive BOOLEAN NOT NULL DEFAULT 0 CHECK (case_sensitive IN (0,1)),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    creation_flags INTEGER NOT NULL DEFAULT 0,
    creation_metadata TEXT,
    comment TEXT,
    PRIMARY KEY (user_id, alias),
    FOREIGN KEY (user_id) REFERENCES users (user_id)
        ON DELETE CASCADE
);

CREATE TABLE participants (
    participant_id INTEGER NOT NULL,
    name TEXT NOT NULL UNIQUE COLLATE FOLD,
    user_id INTEGER,
    PRIMARY KEY (participant_id),
    FOREIGN KEY (user_id) REFERENCES users (user_id)
        ON DELETE SET NULL
);

CREATE UNIQUE INDEX idx_participants_user_id
ON participants (user_id);

CREATE TABLE protocols (
    identifier TEXT NOT NULL,
    name TEXT NOT NULL,
    PRIMARY KEY (identifier)
) WITHOUT ROWID;

CREATE TABLE sources (
    source_id INTEGER NOT NULL,
    protocol TEXT NOT NULL,
    server TEXT,
    channel TEXT,
    PRIMARY KEY (source_id),
    FOREIGN KEY (protocol) REFERENCES protocols (identifier)
        ON UPDATE CASCADE
);

-- Views

CREATE VIEW users_all_names (
    user_id, name, case_sensitive
) AS
    SELECT user_id, name, 1 FROM users
    UNION
    SELECT user_id, alias, case_sensitive FROM aliases;

CREATE VIEW participants_all_names (
    participant_id, user_id, name, case_sensitive
) AS
    SELECT participant_id, user_id, name, 1 FROM participants
    UNION
    SELECT participant_id, user_id, alias, case_sensitive FROM aliases
    JOIN participants USING(user_id);

-- Triggers

CREATE TRIGGER tg_update_participant_name_from_user
AFTER UPDATE OF name ON users
BEGIN
    UPDATE participants
    SET name = new.name
    WHERE user_id = new.user_id;
END;

CREATE TRIGGER tg_update_user_name_from_participant
AFTER UPDATE OF name ON participants
BEGIN
    UPDATE users
    SET name = new.name
    WHERE user_id = new.user_id;
END;

CREATE TRIGGER tg_new_user_upsert_participants
AFTER INSERT ON users
BEGIN
    INSERT INTO participants (name, user_id)
    VALUES (new.name, new.user_id)
    ON CONFLICT (name) DO UPDATE
        SET user_id = new.user_id;
END;

CREATE TRIGGER tg_prevent_linked_participant_delete
BEFORE DELETE ON participants
BEGIN
    SELECT RAISE(FAIL, 'Can''t delete participant that is linked to a user')
    FROM participants
    WHERE participant_id = old.participant_id
        AND user_id IS NOT NULL;
END;
