-- Add support for reversible like action in reader UI.
ALTER TYPE event_type_enum ADD VALUE IF NOT EXISTS 'unlike';
