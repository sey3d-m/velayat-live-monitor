# Velayat Live Monitor — Production v2

## Changes in v2

The report is now content-first and includes:

- Jalali program date
- Program name
- Expert name
- Main topic
- Full content summary
- Main content axes
- Every audience question that received an answer
- A concise summary of the expert's answer to each audience question
- Phone question count
- Message/SMS question count
- Unknown-source audience question count
- Total answered audience questions
- Audience names only when explicitly mentioned in the program

The report does not create a "doubts / shobohat" section.

## Official Tehran schedule

Saturday through Thursday:

- 18:00–19:00
- 19:30–20:30
- 21:00–22:00

The workflow is scheduled at the official start time, not before it.
GitHub Actions can still queue scheduled jobs for a short period during high load.

## Upload

Repository root:
- `velayat_monitor.py`
- `requirements.txt`

Workflow path:
- `.github/workflows/velayat-monitor.yml`

Replace the previous production files with these versions.
