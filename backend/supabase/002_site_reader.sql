-- A read-only database user for the public site, so the website can never change or delete anything.
-- Run once in the Supabase dashboard: SQL Editor -> New query -> paste -> replace the password -> Run.
--
-- Then the site connects with the Session pooler address, but with this user instead of "postgres":
--   postgresql://site_reader.<your-project-ref>:<the password below>@<pooler host>:5432/postgres
-- (copy the studio's SUPABASE_DB_URL and change only the user name and password).

do $$
begin
    if not exists (select 1 from pg_roles where rolname = 'site_reader') then
        create role site_reader login password 'CHANGE-ME-to-a-long-random-password';
    end if;
end $$;

grant usage on schema public to site_reader;
grant select on videos, video_chunks, documents, chunks, project_documents to site_reader;

-- Row level security is on for these tables; let the site user read every row (and nothing else).
drop policy if exists site_read on videos;
create policy site_read on videos for select to site_reader using (true);
drop policy if exists site_read on video_chunks;
create policy site_read on video_chunks for select to site_reader using (true);
drop policy if exists site_read on documents;
create policy site_read on documents for select to site_reader using (true);
drop policy if exists site_read on chunks;
create policy site_read on chunks for select to site_reader using (true);
drop policy if exists site_read on project_documents;
create policy site_read on project_documents for select to site_reader using (true);
