# INSTALL — What to Install & Which Accounts to Make

**Temporary setup file.** Do this once, before the project starts.
**Everything here is free. Nothing asks for payment.**

👉 **All 3 members (Hassan, Mudassar, Ifraz) must do PART 1 and PART 2.**
👉 **Only Hassan** does the extra items marked 🟡.

---

# PART 1 — Software to Install

Do these in order. Restart your laptop after finishing all of them.

---

### 1. Python 3.11 ⭐ most important

- Go to **https://www.python.org/downloads/release/python-3119/**
- Scroll down → click **"Windows installer (64-bit)"**
- Run the file
- ⚠️ **TICK THE BOX "Add python.exe to PATH"** at the bottom of the first screen
- Click "Install Now"

**Check it worked** — open Command Prompt and type:
```
python --version
```
You should see `Python 3.11.9`

> ❗ Do **not** install Python 3.13. Some of our libraries don't support it yet.

---

### 2. Git

- Go to **https://git-scm.com/download/win**
- Download and run
- Keep clicking "Next" — all the default options are fine

**Check:**
```
git --version
```

**Then set your name once:**
```
git config --global user.name "Your Name"
git config --global user.email "your@email.com"
```

---

### 3. VS Code (our code editor)

- Go to **https://code.visualstudio.com/**
- Download and install

**Then install these extensions** (click the blocks icon on the left sidebar, search each name, click Install):
- `Python` (by Microsoft)
- `Pylance`
- `Docker`
- `GitLens`
- `Jupyter`
- `YAML`

---

### 4. Docker Desktop

- Go to **https://www.docker.com/products/docker-desktop/**
- Download "Docker Desktop for Windows"
- Install it
- It may ask to install **WSL 2** — say yes and let it do it
- **Restart your laptop**
- Open Docker Desktop and leave it running

**Check:**
```
docker --version
```

> ⚠️ Docker needs about 4 GB of RAM to run comfortably. If your laptop has 8 GB total, close Chrome while using it.

---

### 5. Node.js 🟡 (Hassan only — for React)

- Go to **https://nodejs.org/**
- Download the **LTS** version (the green button on the left)
- Install with default options

**Check:**
```
node --version
npm --version
```

---

### 6. Minikube + kubectl (for Kubernetes)

Open **PowerShell as Administrator** and run:
```
winget install Kubernetes.minikube
winget install Kubernetes.kubectl
```

**Check:**
```
minikube version
kubectl version --client
```

> You can install this later (around Step 18 of the roadmap). It's not needed on day 1.

---

### 7. Python libraries

Open Command Prompt inside the project folder and run:

```
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
```

Then install everything:
```
pip install pandas numpy pyarrow requests python-dotenv pyyaml
pip install scikit-learn xgboost lightgbm
pip install mlflow dvc[s3] dagshub
pip install flask gunicorn flask-cors prometheus-flask-exporter
pip install pandera evidently feast
pip install pytest pytest-cov ruff pre-commit
```

> 💡 You'll see `(.venv)` at the start of your command line. That means it's working.
> You must run `.venv\Scripts\activate` **every time** you open a new terminal.

