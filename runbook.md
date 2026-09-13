# Running the prototype

Order matters. The toolbox has to be up before the agents start, because each
agent loads its toolset at import time.

## 1. Database

Create a Cloud SQL for MySQL instance with a public IP, a database called
`bank` and a user you can connect with. Load both schema files:

    mysql -h $MYSQL_HOST -u $MYSQL_USER -p bank < docs/deposit.sql
    mysql -h $MYSQL_HOST -u $MYSQL_USER -p bank < docs/loan.sql

Authorise your own IP on the instance, otherwise the toolbox cannot connect.

## 2. Cloud Storage

Create a bucket and upload the two PDFs:

    gsutil cp docs/loan-policy.pdf docs/loan-customer-info.pdf gs://YOUR_BUCKET/

Put the bucket name in `GCS_BUCKET`. Authenticate with
`gcloud auth application-default login` so the storage client can read it.

## 3. Toolbox

    export $(grep -v '^#' .env | xargs)
    ./toolbox --tools-files deposit/tools.yaml --tools-files loan/tools.yaml

It listens on port 5000 by default. If you move it, update `TOOLBOX_URL`.

## 4. Agents

In a second terminal, from the `starter` folder:

    source .venv/bin/activate
    export $(grep -v '^#' .env | xargs)
    adk web --a2a

Open the URL it prints. The dropdown at the top left switches between
`deposit`, `loan` and `manager`.

## 5. Checks

    python ../testing/bin/a2a.py --url http://localhost:8000/a2a/deposit --card
    python ../testing/bin/a2a.py --url http://localhost:8000/a2a/deposit --prompt "How much is in my vacation account?"
    python ../testing/bin/a2a.py --url http://localhost:8000/a2a/deposit --prompt "How much do I have in total?"

The third one should refuse.

## 6. Test run

Restart the agents first, so no earlier sessions are still in memory.

    python ../testing/bin/a2a.py --in ../testing/test_scenarios.csv --out test_results

## Running the agents on separate ports

Start three processes, each pointed at a folder, for example port 8000 for
deposit, 8001 for loan and 8002 for manager. Then update the `url` field in
each `agent.json` and the `DEPOSIT_AGENT_URL` and `LOAN_AGENT_URL` values in
`.env` to match, since that is how the loan and manager agents find their
peers.