# 🚀 Log Analysis AI Agent  

An intelligent, end-to-end **AI-powered log analysis system** designed to streamline debugging, accelerate incident response, and extract actionable insights from complex logs..

---

## 👨‍💻 Genz Developers  
- **Jay Paun**  
- **Preet Patel**

---

## ✨ Key Features  

### 🔹 ErrorSplitter  
Automatically separates logs by error types for focused debugging.

### 🔹 LogSummary  
Generates concise, AI-driven summaries of long and noisy log files.

### 🔹 StackTrace Analyzer  
Simplifies and extracts stack traces for fast root-cause identification.

### 🔹 Error Line Detection (`error_lines`)  
Pinpoints critical failure lines in large logs.

### 🔹 Keyword-Based Log Search (`search_on_keyword`)  
Searches and highlights logs using specific keywords or patterns.

### 🔹 Time Slicing  
Analyzes log activity within selected time ranges.

### 🔹 Root-Cause Extraction  
Applies AI/ML logic to identify probable causes behind errors.

---

## 📂 Dataset Sources  

We use publicly available datasets for training and benchmarking:

- 🔗 https://github.com/logpai/loghub  
- 🔗 https://www.kaggle.com/datasets/ayenuryrr/loghub-hdfs-hadoop-distributed-file-system-data  

---

## 📂 Project Structure

```text
log-analysis-AI-agent/
├── 🤖 agent/
│   ├── agent_core.py        # Core agent orchestration
│   ├── reasoning.py         # Logic and reasoning modules
│   └── tools.py             # Utility tools for the agent
├── 💾 data/
│   ├── 📥 input/            # Directory for raw log files
│   └── 📤 output/           # Directory for analysis results
├── 🖥️ ui/
│   └── app.py               # Main application interface
├── ⚙️ utilities/
│   ├── error_lines.py       # Extract specific error lines
│   ├── error_splitter.py    # Split logs by error types
│   ├── log_summary.py       # Generate log summaries
│   ├── search_on_keyword.py # Keyword-based search
│   ├── stacktrace.py        # Stacktrace parsing and analysis
│   └── time_slice.py        # Filter logs by time windows
└── 📄 README.md             # Project documentation
```

## 🔮 Coming Soon  

- ReactJS-based Web UI  
- Automated pipeline for log ingestion  
- Real-time log monitoring system with alerts  
- LLM-enhanced advanced log reasoning  
- Visualization dashboard for anomalies  

---

## ⭐ Vision  

Logs are messy.  
Debugging is slow.  
Our goal: Make log analysis **smarter, faster, and fully automated** using AI.

