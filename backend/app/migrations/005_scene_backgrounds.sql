-- The old shared style asked for a "warm off-white paper background" in every image, which fought
-- scenes set at night or indoors (Flow sometimes drew a night raid on white). Give existing projects
-- the new wording: the background follows the scene's place, time of day and lighting.
UPDATE style_guides
SET style_prefix = replace(
    replace(style_prefix,
        'warm off-white paper background, flat colors used sparingly for props, clothing accents and simple backgrounds (',
        'flat colors for props, clothing and backgrounds ('),
    '). Uncluttered composition with one clear focal point',
    '). The background fills the whole frame and matches the scene''s place, time of day and lighting: night scenes are dark, indoor scenes show the room, never a blank white or paper background. Uncluttered composition with one clear focal point')
WHERE style_prefix LIKE '%warm off-white paper background, flat colors used sparingly%';
