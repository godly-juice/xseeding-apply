# xseeding-apply - the "apply to join" door, in the open

This is the exact code behind **https://apply.xseed.ing** - how people apply to join the xSeeding team (Lumi, a local AI, and xOS, its own
operating system on its own compiled kernel), what we look for, what we store, and what the AI is allowed to read. It is public so there is no
confusion about any of it.

## What we look for

- **People who ship.** Something you made that works. Size does not matter; finished does.
- **Picky testers.** You notice the cut-off label, the button that does nothing, the step a stranger gets stuck on.
- **Clear writers.** You can explain a thing in plain words to someone who is lost.
- **Local-first, privacy-first.** You like AI that lives on the machine, not in someone's cloud.
- **Honest about what you know.** "I don't know yet, but I'll find out" is a great answer.

No CV needed. Show us a thing.

## What happens when someone applies

1. `server.py` takes the form (name/handle, how to reach you, your text, links, handles, up to 5 files) and stores it in `data/<id>/`
   with `consent.json`: the exact wording of every source they ticked, when, and a delete token.
2. The applicant gets a **delete link** at once. It removes everything, no questions.
3. `lumi_research.py` (a loop on the same machine) reads **only the ticked sources** and asks a local model (nothing leaves the machine)
   for a first summary: strengths with their source, what they could own, questions to ask, doubts the material actually shows, confidence.
   Ticking nothing is fine: a human reads every application anyway.
4. A human reads the application and the summary. The summary is never a decision.
5. Applications are deleted after `keep_days` (90) unless the person joined.

## The sources - the full list, nothing else is ever opened

| Ticked | What is read |
|---|---|
| links | the pages they linked, public text only (10 pages, 6k chars each) |
| github | GitHub's public API: profile, 30 public repos, README of the top 5 |
| web | one web search on the name + handles; the public result pages |
| files | the uploaded files as text (PDF, txt/md, docx; images are listed, not read) |
| google | Google Drive **read-only** (names of 40 recent files + the text of up to 8 Google Docs) - only after they click Connect, revocable in their Google account |

No logging in as the person, no private messages, no friends lists, no data bought from anyone.

## Run it yourself

Python 3.13+, standard library only (`pypdf` optional for PDFs).

```
python server.py                # 127.0.0.1:11594 - put a reverse proxy / tunnel in front for the public routes only
python lumi_research.py         # the research loop (needs an OpenAI-style local chat server at WRITER)
```
Config file (path in `server.py`): `public_url`, `contact_email`, `keep_days`, `google_client_id`, `google_client_secret` (Google OAuth, Web
application, redirect `<public_url>/google/callback`, scope `drive.readonly` - the Connect button only appears when both are set), `copy_dir`.

Public routes: `/`, `/privacy`, `/static/*`, `/api/config`, `POST /api/apply`, `/delete/<id>/<token>`, `/google/start`, `/google/callback`.
`/admin` answers only on 127.0.0.1 (never through the tunnel). Honeypot field, 10 applications per address per day, file type allow-list.

## Privacy page

`static/privacy.html` is what applicants read. Written to be clear and lawful for a small team; if the law where you live gives you more rights,
you have them here too.

MIT licence.
