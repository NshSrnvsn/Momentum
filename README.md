# Momentum - A Habit Tracker

A Streamlit application to record your habits daily and analyse weekly and monthly progress.

- Daily habit checklist with goal-aware sorting
- Calendar overview
- Weekly and monthly goal completion analysis
- Goal setting per habit

## Stack

- **Frontend / App**: [Streamlit](https://streamlit.io)
- **Database**: [Supabase](https://supabase.com) (Postgres)
- **Auth**: Supabase Auth

## Run locally

1. Create a Supabase project at [supabase.com](https://supabase.com) and run the following SQL in the project editor:

```sql
create table habits (
  id text primary key,
  name text not null,
  color text not null default '#2563eb',
  user_id uuid references auth.users(id) on delete cascade,
  created_at timestamptz default now()
);

create table checkins (
  id bigserial primary key,
  date text not null,
  habit_id text not null references habits(id) on delete cascade,
  progress integer not null default 0,
  note text not null default '',

```

3. Install dependencies and run:

```bash
pip install -r requirements.txt
streamlit run app.py
```

Then open `http://localhost:8501` in your browser.

## Deploy

Baked and ready at to use: https://moomentum.streamlit.app

To deploy your own instance, push to GitHub and connect at [share.streamlit.io](https://share.streamlit.io). 
Set the main file to `app.py` and add the three Supabase keys under App Settings → Secrets.

