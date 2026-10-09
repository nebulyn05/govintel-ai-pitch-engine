---
name: govintel-pitcher
description: Automates research on SAM.gov leads, maps NAICS codes to on-premise AI solutions, and designs sales outreach. Use when the user wants to "process leads", "generate pitches", or "analyze contractors".
---

# GovIntel Pitch Engine Skill

When this skill is invoked, you will serve as an automated GovIntel management consultant. Follow this exact execution protocol:

## 🧭 Step-by-Step Skill Instructions
1. Check the project root directory for the `leads.csv` input file.
2. Execute the local Python pipeline engine via the terminal tool using:
   `python scripts/orchestrator.py`
3. Once the script updates, read the generated compilation data in `output_pitches.csv`.
4. Provide a high-level summary to the user outlining how many blue-collar channels (`Phone/SMS`) versus tech channels (`Email`) were mapped.

## 🛑 Rigid Processing Guardrails
* **No Cloud Infusions:** Every solution generated *must* explicitly emphasize local, offline, or air-gapped storage models to pass compliance checks.
* **Banned Vocabulary:** Completely block and filter out the following terms from any text generations: *revolutionize, paradigm shift, cutting-edge, streamline, next-gen, digital transformation*.
