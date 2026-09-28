CREATE TABLE IF NOT EXISTS claims (
  blob_sha    TEXT NOT NULL,
  id          TEXT NOT NULL,
  text        TEXT NOT NULL,
  kind        TEXT NOT NULL CHECK (kind IN ('finding','hypothesis','method','citation')),
  source_path TEXT NOT NULL,
  line_start  INTEGER NOT NULL,
  line_end    INTEGER NOT NULL,
  commit_sha  TEXT NOT NULL,
  author      TEXT NOT NULL,
  PRIMARY KEY (blob_sha, id)
);

CREATE TABLE IF NOT EXISTS branch_files (
  branch   TEXT NOT NULL,
  path     TEXT NOT NULL,
  blob_sha TEXT NOT NULL,
  head_sha TEXT NOT NULL,
  PRIMARY KEY (branch, path)
);

CREATE TABLE IF NOT EXISTS seen_heads (
  branch   TEXT PRIMARY KEY,
  head_sha TEXT NOT NULL,
  author   TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS claims_fts USING fts5(text, content='claims', content_rowid='rowid');
CREATE TRIGGER IF NOT EXISTS claims_ai AFTER INSERT ON claims BEGIN
  INSERT INTO claims_fts(rowid, text) VALUES (new.rowid, new.text);
END;
CREATE TRIGGER IF NOT EXISTS claims_ad AFTER DELETE ON claims BEGIN
  INSERT INTO claims_fts(claims_fts, rowid, text) VALUES ('delete', old.rowid, old.text);
END;

CREATE TABLE IF NOT EXISTS journal (
  id          INTEGER PRIMARY KEY,
  ts          TEXT NOT NULL DEFAULT (datetime('now')),
  goal        TEXT NOT NULL,
  step        INTEGER NOT NULL,
  action      TEXT NOT NULL,
  verdict     TEXT NOT NULL,
  ok          INTEGER NOT NULL,
  observation TEXT NOT NULL,
  lesson      TEXT NOT NULL DEFAULT ''
);
