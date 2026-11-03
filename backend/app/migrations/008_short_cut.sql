-- Where the Short ends (seconds), chosen once per voice-over at the cliffhanger sentence that ends
-- between shorts.min_seconds and shorts.max_seconds. cut_key identifies the narration it was chosen
-- for, so a new voice-over picks again.
ALTER TABLE shorts ADD COLUMN cut_s REAL;
ALTER TABLE shorts ADD COLUMN cut_key TEXT;
