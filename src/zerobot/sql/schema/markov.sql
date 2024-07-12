CREATE TABLE IF NOT EXISTS markov_corpus (
    line_id INTEGER NOT NULL,
    line TEXT NOT NULL,
    source INTEGER,
    author INTEGER,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (line_id),
    FOREIGN KEY (source) REFERENCES sources (source_id)
        ON UPDATE CASCADE
        ON DELETE SET NULL,
    FOREIGN KEY (author) REFERENCES participants (participant_id)
        ON UPDATE CASCADE
        ON DELETE SET NULL
);
