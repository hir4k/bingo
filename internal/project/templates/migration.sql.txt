-- +goose Up
CREATE TABLE todos (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 name TEXT NOT NULL,
 completed BOOLEAN NOT NULL DEFAULT FALSE,
 created_at DATETIME,
 updated_at DATETIME
);
INSERT INTO todos (name, completed, created_at, updated_at)
VALUES ('Learn Go templates', false, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
       ('Build with Bingo', true, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);

-- +goose Down
DROP TABLE todos;
