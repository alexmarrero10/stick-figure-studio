-- Short image titles ("Victorian London street") used to number prompts so Flow's file names sort correctly.
ALTER TABLE image_prompts ADD COLUMN label TEXT NOT NULL DEFAULT '';

-- Batches the user has ticked off as created in Google Flow.
CREATE TABLE prompt_batches (
    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    batch_no    INTEGER NOT NULL,
    done        INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (project_id, batch_no)
);
