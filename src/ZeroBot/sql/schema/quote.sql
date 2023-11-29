CREATE TABLE IF NOT EXISTS quote (
    quote_id INTEGER NOT NULL,
    submitter INTEGER NOT NULL DEFAULT 0,
    submission_date DATETIME DEFAULT CURRENT_TIMESTAMP,
    style INTEGER NOT NULL DEFAULT 1,
    hidden BOOLEAN NOT NULL DEFAULT 0 CHECK (hidden IN (0,1)),
    PRIMARY KEY (quote_id)
    FOREIGN KEY (submitter)
        REFERENCES participants (participant_id)
        ON DELETE SET DEFAULT
);

CREATE TABLE IF NOT EXISTS quote_lines (
    quote_id INTEGER NOT NULL,
    line_num INTEGER NOT NULL DEFAULT 1,
    line TEXT NOT NULL,
    participant_id INTEGER NOT NULL DEFAULT 0,
    author_num INTEGER NOT NULL DEFAULT 1,
    action BOOLEAN NOT NULL DEFAULT 0 CHECK (action IN (0,1)),
    PRIMARY KEY (quote_id, line_num),
    FOREIGN KEY (quote_id) REFERENCES quote (quote_id)
        ON DELETE CASCADE,
    FOREIGN KEY (participant_id) REFERENCES participants (participant_id)
        ON DELETE SET DEFAULT
        ON UPDATE CASCADE
) WITHOUT ROWID;

-- Views

CREATE VIEW IF NOT EXISTS quote_leaderboard AS
SELECT
    authors.name AS Name,
    COUNT(DISTINCT quote_id) AS "Number of Quotes",
    ifnull(numsubs, 0) AS "Number of Submissions",
    ROUND(100.0 * COUNT(DISTINCT quote_id) / (SELECT COUNT(*) FROM quote), 1) || '%' AS "Quote %",
    ROUND(100.0 * ifnull(numsubs, 0) / (SELECT COUNT(*) FROM quote), 1) || '%' AS "Submission %"
FROM quote_lines
JOIN participants AS authors USING (participant_id)
LEFT JOIN (
    SELECT name, COUNT(quote_id) AS numsubs
    FROM quote
    JOIN participants ON participant_id = submitter
    GROUP BY submitter
) AS submissions ON authors.name = submissions.name
GROUP BY authors.name;

CREATE VIEW IF NOT EXISTS quote_merged AS
SELECT
    quote_id AS "Quote ID",
    line_num AS "Line #",
    authors.name AS Author,
    line AS Line,
    submission_date AS "Submission Date",
    submitters.name AS "Submitter",
    action AS "Action?",
    style AS Style,
    hidden AS "Hidden?"
FROM quote
JOIN quote_lines USING (quote_id)
JOIN participants AS submitters ON submitter = submitters.participant_id
JOIN participants AS authors USING (participant_id);

CREATE VIEW IF NOT EXISTS quote_stats_global AS
WITH self AS (
    SELECT quote_id, 1 AS selfsub
    FROM quote
    JOIN quote_lines USING (quote_id)
    GROUP BY quote_id
    HAVING submitter = participant_id AND COUNT(line_num) = 1
)
SELECT
    COUNT(DISTINCT top.quote_id) AS "Number of Quotes",
    COUNT(DISTINCT submitter) AS "Number of Submitters",
    COUNT(selfsub) AS "Self-Submissions",
    ROUND(100.0 * COUNT(selfsub) / COUNT(DISTINCT top.quote_id), 1) || '%' AS "Self-Sub %",
    "Quotes in Year" AS "Quotes this Year",
    "Avg. Yearly Quotes"
FROM quote AS top
LEFT JOIN self ON top.quote_id = self.quote_id
JOIN quote_yearly_quotes ON Year = strftime('%Y', 'now')
JOIN (
    SELECT AVG("Quotes in Year") AS "Avg. Yearly Quotes"
    FROM quote_yearly_quotes
) AS avg;

CREATE VIEW IF NOT EXISTS quote_stats_user AS
WITH submissions AS (
    SELECT name, COUNT(quote_id) AS numsubs
    FROM quote
    JOIN participants ON participant_id = submitter
    GROUP BY submitter
),
self AS (
    SELECT quote_id, 1 AS selfsub
    FROM quote
    JOIN quote_lines USING (quote_id)
    GROUP BY quote_id
    HAVING submitter = participant_id AND COUNT(line_num) = 1
),
year_quotes AS (
    SELECT
        name,
        COUNT(DISTINCT quote_id) AS "Quotes in Year",
        strftime('%Y', submission_date) AS Year
    FROM quote
    JOIN quote_lines USING (quote_id)
    JOIN participants USING (participant_id)
    GROUP BY name, Year
),
year_subs AS (
    SELECT
        name,
        COUNT(DISTINCT quote_id) AS "Submissions in Year",
        strftime('%Y', submission_date) AS Year
    FROM quote
    JOIN participants ON submitter = participant_id
    GROUP BY name, Year
),
avg_year_quotes AS (
    SELECT name, AVG("Quotes in Year") AS "Avg. Yearly Quotes"
    FROM year_quotes
    GROUP BY name
),
avg_year_subs AS (
    SELECT name, AVG("Submissions in Year") AS "Avg. Yearly Subs"
    FROM year_subs
    GROUP BY name
)
SELECT
    authors.name AS Name,
    "Number of Quotes",
    ROUND(100.0 * COUNT(DISTINCT top.quote_id) / (SELECT COUNT(*) FROM quote), 1) || '%' AS "Quote %",
    "Number of Submissions",
    ROUND(100.0 * ifnull(numsubs, 0) / (SELECT COUNT(*) FROM quote), 1) || '%' AS "Submission %",
    COUNT(selfsub) AS "Self-Submissions",
    ROUND(100.0 * COUNT(selfsub) / COUNT(DISTINCT top.quote_id), 1) || '%' AS "Self-Sub %",
    ifnull("Quotes in Year", 0) AS "Quotes this Year",
    ifnull("Submissions in Year", 0) AS "Submissions this Year",
    ROUND(ifnull("Avg. Yearly Quotes", 0), 2) AS "Avg. Yearly Quotes",
    ROUND(ifnull("Avg. Yearly Subs", 0), 2) AS "Avg. Yearly Subs"
FROM quote AS top
JOIN quote_lines USING (quote_id)
JOIN participants AS authors USING (participant_id)
JOIN quote_leaderboard AS lb ON authors.name = lb.name
LEFT JOIN submissions ON authors.name = submissions.name
LEFT JOIN self ON top.quote_id = self.quote_id
LEFT JOIN year_quotes ON year_quotes.name = authors.name AND year_quotes.Year = strftime('%Y', 'now')
LEFT JOIN year_subs ON year_subs.name = authors.name AND year_subs.Year = strftime('%Y', 'now')
LEFT JOIN avg_year_quotes AS "ayq" ON ayq.name = authors.name
LEFT JOIN avg_year_subs AS "ays" ON ays.name = authors.name
GROUP BY authors.name;

CREATE VIEW IF NOT EXISTS quote_yearly_quotes AS
SELECT
    COUNT(quote_id) AS "Quotes in Year",
    strftime('%Y', submission_date) AS Year
FROM quote
GROUP BY Year;
