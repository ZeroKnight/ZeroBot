CREATE TABLE IF NOT EXISTS obit (
    participant_id INTEGER NOT NULL DEFAULT 0,
    kills INTEGER NOT NULL DEFAULT 0,
    deaths INTEGER NOT NULL DEFAULT 0,
    suicides INTEGER NOT NULL DEFAULT 0,
    last_victim INTEGER,
    last_murderer INTEGER,
    last_kill DATETIME,
    last_death DATETIME,
    PRIMARY KEY (participant_id),
    FOREIGN KEY (participant_id) REFERENCES participants (participant_id)
        ON DELETE SET DEFAULT
        ON UPDATE CASCADE,
    FOREIGN KEY (last_victim) REFERENCES participants (participant_id)
        ON DELETE SET NULL
        ON UPDATE CASCADE,
    FOREIGN KEY (last_murderer) REFERENCES participants (participant_id)
        ON DELETE SET NULL
        ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS obit_strings (
    content TEXT NOT NULL,
    type INTEGER NOT NULL DEFAULT 1,
    submitter INTEGER NOT NULL DEFAULT 0,
    date_added DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (content, type),
    FOREIGN KEY (submitter) REFERENCES participants (participant_id)
        ON DELETE SET DEFAULT
        ON UPDATE CASCADE
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS idx_obit_strings_type
ON obit_strings (type ASC);

CREATE VIEW IF NOT EXISTS obit_merged AS
SELECT
    p.name AS User,
    kills AS Kills,
    deaths AS Deaths,
    suicides AS Suicides,
    victims.name AS "Last Victim",
    last_kill AS "Last Victim Killed At",
    murderers.name AS "Last Murderer",
    last_death AS "Last Killed At"
FROM obit
JOIN participants AS p USING (participant_id)
LEFT JOIN participants AS victims ON last_victim = victims.participant_id
LEFT JOIN participants AS murderers ON last_murderer = murderers.participant_id;
