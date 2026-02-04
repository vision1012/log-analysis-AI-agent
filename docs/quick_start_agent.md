# Quick Start: AI Agent Implementation

## Immediate Next Steps (This Week)

### Step 1: Setup Environment (30 minutes)

1. **Install Dependencies**
```bash
pip install openai langchain langchain-openai chromadb sentence-transformers
```

2. **Set API Key**
```bash
export OPENAI_API_KEY="your-api-key-here"
# OR create .env file
echo "OPENAI_API_KEY=your-api-key-here" > .env
```

3. **Create Requirements File**
```bash
# Add to requirements.txt
openai>=1.0.0
langchain>=0.1.0
langchain-openai>=0.1.0
chromadb>=0.4.0
sentence-transformers>=2.2.0
python-dotenv>=1.0.0
```

### Step 2: Implement LLM Client (1-2 hours)

Create `agent/llm_client.py`:

```python
import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

class LLMClient:
    def __init__(self, model: str = "gpt-4"):
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.model = model
    
    def chat(self, messages, tools=None):
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=tools,
            tool_choice="auto"
        )
        return response
```

### Step 3: Define Tools (2-3 hours)

Create `agent/tools.py` with tool definitions for all 8 `run_*()` functions.

### Step 4: Basic Agent (3-4 hours)

Implement basic agent in `agent/agent_core.py` that can:
- Accept natural language queries
- Select appropriate tools
- Execute tools
- Return responses

### Step 5: Test (1 hour)

Test with simple queries like:
- "Find all errors in app.log"
- "Summarize the log file"
- "Filter ERROR logs from the last hour"

---

## MVP Checklist

- [ ] LLM client setup
- [ ] Tool definitions for all 8 functions
- [ ] Basic agent implementation
- [ ] Simple query processing
- [ ] Error handling
- [ ] Basic testing

---

## Step 6 Verification Commands

After running a job, verify that Step 6 rules are enforced by checking the job directory structure and validating invariants.

### Running a Job

```bash
# Run a job with heuristic planning
python scripts/run_job.py --file data/sample.log --query "Summarize errors"

# Run a job with LLM planning (requires LLAMA_API_KEY and LLAMA_BASE_URL)
python scripts/run_job.py --file data/sample.log --query "Analyze this log" --mode llm
```

### Required Directory Structure

After job execution, the following structure must exist:

```
output/jobs/<job_id>/
├── job.json                    # Authoritative job state snapshot
├── artifacts/                  # All tool-generated artifacts
│   └── <artifact_files>
├── tool_results/               # Individual tool result JSON files
│   ├── 000_<tool_name>.json
│   ├── 001_<tool_name>.json
│   └── ...
└── inputs/                     # Copied input files
    └── <input_file>
```

### Verification Commands

```bash
# Check job directory exists
ls -la output/jobs/<job_id>/

# Verify job.json exists and is valid JSON
cat output/jobs/<job_id>/job.json | python -m json.tool

# Verify artifacts directory exists
ls -la output/jobs/<job_id>/artifacts/

# Verify tool_results directory exists
ls -la output/jobs/<job_id>/tool_results/

# Verify no files created in root output/ (except output/jobs/)
ls output/ | grep -v jobs
```

### Step 6 Invariants

The following invariants must always hold:

1. **Validated Tool Results Only**
   - All `tool_results` entries validate against the `ToolResult` Pydantic schema
   - Every tool result has required fields: `tool`, `status`, `input`, `summary`, `data`, `artifacts`, `warnings`, `errors`
   - Tool results are persisted as JSON files in `tool_results/` directory

2. **No Root Output Writes**
   - No files are created directly under `output/` during job execution
   - All artifacts must be under `output/jobs/<job_id>/artifacts/`
   - All tool result files must be under `output/jobs/<job_id>/tool_results/`
   - Input files are copied to `output/jobs/<job_id>/inputs/`

3. **No Crash Guarantee**
   - `run_job()` always returns a valid `JobResult`, never raises exceptions
   - Tool failures result in `status="error"` ToolResult dicts, not crashes
   - Job continues execution even when individual tools fail
   - All exceptions are caught and converted to `JobResult.errors` or `ToolResult.errors`

### Running Verification Tests

```bash
# Run artifact paths contract tests
python -m unittest code_testing.test_artifact_paths_contract -v

# Run worker never crashes tests
python -m unittest code_testing.test_worker_never_crashes -v

# Run schema contract tests
python -m unittest code_testing.test_schema_contract -v
```

### Expected Output

When running a job successfully, you should see:

```
======================================================================
JOB RESULT
======================================================================
Job ID: <job_id>
Status: succeeded

Directory Paths:
  Job Directory:      /absolute/path/to/output/jobs/<job_id>
  Artifacts Directory: /absolute/path/to/output/jobs/<job_id>/artifacts
  Tool Results Dir:   /absolute/path/to/output/jobs/<job_id>/tool_results

Final Answer:
----------------------------------------------------------------------
[Answer content...]

Generated Artifacts:
  - <artifact_name>: <artifact_path>

Duration: <duration>ms

Full job state saved to: /absolute/path/to/output/jobs/<job_id>/job.json
```

### Troubleshooting

If verification fails:

1. **Missing directories**: Check that `create_job_context()` is called in `worker.py`
2. **Files in root output/**: Verify `ToolExecutor` injects `output_dir` from `JobContext`
3. **Uncaught exceptions**: Ensure all exceptions are caught in `run_job()` and converted to `JobResult.errors`
4. **Invalid tool results**: Verify `validate_tool_result()` is called for all tool outputs

---

## Full Roadmap

See `docs/ai_agent_implementation_roadmap.md` for complete implementation plan.
