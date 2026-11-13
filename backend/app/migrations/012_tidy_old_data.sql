-- Brings data saved by older versions up to the current shape, so the code no longer needs to convert it
-- every time it reads it.

-- Style guides made before the arms-and-hands rule: swap the old limbs phrase for it.
UPDATE style_guides
SET style_prefix = replace(style_prefix, 'thin black stick limbs',
    'thin black stick arms and legs that show as plain black lines wherever clothing does not cover them, '
    || 'with sleeves and trousers drawn as flat colored clothing over them, and simple round cartoon hands '
    || 'that are always the same color as the head, never black, unless a character''s look gives gloves or mittens')
WHERE instr(style_prefix, 'thin black stick limbs') > 0
  AND instr(style_prefix, 'thin black stick arms and legs') = 0;

-- Characters made before full looks only had a short marker: give them the look built from it.
UPDATE style_guides
SET characters = (
    SELECT json_group_array(json(CASE
        WHEN coalesce(json_extract(value, '$.look'), '') = ''
        THEN json_set(value, '$.look', 'stick figure, white head and hands, with ' || coalesce(json_extract(value, '$.marker'), ''))
        ELSE value END) ORDER BY key)
    FROM json_each(style_guides.characters))
WHERE EXISTS (SELECT 1 FROM json_each(style_guides.characters) WHERE coalesce(json_extract(value, '$.look'), '') = '');

-- Publishing packs made before Nov 2026 held three auto-suggested thumbnail prompts, which are no longer shown.
UPDATE publish_meta SET content = json_remove(content, '$.thumbnail_prompts')
WHERE json_extract(content, '$.thumbnail_prompts') IS NOT NULL;

-- Posting to social apps was removed on 2026-11-06; its table was never used after that.
DROP TABLE IF EXISTS social_posts;
