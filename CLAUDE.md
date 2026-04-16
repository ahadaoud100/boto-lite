# Project: Minimal AWS Facade
**Goal**: Build a zero-dependency (other than `boto3`) facade over AWS S3, Secrets Manager, and SQS. 

**Hard Constraints**:
- Python 3.10+ only.
- ZERO dependencies other than `boto3`. 
- Use `uv` for all dependency management (`uv init --lib`).
- Keep public API flat and strongly typed.
- Never publish to GitHub or PyPI without the exact user message: "RELEASE".

**Workflow Rules**:
- Always read `STATE.md` before starting work.
- Keep diffs minimal. Do not rewrite files unless necessary.
- If a test fails 3 times, stop and ask the user.
- Whenever you finish a task, or the user types "CHECKPOINT", you must update `STATE.md` with the current status, what works, what is broken, and the exact next step. Then, stop generating.
