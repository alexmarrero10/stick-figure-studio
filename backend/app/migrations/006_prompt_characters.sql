-- Who is drawn in each image: a JSON list of {name, variant} picked from the style guide's
-- characters before the prompt is written, so the prompt repeats their exact look. NULL for
-- prompts written before casting existed.
ALTER TABLE image_prompts ADD COLUMN characters TEXT;
