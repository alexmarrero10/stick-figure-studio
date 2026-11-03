-- Which recurring objects (and which side of each) and which recurring place are in each image:
-- JSON {"objects": [{name, view}], "place": name}, picked with the cast so the prompt repeats their
-- exact looks. NULL for prompts written before this existed.
ALTER TABLE image_prompts ADD COLUMN things TEXT;
