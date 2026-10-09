govintel-ai-pitch-engine/
│
├── .claude/                        # Claude-specific local workspace folder
│   └── skills/                     # Location for automated CLI tools/scripts
│
├── references/                     # 📘 BLUEPRINTS LAYER (B) - Static domain data
│   ├── naics_matrix.json           # NAICS codes mapped to bottlenecks & on-prem solutions
│   └── copywriting_rules.md        # Rigid formatting rules, channel routing, & banned words
│
├── scripts/                        # 🛠️ SOLUTIONS LAYER (S) - Deterministic execution scripts
│   ├── orchestrator.py             # Main entry point that loops through the CSV rows
│   └── mine_reviews.py             # Scraper script to gather Google reviews & web footprints
│
├── .env.example                    # Sample environment variables file (API keys)
├── .gitignore                      # Git configuration to ignore credentials and output folders
├── CLAUDE.md                       # 🎯 DIRECTION LAYER (D) - Master instructions for your AI agent
├── README.md                       # High-level setup, usage guide, and quick-start workflow
│
├── leads.csv                       # 📥 INPUT: Raw SAM.gov lead export file (Drop your export here)
└── output_pitches.csv              # 📤 OUTPUT: The final system-generated outreach script file


govintel-ai-pitch-engine/
├── .claude/                        
│   └── skills/                     
│       └── govintel-pitcher/       <-- The new skill folder
│           ├── SKILL.md            <-- REQUIRED: Exact name & uppercase
│           ├── naics_matrix.json   <-- Relocated inside the skill directory
│           └── copywriting_rules.md<-- Relocated inside the skill directory
├── scripts/                        
│   └── orchestrator.py             
├── README.md                       
├── CLAUDE.md                       
└── leads.csv                       