Install these two **separately** (they're heavy and can conflict):
```
pip install apache-airflow
pip install kfp
```

---

### 8. Optional but helpful

| Software | Why | Link |
|---|---|---|
| **Postman** | Test our API with clicks instead of commands | https://www.postman.com/downloads/ |
| **DBeaver** | Look inside the database | https://dbeaver.io/download/ |
| **draw.io** | Draw the architecture diagram (needed for the report) | https://app.diagrams.net/ (works in browser, no install) |
| **OBS Studio** | Record demo videos as backup | https://obsproject.com/ |

---

# PART 2 — Accounts to Create

All free. Sign in with your **Google account** wherever possible — it's faster.

---

### 1. GitHub ⭐ (all 3 members)

- Go to **https://github.com/signup**
- Make an account with your email
- 🟡 **Hassan:** create the repository
  - Click **+** (top right) → **New repository**
  - Name: `Pakistan-AirWatch-AI`
  - Set it to **Public** (this gives us unlimited free GitHub Actions minutes)
  - Create
  - Then: **Settings → Collaborators → Add people** → add Mudassar and Ifraz

**Also:** 🟡 Hassan applies for **GitHub Student Developer Pack** (free, gives extra benefits):
- **https://education.github.com/pack**
- Upload your student ID or university email

---

### 2. DagsHub ⭐⭐ (all 3 members) — this is our shared MLflow server

This is the most important account. It gives us a **free MLflow server** that all three of us log into, plus free storage for our data.

- Go to **https://dagshub.com/user/sign_up**
- Click **"Sign in with GitHub"** (easiest)
- 🟡 **Hassan:** connect our repo
  - Click **Create** → **New Repository** → **Connect A Repository**
  - Choose GitHub → pick `Pakistan-AirWatch-AI`
  - Then **Settings → Collaborators** → add Mudassar and Ifraz

**Then every member gets their own token:**
- Click your profile picture (top right) → **Settings** → **Tokens**
- Click **Generate new token**
- Copy it and save it somewhere safe — you cannot see it again

> ⚠️ Never share your token with anyone. Each person uses their own.

**Where to find the connection details:**
- Open the repo page on DagsHub → click the green **Remote** button
- There are tabs for **DVC** and **MLflow** — copy the values from there into your `.env` file

---

### 3. OpenAQ API Key (all 3, or just Hassan shares the setup)

Gives us real sensor readings from Pakistani monitoring stations.

- Go to **https://explore.openaq.org/register**
- Register with your email
- Confirm the email
- Log in → go to your account page → copy your **API key**

**Free limits:** plenty for us. No card needed.

---

### 4. Open-Meteo — ❌ NO ACCOUNT NEEDED 🎉

This is our **main data source** (12 years of hourly air quality + weather for all cities).

- **No sign-up. No API key. No credit card. Nothing.**
- Just call the URL directly:
  ```
  https://air-quality-api.open-meteo.com/v1/air-quality?latitude=31.52&longitude=74.36&hourly=pm2_5
  ```
- Free for non-commercial use. We only have to write a credit line in our README.

---

### 5. Oracle Cloud Always Free 🟡 (Hassan only) — where we deploy

This replaces AWS. **Free forever**, not a trial.

- Go to **https://signup.cloud.oracle.com/**
- Sign up
- ⚠️ It will ask for a **credit/debit card** — this is only for identity verification. **It never charges you** as long as you stay on "Always Free" resources.
- Choose a **home region near Pakistan** (e.g. Mumbai or Singapore) — you cannot change this later
- Wait for the account to be ready (can take 10–30 minutes)

**What we get free forever:**
- A real Linux server (up to 4 CPU cores + 24 GB RAM, ARM)
- 200 GB storage
- Object storage (like AWS S3)
- Logging & monitoring (like AWS CloudWatch)

> ⚠️ **Rule:** only create resources that say **"Always Free eligible"**. If it doesn't have that label, don't create it.

---

### 6. Hugging Face 🟡 (Hassan only) — our backup deployment

Use this if Oracle Cloud gives any trouble. **No credit card at all.**

- Go to **https://huggingface.co/join**
- Sign up with email or GitHub
- That's it for now — we create the "Space" later when deploying

---

### 7. Grafana Cloud (optional backup)

We will mostly run Grafana ourselves in Docker (free). This is only a backup.

- **https://grafana.com/auth/sign-up/create-user**
- Free tier, no card needed

---

# PART 3 — Quick Summary Table

### Software

| # | Software | Who | Needed from day 1? |
|---|---|---|---|
| 1 | Python 3.11 | All 3 | ✅ Yes |
| 2 | Git | All 3 | ✅ Yes |
| 3 | VS Code | All 3 | ✅ Yes |
| 4 | Docker Desktop | All 3 | ✅ Yes |
| 5 | Node.js | 🟡 Hassan | Later |
| 6 | Minikube + kubectl | All 3 | Later |
| 7 | Python libraries (pip) | All 3 | ✅ Yes |
| 8 | Postman / DBeaver / draw.io | Optional | Later |

### Accounts

| # | Platform | Link | Card needed? | Who |
|---|---|---|---|---|
| 1 | GitHub | github.com/signup | ❌ No | All 3 |
| 2 | **DagsHub** ⭐ | dagshub.com/user/sign_up | ❌ No | All 3 |
| 3 | OpenAQ | explore.openaq.org/register | ❌ No | All 3 |
| 4 | Open-Meteo | — **no account at all** — | ❌ No | — |
| 5 | Oracle Cloud | signup.cloud.oracle.com | ⚠️ Card for ID only, never charged | 🟡 Hassan |
| 6 | Hugging Face | huggingface.co/join | ❌ No | 🟡 Hassan |
| 7 | Grafana Cloud | grafana.com (optional) | ❌ No | 🟡 Hassan |

### Things that come with Docker — don't install separately

These all run inside Docker, so **do not download them**:
- PostgreSQL / PostGIS
- MLflow server (we use DagsHub's anyway)
- Prometheus
- Grafana
- Apache Airflow
- Kubeflow

---

# PART 4 — After Installing: Your Secrets File

Make a file called `.env` in the project folder. Fill in your **own** values:

```
MLFLOW_TRACKING_URI=https://dagshub.com/<owner>/Pakistan-AirWatch-AI.mlflow
MLFLOW_TRACKING_USERNAME=your-dagshub-username
MLFLOW_TRACKING_PASSWORD=your-dagshub-token
DAGSHUB_USER_TOKEN=your-dagshub-token
OPENAQ_API_KEY=your-openaq-key
POSTGRES_USER=airwatch
POSTGRES_PASSWORD=pick-any-password
POSTGRES_DB=airwatch
```

### 🚨 THE MOST IMPORTANT RULE OF THE WHOLE PROJECT

**`.env` must NEVER go to GitHub.**

Make sure the file `.gitignore` contains this line:
```
.env
```

If a token ever reaches GitHub:
1. Go to DagsHub → Settings → Tokens → **delete that token immediately**
2. Make a new one
3. Then worry about cleaning the git history

---

# PART 5 — Final Check

Run these one by one. All should print a version number:

```
python --version
pip --version
git --version
docker --version
node --version
minikube version
kubectl version --client
```

Then test the virtual environment:
```
.venv\Scripts\activate
python -c "import pandas, xgboost, mlflow, flask; print('All good!')"
```

If you see **"All good!"** — you're ready. ✅

---

# Common Problems

| Problem | Fix |
|---|---|
| `'python' is not recognized` | You forgot to tick "Add to PATH". Uninstall Python and reinstall with the box ticked. |
| `'docker' is not recognized` | Open Docker Desktop first and wait for it to say "Running". Then restart your terminal. |
| Docker won't start | Turn on virtualization in BIOS, and enable WSL2 in Windows Features. |
| `pip install` fails on xgboost | Install Microsoft C++ Build Tools: https://visualstudio.microsoft.com/visual-cpp-build-tools/ |
| `(.venv)` is missing from my terminal | Run `.venv\Scripts\activate` again — you must do this in every new terminal. |
| Oracle Cloud rejects my card | Try a different card, or just use Hugging Face Spaces instead (no card needed). |

---

**Next step after finishing this file:** open `SIMPLE_ROADMAP.md` and start at **Step 3 (Create the project on GitHub)**.
