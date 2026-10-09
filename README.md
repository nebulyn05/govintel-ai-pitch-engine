# GovIntel AI Pitch Engine (SAM.gov Edition)

An advanced, automated B2B outbound engine designed specifically for the industrial, field services, and engineering sectors operating within the US Federal Contracting ecosystem. 

Powered by the **DBS (Direction, Blueprints, Solutions) Framework**, this repository converts raw **SAM.gov CSV data** into deep operational intelligence, matches government contractors with high-value on-premise AI utilities, and determines the perfect mobile or asynchronous sales script on autopilot.

## 🏗️ DBS Architecture Breakdown

This repository strictly follows the platform-agnostic **DBS Framework** to decouple execution layers and prevent monolithic context inflation:

*   **Direction (D):** Managed via `CLAUDE.md` and the master skill protocols. Defines the agentic logic trees, execution boundaries, and explicit workflow guardrails.
*   **Blueprints (B):** Managed via `/references/`. Houses static domain templates, regulatory boundaries (DFARS, CMMC, NIST), and zero-fluff blue-collar communication matrices.
*   **Solutions (S):** Managed via `/scripts/`. Deterministic Python scripts handling CSV data ingestion, Google Places review mining, and formatting outputs without LLM hallucination.

## 🚀 Quick Start (Using ChatGPT / Claude Code)

1. **Clone the Repository:**
   ```bash
   git clone https://github.com
   cd govintel-ai-pitch-engine
   ```

2. **Prepare Your Lead List:**
   * Export your target lead list from **SAM.gov** containing columns for Legal Business Name, Website, NAICS Code, Core Capabilities, Government Point of Contact (POC), Email, and Phone Number.
   * Drop the file into the project root directory and name it `leads.csv`.

3. **Install Dependencies:**
   ```bash
   pip install pandas beautifulsoup4 requests dotenv
   ```

4. **Execute Code Generation / Execution:**
   * Use **ChatGPT** to run the orchestration loop by giving it the context in `CLAUDE.md` and the reference files.
   * If running locally via **Claude Code CLI**, the `.claude/skills/` directory will automatically map the logic hooks.
