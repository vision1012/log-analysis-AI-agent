# log-analysis-AI-agent
**Genz Developers:**  
- Jay Paun  
- Preet Patel  

## Features
- ErrorSplitter  
- LogSummary  
- StackTrace  
- error_lines  
- search_on_keyword  
- time slicing  
- root-cause extraction  



log-analysis-ai-agent/
│
├── agent/
│   ├── agent_core.py
│   ├── tools.py      ← your utilities wrapped as tools
│   ├── reasoning.py
│
├── utilities/
│   ├── error_splitter.py
│   ├── log_summary.py
│   ├── stacktrace.py
│   ├── search_on_keyword.py
│   ├── error_lines.py
│   ├── time_slice.py
│
├── ui/
│   ├── app.py        ← Streamlit or FastAPI app
│
├── data/
│   ├── input/
│   ├── output/
│
└── README.md
