CREATE TABLE users (
  id SERIAL PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  role TEXT NOT NULL CHECK (role IN ('employee','manager','hr')),
  manager_id INT REFERENCES users(id),
  on_notice BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE TABLE documents (
  id SERIAL PRIMARY KEY,
  owner_id INT NOT NULL REFERENCES users(id),
  title TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  source_type TEXT NOT NULL,          -- doc | chat | transcript | mom
  content TEXT NOT NULL,
  created_at DATE NOT NULL DEFAULT CURRENT_DATE
);
CREATE TABLE chunks (
  id SERIAL PRIMARY KEY,
  doc_id INT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  owner_id INT NOT NULL REFERENCES users(id),   -- denormalised for fast ACL filter
  idx INT NOT NULL,
  text TEXT NOT NULL,
  embedding vector(768) NOT NULL
);
CREATE INDEX chunks_owner_idx ON chunks(owner_id);
CREATE TABLE transfers (
  id SERIAL PRIMARY KEY,
  from_id INT NOT NULL REFERENCES users(id),
  to_id INT NOT NULL REFERENCES users(id),
  created_by INT NOT NULL REFERENCES users(id),
  created_at TIMESTAMP NOT NULL DEFAULT NOW(),
  active BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE TABLE tasks (
  id SERIAL PRIMARY KEY,
  mom_doc_id INT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  assignee_id INT NOT NULL REFERENCES users(id),
  created_by INT NOT NULL REFERENCES users(id),
  due_date DATE,
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','done')),
  completed_at TIMESTAMP,
  completion_comment TEXT,
  completion_file_name TEXT,
  completion_file BYTEA,
  completion_doc_id INT REFERENCES documents(id) ON DELETE SET NULL
);
