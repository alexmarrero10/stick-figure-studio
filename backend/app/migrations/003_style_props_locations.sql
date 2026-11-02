-- Recurring objects and places, each with one fixed look repeated word for word in every prompt.
ALTER TABLE style_guides ADD COLUMN props TEXT NOT NULL DEFAULT '[]';      -- JSON list of {name, look}
ALTER TABLE style_guides ADD COLUMN locations TEXT NOT NULL DEFAULT '[]';  -- JSON list of {name, look}
